"""
Tracking for AI-generated clips.

An extension to the core spine in db.py, kept in its own module so it can
be removed cleanly if it does not earn its place.

Two tables:

    shots       - what the edit needed that the footage library did not have
    generations - each attempt at making it, and whether you kept the result

The measurement that matters is not "is the prompt good". It is **how many
attempts before a usable clip**. Generative video is a slot machine, and
attempts-to-keeper is the number that tells you whether a prompt change,
or a different tool, actually helped. A prompt that lands in 2 tries beats
one that lands in 9 no matter how it reads.

Same labelling pattern as pitch selection: you already decide keep or
discard. This records the decision instead of losing it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .db import DB_PATH, _now, connect
from .shot import TOOLS, Shot

# The generations-log vocabulary: every video tool from the Shot
# registry, plus the still-image connectors (midjourney.py,
# nano_banana.py) that log attempts here but never render a Shot --
# they must not join shot.PLATFORMS or they'd be offered as AI-shot
# video tools in concepts.
IMAGE_TOOLS = ("midjourney", "nano")
LOG_TOOLS = TOOLS + IMAGE_TOOLS

SCHEMA = """
CREATE TABLE IF NOT EXISTS shots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    idea_id     INTEGER REFERENCES ideas(id) ON DELETE SET NULL,
    slot_index  INTEGER,
    spec_json   TEXT    NOT NULL,
    subject     TEXT    NOT NULL,
    camera      TEXT,
    size        TEXT,
    duration_s  REAL,
    resolved    INTEGER NOT NULL DEFAULT 0,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS generations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shot_id     INTEGER NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL,
    tool        TEXT    NOT NULL,
    attempt     INTEGER NOT NULL,
    prompt      TEXT    NOT NULL,
    params_json TEXT,
    output_path TEXT,
    cost_usd    REAL,
    kept        INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_shots_idea      ON shots (idea_id);
CREATE INDEX IF NOT EXISTS idx_gen_shot        ON generations (shot_id);
CREATE INDEX IF NOT EXISTS idx_gen_tool_kept   ON generations (tool, kept);
"""


def init(path: Path | str = DB_PATH) -> None:
    """Create the generative tables. Run after db.init_db()."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def add_shot(
    shot: Shot,
    idea_id: Optional[int] = None,
    slot_index: Optional[int] = None,
    notes: Optional[str] = None,
    path: Path | str = DB_PATH,
) -> int:
    """
    Record a gap in the footage that a generated clip will fill.

    idea_id links it to the pitch it serves, slot_index to its position in
    that edit's cut list.
    """
    with connect(path) as conn:
        if idea_id is not None:
            if not conn.execute("SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone():
                raise ValueError(f"no idea with id {idea_id}")
        cur = conn.execute(
            """
            INSERT INTO shots
                (created_at, idea_id, slot_index, spec_json, subject,
                 camera, size, duration_s, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_now(), idea_id, slot_index, json.dumps(shot.as_dict()),
             shot.subject, shot.camera, shot.size, shot.duration_s, notes),
        )
        return int(cur.lastrowid)


def get_shot(shot_id: int, path: Path | str = DB_PATH) -> Optional[dict[str, Any]]:
    """Fetch a shot with its spec parsed back out."""
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM shots WHERE id = ?", (shot_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["spec"] = json.loads(data.pop("spec_json"))
    return data


def record_generation(
    shot_id: int,
    tool: str,
    prompt: str,
    params: Optional[dict] = None,
    output_path: Optional[str] = None,
    cost_usd: Optional[float] = None,
    notes: Optional[str] = None,
    path: Path | str = DB_PATH,
) -> int:
    """
    Log one attempt. Attempt number is assigned automatically, counting per
    shot and tool, so two runway attempts on the same shot coexist.
    """
    if tool not in LOG_TOOLS:
        raise ValueError(f"tool must be one of {LOG_TOOLS}, got {tool!r}")
    if not prompt.strip():
        raise ValueError("prompt cannot be empty")

    with connect(path) as conn:
        if not conn.execute("SELECT 1 FROM shots WHERE id = ?", (shot_id,)).fetchone():
            raise ValueError(f"no shot with id {shot_id}")
        prior = conn.execute(
            "SELECT COALESCE(MAX(attempt), 0) FROM generations "
            "WHERE shot_id = ? AND tool = ?",
            (shot_id, tool),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO generations
                (shot_id, created_at, tool, attempt, prompt, params_json,
                 output_path, cost_usd, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (shot_id, _now(), tool, prior + 1, prompt,
             json.dumps(params) if params else None,
             output_path, cost_usd, notes),
        )
        return int(cur.lastrowid)


def mark_kept(
    generation_id: int,
    output_path: Optional[str] = None,
    path: Path | str = DB_PATH,
) -> None:
    """
    The one you used. Marks its shot resolved.

    This is the label. Everything in tool_scoreboard and
    attempts_to_keeper depends on you calling it.
    """
    with connect(path) as conn:
        row = conn.execute(
            "SELECT shot_id FROM generations WHERE id = ?", (generation_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"no generation with id {generation_id}")
        conn.execute(
            "UPDATE generations SET kept = 1, output_path = COALESCE(?, output_path) "
            "WHERE id = ?",
            (output_path, generation_id),
        )
        conn.execute("UPDATE shots SET resolved = 1 WHERE id = ?", (row["shot_id"],))


def mark_rejected(
    generation_id: int,
    reason: str,
    path: Path | str = DB_PATH,
) -> None:
    """
    Why a take failed. Free text, but keep the vocabulary tight — "morphing
    hands", "wrong lighting", "camera ignored the move". Grouping these is
    how you learn which failure your prompts keep inviting.
    """
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE generations SET reject_reason = ? WHERE id = ?",
            (reason, generation_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no generation with id {generation_id}")


# --------------------------------------------------------------------------
# what this is all for
# --------------------------------------------------------------------------


def attempts_to_keeper(
    tool: Optional[str] = None,
    path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    """
    For each resolved shot, how many attempts it took on the tool that won.

    This is the headline number. Track it over time and a prompt change
    that drops the median from 6 to 3 is a measured improvement, not a
    feeling.
    """
    sql = """
        SELECT g.shot_id, s.subject, s.camera, s.size,
               g.tool, g.attempt AS attempts, g.cost_usd,
               (SELECT COUNT(*) FROM generations x
                 WHERE x.shot_id = g.shot_id) AS total_attempts_all_tools,
               (SELECT COALESCE(SUM(x.cost_usd), 0) FROM generations x
                 WHERE x.shot_id = g.shot_id) AS total_cost
        FROM generations g
        JOIN shots s ON s.id = g.shot_id
        WHERE g.kept = 1
        {tool_clause}
        ORDER BY g.shot_id
    """.format(tool_clause="AND g.tool = ?" if tool else "")
    params = (tool,) if tool else ()
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def tool_scoreboard(path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    """
    Per tool: attempts made, clips kept, hit rate, spend.

    Only counts shots where something was eventually kept, so a shot you
    abandoned entirely does not silently punish whichever tool you tried
    first.
    """
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT g.tool,
                   COUNT(*)                    AS attempts,
                   SUM(g.kept)                 AS kept,
                   COALESCE(SUM(g.cost_usd),0) AS spend
            FROM generations g
            WHERE g.shot_id IN (SELECT shot_id FROM generations WHERE kept = 1)
            GROUP BY g.tool
            ORDER BY g.tool
            """
        ).fetchall()
    out = []
    for r in rows:
        kept = r["kept"] or 0
        out.append({
            "tool": r["tool"],
            "attempts": r["attempts"],
            "kept": kept,
            "hit_rate": round(kept / r["attempts"], 3) if r["attempts"] else None,
            "spend": round(r["spend"], 2),
            "cost_per_keeper": round(r["spend"] / kept, 2) if kept else None,
        })
    return out


def failure_reasons(
    tool: Optional[str] = None,
    path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    """
    What goes wrong, grouped. Tells you which failure your prompts keep
    inviting, which is more actionable than a hit rate on its own.
    """
    sql = """
        SELECT reject_reason AS reason, COUNT(*) AS n
        FROM generations
        WHERE reject_reason IS NOT NULL {tool_clause}
        GROUP BY reject_reason
        ORDER BY n DESC
    """.format(tool_clause="AND tool = ?" if tool else "")
    params = (tool,) if tool else ()
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def winning_prompts(
    limit: int = 10,
    path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    """
    Prompts that produced a keeper, fewest attempts first.

    Feed these to the writer as examples. This is the retrieval step for
    generative prompts, and it works the same way as pulling past pitch
    picks — your own record, not general advice.
    """
    with connect(path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                """
                SELECT g.tool, g.attempt AS attempts, g.prompt,
                       s.subject, s.camera, s.size, s.spec_json
                FROM generations g
                JOIN shots s ON s.id = g.shot_id
                WHERE g.kept = 1
                ORDER BY g.attempt ASC, g.created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]


def open_shots(path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    """Shots with no keeper yet — the working queue."""
    with connect(path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                """
                SELECT s.*, COUNT(g.id) AS attempts_so_far
                FROM shots s
                LEFT JOIN generations g ON g.shot_id = s.id
                WHERE s.resolved = 0
                GROUP BY s.id
                ORDER BY s.created_at DESC
                """
            )
        ]


def summary(path: Path | str = DB_PATH) -> dict[str, int]:
    with connect(path) as conn:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("shots", "generations")
        }

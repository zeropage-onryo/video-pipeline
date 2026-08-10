"""
Autonomy bookkeeping for the content graph: which destination may post
on its own, what got parked instead of posted, and the one switch that
stops everything.

Same shape as preprod.py/entities.py: own SCHEMA, own init(), tables on
the shared pipeline DB through db.connect -- one SQLite file, not a
second store.

Four tables:
- channels     -- per-destination autonomy ("shadow" | "queue" | "auto")
                  and a hard posts/day rate cap. Autonomy is a property
                  of each destination, never a global flag: Zero Page
                  can run unattended while the personal account stays
                  gated. Promotion is a one-row change.
- hold_queue   -- the dead-man log. EVERY graph run ends here as a row:
                  held (with why) or posted (with what). If you want to
                  know what the graph did while you weren't looking,
                  it's one table.
- corrections  -- mid-run human notes, for the human_note interrupt
                  node when it lands. Written now so the schema exists.
- settings     -- key/value; the kill switch lives here. Global on
                  purpose: one place to pull the plug on every channel
                  at once.

Both channels seed as "shadow": nothing posts unattended on day one --
auto is earned by grading the evaluator against your own judgment, then
promoted with a one-row change.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    name       TEXT PRIMARY KEY,
    autonomy   TEXT NOT NULL DEFAULT 'shadow',   -- shadow | queue | auto
    rate_cap   INTEGER NOT NULL DEFAULT 1,       -- hard max posts/day
    notes      TEXT
);

CREATE TABLE IF NOT EXISTS hold_queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    channel    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'held',     -- held | approved | rejected | posted
    reason     TEXT,
    concept_id INTEGER,
    caption    TEXT,
    payload    TEXT                              -- JSON: prompts/clips/anything worth replaying
);
CREATE INDEX IF NOT EXISTS idx_hold_queue_status ON hold_queue (status);
CREATE INDEX IF NOT EXISTS idx_hold_queue_channel ON hold_queue (channel);

CREATE TABLE IF NOT EXISTS corrections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    run_id     TEXT,
    note       TEXT NOT NULL,
    consumed   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT
);

CREATE TABLE IF NOT EXISTS prompt_scores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    run_id        TEXT,
    prompt        TEXT,
    score         INTEGER,
    passed        INTEGER,
    reason        TEXT,
    dims          TEXT,           -- json {subject, camera, motion, lighting, coherence}
    human_verdict TEXT            -- 'post' | 'reject' | NULL, filled when the hold is graded
);
CREATE INDEX IF NOT EXISTS idx_prompt_scores_run ON prompt_scores (run_id);
"""

KILL_KEY = "kill_switch"

DEFAULT_CHANNELS = (
    ("zeropage", "shadow", 1, "the low-stakes sandbox; earns auto via the credit gate"),
    ("personal", "shadow", 1, "stays gated until Zero Page's track record covers it"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init(path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.executescript(SCHEMA)
        for name, autonomy, cap, notes in DEFAULT_CHANNELS:
            conn.execute(
                "INSERT OR IGNORE INTO channels (name, autonomy, rate_cap, notes) "
                "VALUES (?, ?, ?, ?)",
                (name, autonomy, cap, notes),
            )


# --- channels -------------------------------------------------------------

def get_channel(name: str, path=db.DB_PATH) -> Optional[dict]:
    with db.connect(path) as conn:
        row = conn.execute("SELECT * FROM channels WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None


def set_autonomy(name: str, autonomy: str, path=db.DB_PATH) -> None:
    """The promotion (or demotion): one row change, nothing else moves."""
    if autonomy not in ("shadow", "queue", "auto"):
        raise ValueError(f"autonomy must be shadow|queue|auto, got {autonomy!r}")
    with db.connect(path) as conn:
        conn.execute("UPDATE channels SET autonomy = ? WHERE name = ?", (autonomy, name))


def list_channels(path=db.DB_PATH) -> list[dict]:
    with db.connect(path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM channels ORDER BY name")]


# --- the kill switch ------------------------------------------------------

def kill(reason: str = "", path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (KILL_KEY, reason or "killed"),
        )


def unkill(path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (KILL_KEY,))


def killed(path=db.DB_PATH) -> bool:
    """True forces every run on every channel to hold. Also honours the
    ZEROPAGE_KILL env var so the plug can be pulled without a DB write."""
    import os
    if os.environ.get("ZEROPAGE_KILL"):
        return True
    with db.connect(path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (KILL_KEY,)).fetchone()
        return row is not None


# --- the hold queue / dead-man log ---------------------------------------

def to_hold(channel: str, reason: str, concept_id=None, caption: str = "",
            payload: Optional[dict] = None, status: str = "held",
            path=db.DB_PATH) -> int:
    with db.connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO hold_queue (created_at, channel, status, reason, "
            "concept_id, caption, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_now(), channel, status, reason, concept_id, caption,
             json.dumps(payload) if payload is not None else None),
        )
        return cursor.lastrowid


def list_hold(status: Optional[str] = "held", path=db.DB_PATH) -> list[dict]:
    query = "SELECT * FROM hold_queue"
    params: tuple = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY created_at DESC"
    with db.connect(path) as conn:
        rows = [dict(r) for r in conn.execute(query, params)]
    for row in rows:
        if row.get("payload"):
            try:
                row["payload"] = json.loads(row["payload"])
            except (ValueError, TypeError):
                pass
    return rows


def resolve_hold(hold_id: int, status: str, path=db.DB_PATH) -> None:
    """Your morning verdict on a shadow run: approved (would have
    posted) or rejected (glad it held). This is how the evaluator gets
    graded -- agreement over these rows is the number that earns auto."""
    if status not in ("approved", "rejected", "posted"):
        raise ValueError(f"status must be approved|rejected|posted, got {status!r}")
    with db.connect(path) as conn:
        conn.execute("UPDATE hold_queue SET status = ? WHERE id = ?", (status, hold_id))


def posts_today(channel: str, path=db.DB_PATH) -> int:
    """Posted rows for this channel since UTC midnight -- what the rate
    cap in the publish gate counts against."""
    today = datetime.now(timezone.utc).date().isoformat()
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM hold_queue "
            "WHERE channel = ? AND status = 'posted' AND created_at >= ?",
            (channel, today),
        ).fetchone()
        return row[0]


def evaluator_agreement(channel: Optional[str] = None, path=db.DB_PATH) -> dict:
    """The credit-gate number: of the shadow runs you've graded, how
    often would you have posted what the graph wanted to post? ~0.9
    over a real stretch is the doc's bar for promoting a channel."""
    query = ("SELECT status, COUNT(*) FROM hold_queue "
             "WHERE status IN ('approved', 'rejected')")
    params: tuple = ()
    if channel:
        query += " AND channel = ?"
        params = (channel,)
    query += " GROUP BY status"
    with db.connect(path) as conn:
        counts = dict(conn.execute(query, params).fetchall())
    graded = sum(counts.values())
    return {
        "graded": graded,
        "approved": counts.get("approved", 0),
        "agreement": round(counts.get("approved", 0) / graded, 3) if graded else None,
    }


# --- the prompt gate's log -------------------------------------------------

def log_prompt_scores(run_id, scored: list, path=db.DB_PATH) -> None:
    """One row per scored prompt per run -- the record the gate-vs-you
    agreement number is computed from. Logged before any credit could
    be spent, pass or fail."""
    with db.connect(path) as conn:
        for x in scored:
            conn.execute(
                "INSERT INTO prompt_scores (created_at, run_id, prompt, score, "
                "passed, reason, dims) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_now(), run_id, x.get("prompt"), x.get("score"),
                 int(bool(x.get("pass"))), x.get("reason"),
                 json.dumps(x.get("dims", {}))),
            )


def set_prompt_verdicts(run_id, verdict: str, path=db.DB_PATH) -> int:
    """Your /holds grade written next to the gate's: approved -> 'post',
    rejected -> 'reject'. Returns rows updated (0 when a run predates
    the gate or had no AI shots)."""
    if verdict not in ("post", "reject"):
        raise ValueError(f"verdict must be post|reject, got {verdict!r}")
    if not run_id:
        return 0
    with db.connect(path) as conn:
        cursor = conn.execute(
            "UPDATE prompt_scores SET human_verdict = ? WHERE run_id = ?",
            (verdict, run_id),
        )
        return cursor.rowcount


def prompt_gate_agreement(path=db.DB_PATH) -> dict:
    """Gate vs. you, over the graded rows: (passed AND you'd post) OR
    (held AND you'd reject). The two disagreement types cost
    differently -- passed-but-reject burns a credit, held-but-post only
    costs a manual approval -- so both are broken out."""
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*),"
            " SUM((passed = 1 AND human_verdict = 'post') OR"
            "     (passed = 0 AND human_verdict = 'reject')),"
            " SUM(passed = 1 AND human_verdict = 'reject'),"
            " SUM(passed = 0 AND human_verdict = 'post')"
            " FROM prompt_scores WHERE human_verdict IS NOT NULL"
        ).fetchone()
    graded, agreed, expensive, cheap = (row[0], row[1] or 0, row[2] or 0, row[3] or 0)
    return {
        "graded": graded,
        "agreement": round(agreed / graded, 3) if graded else None,
        "passed_but_rejected": expensive,   # would have burned a credit
        "held_but_posted": cheap,           # only cost an approval
    }


def first_try_pass_rate(path=db.DB_PATH) -> dict:
    """Purely descriptive: how often the gate lets a render through.
    Not the trust number -- that's prompt_gate_agreement."""
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*), SUM(passed) FROM prompt_scores"
        ).fetchone()
    total, passed = row[0], row[1] or 0
    return {"total": total, "passed": passed,
            "rate": round(passed / total, 3) if total else None}


# --- corrections (for the human_note interrupt, when it lands) ------------

def add_correction(note: str, run_id: Optional[str] = None, path=db.DB_PATH) -> int:
    with db.connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO corrections (created_at, run_id, note) VALUES (?, ?, ?)",
            (_now(), run_id, note),
        )
        return cursor.lastrowid


def pending_corrections(path=db.DB_PATH) -> list[dict]:
    with db.connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM corrections WHERE consumed = 0 ORDER BY created_at"
        )]


def consume_correction(correction_id: int, path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.execute("UPDATE corrections SET consumed = 1 WHERE id = ?", (correction_id,))

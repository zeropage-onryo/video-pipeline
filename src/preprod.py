"""
Pre-production: places you could shoot, and concepts you haven't shot.

Everything else in this pipeline starts from footage that already
exists -- manifest.json is a record of what was filmed. This module
covers the phase before that: photograph the spaces available to you,
have them described, and generate concepts grounded in those real
spaces rather than in a script written blind.

An extension to db.py in its own module, same as generative.py: own
SCHEMA, own init(), run after db.init_db().

`shot_done` is the label worth having. You generate several concepts
and go shoot some of them; that choice is ground truth about what's
actually worth making, in exactly the way ideas.selected is for
pitches, and it costs one column to keep.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .db import DB_PATH, _hash, _now, connect

BRANDS = ("antihero", "zeropage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    name        TEXT    NOT NULL UNIQUE,
    photo_count INTEGER,
    description_json TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS shoot_concepts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    brand       TEXT    NOT NULL,
    client      TEXT,
    spark       TEXT,
    title       TEXT    NOT NULL,
    hook        TEXT,
    logline     TEXT,
    duration    TEXT,
    shots_json  TEXT    NOT NULL,
    ai_json     TEXT,
    edit_note   TEXT,
    grade_note  TEXT,
    shot_done   INTEGER NOT NULL DEFAULT 0,
    prompt_hash TEXT,
    warnings_json TEXT,
    use_pov     INTEGER NOT NULL DEFAULT 1,
    notes       TEXT,
    judge_overall REAL,
    judge_taste   REAL,
    judge_perf    REAL,
    judge_reason  TEXT,
    format        TEXT,
    uncanny_overall REAL,
    uncanny_passed  INTEGER,
    uncanny_reason  TEXT
);

CREATE TABLE IF NOT EXISTS concept_locations (
    concept_id  INTEGER NOT NULL REFERENCES shoot_concepts(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    UNIQUE (concept_id, location_id)
);

CREATE TABLE IF NOT EXISTS scene_briefs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    brand      TEXT NOT NULL,
    spark      TEXT,
    title      TEXT NOT NULL,
    brief      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_concepts_shot ON shoot_concepts (shot_done);
CREATE INDEX IF NOT EXISTS idx_cl_concept    ON concept_locations (concept_id);
"""


def init(path: Path | str = DB_PATH) -> None:
    """Create the pre-production tables. Run after db.init_db()."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS won't add a column to a table that
        # already exists, so databases created before warnings_json need
        # it added explicitly.
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(shoot_concepts)")}
        if "warnings_json" not in existing:
            conn.execute("ALTER TABLE shoot_concepts ADD COLUMN warnings_json TEXT")
        if "use_pov" not in existing:
            conn.execute(
                "ALTER TABLE shoot_concepts ADD COLUMN use_pov INTEGER NOT NULL DEFAULT 1"
            )
        # taste + performance judge scores (BACKLOG #5), added later still
        for col in ("judge_overall REAL", "judge_taste REAL",
                    "judge_perf REAL", "judge_reason TEXT"):
            if col.split()[0] not in existing:
                conn.execute(f"ALTER TABLE shoot_concepts ADD COLUMN {col}")
        # Zero Page's on-brand (uncanny) gate: a fixed-rubric pass/fail that
        # decides whether a concept may auto-post. Separate from the taste
        # judge above (history-based ranking) -- this one gates. `format` is
        # the skeleton the concept rides (Zero Page).
        for col in ("format TEXT", "uncanny_overall REAL",
                    "uncanny_passed INTEGER", "uncanny_reason TEXT"):
            if col.split()[0] not in existing:
                conn.execute(f"ALTER TABLE shoot_concepts ADD COLUMN {col}")
        # the pick: which of the several scenes one idea produced is
        # worth rendering (see set_picked / pick_rate). Additive, so an
        # existing database gains it without touching a single row.
        if "picked_at" not in existing:
            conn.execute("ALTER TABLE shoot_concepts ADD COLUMN picked_at TEXT")
        # the board clears itself: a concept you resolved (picked and sent
        # to render, or passed over) stops being a card without stopping
        # being a row. The row is the label -- pick_rate needs the ones
        # you did NOT pick as much as the ones you did -- and it stays in
        # the Dev Studio's ungraded pool until it is graded. Archiving is
        # the board's memory, not the database's.
        if "archived_at" not in existing:
            conn.execute("ALTER TABLE shoot_concepts ADD COLUMN archived_at TEXT")


def save_judge_score(concept_id: int, judge: dict, path: Path | str = DB_PATH) -> None:
    """Store the taste + performance judge's verdict on a concept so the UI
    can show and rank by it. `judge` is taste_judge.score_concept()'s dict."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE shoot_concepts SET judge_overall=?, judge_taste=?, "
            "judge_perf=?, judge_reason=? WHERE id=?",
            (judge.get("overall"), judge.get("taste_fit"), judge.get("performance"),
             " · ".join(judge.get("reasons") or [])[:500], concept_id),
        )


def save_uncanny_score(concept_id: int, score: dict, path: Path | str = DB_PATH) -> None:
    """Store Zero Page's on-brand gate verdict on a concept so the UI can show
    the PASS/HOLD and autopilot can check it. `score` is
    uncanny_judge.score_concept()'s dict."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE shoot_concepts SET uncanny_overall=?, uncanny_passed=?, "
            "uncanny_reason=? WHERE id=?",
            (score.get("overall"), 1 if score.get("passed") else 0,
             " · ".join(score.get("reasons") or [])[:500], concept_id),
        )


def delete_concept(concept_id: int, path: Path | str = DB_PATH) -> None:
    """Discard a concept for good. concept_locations rows cascade via the
    FK (connect() sets PRAGMA foreign_keys=ON)."""
    with connect(path) as conn:
        conn.execute("DELETE FROM shoot_concepts WHERE id = ?", (concept_id,))


def delete_all_concepts(brand: Optional[str] = None, path: Path | str = DB_PATH) -> int:
    """Clear the concept slate -- all of it, or just one brand's. Returns
    how many were removed. concept_locations cascades via the FK."""
    with connect(path) as conn:
        if brand:
            cur = conn.execute("DELETE FROM shoot_concepts WHERE brand = ?", (brand,))
        else:
            cur = conn.execute("DELETE FROM shoot_concepts")
        return cur.rowcount


# --------------------------------------------------------------------------
# scene briefs -- one cohesive whole-scene prompt (the winning skeleton)
# --------------------------------------------------------------------------
def save_scene_brief(brand: str, title: str, brief: str,
                     spark: Optional[str] = None, path: Path | str = DB_PATH) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO scene_briefs (created_at, brand, spark, title, brief) "
            "VALUES (?, ?, ?, ?, ?)",
            (_now(), brand, (spark or "").strip() or None,
             (title or "Untitled scene").strip(), brief.strip()),
        )
        return int(cur.lastrowid)


def list_scene_briefs(brand: Optional[str] = None,
                      path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    sql = "SELECT * FROM scene_briefs"
    params: list[Any] = []
    if brand:
        sql += " WHERE brand = ?"
        params.append(brand)
    sql += " ORDER BY id DESC"
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def delete_scene_brief(brief_id: int, path: Path | str = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("DELETE FROM scene_briefs WHERE id = ?", (brief_id,))


# --------------------------------------------------------------------------
# locations
# --------------------------------------------------------------------------


def add_location(
    name: str,
    description: Optional[dict] = None,
    photo_count: Optional[int] = None,
    notes: Optional[str] = None,
    path: Path | str = DB_PATH,
) -> int:
    """
    Record (or re-record) a place you can shoot. Keyed by name, so
    re-describing a location after adding photos updates it instead of
    creating a second row -- names are how you refer to a space out
    loud, and two rows for one hallway would be a bug, not a feature.
    """
    if not name or not name.strip():
        raise ValueError("a location needs a name")
    name = name.strip()

    with connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO locations (created_at, name, photo_count, description_json, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET
                photo_count      = excluded.photo_count,
                description_json = excluded.description_json,
                notes            = COALESCE(excluded.notes, locations.notes)
            """,
            (_now(), name, photo_count,
             json.dumps(description) if description is not None else None, notes),
        )
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = conn.execute("SELECT id FROM locations WHERE name = ?", (name,)).fetchone()
        return int(row["id"])


def _location_row(row) -> dict[str, Any]:
    data = dict(row)
    raw = data.pop("description_json", None)
    data["description"] = json.loads(raw) if raw else None
    return data


def get_location(location_id: int, path: Path | str = DB_PATH) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    return _location_row(row) if row else None


def get_location_by_name(name: str, path: Path | str = DB_PATH) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM locations WHERE name = ?", (name,)).fetchone()
    return _location_row(row) if row else None


def list_locations(path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    with connect(path) as conn:
        return [
            _location_row(r)
            for r in conn.execute("SELECT * FROM locations ORDER BY name ASC")
        ]


# --------------------------------------------------------------------------
# concepts
# --------------------------------------------------------------------------


def save_concept(
    concept: dict,
    brand: str,
    client: Optional[str] = None,
    spark: Optional[str] = None,
    location_ids: Optional[list] = None,
    prompt_template: Optional[str] = None,
    warnings: Optional[list] = None,
    use_pov: bool = False,
    path: Path | str = DB_PATH,
) -> int:
    """
    Store one generated concept, warnings and all. Returns its id.

    Warnings are stored rather than just counted: a concept that broke a
    rule is worth looking at and deciding on, and a number in a flash
    message that disappears on the next page load is not "attached".

    prompt_template is hashed rather than stored, same as pitch_runs --
    enough to tell which prompt version produced which shoot rate,
    without keeping a copy of every prompt ever used.
    """
    title = (concept.get("title") or "").strip()
    if not title:
        raise ValueError("concept has no title")
    if brand not in BRANDS:
        raise ValueError(f"brand must be one of {BRANDS}, got {brand!r}")

    with connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO shoot_concepts
                (created_at, brand, client, spark, title, hook, logline,
                 duration, shots_json, ai_json, edit_note, grade_note, prompt_hash,
                 warnings_json, use_pov, format)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_now(), brand, client, spark, title,
             concept.get("hook"), concept.get("logline"), concept.get("duration"),
             json.dumps(concept.get("shots") or []),
             json.dumps(concept["ai"]) if concept.get("ai") else None,
             concept.get("edit"), concept.get("grade"), _hash(prompt_template),
             json.dumps(warnings) if warnings else None, 1 if use_pov else 0,
             concept.get("format")),
        )
        concept_id = int(cur.lastrowid)

        for location_id in location_ids or []:
            conn.execute(
                "INSERT OR IGNORE INTO concept_locations (concept_id, location_id) VALUES (?, ?)",
                (concept_id, location_id),
            )
        return concept_id


def _concept_row(row, conn) -> dict[str, Any]:
    data = dict(row)
    data["shots"] = json.loads(data.pop("shots_json") or "[]")
    ai_raw = data.pop("ai_json", None)
    data["ai"] = json.loads(ai_raw) if ai_raw else None
    warn_raw = data.pop("warnings_json", None)
    data["warnings"] = json.loads(warn_raw) if warn_raw else []
    # Derived, not stored: an idea that hasn't been planned yet simply
    # has no shots. Storing a flag as well would let the two disagree.
    data["has_shot_list"] = bool(data["shots"])
    # Derived the same way: the AI shots are the shots whose source says
    # so. Rows written before the de-cap carried one concept-level ai
    # dict instead -- surface it here too, so old concepts keep
    # rendering wherever ai_shots is read.
    data["ai_shots"] = [s for s in data["shots"] if s.get("source") == "AI"]
    if not data["ai_shots"] and data["ai"]:
        data["ai_shots"] = [data["ai"]]
    data["use_pov"] = bool(data.get("use_pov", 1))
    # Derived for the same reason: a concept IS one scene when it holds
    # exactly one shot, and it is picked when it carries a pick time.
    # Two stored flags could disagree with the rows they describe.
    data["is_scene"] = len(data["shots"]) == 1
    data["picked"] = bool(data.get("picked_at"))
    data["archived"] = bool(data.get("archived_at"))
    # graded is what finally retires an archived concept: the Dev
    # Studio's grade queue draws on judge_overall IS NULL, so a row
    # archived off the board is still waiting to teach something.
    data["graded"] = data.get("judge_overall") is not None
    # the reference photos this scene was written against, carried on
    # the shot itself -- shots_json was always one flexible JSON column,
    # so plural references cost no schema change
    data["refs"] = (data["shots"][0].get("refs") or []) if data["shots"] else []
    # parked: the chain got this scene as far as it can go without
    # spending, and it is sitting in the Queue. Stored on the shot
    # rather than derived from reference_image, which the Director
    # canvas also writes -- see set_shot_parked.
    first = data["shots"][0] if data["shots"] else {}
    data["parked"] = bool(first.get("parked_at"))
    data["park_reason"] = first.get("park_reason") or ""

    data["locations"] = [
        dict(r)
        for r in conn.execute(
            """
            SELECT l.id, l.name FROM locations l
            JOIN concept_locations cl ON cl.location_id = l.id
            WHERE cl.concept_id = ?
            ORDER BY l.name
            """,
            (data["id"],),
        )
    ]
    return data


def get_concept(concept_id: int, path: Path | str = DB_PATH) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM shoot_concepts WHERE id = ?", (concept_id,)
        ).fetchone()
        return _concept_row(row, conn) if row else None


def list_concepts(limit: int = 100, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    """Newest first -- the ones you just generated are the ones you're
    deciding about."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM shoot_concepts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_concept_row(r, conn) for r in rows]


def save_concept_ideas(
    ideas: list,
    brand: str,
    client: Optional[str] = None,
    spark: Optional[str] = None,
    prompt_template: Optional[str] = None,
    use_pov: bool = False,
    path: Path | str = DB_PATH,
) -> list:
    """
    Stage one: save a batch of cheap ideas, no shot lists yet. Returns
    their ids in order. Which of these later gets a shot list is the
    pick worth measuring.
    """
    return [
        save_concept(idea, brand=brand, client=client, spark=spark,
                     prompt_template=prompt_template, use_pov=use_pov, path=path)
        for idea in ideas
    ]


def update_concept_shots(
    concept_id: int,
    plan: dict,
    location_ids: Optional[list] = None,
    warnings: Optional[list] = None,
    path: Path | str = DB_PATH,
) -> None:
    """
    Stage two: attach a shot list to an idea you chose. Leaves the
    idea's own fields (title, hook, logline) alone -- those were the
    thing you picked, and rewriting them here would quietly change
    what you agreed to.
    """
    with connect(path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM shoot_concepts WHERE id = ?", (concept_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"no concept with id {concept_id}")

        conn.execute(
            """
            UPDATE shoot_concepts
               SET duration   = COALESCE(?, duration),
                   shots_json = ?,
                   ai_json    = ?,
                   edit_note  = COALESCE(?, edit_note),
                   grade_note = COALESCE(?, grade_note),
                   warnings_json = ?
             WHERE id = ?
            """,
            (plan.get("duration"),
             json.dumps(plan.get("shots") or []),
             json.dumps(plan["ai"]) if plan.get("ai") else None,
             plan.get("edit"), plan.get("grade"),
             # replaced, not merged: planning re-validates from scratch,
             # so an idea-stage warning must not linger as if still true
             json.dumps(warnings) if warnings else None,
             concept_id),
        )

        for location_id in location_ids or []:
            conn.execute(
                "INSERT OR IGNORE INTO concept_locations (concept_id, location_id) VALUES (?, ?)",
                (concept_id, location_id),
            )


def set_shot_media_url(concept_id: int, shot_n, media_url: str,
                        path: Path | str = DB_PATH) -> None:
    """
    Attach a rendered clip's public URL to one shot in a concept's shot
    list -- the one field autopilot.build_plan() checks before it will
    ever emit a post action (see autopilot.py). Rewrites just the
    matching shot's media_url in place; everything else in the shot
    list -- other shots, prompts, camera notes -- is left untouched.

    Raises if the concept or the shot (by its "n") doesn't exist,
    rather than silently no-op'ing -- storage.publish_shot_media()
    catches this and turns it into a result dict.
    """
    if not (media_url or "").strip():
        raise ValueError("media_url is required")

    with connect(path) as conn:
        row = conn.execute(
            "SELECT shots_json FROM shoot_concepts WHERE id = ?", (concept_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"no concept with id {concept_id}")

        shots = json.loads(row["shots_json"] or "[]")
        for shot in shots:
            if shot.get("n") == shot_n:
                shot["media_url"] = media_url.strip()
                break
        else:
            raise ValueError(f"concept {concept_id} has no shot n={shot_n!r}")

        conn.execute(
            "UPDATE shoot_concepts SET shots_json = ? WHERE id = ?",
            (json.dumps(shots), concept_id),
        )


def set_shot_reference_image(concept_id: int, shot_n, reference_url,
                             path: Path | str = DB_PATH) -> None:
    """
    Attach a real capture -- the acting take or room plate Michael
    filmed -- to one shot as the reference image its AI generation
    anchors on. Shots live as dicts inside shots_json, so this rewrites
    just the matching shot's reference_image in place, exactly the
    set_shot_media_url() shape above.

    Unlike media_url, empty is legal here and CLEARS the reference: a
    reference is an enhancement to a shot, never a gate on it, so
    detaching one must be as easy as attaching it. Raises if the
    concept or the shot (by its "n") doesn't exist.
    """
    with connect(path) as conn:
        row = conn.execute(
            "SELECT shots_json FROM shoot_concepts WHERE id = ?", (concept_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"no concept with id {concept_id}")

        shots = json.loads(row["shots_json"] or "[]")
        for shot in shots:
            if shot.get("n") == shot_n:
                cleaned = (reference_url or "").strip()
                if cleaned:
                    shot["reference_image"] = cleaned
                else:
                    # absent, not empty-string: a shot carries the key
                    # only while a reference is actually attached
                    shot.pop("reference_image", None)
                break
        else:
            raise ValueError(f"concept {concept_id} has no shot n={shot_n!r}")

        conn.execute(
            "UPDATE shoot_concepts SET shots_json = ? WHERE id = ?",
            (json.dumps(shots), concept_id),
        )


def set_shot_parked(concept_id: int, shot_n, reason: str = "",
                    path: Path | str = DB_PATH) -> None:
    """
    Mark a shot as finished with the automatic half and waiting on a
    human to approve the spend -- what the Studio chain writes when it
    has a concept, an enhanced prompt and (usually) a keyframe, and the
    next step is the one that costs money.

    An explicit marker, not an inference. The obvious shortcut is to
    treat "has a reference_image" as "waiting in the Queue", but that
    field is also written by the Director canvas mid-work
    (POST /concepts/{id}/shots/{n}/reference), so inferring would drag
    every scene anyone has ever keyframed into the spend queue. Stored
    on the shot like refs / reference_image / media_url -- shots_json
    was always one flexible JSON column, so no migration.

    Empty reason is legal (parked, nothing to say). Passing parked=False
    is not a thing: leaving the queue is approving or archiving, both of
    which already have their own timestamps. Raises if the concept or
    the shot (by its "n") doesn't exist.
    """
    with connect(path) as conn:
        row = conn.execute(
            "SELECT shots_json FROM shoot_concepts WHERE id = ?", (concept_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"no concept with id {concept_id}")

        shots = json.loads(row["shots_json"] or "[]")
        for shot in shots:
            if shot.get("n") == shot_n:
                shot["parked_at"] = _now()
                cleaned = (reason or "").strip()
                if cleaned:
                    shot["park_reason"] = cleaned
                else:
                    shot.pop("park_reason", None)
                break
        else:
            raise ValueError(f"concept {concept_id} has no shot n={shot_n!r}")

        conn.execute(
            "UPDATE shoot_concepts SET shots_json = ? WHERE id = ?",
            (json.dumps(shots), concept_id),
        )


def set_picked(concept_id: int, picked: bool = True,
               path: Path | str = DB_PATH) -> None:
    """The label, moved to fit the unit (2026-08-26).

    shortlist_rate asked "was this idea worth planning a shot list for",
    derived from `shots != []`. Now that a concept IS one scene with one
    shot, every concept has shots the moment it exists and that question
    has no answer left in it. The decision actually being made is "is
    this scene worth rendering", so THAT is what gets recorded -- picking
    one of the several a single idea produced.

    Timestamped rather than a flag: a rate you cannot window by date
    stops being useful the moment the prompt changes.
    """
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE shoot_concepts SET picked_at = ? WHERE id = ?",
            (_now() if picked else None, concept_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no concept {concept_id}")


def set_archived(concept_id: int, archived: bool = True,
                 path: Path | str = DB_PATH) -> None:
    """Take a concept off the board without taking it out of the data.

    The board is a decision surface: once you have picked one of the
    several an idea produced and sent it to render, the others have been
    decided about and standing there they are just noise. But an
    unpicked row is the only negative signal this system collects --
    pick_rate is generated-vs-picked, and deleting the ones you passed
    over would make the rate 100% forever and unfalsifiable.

    So archiving hides, it does not delete. The row keeps counting in
    pick_rate and keeps sitting in the Dev Studio's ungraded pool
    (judge_overall IS NULL), which is where it finally earns its keep by
    teaching the RAG shelves what a miss looks like.
    """
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE shoot_concepts SET archived_at = ? WHERE id = ?",
            (_now() if archived else None, concept_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no concept {concept_id}")


def archive_batch(spark: str, keep_ids: list[int] | None = None,
                  brand: Optional[str] = None,
                  path: Path | str = DB_PATH) -> int:
    """Archive every unresolved concept written from one idea, except
    the ones named in keep_ids. Returns how many were archived.

    A batch is "the concepts one idea produced", and the idea is stored
    on each row as `spark` -- generate_scene_concepts writes all N with
    the same one. That is the grouping the human is actually deciding
    within: pick from these four, the other three are answered.
    """
    keep = set(keep_ids or [])
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT id FROM shoot_concepts "
            "WHERE spark = ? AND archived_at IS NULL"
            + (" AND brand = ?" if brand else ""),
            (spark, brand) if brand else (spark,),
        ).fetchall()
        targets = [r["id"] for r in rows if r["id"] not in keep]
        for concept_id in targets:
            conn.execute(
                "UPDATE shoot_concepts SET archived_at = ? WHERE id = ?",
                (_now(), concept_id),
            )
    return len(targets)


def pick_rate(path: Path | str = DB_PATH) -> dict[str, Any]:
    """Of the scenes generated, how many were worth rendering.

    shortlist_rate's successor, same shape and same per-prompt-hash
    breakdown -- derived from the rows rather than stored, so it cannot
    drift from what it describes. Counts only ONE-SHOT concepts: a
    legacy multi-shot concept was never a single scene to pick, and
    mixing the two would compare different decisions.
    """
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT prompt_hash,
                   COUNT(*) AS generated,
                   SUM(CASE WHEN picked_at IS NOT NULL THEN 1 ELSE 0 END) AS picked
            FROM shoot_concepts
            WHERE json_array_length(shots_json) = 1
            GROUP BY prompt_hash
            """
        ).fetchall()

    by_prompt = [
        {
            "prompt_hash": r["prompt_hash"],
            "generated": r["generated"],
            "picked": r["picked"] or 0,
            "rate": round((r["picked"] or 0) / r["generated"], 3),
        }
        for r in rows
    ]
    generated = sum(b["generated"] for b in by_prompt)
    picked = sum(b["picked"] for b in by_prompt)
    return {
        "generated": generated,
        "picked": picked,
        "rate": round(picked / generated, 3) if generated else None,
        "by_prompt": by_prompt,
    }


def mark_shot(concept_id: int, shot: bool = True, path: Path | str = DB_PATH) -> None:
    """Record that you actually went and shot this one -- the label."""
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE shoot_concepts SET shot_done = ? WHERE id = ?",
            (1 if shot else 0, concept_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no concept with id {concept_id}")


def shoot_rate(path: Path | str = DB_PATH) -> dict[str, Any]:
    """
    How many generated concepts you actually shoot, overall and per
    prompt version. The pre-production equivalent of selection_rate.
    """
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT prompt_hash,
                   COUNT(*)        AS generated,
                   SUM(shot_done)  AS shot
            FROM shoot_concepts
            GROUP BY prompt_hash
            """
        ).fetchall()

    by_prompt = [
        {
            "prompt_hash": r["prompt_hash"],
            "generated": r["generated"],
            "shot": r["shot"] or 0,
            "rate": round((r["shot"] or 0) / r["generated"], 3),
        }
        for r in rows
    ]
    generated = sum(b["generated"] for b in by_prompt)
    shot = sum(b["shot"] for b in by_prompt)
    return {
        "generated": generated,
        "shot": shot,
        "rate": round(shot / generated, 3) if generated else None,
        "by_prompt": by_prompt,
    }


def summary(path: Path | str = DB_PATH) -> dict[str, int]:
    with connect(path) as conn:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("locations", "shoot_concepts")
        }

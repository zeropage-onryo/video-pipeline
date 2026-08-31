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
import re
from pathlib import Path
from typing import Any, Optional

from .db import DB_PATH, _ensure_accounts_table, _hash, _now, connect, own_table

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


# `locations.name` was globally UNIQUE, which is fine for one operator and
# wrong the moment there are two: no second account could ever own a place
# called "Garage". A UNIQUE lives in the table definition and SQLite cannot
# ALTER one away, so the fix is a rebuild.
LOCATIONS_TARGET = """
CREATE TABLE locations_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    photo_count INTEGER,
    description_json TEXT,
    notes       TEXT,
    account_id  INTEGER REFERENCES accounts(id)
)
"""

# Uniqueness is an expression index, not a table constraint, and the
# COALESCE is load-bearing: SQLite treats NULLs as distinct inside a
# UNIQUE, so a plain UNIQUE(account_id, name) lets two ownerless rows
# named "hallway" both exist -- which is exactly what add_location's
# upsert relies on NOT happening. Folding NULL to 0 keeps an unowned row
# behaving the way it did before tenancy, so nothing changes for a
# caller that has not been given an account yet, while two real accounts
# can still each own a Garage.
LOCATIONS_UNIQUE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_locations_owner_name "
    "ON locations (COALESCE(account_id, 0), name)"
)

CONCEPT_LOCATIONS_TARGET = """
CREATE TABLE concept_locations_new (
    concept_id  INTEGER NOT NULL REFERENCES shoot_concepts(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    UNIQUE (concept_id, location_id)
)
"""


def _rebuild_locations_unique(conn) -> bool:
    """Move locations from UNIQUE(name) to UNIQUE(account_id, name).

    Driven by the target shape rather than by the old one, so it is
    idempotent and takes the same path on a fresh database as on an
    existing one. Returns True when it actually rebuilt.

    **Never rename the old table out of the way.** That is the obvious
    shape for a SQLite rebuild and it is wrong here, because
    `concept_locations` has a foreign key into `locations`: since 3.25 a
    RENAME rewrites the REFERENCES clauses of *other* tables to follow
    it, so `concept_locations` ends up pointing at `locations_old` and
    that table is about to be dropped. Neither `PRAGMA foreign_keys=OFF`
    nor `PRAGMA legacy_alter_table=ON` prevents it -- both were tried
    against a copy of the live database and both still rewrote the
    clause (SQLite 3.37.2).

    So build the new table alongside, drop the original, and rename the
    new one *into* the original's name. Nothing ever references
    `locations_new`, so that rename rewrites nothing, and
    `concept_locations` keeps pointing at `locations` throughout.
    Foreign keys go off only so the DROP does not fire ON DELETE CASCADE
    down into `concept_locations`.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'locations'"
    ).fetchone()
    if row is None or "UNIQUE" not in (row["sql"] or "").upper():
        return False   # already the target shape

    present = {r["name"] for r in conn.execute("PRAGMA table_info(locations)")}
    carried = [c for c in ("id", "created_at", "name", "photo_count",
                           "description_json", "notes", "account_id")
               if c in present]
    cols = ", ".join(carried)

    # The new table points at accounts(id), so that table has to exist
    # first -- init() runs before seed() on a fresh database, and a
    # REFERENCES clause naming a missing table is a live landmine rather
    # than an error at CREATE time. _assert_no_dangling below is what
    # caught this.
    _ensure_accounts_table(conn)

    conn.commit()   # a PRAGMA is a no-op inside an open transaction
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(LOCATIONS_TARGET)
        conn.execute(f"INSERT INTO locations_new ({cols}) SELECT {cols} FROM locations")
        conn.execute("DROP TABLE locations")
        conn.execute("ALTER TABLE locations_new RENAME TO locations")
        conn.execute(LOCATIONS_UNIQUE)
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    _assert_no_dangling(conn, "locations rebuild")
    return True


def _repair_concept_locations_fk(conn) -> bool:
    """Heal a `concept_locations` whose FK was rewritten to point at a
    table that no longer exists.

    This is not hypothetical: the first version of the rebuild above
    renamed `locations` out of the way, and every database it touched
    came out with `REFERENCES "locations_old"(id)`. That table is gone,
    so any INSERT into concept_locations dies with
    `no such table: main.locations_old` -- which is every time a concept
    is saved against a location. The table is a pure join table, so the
    repair carries its rows across and costs nothing.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' "
        "AND name = 'concept_locations'"
    ).fetchone()
    if row is None or "locations_old" not in (row["sql"] or ""):
        return False

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(CONCEPT_LOCATIONS_TARGET)
        conn.execute(
            "INSERT INTO concept_locations_new (concept_id, location_id) "
            "SELECT concept_id, location_id FROM concept_locations"
        )
        conn.execute("DROP TABLE concept_locations")
        conn.execute("ALTER TABLE concept_locations_new RENAME TO concept_locations")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cl_concept ON concept_locations (concept_id)"
        )
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    _assert_no_dangling(conn, "concept_locations repair")
    return True


def _assert_no_dangling(conn, what: str) -> None:
    """`PRAGMA foreign_key_check` is not enough on its own -- it stays
    silent about a REFERENCES clause naming a table that does not exist,
    which is exactly the failure mode here. So check the schema text too."""
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"{what} left FK violations: {violations}")
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table'"):
        for ref in re.findall(r'REFERENCES\s+"?(\w+)"?', sql or ""):
            if ref not in names:
                raise RuntimeError(
                    f"{what} left {table} referencing missing table {ref}")


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
        # tenancy. The rebuild runs first: it creates locations already
        # carrying account_id, so own_table then only has to claim the rows.
        _repair_concept_locations_fk(conn)
        _rebuild_locations_unique(conn)
        own_table(conn, "locations")
        own_table(conn, "shoot_concepts")
        own_table(conn, "scene_briefs")
        # the shape every board query uses: this account's, newest first
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_concepts_account "
            "ON shoot_concepts (account_id, id DESC)"
        )


def save_judge_score(concept_id: int, judge: dict, path: Path | str = DB_PATH, *,
                     account_id: int) -> None:
    """Store the taste + performance judge's verdict on a concept so the UI
    can show and rank by it. `judge` is taste_judge.score_concept()'s dict."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE shoot_concepts SET judge_overall=?, judge_taste=?, "
            "judge_perf=?, judge_reason=? WHERE id=? AND account_id IS ?",
            (judge.get("overall"), judge.get("taste_fit"), judge.get("performance"),
             " · ".join(judge.get("reasons") or [])[:500], concept_id, account_id),
        )


def save_uncanny_score(concept_id: int, score: dict, path: Path | str = DB_PATH, *,
                       account_id: int) -> None:
    """Store Zero Page's on-brand gate verdict on a concept so the UI can show
    the PASS/HOLD and autopilot can check it. `score` is
    uncanny_judge.score_concept()'s dict."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE shoot_concepts SET uncanny_overall=?, uncanny_passed=?, "
            "uncanny_reason=? WHERE id=? AND account_id IS ?",
            (score.get("overall"), 1 if score.get("passed") else 0,
             " · ".join(score.get("reasons") or [])[:500], concept_id, account_id),
        )


def delete_concept(concept_id: int, path: Path | str = DB_PATH, *,
                   account_id: int) -> None:
    """Discard a concept for good -- if it is yours. concept_locations
    rows cascade via the FK (connect() sets PRAGMA foreign_keys=ON).

    Deleting someone else's is silently a no-op rather than an error,
    for the same reason get_concept returns None: an error would confirm
    the row exists."""
    with connect(path) as conn:
        conn.execute(
            "DELETE FROM shoot_concepts WHERE id = ? AND account_id IS ?",
            (concept_id, account_id),
        )


def delete_all_concepts(brand: Optional[str] = None, path: Path | str = DB_PATH, *,
                        account_id: int) -> int:
    """Clear ONE ACCOUNT's concept slate -- all of it, or just one of its
    brands. Returns how many were removed. concept_locations cascades.

    `account_id` is required here above all: this used to be
    `DELETE FROM shoot_concepts` with no argument at all, which wiped the
    whole table. With a second account on the database that is not a
    reset, it is someone else's work gone."""
    with connect(path) as conn:
        if brand:
            cur = conn.execute(
                "DELETE FROM shoot_concepts WHERE brand = ? AND account_id IS ?",
                (brand, account_id),
            )
        else:
            cur = conn.execute(
                "DELETE FROM shoot_concepts WHERE account_id IS ?", (account_id,)
            )
        return cur.rowcount


# --------------------------------------------------------------------------
# scene briefs -- one cohesive whole-scene prompt (the winning skeleton)
# --------------------------------------------------------------------------
def save_scene_brief(brand: str, title: str, brief: str,
                     spark: Optional[str] = None, path: Path | str = DB_PATH, *,
                     account_id: int) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO scene_briefs (created_at, brand, spark, title, brief, "
            "account_id) VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), brand, (spark or "").strip() or None,
             (title or "Untitled scene").strip(), brief.strip(), account_id),
        )
        return int(cur.lastrowid)


def list_scene_briefs(brand: Optional[str] = None,
                      path: Path | str = DB_PATH, *,
                      account_id: int) -> list[dict[str, Any]]:
    """This account's briefs. `brand` still narrows within them -- it is
    a label on the row now, not the thing that decides who may see it."""
    sql = "SELECT * FROM scene_briefs WHERE account_id IS ?"
    params: list[Any] = [account_id]
    if brand:
        sql += " AND brand = ?"
        params.append(brand)
    sql += " ORDER BY id DESC"
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def delete_scene_brief(brief_id: int, path: Path | str = DB_PATH, *,
                       account_id: int) -> None:
    with connect(path) as conn:
        conn.execute(
            "DELETE FROM scene_briefs WHERE id = ? AND account_id IS ?",
            (brief_id, account_id),
        )


# --------------------------------------------------------------------------
# locations
# --------------------------------------------------------------------------


def add_location(
    name: str,
    description: Optional[dict] = None,
    photo_count: Optional[int] = None,
    notes: Optional[str] = None,
    path: Path | str = DB_PATH,
    *,
    account_id: int,
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
            INSERT INTO locations (created_at, name, photo_count, description_json,
                                   notes, account_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (COALESCE(account_id, 0), name) DO UPDATE SET
                photo_count      = excluded.photo_count,
                description_json = excluded.description_json,
                notes            = COALESCE(excluded.notes, locations.notes)
            """,
            (_now(), name, photo_count,
             json.dumps(description) if description is not None else None, notes,
             account_id),
        )
        # `cur.lastrowid` is not trustworthy after an upsert that took the
        # DO UPDATE path -- it reports a rowid no statement wrote. Ask.
        row = conn.execute(
            "SELECT id FROM locations WHERE name = ? "
            "AND COALESCE(account_id, 0) = COALESCE(?, 0)",
            (name, account_id),
        ).fetchone()
        return int(row["id"]) if row else int(cur.lastrowid)


def _location_row(row) -> dict[str, Any]:
    data = dict(row)
    raw = data.pop("description_json", None)
    data["description"] = json.loads(raw) if raw else None
    return data


def get_location(location_id: int, path: Path | str = DB_PATH, *,
                 account_id: int) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND account_id IS ?",
            (location_id, account_id),
        ).fetchone()
    return _location_row(row) if row else None


def get_location_by_name(name: str, path: Path | str = DB_PATH, *,
                         account_id: int) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM locations WHERE name = ? AND account_id IS ?",
            (name, account_id),
        ).fetchone()
    return _location_row(row) if row else None


def list_locations(path: Path | str = DB_PATH, *,
                   account_id: int) -> list[dict[str, Any]]:
    with connect(path) as conn:
        return [
            _location_row(r)
            for r in conn.execute(
                "SELECT * FROM locations WHERE account_id IS ? ORDER BY name ASC",
                (account_id,),
            )
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
    *,
    account_id: int,
) -> int:
    """
    Store one generated concept, warnings and all. Returns its id.

    `account_id` is stamped from the caller's session, never taken from
    a request parameter -- a client that can name the owner of a row it
    is creating can create rows in someone else's account.

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
                 warnings_json, use_pov, format, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_now(), brand, client, spark, title,
             concept.get("hook"), concept.get("logline"), concept.get("duration"),
             json.dumps(concept.get("shots") or []),
             json.dumps(concept["ai"]) if concept.get("ai") else None,
             concept.get("edit"), concept.get("grade"), _hash(prompt_template),
             json.dumps(warnings) if warnings else None, 1 if use_pov else 0,
             concept.get("format"), account_id),
        )
        concept_id = int(cur.lastrowid)

        for location_id in location_ids or []:
            # a concept may only be pinned to a location the same account
            # owns -- otherwise a guessed id links you to a stranger's room
            owned = conn.execute(
                "SELECT 1 FROM locations WHERE id = ? AND account_id IS ?",
                (location_id, account_id),
            ).fetchone()
            if not owned:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO concept_locations (concept_id, location_id) VALUES (?, ?)",
                (concept_id, location_id),
            )
        return concept_id


# --- the one line a card shows -----------------------------------------------
# The board's whole job is choosing between several concepts, and a
# scene prompt is ~1200 characters of camera, grade and beats -- reading
# four of those to find out what happens is what the summary line
# replaces (2026-08-31). The writer supplies it as `logline`; these two
# helpers are the safety net for a row that has none (every concept
# written before the prompt asked for one) and the hard cap that keeps
# it to ONE line whatever the model returned.

# Measured, not guessed (2026-08-31). .scenegrid is
# repeat(auto-fill,minmax(380px,1fr)) capped at 1680px, so the NARROWEST
# a card ever gets is a 4-column row on a wide screen: a 349px text box,
# which fits ~54 average characters at 14.5px. Budget under that and cut
# on a word boundary -- a line trimmed at a word reads as a short
# summary, where the CSS ellipsis mid-word reads as broken.
SUMMARY_WORDS = 8
SUMMARY_CHARS = 52

# Camera-craft openers the beats almost always start with. Stripping
# them is what turns "Open on an extreme macro of a pale membrane pinned
# over a hole" into "a pale membrane pinned over a hole" -- the summary
# is meant to say what happens, and framing is not what happens.
_OPENERS = re.compile(
    r"""^\s*(?:the\s+(?:scene|video|clip|film)\s+)?(?:
        (?:begin|begins|open|opens|start|starts|starting|opening)
        (?:\s+(?:on|with|in))?\s+
        (?:an?\s+|the\s+)?
        (?:(?:extreme\s+|low[- ]angle\s+|high[- ]angle\s+|wide\s+|close\s+|macro\s+|tight\s+|
             handheld\s+|static\s+|slow\s+)*
           (?:shot|macro|angle|close[- ]up|frame|framing|push[- ]in|pan|tilt)
           (?:\s+(?:of|on|at))?\s+)?
      | the\s+camera\s+\w+(?:s)?(?:\s+(?:on|to|in|at|from))?\s+
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def derive_logline(prompt: str) -> str:
    """A summary read out of the prompt itself, for a concept the writer
    gave no logline. First sentence of the BEATS block with the camera
    direction taken off the front -- coarse on purpose: this is the
    fallback, and a concept written today carries a real logline."""
    text = (prompt or "").strip()
    if not text:
        return ""
    beats = re.split(r"\bbeats?\s*:", text, maxsplit=1, flags=re.IGNORECASE)
    # No BEATS header: skip the open line and the style block, which are
    # boilerplate in every prompt this pipeline writes.
    body = beats[1] if len(beats) > 1 else re.split(
        r"\bstyle\s*:[^.]*\.", text, maxsplit=1, flags=re.IGNORECASE)[-1]
    sentence = re.split(r"(?<=[.!?])\s+", body.strip(), maxsplit=1)[0]
    return _OPENERS.sub("", sentence).strip()


def concept_summary(logline: str = "", prompt: str = "",
                    words: int = SUMMARY_WORDS,
                    chars: int = SUMMARY_CHARS) -> str:
    """The line the card prints, capped so it stays ONE line at the
    narrowest a card gets: the writer's logline when there is one,
    otherwise derive_logline. Both caps cut on a word boundary."""
    line = " ".join((logline or "").split())
    if not line:
        line = " ".join(derive_logline(prompt).split())
    if not line:
        return ""
    line = line.rstrip(" .,;:—-")
    parts = line.split(" ")
    cut = len(parts) > words
    if cut:
        parts = parts[:words]
    while len(" ".join(parts)) > chars and len(parts) > 1:
        parts.pop()
        cut = True
    line = " ".join(parts).rstrip(" .,;:—-") + ("…" if cut else "")
    return line[:1].upper() + line[1:]


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
            WHERE cl.concept_id = ? AND l.account_id IS ?
            ORDER BY l.name
            """,
            (data["id"], data.get("account_id")),
        )
    ]
    return data


def get_concept(concept_id: int, path: Path | str = DB_PATH, *,
                account_id: int) -> Optional[dict[str, Any]]:
    """One concept, if it is this account's.

    Returns None for a concept that belongs to someone else -- the same
    answer as for a concept that does not exist. The distinction would
    be an enumeration oracle: ids are sequential integers, so "not
    yours" and "not found" have to be indistinguishable or anyone can
    map the whole table by counting.

    `account_id` is keyword-only and has no default. An optional
    ownership argument is a leak waiting for the one call site that
    forgets it; this way a forgotten one is a TypeError at the call.
    """
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM shoot_concepts WHERE id = ? AND account_id IS ?",
            (concept_id, account_id),
        ).fetchone()
        return _concept_row(row, conn) if row else None


def list_concepts(limit: int = 100, path: Path | str = DB_PATH, *,
                  account_id: int) -> list[dict[str, Any]]:
    """This account's concepts, newest first -- the ones you just
    generated are the ones you're deciding about."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM shoot_concepts WHERE account_id IS ? "
            "ORDER BY id DESC LIMIT ?",
            (account_id, limit),
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
    *,
    account_id: int,
) -> list:
    """
    Stage one: save a batch of cheap ideas, no shot lists yet. Returns
    their ids in order. Which of these later gets a shot list is the
    pick worth measuring.
    """
    return [
        save_concept(idea, brand=brand, client=client, spark=spark,
                     prompt_template=prompt_template, use_pov=use_pov, path=path,
                     account_id=account_id)
        for idea in ideas
    ]


def update_concept_shots(
    concept_id: int,
    plan: dict,
    location_ids: Optional[list] = None,
    warnings: Optional[list] = None,
    path: Path | str = DB_PATH,
    *,
    account_id: int,
) -> None:
    """
    Stage two: attach a shot list to an idea you chose. Leaves the
    idea's own fields (title, hook, logline) alone -- those were the
    thing you picked, and rewriting them here would quietly change
    what you agreed to.
    """
    with connect(path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM shoot_concepts WHERE id = ? AND account_id IS ?",
            (concept_id, account_id),
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
             WHERE id = ? AND account_id IS ?
            """,
            (plan.get("duration"),
             json.dumps(plan.get("shots") or []),
             json.dumps(plan["ai"]) if plan.get("ai") else None,
             plan.get("edit"), plan.get("grade"),
             # replaced, not merged: planning re-validates from scratch,
             # so an idea-stage warning must not linger as if still true
             json.dumps(warnings) if warnings else None,
             concept_id, account_id),
        )

        for location_id in location_ids or []:
            owned = conn.execute(
                "SELECT 1 FROM locations WHERE id = ? AND account_id IS ?",
                (location_id, account_id),
            ).fetchone()
            if not owned:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO concept_locations (concept_id, location_id) VALUES (?, ?)",
                (concept_id, location_id),
            )


def set_shot_media_url(concept_id: int, shot_n, media_url: str,
                        path: Path | str = DB_PATH, *,
                        account_id: int) -> None:
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
            "SELECT shots_json FROM shoot_concepts WHERE id = ? AND account_id IS ?",
            (concept_id, account_id),
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
            "UPDATE shoot_concepts SET shots_json = ? WHERE id = ? AND account_id IS ?",
            (json.dumps(shots), concept_id, account_id),
        )


def set_shot_reference_image(concept_id: int, shot_n, reference_url,
                             path: Path | str = DB_PATH, *,
                             account_id: int) -> None:
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
            "SELECT shots_json FROM shoot_concepts WHERE id = ? AND account_id IS ?",
            (concept_id, account_id),
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
            "UPDATE shoot_concepts SET shots_json = ? WHERE id = ? AND account_id IS ?",
            (json.dumps(shots), concept_id, account_id),
        )


def set_shot_parked(concept_id: int, shot_n, reason: str = "",
                    path: Path | str = DB_PATH, *,
                    account_id: int) -> None:
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
            "SELECT shots_json FROM shoot_concepts WHERE id = ? AND account_id IS ?",
            (concept_id, account_id),
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
            "UPDATE shoot_concepts SET shots_json = ? WHERE id = ? AND account_id IS ?",
            (json.dumps(shots), concept_id, account_id),
        )


def set_picked(concept_id: int, picked: bool = True,
               path: Path | str = DB_PATH, *,
               account_id: int) -> None:
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
            "UPDATE shoot_concepts SET picked_at = ? WHERE id = ? AND account_id IS ?",
            (_now() if picked else None, concept_id, account_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no concept {concept_id}")


def set_archived(concept_id: int, archived: bool = True,
                 path: Path | str = DB_PATH, *,
                 account_id: int) -> None:
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
            "UPDATE shoot_concepts SET archived_at = ? WHERE id = ? AND account_id IS ?",
            (_now() if archived else None, concept_id, account_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no concept {concept_id}")


def archive_batch(spark: str, keep_ids: list[int] | None = None,
                  brand: Optional[str] = None,
                  path: Path | str = DB_PATH, *,
                  account_id: int) -> int:
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
            "WHERE spark = ? AND archived_at IS NULL AND account_id IS ?"
            + (" AND brand = ?" if brand else ""),
            (spark, account_id, brand) if brand else (spark, account_id),
        ).fetchall()
        targets = [r["id"] for r in rows if r["id"] not in keep]
        for concept_id in targets:
            conn.execute(
                "UPDATE shoot_concepts SET archived_at = ? WHERE id = ? AND account_id IS ?",
                (_now(), concept_id, account_id),
            )
    return len(targets)


def pick_rate(path: Path | str = DB_PATH, *, account_id: int) -> dict[str, Any]:
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
            WHERE json_array_length(shots_json) = 1 AND account_id IS ?
            GROUP BY prompt_hash
            """,
            (account_id,),
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


def mark_shot(concept_id: int, shot: bool = True, path: Path | str = DB_PATH, *,
              account_id: int) -> None:
    """Record that you actually went and shot this one -- the label."""
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE shoot_concepts SET shot_done = ? WHERE id = ? AND account_id IS ?",
            (1 if shot else 0, concept_id, account_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no concept with id {concept_id}")


def shoot_rate(path: Path | str = DB_PATH, *, account_id: int) -> dict[str, Any]:
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
            WHERE account_id IS ?
            GROUP BY prompt_hash
            """,
            (account_id,),
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


def summary(path: Path | str = DB_PATH, *, account_id: int) -> dict[str, int]:
    """Counts for one account. An unscoped COUNT here would have been a
    quiet cross-account leak -- small, but it is still telling you how
    much work everyone else has done."""
    with connect(path) as conn:
        return {
            t: conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE account_id IS ?", (account_id,)
            ).fetchone()[0]
            for t in ("locations", "shoot_concepts")
        }

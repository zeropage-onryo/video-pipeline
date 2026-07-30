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
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS concept_locations (
    concept_id  INTEGER NOT NULL REFERENCES shoot_concepts(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    UNIQUE (concept_id, location_id)
);

CREATE INDEX IF NOT EXISTS idx_concepts_shot ON shoot_concepts (shot_done);
CREATE INDEX IF NOT EXISTS idx_cl_concept    ON concept_locations (concept_id);
"""


def init(path: Path | str = DB_PATH) -> None:
    """Create the pre-production tables. Run after db.init_db()."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)


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
    path: Path | str = DB_PATH,
) -> int:
    """
    Store one generated concept. Returns its id.

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
                 duration, shots_json, ai_json, edit_note, grade_note, prompt_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_now(), brand, client, spark, title,
             concept.get("hook"), concept.get("logline"), concept.get("duration"),
             json.dumps(concept.get("shots") or []),
             json.dumps(concept["ai"]) if concept.get("ai") else None,
             concept.get("edit"), concept.get("grade"), _hash(prompt_template)),
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

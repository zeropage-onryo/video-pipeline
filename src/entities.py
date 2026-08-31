"""
Characters and props -- the two pre-production entities the pipeline didn't
have yet. Same shape as the rest of the pre-production data: a small SQLite
table on the shared pipeline DB, a JSON `description` blob (mirroring how
locations store their description dict), and photos on disk under the repo.

Owns its own tables, initialised from the app lifespan alongside
`db.init_db` and `preprod.init`. Uses `db.connect` so it inherits the same
row_factory + foreign-keys + commit/rollback contract as everything else.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    role            TEXT,                 -- protagonist / talent / voice
    description     TEXT,                 -- JSON: {look, wardrobe, notes}
    reference_image TEXT,                 -- filename under characters/<slug>/
    photo_count     INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_characters_name ON characters (name);

CREATE TABLE IF NOT EXISTS props (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    category        TEXT,                 -- vehicle / wardrobe / set-dressing
    description     TEXT,                 -- JSON blob, same pattern as locations
    reference_image TEXT,
    photo_count     INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_props_category ON props (category);
"""


def init(path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.executescript(SCHEMA)
        # tenancy: a cast member or a prop belongs to one account's bank
        db.own_table(conn, "characters")
        db.own_table(conn, "props")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    d = dict(row)
    raw = d.get("description")
    if raw:
        try:
            d["description"] = json.loads(raw)
        except (ValueError, TypeError):
            d["description"] = {"notes": raw}
    else:
        d["description"] = {}
    return d


# --- characters -----------------------------------------------------------

def add_character(name, role="", description=None, reference_image="",
                  photo_count=0, notes="", path=db.DB_PATH) -> int:
    with db.connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO characters "
            "(name, created_at, role, description, reference_image, photo_count, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, _now(), role,
             json.dumps(description) if description is not None else None,
             reference_image, photo_count, notes),
        )
        return cur.lastrowid


def list_characters(path=db.DB_PATH) -> list[dict]:
    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM characters ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_character(character_id: int, path=db.DB_PATH):
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_character(character_id: int, path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))


# --- props ----------------------------------------------------------------

def add_prop(name, category="", description=None, reference_image="",
             photo_count=0, notes="", path=db.DB_PATH) -> int:
    with db.connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO props "
            "(name, created_at, category, description, reference_image, photo_count, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, _now(), category,
             json.dumps(description) if description is not None else None,
             reference_image, photo_count, notes),
        )
        return cur.lastrowid


def list_props(path=db.DB_PATH) -> list[dict]:
    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM props ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_prop(prop_id: int, path=db.DB_PATH):
    with db.connect(path) as conn:
        row = conn.execute("SELECT * FROM props WHERE id = ?", (prop_id,)).fetchone()
    return _row_to_dict(row) if row else None


def delete_prop(prop_id: int, path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.execute("DELETE FROM props WHERE id = ?", (prop_id,))


# --- descriptions ----------------------------------------------------------

TABLES = {"character": "characters", "prop": "props"}


def set_description(kind: str, entity_id: int, description: dict,
                    path=db.DB_PATH) -> None:
    """Attach (or replace) the vision description on one entity --
    what `locations.describe_entity` produced from its photos. Merged
    over whatever the row already carried, so the typed `notes` a
    person entered survive a later re-describe."""
    if kind not in TABLES:
        raise ValueError(f"kind must be one of {tuple(TABLES)}, got {kind!r}")
    getter = get_character if kind == "character" else get_prop
    row = getter(entity_id, path=path)
    if row is None:
        raise ValueError(f"no such {kind}: {entity_id}")
    merged = {**(row.get("description") or {}), **(description or {})}
    with db.connect(path) as conn:
        conn.execute(
            f"UPDATE {TABLES[kind]} SET description = ? WHERE id = ?",
            (json.dumps(merged), entity_id),
        )


def summary(path=db.DB_PATH) -> dict:
    """Counts for the Scoreboard, mirroring db.summary()'s shape."""
    with db.connect(path) as conn:
        chars = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
        props = conn.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    return {"characters": chars, "props": props}

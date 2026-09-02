"""
Saved Workflows: the node graphs the /ui Workflows canvas builds.

A workflow is nodes + positions + edges + each node's config, exactly
the JSON LiteGraph's serialize()/configure() produce and consume, so
this module is storage, not a serialization format of its own. Extends
db.py in its own module (own SCHEMA, own init), the preprod.py pattern.

Execution lives elsewhere (app/workflow_runner.py); a row here is only
the drawing. Deleting one deletes a saved graph, never a render -- the
generations table keeps every attempt regardless.

OWNED (db.OWNED_TABLES, 2026-09-02). `account_id` is who owns a canvas;
`brand` stays a label the picker filters inside it. The dry run proved
that without the owner any signed-in user listed Mike's canvases,
overwrote one and deleted "Midnight Evasion" -- a shot's saved graph
carries its outputs, so that was the record of paid renders, not
scratch. Every function below takes the owner keyword-only with no
default, so a call site that forgets is a TypeError, never a leak.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .db import DB_PATH, _now, bootstrap_account_id, connect, own_table

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    brand      TEXT,
    name       TEXT NOT NULL,
    graph_json TEXT NOT NULL
);
"""


def init(path=DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        # A concept's canvas is a saved graph too (2026-08-28). It used
        # to be rebuilt from the shot every time it opened and thrown
        # away on exit, so the enhance output -- a paid Gemini call --
        # had to be re-run on every visit just to see it again.
        # Additive, so an existing database gains the columns untouched.
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(workflows)")}
        for column in ("concept_id INTEGER", "shot_n INTEGER",
                       "states_json TEXT", "seed_hash TEXT"):
            if column.split()[0] not in existing:
                conn.execute(f"ALTER TABLE workflows ADD COLUMN {column}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_wf_shot "
                     "ON workflows (concept_id, shot_n) "
                     "WHERE concept_id IS NOT NULL")
        # tenancy (2026-09-02): additive ALTER + backfill to the bootstrap
        # account, the path every other owned table took. Proved against
        # a copy of the live database (5 canvases, all claimed by account
        # 1) before this line existed in the tree.
        own_table(conn, "workflows")


def save_shot_graph(concept_id: int, shot_n: int, graph: dict,
                    states: Optional[dict] = None, name: Optional[str] = None,
                    brand: Optional[str] = None, seed_hash: Optional[str] = None,
                    path=DB_PATH, *, account_id: Optional[int]) -> int:
    """The canvas for one shot of one concept, upserted.

    Keyed on (concept_id, shot_n) rather than appended, because a Run
    all used to POST a brand-new workflow row every time and then never
    read any of them back -- the graph was saved purely so the runner
    had something to execute, and reopening the concept rebuilt it from
    scratch regardless.

    `states` is what each node PRODUCED (the runner's own node states).
    Stored beside the drawing because LiteGraph's serialize() carries
    node config and position but not output: without it a restored
    canvas is the right shape with every box empty, which is exactly
    the thing that made re-running feel mandatory.
    """
    now = _now()
    payload = (json.dumps(graph or {}),
               json.dumps(states) if states is not None else None)
    with connect(path) as conn:
        row = conn.execute(
            "SELECT id FROM workflows WHERE concept_id = ? AND shot_n = ? "
            "AND account_id IS ?",
            (concept_id, shot_n, account_id),
        ).fetchone()
        if row:
            # states absent means "graph only" -- never blank what the
            # last run produced just because this save didn't carry it
            if payload[1] is None:
                conn.execute(
                    "UPDATE workflows SET updated_at = ?, graph_json = ?, "
                    "seed_hash = ? WHERE id = ? AND account_id IS ?",
                    (now, payload[0], seed_hash, row["id"], account_id))
            else:
                conn.execute(
                    "UPDATE workflows SET updated_at = ?, graph_json = ?, "
                    "states_json = ?, seed_hash = ? WHERE id = ? AND account_id IS ?",
                    (now, payload[0], payload[1], seed_hash, row["id"], account_id))
            return int(row["id"])
        cursor = conn.execute(
            "INSERT INTO workflows (created_at, updated_at, brand, name, "
            "graph_json, concept_id, shot_n, states_json, seed_hash, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now, now, brand, (name or "").strip() or f"Shot {shot_n}",
             payload[0], concept_id, shot_n, payload[1], seed_hash, account_id),
        )
        return int(cursor.lastrowid)


def get_shot_graph(concept_id: int, shot_n: int, path=DB_PATH, *,
                   account_id: Optional[int]) -> Optional[dict]:
    """The saved canvas for one shot, or None to build a fresh one."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM workflows WHERE concept_id = ? AND shot_n = ? "
            "AND account_id IS ?",
            (concept_id, shot_n, account_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "graph": json.loads(row["graph_json"] or "{}"),
        "states": json.loads(row["states_json"] or "null"),
        "seed_hash": row["seed_hash"],
        "updated_at": row["updated_at"],
    }


def delete_shot_graphs(concept_id: int, path=DB_PATH, *,
                       account_id: Optional[int]) -> int:
    """Drop a concept's saved canvases -- used when its prompt changes
    underneath them and the stored graph would be a stale drawing of a
    shot that no longer says that."""
    with connect(path) as conn:
        cursor = conn.execute(
            "DELETE FROM workflows WHERE concept_id = ? AND account_id IS ?",
            (concept_id, account_id))
        return cursor.rowcount


def create_workflow(name: str, graph: dict, brand: Optional[str] = None,
                    path=DB_PATH, *, account_id: Optional[int]) -> int:
    name = (name or "").strip() or "Untitled workflow"
    now = _now()
    with connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO workflows (created_at, updated_at, brand, name, "
            "graph_json, account_id) VALUES (?, ?, ?, ?, ?, ?)",
            (now, now, brand, name, json.dumps(graph or {}), account_id),
        )
        return cursor.lastrowid


def update_workflow(workflow_id: int, name: Optional[str] = None,
                    graph: Optional[dict] = None, path=DB_PATH, *,
                    account_id: Optional[int]) -> bool:
    """Update the fields that were passed; absent means unchanged.
    False for someone else's row, same as for a missing id."""
    fields, values = ["updated_at = ?"], [_now()]
    if name is not None and name.strip():
        fields.append("name = ?")
        values.append(name.strip())
    if graph is not None:
        fields.append("graph_json = ?")
        values.append(json.dumps(graph))
    with connect(path) as conn:
        cursor = conn.execute(
            f"UPDATE workflows SET {', '.join(fields)} "
            f"WHERE id = ? AND account_id IS ?",
            (*values, workflow_id, account_id),
        )
        return cursor.rowcount > 0


def delete_workflow(workflow_id: int, path=DB_PATH, *,
                    account_id: Optional[int]) -> bool:
    with connect(path) as conn:
        cursor = conn.execute(
            "DELETE FROM workflows WHERE id = ? AND account_id IS ?",
            (workflow_id, account_id))
        return cursor.rowcount > 0


def _row(raw: dict, with_graph: bool) -> dict[str, Any]:
    graph = json.loads(raw.pop("graph_json") or "{}")
    if with_graph:
        raw["graph"] = graph
    raw["node_count"] = len(graph.get("nodes") or [])
    return raw


def list_workflows(brand: Optional[str] = None, path=DB_PATH, *,
                   account_id: Optional[int]) -> list[dict[str, Any]]:
    """This account's canvases, newest-edited first, graphs left behind
    -- the picker only needs names and sizes, and graph_json is the
    heavy column. A brand filter still includes brandless rows: those
    are the shared templates (the seeded default), visible from every
    brand -- of the same account. Brand filters inside the tenant; it
    never widens it."""
    # concept-scoped canvases are excluded: they belong to a shot, not
    # to the workflow library, and listing them would fill the picker
    # with one entry per shot anyone has ever opened
    query = "SELECT * FROM workflows WHERE concept_id IS NULL AND account_id IS ?"
    params: tuple = (account_id,)
    if brand:
        query += " AND (brand = ? OR brand IS NULL)"
        params = (account_id, brand)
    query += " ORDER BY updated_at DESC, id DESC"
    with connect(path) as conn:
        return [_row(dict(r), with_graph=False)
                for r in conn.execute(query, params)]


def get_workflow(workflow_id: int, path=DB_PATH, *,
                 account_id: Optional[int]) -> Optional[dict[str, Any]]:
    """One canvas, if it is this account's; None otherwise, the same
    answer as for a missing id."""
    with connect(path) as conn:
        raw = conn.execute(
            "SELECT * FROM workflows WHERE id = ? AND account_id IS ?",
            (workflow_id, account_id)).fetchone()
    return _row(dict(raw), with_graph=True) if raw else None


# --- the default template ---------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_ENHANCE_SYSTEM = (
    "You are a prompt enhancement assistant. Take the user's simple prompt "
    "and expand it with vivid, descriptive details. Output only the "
    "enhanced prompt, nothing else.")


def _enhance_system_text() -> str:
    """The template's System Prompt text lives in prompts/ like every
    other prompt (the highest-frequency edit surface); the inline
    fallback only exists so a trimmed checkout still seeds."""
    try:
        text = (PROJECT_ROOT / "prompts" / "enhance_system.txt").read_text().strip()
        return text or DEFAULT_ENHANCE_SYSTEM
    except OSError:
        return DEFAULT_ENHANCE_SYSTEM


def default_template() -> dict:
    """The typical workflow, pre-wired: System Prompt + User Prompt ->
    Gemini Flash enhance -> Nano Banana image. Hand-authored in
    LiteGraph's own serialize() format so graph.configure() loads it
    exactly like a saved drawing."""
    return {
        "last_node_id": 4, "last_link_id": 3,
        "nodes": [
            {"id": 1, "type": "zpf/system_prompt", "title": "System Prompt",
             "pos": [60, 120], "size": [300, 230], "flags": {}, "order": 0,
             "mode": 0,
             "outputs": [{"name": "text", "type": "text", "links": [1]}],
             "properties": {"text": _enhance_system_text()}},
            {"id": 2, "type": "zpf/user_prompt", "title": "User Prompt",
             "pos": [60, 420], "size": [300, 230], "flags": {}, "order": 1,
             "mode": 0,
             "outputs": [{"name": "text", "type": "text", "links": [2]}],
             "properties": {"text": ""}},
            {"id": 3, "type": "zpf/enhance", "title": "Gemini 2.5 Flash",
             "pos": [450, 200], "size": [300, 220], "flags": {}, "order": 2,
             "mode": 0,
             "inputs": [{"name": "system", "type": "text", "link": 1},
                        {"name": "user", "type": "text", "link": 2},
                        {"name": "image", "type": "image", "link": None}],
             "outputs": [{"name": "text", "type": "text", "links": [3]}],
             "properties": {}},
            {"id": 4, "type": "zpf/nano_banana", "title": "Nano Banana",
             "pos": [840, 200], "size": [300, 260], "flags": {}, "order": 3,
             "mode": 0,
             "inputs": [{"name": "prompt", "type": "text", "link": 3},
                        {"name": "image", "type": "image", "link": None}],
             "outputs": [{"name": "image", "type": "image", "links": None}],
             "properties": {}},
        ],
        "links": [[1, 1, 0, 3, 0, "text"],
                  [2, 2, 0, 3, 1, "text"],
                  [3, 3, 0, 4, 0, "text"]],
        "groups": [], "config": {}, "version": 0.4,
    }


def seed_default(path=DB_PATH) -> Optional[int]:
    """Seed the "Prompt enhancement" template once, so the Workflows
    canvas opens onto the typical workflow instead of an empty grid.
    Brandless (shared across brands), idempotent on the name -- a
    deleted template stays deleted only while other workflows exist;
    an entirely empty table reseeds, the evalstore pattern.

    An installation-level seed, so its idempotence checks are the two
    statements the static tenancy test allows by name. The row it
    plants belongs to the bootstrap account (None on a database not yet
    seeded, and accounts.seed claims it then) -- the starter canvas is
    the operator's, not a template every tenant is handed."""
    init(path)
    with connect(path) as conn:
        existing = conn.execute(
            "SELECT id FROM workflows WHERE name = ?",
            ("Prompt enhancement",)).fetchone()
        if existing:
            return None
        any_row = conn.execute("SELECT id FROM workflows LIMIT 1").fetchone()
        if any_row:
            return None
        owner = bootstrap_account_id(conn)
    return create_workflow("Prompt enhancement", default_template(),
                           brand=None, path=path, account_id=owner)

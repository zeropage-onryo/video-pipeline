"""
Saved Workflows: the node graphs the /ui Workflows canvas builds.

A workflow is nodes + positions + edges + each node's config, exactly
the JSON LiteGraph's serialize()/configure() produce and consume, so
this module is storage, not a serialization format of its own. Extends
db.py in its own module (own SCHEMA, own init), the preprod.py pattern.

Execution lives elsewhere (app/workflow_runner.py); a row here is only
the drawing. Deleting one deletes a saved graph, never a render -- the
generations table keeps every attempt regardless.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .db import DB_PATH, _now, connect

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


def create_workflow(name: str, graph: dict, brand: Optional[str] = None,
                    path=DB_PATH) -> int:
    name = (name or "").strip() or "Untitled workflow"
    now = _now()
    with connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO workflows (created_at, updated_at, brand, name, graph_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, now, brand, name, json.dumps(graph or {})),
        )
        return cursor.lastrowid


def update_workflow(workflow_id: int, name: Optional[str] = None,
                    graph: Optional[dict] = None, path=DB_PATH) -> bool:
    """Update the fields that were passed; absent means unchanged."""
    fields, values = ["updated_at = ?"], [_now()]
    if name is not None and name.strip():
        fields.append("name = ?")
        values.append(name.strip())
    if graph is not None:
        fields.append("graph_json = ?")
        values.append(json.dumps(graph))
    with connect(path) as conn:
        cursor = conn.execute(
            f"UPDATE workflows SET {', '.join(fields)} WHERE id = ?",
            (*values, workflow_id),
        )
        return cursor.rowcount > 0


def delete_workflow(workflow_id: int, path=DB_PATH) -> bool:
    with connect(path) as conn:
        cursor = conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        return cursor.rowcount > 0


def _row(raw: dict, with_graph: bool) -> dict[str, Any]:
    graph = json.loads(raw.pop("graph_json") or "{}")
    if with_graph:
        raw["graph"] = graph
    raw["node_count"] = len(graph.get("nodes") or [])
    return raw


def list_workflows(brand: Optional[str] = None, path=DB_PATH) -> list[dict[str, Any]]:
    """Newest-edited first, graphs left behind -- the picker only needs
    names and sizes, and graph_json is the heavy column. A brand filter
    still includes brandless rows: those are the shared templates (the
    seeded default), visible from every brand."""
    query = "SELECT * FROM workflows"
    params: tuple = ()
    if brand:
        query += " WHERE brand = ? OR brand IS NULL"
        params = (brand,)
    query += " ORDER BY updated_at DESC, id DESC"
    with connect(path) as conn:
        return [_row(dict(r), with_graph=False)
                for r in conn.execute(query, params)]


def get_workflow(workflow_id: int, path=DB_PATH) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        raw = conn.execute("SELECT * FROM workflows WHERE id = ?",
                           (workflow_id,)).fetchone()
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
    an entirely empty table reseeds, the evalstore pattern."""
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
    return create_workflow("Prompt enhancement", default_template(),
                           brand=None, path=path)

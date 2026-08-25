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
    names and sizes, and graph_json is the heavy column."""
    query = "SELECT * FROM workflows"
    params: tuple = ()
    if brand:
        query += " WHERE brand = ?"
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

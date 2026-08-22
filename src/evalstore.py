"""
Durable state for the retrieval-eval surface: the golden query set and
every harness run's scores. Extends db.py in its own module (own
SCHEMA, own init), the preprod.py pattern.

The golden set lives in SQLite rather than eval_cases.json so the /ui
Evals view can add a query straight from the probe without a git
commit; on first init the table is seeded FROM eval_cases.json so the
CI gate's cases and the interactive set start identical. A run row
records the metrics AND the config + per-query breakdown that produced
them -- a score is meaningless without knowing which query set and
which retrieval config it came from.
"""
import json
from pathlib import Path
from typing import Any, Optional

from . import db
from .db import connect

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_CASES_PATH = PROJECT_ROOT / "eval_cases.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_golden (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    query         TEXT NOT NULL UNIQUE,
    relevant_json TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    label        TEXT NOT NULL,
    k            INTEGER NOT NULL,
    n            INTEGER NOT NULL,
    hit_rate     REAL NOT NULL,
    mrr          REAL NOT NULL,
    p50_ms       INTEGER,
    config_json  TEXT,
    results_json TEXT NOT NULL
);
"""


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init(path=db.DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        empty = conn.execute("SELECT COUNT(*) FROM eval_golden").fetchone()[0] == 0
    if empty and SEED_CASES_PATH.is_file():
        try:
            cases = json.loads(SEED_CASES_PATH.read_text())
        except (ValueError, OSError):
            return
        for case in cases:
            if case.get("query") and case.get("relevant"):
                add_golden(case["query"], case["relevant"], source="seed", path=path)


def add_golden(query: str, relevant: list, source: str = "manual",
               path=db.DB_PATH) -> int:
    query = (query or "").strip()
    relevant = [str(r).strip() for r in (relevant or []) if str(r).strip()]
    if not query:
        raise ValueError("a golden query needs the query text")
    if not relevant:
        raise ValueError("a golden query needs at least one relevant source")
    with connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO eval_golden (created_at, query, relevant_json, source) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(query) DO UPDATE SET relevant_json = excluded.relevant_json",
            (_now(), query, json.dumps(relevant), source),
        )
        if cursor.lastrowid:
            return cursor.lastrowid
        row = conn.execute(
            "SELECT id FROM eval_golden WHERE query = ?", (query,)
        ).fetchone()
        return row["id"]


def list_golden(path=db.DB_PATH) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM eval_golden ORDER BY id DESC")]
    for row in rows:
        row["relevant"] = json.loads(row.pop("relevant_json"))
    return rows


def delete_golden(golden_id: int, path=db.DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("DELETE FROM eval_golden WHERE id = ?", (golden_id,))


def save_run(label: str, result: dict, p50_ms: Optional[int] = None,
             config: Optional[dict] = None, path=db.DB_PATH) -> int:
    """result is rag_eval.evaluate()'s dict, stored whole."""
    with connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO eval_runs (created_at, label, k, n, hit_rate, mrr, "
            "p50_ms, config_json, results_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), label, result["k"], result["n"], result["hit_rate"],
             result["mrr"], p50_ms,
             json.dumps(config) if config else None,
             json.dumps(result["per_query"])),
        )
        return cursor.lastrowid


def list_runs(path=db.DB_PATH) -> list[dict[str, Any]]:
    """Oldest first -- the history chart reads left to right."""
    with connect(path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, created_at, label, k, n, hit_rate, mrr, p50_ms, "
            "config_json FROM eval_runs ORDER BY id ASC")]
    for row in rows:
        raw = row.pop("config_json", None)
        row["config"] = json.loads(raw) if raw else None
    return rows


def get_run(run_id: int, path=db.DB_PATH) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["per_query"] = json.loads(run.pop("results_json"))
    raw = run.pop("config_json", None)
    run["config"] = json.loads(raw) if raw else None
    return run

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
    results_json TEXT NOT NULL,
    mode         TEXT NOT NULL DEFAULT 'base',
    base_hit_rate REAL,
    base_mrr      REAL,
    requery_rate  REAL,
    requery_success_rate REAL,
    avg_score_improvement REAL,
    requery_adoption_rate REAL,
    requery_expected_source_rate REAL,
    library_count INTEGER,
    library_fingerprint TEXT,
    set_fingerprint TEXT
);

CREATE TABLE IF NOT EXISTS crag_retrievals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL,
    original_query TEXT NOT NULL,
    rewritten_query TEXT,
    initial_score  REAL,
    retry_score    REAL,
    final_score    REAL,
    score_change   REAL,
    rewrite_attempted INTEGER NOT NULL DEFAULT 0,
    requery_triggered INTEGER NOT NULL DEFAULT 0,
    score_improved INTEGER NOT NULL DEFAULT 0,
    rewrite_adopted INTEGER NOT NULL DEFAULT 0,
    threshold      REAL,
    domain_json    TEXT,
    project        TEXT,
    library_count  INTEGER,
    library_fingerprint TEXT,
    error          TEXT
);

CREATE INDEX IF NOT EXISTS idx_crag_retrievals_created
    ON crag_retrievals (created_at);
"""

RUN_COLUMNS = {
    "mode": "TEXT NOT NULL DEFAULT 'base'",
    "base_hit_rate": "REAL", "base_mrr": "REAL",
    "requery_rate": "REAL", "requery_success_rate": "REAL",
    "avg_score_improvement": "REAL", "requery_adoption_rate": "REAL",
    "requery_expected_source_rate": "REAL", "library_count": "INTEGER",
    "library_fingerprint": "TEXT", "set_fingerprint": "TEXT",
}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_schema(path) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute(
            "PRAGMA table_info(eval_runs)")}
        for name, definition in RUN_COLUMNS.items():
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE eval_runs ADD COLUMN {name} {definition}")


def init(path=db.DB_PATH) -> None:
    _ensure_schema(path)
    with connect(path) as conn:
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
            "p50_ms, config_json, results_json, mode, base_hit_rate, base_mrr, "
            "requery_rate, requery_success_rate, avg_score_improvement, "
            "requery_adoption_rate, requery_expected_source_rate, library_count, "
            "library_fingerprint, set_fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), label, result["k"], result["n"], result["hit_rate"],
             result["mrr"], p50_ms,
             json.dumps(config) if config else None,
             json.dumps(result["per_query"]), result.get("mode", "base"),
             result.get("base_hit_rate"), result.get("base_mrr"),
             result.get("requery_rate"), result.get("requery_success_rate"),
             result.get("avg_score_improvement"),
             result.get("requery_adoption_rate"),
             result.get("requery_expected_source_rate"),
             result.get("library_count"), result.get("library_fingerprint"),
             result.get("set_fingerprint")),
        )
        return cursor.lastrowid


def list_runs(path=db.DB_PATH) -> list[dict[str, Any]]:
    """Oldest first -- the history chart reads left to right."""
    with connect(path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, created_at, label, k, n, hit_rate, mrr, p50_ms, "
            "config_json, mode, base_hit_rate, base_mrr, requery_rate, "
            "requery_success_rate, avg_score_improvement, requery_adoption_rate, "
            "requery_expected_source_rate, library_count, library_fingerprint, "
            "set_fingerprint FROM eval_runs ORDER BY id ASC")]
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


def log_crag_retrieval(event: dict, path=None) -> int:
    """Persist one production CRAG decision without storing document text."""
    path = db.DB_PATH if path is None else path
    _ensure_schema(path)
    with connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO crag_retrievals (created_at, original_query, "
            "rewritten_query, initial_score, retry_score, final_score, "
            "score_change, rewrite_attempted, requery_triggered, score_improved, "
            "rewrite_adopted, threshold, domain_json, project, library_count, "
            "library_fingerprint, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?)",
            (_now(), event.get("original_query", ""),
             event.get("rewritten_query"), event.get("initial_score"),
             event.get("retry_score"), event.get("final_score"),
             event.get("score_change"), int(bool(event.get("rewrite_attempted"))),
             int(bool(event.get("requery_triggered"))),
             int(bool(event.get("score_improved"))),
             int(bool(event.get("rewrite_adopted"))), event.get("threshold"),
             json.dumps(event.get("domain")) if event.get("domain") is not None else None,
             event.get("project"), event.get("library_count"),
             event.get("library_fingerprint"), event.get("error")),
        )
        return cursor.lastrowid


def crag_summary(path=None) -> dict:
    """Aggregate production telemetry for the private Dev Studio."""
    path = db.DB_PATH if path is None else path
    _ensure_schema(path)
    with connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, SUM(requery_triggered) AS retried, "
            "SUM(score_improved) AS improved, SUM(rewrite_adopted) AS adopted, "
            "AVG(CASE WHEN requery_triggered = 1 THEN score_change END) AS avg_lift "
            "FROM crag_retrievals").fetchone()
    total = row["total"] or 0
    retried = row["retried"] or 0
    return {
        "total": total, "retried": retried,
        "requery_rate": round(retried / total, 4) if total else None,
        "requery_success_rate": round((row["improved"] or 0) / retried, 4)
        if retried else None,
        "requery_adoption_rate": round((row["adopted"] or 0) / retried, 4)
        if retried else None,
        "avg_score_improvement": round(row["avg_lift"], 4)
        if row["avg_lift"] is not None else None,
    }

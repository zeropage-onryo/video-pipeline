"""Persistent Asset Bank records for successful AI renders.

Generated media is different from a photographed location, character, or
prop, but it still belongs in the same Asset Bank.  This table keeps the
durable media URL and the exact prompt/model metadata next to the existing
``generations`` attempt log.  Its text twin is written to the RAG ``assets``
shelf so later retrieval can find a render by what it depicts.

Asset publication is deliberately best-effort: a completed, paid render must
still be returned when SQLite or the vector store is temporarily unavailable.

OWNED (db.OWNED_TABLES, merged 2026-09-02): a generated asset is one
account's paid render, so it carries `account_id` and every read says whose.
The `project` column stays the brand label the render was made under; the
RAG chunk's `project` is the TENANT that owns it (src/rag.py's rule), so a
tenant's own renders rank first on the assets shelf without hiding anyone's.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import db, rag

SCHEMA = """
CREATE TABLE IF NOT EXISTS generated_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    generation_id   INTEGER NOT NULL UNIQUE,
    tool            TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    media_kind      TEXT    NOT NULL,
    prompt          TEXT    NOT NULL,
    media_url       TEXT    NOT NULL,
    output_path     TEXT,
    project         TEXT,
    concept_id      INTEGER,
    shot_n          INTEGER,
    metadata_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_generated_assets_created
    ON generated_assets (created_at DESC);
"""


def init(path: Path | str = db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.executescript(SCHEMA)
        db.own_table(conn, "generated_assets")


def _label(tool: str, model: str) -> str:
    if tool == "nano":
        return "Nano Banana Pro" if "pro" in model.lower() else "Nano Banana"
    if tool == "runway":
        return "Runway"
    return tool.replace("_", " ").title()


def _rag_text(*, tool: str, model: str, media_kind: str, prompt: str,
              metadata: dict) -> str:
    lines = [
        f"GENERATED {media_kind.upper()}",
        f"Provider: {_label(tool, model)}",
        f"Model: {model}",
        f"Prompt: {prompt}",
    ]
    for key in ("ratio", "duration", "references", "concept_id", "shot_n"):
        value = metadata.get(key)
        if value is not None and value != "":
            lines.append(f"{key.replace('_', ' ').title()}: {value}")
    return "\n".join(lines)


def _ingest(asset_id: int, *, generation_id: int, tool: str, model: str, media_kind: str,
            prompt: str, project: Optional[str], metadata: dict) -> dict:
    """Write the prompt description to the shared assets shelf."""
    try:
        conn = rag.connect()
        try:
            rag.init_store(conn)
            written = rag.ingest_records(
                [{
                    "source": f"assets/generated-{asset_id}",
                    "text": _rag_text(tool=tool, model=model,
                                      media_kind=media_kind, prompt=prompt,
                                      metadata=metadata),
                    "domain": "assets",
                    "project": project,
                    "source_ref": f"generation:{generation_id}",
                }],
                rag.make_client(), conn,
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {"ok": True, "chunks": written, "error": None}
    except Exception as exc:
        return {"ok": False, "chunks": 0, "error": str(exc)}


def record(*, generation_id: int, tool: str, model: str, media_kind: str,
           prompt: str, media_url: str, output_path: Optional[str] = None,
           project: Optional[str] = None, concept_id: Optional[int] = None,
           shot_n: Optional[int] = None, metadata: Optional[dict] = None,
           path: Path | str = db.DB_PATH,
           account_id: Optional[int]) -> dict[str, Any]:
    """Create or refresh one generated Asset Bank item and index its prompt.
    `account_id` is keyword-only with no default: a render nobody owns is a
    render nobody can see, or everybody can."""
    if media_kind not in ("image", "video"):
        raise ValueError("media_kind must be image or video")
    prompt = (prompt or "").strip()
    media_url = (media_url or "").strip()
    if not prompt or not media_url:
        raise ValueError("a generated asset needs both prompt and media URL")
    meta = dict(metadata or {})
    if concept_id is not None:
        meta.setdefault("concept_id", concept_id)
    if shot_n is not None:
        meta.setdefault("shot_n", shot_n)

    init(path)
    with db.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO generated_assets
                (created_at, generation_id, tool, model, media_kind, prompt,
                 media_url, output_path, project, concept_id, shot_n, metadata_json,
                 account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(generation_id) DO UPDATE SET
                tool=excluded.tool, model=excluded.model,
                media_kind=excluded.media_kind, prompt=excluded.prompt,
                media_url=excluded.media_url, output_path=excluded.output_path,
                project=excluded.project, concept_id=excluded.concept_id,
                shot_n=excluded.shot_n, metadata_json=excluded.metadata_json,
                account_id=excluded.account_id
            """,
            (db._now(), generation_id, tool, model, media_kind, prompt,
             media_url, output_path, project, concept_id, shot_n,
             json.dumps(meta, sort_keys=True), account_id),
        )
        # lastrowid is untrustworthy after an upsert that took DO UPDATE
        row = conn.execute(
            "SELECT id FROM generated_assets WHERE generation_id = ? AND account_id IS ?",
            (generation_id, account_id),
        ).fetchone()
        asset_id = int(row["id"])

    from . import accounts
    return {
        "id": asset_id,
        "rag": _ingest(asset_id, generation_id=generation_id,
                       tool=tool, model=model,
                       media_kind=media_kind, prompt=prompt,
                       project=accounts.slug_of(account_id, path=path),
                       metadata=meta),
    }


def record_best_effort(**kwargs) -> dict[str, Any]:
    """Never let Asset Bank bookkeeping turn a successful render into failure."""
    try:
        return record(**kwargs)
    except Exception as exc:
        return {"id": None, "rag": {"ok": False, "chunks": 0,
                                      "error": str(exc)}}


def list_all(path: Path | str = db.DB_PATH, *,
             account_id: Optional[int]) -> list[dict[str, Any]]:
    """This account's generated assets, newest first."""
    init(path)
    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM generated_assets WHERE account_id IS ? ORDER BY id DESC",
            (account_id,),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except (TypeError, ValueError):
            item["metadata"] = {}
            item.pop("metadata_json", None)
        item["provider"] = _label(item["tool"], item["model"])
        items.append(item)
    return items

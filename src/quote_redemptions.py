"""
Which studio quotes have been spent (2026-10-08, docs/tasks/
task-mcp-studio-v2.md step 1).

The MCP studio surface approves a render with a signed quote
(`pricing.sign_studio`): the person sees a price in credits, says yes in
chat, and Claude calls again with the token. A signature proves the price
and the arguments; it cannot prove the token has not been used. Without a
record, the same yes buys the same image twice -- a retry after a slow
reply, a model that calls twice, a conversation re-run from the top.

So the first redemption CLAIMS the token here, before the job starts, and
the response it got (the job id) is stored with it. A second call with
the same token is handed that first response and starts nothing. The
claim is one `INSERT ... ON CONFLICT DO NOTHING` on the token id, so two
calls racing each other cannot both win.

A claim is made only once every check has passed (the signature, the
arguments, the balance): a refused call leaves the token unspent, so a
person who tops up can still use it within the hour. A claim whose job
could not even be started is forgotten again -- nothing ran, nothing was
held.

OWNED (db.OWNED_TABLES): a redemption is one account's spend. Nothing
here holds or moves credit; src/charge.py does, inside the job.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS quote_redemptions (
    token_id      TEXT PRIMARY KEY,
    account_id    BIGINT,
    tool          TEXT    NOT NULL,
    credits       INTEGER,
    job_id        BIGINT,
    response_json TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init(dsn: Optional[str] = None) -> None:
    """Create and own the table. Idempotent."""
    with db.connect(dsn) as conn:
        conn.execute(SCHEMA)
        db.own_table(conn, "quote_redemptions")


def claim(token_id: str, account_id: Optional[int], *, tool: str,
          credits: Optional[int] = None, dsn: Optional[str] = None) -> Optional[dict]:
    """Claim a token for this account. None when this call won it (go
    ahead and start the work); otherwise the earlier redemption --
    `{"tool", "job_id", "response", "created_at"}`, `response` None while
    the first call is still starting it. Raises on a database error: an
    approval that cannot be recorded must not be spent -- the table is
    made by init() where a server starts (the app's lifespan, the stdio
    entry point), never here, on the money path."""
    with db.connect(dsn) as conn:
        won = conn.execute(
            "INSERT INTO quote_redemptions (token_id, account_id, tool, credits) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (token_id) DO NOTHING RETURNING token_id",
            (token_id, account_id, tool, credits)).fetchone()
        if won:
            return None
        row = conn.execute(
            "SELECT tool, job_id, response_json, created_at FROM quote_redemptions "
            "WHERE token_id = %s AND account_id IS NOT DISTINCT FROM %s",
            (token_id, account_id)).fetchone()
    if row is None:      # a token id another account holds: refused all the same
        return {"tool": tool, "job_id": None, "response": None, "created_at": None}
    return {"tool": row["tool"], "job_id": row["job_id"],
            "response": json.loads(row["response_json"]) if row["response_json"] else None,
            "created_at": row["created_at"]}


def record(token_id: str, account_id: Optional[int], response: dict[str, Any],
           dsn: Optional[str] = None) -> None:
    """What the first redemption got back -- the job id, or the inline
    result -- so a second call can be handed the same answer."""
    job_id = response.get("job_id") if isinstance(response, dict) else None
    with db.connect(dsn) as conn:
        conn.execute(
            "UPDATE quote_redemptions SET job_id = %s, response_json = %s "
            "WHERE token_id = %s AND account_id IS NOT DISTINCT FROM %s",
            (job_id if isinstance(job_id, int) else None,
             json.dumps(response, default=str), token_id, account_id))


def forget(token_id: str, account_id: Optional[int], dsn: Optional[str] = None) -> None:
    """Give a claim back when the work could not even be started: nothing
    ran and nothing was held, so the person's yes is still good."""
    with db.connect(dsn) as conn:
        conn.execute(
            "DELETE FROM quote_redemptions "
            "WHERE token_id = %s AND account_id IS NOT DISTINCT FROM %s AND job_id IS NULL",
            (token_id, account_id))


__all__ = ["init", "claim", "record", "forget"]

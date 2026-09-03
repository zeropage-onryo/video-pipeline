"""
Per-account API credentials (BYOK) -- backlog #10.

Tenancy already threads account_id through every render path
(generate_for_shot, generations_today, the daily-cap checks). This module
is the other half: an encrypted table so a pilot user's Runway / Veo /
Higgsfield / Midjourney / Gemini calls bill *their* account, not Mike's,
and a resolver every provider module's client-maker calls first.

Falls back to the environment when an account has no key of its own --
so this is safe to wire in before anyone has entered a key: Mike's own
account_id keeps working exactly as today, reading os.environ like it
always has.

Table lives in the same Postgres database as everything else (it was
written on 2026-09-03, the night the database moved, and ported with it)
-- one more reason RLS on this table specifically is non-negotiable: a
key is a credential, not a preference. OWNED (db.OWNED_TABLES): every
read and write names the account.

Encryption: Fernet (AES-128-CBC + HMAC) keyed by ACCOUNT_KEYS_SECRET, a
32-byte urlsafe-base64 key generated once and never committed. Losing it
means every stored key must be re-entered -- there is no recovery, which
is the point: the alternative is a plaintext key column that ends up in
every backup and every `cp data/pipeline.db /tmp/debug.db`.

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

CLI:
    venv/bin/python -m src.account_keys set   <account_id> <provider> <key> [<key2>]
    venv/bin/python -m src.account_keys list  <account_id>
    venv/bin/python -m src.account_keys clear <account_id> <provider>
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Optional

from . import db as _db

# provider -> the env var name(s) key_for() falls back to when the account
# has not entered its own key, in the order the provider's own _make_client
# / _credentials functions already read them. Order matters for higgsfield
# (HIGGSFIELD_* is the documented name, HF_* is the historical fallback).
PROVIDER_ENV_FALLBACK: dict[str, tuple[str, ...]] = {
    "runway": ("RUNWAYML_API_SECRET",),
    "veo": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "higgsfield": ("HIGGSFIELD_API_KEY_ID", "HIGGSFIELD_API_KEY_SECRET",
                   "HF_API_KEY_ID", "HF_API_KEY_SECRET"),
    "midjourney": ("ACEDATA_API_KEY",),
}

# how many key fields each provider needs from account_keys.set(), in the
# order key_for() returns them -- one string for a single-secret provider,
# two for higgsfield's id+secret pair.
PROVIDER_FIELDS: dict[str, tuple[str, ...]] = {
    "runway": ("api_secret",),
    "veo": ("api_key",),
    "gemini": ("api_key",),
    "higgsfield": ("api_key_id", "api_key_secret"),
    "midjourney": ("api_key",),
}


def _fernet():
    from cryptography.fernet import Fernet  # noqa: F401
    secret = os.environ.get("ACCOUNT_KEYS_SECRET")
    if not secret:
        raise RuntimeError(
            "ACCOUNT_KEYS_SECRET not set -- generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and put it in .env. "
            "Never rotate this without a re-entry plan: existing rows "
            "become unreadable, not just unencrypted."
        )
    return Fernet(secret.encode())


SCHEMA = """
CREATE TABLE IF NOT EXISTS account_keys (
    account_id  BIGINT NOT NULL,
    provider    TEXT   NOT NULL,
    ciphertext  TEXT   NOT NULL,   -- Fernet token, base64 JSON of PROVIDER_FIELDS
    updated_at  TEXT   NOT NULL,   -- written by the caller (db._now), never a DB default
    PRIMARY KEY (account_id, provider)
);
"""


def _ensure(conn) -> None:
    """The table, on an open connection -- every function below calls it
    first, so the first key stored on a fresh database creates it."""
    conn.execute(SCHEMA)
    _db.own_table(conn, "account_keys")   # the FK to accounts(id)


def init(dsn: Optional[str] = None) -> None:
    """The module-level init every other schema owner has, for the app
    lifespan and the schema audit."""
    with _db.connect(dsn) as conn:
        _ensure(conn)


def set_key(account_id: int, provider: str, *values: str,
            dsn: Optional[str] = None) -> None:
    fields = PROVIDER_FIELDS.get(provider)
    if not fields:
        raise ValueError(f"unknown provider {provider!r}; add it to "
                          f"PROVIDER_FIELDS and PROVIDER_ENV_FALLBACK first")
    if len(values) != len(fields):
        raise ValueError(f"{provider} needs {len(fields)} value(s) "
                          f"({', '.join(fields)}), got {len(values)}")
    payload = json.dumps(dict(zip(fields, values)))
    token = _fernet().encrypt(payload.encode()).decode()
    with _db.connect(dsn) as conn:
        _ensure(conn)
        conn.execute(
            "INSERT INTO account_keys (account_id, provider, ciphertext, updated_at) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (account_id, provider) DO UPDATE SET "
            "ciphertext = excluded.ciphertext, updated_at = excluded.updated_at",
            (account_id, provider, token, _db._now()),
        )


def clear_key(account_id: int, provider: str, dsn: Optional[str] = None) -> bool:
    with _db.connect(dsn) as conn:
        _ensure(conn)
        cur = conn.execute(
            "DELETE FROM account_keys WHERE account_id = %s AND provider = %s",
            (account_id, provider),
        )
        return cur.rowcount > 0


def list_providers(account_id: int, dsn: Optional[str] = None) -> list[dict]:
    with _db.connect(dsn) as conn:
        _ensure(conn)
        rows = conn.execute(
            "SELECT provider, updated_at FROM account_keys "
            "WHERE account_id = %s ORDER BY provider",
            (account_id,),
        ).fetchall()
    return [{"provider": r[0], "updated_at": r[1]} for r in rows]


def key_for(account_id: Optional[int], provider: str,
            dsn: Optional[str] = None) -> Optional[dict]:
    """
    The credential a render call should use for this account: the
    account's own stored key if it has one, else the environment (today's
    behaviour, unchanged). Returns a dict keyed by PROVIDER_FIELDS, e.g.
    {"api_secret": "..."} for runway or {"api_key_id": "...",
    "api_key_secret": "..."} for higgsfield -- or None if neither the
    account nor the environment has a usable value, exactly like the
    provider's own _make_client()/_credentials() returning nothing today.

    account_id=None (unowned / dev-console rows) always falls through to
    the environment -- there is no account to own a key.
    """
    fields = PROVIDER_FIELDS.get(provider)
    if not fields:
        raise ValueError(f"unknown provider {provider!r}")

    if account_id is not None:
        with _db.connect(dsn) as conn:
            _ensure(conn)
            row = conn.execute(
                "SELECT ciphertext FROM account_keys "
                "WHERE account_id = %s AND provider = %s",
                (account_id, provider),
            ).fetchone()
        if row:
            payload = json.loads(_fernet().decrypt(row[0].encode()).decode())
            if all(payload.get(f) for f in fields):
                return payload

    env_names = PROVIDER_ENV_FALLBACK.get(provider, ())
    env_values = [os.environ.get(n) for n in env_names]
    if len(fields) == 1:
        value = next((v for v in env_values if v), None)
        return {fields[0]: value} if value else None
    if len(fields) == len(env_names) and all(env_values):
        return dict(zip(fields, env_values))
    return None


def redact(provider: str) -> str:
    """What _safe_error() should show instead of a real key: which slot
    would have been used, never the value, whether it came from the
    account's own key or the environment fallback."""
    return f"<{provider} key redacted>"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="account_keys")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_set = sub.add_parser("set", help="store an account's key for a provider")
    p_set.add_argument("account_id", type=int)
    p_set.add_argument("provider", choices=sorted(PROVIDER_FIELDS))
    p_set.add_argument("values", nargs="+",
                        help="one value, or two for higgsfield (id then secret)")

    p_list = sub.add_parser("list", help="which providers an account has keys for")
    p_list.add_argument("account_id", type=int)

    p_clear = sub.add_parser("clear", help="remove an account's key for a provider")
    p_clear.add_argument("account_id", type=int)
    p_clear.add_argument("provider", choices=sorted(PROVIDER_FIELDS))

    args = ap.parse_args(argv)
    if args.cmd == "set":
        set_key(args.account_id, args.provider, *args.values)
        print(f"stored {args.provider} key for account {args.account_id}")
    elif args.cmd == "list":
        rows = list_providers(args.account_id)
        if not rows:
            print("no keys stored")
        for r in rows:
            print(f"  {r['provider']:<12} updated {r['updated_at']}")
    elif args.cmd == "clear":
        removed = clear_key(args.account_id, args.provider)
        print("removed" if removed else "nothing stored")


if __name__ == "__main__":
    main()

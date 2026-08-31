#!/usr/bin/env python3
"""
Users, identities, accounts, membership -- the real login's spine.

Executes claude/multi-user-accounts-plan.md's schema: `users` is a
person, `auth_identities` is how that person proves who they are (one
row per OAuth provider, deliberately its own table so adding a provider
is a new row shape, never a schema change), `accounts` is a brand
(zeropage / antihero -- what the hardcoded BRANDS tuple grows up into),
and `account_members` is who may enter which brand.

The gate that matters lives in the shape of this data: a fresh signup
gets a users row and ZERO account_members rows. Membership is granted
by an existing member (manual INSERT for v1), never by signing up --
these are Mike's real accounts, not a public product.

Extends db.py in its own module (own SCHEMA, own init()), the
preprod.py pattern. No password hashing here -- that's the web layer's
job (app/auth.py); this module never sees a plaintext password.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .db import DB_PATH, OWNED_TABLES, backfill_owner, connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    display_name  TEXT,
    avatar_url    TEXT
);

CREATE TABLE IF NOT EXISTS auth_identities (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    provider         TEXT NOT NULL,
    provider_subject TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(provider, provider_subject)
);

CREATE TABLE IF NOT EXISTS accounts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL,
    slug           TEXT NOT NULL UNIQUE,
    display_name   TEXT NOT NULL,
    accent_color   TEXT,
    voice          TEXT,
    house_look     TEXT,
    house_negative TEXT,
    house_aspect   TEXT DEFAULT '9:16',
    never_list     TEXT
);

CREATE TABLE IF NOT EXISTS account_members (
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    role       TEXT NOT NULL DEFAULT 'owner',
    PRIMARY KEY (account_id, user_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def init(path: Path | str = DB_PATH) -> None:
    """Create the auth tables. Run after db.init_db()."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------
# users
# --------------------------------------------------------------------------

def create_user(email: str, password_hash: Optional[str] = None,
                display_name: Optional[str] = None,
                avatar_url: Optional[str] = None,
                path: Path | str = DB_PATH) -> int:
    """One person. Raises sqlite3.IntegrityError on a duplicate email --
    the caller turns that into 'try signing in the other way', it is
    never silently merged."""
    email = email.strip().lower()
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO users (created_at, email, password_hash, display_name, "
            "avatar_url) VALUES (?, ?, ?, ?, ?)",
            (_now(), email, password_hash, display_name, avatar_url),
        )
        return cur.lastrowid


def get_user(user_id: int, path: Path | str = DB_PATH) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str, path: Path | str = DB_PATH) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None


def update_profile(user_id: int, display_name: Optional[str] = None,
                   avatar_url: Optional[str] = None,
                   path: Path | str = DB_PATH) -> None:
    """Fill profile fields from a provider sign-in without clobbering
    what's already there."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE users SET display_name = COALESCE(display_name, ?), "
            "avatar_url = COALESCE(?, avatar_url) WHERE id = ?",
            (display_name, avatar_url, user_id),
        )


# --------------------------------------------------------------------------
# identities
# --------------------------------------------------------------------------

def get_identity(provider: str, provider_subject: str,
                 path: Path | str = DB_PATH) -> Optional[dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM auth_identities WHERE provider = ? AND provider_subject = ?",
            (provider, str(provider_subject)),
        ).fetchone()
        return dict(row) if row else None


def add_identity(user_id: int, provider: str, provider_subject: str,
                 path: Path | str = DB_PATH) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO auth_identities (user_id, provider, provider_subject, "
            "created_at) VALUES (?, ?, ?, ?)",
            (user_id, provider, str(provider_subject), _now()),
        )
        return cur.lastrowid


# --------------------------------------------------------------------------
# accounts + membership
# --------------------------------------------------------------------------

def upsert_account(slug: str, display_name: str, accent_color: Optional[str] = None,
                   path: Path | str = DB_PATH) -> int:
    with connect(path) as conn:
        row = conn.execute("SELECT id FROM accounts WHERE slug = ?", (slug,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO accounts (created_at, slug, display_name, accent_color) "
            "VALUES (?, ?, ?, ?)",
            (_now(), slug, display_name, accent_color),
        )
        return cur.lastrowid


def add_member(account_id: int, user_id: int, role: str = "owner",
               path: Path | str = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO account_members (account_id, user_id, role) "
            "VALUES (?, ?, ?)",
            (account_id, user_id, role),
        )


def memberships(user_id: int, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    """The accounts this user may enter. Empty list == signed in but no
    access -- the state the membership gate renders, never auto-fixed."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT a.*, m.role FROM accounts a "
            "JOIN account_members m ON m.account_id = a.id "
            "WHERE m.user_id = ? ORDER BY a.slug",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# seed
# --------------------------------------------------------------------------

def seed(email: str, password_hash: Optional[str] = None,
         display_name: str = "Mike", path: Path | str = DB_PATH) -> dict[str, Any]:
    """
    The once-only bootstrap: Mike's user, the two real accounts, and
    owner membership on both. Idempotent -- re-running finds instead of
    duplicating. Brand metadata (labels, accents) mirrors app.main's
    BRAND_META so the picker looks like the brand pill always has.
    """
    init(path)
    user = get_user_by_email(email, path=path)
    user_id = user["id"] if user else create_user(
        email, password_hash=password_hash, display_name=display_name, path=path)

    zeropage = upsert_account("zeropage", "Zero Page Films", "#8b5cf6", path=path)
    antihero = upsert_account("antihero", "ANTIHERO", "#d64550", path=path)
    add_member(zeropage, user_id, path=path)
    add_member(antihero, user_id, path=path)
    claimed = claim_unowned_rows(path=path)
    return {"user_id": user_id, "accounts": [zeropage, antihero],
            "claimed": claimed}


def claim_unowned_rows(account_id: Optional[int] = None,
                       path: Path | str = DB_PATH) -> dict[str, int]:
    """Give every pre-tenancy row an owner. Returns {table: rows claimed}.

    Each module's own init() backfills too, but init() runs before there
    is an account to backfill *to* on a fresh database -- so seeding is
    the other end of that. Tables that do not exist yet are skipped
    rather than created: this claims ownership, it does not define
    schema.
    """
    claimed: dict[str, int] = {}
    with connect(path) as conn:
        present = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in OWNED_TABLES:
            if table not in present:
                continue
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "account_id" not in cols:
                continue
            n = backfill_owner(conn, table, account_id)
            if n:
                claimed[table] = n
    return claimed


def resolve_account(slug: Optional[str] = None,
                    path: Path | str = DB_PATH) -> Optional[int]:
    """Turn a `--account <slug>` into an id, or fall back to the oldest
    account on the database.

    For ENTRY POINTS only -- CLIs, the nightly run, anything with no
    session behind it. Library functions take `account_id` as a required
    argument on purpose; a fallback buried in the data layer is the leak
    that rule exists to prevent. Here it is deliberate and in one place.

    Returns None on a database with no accounts -- including one where
    the table does not exist yet, which a fresh install genuinely is.
    The caller then operates on the unowned pool, which is exactly what
    such a database holds. Raising there instead would turn "nothing has
    been seeded" into a crash in every CLI and MCP tool, which is what
    it did until a full-suite run happened to schedule the mcp_server
    tests onto a worker with an unseeded database.
    """
    with connect(path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'accounts'"
        ).fetchone() is None:
            if slug:
                raise ValueError(f"no account {slug!r} -- no accounts exist yet")
            return None
        if slug:
            row = conn.execute(
                "SELECT id FROM accounts WHERE slug = ?", (slug.strip().lower(),)
            ).fetchone()
            if row is None:
                known = [r["slug"] for r in conn.execute(
                    "SELECT slug FROM accounts ORDER BY slug")]
                raise ValueError(
                    f"no account {slug!r}" + (f" -- try one of {known}" if known else ""))
            return int(row["id"])
        row = conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()
        return int(row["id"]) if row and row["id"] is not None else None


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="accounts",
        description="Auth tables + the once-only seed of Mike's user and "
                    "the two brand accounts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_seed = sub.add_parser("seed", help="create user + zeropage/antihero accounts")
    p_seed.add_argument("email")
    p_seed.add_argument("--password", default=None,
                        help="set a login password (hashed, never stored raw)")
    p_seed.add_argument("--name", default="Mike")
    args = parser.parse_args(argv)

    password_hash = None
    if args.password:
        if len(args.password) < 8:
            print("password must be at least 8 characters", file=sys.stderr)
            sys.exit(1)
        from argon2 import PasswordHasher
        password_hash = PasswordHasher().hash(args.password)

    result = seed(args.email, password_hash=password_hash, display_name=args.name)
    print(f"seeded user {result['user_id']} ({args.email}) as owner of "
          f"zeropage + antihero"
          + ("" if password_hash else
             " -- no password set; first Google/Discord sign-in on this "
             "email will attach an identity"))


if __name__ == "__main__":
    main()

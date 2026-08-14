"""
Inspiration accounts: creators whose proven content formula seeds the
concept generator. Each account carries a distilled *pattern* profile
(hooks, formats, grade, what travels) -- the generator riffs on it,
adapted to the brand's own grade and star, never copying the creator.

Own table, own init(), one shared SQLite file -- same shape as
autonomy.py / winners.py. Seeded once (init auto-loads the researched
defaults when the table is empty); add more by hand as you profile them.

This deliberately does NOT use the RAG store: it's a small, explicit set
the user points at ("spin off ideas from @x"), so a plain SQLite table +
direct prompt injection is simpler, hermetic in tests, and needs no
Postgres. RAG grounding stays for the broad reference library.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspiration_accounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    handle     TEXT NOT NULL UNIQUE,
    note       TEXT,
    profile    TEXT NOT NULL
);
"""

# The three verified profiles from 2026-08-12 research. Distilled to the
# transferable formula, not the whole write-up. Seeded when the table is
# empty, so a fresh install has them without a manual step.
DEFAULT_ACCOUNTS = [
    {
        "handle": "layed_black",
        "note": "moto / all-black noir aesthetic (Sony-featured, black Ducati Panigale V4)",
        "profile": (
            "One hero machine as a recurring character, obsessively re-shot in new "
            "light rather than many subjects. All-black low-key noir grade: crushed "
            "blacks, chiaroscuro, fast-prime shallow depth of field, hard directional "
            "light and headlights-on-at-night as the drama. The image is the hook; "
            "the caption is a terse mood-phrase (a feeling, a season), never a spec "
            "sheet. Subject isolated against negative space; editorial, premium, "
            "instantly recognisable at thumbnail scale."
        ),
    },
    {
        "handle": "manny.walkerrr",
        "note": "viral emotion-over-engine hook (Miami moto/muscle, film-noir)",
        "profile": (
            "Emotion-over-engine hook: cold-open on a static moody night image with a "
            "single one-line emotional text overlay that reframes the machine as "
            "loneliness, self-worth, or devotion -- feelings first, engine second (his "
            "therapy-line reel hit 10M views). Dark low-key grade, black + amber + "
            "steel-blue, night streets, gas stations, garages, silhouettes, macro on "
            "parts. Extreme curation -- a few finished hero pieces, not a daily dump. "
            "One consistent, recognisable world."
        ),
    },
    {
        "handle": "alexisglere",
        "note": "adrenaline subject shot as fine art (B&W, poetic one-line captions)",
        "profile": (
            "Collision of a kinetic subject (sportbike, speed, training) with a "
            "slowed-down fine-art treatment: moody black-and-white, low-key dramatic "
            "shadow, classic Leica composition. Ultra-minimal poetic one-line captions "
            "(mood, not information). High curation, sparse posting. The tension "
            "between adrenaline and calm is the signature -- shoot the fast thing like "
            "it's still."
        ),
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init(path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.executescript(SCHEMA)
        empty = conn.execute("SELECT COUNT(*) FROM inspiration_accounts").fetchone()[0] == 0
    if empty:
        for a in DEFAULT_ACCOUNTS:
            add(a["handle"], a["note"], a["profile"], path=path)


def _clean_handle(handle: str) -> str:
    return (handle or "").strip().lstrip("@").lower()


def add(handle: str, note: str, profile: str, path=db.DB_PATH) -> int:
    handle = _clean_handle(handle)
    if not handle:
        raise ValueError("handle cannot be empty")
    if not (profile or "").strip():
        raise ValueError("an inspiration account needs a profile to riff on")
    with db.connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO inspiration_accounts (created_at, handle, note, profile) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(handle) DO UPDATE SET "
            "note=excluded.note, profile=excluded.profile",
            (_now(), handle, (note or "").strip(), profile.strip()),
        )
        return cur.lastrowid


def list_accounts(path=db.DB_PATH) -> list[dict]:
    with db.connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM inspiration_accounts ORDER BY handle")]


def get(handle: str, path=db.DB_PATH) -> Optional[dict]:
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM inspiration_accounts WHERE handle = ?",
            (_clean_handle(handle),)).fetchone()
        return dict(row) if row else None


def delete(handle: str, path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.execute("DELETE FROM inspiration_accounts WHERE handle = ?",
                     (_clean_handle(handle),))


def combined_grounding(path=db.DB_PATH) -> str:
    """Every account's formula folded into one grounding block, so the
    generator can ground on them AUTOMATICALLY (no per-account button).
    '' when there are none. Injected as reference grounding, not the stored
    spark, so it steers the ideas without polluting what's saved. Never
    raises -- grounding is an enhancement, never a dependency."""
    try:
        accounts = list_accounts(path=path)
    except Exception:
        return ""
    if not accounts:
        return ""
    lines = ["INSPIRATION GROUNDING — riff on these reference creators' proven "
             "formulas, adapted to the brand's grade and star; take the structure "
             "(hook, format, mood, what makes it travel), never copy their exact "
             "subject or a signature that reads as imitation:"]
    for a in accounts:
        note = f" ({a['note']})" if a.get("note") else ""
        lines.append(f"- @{a['handle']}{note}: {a['profile']}")
    return "\n".join(lines)


def grounding_block(account: dict) -> str:
    """The prompt-injection form: the creator's formula, wrapped in the
    hard rule to adapt within the brand's grade, never copy the creator."""
    return (
        "INSPIRATION — riff on this creator's proven formula, adapted to the "
        "brand's own grade and star; take the STRUCTURE (hook, format, mood, "
        "what makes it travel), never copy their exact subject or a signature "
        f"that would read as an imitation:\n@{account['handle']}"
        f"{' (' + account['note'] + ')' if account.get('note') else ''}: "
        f"{account['profile']}"
    )


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Inspiration accounts for the generator.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="load the researched default accounts (if table empty)")
    sub.add_parser("list", help="show stored accounts")
    p_add = sub.add_parser("add", help="add/update an account")
    p_add.add_argument("handle")
    p_add.add_argument("profile")
    p_add.add_argument("--note", default="")
    args = parser.parse_args(argv)

    if args.command == "seed":
        init()
        for a in list_accounts():
            print(f"@{a['handle']} — {a['note']}")
    elif args.command == "list":
        for a in list_accounts():
            print(f"@{a['handle']} — {a['note']}\n    {a['profile'][:100]}...")
    elif args.command == "add":
        add(args.handle, args.note, args.profile)
        print(f"saved @{_clean_handle(args.handle)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

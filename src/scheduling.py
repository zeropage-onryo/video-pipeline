#!/usr/bin/env python3
"""
The publish queue -- the piece Instagram's API doesn't give you.

Meta has no native future-scheduling, so this module owns the clock: a
scheduled_posts table (extending db.py in its own module, the preprod.py
pattern), a pure due-window query, and a worker step cron can invoke.

The split that matters: managing the queue (add, list, move) is NOT
gated -- rows are just intentions. The publish itself always runs
through autopilot.execute, so the three-condition gate, the dry-run
default, and the kill switch all apply unchanged. There is no second
path that posts; run_due builds actions and hands them to the gate.

Idempotency: a row is marked `publishing` BEFORE dispatch. If the
process dies mid-publish the row is left in `publishing`, which is
excluded from due_posts -- a crash can never double-post; a stuck row
is visible in `list` and resolved by hand.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import autopilot, instagram, post_seo
from .db import DB_PATH, connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    video_ref   TEXT    NOT NULL,
    caption     TEXT,
    platform    TEXT    NOT NULL DEFAULT 'instagram',
    publish_at  TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'planned',
    media_id    TEXT,
    error       TEXT,
    posted_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_sched_due ON scheduled_posts (status, publish_at);
"""

# Our own ceiling, deliberately well under Meta's 100-posts/24h API
# quota -- a runaway queue should hit our brake long before theirs.
DAILY_CAP = 20


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def init(path: Path | str = DB_PATH) -> None:
    """Create the scheduling table. Run after db.init_db()."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def add_post(video_ref: str, caption: Optional[str], publish_at: str,
             platform: str = "instagram", db_path=None) -> int:
    """Queue a post. Not gated -- a row is an intention, not a publish."""
    with connect(db_path or DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO scheduled_posts (created_at, video_ref, caption, "
            "platform, publish_at) VALUES (?, ?, ?, ?, ?)",
            (_now(), video_ref, caption, platform, publish_at),
        )
        return cur.lastrowid


def list_queue(db_path=None) -> list[dict[str, Any]]:
    with connect(db_path or DB_PATH) as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_posts ORDER BY publish_at, id"
        ).fetchall()
        return [dict(r) for r in rows]


def due_posts(now: Optional[str] = None, db_path=None) -> list[dict[str, Any]]:
    """Planned rows whose time has come. Pure query; `publishing` rows
    are deliberately excluded -- see the idempotency note up top."""
    now = now or _now()
    with connect(db_path or DB_PATH) as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_posts "
            "WHERE status = 'planned' AND publish_at <= ? "
            "ORDER BY publish_at, id",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_status(post_id: int, status: str, media_id=None, error=None,
                db_path=None) -> None:
    with connect(db_path or DB_PATH) as conn:
        conn.execute(
            "UPDATE scheduled_posts SET status = ?, "
            "media_id = COALESCE(?, media_id), error = ?, "
            "posted_at = CASE WHEN ? = 'posted' THEN ? ELSE posted_at END "
            "WHERE id = ?",
            (status, media_id, error, status, _now(), post_id),
        )


def _posted_in_last_day(now: str, db_path=None) -> int:
    cutoff = (datetime.fromisoformat(now) - timedelta(hours=24)) \
        .strftime("%Y-%m-%dT%H:%M:%S")
    with connect(db_path or DB_PATH) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM scheduled_posts "
            "WHERE status = 'posted' AND posted_at > ?",
            (cutoff,),
        ).fetchone()
        return row["n"]


def _quota_remaining() -> int:
    """
    Meta's own 24h quota, checked live. Degrades pessimistically: if
    the check itself fails we report 0 remaining and the run defers,
    because "couldn't confirm quota" must not mean "post anyway."
    """
    user_id, token = instagram.ig_user_id(), instagram.access_token()
    if not (user_id and token):
        return 0
    try:
        return max(0, 100 - instagram.publishing_limit(user_id, token))
    except Exception:
        return 0


def build_caption(fallback: str, db_path=None) -> str:
    """
    A caption grounded in the channel's own performance signal: one
    model call proposes candidates, post_seo.score_post (pure, free)
    picks the winner. Any failure -- no key, no model, no signal --
    degrades to the supplied fallback rather than blocking a publish.
    """
    import os
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return fallback

    kwargs = {"db_path": db_path} if db_path is not None else {}
    try:
        signals = post_seo.derive_signals(**kwargs)
        winning_words = ", ".join(w for w, _ in
                                  signals["winning_title_words"].most_common(10))
        from google import genai

        from .gemini_utils import generate_with_retry, strip_fences
        client = genai.Client(api_key=api_key)
        prompt = (
            "Write 8 short Instagram reel captions (one per line, no numbering, "
            "no hashtags beyond two) for this video:\n"
            f"{fallback}\n\n"
            f"Words that performed for this channel: {winning_words or 'none yet'}"
        )
        lines = [ln.strip("-• ").strip() for ln in
                 strip_fences(generate_with_retry(client, "gemini-3-flash-preview",
                                                  prompt)).splitlines()]
        candidates = [ln for ln in lines if ln]
        if not candidates:
            return fallback
        scored = [(post_seo.score_post(c, signals=signals)["score"], c)
                  for c in candidates]
        return max(scored)[1]
    except Exception:
        return fallback


def run_due(now: Optional[str] = None, approve: bool = False, live: bool = False,
            db_path=None) -> dict[str, Any]:
    """
    The worker step cron invokes. For each due row: mark `publishing`,
    build a post action, run it through autopilot.execute (gate, dry-run
    and kill switch all apply), record the outcome. Never raises.
    """
    now = now or _now()
    due = due_posts(now, db_path=db_path)

    # Probe the gate ONCE with an empty plan: the mode depends only on
    # gate state, and probing with real actions in live mode would
    # publish them -- the double-post this dance exists to prevent.
    mode = autopilot.execute({"actions": []}, approve=approve,
                             dry_run=not live)["mode"]

    published = 0
    deferred: list[str] = []
    failed: list[str] = []
    would_publish: list[str] = []

    for row in due:
        action = {
            "kind": "post",
            "platform": row["platform"],
            "video_url": row["video_ref"],
            "caption": row["caption"] or "(caption generated at publish)",
            "scheduled_id": row["id"],
        }
        plan = {"actions": [action]}

        # In any non-live mode the row stays `planned` and nothing is
        # marked -- the preview costs nothing and changes nothing.
        if mode != "live":
            would_publish.append(f"{row['id']}: {row['video_ref']}")
            continue

        # Live from here down. Our cap, then Meta's quota. Posts made
        # earlier in this same loop are already committed rows, so
        # _posted_in_last_day alone reflects them -- adding `published`
        # on top would double-count and cap one row early.
        if _posted_in_last_day(now, db_path=db_path) >= DAILY_CAP:
            deferred.append(f"{row['id']}: daily cap ({DAILY_CAP}) reached")
            continue
        if _quota_remaining() <= 0:
            deferred.append(f"{row['id']}: publishing quota exhausted or unverifiable")
            continue

        if not row["caption"]:
            action["caption"] = build_caption(row["video_ref"], db_path=db_path)

        mark_status(row["id"], "publishing", db_path=db_path)
        try:
            autopilot.execute(plan, approve=approve, dry_run=not live)
            result = action.get("result") or {}
            mark_status(row["id"], "posted", media_id=result.get("media_id"),
                        db_path=db_path)
            published += 1
        except Exception as e:
            token = instagram.access_token()
            mark_status(row["id"], "failed",
                        error=instagram._safe_error(e, token), db_path=db_path)
            failed.append(str(row["id"]))

    return {"mode": mode, "due": len(due), "published": published,
            "deferred": deferred, "failed": failed,
            "would_publish": would_publish}


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="scheduling",
        description="The Instagram publish queue. `run` is dry-run by default "
                    "and only ever publishes through autopilot's gate.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show the queue")

    p_run = sub.add_parser("run", help="publish due posts through the gate")
    p_run.add_argument("--approve", action="store_true",
                       help="explicit per-run consent (required for live)")
    p_run.add_argument("--live", action="store_true",
                       help="disable dry-run (still requires the env enable)")

    args = parser.parse_args(argv)
    init()

    if args.command == "list":
        queue = list_queue()
        if not queue:
            print("queue is empty -- add rows with scheduling.add_post()")
            return
        for row in queue:
            print(f"[{row['id']:>3}] {row['status']:<10} {row['publish_at']}  "
                  f"{row['platform']}  {row['video_ref']}"
                  + (f"  ({row['error']})" if row["error"] else ""))
        return

    result = run_due(approve=args.approve, live=args.live)
    print(json.dumps(result, indent=2))
    if result["mode"] != "live":
        print(f"\nmode={result['mode']} -- nothing was published.")


if __name__ == "__main__":
    main()

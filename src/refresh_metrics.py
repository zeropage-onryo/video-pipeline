#!/usr/bin/env python3
"""
Nightly analytics sweep: pull the latest numbers for every posted video
from each platform, then promote the fresh top performers into the RAG
`proven_results` shelf so the concept generator grounds on what is
actually working.

    python -m src.refresh_metrics               # refresh all platforms + promote
    python -m src.refresh_metrics --no-promote  # refresh metrics only
    python -m src.refresh_metrics --platform youtube

Never raises on a single video: a missing key or a failed call is
recorded in the summary and the sweep moves on -- the same contract as
youtube/instagram.refresh_metrics_for_video. Facebook and TikTok are
stubbed until their modules land (BACKLOG #4).
"""
import argparse
import os
import sys
from typing import Optional

from dotenv import load_dotenv

from . import accounts, db

WIRED_PLATFORMS = ("youtube", "instagram")


def _refresh_platform(platform, videos, db_path=None):
    """Refresh every video for one platform; return per-video result dicts."""
    if platform == "youtube":
        from . import youtube
        api_key = os.environ.get("YOUTUBE_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return [youtube.refresh_metrics_for_video(v, api_key=api_key, db_path=db_path)
                for v in videos]
    if platform == "instagram":
        from . import instagram
        token = instagram.access_token()
        return [instagram.refresh_metrics_for_video(v, token=token, db_path=db_path)
                for v in videos]
    # facebook / tiktok: modules not wired yet (BACKLOG #4)
    return [{"ok": False, "error": f"{platform} refresh not wired yet"} for _ in videos]


def refresh_all(platform=None, db_path=None, account_id: Optional[int] = None):
    """Sweep metrics for all posted videos, grouped by platform. Returns
    {platform: {videos, refreshed, failed, errors}}."""
    kwargs = {"path": db_path} if db_path is not None else {}
    videos = db.list_videos(limit=10000, **kwargs, account_id=account_id)  # newest first, all platforms
    by_platform = {}
    for v in videos:
        p = v.get("platform")
        if platform and p != platform:
            continue
        by_platform.setdefault(p, []).append(v)

    summary = {}
    for p, vids in by_platform.items():
        results = _refresh_platform(p, vids, db_path=db_path)
        ok = sum(1 for r in results if r.get("ok"))
        summary[p] = {
            "videos": len(vids),
            "refreshed": ok,
            "failed": len(vids) - ok,
            "errors": sorted({r.get("error") for r in results if not r.get("ok") and r.get("error")}),
        }
    return summary


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Refresh post analytics and promote winners into RAG.")
    parser.add_argument("--platform",
                        help="only this platform (default: every platform with posts)")
    parser.add_argument("--no-promote", action="store_true",
                        help="refresh metrics only; skip the promote_winners step")
    parser.add_argument(
        "--account", default=None,
        help=(
            "The account to act as, by slug (zeropage / antihero). "
            "Defaults to the oldest account on the database -- the nightly "
            "job has no session, and acting as nobody would find no videos."
        ),
    )
    args = parser.parse_args(argv)
    account_id = accounts.resolve_account(args.account)

    summary = refresh_all(platform=args.platform, account_id=account_id)
    for p, s in summary.items():
        line = f"{p}: refreshed {s['refreshed']}/{s['videos']}"
        if s["failed"]:
            line += f" (failed {s['failed']}: {'; '.join(s['errors'])})"
        print(line)
    if not summary:
        print("no posted videos to refresh yet -- nothing to do.")

    if args.no_promote:
        return 0

    # Promote fresh top performers into the proven_results shelf. Needs the
    # RAG store (Postgres); if it's down, the refresh still counted -- the
    # promote just waits for next run rather than taking the sweep down.
    try:
        from . import promote_winners
        result = promote_winners.run_auto()
        if result["video_ids"]:
            print(f"promoted {result['promoted']} winner(s) into proven_results: "
                  f"video ids {result['video_ids']}")
        else:
            print("promote: nothing cleared the bar yet (need more equal-age data)")
    except Exception as e:
        print(f"promote step skipped: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

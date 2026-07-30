"""
YouTube Data API v3: parses a video id from a stored URL, fetches its
public statistics (no OAuth needed -- channel analytics would need it,
per-video public stats don't), and writes results through
db.record_metrics like any other snapshot.

Missing key or a failed call must not break the screen -- manual entry
keeps working -- so refresh_metrics_for_video never raises; it always
returns a result dict describing what happened.
"""
from urllib.parse import parse_qs, urlparse

import requests

from . import db

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTU_BE_HOSTS = {"youtu.be"}
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/videos"


def parse_video_id(url):
    """The video id from a youtube.com/watch, youtu.be, or /shorts/ URL,
    or None if it isn't one of those shapes."""
    if not url:
        return None

    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host in YOUTU_BE_HOSTS:
        video_id = parsed.path.lstrip("/")
        return video_id or None

    if host in YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v")
            return values[0] if values else None
        if parsed.path.startswith("/shorts/"):
            video_id = parsed.path[len("/shorts/"):]
            return video_id or None

    return None


def fetch_video_stats(video_id: str, api_key: str) -> dict:
    """
    Public view/like/comment counts for one video. Raises on any
    failure (bad key, unknown id, network error) -- callers that need
    to degrade gracefully do so themselves; this stays a thin, honest
    wrapper over the API.
    """
    response = requests.get(
        YOUTUBE_API_URL,
        params={"part": "statistics", "id": video_id, "key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items") or []
    if not items:
        raise ValueError(f"no video found for id {video_id!r}")

    stats = items[0]["statistics"]
    return {
        "views": int(stats["viewCount"]) if "viewCount" in stats else None,
        "likes": int(stats["likeCount"]) if "likeCount" in stats else None,
        "comments": int(stats["commentCount"]) if "commentCount" in stats else None,
    }


def refresh_metrics_for_video(video: dict, api_key=None, db_path=None) -> dict:
    """
    Fetch and record one video's current numbers. Never raises --
    "missing key or failed call must not break the screen; manual
    entry keeps working" is the whole point. Returns
    {"ok": True, "views": ..., "likes": ..., "comments": ...} on
    success, or {"ok": False, "error": "..."} otherwise.
    """
    if video.get("platform") != "youtube":
        return {"ok": False, "error": "not a youtube video"}
    if not api_key:
        return {"ok": False, "error": "YOUTUBE_API_KEY not set"}

    video_id = parse_video_id(video.get("url"))
    if not video_id:
        return {"ok": False, "error": "could not parse a video id from the stored url"}

    try:
        stats = fetch_video_stats(video_id, api_key)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    kwargs = {"path": db_path} if db_path is not None else {}
    db.record_metrics(video["id"], **stats, **kwargs)
    return {"ok": True, **stats}

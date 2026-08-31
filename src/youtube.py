"""
YouTube Data API v3: parses a video id from a stored URL, fetches its
public statistics (no OAuth needed -- channel analytics would need it,
per-video public stats don't), and writes results through
db.record_metrics like any other snapshot.

Missing key or a failed call must not break the screen -- manual entry
keeps working -- so refresh_metrics_for_video never raises; it always
returns a result dict describing what happened.
"""
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import requests

from . import db

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTU_BE_HOSTS = {"youtu.be"}

API_ROOT = "https://www.googleapis.com/youtube/v3"
YOUTUBE_API_URL = f"{API_ROOT}/videos"
CHANNELS_API_URL = f"{API_ROOT}/channels"
PLAYLIST_ITEMS_API_URL = f"{API_ROOT}/playlistItems"
SEARCH_API_URL = f"{API_ROOT}/search"

# videos.list accepts at most 50 ids per call -- importing a channel
# costs one call per 50 videos rather than one per video.
MAX_IDS_PER_CALL = 50


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

    return _parse_statistics(items[0]["statistics"])


def _safe_error(e: Exception, api_key=None) -> str:
    """
    requests puts the full request URL in its error messages, and our
    URLs carry key=<api key> -- so raw exception text is not safe to
    show in the UI. Redact the key before it ever reaches a page.
    """
    message = str(e)
    if api_key:
        message = message.replace(api_key, "<redacted>")
    return message


def _parse_statistics(stats: dict) -> dict:
    """YouTube returns these counts as strings, and omits a field
    entirely when it's disabled (e.g. likes hidden) rather than zeroing
    it -- absent stays None, which is not the same as 0."""
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
        return {"ok": False, "error": _safe_error(e, api_key)}

    kwargs = {"path": db_path} if db_path is not None else {}
    db.record_metrics(video["id"], **stats, **kwargs)
    return {"ok": True, **stats}


def get_uploads_playlist_id(handle: str, api_key: str) -> str:
    """
    A channel's "uploads" playlist -- a standard auto-maintained
    playlist of every public upload. Listing that playlist is how you
    enumerate a channel's videos; there's no "list videos" endpoint.
    """
    response = requests.get(
        CHANNELS_API_URL,
        params={"part": "contentDetails", "forHandle": handle, "key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items") or []
    if not items:
        raise ValueError(f"no channel found for handle {handle!r}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_channel_videos(handle: str, api_key: str) -> list:
    """
    Every public video on a channel: [{video_id, title, published_at}],
    following nextPageToken so channels past 50 videos still come back
    whole. published_at is trimmed to a date, which is what
    db.add_video's posted_at expects.
    """
    playlist_id = get_uploads_playlist_id(handle, api_key)

    videos = []
    page_token = None
    while True:
        params = {
            "part": "snippet", "playlistId": playlist_id,
            "maxResults": MAX_IDS_PER_CALL, "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        response = requests.get(PLAYLIST_ITEMS_API_URL, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()

        for item in payload.get("items") or []:
            snippet = item["snippet"]
            videos.append({
                "video_id": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "published_at": snippet["publishedAt"][:10],
            })

        page_token = payload.get("nextPageToken")
        if not page_token:
            return videos


def fetch_stats_bulk(video_ids: list, api_key: str) -> dict:
    """
    {video_id: {views, likes, comments}} for many videos at once.
    videos.list takes up to 50 ids per call, so this costs one request
    per 50 videos rather than one per video -- the difference between
    an import fitting in quota and not.
    """
    stats = {}
    for start in range(0, len(video_ids), MAX_IDS_PER_CALL):
        batch = video_ids[start:start + MAX_IDS_PER_CALL]
        response = requests.get(
            YOUTUBE_API_URL,
            params={"part": "statistics", "id": ",".join(batch), "key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        for item in response.json().get("items") or []:
            stats[item["id"]] = _parse_statistics(item["statistics"])
    return stats


def search_videos(query: str, api_key: str, limit: int = 8,
                  days: int = 30, order: str = "viewCount") -> dict:
    """
    Public search for recent videos matching `query`, newest window
    first, returned with their view counts.

    This is the one YouTube call in the codebase that is not about a
    video we already own -- src/scout.py uses it to see what formats are
    actually travelling right now, so the nightly spark is grounded in
    numbers rather than in what a model remembers about last year.

    Never raises: returns {"ok": False, "error": ...} instead. The scout
    treats every lane as optional and a raising search would be the one
    thing able to fail a research pass.

    Quota note: search.list costs 100 units against the free 10,000/day,
    and does NOT return statistics -- so this spends a second call
    (fetch_stats_bulk, 1 unit) to attach view counts. Two calls a night
    per brand is ~1% of the daily quota.
    """
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        response = requests.get(
            SEARCH_API_URL,
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": min(int(limit), 50),
                "order": order,
                "publishedAfter": published_after,
                "key": api_key,
            },
            timeout=10,
        )
        response.raise_for_status()
        items = response.json().get("items") or []
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, api_key), "videos": []}

    videos = []
    for item in items:
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        if not video_id:
            continue
        # The thumbnail is the highest-resolution still YouTube publishes
        # for a video, and it is the frame the creator chose -- which
        # makes it the one useful IMAGE in a search result. src/scout.py
        # pulls it into the research bin as visual evidence for a spark.
        thumbs = snippet.get("thumbnails") or {}
        thumb = ""
        for size in ("maxres", "standard", "high", "medium", "default"):
            if (thumbs.get(size) or {}).get("url"):
                thumb = thumbs[size]["url"]
                break
        videos.append({
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": thumb,
            "views": None,
        })

    # Best-effort enrichment: a failed stats call still leaves usable
    # titles, which is most of the format signal the scout is after.
    try:
        stats = fetch_stats_bulk([v["video_id"] for v in videos], api_key)
        for v in videos:
            v["views"] = (stats.get(v["video_id"]) or {}).get("views")
    except Exception:
        pass

    return {"ok": True, "videos": videos, "error": ""}


def import_channel_videos(handle: str, api_key=None, db_path=None) -> dict:
    """
    Add every video on a channel that isn't already tracked, with an
    initial metrics snapshot where stats are available. Never raises.

    Videos already in the database are matched by video id parsed from
    their stored url, so re-running is safe and a video added by hand
    earlier won't be duplicated.
    """
    if not api_key:
        return {"ok": False, "error": "YOUTUBE_API_KEY not set", "added": 0}

    kwargs = {"path": db_path} if db_path is not None else {}

    try:
        channel_videos = list_channel_videos(handle, api_key)
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, api_key), "added": 0}

    known_ids = {
        parse_video_id(v.get("url"))
        for v in db.list_videos(limit=10_000, **kwargs)
    }
    new_videos = [v for v in channel_videos if v["video_id"] not in known_ids]

    # Stats are a bonus: if this call fails the videos still get added,
    # just without an opening snapshot.
    try:
        stats = fetch_stats_bulk([v["video_id"] for v in new_videos], api_key)
    except Exception:
        stats = {}

    added = 0
    for video in new_videos:
        video_db_id = db.add_video(
            video["title"], "youtube", video["published_at"],
            url=f"https://www.youtube.com/watch?v={video['video_id']}",
            **kwargs,
        )
        added += 1
        if video["video_id"] in stats:
            db.record_metrics(video_db_id, **stats[video["video_id"]], **kwargs)

    return {"ok": True, "added": added}


# --------------------------------------------------------------------------
# uploads -- OAuth2 + resumable insert (the posting half youtube lacked)
# --------------------------------------------------------------------------
# Uploading needs full OAuth (an API key only reads public stats). Creds
# come from env, same dual-name convention as the rest of the app; the
# refresh token is minted once by you, out of band -- this module never
# runs an interactive consent flow and never sees a password.

UPLOAD_SCOPES = ("https://www.googleapis.com/auth/youtube.upload",)


def _oauth_env():
    cid = os.environ.get("YT_CLIENT_ID") or os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YT_CLIENT_SECRET") or os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh = os.environ.get("YT_REFRESH_TOKEN") or os.environ.get("YOUTUBE_REFRESH_TOKEN")
    return cid, secret, refresh


def upload_video(file_path, title, description="", privacy_status="private",
                 tags=None, category_id="22") -> dict:
    """Resumable upload of a LOCAL video file to YouTube. Never raises:
    returns {"ok", "video_id", "url", "error"}. Needs OAuth creds
    (YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN) and the google
    api client libs -- both reported clearly when missing, because that
    is exactly the setup a first live post is waiting on."""
    if not file_path or not os.path.isfile(str(file_path)):
        return {"ok": False, "video_id": None, "url": None,
                "error": f"no video file at {file_path!r}"}
    cid, secret, refresh = _oauth_env()
    if not (cid and secret and refresh):
        return {"ok": False, "video_id": None, "url": None,
                "error": "YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN not set"}
    try:
        from google.auth.transport.requests import Request as _AuthRequest
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except Exception as e:
        return {"ok": False, "video_id": None, "url": None,
                "error": f"google api client not installed ({e}); "
                         "pip install google-api-python-client google-auth"}
    try:
        creds = Credentials(
            None, refresh_token=refresh, client_id=cid, client_secret=secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=list(UPLOAD_SCOPES))
        creds.refresh(_AuthRequest())
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        body = {
            "snippet": {"title": title or "Untitled", "description": description or "",
                        "tags": list(tags or []), "categoryId": category_id},
            "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True)
        request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _status, response = request.next_chunk()
        vid = response.get("id")
        return {"ok": True, "video_id": vid,
                "url": f"https://youtu.be/{vid}" if vid else None, "error": None}
    except Exception as e:
        return {"ok": False, "video_id": None, "url": None, "error": str(e)}


def execute_post_action(action: dict) -> None:
    """The YouTube half of autopilot's post dispatch, mirroring
    instagram.execute_post_action: only ever reached in live mode, so it
    raises on failure and writes the result back onto the action. Needs a
    LOCAL file (video_path) -- YouTube uploads bytes, not a public URL
    like Meta."""
    cid, secret, refresh = _oauth_env()
    if not (cid and secret and refresh):
        raise RuntimeError("YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN "
                           "not set -- live YouTube posting needs all three")
    path = (action.get("video_path") or "").strip()
    if not path:
        raise RuntimeError("youtube post action has no video_path (a local "
                           "rendered file); YouTube uploads a file, not a URL")
    result = upload_video(
        path, action.get("title") or action.get("caption") or "Untitled",
        description=action.get("caption") or "",
        privacy_status=action.get("privacy") or "private")
    if not result["ok"]:
        raise RuntimeError(f"youtube upload failed: {result['error']}")
    action["result"] = result

"""
TikTok Content Posting + Display API: publish a video via Direct Post
(init with a PULL_FROM_URL source, then poll until TikTok says the post
is live) and read its counts back into db.record_metrics -- the third
platform beside instagram.py and youtube.py, holding the same contract:
thin API wrappers that raise, public orchestrators that never do. A
missing token or a failed call is a result dict, not an exception that
takes a page or the scheduler down.

Publishing is asynchronous on TikTok's side exactly as it is on Meta's:
`/video/init/` hands back a publish_id, TikTok fetches the file from the
URL you gave it, and only a later status poll says whether a post
exists. post_video owns that dance and refuses to report success before
the status reads PUBLISH_COMPLETE -- an init that returned 200 has
published nothing.

WHY EVERY ENDPOINT IS A MODULE CONSTANT. TikTok's posting endpoints have
moved twice inside v2 and the scopes moved with them; when they move
again this module should need one line changed, not a search through
call sites. Same reason every HTTP call goes through _request: it is the
one seam tests patch, so a test cannot pass while a real call escapes
(tests/conftest.py's network guard is the backstop).

WHAT IS NOT DONE HERE, and cannot be from this side: TikTok gates
`video.publish` (Direct Post) behind its own app review, and an
unreviewed app can only send a video to the user's inbox as a draft.
The module is complete and the credential is a one-line env var; the
approval is Mike's to file. See docs/BACKLOG.md item 4.

The live-publish path is only ever reached through autopilot's
three-condition gate plus the per-run posting approval (see
execute_post_action) -- this module never posts on import, on schedule,
or by default.
"""
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests

from . import db

# Every endpoint in one place -- a spec change is a one-line fix.
# Dated 2026-09-07 against TikTok's "Content Posting API" and "Display
# API" reference; verify before trusting a moved path.
API_ROOT = "https://open.tiktokapis.com/v2"
PUBLISH_INIT_URL = f"{API_ROOT}/post/publish/video/init/"
PUBLISH_STATUS_URL = f"{API_ROOT}/post/publish/status/fetch/"
VIDEO_QUERY_URL = f"{API_ROOT}/video/query/"
CREATOR_INFO_URL = f"{API_ROOT}/post/publish/creator_info/query/"

# The source that lets us hand TikTok a URL instead of uploading bytes,
# which is what makes this shaped like Instagram rather than YouTube.
SOURCE_PULL_FROM_URL = "PULL_FROM_URL"

# Terminal states of the status poll. Anything else is still in flight.
PUBLISH_COMPLETE = "PUBLISH_COMPLETE"
PUBLISH_FAILED = {"FAILED"}

# Display API field names, which are NOT our schema's names -- the map
# from one to the other lives in refresh_metrics_for_video.
VIDEO_FIELDS = ("id", "view_count", "like_count", "comment_count", "share_count")

# SELF_ONLY is the only privacy level an unaudited app may use, and it
# is the right default regardless: a machine's first live post should be
# private until a person has seen it. Overridable per action.
DEFAULT_PRIVACY = "SELF_ONLY"

REQUEST_TIMEOUT = 15


def access_token():
    """Same dual-name convention as the rest of the app."""
    return os.environ.get("TIKTOK_ACCESS_TOKEN") or os.environ.get("TIKTOK_TOKEN")


def open_id():
    """The creator's open_id. Not needed by the endpoints this module
    calls (the token identifies the creator), kept because TikTok's
    docs use it for user-scoped reads and a missing one should read as
    "not configured" rather than as an auth error."""
    return os.environ.get("TIKTOK_OPEN_ID")


def has_key() -> bool:
    """Whether this lane can run at all -- what /api/capabilities-style
    checks and the metrics sweep ask before reporting a failure."""
    return bool(access_token())


def _safe_error(e: Exception, token=None) -> str:
    """
    The TikTok token rides in an Authorization header, not in the query
    string -- but requests puts headers in some exception reprs, our own
    error strings quote response bodies, and a token that leaks into a
    db row or a page is a token to rotate. Redact before it reaches
    either, exactly as youtube/instagram do for their credentials.
    """
    message = str(e)
    if token:
        message = message.replace(token, "<redacted>")
    return message


# --------------------------------------------------------------------------
# the one network seam
# --------------------------------------------------------------------------

def _request(method: str, url: str, token: str, payload: Optional[dict] = None,
             params: Optional[dict] = None) -> dict:
    """
    Every HTTP call this module makes. Raises on a transport error or a
    non-2xx; returns the parsed body otherwise (TikTok's own errors live
    INSIDE a 200 body -- see _data).

    One function on purpose: a test patches this and nothing can reach
    the network behind its back.
    """
    response = requests.request(
        method, url,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=UTF-8"},
        json=payload, params=params, timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json() or {}


def _data(body: dict) -> dict:
    """TikTok answers 200 with {"data": ..., "error": {"code": "ok"}} and
    reports real failures in that envelope, so a raise_for_status alone
    would read an error as a success. Raise on anything but ok."""
    error = (body or {}).get("error") or {}
    code = error.get("code", "ok")
    if code and code != "ok":
        raise RuntimeError(f"{code}: {error.get('message') or 'no message'}")
    return (body or {}).get("data") or {}


# --------------------------------------------------------------------------
# thin wrappers -- raise on failure, callers catch
# --------------------------------------------------------------------------

def init_direct_post(video_url: str, caption: str, token: str,
                     privacy_level: str = DEFAULT_PRIVACY) -> str:
    """Step one: hand TikTok a public URL to pull the file from and get
    back a publish_id to poll. The URL's domain must be verified on the
    developer app, which is the usual cause of an init that fails with
    url_ownership_unverified."""
    body = _request("POST", PUBLISH_INIT_URL, token, payload={
        "post_info": {"title": caption or "", "privacy_level": privacy_level},
        "source_info": {"source": SOURCE_PULL_FROM_URL, "video_url": video_url},
    })
    data = _data(body)
    publish_id = data.get("publish_id")
    if not publish_id:
        raise RuntimeError("init returned no publish_id")
    return publish_id


def publish_status(publish_id: str, token: str) -> dict:
    """Step two, polled: {"status", "post_id", "fail_reason"}. The post
    id is what refresh_metrics_for_video later queries counts for, and
    TikTok returns it as a list of the posts the publish produced."""
    data = _data(_request("POST", PUBLISH_STATUS_URL, token,
                          payload={"publish_id": publish_id}))
    ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
    return {
        "status": data.get("status") or "",
        "post_id": str(ids[0]) if ids else None,
        "fail_reason": data.get("fail_reason") or "",
    }


def fetch_video_stats(video_ids: list, token: str) -> dict:
    """{video_id: {view_count, like_count, comment_count, share_count}}
    for videos this creator owns. The Display API takes the fields as a
    query parameter and the filter as a body, which is why this is the
    one call here carrying both."""
    if not video_ids:
        return {}
    data = _data(_request(
        "POST", VIDEO_QUERY_URL, token,
        params={"fields": ",".join(VIDEO_FIELDS)},
        payload={"filters": {"video_ids": [str(v) for v in video_ids]}},
    ))
    return {str(v.get("id")): v for v in (data.get("videos") or []) if v.get("id")}


# --------------------------------------------------------------------------
# never-raises edges
# --------------------------------------------------------------------------

def post_video(video_url: str, caption: str, token: str,
               privacy_level: str = DEFAULT_PRIVACY,
               poll_tries: int = 5, poll_delay: float = 20,
               sleep=time.sleep) -> dict:
    """
    The full Direct Post dance: init -> poll until PUBLISH_COMPLETE.
    Never raises; returns {"ok", "publish_id", "video_id", "step",
    "error"} where `step` names where it died, because "init failed"
    (usually an unverified URL domain or a missing scope) and "poll
    failed" (TikTok rejected the file) call for different fixes.
    `sleep` is injectable so tests don't wait out real polling delays.
    """
    try:
        publish_id = init_direct_post(video_url, caption, token,
                                      privacy_level=privacy_level)
    except Exception as e:
        return {"ok": False, "publish_id": None, "video_id": None,
                "step": "init", "error": _safe_error(e, token)}

    status = ""
    try:
        for attempt in range(poll_tries):
            if attempt:
                sleep(poll_delay)
            state = publish_status(publish_id, token)
            status = state["status"]
            if status == PUBLISH_COMPLETE:
                return {"ok": True, "publish_id": publish_id,
                        "video_id": state["post_id"], "step": "publish",
                        "error": None}
            if status in PUBLISH_FAILED:
                return {"ok": False, "publish_id": publish_id, "video_id": None,
                        "step": "poll",
                        "error": f"publish reported {status}"
                                 + (f": {state['fail_reason']}" if state["fail_reason"] else "")}
        return {"ok": False, "publish_id": publish_id, "video_id": None,
                "step": "poll",
                "error": f"not published after {poll_tries} poll(s) "
                         f"(last status: {status or 'unknown'})"}
    except Exception as e:
        return {"ok": False, "publish_id": publish_id, "video_id": None,
                "step": "poll", "error": _safe_error(e, token)}


def parse_video_id(url):
    """
    The video id from what's stored in a video's url field: a bare id, a
    tiktok://<id> ref, or a /video/<id> permalink -- which, unlike an
    Instagram /reel/ permalink, really does carry the numeric id.
    Anything else returns None and the caller says so honestly rather
    than guessing.
    """
    if not url:
        return None
    text = str(url).strip()
    if re.fullmatch(r"\d{5,}", text):
        return text
    if text.startswith("tiktok://"):
        candidate = text[len("tiktok://"):]
        return candidate if re.fullmatch(r"\d+", candidate) else None
    match = re.search(r"/video/(\d+)", urlparse(text).path)
    return match.group(1) if match else None


def refresh_metrics_for_video(video: dict, token=None, db_path=None,
                              account_id: Optional[int] = None) -> dict:
    """
    Fetch and record one TikTok video's current numbers -- the third
    half of what youtube/instagram.refresh_metrics_for_video do, same
    shape. Never raises: manual entry keeps working whatever happens
    here.

    `saves` stays None rather than 0: the Display API does not expose a
    save count, and a zero would be a claim about the post instead of
    an admission about the API.
    """
    if video.get("platform") != "tiktok":
        return {"ok": False, "error": "not a tiktok video"}
    if not token:
        return {"ok": False, "error": "TIKTOK_ACCESS_TOKEN not set"}

    video_id = video.get("media_id") or parse_video_id(video.get("url"))
    if not video_id:
        return {"ok": False,
                "error": "no video id -- store the numeric id (or a "
                         "/video/<id> permalink) in the url field"}

    try:
        stats = fetch_video_stats([video_id], token).get(str(video_id))
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, token)}
    if not stats:
        return {"ok": False, "error": f"no video found for id {video_id}"}

    numbers = {
        "views": stats.get("view_count"),
        "likes": stats.get("like_count"),
        "comments": stats.get("comment_count"),
        "saves": None,
        "shares": stats.get("share_count"),
    }
    kwargs = {"dsn": db_path} if db_path is not None else {}
    # THE OWNER IS THE ROW'S (2026-09-22). Every caller -- the nightly sweep,
    # the app's refresh routes -- passed no account, record_metrics scopes
    # on it, and an owned video was "not found" at the write: a ValueError
    # out of a function whose whole contract is never raising, and no
    # snapshot for any owned video anywhere. The video dict comes off
    # `SELECT *`, so it carries account_id; that is the truth about it.
    owner = account_id if account_id is not None else video.get("account_id")
    try:
        db.record_metrics(video["id"], **numbers, **kwargs, account_id=owner)
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"metrics not recorded: {e}"}
    return {"ok": True, **numbers}


# --------------------------------------------------------------------------
# the autopilot adapter
# --------------------------------------------------------------------------

def execute_post_action(action: dict) -> None:
    """
    The TikTok branch of autopilot's post dispatch, mirroring
    instagram.execute_post_action: only ever called in live mode -- the
    gate returns before the executor loop in every other mode -- so
    raising here is correct, and the caller (scheduling.run_due, or the
    hold's Post now) records a redacted `failed` row.

    Needs a PUBLIC URL, not a local path: Direct Post pulls the file
    itself, so a rendered clip that never reached R2 cannot be posted
    here and says so instead of failing inside TikTok's fetcher.
    """
    token = access_token()
    if not token:
        raise RuntimeError("TIKTOK_ACCESS_TOKEN not set -- live TikTok "
                           "posting needs it")
    video_url = (action.get("video_url") or "").strip()
    if not video_url or not video_url.startswith("http"):
        raise RuntimeError("tiktok post action needs a public video_url "
                           "(Direct Post pulls the file; it cannot read a "
                           "local path)")
    result = post_video(video_url, action.get("caption") or "", token,
                        privacy_level=action.get("privacy") or DEFAULT_PRIVACY)
    if not result["ok"]:
        raise RuntimeError(f"tiktok publish failed at {result['step']}: "
                           f"{result['error']}")
    action["result"] = result

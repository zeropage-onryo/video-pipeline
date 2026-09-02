"""
Instagram Graph API: publish reels/images via the two-step
container -> publish flow, and read media insights back into
db.record_metrics -- the Instagram half of what youtube.py does for
YouTube, holding the same contract: thin API wrappers that raise, and
public orchestrators that never do. A missing token or a failed call is
a result dict, not an exception that takes a page or the scheduler down.

Publishing is asynchronous on Meta's side: a container is created,
processed, and only then publishable. post_reel owns that dance and
refuses to publish before the container reports FINISHED -- publishing
an unprocessed container is the documented way to lose a post.

The live-publish path is only ever reached through autopilot.execute's
three-condition gate (see execute_post_action) -- this module never
posts on import, on schedule, or by default.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

from . import db

# Graph API version, one place. Dated 2026-08-04 -- verify against
# Meta's changelog before bumping; insights metric names shift between
# versions.
VERSION = "v23.0"
API_ROOT = f"https://graph.instagram.com/{VERSION}"

# Insight metric names as of v22+ (dated 2026-08-04): `views` is the
# unified consumption metric (replacing plays/impressions), `saved` is
# Meta's name for what our schema calls `saves`.
REEL_METRICS = ("views", "likes", "comments", "saved", "shares")

CONTAINER_FINISHED = "FINISHED"
CONTAINER_FAILED = {"ERROR", "EXPIRED"}


def ig_user_id():
    """The IG professional-account user id, from either env name --
    same dual-name convention as GEMINI_API_KEY/GOOGLE_API_KEY."""
    return os.environ.get("IG_USER_ID") or os.environ.get("INSTAGRAM_USER_ID")


def access_token():
    return os.environ.get("IG_ACCESS_TOKEN") or os.environ.get("INSTAGRAM_ACCESS_TOKEN")


def _safe_error(e: Exception, token=None) -> str:
    """
    requests puts the full request URL in its error messages, and ours
    carry access_token=<token> -- raw exception text is not safe to show
    or store. Redact before it reaches a page, a log, or a db row.
    """
    message = str(e)
    if token:
        message = message.replace(token, "<redacted>")
    return message


# --------------------------------------------------------------------------
# thin wrappers -- raise on failure, callers catch
# --------------------------------------------------------------------------

def create_reel_container(user_id: str, video_url: str, caption: str,
                          token: str) -> str:
    """Step one of publishing a reel: register the video (a public URL
    Meta can fetch) and get back a container id to poll."""
    response = requests.post(
        f"{API_ROOT}/{user_id}/media",
        data={"media_type": "REELS", "video_url": video_url,
              "caption": caption, "access_token": token},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["id"]


def create_image_container(user_id: str, image_url: str, caption: str,
                           token: str) -> str:
    """Image variant (JPEG only -- Meta rejects PNG/HEIC here)."""
    response = requests.post(
        f"{API_ROOT}/{user_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["id"]


def container_status(container_id: str, token: str) -> str:
    """IN_PROGRESS / FINISHED / ERROR / EXPIRED."""
    response = requests.get(
        f"{API_ROOT}/{container_id}",
        params={"fields": "status_code", "access_token": token},
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("status_code", "")


def publish_container(user_id: str, container_id: str, token: str) -> str:
    """Step two: publish a FINISHED container. Returns the media id."""
    response = requests.post(
        f"{API_ROOT}/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["id"]


def publishing_limit(user_id: str, token: str) -> int:
    """How many posts of the 24h API quota (100) are already used."""
    response = requests.get(
        f"{API_ROOT}/{user_id}/content_publishing_limit",
        params={"access_token": token},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json().get("data") or []
    return int(data[0].get("quota_usage", 0)) if data else 0


def fetch_media_insights(media_id: str, token: str) -> dict:
    """Raw insight values for one media object: {metric_name: value}."""
    response = requests.get(
        f"{API_ROOT}/{media_id}/insights",
        params={"metric": ",".join(REEL_METRICS), "access_token": token},
        timeout=10,
    )
    response.raise_for_status()
    values = {}
    for entry in response.json().get("data") or []:
        entry_values = entry.get("values") or []
        if entry_values:
            values[entry["name"]] = entry_values[0].get("value")
    return values


# --------------------------------------------------------------------------
# never-raises edges
# --------------------------------------------------------------------------

def post_reel(user_id: str, video_url: str, caption: str, token: str,
              poll_tries: int = 5, poll_delay: float = 60,
              sleep=time.sleep) -> dict:
    """
    The full publish dance: create -> poll until FINISHED -> publish.
    Never raises; returns {"ok", "media_id", "step", "error"} where
    `step` names where it died, because "create failed" and "publish
    failed" call for different fixes. `sleep` is injectable so tests
    don't wait out real polling delays.
    """
    try:
        container_id = create_reel_container(user_id, video_url, caption, token)
    except Exception as e:
        return {"ok": False, "media_id": None, "step": "create",
                "error": _safe_error(e, token)}

    status = ""
    try:
        for attempt in range(poll_tries):
            if attempt:
                sleep(poll_delay)
            status = container_status(container_id, token)
            if status == CONTAINER_FINISHED:
                break
            if status in CONTAINER_FAILED:
                return {"ok": False, "media_id": None, "step": "poll",
                        "error": f"container reported {status}"}
        else:
            return {"ok": False, "media_id": None, "step": "poll",
                    "error": f"container not FINISHED after {poll_tries} "
                             f"poll(s) (last status: {status or 'unknown'})"}
    except Exception as e:
        return {"ok": False, "media_id": None, "step": "poll",
                "error": _safe_error(e, token)}

    try:
        media_id = publish_container(user_id, container_id, token)
    except Exception as e:
        return {"ok": False, "media_id": None, "step": "publish",
                "error": _safe_error(e, token)}

    return {"ok": True, "media_id": media_id, "step": "publish", "error": None}


def post_image(user_id: str, image_url: str, caption: str, token: str,
               poll_tries: int = 5, poll_delay: float = 20,
               sleep=time.sleep) -> dict:
    """The image twin of post_reel: create an image container (JPEG only,
    from a public URL Meta can fetch) -> poll until FINISHED -> publish.
    Never raises; returns {"ok", "media_id", "step", "error"}."""
    try:
        container_id = create_image_container(user_id, image_url, caption, token)
    except Exception as e:
        return {"ok": False, "media_id": None, "step": "create",
                "error": _safe_error(e, token)}
    status = ""
    try:
        for attempt in range(poll_tries):
            if attempt:
                sleep(poll_delay)
            status = container_status(container_id, token)
            if status == CONTAINER_FINISHED:
                break
            if status in CONTAINER_FAILED:
                return {"ok": False, "media_id": None, "step": "poll",
                        "error": f"container reported {status}"}
        else:
            return {"ok": False, "media_id": None, "step": "poll",
                    "error": f"container not FINISHED after {poll_tries} "
                             f"poll(s) (last status: {status or 'unknown'})"}
    except Exception as e:
        return {"ok": False, "media_id": None, "step": "poll",
                "error": _safe_error(e, token)}
    try:
        media_id = publish_container(user_id, container_id, token)
    except Exception as e:
        return {"ok": False, "media_id": None, "step": "publish",
                "error": _safe_error(e, token)}
    return {"ok": True, "media_id": media_id, "step": "publish", "error": None}


def parse_media_id(url):
    """
    The numeric media id from what's stored in a video's url field: a
    bare id, an ig://<id> ref, or a permalink carrying ?media_id=. A
    plain /reel/<shortcode>/ permalink does NOT contain the numeric id
    -- that returns None, and the caller says so honestly rather than
    guessing.
    """
    if not url:
        return None
    text = str(url).strip()
    if re.fullmatch(r"\d{5,}", text):
        return text
    if text.startswith("ig://"):
        candidate = text[len("ig://"):]
        return candidate if re.fullmatch(r"\d+", candidate) else None
    values = parse_qs(urlparse(text).query).get("media_id")
    if values and re.fullmatch(r"\d+", values[0]):
        return values[0]
    return None


def refresh_metrics_for_video(video: dict, token=None, db_path=None, account_id: Optional[int] = None) -> dict:
    """
    Fetch and record one Instagram video's current numbers -- the
    alongside-YouTube half, same shape as youtube.refresh_metrics_for_video.
    Never raises: manual entry keeps working whatever happens here.
    """
    if video.get("platform") != "instagram":
        return {"ok": False, "error": "not an instagram video"}
    if not token:
        return {"ok": False, "error": "IG_ACCESS_TOKEN not set"}

    media_id = video.get("media_id") or parse_media_id(video.get("url"))
    if not media_id:
        return {"ok": False,
                "error": "no media id -- store the numeric id (or ig://<id>) "
                         "in the url field; a /reel/ permalink doesn't carry it"}

    try:
        insights = fetch_media_insights(media_id, token)
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, token)}

    stats = {
        "views": insights.get("views"),
        "likes": insights.get("likes"),
        "comments": insights.get("comments"),
        "saves": insights.get("saved"),
        "shares": insights.get("shares"),
    }
    kwargs = {"path": db_path} if db_path is not None else {}
    db.record_metrics(video["id"], **stats, **kwargs, account_id=account_id)
    return {"ok": True, **stats}


# --------------------------------------------------------------------------
# reading OTHER accounts: the research half
# --------------------------------------------------------------------------
# There is no FYP. Meta has never exposed the Explore feed, the For You
# surface, or recommended reels to any API, and probing this account's
# own token (2026-08-31) returns "Tried accessing nonexisting field" for
# explore, reels, trending, recommended_media and discover. Anything that
# claims to serve one is scraping a logged-in session, which is against
# Meta's terms and risks the account this pipeline exists to feed.
#
# What IS readable, and is arguably better signal than a personalised
# feed, is what is PERFORMING:
#
#   business_discovery  the recent public posts of a professional account
#                       you name, with like/comment counts. Curated by
#                       Mike's own taste -- the handles already on file
#                       in inspiration.py -- rather than by an algorithm.
#   hashtag_top_media   Meta's own "top" ranking for a hashtag right now.
#
# BOTH ARE FACEBOOK-LOGIN ONLY. This module's publishing half runs on
# graph.instagram.com with an Instagram-Login token; neither of these
# exists on that host, and that token is not parseable by
# graph.facebook.com. So they read their own credential (IG_GRAPH_TOKEN)
# and report "not configured" until one exists -- the lane is dark, not
# broken, and never borrows the publishing token, which would fail in a
# way that looks like a network problem.

GRAPH_ROOT = f"https://graph.facebook.com/{VERSION}"

# Meta's cap: 30 unique hashtags per rolling 7 days, counted on the
# ig_hashtag_search ID LOOKUP, not on reading a hashtag's media. A tag's
# id never changes, so caching ids is what keeps this lane sustainable:
# only a tag never looked up before spends budget. Without the cache,
# four tags a night crosses 30 in the second week and the lane dies
# quietly -- which is the failure mode this repo keeps paying for.
HASHTAG_WINDOW_DAYS = 7
HASHTAG_WINDOW_MAX = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS ig_hashtag_ids (
    tag         TEXT PRIMARY KEY,
    hashtag_id  TEXT NOT NULL,
    looked_up_at TEXT NOT NULL
);
"""


def init(path=None) -> None:
    kwargs = {"path": path} if path is not None else {}
    with db.connect(**kwargs) as conn:
        conn.executescript(SCHEMA)


def graph_token():
    """The Facebook-Login token the research endpoints need. Separate
    from access_token() on purpose: they are different credentials on
    different hosts, and conflating them produces an OAuthException that
    reads like an outage."""
    return os.environ.get("IG_GRAPH_TOKEN") or os.environ.get("FB_GRAPH_TOKEN")


def graph_user_id():
    """The IG professional-account id as graph.facebook.com sees it.
    Usually the same number as IG_USER_ID; overridable because a
    Business account linked through a Page can differ."""
    return os.environ.get("IG_BUSINESS_ID") or ig_user_id()


def research_ready() -> tuple:
    """(ok, reason) -- one place that answers "can this lane run at all",
    so the scout reports a precise reason instead of an empty result."""
    if not graph_token():
        return (False, "IG_GRAPH_TOKEN not set (Facebook-Login token needed; "
                       "the publishing token cannot read other accounts)")
    if not graph_user_id():
        return (False, "IG_USER_ID / IG_BUSINESS_ID not set")
    return (True, "")


def business_discovery(handle: str, limit: int = 6, token=None,
                       user_id=None) -> dict:
    """Recent public posts of one professional account, with counts.

    Never raises. Returns {"ok", "posts": [...], "error"}. A handle that
    is private, personal (not professional), or simply wrong comes back
    ok=False with Meta's reason -- all three are ordinary states for a
    list of creators someone typed, not failures worth stopping a
    research pass over.
    """
    token = token or graph_token()
    user_id = user_id or graph_user_id()
    ok, reason = research_ready()
    if not token or not user_id:
        return {"ok": False, "posts": [], "error": reason or "not configured"}
    clean = (handle or "").strip().lstrip("@")
    if not clean:
        return {"ok": False, "posts": [], "error": "empty handle"}

    fields = (f"business_discovery.username({clean})"
              "{followers_count,media_count,media"
              ".limit(" + str(int(limit)) + ")"
              "{caption,like_count,comments_count,media_type,media_url,"
              "thumbnail_url,permalink,timestamp}}")
    try:
        resp = requests.get(f"{GRAPH_ROOT}/{user_id}",
                            params={"fields": fields, "access_token": token},
                            timeout=15)
        body = resp.json()
        if "error" in body:
            return {"ok": False, "posts": [],
                    "error": _safe_error(Exception(body["error"].get("message", "")), token)}
        bd = body.get("business_discovery") or {}
        posts = (bd.get("media") or {}).get("data") or []
        return {"ok": True, "handle": clean,
                "followers": bd.get("followers_count"), "posts": posts, "error": ""}
    except Exception as e:
        return {"ok": False, "posts": [], "error": _safe_error(e, token)}


def hashtag_id(tag: str, token=None, user_id=None, path=None) -> dict:
    """A hashtag's stable id, cached forever.

    The cache IS the rate-limit strategy -- see HASHTAG_WINDOW_MAX. A
    cache hit spends nothing; only a genuinely new tag costs one of the
    30. When the window is already full this refuses rather than firing
    a call Meta will reject, so the reason reaching the log is the real
    one and not a generic API error.
    """
    token = token or graph_token()
    user_id = user_id or graph_user_id()
    clean = (tag or "").strip().lstrip("#").lower()
    if not clean:
        return {"ok": False, "error": "empty tag"}
    kwargs = {"path": path} if path is not None else {}
    try:
        init(path)
        with db.connect(**kwargs) as conn:
            row = conn.execute("SELECT hashtag_id FROM ig_hashtag_ids WHERE tag = ?",
                               (clean,)).fetchone()
            if row:
                return {"ok": True, "id": row["hashtag_id"], "cached": True, "error": ""}
            since = (datetime.now(timezone.utc)
                     - timedelta(days=HASHTAG_WINDOW_DAYS)).isoformat()
            spent = conn.execute(
                "SELECT COUNT(*) FROM ig_hashtag_ids WHERE looked_up_at >= ?",
                (since,)).fetchone()[0]
    except Exception as e:
        return {"ok": False, "error": f"hashtag cache unavailable: {type(e).__name__}: {e}"}

    if spent >= HASHTAG_WINDOW_MAX:
        return {"ok": False, "error": (
            f"hashtag budget spent ({spent}/{HASHTAG_WINDOW_MAX} new tags in "
            f"{HASHTAG_WINDOW_DAYS} days) — cached tags still work")}
    if not token or not user_id:
        return {"ok": False, "error": research_ready()[1]}

    try:
        resp = requests.get(f"{GRAPH_ROOT}/ig_hashtag_search",
                            params={"user_id": user_id, "q": clean,
                                    "access_token": token}, timeout=15)
        body = resp.json()
        if "error" in body:
            return {"ok": False,
                    "error": _safe_error(Exception(body["error"].get("message", "")), token)}
        data = body.get("data") or []
        if not data:
            return {"ok": False, "error": f"no hashtag id for #{clean}"}
        found = data[0]["id"]
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, token)}

    try:
        with db.connect(**kwargs) as conn:
            conn.execute("INSERT OR REPLACE INTO ig_hashtag_ids "
                         "(tag, hashtag_id, looked_up_at) VALUES (?, ?, ?)",
                         (clean, found, datetime.now(timezone.utc).isoformat()))
    except Exception:
        pass          # an uncached id costs budget next time, never this call
    return {"ok": True, "id": found, "cached": False, "error": ""}


def hashtag_top_media(tag: str, limit: int = 6, token=None, user_id=None,
                      path=None) -> dict:
    """Meta's own "top" ranking for a hashtag right now.

    Note what is NOT here: `username`. Meta strips it from hashtag
    media, so a post read this way can be shown and linked (permalink)
    but not attributed to a person. The scout stores the permalink as
    the source for exactly that reason.
    """
    token = token or graph_token()
    user_id = user_id or graph_user_id()
    found = hashtag_id(tag, token=token, user_id=user_id, path=path)
    if not found.get("ok"):
        return {"ok": False, "media": [], "error": found.get("error", "")}
    fields = ("caption,like_count,comments_count,media_type,media_url,"
              "permalink,timestamp")
    try:
        resp = requests.get(f"{GRAPH_ROOT}/{found['id']}/top_media",
                            params={"user_id": user_id, "fields": fields,
                                    "limit": int(limit), "access_token": token},
                            timeout=15)
        body = resp.json()
        if "error" in body:
            return {"ok": False, "media": [],
                    "error": _safe_error(Exception(body["error"].get("message", "")), token)}
        return {"ok": True, "tag": (tag or "").lstrip("#").lower(),
                "media": body.get("data") or [], "error": ""}
    except Exception as e:
        return {"ok": False, "media": [], "error": _safe_error(e, token)}


# --------------------------------------------------------------------------
# the autopilot adapter
# --------------------------------------------------------------------------

def execute_post_action(action: dict) -> None:
    """
    The executor registered at autopilot.EXECUTORS["post"]. Only ever
    called in live mode -- autopilot.execute returns before the executor
    loop in every other mode -- so raising here is correct: a failed live
    publish must surface, and the caller (scheduling.run_due) catches it
    and records a redacted `failed` row.

    On success the result is written back onto the action dict, which is
    how the media id gets back to the caller without changing
    autopilot.execute's signature.
    """
    user_id, token = ig_user_id(), access_token()
    if not (user_id and token):
        raise RuntimeError("IG_USER_ID / IG_ACCESS_TOKEN not set -- live "
                           "posting needs both")

    caption = action.get("caption") or ""
    image_url = (action.get("image_url") or "").strip()
    video_url = (action.get("video_url") or "").strip()
    if image_url:
        result = post_image(user_id, image_url, caption, token)
    elif video_url:
        result = post_reel(user_id, video_url, caption, token)
    else:
        raise RuntimeError("post action has neither image_url nor video_url")
    if not result["ok"]:
        raise RuntimeError(f"publish failed at {result['step']}: {result['error']}")
    action["result"] = result

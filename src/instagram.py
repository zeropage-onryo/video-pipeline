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


def refresh_metrics_for_video(video: dict, token=None, db_path=None) -> dict:
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
    db.record_metrics(video["id"], **stats, **kwargs)
    return {"ok": True, **stats}


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

    video_url = (action.get("video_url") or "").strip()
    if not video_url:
        raise RuntimeError("post action has no video_url")

    result = post_reel(user_id, video_url, action.get("caption") or "", token)
    if not result["ok"]:
        raise RuntimeError(f"publish failed at {result['step']}: {result['error']}")
    action["result"] = result

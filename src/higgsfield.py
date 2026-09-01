#!/usr/bin/env python3
"""
The Higgsfield connector: prompt -> clip (or Soul still) -> pipeline.
runway.py's exact shape -- a thin raising wrapper under never-raises
edges -- because the economics are the same: Cloud API calls bill
Higgsfield API credits, a balance separate from the app subscription,
so the cheap path is their app and the API is a deliberate spend.

WHY THIS MODULE EXISTS AT ALL. shootgen.ZEROPAGE_AI_TOOLS has been
("HIGGSFIELD", "RUNWAY") since 2026-08-21 and the shot-plan prompt names
HIGGSFIELD first, but orchestrator.generate_render only knew VEO and
RUNWAY -- so every night a shot planned for Higgsfield came back
"no adapter wired for HIGGSFIELD" and the run parked on it. shot.py
already compiles the prompt (HIGGSFIELD_CAMERA, render_higgsfield);
this is the missing half.

Layers, runway.py's:
- generate_video / generate_image  -- thin wrappers. Submit, poll the
                                      status_url, download immediately.
                                      Raise on anything; callers catch.
- generate_candidates              -- the orchestrator's interface, the
                                      same signature runway/veo expose,
                                      so the nightly graph gains a tool
                                      by one dict entry.
- generate_for_shot                -- the Queue's approve-is-the-pick
                                      render for one concept shot.
- generate_from_prompt             -- the Workflows canvas's free-
                                      standing render.
- generate_image_from_prompt       -- a Soul still (keyframe / image
                                      post), the same walls.

THE SPEND GATE, and why it lives here and not in callers:
- HIGGSFIELD_SPEND_OK=1 must be set or the wrappers raise -- the default
  answer is "generate it in the Higgsfield app, on the subscription you
  already pay for". Set it per run, never in .env: an approval that is
  always on is not an approval.
- DAILY_CAP (HIGGSFIELD_DAILY_CAP, default 6) counted from the
  generations table -- the same wall veo.py and runway.py have, enforced
  by the DB so a runaway loop hits it.
- estimate_cost() prices a plan before anyone approves it. Higgsfield
  does not publish per-request API pricing (checked 2026-08-31), so the
  numbers are env-overridable ESTIMATES, not an invoice.

API contract verified against docs.higgsfield.ai 2026-08-31:
- Host:   https://api.higgsfield.ai   <- NOT platform.higgsfield.ai; an
          earlier draft of this file (unmerged worktree, 2026-08-25)
          used the platform host, which is why it was never live-tested.
- Auth:   Authorization: Key <key_id>:<key_secret>
- Submit: POST <host><model path>, JSON body
          -> {"status": "queued", "request_id", "status_url", "cancel_url"}
- Poll:   GET status_url until terminal. Terminal states documented as
          completed / failed / nsfw / canceled.
- Output: the completed payload carries the result inline. The IMAGE
          shape is documented: {"images": [{"url": ...}]}. The VIDEO
          shape is NOT published, so _output_url() prefers the likely
          keys and falls back to walking the JSON for the first non-
          control URL. PIN THE REAL KEY ON THE FIRST LIVE RENDER and
          date the comment -- an unpinned walk is a guess that happens
          to work.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import generative
from .db import DB_PATH
from .shot import Shot

HOST = os.environ.get("HIGGSFIELD_HOST", "https://api.higgsfield.ai").rstrip("/")

# The Soul path differs between the two places the docs describe it
# (quickstart: /higgsfield-ai/soul/v2/standard; the OpenAPI path list:
# /higgsfield-ai/soul/standard). The quickstart is the one with a full
# worked request/response, so it wins -- overridable until a live call
# settles it (2026-08-31).
SOUL_PATH = os.environ.get("HIGGSFIELD_SOUL_PATH", "/higgsfield-ai/soul/v2/standard")

SPEND_ENV = "HIGGSFIELD_SPEND_OK"
DAILY_CAP = int(os.environ.get("HIGGSFIELD_DAILY_CAP", "6"))
# The installation-wide wall, beside the per-account one. Defaults to the
# SAME number, so a single-operator database behaves exactly as it did --
# admitting a second account is what forces a deliberate decision about
# whose card is paying, instead of the total quietly doubling.
GLOBAL_DAILY_CAP = int(os.environ.get("HIGGSFIELD_GLOBAL_DAILY_CAP", str(DAILY_CAP)))
POLL_SECONDS = 3
TIMEOUT_SECONDS = int(os.environ.get("HIGGSFIELD_TIMEOUT_S", "600"))

# Not published on the docs (checked 2026-08-31) -- estimates for the
# confirm dialog, not a promise. Override once a real invoice is known.
COST_PER_CLIP_USD = float(os.environ.get("HIGGSFIELD_VIDEO_COST_USD", "0.40"))
COST_PER_IMAGE_USD = float(os.environ.get("HIGGSFIELD_IMAGE_COST_USD", "0.05"))

DONE_STATUSES = {"completed", "succeeded", "success", "done"}
FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "nsfw", "rejected"}

RENDER_DIR = Path(__file__).resolve().parent.parent / "data" / "renders" / "higgsfield"
RENDERS_ROOT = Path(__file__).resolve().parent.parent / "data" / "renders"


# --------------------------------------------------------------------------
# the model registry -- paths and the params each endpoint actually takes
# --------------------------------------------------------------------------
# AVAILABILITY IS NOT THE SAME AS DOCUMENTED. The public OpenAPI spec
# advertises seedance, kling and veo paths, but probed live against this
# account's key on 2026-08-31 (POST with an empty body, so no job could
# be created), only the kling routes answer: seedance and veo all return
# 404 {"detail":"model_not_found"}, while kling returns 400 "'prompt' is
# a required property" -- the route exists and rejected the body. The
# Cloud dashboard agrees: it lists only Soul 2, Soul Cinema and Soul ID.
# So the seedance/veo entries stay (the paths are right if the account
# ever gains them) but are marked unavailable, and DEFAULT_MODEL is a
# kling one. Re-probe before trusting an entry marked unavailable.
#
# `params` is a WHITELIST, not documentation: build_body() drops anything
# a model does not declare rather than sending a field the API will
# reject or silently ignore. `verified` dates the body schema against
# docs.higgsfield.ai/docs/openapi.json; an unverified entry sends the
# common fields only, which is the safe subset every model in the list
# advertises (prompt, duration).
VIDEO_MODELS: dict[str, dict] = {
    # 404 model_not_found on this account, probed 2026-08-31
    "seedance-pro": {
        "available": False,
        "t2v": "/bytedance/seedance/v1/pro/fast/text-to-video",
        "i2v": "/bytedance/seedance/v1/pro/fast/image-to-video",
        "params": ("duration", "resolution", "aspect_ratio", "camera_fixed"),
        "durations": (2, 12),          # min/max, integer seconds
        "verified": "2026-08-31",
    },
    # 404 model_not_found on this account, probed 2026-08-31
    "seedance-lite": {
        "available": False,
        "t2v": "/bytedance/seedance/v1/lite/text-to-video",
        "i2v": "/bytedance/seedance/v1/lite/image-to-video",
        "params": ("duration", "resolution", "aspect_ratio", "camera_fixed"),
        "durations": (2, 12),
        "verified": None,
    },
    # route confirmed live 2026-08-31
    "kling2.5": {
        "available": True,
        "t2v": "/kling-video/v2.5-turbo/pro/text-to-video",
        "i2v": "/kling-video/v2.5-turbo/pro/image-to-video",
        # kling takes NO aspect_ratio -- the frame comes from the source
        # image on i2v and the model default on t2v. It does take a real
        # negative_prompt field, which is where HOUSE_NEGATIVE belongs.
        "params": ("duration", "cfg_scale", "negative_prompt"),
        "durations": (5, 10),
        "verified": "2026-08-31",
    },
    # route confirmed live 2026-08-31
    "kling2.1": {
        "available": True,
        "t2v": "/kling-video/v2.1/master/text-to-video",
        "i2v": "/kling-video/v2.1/master/image-to-video",
        "params": ("duration", "cfg_scale", "negative_prompt"),
        "durations": (5, 10),
        "verified": None,
    },
    # 404 model_not_found on this account, probed 2026-08-31
    "veo3.1-fast": {
        "available": False,
        "t2v": "/veo3.1/fast",
        "i2v": "/veo3.1/fast/image-to-video",
        "params": ("duration", "resolution", "aspect_ratio", "generate_audio"),
        "durations": (4, 8),
        "verified": None,
    },
    # 404 model_not_found on this account, probed 2026-08-31
    "veo3.1": {
        "available": False,
        "t2v": "/veo3.1",
        "i2v": "/veo3.1/image-to-video",
        "params": ("duration", "resolution", "aspect_ratio", "generate_audio"),
        "durations": (4, 8),
        "verified": None,
    },
}

MODELS = tuple(VIDEO_MODELS)
AVAILABLE_MODELS = tuple(k for k, v in VIDEO_MODELS.items() if v.get("available"))
DEFAULT_MODEL = os.environ.get("HIGGSFIELD_MODEL", "kling2.5")
# The platform vertical, shot.HOUSE_ASPECT. NOTE: kling -- the only
# family this account can reach -- takes no aspect_ratio at all, so on
# text-to-video the frame is whatever the model defaults to. The 9:16
# house format therefore has to come from the KEYFRAME via
# image-to-video, which is how the pipeline runs anyway (keyframe node
# -> approve -> clip). A t2v kling render will not be vertical.
DEFAULT_ASPECT = "9:16"
DEFAULT_RESOLUTION = os.environ.get("HIGGSFIELD_RESOLUTION", "720")
DEFAULT_DURATION = 5


def model_spec(model: str) -> dict:
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        raise ValueError(f"model must be one of {MODELS}, got {model!r}")
    if not spec.get("available"):
        raise ValueError(
            f"{model!r} returned model_not_found on this account when probed "
            f"2026-08-31 -- its path is right but the account cannot reach it. "
            f"Available: {', '.join(AVAILABLE_MODELS)}. Re-probe before "
            f"removing this guard.")
    return spec


def build_body(prompt: str, *, model: str = DEFAULT_MODEL,
               image_url: Optional[str] = None, duration: int = DEFAULT_DURATION,
               aspect_ratio: str = DEFAULT_ASPECT,
               resolution: str = DEFAULT_RESOLUTION,
               negative_prompt: str = "") -> tuple[str, dict]:
    """(path, json body) for one render -- pure, so the whole request
    shape is testable without spending a credit.

    duration is clamped into the model's own range rather than sent as
    given: every one of these endpoints rejects an out-of-range value,
    and a refused request that costs a round-trip teaches nothing. The
    cut wants what it wants; the tool gives the nearest it has, same
    contract as Shot.duration_s.
    """
    spec = model_spec(model)
    path = spec["i2v"] if image_url else spec["t2v"]
    allowed = spec["params"]
    body: dict = {"prompt": prompt}
    if image_url:
        body["image_url"] = image_url
    if "duration" in allowed:
        low, high = spec["durations"]
        body["duration"] = int(min(max(int(duration), low), high))
    if "aspect_ratio" in allowed:
        body["aspect_ratio"] = aspect_ratio
    if "resolution" in allowed:
        body["resolution"] = resolution
    if "negative_prompt" in allowed and negative_prompt:
        body["negative_prompt"] = negative_prompt
    return path, body


# --------------------------------------------------------------------------
# credentials, gates, cost
# --------------------------------------------------------------------------
def _credentials() -> Optional[tuple[str, str]]:
    """Key id + secret. HIGGSFIELD_* names first, the docs' own HF_*
    names as a fallback (HF_ collides with Hugging Face conventions, so
    it is not what .env.example teaches)."""
    key_id = os.environ.get("HIGGSFIELD_API_KEY_ID") or os.environ.get("HF_API_KEY_ID")
    secret = (os.environ.get("HIGGSFIELD_API_KEY_SECRET")
              or os.environ.get("HF_API_KEY_SECRET"))
    return (key_id, secret) if key_id and secret else None


def has_key() -> bool:
    return _credentials() is not None


def spend_approved() -> bool:
    """The human approval for burning API credits. Per-run by design:
    set HIGGSFIELD_SPEND_OK=1 on the command, not in .env."""
    return (os.environ.get(SPEND_ENV) or "").strip() == "1"


def estimate_cost(n: int, *, model: str = DEFAULT_MODEL,
                  duration: int = DEFAULT_DURATION) -> float:
    """An ESTIMATE -- Higgsfield publishes no per-request API price
    (2026-08-31). Scales with duration so a 10s plan does not read as a
    5s one; the per-clip base is HIGGSFIELD_VIDEO_COST_USD."""
    return round(n * COST_PER_CLIP_USD * (max(int(duration), 1) / DEFAULT_DURATION), 2)


def estimate_image_cost(n: int) -> float:
    return round(n * COST_PER_IMAGE_USD, 2)


def _safe_error(e: Exception) -> str:
    """Neither credential may reach a page, a log line, or a DB row."""
    text = str(e)
    creds = _credentials()
    if creds:
        for secret in creds:
            if secret:
                text = text.replace(secret, "<HIGGSFIELD_CREDENTIAL>")
    return re.sub(r"(Key\s+)[A-Za-z0-9_\-.:]+", r"\1<redacted>", text)


def safe_prompt(prompt: str, db_path=None) -> str:
    """Asset names swapped for their render aliases, the same table
    runway.py sanitises against.

    The alias is a property of the ASSET, not of the vendor: "Cyclops"
    trips a third-party-content classifier wherever it is sent, and the
    keyframe was carrying the look anyway. Reusing runway.render_aliases
    keeps one list -- two would drift, and the drift would only show up
    as a refused render mid-run.
    """
    from .runway import render_aliases
    text = prompt or ""
    for name, alias in render_aliases(db_path).items():
        text = re.sub(r"(?<![\w])" + re.escape(name) + r"(?![\w])",
                      alias, text, flags=re.IGNORECASE)
    return text


def generations_today(db_path=None, *, account_id=None, everyone: bool = False) -> int:
    """This account's higgsfield generations since UTC midnight -- what
    DAILY_CAP counts against. `everyone=True` gives the installation-wide
    count that GLOBAL_DAILY_CAP counts against."""
    return generative.used_today(
        "higgsfield", db_path if db_path is not None else DB_PATH,
        account_id=account_id, everyone=everyone,
    )


# --------------------------------------------------------------------------
# the wire
# --------------------------------------------------------------------------
# api.higgsfield.ai sits behind Cloudflare, and Cloudflare refuses
# urllib's default "Python-urllib/3.x" signature with a 403 (error 1010,
# "banned based on your browser's signature") BEFORE the request ever
# reaches Higgsfield -- so it reads as an auth failure and is not one.
# Verified live 2026-08-31: same URL, same key, default UA -> 403; this
# UA -> 404 "Not found" (the id is fake, the credentials are fine), and
# with no Authorization header at all -> 401 "Invalid credentials".
# Do not remove this header; it is load-bearing, not cosmetic.
USER_AGENT = os.environ.get(
    "HIGGSFIELD_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def _request(url: str, payload: Optional[dict] = None) -> dict:
    """One authenticated JSON round-trip. POST when there is a payload,
    else GET. Injected as `http` in tests so nothing here needs a key."""
    creds = _credentials()
    if creds is None:
        raise RuntimeError(
            "HIGGSFIELD_API_KEY_ID / HIGGSFIELD_API_KEY_SECRET not set "
            "(create a key in Higgsfield Cloud)")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Key {creds[0]}:{creds[1]}",
                 "Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": USER_AGENT},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode())


# The documented image shape is {"images": [{"url": ...}]}. The video
# shape is not published, so these are the candidates in order of
# likelihood, checked before falling back to the walk. PIN THE REAL ONE
# after the first live clip and delete the guesswork.
OUTPUT_KEYS = ("videos", "video", "images", "image", "output", "outputs", "result")


def _first_url(value, skip: set) -> Optional[str]:
    if isinstance(value, str):
        return value if value.startswith(("http://", "https://")) and value not in skip else None
    if isinstance(value, dict):
        for key in ("url", "video_url", "image_url", "signed_url"):
            found = _first_url(value.get(key), skip)
            if found:
                return found
        for nested in value.values():
            found = _first_url(nested, skip)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _first_url(item, skip)
            if found:
                return found
    return None


def _output_url(payload: dict, skip: set) -> Optional[str]:
    """The finished asset's URL: the documented/likely keys first, then
    a walk of the whole payload as a last resort. The walk skips the
    status/cancel URLs, which are the two http strings every payload
    carries and would otherwise 'succeed' by downloading JSON."""
    if isinstance(payload, dict):
        for key in OUTPUT_KEYS:
            if key in payload:
                found = _first_url(payload[key], skip)
                if found:
                    return found
    return _first_url(payload, skip)


def _download(url: str, out_path: Path) -> None:
    """Outputs are hosted and expire; download the moment the job
    finishes and the repo keeps the file forever."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as response, open(out_path, "wb") as f:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def _submit_and_wait(path: str, body: dict, *, http=None,
                     timeout_s: int = TIMEOUT_SECONDS) -> tuple[dict, set]:
    """Submit -> poll to a terminal state -> (final payload, control
    URLs to skip). Raises on failure or timeout."""
    http = http or _request
    submitted = http(HOST + path, body)
    status_url = submitted.get("status_url")
    if not status_url:
        raise RuntimeError(
            f"Higgsfield submit returned no status_url (keys: {sorted(submitted)})")
    skip = {status_url, submitted.get("cancel_url")}

    deadline = time.time() + timeout_s
    state = submitted
    while True:
        state = http(status_url)
        status = str(state.get("status") or "").lower()
        if status in DONE_STATUSES:
            return state, skip
        if status in FAILED_STATUSES:
            raise RuntimeError(
                f"Higgsfield job {status}: "
                f"{state.get('error') or state.get('detail') or 'no reason given'}")
        if time.time() > deadline:
            raise RuntimeError(
                f"Higgsfield job still {status or 'pending'} after {timeout_s}s")
        time.sleep(POLL_SECONDS)


def generate_video(prompt: str, out_path, *, model: str = DEFAULT_MODEL,
                   image_url: Optional[str] = None,
                   duration: int = DEFAULT_DURATION,
                   aspect_ratio: str = DEFAULT_ASPECT,
                   resolution: str = DEFAULT_RESOLUTION,
                   negative_prompt: str = "",
                   http=None, db_path=None) -> Path:
    """
    The thin wrapper: submit -> poll -> download. Raises on anything --
    including a missing spend approval, which is checked HERE so no
    caller can spend a credit around the gate.
    """
    if not spend_approved():
        raise RuntimeError(
            f"credit spend not approved: render this in the Higgsfield app "
            f"instead, or set {SPEND_ENV}=1 on this run to approve "
            f"~${estimate_cost(1, model=model, duration=duration)} of API credits"
        )
    # Name-swap first, THEN build the body: what we check has to be what
    # we send.
    prompt = safe_prompt(prompt, db_path)
    path, body = build_body(prompt, model=model, image_url=image_url,
                            duration=duration, aspect_ratio=aspect_ratio,
                            resolution=resolution, negative_prompt=negative_prompt)
    state, skip = _submit_and_wait(path, body, http=http)
    url = _output_url(state, skip)
    if not url:
        raise RuntimeError(
            f"Higgsfield job finished but no output URL was found in the "
            f"payload (keys: {sorted(state)})")
    out_path = Path(out_path)
    _download(url, out_path)
    return out_path


def generate_image(prompt: str, out_path, *, http=None, db_path=None,
                   aspect_ratio: str = DEFAULT_ASPECT) -> Path:
    """A Soul still, same wall. The documented completed payload is
    {"images": [{"url": ...}]} (docs.higgsfield.ai quickstart,
    2026-08-31)."""
    if not spend_approved():
        raise RuntimeError(
            f"credit spend not approved: generate this in the Higgsfield app "
            f"instead, or set {SPEND_ENV}=1 on this run to approve "
            f"~${estimate_image_cost(1)} of API credits"
        )
    prompt = safe_prompt(prompt, db_path)
    state, skip = _submit_and_wait(
        SOUL_PATH, {"prompt": prompt, "aspect_ratio": aspect_ratio}, http=http)
    url = _output_url(state, skip)
    if not url:
        raise RuntimeError(
            f"Higgsfield Soul job finished but no image URL was found "
            f"(keys: {sorted(state)})")
    out_path = Path(out_path)
    _download(url, out_path)
    return out_path


# --------------------------------------------------------------------------
# references: Higgsfield needs a URL, not bytes
# --------------------------------------------------------------------------
def _local_render_bytes(value: str):
    """A site-relative /renders/ URL -> that file's bytes, or None.
    Mirrors runway._local_render_bytes; anything escaping data/renders/
    is refused."""
    try:
        root = RENDERS_ROOT.resolve()
        target = (root / value[len("/renders/"):]).resolve()
        if root in target.parents and target.is_file():
            return target.read_bytes()
    except OSError:
        return None
    return None


def as_image_url(value, *, resolve_photo=None) -> Optional[str]:
    """Anything we might have stored as a reference -> a URL Higgsfield
    can actually FETCH, or None.

    This is the one real difference from runway.as_prompt_image, and it
    is worth stating plainly: Runway accepts an inline data: URI, so a
    keyframe on a machine without R2 still anchors. Higgsfield's
    image-to-video endpoints take `image_url` -- a URI their servers
    fetch -- so a local keyframe MUST be uploaded somewhere public
    first. With storage configured that happens here; without it the
    reference is dropped and the caller records prompt_image=False, so
    the Queue card cannot claim an anchor that was never sent. That was
    exactly runway's old silent-drop bug (see as_prompt_image), and it
    is not being repeated with a different vendor.
    """
    from . import storage

    if not value and not isinstance(value, (bytes, bytearray)):
        return None
    if isinstance(value, str):
        value = value.strip()
        if value.startswith(("http://", "https://")):
            return value
        if value.startswith("data:"):
            return None        # not fetchable by a remote server
        data = (_local_render_bytes(value) if value.startswith("/renders/")
                else None)
        if data is None and resolve_photo is not None:
            try:
                target = resolve_photo(value)
            except Exception:
                target = None
            if target is not None:
                try:
                    data = Path(target).read_bytes()
                except OSError:
                    data = None
    elif isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        return None

    if not data or not storage.configured():
        return None

    import hashlib

    from .gemini_utils import sniff_mime
    mime = sniff_mime(data)
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
    key = f"refs/higgsfield/{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    tmp = RENDER_DIR / "refs" / Path(key).name
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    try:
        return storage.upload_file(tmp, key=key, content_type=mime)
    except Exception:
        return None            # a reference is an enhancement, never a gate


# --------------------------------------------------------------------------
# the never-raises edges
# --------------------------------------------------------------------------
def _shot_row_for_prompt(prompt: str, db_path, note: str, account_id: Optional[int] = None) -> int:
    """A generations row needs a shot to hang off. The graph's AI shots
    do not have one, so synthesize a minimal Shot -- the row exists to
    make the attempt countable, and its notes say where it came from."""
    kwargs = {"path": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="as prompted")
    return generative.add_shot(shot, notes=note, **kwargs, account_id=account_id)


def generate_candidates(prompt: str, out_dir, n: int = 3, *,
                        shot_id: Optional[int] = None, db_path=None,
                        model: str = DEFAULT_MODEL, http=None, account_id: Optional[int] = None, **cfg) -> dict:
    """
    Never raises. The interface orchestrator.generate_render calls --
    identical in signature and result shape to runway.generate_candidates
    and veo.generate_candidates, which is the whole point: the nightly
    graph gains HIGGSFIELD by one entry in its connectors dict, and a
    shot planned for Higgsfield stops coming back "no adapter wired".

    {"ok", "candidates": [{path, generation_id, model}], "shot_id",
    "error"} -- a missing approval, a missing key, a failed job or the
    daily cap is a result the caller can show, not an exception that
    takes the night down. Partial success is success.
    """
    n = int(os.environ.get("HIGGSFIELD_CANDIDATES", n))
    kwargs = {"path": db_path} if db_path is not None else {}
    duration = int(cfg.get("duration", DEFAULT_DURATION))

    try:
        if model not in VIDEO_MODELS:
            return {"ok": False, "candidates": [],
                    "error": f"unknown Higgsfield model {model!r} "
                             f"(HIGGSFIELD_MODEL); known: {', '.join(MODELS)}"}
        if not has_key():
            return {"ok": False, "candidates": [],
                    "error": "Higgsfield not configured — "
                             "HIGGSFIELD_API_KEY_ID / _SECRET are unset"}
        if not spend_approved():
            return {"ok": False, "candidates": [],
                    "error": f"credit spend not approved: generate in the "
                             f"Higgsfield app, or set {SPEND_ENV}=1 to approve "
                             f"~${estimate_cost(n, model=model, duration=duration)} "
                             f"of API credits for this run"}

        generative.init(**kwargs)
        refusal = generative.cap_error(
            "higgsfield", n, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            path=db_path if db_path is not None else DB_PATH,
            env_prefix="HIGGSFIELD", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "candidates": [], "error": refusal}

        if shot_id is None:
            shot_id = _shot_row_for_prompt(
                prompt, db_path, "auto-created by higgsfield.generate_candidates")

        out_dir = Path(out_dir)
        candidates, errors = [], []
        for i in range(1, n + 1):
            out_path = out_dir / f"cand{i}.mp4"
            try:
                generate_video(prompt, out_path, model=model, http=http,
                               db_path=db_path, **cfg)
            except Exception as e:
                errors.append(f"candidate {i}: {_safe_error(e)}")
                continue
            generation_id = generative.record_generation(
                shot_id, "higgsfield", prompt,
                params={"model": model, **cfg},
                output_path=str(out_path),
                cost_usd=estimate_cost(1, model=model, duration=duration),
                notes=None,
                **kwargs,
             account_id=account_id)
            candidates.append({"path": str(out_path),
                               "generation_id": generation_id, "model": model})

        return {"ok": bool(candidates), "candidates": candidates,
                "shot_id": shot_id,
                "error": "; ".join(errors) if errors else None}
    except Exception as e:
        return {"ok": False, "candidates": [], "error": _safe_error(e)}


def _publish(out_path: Path, content_type: str) -> str:
    """R2 when configured (Instagram needs a public URL), else the app's
    own /renders mount."""
    from . import storage
    if storage.configured():
        return storage.upload_file(
            out_path, key=f"renders/higgsfield/{out_path.name}",
            content_type=content_type)
    return f"/renders/higgsfield/{out_path.name}"


def generate_for_shot(concept_id: int, shot_n, *, db_path=None,
                      model: str = DEFAULT_MODEL, resolve_photo=None,
                      http=None,
                      account_id: Optional[int] = None,
) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    One render for one concept shot, through every wall this module has
    -- the spend gate lives inside generate_video, so this layer cannot
    spend around it; the cap is checked before any call; the attempt is
    a generations row either way the pick later goes.

    Anchors on the shot's reference_image through as_image_url, and
    records prompt_image as what was ACTUALLY sent -- False when the
    keyframe could not be made fetchable (no R2), so nothing downstream
    can claim an anchor that never left the building.
    """
    from . import preprod
    kwargs = {"path": db_path} if db_path is not None else {}

    try:
        refusal = generative.cap_error(
            "higgsfield", 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            path=db_path if db_path is not None else DB_PATH,
            env_prefix="HIGGSFIELD", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "error": refusal}

        concept = preprod.get_concept(concept_id, **kwargs, account_id=account_id)
        if concept is None:
            return {"ok": False, "error": f"no concept {concept_id}"}
        shot = next((s for s in concept.get("shots") or []
                     if s.get("n") == shot_n), None)
        if shot is None:
            return {"ok": False, "error": f"concept {concept_id} has no shot {shot_n}"}
        prompt = (shot.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False,
                    "error": f"shot {shot_n} has no AI prompt to render from"}

        image_url = as_image_url(shot.get("reference_image"),
                                 resolve_photo=resolve_photo)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"c{concept_id}-s{shot_n}-{stamp}.mp4"
        generate_video(prompt, out_path, model=model, image_url=image_url,
                       http=http, db_path=db_path)

        shot_row_id = _shot_row_for_prompt(
            prompt, db_path, "auto-created by higgsfield.generate_for_shot")
        generation_id = generative.record_generation(
            shot_row_id, "higgsfield", prompt,
            params={"model": model, "aspect_ratio": DEFAULT_ASPECT,
                    "duration": DEFAULT_DURATION,
                    "concept_id": concept_id, "shot_n": shot_n,
                    "prompt_image": bool(image_url)},
            output_path=str(out_path),
            cost_usd=estimate_cost(1, model=model),
            **kwargs,
         account_id=account_id)
        media_url = _publish(out_path, "video/mp4")
        preprod.set_shot_media_url(concept_id, shot_n, media_url, **kwargs, account_id=account_id)
        return {"ok": True, "media_url": media_url,
                "generation_id": generation_id, "path": str(out_path),
                "error": None}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e)}


def generate_from_prompt(prompt: str, *, reference_image=None, db_path=None,
                         model: str = DEFAULT_MODEL, resolve_photo=None,
                         http=None,
                         account_id: Optional[int] = None,
) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    The free-standing render behind the Workflows canvas's Generate node
    -- generate_for_shot's walls without its concept/shot coupling.
    """
    kwargs = {"path": db_path} if db_path is not None else {}

    try:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "an empty prompt renders nothing"}

        # a fresh DB has no generations table until something inits it;
        # the cap count must not be the thing that discovers that
        generative.init(**kwargs)
        refusal = generative.cap_error(
            "higgsfield", 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            path=db_path if db_path is not None else DB_PATH,
            env_prefix="HIGGSFIELD", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "error": refusal}

        image_url = as_image_url(reference_image, resolve_photo=resolve_photo)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"wf-{stamp}.mp4"
        generate_video(prompt, out_path, model=model, image_url=image_url,
                       http=http, db_path=db_path)

        shot_row_id = _shot_row_for_prompt(
            prompt, db_path, "auto-created by higgsfield.generate_from_prompt")
        generation_id = generative.record_generation(
            shot_row_id, "higgsfield", prompt,
            params={"model": model, "aspect_ratio": DEFAULT_ASPECT,
                    "duration": DEFAULT_DURATION, "source": "workflow",
                    "prompt_image": bool(image_url)},
            output_path=str(out_path),
            cost_usd=estimate_cost(1, model=model),
            **kwargs,
         account_id=account_id)
        return {"ok": True, "media_url": _publish(out_path, "video/mp4"),
                "generation_id": generation_id, "path": str(out_path),
                "error": None}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e)}


def generate_image_from_prompt(prompt: str, *, db_path=None, http=None, account_id: Optional[int] = None) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    A Soul still -- the keyframe alternative to nano_banana and the
    image-post path. Same walls; the image lands on R2 when configured
    (Instagram needs a public URL) else the app's /renders mount.
    """
    kwargs = {"path": db_path} if db_path is not None else {}

    try:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "an empty prompt renders nothing"}

        generative.init(**kwargs)
        refusal = generative.cap_error(
            "higgsfield", 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            path=db_path if db_path is not None else DB_PATH,
            env_prefix="HIGGSFIELD", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "error": refusal}

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"soul-{stamp}.jpg"
        generate_image(prompt, out_path, http=http, db_path=db_path)

        shot_row_id = _shot_row_for_prompt(
            prompt, db_path, "auto-created by higgsfield.generate_image_from_prompt")
        generation_id = generative.record_generation(
            shot_row_id, "higgsfield", prompt,
            params={"model": "soul-standard", "source": "workflow"},
            output_path=str(out_path),
            cost_usd=estimate_image_cost(1),
            **kwargs,
         account_id=account_id)
        return {"ok": True, "media_url": _publish(out_path, "image/jpeg"),
                "generation_id": generation_id, "path": str(out_path),
                "error": None}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e)}

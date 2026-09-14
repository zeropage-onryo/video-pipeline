#!/usr/bin/env python3
"""
The fal.ai connector: one queue API, many models -- and the thing that
finally wakes the four dormant platforms.

WHY THIS MODULE EXISTS. shot.PLATFORMS has carried prompt renderers for
`kling`, `ltx`, `wan` and `seedance` since the registry was written, and
providers.py's own docstring said the quiet part out loud: "kling,
seedance, ltx and wan already have prompt-compilation support in
shot.PLATFORMS but no execution adapter". So shootgen could plan a shot
for KLING, shot.py could compile a beautiful Kling-shaped prompt, and
orchestrator.generate_render answered "no adapter wired for KLING" and
parked the run. Four of the eight platforms this project can WRITE for
were platforms it could not RENDER on. fal.ai hosts all four behind one
queue API and one key, so one adapter closes all four gaps at once.

Layers, higgsfield.py's exactly (which is runway.py's):
- generate_video     -- the thin wrapper. Submit, poll the status_url,
                        fetch the response_url, download. Raises on
                        anything, including a missing spend approval.
- generate_image     -- the same walls over fal's FLUX endpoints. See
                        "IMAGES" below for why this exists and why it
                        does not touch the video contract.
- generate_candidates -- the never-raises edge orchestrator.generate_render
                        calls; N attempts, a generations row each,
                        nothing ever auto-kept.
- connector(platform) -- ONE module, MANY models (higgsfield's kling2.5
                        handling, one size up). fal is a single entry in
                        providers.VIDEO_PROVIDERS with a MODELS table;
                        the four platform names are bindings of this
                        module to one model each, not four registry
                        entries pretending to be four vendors.

THE SPEND GATE, same order and same semantics as higgsfield/runway:
- THE APPROVAL IS THE CLICK (2026-09-09, Mike's call). generate_video
  refuses unless the caller passes approved=True, which the routes a
  person drives do and nothing else does. FAL_SPEND_OK=1 still satisfies
  the gate when no caller says otherwise -- that is what keeps the
  unattended paths (orchestrator, autopilot, the CLI) needing a
  deliberate arming of their own. See spend_approved().
  Unlike Runway and Higgsfield there is no free app to fall back to here:
  fal is an API company, so the refusal points at the estimate instead of
  at a cheaper door.
- FAL_DAILY_CAP / FAL_GLOBAL_DAILY_CAP through generative.cap_error,
  counted from the generations table so a runaway loop hits a wall the DB
  enforces rather than one this process remembers.
- estimate_cost() prices a plan before anyone approves it, off the dated
  MODELS table below.

THE QUEUE API, verified against fal.ai/docs 2026-09-08:
- Base:   https://queue.fal.run
- Auth:   Authorization: Key $FAL_KEY   (ONE secret, unlike higgsfield's
          id:secret pair)
- Submit: POST https://queue.fal.run/{model_id}, JSON body of
          model-specific args -> {"request_id", "response_url",
          "status_url", "cancel_url", "queue_position"}
- Poll:   GET {status_url} -> status IN_QUEUE | IN_PROGRESS | COMPLETED
- Result: GET {response_url} -- a SEPARATE call. This is the one real
          shape difference from higgsfield, whose terminal status payload
          carries the output inline.
- Cancel: PUT {cancel_url}

**THERE IS NO FAILED STATUS**, and that is the fact worth carrying in
your head while reading _submit_and_wait. fal documents exactly three
states and none of them is terminal-failure: a job that fails comes back
COMPLETED with `error` / `error_type` fields in the payload, or the HTTP
call itself errors. So the code cannot wait for a failure string that
never arrives -- it checks for an error payload on every poll AND on the
result, treats an unrecognised status as a reason to keep waiting rather
than as success, and always dies on the deadline. A poller that only
knows how to stop on "FAILED" here is a poller that hangs.

IMAGES. fal also hosts FLUX, and adding it cost nothing structural: the
image path shares the queue, the key, the gates and the redaction, and
touches none of the six names providers.REQUIRED checks. It gets its own
IMAGE_MODELS table, its own per-image price, and logs under the tool name
"fal" (generative.IMAGE_TOOLS) rather than under a video platform, so an
image can never be mistaken for a clip in the scoreboards and the VIDEO
daily cap -- which counts the four platform tool names -- does not move
when someone renders a still.
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

from . import account_keys, generative
from .shot import Shot

HOST = os.environ.get("FAL_HOST", "https://queue.fal.run").rstrip("/")

SPEND_ENV = "FAL_SPEND_OK"
DAILY_CAP = int(os.environ.get("FAL_DAILY_CAP", "6"))
# The installation-wide wall beside the per-account one, defaulting to the
# SAME number so a single-operator database behaves exactly as it did --
# runway.py/higgsfield.py's comment, and the same reasoning: admitting a
# second account should force a decision about whose card is paying.
# 0 = no installation-wide ceiling (2026-09-14, Mike's call): a user who
# brought their own key was still consuming the operator's shared budget and
# could lock everyone else out of money nobody spent. The per-account cap
# (FAL_DAILY_CAP) is the wall that remains. Set FAL_GLOBAL_DAILY_CAP to a
# positive number to put the ceiling back -- see generative.cap_error.
GLOBAL_DAILY_CAP = int(os.environ.get("FAL_GLOBAL_DAILY_CAP", "0"))
POLL_SECONDS = 3
TIMEOUT_SECONDS = int(os.environ.get("FAL_TIMEOUT_S", "900"))

# The three documented states. COMPLETED is terminal; the other two mean
# keep waiting -- and so does anything else, see _submit_and_wait.
STATUS_QUEUED = "IN_QUEUE"
STATUS_RUNNING = "IN_PROGRESS"
STATUS_DONE = "COMPLETED"
PENDING_STATUSES = {STATUS_QUEUED, STATUS_RUNNING}

RENDER_DIR = Path(__file__).resolve().parent.parent / "data" / "renders" / "fal"
RENDERS_ROOT = Path(__file__).resolve().parent.parent / "data" / "renders"


# --------------------------------------------------------------------------
# the model table -- ids and prices, dated, in shot.py's camera-map style
# --------------------------------------------------------------------------
# EVERY id and price below was read off that model's own fal.ai page on
# 2026-09-08. The catalogue moves fast enough that an undated table is a
# guess: fal ships new majors monthly (v2.5-turbo -> v3 -> v3-turbo for
# Kling inside one quarter), renames namespaces (`fal-ai/wan-*` became
# `alibaba/wan-3.0/*`, `bytedance/seedance-2.0/*` is likewise vendor-
# namespaced, NOT `fal-ai/`-prefixed), and reprices. Re-check the `source`
# URL and re-date the entry before trusting one; a stale id is a 404 after
# a queue wait, and a stale price is a spend approval given on a lie.
#
# `prices` is USD per SECOND of output, keyed by resolution, because that
# is how fal bills every video model here -- there is no per-clip sticker
# price to copy. Env override per model: FAL_PRICE_<KEY>, e.g.
# FAL_PRICE_LTX2_3=0.07, applied to every resolution of that model (the
# override exists for a repriced model, not for modelling a rate card).
#
# `params` is a WHITELIST, not documentation: build_body drops anything a
# model does not declare rather than sending a field the endpoint will
# reject after the queue wait. `platform` is the shot.PLATFORMS name this
# entry renders for, which is also the tool a generations row is logged
# under -- so the scoreboard says "kling", the truth about what rendered
# the clip, rather than "fal", the truth about who invoiced it.
def _price_env(key: str, prices: dict[str, float]) -> dict[str, float]:
    """FAL_PRICE_<KEY> overrides every resolution of one model."""
    name = "FAL_PRICE_" + re.sub(r"[^A-Z0-9]", "_", key.upper())
    override = os.environ.get(name)
    if not override:
        return prices
    return {resolution: float(override) for resolution in prices}


VIDEO_MODELS: dict[str, dict] = {
    # $0.06/s at 1080p makes this the cheapest real clip in the whole
    # repo (5s = $0.30, against runway's $0.25 and higgsfield's $0.40),
    # which is why it is DEFAULT_MODEL. 9:16 native.
    #
    # THE WEIGHTS ARE OPEN, THE LICENSE IS NOT APACHE-2.0 (this comment
    # said Apache-2.0 until 2026-09-09; it was never true for any LTX-2
    # release). It is the LTX-2 Community License: free commercial use
    # INCLUDING hosting for third parties (SaaS) under $10,000,000
    # annual revenue, counted across all affiliates and entities under
    # common control; a paid agreement above that line. Three terms that
    # bind a fine-tune rather than a rented API call, which is the only
    # reason this belongs in a price table: a Derivative -- explicitly
    # including fine-tuned weights AND models trained on LTX Outputs --
    # must be distributed under THIS license, the use restrictions
    # (Attachment A) must be passed to anyone we distribute or serve to,
    # and modified files must carry a notice saying they were changed.
    # Nothing here constrains billing fal for a render; all of it
    # constrains shipping a LoRA trained on our own footage.
    # https://huggingface.co/Lightricks/LTX-2.3/blob/main/LICENSE
    # checked 2026-09-09
    "ltx2.3": {
        "t2v": "fal-ai/ltx-2.3/text-to-video",
        "i2v": "fal-ai/ltx-2.3/image-to-video",
        "params": ("duration", "resolution", "aspect_ratio", "negative_prompt"),
        "durations": (1, 20),
        "resolutions": ("1080p", "1440p", "2160p"),
        "default_resolution": "1080p",
        "prices": {"1080p": 0.06, "1440p": 0.12, "2160p": 0.24},
        "platform": "ltx",
        "checked": "2026-09-08",
        "source": "https://fal.ai/models/fal-ai/ltx-2.3/image-to-video",
    },
    # NOTE THE NAMESPACE: `alibaba/`, not `fal-ai/`. The older
    # fal-ai/wan-i2v and fal-ai/wan-pro routes still exist and are a
    # different, older model -- do not "fix" this prefix.
    "wan3": {
        "t2v": "alibaba/wan-3.0/text-to-video",
        "i2v": "alibaba/wan-3.0/image-to-video",
        "params": ("duration", "resolution", "aspect_ratio"),
        "durations": (2, 10),
        "resolutions": ("480p", "720p", "1080p"),
        "default_resolution": "720p",
        "prices": {"480p": 0.05, "720p": 0.10, "1080p": 0.20},
        "platform": "wan",
        "checked": "2026-09-08",
        "source": "https://fal.ai/models/alibaba/wan-3.0/image-to-video",
    },
    # Kling's current turbo pro. $0.14/s flat -- fal lists no per-
    # resolution rate card for this one, so the single key is honest
    # rather than three copies of the same number.
    "kling3-turbo-pro": {
        "t2v": "fal-ai/kling-video/v3/turbo/pro/text-to-video",
        "i2v": "fal-ai/kling-video/v3/turbo/pro/image-to-video",
        "params": ("duration", "aspect_ratio", "negative_prompt", "cfg_scale"),
        "durations": (5, 10),
        "resolutions": ("1080p",),
        "default_resolution": "1080p",
        "prices": {"1080p": 0.14},
        "platform": "kling",
        "checked": "2026-09-08",
        "source": "https://fal.ai/models/fal-ai/kling-video/v3/turbo/pro/image-to-video",
    },
    # Seedance 2.0's fast tier: $0.2419/s against the standard tier's
    # $0.3024/s, capped at 720p. 720p IS the house format's ceiling for a
    # 9:16 social clip, so paying 25% more for a resolution nothing
    # downstream uses would be spending for the invoice's sake. The
    # standard tier is the entry below when someone wants 1080p.
    "seedance2-fast": {
        "t2v": "bytedance/seedance-2.0/fast/text-to-video",
        "i2v": "bytedance/seedance-2.0/fast/image-to-video",
        "params": ("duration", "resolution", "aspect_ratio", "generate_audio", "seed"),
        "durations": (4, 15),
        "resolutions": ("480p", "720p"),
        "default_resolution": "720p",
        "prices": {"480p": 0.2419, "720p": 0.2419},
        "platform": "seedance",
        "checked": "2026-09-08",
        "source": "https://fal.ai/models/bytedance/seedance-2.0/image-to-video",
    },
    "seedance2": {
        "t2v": "bytedance/seedance-2.0/text-to-video",
        "i2v": "bytedance/seedance-2.0/image-to-video",
        "params": ("duration", "resolution", "aspect_ratio", "generate_audio", "seed"),
        "durations": (4, 15),
        "resolutions": ("480p", "720p", "1080p"),
        "default_resolution": "720p",
        # 720p i2v is $0.3024/s; the 1080p t2v rate card reads $0.682/s.
        "prices": {"480p": 0.3024, "720p": 0.3024, "1080p": 0.682},
        "platform": "seedance",
        "checked": "2026-09-08",
        "source": "https://fal.ai/models/bytedance/seedance-2.0/image-to-video",
    },
}

for _key, _spec in VIDEO_MODELS.items():
    _spec["prices"] = _price_env(_key, _spec["prices"])

# DELIBERATELY ABSENT: fal-ai/veo3.1/image-to-video ($0.40/s with audio at
# 1080p, checked 2026-09-08, https://fal.ai/models/fal-ai/veo3.1/image-to-video).
# It exists and it works, but veo has its own adapter (src/veo.py) on the
# Gemini key, and a VEO row rendered here would land in the generations
# table under tool "veo" -- silently sharing veo.py's daily cap with a
# different vendor's invoice. Two adapters, one cap, two credit cards is
# the kind of thing that is only discovered by a surprise bill. If fal
# ever becomes the cheaper door to Veo, move the whole platform, don't
# add a second one.

MODELS = tuple(VIDEO_MODELS)
DEFAULT_MODEL = os.environ.get("FAL_MODEL", "ltx2.3")
DEFAULT_DURATION = 5
# The platform vertical, shot.HOUSE_ASPECT's shape. Sent only on
# text-to-video: on image-to-video every one of these models takes the
# frame from the source image, and declaring a conflicting ratio beside a
# 9:16 keyframe is a fight the image wins or the request loses.
DEFAULT_ASPECT = "9:16"

# The bridge that wakes the dormant four: shot.PLATFORMS name -> the model
# a shot planned for that platform renders on. `connector(name)` binds
# this module to one of these, and orchestrator.generate_render maps the
# uppercase tool names onto those bindings. Keep the choice CHEAPEST-
# CREDIBLE per family: the platform is the creative decision shootgen
# already made, the model within it is ours.
PLATFORM_MODELS: dict[str, str] = {
    "kling": "kling3-turbo-pro",
    "ltx": "ltx2.3",
    "wan": "wan3",
    "seedance": "seedance2-fast",
}
# What generations_today() counts for the FAL daily cap: every tool name
# this adapter can write. NOT "fal" -- a row is logged under the platform
# that rendered it, so the cap has to sum the platforms rather than read
# one label. The image tool name is deliberately outside this set (see the
# module docstring's IMAGES note).
VIDEO_LOG_TOOLS = tuple(sorted(PLATFORM_MODELS))

# FLUX and friends. Priced per MEGAPIXEL, not per image, so the constant
# below is "what one 1MP image costs" and estimate_image_cost says so.
IMAGE_MODELS: dict[str, dict] = {
    "flux-pro1.1": {
        "endpoint": "fal-ai/flux-pro/v1.1",
        "params": ("width", "height", "num_inference_steps", "guidance_scale", "seed"),
        "usd_per_megapixel": 0.04,
        "checked": "2026-09-08",
        "source": "https://fal.ai/models/fal-ai/flux-pro/v1.1",
    },
}
IMAGE_MODEL_NAMES = tuple(IMAGE_MODELS)
DEFAULT_IMAGE_MODEL = os.environ.get("FAL_IMAGE_MODEL", "flux-pro1.1")
COST_PER_IMAGE_USD = float(
    os.environ.get("FAL_IMAGE_COST_USD",
                   str(IMAGE_MODELS[DEFAULT_IMAGE_MODEL]["usd_per_megapixel"])))
# The tool name an image attempt is logged under -- generative.IMAGE_TOOLS,
# beside midjourney and nano, never a video platform.
IMAGE_LOG_TOOL = "fal"


def model_spec(model: str) -> dict:
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        raise ValueError(f"model must be one of {MODELS}, got {model!r}")
    return spec


def model_for_platform(platform: str) -> str:
    """The fal model a shot planned for `platform` renders on."""
    model = PLATFORM_MODELS.get((platform or "").lower())
    if model is None:
        raise ValueError(
            f"fal renders for {', '.join(sorted(PLATFORM_MODELS))}, not {platform!r}")
    return model


def build_body(prompt: str, *, model: str = DEFAULT_MODEL,
               image_url: Optional[str] = None, duration: int = DEFAULT_DURATION,
               aspect_ratio: str = DEFAULT_ASPECT,
               resolution: Optional[str] = None,
               negative_prompt: str = "") -> tuple[str, dict]:
    """(model_id, json body) for one render -- pure, so the entire request
    shape is testable without spending a cent.

    duration is clamped into the model's own range rather than sent as
    given: every one of these endpoints rejects an out-of-range value, and
    a refused request that cost a queue wait teaches nothing. The cut wants
    what it wants; the tool gives the nearest it has, the same contract
    Shot.duration_s has always had.

    aspect_ratio is sent on text-to-video ONLY. Handed a keyframe, all of
    these models derive the frame from the image, and a 16:9 default
    arriving beside a 9:16 still is either ignored (best case) or obeyed
    (a letterboxed clip nobody asked for).
    """
    spec = model_spec(model)
    model_id = spec["i2v"] if image_url else spec["t2v"]
    allowed = spec["params"]
    body: dict = {"prompt": prompt}
    if image_url:
        body["image_url"] = image_url
    if "duration" in allowed:
        low, high = spec["durations"]
        body["duration"] = int(min(max(int(duration), low), high))
    if "aspect_ratio" in allowed and not image_url:
        body["aspect_ratio"] = aspect_ratio
    if "resolution" in allowed:
        body["resolution"] = resolution or spec["default_resolution"]
    if "negative_prompt" in allowed and negative_prompt:
        body["negative_prompt"] = negative_prompt
    return model_id, body


# --------------------------------------------------------------------------
# credentials, gates, cost
# --------------------------------------------------------------------------
def _credential(account_id: Optional[int] = None) -> Optional[str]:
    """This account's own stored fal key (BYOK) first, then FAL_KEY from
    the environment -- account_keys.key_for's whole job. One secret, not
    higgsfield's pair, so the tuple-of-tuples in PROVIDER_ENV_FALLBACK has
    exactly one field."""
    creds = account_keys.key_for(account_id, "fal")
    if creds:
        return creds.get("api_key")
    return None


def has_key(account_id: Optional[int] = None) -> bool:
    return _credential(account_id) is not None


def spend_approved(approved: Optional[bool] = None) -> bool:
    """Is this ONE call approved to spend?

    THE APPROVAL IS THE CLICK NOW (2026-09-09, Mike's call). It used to
    be FAL_SPEND_OK=1 in the process environment, set per run on the command
    and never in .env -- "an approval that's always on isn't an
    approval". That reasoning was right about what an approval IS and
    wrong about where this one lives: the person approving a render is
    standing at the Queue pressing a priced button, and making them
    restart the server with an environment variable to make that button
    work meant the variable ended up set for the whole session anyway --
    an approval that was always on, arrived at the long way round.

    So the approval became an ARGUMENT. `approved=True` is passed by the
    routes a human drives and by nothing else, which is what the env var
    was really standing in for. The check still lives inside
    generate_video, so no caller can spend around it.

    The environment variable still satisfies the gate when no caller
    says otherwise. That is deliberate and it is what keeps the
    unattended paths exactly as safe as they were: orchestrator.py and
    autopilot.py pass no approval, so a nightly run still needs
    FAL_SPEND_OK=1 set for it on purpose, on top of its own flags. Same for
    the CLI and the ops scripts.
    """
    if approved is not None:
        return bool(approved)
    return (os.environ.get(SPEND_ENV) or "").strip() == "1"


def price_per_second(model: str = DEFAULT_MODEL,
                     resolution: Optional[str] = None) -> float:
    spec = model_spec(model)
    prices = spec["prices"]
    return prices.get(resolution or spec["default_resolution"],
                      prices[spec["default_resolution"]])


def estimate_cost(n: int, *, model: str = DEFAULT_MODEL,
                  duration: int = DEFAULT_DURATION,
                  resolution: Optional[str] = None) -> float:
    """What n clips will cost, off the dated table above.

    Real per-second pricing, not higgsfield's estimate: fal publishes a
    rate card per model, so this is close to an invoice rather than a
    guess -- close, because the duration actually billed is the duration
    the model RETURNS, and a model asked for 5s that hands back 5.2s bills
    the 5.2. Rounded to the cent the way every other adapter's does.
    """
    seconds = min(max(int(duration), 1), model_spec(model)["durations"][1])
    return round(n * price_per_second(model, resolution) * seconds, 2)


def estimate_image_cost(n: int, *, megapixels: float = 1.0) -> float:
    """FLUX bills per megapixel, rounded UP to the next whole one, so a
    1024x1024 still is one megapixel and the default here is the real
    common case rather than a fractional fiction."""
    return round(n * COST_PER_IMAGE_USD * max(1, int(megapixels + 0.9999)), 4)


def _safe_error(e: Exception, account_id: Optional[int] = None) -> str:
    """The key must never reach a page, a log line, or a DB row.

    It takes the account because _credential() does, and that is the whole
    bug this signature exists to avoid: called with no account, this
    resolves the OPERATOR's FAL_KEY and redacts that, while a BYOK
    customer's own stored key -- the one the failing request was actually
    signed with -- passes straight through into an error string that
    reaches a Queue card and a generations row. runway, veo and higgsfield
    were all fixed for exactly this on 2026-09-07; this module was written
    with the fix rather than into it.

    Best effort on the lookup: redaction runs on the failure path and must
    never be the thing that raises there.
    """
    text = str(e)
    try:
        secret = _credential(account_id)
    except Exception:
        secret = None
    if secret:
        text = text.replace(secret, account_keys.redact("fal"))
    return re.sub(r"(Key\s+)[A-Za-z0-9_\-.:]+", r"\1<redacted>", text)


def safe_prompt(prompt: str, db_path=None) -> str:
    """Asset names swapped for their render aliases -- runway.py's table,
    reused rather than copied.

    The alias is a property of the ASSET, not of the vendor: "Cyclops"
    trips a third-party-content classifier wherever it is sent, and the
    keyframe was carrying the look anyway. Two lists would drift, and the
    drift would only surface as a refused render mid-run.
    """
    from .runway import render_aliases
    text = prompt or ""
    for name, alias in render_aliases(db_path).items():
        text = re.sub(r"(?<![\w])" + re.escape(name) + r"(?![\w])",
                      alias, text, flags=re.IGNORECASE)
    return text


def generations_today(db_path=None, *, account_id=None, everyone: bool = False,
                      operator_billed_only: bool = False) -> int:
    """This account's fal-rendered generations since UTC midnight -- what
    DAILY_CAP counts against. `everyone=True` gives the installation-wide
    count GLOBAL_DAILY_CAP counts against.

    Summed over VIDEO_LOG_TOOLS rather than read off one label, because a
    row records the PLATFORM that rendered it (kling / ltx / wan /
    seedance) and not the vendor that billed it. A cap that read tool
    "fal" would count zero forever while the money went out the door.
    """
    return sum(
        generative.used_today(tool, db_path, account_id=account_id, everyone=everyone,
                              operator_billed_only=operator_billed_only)
        for tool in VIDEO_LOG_TOOLS
    )


# --------------------------------------------------------------------------
# the wire
# --------------------------------------------------------------------------
def _request(url: str, payload: Optional[dict] = None, *,
             account_id: Optional[int] = None) -> dict:
    """One authenticated JSON round-trip. POST when there is a payload,
    else GET. Injected as `http` by every caller in tests, which is why
    nothing above this line needs a key to be exercised."""
    key = _credential(account_id)
    if key is None:
        raise RuntimeError("FAL_KEY not set (create one at fal.ai/dashboard/keys)")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Key {key}",
                 "Content-Type": "application/json",
                 "Accept": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode())


# fal's video payloads are documented as {"video": {"url": ...}}; image
# payloads as {"images": [{"url": ...}]}. Both are checked before the walk
# below, which exists only so a model with a slightly different output key
# does not cost a paid render.
OUTPUT_KEYS = ("video", "videos", "image", "images", "output", "outputs")


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
    """The finished asset's URL: documented keys first, then a walk of the
    whole payload. The walk skips the queue's own status/response/cancel
    URLs, which are the http strings every fal payload carries and which
    would otherwise "succeed" by downloading JSON."""
    if isinstance(payload, dict):
        for key in OUTPUT_KEYS:
            if key in payload:
                found = _first_url(payload[key], skip)
                if found:
                    return found
    return _first_url(payload, skip)


def _error_in(payload) -> Optional[str]:
    """fal's failure shape, and the reason this helper is called on BOTH
    the status poll and the result fetch.

    There is no FAILED status (docs, 2026-09-08) -- three states, all of
    them non-failure. A job that dies comes back COMPLETED carrying
    `error` (human readable) and `error_type` (machine readable), so the
    only way to notice is to look for the fields rather than to wait for a
    status that is never sent.
    """
    if not isinstance(payload, dict):
        return None
    error = payload.get("error") or payload.get("detail")
    if not error:
        return None
    kind = payload.get("error_type")
    text = error if isinstance(error, str) else json.dumps(error)
    return f"{kind}: {text}" if kind else text


def _download(url: str, out_path: Path) -> None:
    """fal's output URLs are hosted and expire; download the moment the
    job finishes and the repo keeps the file forever."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as response, open(out_path, "wb") as f:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def _submit_and_wait(model_id: str, body: dict, *, http=None,
                     timeout_s: Optional[int] = None,
                     account_id: Optional[int] = None) -> tuple[dict, set]:
    """Submit -> poll to COMPLETED -> fetch the result. Returns (result
    payload, queue URLs to skip). Raises on an error payload or the
    deadline.

    Three things here are load-bearing and none of them are obvious:

    1. The result is a SECOND request. fal's terminal status payload is a
       receipt, not the output -- the video lives behind `response_url`.
       (higgsfield's terminal payload carries the asset inline, which is
       why this is the one place the two adapters diverge.)
    2. An UNKNOWN status keeps waiting. fal documents three states, and
       the safe reading of a fourth is "a state we do not understand yet",
       not "done" -- treating it as done would fetch a result that is not
       there and report a missing-URL error for a job that was merely
       still running.
    3. The deadline is checked on every pass, so a job that never leaves
       IN_QUEUE raises instead of holding the night open forever. There is
       no failure status to rescue us here; the clock is the only wall.
    """
    # Read the module constant HERE rather than as a default argument: a
    # default binds at import, so TIMEOUT_SECONDS could never be changed
    # afterwards -- not by a test, and not by anything that reloads the
    # env. The deadline is the only wall this function has; it must be the
    # one actually in force.
    timeout_s = TIMEOUT_SECONDS if timeout_s is None else timeout_s
    http = http or (lambda u, p=None: _request(u, p, account_id=account_id))
    submitted = http(f"{HOST}/{model_id}", body)
    status_url = submitted.get("status_url")
    response_url = submitted.get("response_url")
    if not status_url or not response_url:
        raise RuntimeError(
            f"fal submit returned no status_url/response_url "
            f"(keys: {sorted(submitted)})")
    skip = {status_url, response_url, submitted.get("cancel_url")}
    failed = _error_in(submitted)
    if failed:
        raise RuntimeError(f"fal refused the job at submit: {failed}")

    deadline = time.time() + timeout_s
    while True:
        state = http(status_url)
        status = str(state.get("status") or "").upper()
        failed = _error_in(state)
        if failed:
            raise RuntimeError(f"fal job failed: {failed}")
        if status == STATUS_DONE:
            break
        if time.time() > deadline:
            raise RuntimeError(
                f"fal job still {status or 'pending'} after {timeout_s}s "
                f"(fal documents no failure status, so a stuck job can only "
                f"be caught by this deadline)")
        time.sleep(POLL_SECONDS)

    result = http(response_url)
    failed = _error_in(result)
    if failed:
        raise RuntimeError(f"fal job failed: {failed}")
    return result, skip


def generate_video(prompt: str, out_path, *, model: str = DEFAULT_MODEL,
                   image_url: Optional[str] = None,
                   duration: int = DEFAULT_DURATION,
                   aspect_ratio: str = DEFAULT_ASPECT,
                   resolution: Optional[str] = None,
                   negative_prompt: str = "",
                   http=None, db_path=None,
                   approved: Optional[bool] = None,
                   account_id: Optional[int] = None) -> Path:
    """
    The thin wrapper: submit -> poll -> fetch -> download. Raises on
    anything, including a missing spend approval, which is checked HERE so
    no caller can spend around the gate.
    """
    if not spend_approved(approved):
        raise RuntimeError(
            f"spend not approved: this call was not approved by a person. "
            f"Approve it at the Queue, or set {SPEND_ENV}=1 for an unattended run "
            f"(~${estimate_cost(1, model=model, duration=duration, resolution=resolution)} "
            f"at fal, {model}). There is no free app to fall back to here."
        )
    # Name-swap first, THEN build the body: what we check has to be what
    # we send.
    prompt = safe_prompt(prompt, db_path)
    model_id, body = build_body(prompt, model=model, image_url=image_url,
                                duration=duration, aspect_ratio=aspect_ratio,
                                resolution=resolution,
                                negative_prompt=negative_prompt)
    result, skip = _submit_and_wait(model_id, body, http=http, account_id=account_id)
    url = _output_url(result, skip)
    if not url:
        raise RuntimeError(
            f"fal job completed but no output URL was found in the result "
            f"(keys: {sorted(result) if isinstance(result, dict) else type(result)})")
    out_path = Path(out_path)
    _download(url, out_path)
    return out_path


def generate_image(prompt: str, out_path, *, model: str = DEFAULT_IMAGE_MODEL,
                   width: int = 1024, height: int = 1024,
                   http=None, db_path=None,
                   approved: Optional[bool] = None,
                   account_id: Optional[int] = None) -> Path:
    """A FLUX still, same queue and same walls. Separate from the video
    path on purpose -- it shares the transport, not the contract."""
    spec = IMAGE_MODELS.get(model)
    if spec is None:
        raise ValueError(f"image model must be one of {IMAGE_MODEL_NAMES}, got {model!r}")
    if not spend_approved(approved):
        raise RuntimeError(
            f"spend not approved: this call was not approved by a person. "
            f"Approve it at the Queue, or set {SPEND_ENV}=1 for an unattended run "
            f"(~${estimate_image_cost(1)} at fal, {model})")
    prompt = safe_prompt(prompt, db_path)
    body = {"prompt": prompt}
    if "width" in spec["params"]:
        body["width"], body["height"] = int(width), int(height)
    result, skip = _submit_and_wait(spec["endpoint"], body, http=http,
                                    account_id=account_id)
    url = _output_url(result, skip)
    if not url:
        raise RuntimeError("fal image job completed but carried no image URL")
    out_path = Path(out_path)
    _download(url, out_path)
    return out_path


def as_image_url(value, *, resolve_photo=None) -> Optional[str]:
    """Anything stored as a reference -> a URL fal's servers can actually
    FETCH, or None.

    Delegated to higgsfield.as_image_url because the requirement is
    identical and so is the failure it guards: fal's image-to-video
    endpoints take an `image_url` their servers fetch, so a local keyframe
    has to be uploaded somewhere public first, and without storage
    configured the reference is DROPPED and the caller records
    prompt_image=False. A silently dropped anchor while the Queue card
    claims one is runway's old bug, and it is not being repeated with a
    third vendor -- or with a fourth copy of the code.
    """
    from . import higgsfield
    return higgsfield.as_image_url(value, resolve_photo=resolve_photo)


# --------------------------------------------------------------------------
# the never-raises edges
# --------------------------------------------------------------------------
def _shot_row_for_prompt(prompt: str, db_path, note: str,
                         account_id: Optional[int] = None) -> int:
    """A generations row needs a shot to hang off. The graph's AI shots do
    not have one, so synthesize a minimal Shot -- the row exists to make
    the attempt countable, and its notes say where it came from."""
    kwargs = {"dsn": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="as prompted")
    return generative.add_shot(shot, notes=note, **kwargs, account_id=account_id)


def _cap_refusal(n: int, db_path, account_id):
    return generative.cap_error(
        "fal", n, account_id=account_id,
        per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
        dsn=db_path,
        env_prefix="FAL", phrase="generations used",
        used=generations_today(db_path=db_path, account_id=account_id),
        used_everywhere=generations_today(db_path=db_path, everyone=True,
                                             operator_billed_only=True),
    )


def generate_candidates(prompt: str, out_dir, n: int = 3, *,
                        shot_id: Optional[int] = None, db_path=None,
                        model: str = DEFAULT_MODEL, http=None,
                        approved: Optional[bool] = None,
                        account_id: Optional[int] = None, **cfg) -> dict:
    """
    Never raises. The interface orchestrator.generate_render calls --
    identical in signature and result shape to runway/veo/higgsfield's,
    which is the whole point: four dormant platforms come online through
    four bindings of this one function.

    {"ok", "candidates": [{path, generation_id, model}], "shot_id",
    "error"} -- a missing approval, a missing key, a failed job or the
    daily cap is a result the caller can show, not an exception that takes
    the night down. Partial success is success.

    The generations row is logged under the PLATFORM (kling / ltx / wan /
    seedance), not under "fal": the scoreboard question is "which tool
    makes clips worth keeping", and the answer "fal" would collapse four
    genuinely different models into one row while making
    tool_scoreboard's cost_per_keeper an average of things that cost
    $0.30 and $1.51.
    """
    n = int(os.environ.get("FAL_CANDIDATES", n))
    kwargs = {"dsn": db_path} if db_path is not None else {}
    duration = int(cfg.get("duration", DEFAULT_DURATION))

    try:
        if model not in VIDEO_MODELS:
            return {"ok": False, "candidates": [],
                    "error": f"unknown fal model {model!r} (FAL_MODEL); "
                             f"known: {', '.join(MODELS)}"}
        if not has_key(account_id):
            return {"ok": False, "candidates": [],
                    "error": "fal not configured — FAL_KEY is unset"}
        if not spend_approved(approved):
            return {"ok": False, "candidates": [],
                    "error": f"spend not approved: set {SPEND_ENV}=1 to approve "
                             f"~${estimate_cost(n, model=model, duration=duration)} "
                             f"at fal for this run"}

        generative.init(**kwargs)
        refusal = _cap_refusal(n, db_path, account_id)
        if refusal:
            return {"ok": False, "candidates": [], "error": refusal}

        if shot_id is None:
            shot_id = _shot_row_for_prompt(
                prompt, db_path, "auto-created by fal.generate_candidates",
                account_id)

        tool = model_spec(model)["platform"]
        out_dir = Path(out_dir)
        candidates, errors = [], []
        for i in range(1, n + 1):
            out_path = out_dir / f"cand{i}.mp4"
            try:
                generate_video(prompt, out_path, model=model, http=http,
                               db_path=db_path, approved=approved,
                               account_id=account_id, **cfg)
            except Exception as e:
                errors.append(f"candidate {i}: {_safe_error(e, account_id)}")
                continue
            generation_id = generative.record_generation(
                shot_id, tool, prompt,
                params={"provider": "fal", "model": model,
                        "model_id": model_spec(model)["t2v"],
                        "key_source": account_keys.key_source(
                            account_id, "fal", db_path),
                        **cfg},
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
        return {"ok": False, "candidates": [], "error": _safe_error(e, account_id)}


def _publish(out_path: Path, content_type: str) -> str:
    """R2 when configured (Instagram needs a public URL), else the app's
    own /renders mount."""
    from . import storage
    if storage.configured():
        return storage.upload_file(
            out_path, key=f"renders/fal/{out_path.name}",
            content_type=content_type)
    return f"/renders/fal/{out_path.name}"


def generate_for_shot(concept_id: int, shot_n, *, db_path=None,
                      model: str = DEFAULT_MODEL,
                      duration: int = DEFAULT_DURATION,
                      resolution: Optional[str] = None,
                      resolve_photo=None, http=None,
                      approved: Optional[bool] = None,
                      account_id: Optional[int] = None,
                      part: Optional[int] = None,
) -> dict:
    """
    `part` (2026-09-10) renders ONE shot of a timed scene -- its composed
    prompt, anchored on its own still, attached to that part (see
    src/timeline.py). None is the whole scene, exactly as before.

    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    One render for one concept shot -- runway.generate_for_shot's contract
    on this vendor, so the Queue's approve can dispatch to either without
    caring which. Every wall this module already has still applies: the
    spend gate lives inside generate_video so this layer cannot spend
    around it, the cap is checked before any call, and the attempt is a
    generations row either way the pick later goes.

    THE ROW IS LOGGED UNDER THE PLATFORM, never under "fal" -- the tool
    scoreboard asks which model makes keepable clips, and one "fal" row
    would average a $0.30 LTX clip with a $1.51 Seedance one. That is the
    module's standing rule (see VIDEO_LOG_TOOLS); this caller is not an
    exception to it.

    `duration` and `resolution` are the operator's, passed through to
    build_body, which clamps duration into the model's own range. The
    Queue refuses out-of-range values before it gets here
    (providers.check_render_choice) precisely because there is a human
    to refuse TO; the clamp stays for the graph, which has none.
    """
    from . import preprod, render_assets
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        generative.init(**kwargs)
        refusal = _cap_refusal(1, db_path, account_id)
        if refusal:
            return {"ok": False, "error": refusal}

        concept = preprod.get_concept(concept_id, **kwargs, account_id=account_id)
        if concept is None:
            return {"ok": False, "error": f"no concept {concept_id}"}
        shot = next((s for s in concept.get("shots") or []
                     if s.get("n") == shot_n), None)
        if shot is None:
            return {"ok": False, "error": f"concept {concept_id} has no shot {shot_n}"}
        from . import timeline
        target = timeline.render_target(shot, part)
        if target is None:
            return {"ok": False, "error": f"shot {shot_n} has no part {part}"}
        prompt = target["prompt"]
        if not prompt:
            return {"ok": False,
                    "error": f"shot {shot_n} has no AI prompt to render from"}

        # as_image_url, not runway's as_prompt_image: fal fetches an
        # image_url server-side, so a local keyframe with no R2 behind it
        # is dropped and prompt_image records False -- nothing downstream
        # gets to claim an anchor that never left the building.
        image_url = as_image_url(target["reference_image"],
                                 resolve_photo=resolve_photo)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"c{concept_id}-s{shot_n}{f'-p{part}' if part else ''}-{stamp}.mp4"
        generate_video(prompt, out_path, model=model, image_url=image_url,
                       duration=duration, resolution=resolution,
                       http=http, db_path=db_path, approved=approved,
                       account_id=account_id)

        platform = model_spec(model)["platform"]
        shot_row_id = _shot_row_for_prompt(
            prompt, db_path, "auto-created by fal.generate_for_shot", account_id)
        generation_params = {"provider": "fal", "model": model,
                             "duration": duration,
                             "resolution": resolution or model_spec(model)["default_resolution"],
                             "concept_id": concept_id, "shot_n": shot_n,
                             **({"part": part} if part else {}),
                             "prompt_image": bool(image_url),
                             "key_source": account_keys.key_source(
                                 account_id, "fal", db_path)}
        generation_id = generative.record_generation(
            shot_row_id, platform, prompt,
            params=generation_params,
            output_path=str(out_path),
            cost_usd=estimate_cost(1, model=model, duration=duration,
                                   resolution=resolution),
            **kwargs,
            account_id=account_id)

        media_url = _publish(out_path, "video/mp4")
        if part:
            timeline.attach_part(concept_id, shot_n, part, "media_url", media_url,
                                 db_path=db_path, account_id=account_id)
        else:
            preprod.set_shot_media_url(concept_id, shot_n, media_url,
                                       **kwargs, account_id=account_id)
        asset = render_assets.record_best_effort(
            account_id=account_id,
            generation_id=generation_id, tool=platform, model=model,
            media_kind="video", prompt=prompt, media_url=media_url,
            output_path=str(out_path), project=concept.get("brand"),
            concept_id=concept_id, shot_n=shot_n,
            metadata=generation_params,
            dsn=db_path,
        )
        return {"ok": True, "media_url": media_url,
                "generation_id": generation_id, "path": str(out_path),
                "asset_id": asset["id"], "asset_rag": asset["rag"],
                "error": None}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, account_id)}


def generate_from_prompt(prompt: str, *, reference_image=None, db_path=None,
                         model: str = DEFAULT_MODEL, resolve_photo=None,
                         http=None, approved: Optional[bool] = None,
                         account_id: Optional[int] = None) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    The free-standing render behind the Workflows canvas's Generate node,
    higgsfield.generate_from_prompt's twin.
    """
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "an empty prompt renders nothing"}

        # a fresh DB has no generations table until something inits it;
        # the cap count must not be the thing that discovers that
        generative.init(**kwargs)
        refusal = _cap_refusal(1, db_path, account_id)
        if refusal:
            return {"ok": False, "error": refusal}

        image_url = as_image_url(reference_image, resolve_photo=resolve_photo)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"wf-{stamp}.mp4"
        generate_video(prompt, out_path, model=model, image_url=image_url,
                       http=http, db_path=db_path, approved=approved,
                       account_id=account_id)

        shot_row_id = _shot_row_for_prompt(
            prompt, db_path, "auto-created by fal.generate_from_prompt", account_id)
        generation_id = generative.record_generation(
            shot_row_id, model_spec(model)["platform"], prompt,
            params={"provider": "fal", "model": model,
                    "duration": DEFAULT_DURATION, "source": "workflow",
                    "prompt_image": bool(image_url),
                    "key_source": account_keys.key_source(
                        account_id, "fal", db_path)},
            output_path=str(out_path),
            cost_usd=estimate_cost(1, model=model),
            **kwargs,
            account_id=account_id)
        return {"ok": True, "media_url": _publish(out_path, "video/mp4"),
                "generation_id": generation_id, "path": str(out_path),
                "error": None}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, account_id)}


def generate_image_from_prompt(prompt: str, *, db_path=None, http=None,
                               model: str = DEFAULT_IMAGE_MODEL,
                               approved: Optional[bool] = None,
                               account_id: Optional[int] = None) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    A FLUX still -- the keyframe alternative to nano_banana, on the same
    key and the same gates as the clips. Logged under IMAGE_LOG_TOOL so it
    never lands in the video scoreboards or moves the video cap.
    """
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "an empty prompt renders nothing"}

        generative.init(**kwargs)
        # Images are counted on their own tool name, so the wall they hit
        # is the image count -- a still must not eat a clip's budget.
        refusal = generative.cap_error(
            IMAGE_LOG_TOOL, 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            dsn=db_path, env_prefix="FAL", phrase="images generated",
        )
        if refusal:
            return {"ok": False, "error": refusal}

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"flux-{stamp}.jpg"
        generate_image(prompt, out_path, model=model, http=http,
                       db_path=db_path, approved=approved, account_id=account_id)

        shot_row_id = _shot_row_for_prompt(
            prompt, db_path, "auto-created by fal.generate_image_from_prompt",
            account_id)
        generation_id = generative.record_generation(
            shot_row_id, IMAGE_LOG_TOOL, prompt,
            params={"provider": "fal", "model": model, "source": "workflow",
                    "key_source": account_keys.key_source(
                        account_id, "fal", db_path)},
            output_path=str(out_path),
            cost_usd=estimate_image_cost(1),
            **kwargs,
            account_id=account_id)
        return {"ok": True, "media_url": _publish(out_path, "image/jpeg"),
                "generation_id": generation_id, "path": str(out_path),
                "error": None}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, account_id)}


# --------------------------------------------------------------------------
# one module, many platforms
# --------------------------------------------------------------------------
class _PlatformConnector:
    """This module, bound to ONE shot.PLATFORMS name and its model.

    orchestrator.generate_render looks a connector up by uppercase tool
    name and calls generate_candidates(prompt, out_dir, n=, db_path=,
    account_id=) on it. The three existing connectors are modules because
    each is one vendor with one model family; fal is one vendor behind
    FOUR platform names, and four registry entries would have made it look
    like four vendors -- so it stays a single entry in
    providers.VIDEO_PROVIDERS and this is the binding the orchestrator
    holds instead.

    It carries the full REQUIRED shape, not just generate_candidates, so a
    router handed one of these behaves exactly as it does with a module.
    PROVIDER says which entry in VIDEO_PROVIDERS this really is, so
    generate_render's failover can exclude fal itself after a fal failure
    rather than "retrying" on the same vendor that just failed.
    """

    PROVIDER = "fal"

    def __init__(self, platform: str):
        self.platform = platform
        self.model = model_for_platform(platform)

    def __repr__(self) -> str:                      # pragma: no cover - debug aid
        return f"<fal connector {self.platform} -> {self.model}>"

    def generate_video(self, prompt, out_path, **kw):
        kw.setdefault("model", self.model)
        return generate_video(prompt, out_path, **kw)

    def generate_candidates(self, prompt, out_dir, n: int = 3, **kw):
        kw.setdefault("model", self.model)
        return generate_candidates(prompt, out_dir, n, **kw)

    def generate_for_shot(self, concept_id, shot_n, **kw):
        # part of the providers.REQUIRED contract since 2026-09-08, and a
        # binding that did not carry it would be a router's "module"
        # missing the one function the spend gate calls
        kw.setdefault("model", self.model)
        return generate_for_shot(concept_id, shot_n, **kw)

    def estimate_cost(self, n: int, **kw):
        kw.setdefault("model", self.model)
        return estimate_cost(n, **kw)

    def spend_approved(self, approved: Optional[bool] = None):
        return spend_approved(approved)

    def has_key(self, account_id: Optional[int] = None):
        return has_key(account_id)

    def generations_today(self, db_path=None, **kw):
        return generations_today(db_path, **kw)


def connector(platform: str) -> _PlatformConnector:
    """The binding orchestrator.generate_render's connectors dict holds
    for KLING / LTX / WAN / SEEDANCE."""
    return _PlatformConnector(platform)

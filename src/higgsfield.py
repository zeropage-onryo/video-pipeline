#!/usr/bin/env python3
"""
The Higgsfield connector -- STILLS ONLY since 2026-09-26.

fal became the only video renderer that day (Mike's call, docs/tasks/
task-fal-only.md), and this module's video path -- generate_video,
generate_candidates, generate_for_shot, generate_from_prompt, the
VIDEO_MODELS table -- went with Runway and Veo. What stays is the Soul
image path, which the video decision did not touch:

- generate_image                -- the thin wrapper. Submit, poll the
                                   status_url, download. Raises.
- generate_image_from_prompt    -- a Soul still (the scene chain's visual
                                   targets, the image post), never raises.

Refgen (src/refgen.py) and scene_chain's visual targets call these.

THE SPEND GATE lives here, not in callers: generate_image refuses unless
the caller passes approved=True or HIGGSFIELD_SPEND_OK=1 is set for an
unattended run. DAILY_CAP (HIGGSFIELD_DAILY_CAP, default 6) is counted
from the generations table under tool "higgsfield".

API contract verified against docs.higgsfield.ai 2026-08-31:
- Host:   https://api.higgsfield.ai
- Auth:   Authorization: Key <key_id>:<key_secret>
- Submit: POST <host><model path>, JSON body
          -> {"status": "queued", "request_id", "status_url", "cancel_url"}
- Poll:   GET status_url until terminal (completed / failed / nsfw /
          canceled).
- Output: the completed payload carries the result inline,
          {"images": [{"url": ...}]}.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import charge as charging
from . import generative, ledger
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
# 0 = no installation-wide ceiling (2026-09-14, Mike's call): a user who
# brought their own key was still consuming the operator's shared budget and
# could lock everyone else out of money nobody spent. The per-account cap
# (HIGGSFIELD_DAILY_CAP) is the wall that remains. Set HIGGSFIELD_GLOBAL_DAILY_CAP to a
# positive number to put the ceiling back -- see generative.cap_error.
GLOBAL_DAILY_CAP = int(os.environ.get("HIGGSFIELD_GLOBAL_DAILY_CAP", "0"))
POLL_SECONDS = 3
# The shipped default and the fallback `timeout_seconds()` reads when the
# environment says nothing. Bound at import like every other constant
# here -- what must NOT be bound at import is the value the poll loop
# actually uses; see timeout_seconds().
TIMEOUT_SECONDS = int(os.environ.get("HIGGSFIELD_TIMEOUT_S", "600"))


def timeout_seconds() -> int:
    """How long a poll loop may wait, resolved PER CALL.

    `_submit_and_wait` used to carry `timeout_s: int = TIMEOUT_SECONDS`,
    and a default argument binds at import: once this module was
    imported, `HIGGSFIELD_TIMEOUT_S` could never be changed again.
    Setting it in the environment afterwards did nothing, and a test
    that patched the constant patched a name the function no longer
    read -- so the failure mode was a poll loop hanging for the OLD
    timeout while the operator believed they had shortened it, with
    nothing anywhere saying otherwise. `src/fal.py::_submit_and_wait`
    was written against that trap (it reads its constant inside the
    function); this is the same fix with the environment read live as
    well, so `settings.py`'s rule -- env beats the shipped default,
    resolved when it is needed rather than when the process started --
    holds for the one number that decides how long money can sit in
    flight.

    A junk value falls back to the constant rather than raising: this is
    a deadline, and refusing to render because someone typed
    `HIGGSFIELD_TIMEOUT_S=soon` would be a worse answer than using 600.
    """
    raw = os.environ.get("HIGGSFIELD_TIMEOUT_S")
    if raw is None:
        return int(TIMEOUT_SECONDS)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(TIMEOUT_SECONDS)

# Not published on the docs (checked 2026-08-31) -- an estimate, not a
# promise. Override once a real invoice is known.
COST_PER_IMAGE_USD = float(os.environ.get("HIGGSFIELD_IMAGE_COST_USD", "0.05"))

DONE_STATUSES = {"completed", "succeeded", "success", "done"}
FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "nsfw", "rejected"}

RENDER_DIR = Path(__file__).resolve().parent.parent / "data" / "renders" / "higgsfield"
RENDERS_ROOT = Path(__file__).resolve().parent.parent / "data" / "renders"


# The platform vertical, shot.HOUSE_ASPECT.
DEFAULT_ASPECT = "9:16"


# --------------------------------------------------------------------------
# credentials, gates, cost
# --------------------------------------------------------------------------
def _credentials(account_id: Optional[int] = None) -> Optional[tuple[str, str]]:
    """Key id + secret from the environment: HIGGSFIELD_* first, the docs'
    own HF_* names as a fallback (HF_ collides with Hugging Face
    conventions, so it is not what .env.example teaches). The operator's
    credential only -- per-account keys were removed on 2026-09-26."""
    key_id = os.environ.get("HIGGSFIELD_API_KEY_ID") or os.environ.get("HF_API_KEY_ID")
    secret = (os.environ.get("HIGGSFIELD_API_KEY_SECRET")
              or os.environ.get("HF_API_KEY_SECRET"))
    return (key_id, secret) if key_id and secret else None


def has_key(account_id: Optional[int] = None) -> bool:
    return _credentials(account_id) is not None


def spend_approved(approved: Optional[bool] = None, quote=None) -> bool:
    """Is this ONE call approved to spend?

    THE APPROVAL IS THE CLICK NOW (2026-09-09, Mike's call). It used to
    be HIGGSFIELD_SPEND_OK=1 in the process environment, set per run on the command
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
    generate_image, so no caller can spend around it.

    The environment variable still satisfies the gate when no caller
    says otherwise. That is deliberate and it is what keeps the
    unattended paths exactly as safe as they were: orchestrator.py and
    autopilot.py pass no approval, so a nightly run still needs
    HIGGSFIELD_SPEND_OK=1 set for it on purpose, on top of its own flags. Same for
    the CLI and the ops scripts.
    """
    # A Quote for another renderer is refused whatever else was said --
    # it is a price for a different render. (No still is quoted today.)
    if quote is not None and getattr(quote, "provider", None) != "higgsfield":
        return False
    if approved is not None:
        return bool(approved)
    if quote is not None:
        return True
    return (os.environ.get(SPEND_ENV) or "").strip() == "1"


def estimate_image_cost(n: int) -> float:
    return round(n * COST_PER_IMAGE_USD, 2)


def _safe_error(e: Exception, account_id: Optional[int] = None) -> str:
    """Neither credential may reach a page, a log line, or a DB row. Best
    effort on the lookup: redaction runs on the failure path and must
    never be the thing that raises there."""
    text = str(e)
    try:
        creds = _credentials(account_id)
    except Exception:
        creds = None
    if creds:
        for secret in creds:
            if secret:
                text = text.replace(secret, "<HIGGSFIELD_CREDENTIAL>")
    return re.sub(r"(Key\s+)[A-Za-z0-9_\-.:]+", r"\1<redacted>", text)


def safe_prompt(prompt: str, db_path=None, account_id: Optional[int] = None) -> str:
    """Asset names swapped for their render aliases (entities.render_aliases,
    the one table every renderer sanitises against)."""
    from .entities import render_aliases
    text = prompt or ""
    for name, alias in render_aliases(db_path, account_id=account_id).items():
        text = re.sub(r"(?<![\w])" + re.escape(name) + r"(?![\w])",
                      alias, text, flags=re.IGNORECASE)
    return text


def generations_today(db_path=None, *, account_id=None, everyone: bool = False,
                      operator_billed_only: bool = False) -> int:
    """This account's higgsfield generations since UTC midnight -- what
    DAILY_CAP counts against. `everyone=True` gives the installation-wide
    count that GLOBAL_DAILY_CAP counts against."""
    return generative.used_today(
        "higgsfield", db_path,
        account_id=account_id, everyone=everyone,
        operator_billed_only=operator_billed_only,
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


def _request(url: str, payload: Optional[dict] = None, *,
             account_id: Optional[int] = None) -> dict:
    """One authenticated JSON round-trip. POST when there is a payload,
    else GET. Injected as `http` in tests so nothing here needs a key."""
    creds = _credentials(account_id)
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
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        # urllib's message is only "HTTP Error 423: Locked"; the reason
        # (model_blocked, model_not_found, a credit error) is in the body.
        # Attach it so the Queue card says WHY, not just the status line.
        try:
            detail = e.read().decode(errors="replace")[:300].strip()
        except Exception:
            detail = ""
        if detail:
            raise RuntimeError(f"HTTP Error {e.code}: {e.reason} -- {detail}") from e
        raise


# The documented image shape is {"images": [{"url": ...}]}, checked first;
# the rest are the fallback walk's order.
OUTPUT_KEYS = ("images", "image", "output", "outputs", "result")


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
                     timeout_s: Optional[int] = None,
                     account_id: Optional[int] = None) -> tuple[dict, set]:
    """Submit -> poll to a terminal state -> (final payload, control
    URLs to skip). Raises on failure or timeout.

    The deadline is resolved HERE, through `timeout_seconds()`, and not
    as a default argument: a default binds at import, so the value would
    be whatever `HIGGSFIELD_TIMEOUT_S` said the first time anything
    imported this module and nothing could change it afterwards. This is
    the only wall between a stuck job and a night held open; it has to
    be the one actually in force. fal.py's `_submit_and_wait` carries
    the same shape and the same comment.
    """
    timeout_s = timeout_seconds() if timeout_s is None else int(timeout_s)
    http = http or (lambda u, p=None: _request(u, p, account_id=account_id))
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


def generate_image(prompt: str, out_path, *, http=None, db_path=None,
                   aspect_ratio: str = DEFAULT_ASPECT,
                   approved: Optional[bool] = None,
                   account_id: Optional[int] = None,
                   soul_id: Optional[str] = None) -> Path:
    """A Soul still, same wall. The documented completed payload is
    {"images": [{"url": ...}]} (docs.higgsfield.ai quickstart,
    2026-08-31)."""
    if not spend_approved(approved):
        raise RuntimeError(
            f"credit spend not approved: this call was not approved by a person. "
            f"Generate it in the Higgsfield app instead, or set {SPEND_ENV}=1 for "
            f"an unattended run (~${estimate_image_cost(1)} of API credits)"
        )
    prompt = safe_prompt(prompt, db_path, account_id)
    body = {"prompt": prompt, "aspect_ratio": aspect_ratio}
    if soul_id is None:
        soul_id = os.environ.get("HIGGSFIELD_SOUL_ID", "").strip()
    if soul_id:
        # NOT THE LIKENESS PATH ANY MORE (2026-09-06, Mike's call after
        # seeing the renders): the trained Soul "Mike Antihero v2" on Soul
        # Cinema / Soul V2 produced a different actor -- thick mustache,
        # pompadour. His face comes from nano_banana with his real photos
        # attached (refgen.identity_references); HIGGSFIELD_SOUL_ID is
        # left unset in .env so this branch is opt-in for someone else's
        # Soul, never his default. Field names are the JS SDK's for
        # /v1/text2image/soul (custom_reference_id,
        # custom_reference_strength); verify against SOUL_PATH on the first
        # live call -- an unknown field is a 400, not a silent drop.
        body["custom_reference_id"] = soul_id
        body["custom_reference_strength"] = float(
            os.environ.get("HIGGSFIELD_SOUL_STRENGTH", "1.0"))
    state, skip = _submit_and_wait(SOUL_PATH, body, http=http,
                                   account_id=account_id)
    url = _output_url(state, skip)
    if not url:
        raise RuntimeError(
            f"Higgsfield Soul job finished but no image URL was found "
            f"(keys: {sorted(state)})")
    out_path = Path(out_path)
    _download(url, out_path)
    return out_path


# --------------------------------------------------------------------------
# the never-raises edges
# --------------------------------------------------------------------------
def _shot_row_for_prompt(prompt: str, db_path, note: str, account_id: Optional[int] = None) -> int:
    """A generations row needs a shot to hang off. The graph's AI shots
    do not have one, so synthesize a minimal Shot -- the row exists to
    make the attempt countable, and its notes say where it came from."""
    kwargs = {"dsn": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="as prompted")
    return generative.add_shot(shot, notes=note, **kwargs, account_id=account_id)


def _publish(out_path: Path, content_type: str,
             account_id: Optional[int] = None) -> str:
    """R2 when configured (Instagram needs a public URL), else the app's
    own /renders mount. The key carries the tenant -- see src/media.py."""
    from . import media, storage
    if storage.configured():
        return storage.upload_file(
            out_path,
            key=media.object_key(f"renders/higgsfield/{out_path.name}", account_id),
            content_type=content_type)
    return f"/renders/higgsfield/{out_path.name}"


def generate_image_from_prompt(prompt: str, *, db_path=None, http=None, account_id: Optional[int] = None) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    A Soul still -- the keyframe alternative to nano_banana and the
    image-post path. Same walls; the image lands on R2 when configured
    (Instagram needs a public URL) else the app's /renders mount.
    """
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "an empty prompt renders nothing"}

        generative.init(**kwargs)
        refusal = generative.cap_error(
            "higgsfield", 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            dsn=db_path,
            env_prefix="HIGGSFIELD", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True,
                                             operator_billed_only=True),
        )
        if refusal:
            return {"ok": False, "error": refusal}

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"soul-{stamp}.jpg"
        generate_image(prompt, out_path, http=http, db_path=db_path,
                       account_id=account_id)

        shot_row_id = _shot_row_for_prompt(
            prompt, db_path, "auto-created by higgsfield.generate_image_from_prompt",
            account_id)
        generation_id = generative.record_generation(
            shot_row_id, "higgsfield", prompt,
            params={"model": "soul-standard", "source": "workflow",
                    "key_source": "env"},
            output_path=str(out_path),
            cost_usd=estimate_image_cost(1),
            **kwargs,
         account_id=account_id)
        return {"ok": True, "media_url": _publish(out_path, "image/jpeg", account_id),
                "generation_id": generation_id, "path": str(out_path),
                "error": None}
    except ledger.InsufficientCredit as e:
        return {"ok": False, "error": charging.refusal(e)}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, account_id)}

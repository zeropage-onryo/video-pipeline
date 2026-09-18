#!/usr/bin/env python3
"""
The Veo connector: prompt -> video -> pipeline. Same SDK and key as
every other stage (google-genai + GEMINI_API_KEY), no new secret.

Two layers, youtube.py's shape:
- generate_video      -- the thin wrapper. Submit, poll the long-running
                         operation, download to out_path. Raises on
                         failure or timeout; its caller catches.
- generate_candidates -- the never-raises edge you actually use:
                         N candidate clips for one prompt, every attempt
                         logged through generative.record_generation
                         (the genlog data attempts_to_keeper and the
                         tool scoreboard read), files under
                         footage/generated/. Nothing is ever
                         auto-selected: keeping a candidate is a human
                         action through genlog, because the pick is the
                         label.

EVERY CALL COSTS REAL MONEY. Three guardrails live here, not in callers:
- THE APPROVAL IS THE CLICK (2026-09-09, Mike's call). generate_video
  refuses unless the caller passes approved=True, which the routes a
  person drives do and nothing else does. VEO_SPEND_OK=1 still satisfies
  the gate when no caller says otherwise -- that is what keeps the
  unattended paths (orchestrator, autopilot, the CLI) needing a
  deliberate arming of their own. See spend_approved().
  This is the most expensive tool in the repo -- estimate_cost(6) is
  $19.20 -- so DAILY_CAP below matters more here than anywhere else.
- DAILY_CAP: a hard per-UTC-day cap on generations (default 6,
  VEO_DAILY_CAP to change) counted from the generations table, so a
  runaway loop hits a wall the DB enforces.
- estimate_cost(): surfaced in every dry-run preview so "N candidates"
  reads as dollars before anyone approves.

Model ids + config verified against Google's Veo docs 2026-08 (see
task-veo-generate.md's sources): veo-3.1-generate-preview is current,
veo-3 / veo-3-fast stable; aspect_ratio 16:9|9:16, resolution
720p|1080p|4k (1080p/4k force 8s), duration 4|6|8. Files live on
Google's server ~2 days, so download immediately. Re-verify before a
live run -- Google versions these.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from . import account_keys, generative, ledger
from . import charge as charging
from .shot import Shot

MODELS = ("veo-3.1-generate-preview", "veo-3", "veo-3-fast")
DEFAULT_MODEL = os.environ.get("VEO_MODEL", "veo-3-fast")   # cheapest first spend
DEFAULT_RESOLUTION = os.environ.get("VEO_RESOLUTION", "720p")
# The length generate_video asks for when nobody says otherwise.
# A CONSTANT rather than a literal in the signature because
# providers.render_options offers it to the Queue card as the one
# duration verified against the installed SDK -- two copies of that
# number is how a card comes to offer a length the adapter refuses.
DEFAULT_DURATION = 8
DAILY_CAP = int(os.environ.get("VEO_DAILY_CAP", "6"))
# The installation-wide wall, beside the per-account one. Defaults to the
# SAME number, so a single-operator database behaves exactly as it did --
# admitting a second account is what forces a deliberate decision about
# whose card is paying, instead of the total quietly doubling.
GLOBAL_DAILY_CAP = int(os.environ.get("VEO_GLOBAL_DAILY_CAP", str(DAILY_CAP)))

SPEND_ENV = "VEO_SPEND_OK"

# Rough per-clip estimate for the previews (8s, 720p, audio included),
# from Veo API pricing pages 2026-08. An estimate for a confirm dialog,
# not an invoice -- verify against Google's pricing before live spend.
COST_PER_CLIP_USD = 3.20

# Where a clip lands, and the root anything site-relative resolves
# against. Both are the runway.py shape, because app/main.py mounts
# data/renders once and serves every vendor's folder out of it.
RENDERS_ROOT = Path(__file__).resolve().parent.parent / "data" / "renders"
RENDER_DIR = RENDERS_ROOT / "veo"


def _safe_error(e: Exception, account_id: Optional[int] = None) -> str:
    """The key must never reach a page, a log line, or a DB row -- and
    since BYOK that includes the account's OWN stored key, which is
    never in this process's environment and so was never being redacted
    (runway._safe_error had the same hole). Best-effort on the account
    lookup: this runs on the failure path and must not raise there."""
    text = str(e)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(name)
        if value:
            text = text.replace(value, f"<{name}>")
    try:
        creds = account_keys.key_for(account_id, "veo")
    except Exception:
        creds = None
    if creds and creds.get("api_key"):
        text = text.replace(creds["api_key"], "<GEMINI_API_KEY>")
    return re.sub(r"key=[A-Za-z0-9_\-]+", "key=<redacted>", text)


def spend_approved(approved: Optional[bool] = None) -> bool:
    """Is this ONE call approved to spend?

    THE APPROVAL IS THE CLICK NOW (2026-09-09, Mike's call). It used to
    be VEO_SPEND_OK=1 in the process environment, set per run on the command
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
    VEO_SPEND_OK=1 set for it on purpose, on top of its own flags. Same for
    the CLI and the ops scripts.
    """
    if approved is not None:
        return bool(approved)
    return (os.environ.get(SPEND_ENV) or "").strip() == "1"


def estimate_cost(n: int) -> float:
    return round(n * COST_PER_CLIP_USD, 2)


def generations_today(db_path=None, *, account_id=None, everyone: bool = False) -> int:
    """This account's veo generations since UTC midnight -- what
    DAILY_CAP counts against. `everyone=True` gives the installation-wide
    count that GLOBAL_DAILY_CAP counts against."""
    return generative.used_today(
        "veo", db_path,
        account_id=account_id, everyone=everyone,
    )


def _make_client(account_id: Optional[int] = None) -> genai.Client:
    """
    account_id's own stored key (BYOK, backlog #10) if it has one, else
    GEMINI_API_KEY/GOOGLE_API_KEY from the environment -- same fallback
    shape as runway._make_client(), via account_keys.key_for().
    """
    creds = account_keys.key_for(account_id, "veo")
    key = creds["api_key"] if creds else None
    if not key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set")
    return genai.Client(api_key=key)


def has_key(account_id: Optional[int] = None) -> bool:
    return account_keys.key_for(account_id, "veo") is not None


def generate_video(prompt: str, out_path, *, model: str = DEFAULT_MODEL,
                   aspect_ratio: str = "9:16", resolution: str = DEFAULT_RESOLUTION,
                   duration: int = DEFAULT_DURATION, image=None, client=None,
                   poll_delay: float = 10.0, timeout_s: float = 600.0,
                   approved: Optional[bool] = None,
                   account_id: Optional[int] = None,
                   db_path=None,
                   charge: Optional[charging.Charge] = None) -> Path:
    """
    The thin wrapper: submit -> poll until done or timeout -> download.
    Raises on anything; generate_candidates is the layer that catches.
    The credit hold is taken here too, after the spend gate and before
    the submit (src/charge.py, 2026-09-18): `charge` is the caller's when
    it will record the generation; otherwise this call holds and settles
    its own at the estimate. `db_path` is the ledger's DSN for that case.
    Latency runs ~11s to ~6min, so polling is the contract, not an edge
    case.

    Config field names verified against the INSTALLED google-genai
    (1.x, 2026-08): the SDK takes duration_seconds (int), not the
    docs-snippet "duration" string.

    The spend gate is checked HERE, before the client is even built, so
    no caller can spend around it -- runway.generate_video's rule.
    """
    if not spend_approved(approved):
        raise RuntimeError(
            f"credit spend not approved: this call was not approved by a person. "
            f"Approve it at the Queue, or set {SPEND_ENV}=1 for an unattended run "
            f"(~${COST_PER_CLIP_USD:.2f} per clip -- the most expensive in the repo)"
        )
    client = client or _make_client(account_id)
    kwargs = {"image": image} if image is not None else {}
    out_path = Path(out_path)
    own = charge is None
    if own:
        charge = charging.Charge(
            account_id, provider="veo", ref=out_path.name,
            estimate_usd=estimate_cost(1),
            key_source=account_keys.key_source(account_id, "veo", db_path),
            dsn=db_path)
    charge.take()          # InsufficientCredit raises HERE: nothing submitted
    charge.submitted()     # the last line before the provider call
    try:
        operation = client.models.generate_videos(
            model=model,
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=int(duration),
            ),
            **kwargs,
        )

        deadline = time.monotonic() + timeout_s
        while not operation.done:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Veo job did not finish within {timeout_s:.0f}s")
            time.sleep(poll_delay)
            operation = client.operations.get(operation)

        videos = getattr(operation.response, "generated_videos", None) or []
        if not videos:
            raise RuntimeError("Veo job finished with no video in the response")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        video = videos[0]
        # download NOW -- Google keeps the file ~2 days, the repo keeps it forever
        client.files.download(file=video.video)
        video.video.save(str(out_path))
    except Exception as e:
        charge.release(f"veo: {type(e).__name__}")
        raise
    if own:
        charge.settle()
    return out_path


def _shot_row_for_prompt(prompt: str, db_path, account_id: Optional[int] = None) -> int:
    """A generations row needs a shot to hang off. The interactive path
    has one from promptgen; the graph's AI shots don't, so synthesize a
    minimal Shot -- the row exists to make the attempt countable, and
    its notes say where it came from."""
    kwargs = {"dsn": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="as prompted")
    return generative.add_shot(shot, notes="auto-created by veo.generate_candidates",
                               **kwargs, account_id=account_id)


def generate_candidates(prompt: str, out_dir, n: int = 3, *, shot_id: Optional[int] = None,
                        db_path=None, client=None, model: str = DEFAULT_MODEL,
                        approved: Optional[bool] = None,
                        account_id: Optional[int] = None, **cfg) -> dict:
    """
    Never raises. {"ok", "candidates": [{path, generation_id, model}],
    "error"} -- a missing key, a failed job, or the daily cap is a
    result the caller can show, not an exception that takes the run
    down. Partial success is success: three asked, one landed, you still
    get the one (with the error noted).
    """
    n = int(os.environ.get("VEO_CANDIDATES", n))
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        if not spend_approved(approved):
            return {"ok": False, "candidates": [],
                    "error": f"credit spend not approved: set {SPEND_ENV}=1 to "
                             f"approve ~${estimate_cost(n)} of Veo spend for this run"}

        refusal = generative.cap_error(
            "veo", n, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            dsn=db_path,
            env_prefix="VEO", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "candidates": [], "error": refusal}

        if shot_id is None:
            shot_id = _shot_row_for_prompt(prompt, db_path, account_id)

        out_dir = Path(out_dir)
        candidates, errors = [], []
        for i in range(1, n + 1):
            out_path = out_dir / f"cand{i}.mp4"
            try:
                generate_video(prompt, out_path, model=model, client=client,
                             approved=approved, account_id=account_id, **cfg)
            except Exception as e:
                errors.append(f"candidate {i}: {_safe_error(e, account_id)}")
                continue
            generation_id = generative.record_generation(
                shot_id, "veo", prompt,
                params={"model": model,
                        "key_source": account_keys.key_source(account_id, "veo", db_path),
                        **cfg},
                output_path=str(out_path),
                cost_usd=COST_PER_CLIP_USD,
                notes=None,
                **kwargs,
             account_id=account_id)
            candidates.append({"path": str(out_path),
                               "generation_id": generation_id, "model": model})

        return {"ok": bool(candidates), "candidates": candidates, "shot_id": shot_id,
                "error": "; ".join(errors) if errors else None}
    except Exception as e:
        return {"ok": False, "candidates": [], "error": _safe_error(e, account_id)}



def _local_render_bytes(value: str):
    """A site-relative /renders/ URL -> that file's bytes, or None.

    A render is a local file no model provider can fetch by URL, and the
    path comes out of a stored shot, so anything escaping data/renders/
    is refused. runway._local_render_bytes' twin; the copy exists for the
    same reason that one does -- src/ never imports app/."""
    try:
        root = RENDERS_ROOT.resolve()
        target = (root / value[len("/renders/"):]).resolve()
        if root in target.parents and target.is_file():
            return target.read_bytes()
    except OSError:
        return None
    return None


def as_prompt_image(value, *, resolve_photo=None):
    """Anything we might have stored as a reference -> a types.Image Veo
    can anchor on, or None.

    Veo differs from BOTH of the shapes already in this repo, so this is
    a third one rather than a copy: Runway takes a public URL or a data:
    URI, Higgsfield and fal take a URL their servers fetch, and the
    google-genai SDK takes RAW BYTES with a mime type. That last one is
    the friendliest of the three -- a keyframe on a machine with no R2
    still anchors here, where the fetching vendors have to drop it.

    The mime comes from the magic number, never a guess: Nano writes PNG
    and the pipeline's keyframes are Nano's.
    """
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    elif value and isinstance(value, str):
        value = value.strip()
        data = None
        if value.startswith("data:image/"):
            import base64
            try:
                data = base64.b64decode(value.split(",", 1)[1])
            except Exception:
                data = None
        elif value.startswith("/renders/"):
            data = _local_render_bytes(value)
        elif value.startswith(("http://", "https://")):
            from .imagery import fetch_image_bytes
            data = fetch_image_bytes(value)
        elif resolve_photo is not None:
            try:
                target = resolve_photo(value)
            except Exception:
                target = None
            if target is not None:
                try:
                    data = Path(target).read_bytes()
                except OSError:
                    data = None
    else:
        return None
    if not data:
        # a reference that cannot be resolved is dropped, never fatal --
        # generate_for_shot records prompt_image=False either way, so
        # nothing downstream claims an anchor that was never sent
        return None
    from .gemini_utils import sniff_mime
    return types.Image(image_bytes=data, mime_type=sniff_mime(data))


def _publish(out_path: Path, content_type: str) -> str:
    """R2 when configured (Instagram needs a public URL), else the app's
    own /renders mount."""
    from . import storage
    if storage.configured():
        return storage.upload_file(
            out_path, key=f"renders/veo/{out_path.name}",
            content_type=content_type)
    return f"/renders/veo/{out_path.name}"


def generate_for_shot(concept_id: int, shot_n, *, db_path=None,
                      model: str = DEFAULT_MODEL,
                      duration: int = DEFAULT_DURATION,
                      resolution: str = DEFAULT_RESOLUTION,
                      resolve_photo=None, client=None,
                      approved: Optional[bool] = None,
                      account_id: Optional[int] = None,
                      part: Optional[int] = None,
) -> dict:
    """
    `part` (2026-09-10) renders ONE shot of a timed scene -- its composed
    prompt, anchored on its own still, attached to that part (see
    src/timeline.py). None is the whole scene, exactly as before.

    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    One render for one concept shot -- runway.generate_for_shot's exact
    contract, so the Queue's approve can dispatch here without knowing
    which vendor it is talking to. The spend gate lives inside
    generate_video, the cap is checked before any call, and the attempt
    is a generations row either way the pick later goes.

    THIS IS THE MOST EXPENSIVE BUTTON IN THE REPO. Veo is $3.20 a clip
    against Runway's ~$0.25, and VEO_DAILY_CAP defaults to 6 for that
    reason. Nothing here loosens either wall; the Queue simply stops
    being able to reach the cheap vendors only.
    """
    from . import preprod, render_assets
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        generative.init(**kwargs)
        refusal = generative.cap_error(
            "veo", 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            dsn=db_path,
            env_prefix="VEO", phrase="generations used",
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
        from . import timeline
        target = timeline.render_target(shot, part)
        if target is None:
            return {"ok": False, "error": f"shot {shot_n} has no part {part}"}
        prompt = target["prompt"]
        if not prompt:
            return {"ok": False,
                    "error": f"shot {shot_n} has no AI prompt to render from"}

        image = as_prompt_image(target["reference_image"],
                               resolve_photo=resolve_photo)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"c{concept_id}-s{shot_n}{f'-p{part}' if part else ''}-{stamp}.mp4"
        key_source = account_keys.key_source(account_id, "veo", db_path)
        charge = charging.Charge(
            account_id, provider="veo", ref=out_path.name,
            estimate_usd=estimate_cost(1), key_source=key_source, dsn=db_path)
        generate_video(prompt, out_path, model=model, duration=duration,
                       resolution=resolution, image=image, client=client,
                       approved=approved, account_id=account_id, charge=charge)

        shot_row_id = _shot_row_for_prompt(prompt, db_path, account_id)
        generation_params = {"model": model, "duration": duration,
                             "resolution": resolution,
                             "concept_id": concept_id, "shot_n": shot_n,
                             **({"part": part} if part else {}),
                             "prompt_image": image is not None,
                             "key_source": key_source,
                             **charge.params()}
        generation_id = generative.record_generation(
            shot_row_id, "veo", prompt,
            params=generation_params,
            output_path=str(out_path),
            cost_usd=estimate_cost(1),
            **kwargs,
            account_id=account_id)
        charge.settle(generation_id=generation_id)

        media_url = _publish(out_path, "video/mp4")
        if part:
            timeline.attach_part(concept_id, shot_n, part, "media_url", media_url,
                                 db_path=db_path, account_id=account_id)
        else:
            preprod.set_shot_media_url(concept_id, shot_n, media_url,
                                       **kwargs, account_id=account_id)
        asset = render_assets.record_best_effort(
            account_id=account_id,
            generation_id=generation_id, tool="veo", model=model,
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
    except ledger.InsufficientCredit as e:
        return {"ok": False, "error": charging.refusal(e)}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, account_id)}

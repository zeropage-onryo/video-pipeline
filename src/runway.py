#!/usr/bin/env python3
"""
The Runway connector: prompt -> video -> pipeline. veo.py's exact shape
(thin raising wrapper under a never-raises edge), one extra gate.

Two layers:
- generate_video      -- the thin wrapper. Create the task via the
                         runwayml SDK, wait for it, download the output
                         URL immediately (Runway's output URLs are
                         signed and ephemeral). Raises on failure; its
                         caller catches.
- generate_candidates -- the never-raises edge: N candidate clips for
                         one prompt, every attempt logged through
                         generative.record_generation. Nothing is ever
                         auto-kept -- the pick is the label.

THE SPEND GATE, and why it's here and not in callers: the Runway API
has no Explore Mode. Unlimited generation is a web-app feature of the
Unlimited/Max plan; API calls always burn API credits, a separate
balance from the app subscription ("web app credits will never appear
in your API credits" -- help.runwayml.com, checked 2026-08-12). So the
cheap path is the app, and the API is a deliberate spend:
- RUNWAY_SPEND_OK=1 must be set or generate_video raises -- the default
  answer is "render it in the Runway app for free". Set it per run,
  never in .env, so every credit spend is an explicit human approval.
- DAILY_CAP (RUNWAY_DAILY_CAP, default 6) counted from the generations
  table, same wall veo.py has.
- estimate_cost() prices a plan before anyone approves it.

SDK verified against docs.dev.runwayml.com 2026-08-12: package
`runwayml`, key in RUNWAYML_API_SECRET, client.image_to_video.create
(omit prompt_image for text-to-video), models gen4_turbo (5 credits/s)
and gen4.5 (12 credits/s) at $0.01/credit, ratio "720:1280" for 9:16,
wait_for_task_output() polls and raises TaskFailedError. Re-verify on
SDK bump -- Runway versions these.
"""
from __future__ import annotations

import base64
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import generative, render_assets
from .db import DB_PATH
from .shot import Shot

MODELS = ("gen4_turbo", "gen4.5")
DEFAULT_MODEL = os.environ.get("RUNWAY_MODEL", "gen4_turbo")   # cheapest first spend
DEFAULT_RATIO = "720:1280"   # 9:16, the platform vertical
DEFAULT_DURATION = 5
DAILY_CAP = int(os.environ.get("RUNWAY_DAILY_CAP", "6"))

SPEND_ENV = "RUNWAY_SPEND_OK"

# $0.01/credit; credits/second per model, dev-portal pricing 2026-08-12.
CREDIT_USD = 0.01
CREDITS_PER_SECOND = {"gen4_turbo": 5, "gen4.5": 12}


def spend_approved() -> bool:
    """The human approval for burning API credits. Per-run by design:
    set RUNWAY_SPEND_OK=1 on the command, not in .env -- an approval
    that's always on isn't an approval."""
    return (os.environ.get(SPEND_ENV) or "").strip() == "1"


def _safe_error(e: Exception) -> str:
    """The key must never reach a page, a log line, or a DB row."""
    text = str(e)
    secret = os.environ.get("RUNWAYML_API_SECRET")
    if secret:
        text = text.replace(secret, "<RUNWAYML_API_SECRET>")
    return re.sub(r"(Bearer\s+)[A-Za-z0-9_\-.]+", r"\1<redacted>", text)


def estimate_cost(n: int, *, model: str = DEFAULT_MODEL,
                  duration: int = DEFAULT_DURATION) -> float:
    per_second = CREDITS_PER_SECOND.get(model, max(CREDITS_PER_SECOND.values()))
    return round(n * duration * per_second * CREDIT_USD, 2)


def generations_today(db_path=None) -> int:
    """Runway generations logged since UTC midnight -- what DAILY_CAP
    counts against. Reads the same generations table the scoreboards do,
    so the cap can't drift from the log."""
    today = datetime.now(timezone.utc).date().isoformat()
    with generative.connect(db_path if db_path is not None else DB_PATH) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM generations WHERE tool = 'runway' AND created_at >= ?",
            (today,),
        ).fetchone()
        return row[0]


def _make_client():
    key = os.environ.get("RUNWAYML_API_SECRET")
    if not key:
        raise RuntimeError("RUNWAYML_API_SECRET not set")
    try:
        from runwayml import RunwayML
    except ImportError as e:
        raise RuntimeError("runwayml SDK not installed -- it's in requirements.txt") from e
    return RunwayML(api_key=key)


def _download(url: str, out_path: Path) -> None:
    """Runway's output URLs are signed and expire; download the moment
    the task finishes, the repo keeps the file forever."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, open(out_path, "wb") as f:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def generate_video(prompt: str, out_path, *, model: str = DEFAULT_MODEL,
                   ratio: str = DEFAULT_RATIO, duration: int = DEFAULT_DURATION,
                   prompt_image=None, client=None) -> Path:
    """
    The thin wrapper: create -> wait -> download. Raises on anything --
    including a missing spend approval, which is checked HERE so no
    caller can spend a credit around the gate. generate_candidates is
    the layer that catches.
    """
    if not spend_approved():
        raise RuntimeError(
            f"credit spend not approved: render this in the Runway app instead "
            f"(Explore Mode, free on the Unlimited plan), or set {SPEND_ENV}=1 "
            f"on this run to approve API credits"
        )
    client = client or _make_client()
    kwargs = {"prompt_image": prompt_image} if prompt_image is not None else {}
    task = client.image_to_video.create(
        model=model,
        prompt_text=prompt,
        ratio=ratio,
        duration=int(duration),
        **kwargs,
    ).wait_for_task_output()

    outputs = getattr(task, "output", None) or []
    if not outputs:
        raise RuntimeError("Runway task finished with no output URL")

    out_path = Path(out_path)
    _download(outputs[0], out_path)
    return out_path


def _shot_row_for_prompt(prompt: str, db_path) -> int:
    """A generations row needs a shot to hang off. The graph's AI shots
    don't have one, so synthesize a minimal Shot -- the row exists to
    make the attempt countable, and its notes say where it came from."""
    kwargs = {"path": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="as prompted")
    return generative.add_shot(shot, notes="auto-created by runway.generate_candidates",
                               **kwargs)


def generate_candidates(prompt: str, out_dir, n: int = 3, *, shot_id: Optional[int] = None,
                        db_path=None, client=None, model: str = DEFAULT_MODEL,
                        **cfg) -> dict:
    """
    Never raises. {"ok", "candidates": [{path, generation_id, model}],
    "error"} -- a missing approval, a missing key, a failed job, or the
    daily cap is a result the caller can show, not an exception that
    takes the run down. Partial success is success.
    """
    n = int(os.environ.get("RUNWAY_CANDIDATES", n))
    kwargs = {"path": db_path} if db_path is not None else {}

    try:
        if not spend_approved():
            return {"ok": False, "candidates": [],
                    "error": f"credit spend not approved: render in the Runway app "
                             f"(Explore Mode, free) or set {SPEND_ENV}=1 to approve "
                             f"~${estimate_cost(n, model=model, duration=int(cfg.get('duration', DEFAULT_DURATION)))} "
                             f"of API credits for this run"}

        used = generations_today(db_path=db_path)
        if used + n > DAILY_CAP:
            return {"ok": False, "candidates": [],
                    "error": f"daily cap: {used}/{DAILY_CAP} generations used today, "
                             f"{n} more would exceed it (RUNWAY_DAILY_CAP to raise)"}

        if shot_id is None:
            shot_id = _shot_row_for_prompt(prompt, db_path)

        out_dir = Path(out_dir)
        duration = int(cfg.get("duration", DEFAULT_DURATION))
        candidates, errors = [], []
        for i in range(1, n + 1):
            out_path = out_dir / f"cand{i}.mp4"
            try:
                generate_video(prompt, out_path, model=model, client=client, **cfg)
            except Exception as e:
                errors.append(f"candidate {i}: {_safe_error(e)}")
                continue
            generation_id = generative.record_generation(
                shot_id, "runway", prompt,
                params={"model": model, **cfg},
                output_path=str(out_path),
                cost_usd=estimate_cost(1, model=model, duration=duration),
                notes=None,
                **kwargs,
            )
            candidates.append({"path": str(out_path),
                               "generation_id": generation_id, "model": model})

        return {"ok": bool(candidates), "candidates": candidates, "shot_id": shot_id,
                "error": "; ".join(errors) if errors else None}
    except Exception as e:
        return {"ok": False, "candidates": [], "error": _safe_error(e)}


# --- the scene board's one-click render (added 2026-08-21) -----------------

RENDER_DIR = Path(__file__).resolve().parent.parent / "data" / "renders" / "runway"


def has_key() -> bool:
    return bool(os.environ.get("RUNWAYML_API_SECRET"))


def generate_for_shot(concept_id: int, shot_n, *, db_path=None,
                      model: str = DEFAULT_MODEL, client=None) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "error"}. One
    render for one concept shot, through every wall this module already
    has -- the spend gate lives inside generate_video, so this layer
    cannot spend around it; the cap is checked before any call; the
    attempt is a generations row either way the pick later goes.

    Reads the shot's stored prompt, anchors on its reference_image when
    that's a public URL (what the reference is FOR), downloads the clip
    to data/renders/runway/, uploads to R2 when configured (Instagram
    needs a public URL), else leaves it served from the app's /renders
    mount -- and attaches the result via preprod.set_shot_media_url,
    the field autopilot.build_plan requires before it will ever emit a
    post action.
    """
    from . import preprod, storage
    kwargs = {"path": db_path} if db_path is not None else {}

    try:
        used = generations_today(db_path=db_path)
        if used >= DAILY_CAP:
            return {"ok": False,
                    "error": f"daily cap: {used}/{DAILY_CAP} generations used "
                             f"today (RUNWAY_DAILY_CAP to raise)"}

        concept = preprod.get_concept(concept_id, **kwargs)
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

        reference = (shot.get("reference_image") or "").strip()
        prompt_image = reference if reference.startswith(("http://", "https://")) else None

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"c{concept_id}-s{shot_n}-{stamp}.mp4"
        generate_video(prompt, out_path, model=model,
                       prompt_image=prompt_image, client=client)

        shot_row_id = _shot_row_for_prompt(prompt, db_path)
        generation_params = {"model": model, "ratio": DEFAULT_RATIO,
                             "duration": DEFAULT_DURATION,
                             "concept_id": concept_id, "shot_n": shot_n,
                             "prompt_image": bool(prompt_image)}
        generation_id = generative.record_generation(
            shot_row_id, "runway", prompt,
            params=generation_params,
            output_path=str(out_path),
            cost_usd=estimate_cost(1, model=model),
            **kwargs,
        )

        if storage.configured():
            media_url = storage.upload_file(
                out_path, key=f"renders/runway/{out_path.name}",
                content_type="video/mp4")
        else:
            media_url = f"/renders/runway/{out_path.name}"

        preprod.set_shot_media_url(concept_id, shot_n, media_url, **kwargs)
        asset = render_assets.record_best_effort(
            generation_id=generation_id, tool="runway", model=model,
            media_kind="video", prompt=prompt, media_url=media_url,
            output_path=str(out_path), project=concept.get("brand"),
            concept_id=concept_id, shot_n=shot_n,
            metadata=generation_params,
            path=db_path if db_path is not None else DB_PATH,
        )
        return {"ok": True, "media_url": media_url,
                "generation_id": generation_id, "path": str(out_path),
                "asset_id": asset["id"], "asset_rag": asset["rag"],
                "error": None}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e)}


def generate_from_prompt(prompt: str, *, reference_image=None, db_path=None,
                         model: str = DEFAULT_MODEL, client=None) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    The free-standing render behind the Workflows canvas's Generate
    node: a prompt plus an optional reference, no concept/shot row
    required -- generate_for_shot's walls without its coupling. The
    spend gate lives inside generate_video, so this layer cannot spend
    around it either; the cap is checked first; the attempt is a
    generations row via the same synthesized-shot path the graph uses.

    `reference_image` anchors the render: a public http(s) URL or a
    data: URI passes straight through as prompt_image; raw image bytes
    (a picked local asset photo, which Runway could never fetch) become
    a data URI. Anything else is dropped -- a reference is an
    enhancement, never a gate.
    """
    from . import storage
    kwargs = {"path": db_path} if db_path is not None else {}

    try:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "an empty prompt renders nothing"}

        # a fresh DB has no generations table until something inits it;
        # the cap count below must not be the thing that discovers that
        generative.init(**kwargs)
        used = generations_today(db_path=db_path)
        if used >= DAILY_CAP:
            return {"ok": False,
                    "error": f"daily cap: {used}/{DAILY_CAP} generations used "
                             f"today (RUNWAY_DAILY_CAP to raise)"}

        prompt_image = None
        if isinstance(reference_image, (bytes, bytearray)):
            prompt_image = ("data:image/jpeg;base64,"
                            + base64.b64encode(bytes(reference_image)).decode("ascii"))
        elif isinstance(reference_image, str) and reference_image.startswith(
                ("http://", "https://", "data:image/")):
            prompt_image = reference_image

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"wf-{stamp}.mp4"
        generate_video(prompt, out_path, model=model,
                       prompt_image=prompt_image, client=client)

        shot_row_id = _shot_row_for_prompt(prompt, db_path)
        generation_params = {"model": model, "ratio": DEFAULT_RATIO,
                             "duration": DEFAULT_DURATION,
                             "source": "workflow",
                             "prompt_image": bool(prompt_image)}
        generation_id = generative.record_generation(
            shot_row_id, "runway", prompt,
            params=generation_params,
            output_path=str(out_path),
            cost_usd=estimate_cost(1, model=model),
            **kwargs,
        )

        if storage.configured():
            media_url = storage.upload_file(
                out_path, key=f"renders/runway/{out_path.name}",
                content_type="video/mp4")
        else:
            media_url = f"/renders/runway/{out_path.name}"

        asset = render_assets.record_best_effort(
            generation_id=generation_id, tool="runway", model=model,
            media_kind="video", prompt=prompt, media_url=media_url,
            output_path=str(out_path), metadata=generation_params,
            path=db_path if db_path is not None else DB_PATH,
        )

        return {"ok": True, "media_url": media_url,
                "generation_id": generation_id, "path": str(out_path),
                "asset_id": asset["id"], "asset_rag": asset["rag"],
                "error": None}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e)}

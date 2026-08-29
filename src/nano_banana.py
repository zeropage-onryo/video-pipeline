"""
The Nano Banana connector -- Gemini image generation on the same SDK
and key everything else already uses. runway.py's exact shape: a thin
raising wrapper (generate_image) under a never-raises edge
(generate_from_prompt), every attempt a generations row, a DB-enforced
daily cap.

No separate spend gate, deliberately: this is the GEMINI_API_KEY the
whole pipeline already bills against, and one image costs cents where
a Runway render burns real credits. The wall here is NANO_DAILY_CAP
(default 20/day), counted from the generations table so it can't drift
from the log.

Model verified against the Gemini API docs 2026-08-25:
"gemini-2.5-flash-image" is Nano Banana; set NANO_BANANA_MODEL to
"gemini-3-pro-image-preview" for Nano Banana Pro (better text/layout,
several times the per-image price). Output arrives as inline_data
bytes on the response parts -- there is no file URL to download.
"""
import base64
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import generative, render_assets
from .db import DB_PATH
from .gemini_utils import sniff_mime
from .shot import Shot

MODEL = os.environ.get("NANO_BANANA_MODEL", "gemini-2.5-flash-image")
DAILY_CAP = int(os.environ.get("NANO_DAILY_CAP", "20"))
RETRIES = int(os.environ.get("NANO_RETRIES", "3"))
RETRY_DELAY = 4.0

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RENDER_DIR = PROJECT_ROOT / "data" / "renders" / "nano"

# Every prompt this pipeline writes is a VIDEO prompt -- "9:16", "the
# camera follows", "handheld drift". Handed to an image model those read
# as instructions it cannot carry out, and it answers in prose instead
# of rendering ("Understood. I will apply these guidelines...") -- a
# billed call that returns no image. Re-framing the same words as a
# description of ONE frame keeps every detail and drops the impossible
# instruction. Pure and constant, so what was sent is always
# reconstructable from the logged prompt.
STILL_FRAME_TEMPLATE = (
    "Render a single photorealistic still image: one frame lifted out of "
    "the shot described below.\n\n"
    "Treat camera, lens, motion and duration language as a description of "
    "how this one frame is composed and where the movement is caught "
    "mid-move -- never as a sequence to play out. Output the image itself, "
    "with no commentary.\n\n"
    "{reference}THE SHOT\n{prompt}"
)

# Attaching a reference is not the same as saying what it is FOR. Bytes
# with no instruction leave the model to guess between "copy this",
# "continue this" and "ignore this" -- so the shot's own description
# gets overridden as often as it gets matched.
REFERENCE_NOTE = (
    "THE ATTACHED {subject} reference material for this shot: match the "
    "subject's face, wardrobe, props and location exactly as they appear "
    "in {them}. Do NOT copy {their} framing, crop or camera angle -- those "
    "come from the shot description below.\n\n"
)


def as_still_frame(prompt: str, *, has_reference=False) -> str:
    """The video prompt, re-framed as a single-frame brief. Pure -- no
    model call goes near it, so a refusal is either a bad framing
    (visible here) or a bad prompt, never both at once."""
    prompt = (prompt or "").strip()
    if not prompt:
        return ""
    count = int(has_reference)          # a bool counts as one
    note = "" if not count else REFERENCE_NOTE.format(
        subject="IMAGE is" if count == 1 else f"{count} IMAGES are",
        them="it" if count == 1 else "them",
        their="its" if count == 1 else "their")
    return STILL_FRAME_TEMPLATE.format(prompt=prompt, reference=note)


def has_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _client():
    from google import genai
    return genai.Client()


def generations_today(db_path=None) -> int:
    """Nano generations logged since UTC midnight -- what DAILY_CAP
    counts against, read from the same generations table the
    scoreboards do."""
    today = datetime.now(timezone.utc).date().isoformat()
    with generative.connect(db_path if db_path is not None else DB_PATH) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM generations WHERE tool = 'nano' AND created_at >= ?",
            (today,),
        ).fetchone()
        return row[0]


def _shot_row_for_prompt(prompt: str, db_path) -> int:
    """A generations row needs a shot to hang off; a free-standing
    canvas prompt doesn't have one, so synthesize a minimal Shot --
    the row exists to make the attempt countable."""
    kwargs = {"path": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="as prompted")
    return generative.add_shot(shot, notes="auto-created by nano_banana.generate_from_prompt",
                               **kwargs)


def _generate_content(client, model: str, parts):
    """The image call, retried on the two transient statuses the rest of
    the project already retries (gemini_utils.generate_with_retry).
    Its own helper rather than that one because that returns
    response.text and falls through to FALLBACK_MODELS -- both wrong
    here: the deliverable is inline image bytes, and the text models it
    falls back to cannot draw. No model fallback for the same reason;
    NANO_BANANA_MODEL is a deliberate choice, not a substitutable one.

    Measured 2026-08-26: two of four live calls came back 503
    UNAVAILABLE ("high demand... usually temporary") -- without this a
    spike reads to the person on the canvas as a hard failure."""
    last = None
    for attempt in range(RETRIES):
        try:
            return client.models.generate_content(model=model, contents=parts)
        except Exception as e:
            if not ("RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e)):
                raise
            last = e
            if attempt < RETRIES - 1:
                match = re.search(r"retry in ([\d.]+)s", str(e))
                time.sleep(float(match.group(1)) + 2 if match else RETRY_DELAY)
    raise last


def as_reference_list(reference) -> list:
    """One reference or several, normalised to a list of byte strings.

    Plural on purpose: a character's face and their wardrobe are two
    references, not one, and the whole point of naming assets is that
    several of them describe one shot. Anything that isn't bytes is
    dropped -- a reference is an enhancement, never a gate."""
    if reference is None:
        return []
    items = reference if isinstance(reference, (list, tuple)) else [reference]
    return [bytes(i) for i in items if isinstance(i, (bytes, bytearray)) and i]


def generate_image(prompt: str, out_path: Path, *, model: str = MODEL,
                   reference_bytes=None,
                   reference_mime: Optional[str] = None, client=None) -> Path:
    """The thin raising wrapper: one generate_content call (retried on a
    transient overload), first image part written to out_path. Raises
    when the model returns no image -- here the image IS the deliverable
    (the promptgen contract), and a text-only refusal must surface, not
    save an empty file.

    `reference_bytes` takes one image or a list of them; each rides as
    its own inline part, mime sniffed per image. reference_mime is
    honoured for a single reference so existing callers keep their
    behaviour, and ignored for a list, where per-image sniffing is the
    only thing that can be right."""
    from google.genai import types

    client = client or _client()
    references = as_reference_list(reference_bytes)
    parts = [
        types.Part.from_bytes(
            data=data,
            mime_type=(reference_mime if reference_mime and len(references) == 1
                       else sniff_mime(data)))
        for data in references
    ]
    parts.append(prompt)
    response = _generate_content(client, model, parts)
    for candidate in response.candidates or []:
        for part in (candidate.content.parts or []) if candidate.content else []:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                data = inline.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                out_path.write_bytes(data)
                return out_path
    text = getattr(response, "text", None)
    raise RuntimeError("no image in the response"
                       + (f" — model said: {text[:200]}" if text else ""))


def generate_from_prompt(prompt: str, *, reference_image=None, db_path=None,
                         model: str = MODEL, client=None) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    The Workflows canvas's Nano Banana node: prompt in, an image under
    /renders/nano/ out (uploaded to R2 when configured). reference_image
    may be raw bytes (a picked asset photo or an upstream render) --
    anything else is dropped, a reference is an enhancement, never a
    gate.

    The prompt goes through as_still_frame first: this pipeline's
    prompts describe video, and an image model handed camera moves
    answers in prose instead of rendering. The thin generate_image
    wrapper stays literal for callers who mean exactly what they typed.
    """
    from . import storage
    kwargs = {"path": db_path} if db_path is not None else {}

    try:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "an empty prompt renders nothing"}
        if not has_key():
            return {"ok": False, "error": "GEMINI_API_KEY not set"}

        generative.init(**kwargs)
        used = generations_today(db_path=db_path)
        if used >= DAILY_CAP:
            return {"ok": False,
                    "error": f"daily cap: {used}/{DAILY_CAP} images generated "
                             f"today (NANO_DAILY_CAP to raise)"}

        references = as_reference_list(reference_image)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"wf-{stamp}.png"
        generate_image(as_still_frame(prompt, has_reference=len(references)),
                       out_path, model=model,
                       reference_bytes=references, client=client)

        # the row logs the prompt the person wrote, not the constant
        # wrapper around it -- the flag says which framing was applied
        shot_row_id = _shot_row_for_prompt(prompt, db_path)
        generation_params = {"model": model, "source": "workflow",
                             "framing": "still", "references": len(references)}
        generation_id = generative.record_generation(
            shot_row_id, "nano", prompt,
            params=generation_params,
            output_path=str(out_path),
            **kwargs,
        )

        if storage.configured():
            media_url = storage.upload_file(
                out_path, key=f"renders/nano/{out_path.name}",
                content_type="image/png")
        else:
            media_url = f"/renders/nano/{out_path.name}"

        asset = render_assets.record_best_effort(
            generation_id=generation_id, tool="nano", model=model,
            media_kind="image", prompt=prompt, media_url=media_url,
            output_path=str(out_path), metadata=generation_params,
            path=db_path if db_path is not None else DB_PATH,
        )

        return {"ok": True, "media_url": media_url,
                "generation_id": generation_id, "path": str(out_path),
                "asset_id": asset["id"], "asset_rag": asset["rag"],
                "error": None}
    except Exception as e:
        return {"ok": False, "media_url": None, "generation_id": None,
                "path": None, "error": str(e)}

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

from . import generative
from .db import DB_PATH
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
    "THE SHOT\n{prompt}"
)


def as_still_frame(prompt: str) -> str:
    """The video prompt, re-framed as a single-frame brief. Pure -- no
    model call goes near it, so a refusal is either a bad framing
    (visible here) or a bad prompt, never both at once."""
    prompt = (prompt or "").strip()
    if not prompt:
        return ""
    return STILL_FRAME_TEMPLATE.format(prompt=prompt)


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


def generate_image(prompt: str, out_path: Path, *, model: str = MODEL,
                   reference_bytes: Optional[bytes] = None,
                   reference_mime: str = "image/jpeg", client=None) -> Path:
    """The thin raising wrapper: one generate_content call (retried on a
    transient overload), first image part written to out_path. Raises
    when the model returns no image -- here the image IS the deliverable
    (the promptgen contract), and a text-only refusal must surface, not
    save an empty file."""
    from google.genai import types

    client = client or _client()
    parts = []
    if reference_bytes:
        parts.append(types.Part.from_bytes(data=reference_bytes,
                                           mime_type=reference_mime))
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

        reference_bytes = (bytes(reference_image)
                           if isinstance(reference_image, (bytes, bytearray)) else None)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"wf-{stamp}.png"
        generate_image(as_still_frame(prompt), out_path, model=model,
                       reference_bytes=reference_bytes, client=client)

        # the row logs the prompt the person wrote, not the constant
        # wrapper around it -- the flag says which framing was applied
        shot_row_id = _shot_row_for_prompt(prompt, db_path)
        generation_id = generative.record_generation(
            shot_row_id, "nano", prompt,
            params={"model": model, "source": "workflow",
                    "framing": "still", "reference": bool(reference_bytes)},
            output_path=str(out_path),
            **kwargs,
        )

        if storage.configured():
            media_url = storage.upload_file(
                out_path, key=f"renders/nano/{out_path.name}",
                content_type="image/png")
        else:
            media_url = f"/renders/nano/{out_path.name}"

        return {"ok": True, "media_url": media_url,
                "generation_id": generation_id, "path": str(out_path),
                "error": None}
    except Exception as e:
        return {"ok": False, "media_url": None, "generation_id": None,
                "path": None, "error": str(e)}

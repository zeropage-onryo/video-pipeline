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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import generative
from .db import DB_PATH
from .shot import Shot

MODEL = os.environ.get("NANO_BANANA_MODEL", "gemini-2.5-flash-image")
DAILY_CAP = int(os.environ.get("NANO_DAILY_CAP", "20"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RENDER_DIR = PROJECT_ROOT / "data" / "renders" / "nano"


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


def generate_image(prompt: str, out_path: Path, *, model: str = MODEL,
                   reference_bytes: Optional[bytes] = None,
                   reference_mime: str = "image/jpeg", client=None) -> Path:
    """The thin raising wrapper: one generate_content call, first image
    part written to out_path. Raises when the model returns no image --
    here the image IS the deliverable (the promptgen contract), and a
    text-only refusal must surface, not save an empty file."""
    from google.genai import types

    client = client or _client()
    parts = []
    if reference_bytes:
        parts.append(types.Part.from_bytes(data=reference_bytes,
                                           mime_type=reference_mime))
    parts.append(prompt)
    response = client.models.generate_content(model=model, contents=parts)
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
        generate_image(prompt, out_path, model=model,
                       reference_bytes=reference_bytes, client=client)

        shot_row_id = _shot_row_for_prompt(prompt, db_path)
        generation_id = generative.record_generation(
            shot_row_id, "nano", prompt,
            params={"model": model, "source": "workflow",
                    "reference": bool(reference_bytes)},
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

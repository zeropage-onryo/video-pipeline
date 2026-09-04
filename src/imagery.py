"""
src/imagery.py -- everything between a stored reference and the model
that has to actually SEE it, plus the one call that consumes them.

A reference in this pipeline is a URL: a picked asset photo
(/characters/michael/photo/1.jpg), an upload (/refs/<hash>.jpg), a
local render (/renders/nano/wf-*.png) or, once R2 is configured, a
public https URL. NEITHER Gemini nor Nano can fetch a URL -- naming one
in the prompt text is indistinguishable from attaching nothing -- so
every path here ends in bytes.

Lifted out of app/workflow_runner.py unchanged (2026-08-29), when the
Studio's scene chain needed the same resolution from src/, which must
never import app/. The canvas keeps working through re-exports, and the
hard-won details came across untouched: the SSRF guard, the 15MB inline
cap, the EXIF-rotation/downscale pass, and enhance()'s
caption-then-bytes ordering. These are bugs already paid for.
"""
from __future__ import annotations

from typing import Optional

from . import shootgen, workflows
from .gemini_utils import sniff_mime


def render_bytes(value):
    """An upstream node's /renders/ URL -> that file's bytes, or None.
    Shared by both reference resolvers: a render is a local file no
    model provider can fetch by URL, and the path is user-influenced,
    so anything escaping data/renders/ is refused."""
    from pathlib import Path

    root = (Path(__file__).resolve().parent.parent / "data" / "renders").resolve()
    target = (root / value[len("/renders/"):]).resolve()
    if root in target.parents and target.is_file():
        return target.read_bytes()
    return None


MAX_FETCH_BYTES = 15 * 1024 * 1024      # Gemini's inline request budget is ~20MB
FETCH_TIMEOUT = 10


def _public_host(host) -> bool:
    """Delegates to refbin.public_host -- one guard, two fetchers.
    Kept as a name here because the tests and the node handlers use it.
    """
    from . import refbin
    return refbin.public_host(host)


def fetch_image_bytes(url):
    """A public image URL -> its bytes, or None. Never raises.

    This exists because R2 went live: once storage is configured every
    stored reference image and every keyframe is an https URL, and
    NEITHER model can fetch one. Gemini takes inline bytes only, so
    before this an https reference was silently dropped (Nano) or
    degraded to a line of text naming the URL (enhance) -- the reference
    looked attached on the canvas and reached no model at all."""
    from urllib.parse import urlparse

    import requests

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if not _public_host(parsed.hostname):
        return None
    try:
        with requests.get(url, stream=True, timeout=FETCH_TIMEOUT) as response:
            response.raise_for_status()
            kind = (response.headers.get("content-type") or "").split(";")[0].strip()
            if kind and not kind.startswith("image/"):
                return None
            data = b""
            for chunk in response.iter_content(64 * 1024):
                data += chunk
                if len(data) > MAX_FETCH_BYTES:
                    return None            # too big to ride inline; drop it
        return data or None
    except Exception:
        return None                        # a reference is an enhancement, never a gate




def image_bytes_for_gemini(value, resolve_photo=None):
    """Any reference input -> raw bytes Gemini can take as vision input
    (it never fetches URLs itself). A data URI decodes; an upstream
    render's /renders/ URL resolves against data/renders/; a picked
    asset photo resolves through resolve_photo; a public http(s) URL is
    fetched. Local resolution is tried first -- a file on this disk
    beats a round trip. None when nothing resolves: a reference is an
    enhancement, never a gate."""
    import base64

    if not value or not isinstance(value, str):
        return None
    if value.startswith("data:image/"):
        try:
            return base64.b64decode(value.split(",", 1)[1])
        except Exception:
            return None
    if value.startswith("/renders/"):
        return render_bytes(value)
    if value.startswith(("http://", "https://")):
        return fetch_image_bytes(value)
    target = resolve_photo(value) if resolve_photo else None
    return upright(target.read_bytes()) if target is not None else None


VISION_MAX_EDGE = 1536   # these models tile an image at ~1k px anyway


def upright(data):
    """A reference photo as the renderers should receive it: rotation
    baked in, and not absurdly larger than the model will look at.

    Two things, because both are about the same journey from disk to
    request body:

    ROTATION. Every photo off Mike's iPhone is stored landscape with
    EXIF orientation 6 -- a portrait only because a tag says to turn
    it. We hand the renderers raw bytes, and a model fed a face lying
    on its side grounds badly on it (2026-08-28).

    SIZE. These models tile an image down to about a thousand pixels
    regardless, so a 5712x4284 still costs megabytes of request body
    and buys nothing with them. Three untouched references came to
    ~10MB against an inline ceiling around 20MB, and a request that
    heavy is also the first thing shed when the model is busy. Capping
    the long edge takes the same three to a few hundred KB.

    A photo already upright and already small comes back as the very
    same object -- no re-encode, no generation loss. Never a gate:
    bytes we cannot read pass through to fail where they did before.
    """
    if not data:
        return data
    try:
        import io

        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(data)) as im:
            turned = (im.getexif() or {}).get(274, 1) not in (1, None)
            oversized = max(im.size) > VISION_MAX_EDGE
            if not (turned or oversized):
                return data
            fixed = ImageOps.exif_transpose(im) if turned else im
            if oversized:
                fixed.thumbnail((VISION_MAX_EDGE, VISION_MAX_EDGE),
                                Image.LANCZOS)
            out = io.BytesIO()
            fixed.convert("RGB").save(out, format="JPEG", quality=88,
                                      optimize=True)
            return out.getvalue()
    except Exception:
        return data


def enhance(system: str, user: str, images=None, *, gemini_client,
            resolve_photo=None, model: Optional[str] = None,
            references: str = "") -> str:
    """The Gemini 2.5 Flash enhance call: system + user prompt plus
    optional reference images as vision input -- the same
    generate_with_retry path director.py and shootgen.py already use.
    An empty system falls back to the prompt-enhancement instruction
    (prompts/enhance_system.txt via workflows._enhance_system_text), so
    a bare user prompt is still ENHANCED with vivid detail rather than
    echoed to an uninstructed model. `references` is the optional RAG
    grounding block (the Ground node's output) folded in as its own
    labelled section -- grounding material, not the instruction.
    Raises on an empty prompt or a dead model: here the model call IS
    the deliverable, the promptgen contract."""
    from google.genai import types

    from .gemini_utils import generate_with_retry


    system = (system or "").strip()
    user = (user or "").strip()
    references = (references or "").strip()
    if not (system or user or references):
        raise ValueError("nothing to enhance — connect or type a prompt first")
    if not system:
        system = workflows._enhance_system_text()
    blocks = [system]
    if references:
        blocks.append("REFERENCES — ground the prompt in these:\n" + references)
    if user:
        blocks.append(user)
    text = "\n\n".join(blocks)
    parts = []
    for image in images or []:
        # every reference the same way, local file or public URL -- the
        # model must SEE it. Naming a URL in the text (what this did
        # before) tells a model that cannot fetch URLs that one exists,
        # which is indistinguishable from no reference at all.
        data = image_bytes_for_gemini(image, resolve_photo=resolve_photo)
        if data:
            # caption first, image second -- the binding between a photo
            # and the name the prompt uses for it
            label = (shootgen.reference_label(image)
                     if isinstance(image, str) else "")
            if label:
                parts.append(label)
            parts.append(types.Part.from_bytes(
                data=data, mime_type=sniff_mime(data)))
        elif isinstance(image, str) and image.startswith(("http://", "https://")):
            # unreachable (private host, too big, dead link): say so,
            # rather than pretending the reference landed
            text += f"\nReference image (could not be loaded): {image}"
    parts.append(text)
    return generate_with_retry(gemini_client, model or shootgen.MODEL, parts,
                               stage="enhance")

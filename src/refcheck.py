"""Somebody has to LOOK at the picture (2026-09-24).

The most valuable check this project ever ran was opening three banked
images by hand and finding YouTube monetisation thumbnails behind a Zero
Page scene (scout_bin_images.md). Every automatic guard passed: the
fetch checks size, host and format, and `bank_reference` stores a
source_url it never resolves. Nothing has ever asked what is IN the
frame — so "verify by running it" is not enough for a step whose output
is an image. This module is that missing look, in code.

It does two jobs in one call per batch:

- **The clean-frame floor**, which is not taste and is not negotiable:
  watermarks, subtitles, player chrome, channel logos, big text overlays,
  collages, screenshots. invideo's Referencer carries the same rule as a
  sacred invariant, and it is what a poisoned thumbnail always trips.
  A flag in HARD_FLAGS rejects the frame whatever the model concluded —
  prompts request, code enforces (and here code only ever enforces
  DOWNWARDS: it can reject, never keep).
- **The judgement**: does this frame show what the need asked for, in
  this brand's look, and does it hit an anti-reference.

It never raises, and it is deliberately honest about not having run:
`checked` False means no client, no key or a failed call, and the
CALLER decides what that means. `scout.illustrate`'s old behaviour (bank
it anyway) and a new hunt that refuses to bank unchecked frames are both
reasonable, and they are not this module's decision to make.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PROMPT_PATH = PROMPTS_DIR / "refcheck.txt"

# What the model is allowed to say about a frame.
FLAGS = (
    "watermark", "subtitles", "player_ui", "logo", "text_overlay",
    "collage", "screenshot", "recognisable_person", "stock_gloss",
    "low_quality", "wrong_subject", "wrong_look",
)

# The clean-frame floor. Any of these and the frame is out, whatever the
# model's own verdict said -- a reference carries its defects into the
# render, and a subtitle burned into refs[0] is a subtitle in the clip.
HARD_FLAGS = ("watermark", "subtitles", "player_ui", "logo",
              "text_overlay", "collage", "screenshot")

MAX_BATCH = 6          # a contact sheet's worth per call
MAX_CAPTION = 160


def build_prompt(need: Optional[dict] = None, *, look: str = "", anti=(),
                 count: int = 1) -> str:
    need = need or {}
    template = PROMPT_PATH.read_text()
    anti_block = "\n".join(f"- {line}" for line in anti) or "- (none given)"
    return template.format(
        count=count,
        role=need.get("role") or "mood",
        want=need.get("want") or need.get("query") or "a frame for this scene",
        query=need.get("query") or "",
        look=(look or "").strip() or "(no look file for this brand)",
        anti=anti_block,
        flags=", ".join(FLAGS),
        hard=", ".join(HARD_FLAGS),
    )


def parse(answer: str, ids) -> dict:
    """Model JSON -> {id: verdict}, closed over the ids we sent.

    An id nobody issued is dropped rather than trusted: the same closed
    set rule `imagesearch.get` enforces for candidates, for the same
    reason -- a model recalling an id is indistinguishable from a model
    reading one.
    """
    import json

    from .gemini_utils import strip_fences

    try:
        data = json.loads(strip_fences(answer or ""))
    except Exception:
        return {}
    rows = data.get("frames") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {}
    known = {str(i) for i in ids}
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id", "")).strip()
        if rid not in known:
            continue
        flags = [f for f in (row.get("flags") or []) if f in FLAGS]
        keep = bool(row.get("keep"))
        why = " ".join(str(row.get("why", "")).split())[:MAX_CAPTION]
        hard = [f for f in flags if f in HARD_FLAGS]
        if hard:
            # The override, and the reason it is recorded rather than
            # silent: a card that says "rejected" with no cause is a
            # card nobody can argue with.
            keep = False
            why = f"{', '.join(hard)} — not a clean frame" + (f"; {why}" if why else "")
        out[rid] = {
            "id": rid,
            "keep": keep,
            "flags": flags,
            "why": why,
            "caption": " ".join(str(row.get("caption", "")).split())[:MAX_CAPTION],
        }
    return out


def _text(value) -> str:
    """`gemini_utils.generate_with_retry` returns the answer TEXT unless
    raw=True; a response object only comes back from the raw path. Both
    shapes are accepted here because reading `.text` off a string is the
    silent empty-answer bug this cost once already."""
    if isinstance(value, str):
        return value
    return getattr(value, "text", "") or ""


def _unjudged(cid: str, note: str = "not judged") -> dict:
    return {"id": str(cid), "keep": False, "flags": [], "why": note, "caption": ""}


def check(images, need: Optional[dict] = None, *, brand: str = "",
          look: str = "", anti=None, client=None, model: str = "",
          account_id=None) -> dict:
    """Look at up to a contact sheet's worth of frames.

    `images` are {"id", "bytes", "mime"} — already fetched, because the
    fetch has its own guards (refbin) and this module should be testable
    without one. Returns {"ok", "checked", "verdicts", "note"}.
    """
    images = [i for i in (images or []) if i.get("bytes")]
    if not images:
        return {"ok": False, "checked": False, "verdicts": [],
                "note": "no image bytes to look at"}
    if anti is None:
        from . import reference_needs
        anti = reference_needs.anti_references(brand)
    if not look:
        try:
            from . import looks
            look = looks.look_block(brand)
        except Exception:
            look = ""
    if client is None:
        try:
            from . import gemini_utils
            client = gemini_utils.client_for(account_id)
        except Exception as e:
            return {"ok": False, "checked": False,
                    "verdicts": [_unjudged(i["id"], "no model client") for i in images],
                    "note": f"no model client: {e}"}
    if not model:
        from . import gemini_utils
        model = gemini_utils.FAST_MODEL

    from google.genai import types

    from . import gemini_utils

    verdicts, failures = [], 0
    for start in range(0, len(images), MAX_BATCH):
        batch = images[start:start + MAX_BATCH]
        parts = []
        for image in batch:
            # id first, image second: the binding between a frame and the
            # name the answer must use for it (imagery.enhance's pattern).
            parts.append(f"FRAME {image['id']}")
            parts.append(types.Part.from_bytes(
                data=image["bytes"],
                mime_type=image.get("mime") or gemini_utils.sniff_mime(image["bytes"])))
        parts.append(build_prompt(need, look=look, anti=anti, count=len(batch)))
        try:
            resp = gemini_utils.generate_with_retry(
                client, model, parts, stage="reference_check",
                account_id=account_id)
            judged = parse(_text(resp), [i["id"] for i in batch])
        except Exception:
            judged, failures = {}, failures + 1
        for image in batch:
            verdicts.append(judged.get(str(image["id"]))
                            or _unjudged(image["id"]))
    kept = [v for v in verdicts if v["keep"]]
    checked = failures == 0
    return {
        "ok": bool(kept),
        "checked": checked,
        "verdicts": verdicts,
        "note": (f"{len(kept)} of {len(verdicts)} frame(s) kept"
                 if checked else
                 f"{failures} batch(es) could not be looked at; kept {len(kept)}"),
    }


def screen(candidates, need: Optional[dict] = None, *, brand: str = "",
           fetch=None, **kwargs) -> dict:
    """Search candidates in, keepers out, with a look at each one.

    The tie-in for a hunt: `imagesearch.search` hands back candidates
    carrying ids and URLs, this fetches the bytes, checks them, and
    returns the survivors with their verdict attached (`kept_for` is the
    caption the card shows, and the per-reference note their Referencer
    stores and this repo has only ever had globally).
    """
    candidates = list(candidates or [])
    if not candidates:
        return {"ok": False, "checked": False, "keepers": [], "rejected": [],
                "note": "nothing to screen"}
    if fetch is None:
        from .imagery import fetch_image_bytes as fetch
    images = []
    for c in candidates:
        cid = str(c.get("id") or c.get("image_url") or "")
        try:
            data = fetch(c.get("image_url") or "")
        except Exception:
            data = None
        if data:
            images.append({"id": cid, "bytes": data})
    if not images:
        return {"ok": False, "checked": False, "keepers": [], "rejected": [],
                "note": "no candidate image could be fetched"}
    result = check(images, need, brand=brand, **kwargs)
    by_id = {v["id"]: v for v in result["verdicts"]}
    keepers, rejected = [], []
    for c in candidates:
        cid = str(c.get("id") or c.get("image_url") or "")
        verdict = by_id.get(cid)
        if not verdict:
            rejected.append({**c, "why": "not fetched"})
            continue
        row = {**c, "why": verdict["why"], "flags": verdict["flags"],
               "kept_for": verdict["caption"],
               "role": (need or {}).get("role", "")}
        (keepers if verdict["keep"] else rejected).append(row)
    return {"ok": bool(keepers), "checked": result["checked"],
            "keepers": keepers, "rejected": rejected, "note": result["note"]}

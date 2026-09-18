"""The reference sheet an element is drawn with (2026-09-18, Mike's call:
"build the in-app version, and this is part of the process when adding a
new element").

An element -- a character, a prop, a place -- is saved from the photos
Mike uploads, and until today that was all it had: the frames a shot is
held to were exactly those photos. This module draws ONE sheet per
element on top of them, the shape Higgsfield's character sheet has:
five panels for a person (face close-up, front, back, left, right, an
info block), a turnaround for a prop, plates for a place. The prompt
per kind is plain text in prompts/element_sheet_<kind>.txt, the
highest-frequency edit surface in this repo.

Three rules, all deliberate:

- **The real photos stay first.** The sheet is a DERIVATIVE of the
  face, never evidence of it, and keyframes have drifted to a
  stranger before when the anchor was a drawing (see likeness.md). So
  the sheet is saved under SHEET_STEM and `app/api._photo_names` sorts
  it LAST -- it rides into a render behind the uploads, never as
  `refs[0]`.
- **It spends, so it is a job and it is opt-in per element.** Cents on
  Nano Banana Pro under NANO_DAILY_CAP, through the same
  `nano_banana.generate_from_prompt` every keyframe uses (caps, the
  generations row, the meter, R2), with `literal=True` because a sheet
  is not a video prompt and `bank=False` because a sheet lives with
  its element, not on the Assets wall.
- **It never raises.** A sheet that fails leaves the element exactly as
  it was saved, with a note; the photos and the row are the deliverable,
  the sheet is an enhancement.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

SHEET_STEM = "sheet"          # <element folder>/sheet.jpg
SHEET_ASPECT = "16:9"         # four or five panels side by side
KINDS = ("character", "prop", "location")
MAX_REFERENCES = 6            # every upload after the sixth adds cost, not likeness


def is_sheet(filename: str) -> bool:
    return Path(filename).stem.lower() == SHEET_STEM


def prompt_for(kind: str, name: str, detail: str = "", notes: str = "") -> str:
    """The sheet prompt for one element, filled from its row."""
    if kind not in KINDS:
        raise ValueError(f"no sheet for kind {kind!r}")
    template = (PROMPTS_DIR / f"element_sheet_{kind}.txt").read_text()
    detail = (detail or "").strip()
    notes = (notes or "").strip()
    return template.format(
        name=name.strip(),
        name_upper=name.strip().upper(),
        detail_line=f", {detail}" if detail else "",
        detail_upper=detail.upper() if detail else "—",
        wardrobe=notes or "as in the attached photos.",
    ).strip()


def _to_jpeg(data: bytes) -> bytes:
    """The sheet lands as a JPEG like every other element photo, so the
    R2 mirror's content type and the thumbnail pass stay one rule."""
    try:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            out = io.BytesIO()
            im.convert("RGB").save(out, format="JPEG", quality=92)
            return out.getvalue()
    except Exception:
        return data


def draw(kind: str, name: str, photos: list, out_dir: Path, *,
         detail: str = "", notes: str = "",
         account_id: Optional[int] = None, db_path=None) -> dict:
    """Draw the sheet from the element's real photos into out_dir.

    Never raises: {"ok", "path", "generation_id", "error"}. `photos` are
    the uploads on disk (the sheet itself is skipped if it is among
    them, so redrawing never grounds on the last drawing).
    """
    from . import nano_banana
    try:
        refs = []
        for i, photo in enumerate(photos):
            photo = Path(photo)
            if is_sheet(photo.name) or not photo.is_file():
                continue
            refs.append((f"{name} — photo {len(refs) + 1}", photo.read_bytes()))
            if len(refs) >= MAX_REFERENCES:
                break
        if not refs:
            return {"ok": False, "path": None, "generation_id": None,
                    "error": "no photos to draw the sheet from"}
        result = nano_banana.generate_from_prompt(
            prompt_for(kind, name, detail, notes),
            reference_image=refs, aspect_ratio=SHEET_ASPECT,
            image_size=nano_banana.IMAGE_SIZE or "2K",
            account_id=account_id, db_path=db_path,
            literal=True, bank=False, source="element_sheet")
        if not result.get("ok"):
            return {"ok": False, "path": None, "generation_id": None,
                    "error": result.get("error") or "the sheet did not render"}
        rendered = Path(result["path"])
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{SHEET_STEM}.jpg"
        target.write_bytes(_to_jpeg(rendered.read_bytes()))
        return {"ok": True, "path": target,
                "generation_id": result.get("generation_id"), "error": None}
    except Exception as e:
        return {"ok": False, "path": None, "generation_id": None, "error": str(e)}

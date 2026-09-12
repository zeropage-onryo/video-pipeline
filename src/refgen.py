"""Generated references: a still rendered IN THE LOOK for a spark.

Mike, 2026-09-06: the web lanes return real photographs of real streets;
a spark set in a flooded mall or a company town has nothing on the
internet that looks like it. So the reference for an invented world is
rendered from the spark's own hook frame plus the brand's look block --
Midjourney first (his call), Gemini's image model as the fallback that
needs no extra key and no per-run approval, Higgsfield Soul last.

ONE STILL PER SPARK, CAPPED. `render_for_finding` is the only entry:
it renders once, normalises through refbin like every other reference,
and banks the result on the finding's OWN pass (gen-<id>, read ahead of
the crawl pass by scout.bin_for_finding) with lane="generated" so
`spark_images` shows the credit ("generated: midjourney") and nothing
downstream has to know it was not fetched. The cap is counted from
those rows (REFGEN_DAILY_CAP, default 8 across both brands) so no new
table and no new counter; a night that renders eight and stops is the
designed behaviour.

MIDJOURNEY'S OWN GATE STILL HOLDS. midjourney.generate_image refuses
without MIDJOURNEY_SPEND_OK=1 and ACEDATA_API_KEY -- that gate was
built so every AceData credit is an explicit approval, and this does
not go around it. run_morning_prompts.sh exports it for the night if
Mike wants the night to spend there; without it, this falls straight
to Gemini and says so in the note.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import db, looks, refbin, scout

DAILY_CAP = int(os.environ.get("REFGEN_DAILY_CAP", "8"))
PROVIDERS = ("midjourney", "nano", "higgsfield")

# THE LIKENESS PATH (2026-09-06, Mike: "This isn't what I look like").
# What reproduces his face is Nano Banana Pro handed his REAL PHOTOS as
# reference parts -- three angles out of characters/michael -- with a
# prompt that opens by saying the attached man is the subject. Nothing
# else has passed the test: the trained Soul ("Mike Antihero v2") on Soul
# Cinema and Soul V2 rendered a different actor (thick mustache,
# pompadour), an Element hint inside Nano put his mustache on somebody
# else, and Midjourney has no reference of him at all. So a still with
# Michael in it goes to nano WITH these photos, first and only-by-default;
# the Soul path stays callable but is no longer where his face comes from.
LIKENESS_SLUG = "michael"
LIKENESS_PHOTOS = tuple(p.strip() for p in os.environ.get(
    # 2026-09-07: the old default (IMG_0586/0593/0599) was three wide,
    # full-body shots where his face is a small fraction of the frame --
    # AND all three happen to have him in the moto jacket, so identity lock
    # was drifting to a generic archetype AND dragging the jacket into every
    # scene regardless of what it called for. 07 is an actual tight
    # headshot; 08 is a clear front angle in a plain shirt, no jacket.
    "LIKENESS_PHOTOS",
    "07-headshot-frontal-neutral.jpg,08-frontal-indoor-seated.jpg,IMG_0593.JPG",
).split(",") if p.strip())
LIKENESS_MODEL = os.environ.get("NANO_LIKENESS_MODEL", "gemini-3-pro-image-preview")
LIKENESS_OPENER = (
    "This is the same man as in the attached reference photos: reproduce his "
    "face exactly -- same features, skin, hair, brows, and his even light "
    "stubble across the whole jaw and upper lip. He does NOT have a grown or "
    "shaped mustache -- do not add one. Do not default to any particular "
    "jacket or outfit from the reference photos unless the scene text below "
    "specifically calls for it. New scene, new framing, new light, new "
    "wardrobe: do not copy the photos' backgrounds, poses, or clothing. ")


def enabled() -> bool:
    return (os.environ.get("REFGEN_LANE", "1") or "").strip().lower() not in ("", "0", "no", "off", "false")


def provider_order(identity: bool = False) -> tuple:
    """Midjourney first (Mike's call) -- EXCEPT when the still has to be
    Michael: then nano leads, because nano is the one renderer that can
    be handed his real photos (see LIKENESS_PHOTOS). Midjourney has no
    reference of his face to hold and the Soul path rendered someone
    else, so both fall to the back for him -- still reachable if nano
    fails, never the first answer. REFGEN_PROVIDERS overrides the base
    order."""
    chosen = [p.strip() for p in (os.environ.get("REFGEN_PROVIDERS") or "").split(",") if p.strip()]
    order = tuple(p for p in chosen if p in PROVIDERS) or PROVIDERS
    if identity and "nano" in order:
        order = ("nano",) + tuple(p for p in order if p != "nano")
    return order


def identity_references() -> list:
    """Michael's face photos as (label, jpeg bytes) pairs for nano's
    reference parts -- LIKENESS_PHOTOS out of characters/michael, each
    normalised through refbin (HEIC and EXIF rotation included). Missing
    files are skipped, so a deployment without his photos renders from
    the text line alone and the caller can say so. Never raises."""
    try:
        from . import asset_shelf
        on_disk = {p.name.lower(): p for p in asset_shelf.photos_for("character", LIKENESS_SLUG)}
    except Exception:
        return []
    out = []
    for i, name in enumerate(LIKENESS_PHOTOS, 1):
        path = on_disk.get(name.lower())
        if path is None:
            continue
        try:
            jpeg = refbin.to_jpeg(path.read_bytes())
        except Exception:
            jpeg = None
        if jpeg:
            out.append((f"Reference photo {i} of Michael", jpeg))
    return out


def is_identity(hook_frame: str, brand: str) -> bool:
    return brand == "antihero" and "michael" in (hook_frame or "").lower()


def rendered_today(dsn=None) -> int:
    """Generated references banked since UTC midnight, both brands."""
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    try:
        with db.connect(dsn) as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM scout_bin WHERE lane = 'generated' AND created_at >= %s",
                (since,)).fetchone()[0])
    except Exception:
        return 0


def build_prompt(hook_frame: str, brand: str) -> str:
    """The hook frame is the subject; the look block is the grade. Kept
    short and concrete because a still model reads the first clause
    hardest, and Midjourney parameters go last."""
    terms = look_terms(brand)
    framing = ""
    if brand == "antihero" and "michael" in hook_frame.lower():
        # His call, 2026-09-06: a face at 50px is a stranger. The world goes
        # behind him, not around him, whenever he is the subject.
        framing = (" Medium shot or closer on Michael, his face at least a "
                   "third of the frame height, sharp and clearly lit.")
    opener = LIKENESS_OPENER if is_identity(hook_frame, brand) else ""
    return (opener + f"{hook_frame.strip().rstrip('.')}. "
            + " ".join(terms) + framing
            + " Cinematic film still, vertical 9:16, photorealistic, no text, no logo.")


# LIKENESS is read too (2026-09-06): the antihero look carries Michael's
# feature line, and every generated reference with him in it must say it --
# the zeropage look has no such entry, so nothing is appended there.
KEYS = ("GRADE", "AIR", "GROUND", "LENS", "FINISH", "LIKENESS")


def look_terms(brand: str) -> list[str]:
    """The look file's GRADE/AIR/GROUND/LENS/FINISH entries, each with its
    wrapped continuation lines joined -- the file is written for a model
    to read, two-space-indented, so an entry runs until the next key."""
    out, current = {}, None
    for raw in looks.look_block(brand).splitlines():
        line = raw.strip()
        if not line:
            continue
        key = line.split(" ", 1)[0]
        if key in KEYS:
            current = key
            out[key] = line.split(None, 1)[1].strip() if " " in line else ""
        elif key.isupper() and key.isalpha():
            current = None                      # SCALE / CAST / a heading
        elif current:
            out[current] = f"{out[current]} {line}".strip()
    return [out[k].rstrip(".") + "." for k in KEYS if out.get(k)]


def _midjourney(prompt: str, out: Path) -> Path:
    from . import midjourney
    return midjourney.generate_image(prompt + " --ar 9:16 --style raw --s 150", out)


def _nano(prompt: str, out: Path, identity: bool = False) -> Path:
    from . import nano_banana
    if not nano_banana.has_key():
        raise RuntimeError("no GEMINI_API_KEY")
    if not identity:
        return nano_banana.generate_image(prompt, out, aspect_ratio="9:16")
    refs = identity_references()
    if not refs:
        raise RuntimeError(
            f"no likeness photos found in characters/{LIKENESS_SLUG} "
            f"({', '.join(LIKENESS_PHOTOS)}) -- a still of Michael without "
            f"them is a stranger")
    return nano_banana.generate_image(prompt, out, model=LIKENESS_MODEL,
                                      reference_bytes=refs, aspect_ratio="9:16")


def _higgsfield(prompt: str, out: Path) -> Path:
    from . import higgsfield
    return higgsfield.generate_image(prompt, out, aspect_ratio="9:16")


_RENDERERS = {"midjourney": _midjourney, "nano": _nano, "higgsfield": _higgsfield}


def render(prompt: str, identity: bool = False) -> dict:
    """Try the providers in order; first image wins. Never raises.
    Returns {"path", "provider", "tried": [(provider, error), ...]}."""
    tried = []
    for name in provider_order(identity):
        out = Path(tempfile.mkdtemp(prefix="refgen-")) / f"{name}.jpg"
        try:
            if name == "nano":
                _RENDERERS[name](prompt, out, identity)
            else:
                _RENDERERS[name](prompt, out)
            if out.is_file() and out.stat().st_size > 0:
                return {"path": out, "provider": name, "tried": tried}
            tried.append((name, "no file"))
        except Exception as e:                       # noqa: BLE001
            tried.append((name, f"{type(e).__name__}: {str(e)[:120]}"))
    return {"path": None, "provider": "", "tried": tried}


def render_for_finding(finding_id: int, hook_frame: str, dsn=None,
                       cap: int = DAILY_CAP) -> dict:
    """One generated reference for one spark. The public contract for
    both the MCP tool and the crawl."""
    if not enabled():
        return {"ok": False, "note": "generated references are off (REFGEN_LANE=0)"}
    finding = scout.get_finding(int(finding_id), dsn=dsn)
    if finding is None:
        return {"ok": False, "note": f"no finding {finding_id}"}
    if not (hook_frame or "").strip():
        return {"ok": False, "note": "a hook frame is required -- what is on screen in frame one"}
    used = rendered_today(dsn=dsn)
    if used >= cap:
        return {"ok": False, "note": f"generated-reference cap reached ({used}/{cap} today, REFGEN_DAILY_CAP)"}
    pass_id = scout.generated_pass_id(finding_id)   # its own bin, read first
    prompt = build_prompt(hook_frame, finding["brand"])
    result = render(prompt, identity=is_identity(hook_frame, finding["brand"]))
    if not result["path"]:
        why = "; ".join(f"{p}: {e}" for p, e in result["tried"]) or "no provider configured"
        return {"ok": False, "note": f"nothing rendered -- {why}", "prompt": prompt}
    jpeg = refbin.to_jpeg(Path(result["path"]).read_bytes())
    stored = refbin.save(jpeg) if jpeg else None
    if not stored:
        return {"ok": False, "note": "render could not be normalised to JPEG", "prompt": prompt}
    row = scout.bin_add(finding["brand"], pass_id, stored,
                        source_url=f"generated://{result['provider']}/{Path(stored).stem}",
                        title=f"generated: {result['provider']} -- {hook_frame.strip()[:140]}",
                        lane="generated", dsn=dsn)
    if row is None:
        return {"ok": False, "note": "the pass is full or the write failed", "prompt": prompt}
    print(f"refgen: {result['provider']} rendered a reference for finding {finding_id}",
          file=sys.stderr)
    return {"ok": True, "finding_id": int(finding_id), "pass_id": pass_id,
            "provider": result["provider"], "url": stored, "prompt": prompt,
            "fell_back_from": [p for p, _ in result["tried"]],
            "rendered_today": used + 1, "cap": cap}

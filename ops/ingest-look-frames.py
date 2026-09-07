#!/usr/bin/env python3
"""File the reference-look stills into the frame bank, per brand.

    venv/bin/python ops/ingest-look-frames.py            # docs/reference-look/sref
    venv/bin/python ops/ingest-look-frames.py --dir X    # any folder of stills

WHY. The frame bank (ops/build-frame-bank.py) is Michael's garage footage:
daylight, gloved hands, engine detail. It grounds Antihero on his real
textures but says nothing about the LOOK he handed over on 2026-09-04
(teal/amber, one red, wet, hazed), and it gives Zero Page nothing at all.
The six frames in docs/reference-look/sref ARE the look. Filing them as
frames rows -- moto_* under antihero, horror_* under zeropage -- makes
`images_for("teal fog wet asphalt red neon")` return the actual reference
instead of a teal towel, for either brand, and lets the research agent
bank them behind a spark so Runway anchors on them.

Captions come from Gemini like every other frame, then the look tags are
added so the words in prompts/look_<brand>.txt find these first. Any
folder works: drop more stills in, name them moto_* or horror_* (or pass
--brand), re-run. Idempotent: same file, same row.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = PROJECT_ROOT / "docs" / "reference-look" / "sref"
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
LOOK_TAGS = {
    "antihero": ["reference look", "teal", "cyan", "amber", "sodium", "tungsten",
                 "red neon", "fog", "haze", "wet asphalt", "reflections",
                 "night", "anamorphic", "glossy", "superbike", "rider"],
    "zeropage": ["reference look", "blue hour", "teal", "amber window",
                 "red light", "drizzle", "rain", "wet street", "glass",
                 "night", "suburban", "horror", "face", "cinematic"],
}


def brand_for(name: str, fallback: str) -> str:
    n = name.lower()
    if n.startswith("moto") or n.startswith("antihero"):
        return "antihero"
    if n.startswith("horror") or n.startswith("zeropage") or n.startswith("zp"):
        return "zeropage"
    return fallback


def main(argv=None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--brand", default="", help="override the filename rule")
    ap.add_argument("--no-captions", action="store_true")
    args = ap.parse_args(argv)

    from src import framebank
    files = sorted(p for p in Path(args.dir).iterdir() if p.suffix.lower() in SUFFIXES)
    if not files:
        print(f"no stills in {args.dir}", file=sys.stderr)
        return 1

    client = None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    if not args.no_captions and os.environ.get("GEMINI_API_KEY"):
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    framebank.FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for src in files:
        clip = f"reference-look/{src.name}"
        fid = framebank.frame_id(clip, 0.0)
        dest = framebank.FRAMES_DIR / f"{fid}.jpg"
        if not dest.is_file():
            shutil.copyfile(src, dest)
        frames.append({"id": fid, "clip": clip, "t_sec": 0.0, "path": str(dest),
                       "brand": args.brand or brand_for(src.name, "zeropage")})

    captioned = (framebank.caption(frames, client, model) if client
                 else [{**f, "caption": f"reference look still {f['clip']}", "tags": []} for f in frames])
    for f in captioned:
        tags = [t for t in (f.get("tags") or []) if t.lower() != "unusable"]
        f["tags"] = tags + LOOK_TAGS[f["brand"]]
        f["caption"] = (f.get("caption") or f"reference look still {f['clip']}") + \
            f" (Michael's reference look, {f['brand']})"
        framebank.record(f, brand=f["brand"])
        print(f"{f['brand']:9s} {f['clip']}: {f['caption'][:90]}")
    print(f"filed {len(captioned)} look still(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

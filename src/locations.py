#!/usr/bin/env python3
"""
Describe the spaces you can shoot in.

`locations/<name>/*.jpg` -- a directory per space, photographed from
whatever angles matter. Each space's photos go to Gemini vision and
come back as a structured description: geometry, light sources,
textures, workable camera positions, and what the space won't let you
do. That description is what grounds generated concepts in real rooms
instead of imagined ones.

Same shape as ingest.py's per-clip vision step, and incremental for
the same reason: a space already described is skipped unless you ask
for it again with --force.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

from . import preprod
from .db import DB_PATH, init_db
from .gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCATIONS_DIR = PROJECT_ROOT / "locations"

VISION_MODEL = "gemini-3-flash-preview"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

MIME_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".heic": "image/heic", ".webp": "image/webp",
}


def find_location_dirs(root: Path) -> list:
    """
    [(name, [photo paths])] for each non-empty subdirectory, sorted.
    A directory with no images isn't a location yet, so it's skipped
    rather than saved as an empty one.
    """
    root = Path(root)
    if not root.is_dir():
        return []

    found = []
    for space in sorted(p for p in root.iterdir() if p.is_dir()):
        photos = sorted(
            p for p in space.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        )
        if photos:
            found.append((space.name, photos))
    return found


def build_location_prompt(name: str, photo_count: int) -> str:
    return (
        f"These {photo_count} photo(s) are one real location available to a solo "
        f"filmmaker, referred to as \"{name}\".\n\n"
        "Describe it as a place to shoot, not as a picture. What is the geometry "
        "and how much room is there to work? What light sources are actually "
        "visible, and what would they do on camera? What textures and surfaces "
        "read well? Which specific camera positions would work in this space? "
        "What does the space make difficult or impossible?\n\n"
        "Output STRICT JSON ONLY, no markdown fences, in this exact shape:\n"
        '{"space": <one or two sentences>, "light_sources": [<string>, ...], '
        '"textures": [<string>, ...], "angles": [<workable camera position>, ...], '
        '"constraints": <what this space will not let you do>}'
    )


def parse_description(text: str) -> dict:
    """
    The testable seam. A description with no "space" is unusable for
    grounding a concept, so it's rejected here rather than stored and
    discovered later.
    """
    data = json.loads(strip_fences(text))
    if not data.get("space"):
        raise ValueError("location description is missing 'space'")
    return data


def describe_location(client, name: str, photos: list) -> dict:
    parts = [
        types.Part.from_bytes(
            data=photo.read_bytes(),
            mime_type=MIME_TYPES.get(photo.suffix.lower(), "image/jpeg"),
        )
        for photo in photos
    ]
    parts.append(build_location_prompt(name, len(photos)))
    return parse_description(generate_with_retry(client, VISION_MODEL, parts))


# --- cast & props ----------------------------------------------------------
# The same vision step, pointed at a character or a prop instead of a
# room (added 2026-08-26). It lives here rather than in entities.py so
# every vision-describe in the project shares one model, one mime map,
# and one parse seam -- entities.py stays pure DB. What it produces is
# what makes an asset *searchable*: the RAG library is text-only, so
# without a description the only thing retrievable about a character is
# whatever name and notes were typed, never how they actually look.

ENTITY_KINDS = ("character", "prop")


def build_entity_prompt(kind: str, name: str, photo_count: int) -> str:
    subject = ("a person who appears on camera" if kind == "character"
               else "an object used on camera")
    return (
        f"These {photo_count} photo(s) show {subject}, referred to as \"{name}\".\n\n"
        "Describe it for later visual reference, not as a picture. What does it "
        "look like in concrete, physical terms someone could match in another "
        "shot? What specific features would a viewer recognise it by? What "
        "colours, materials, wear, or condition are visible? What has to stay "
        "consistent from shot to shot for it to read as the same "
        f"{'person' if kind == 'character' else 'object'}?\n\n"
        "Describe only what is actually visible. Do not guess at names, brands, "
        "or backstory.\n\n"
        "Output STRICT JSON ONLY, no markdown fences, in this exact shape:\n"
        '{"look": <one or two sentences>, "features": [<recognisable detail>, ...], '
        '"materials": [<colour / fabric / material / finish>, ...], '
        '"continuity": <what must stay the same across shots>}'
    )


def parse_entity_description(text: str) -> dict:
    """Same seam as parse_description: a description with no "look" is
    useless for grounding, so it's rejected here rather than stored and
    discovered later."""
    data = json.loads(strip_fences(text))
    if not data.get("look"):
        raise ValueError("entity description is missing 'look'")
    return data


def describe_entity(client, kind: str, name: str, photos: list) -> dict:
    if kind not in ENTITY_KINDS:
        raise ValueError(f"kind must be one of {ENTITY_KINDS}, got {kind!r}")
    parts = [
        types.Part.from_bytes(
            data=Path(photo).read_bytes(),
            mime_type=MIME_TYPES.get(Path(photo).suffix.lower(), "image/jpeg"),
        )
        for photo in photos
    ]
    parts.append(build_entity_prompt(kind, name, len(photos)))
    return parse_entity_description(generate_with_retry(client, VISION_MODEL, parts))


def describe_locations(root: Path, client=None, db_path=None, force: bool = False,
        account_id: Optional[int] = None) -> dict:
    """
    Describe every space under `root` and save it. Returns counts of
    what happened. One unusable response doesn't lose the rest of the
    run -- it's reported and the other spaces still land.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    described = skipped = failed = 0

    for name, photos in find_location_dirs(root):
        if not force and preprod.get_location_by_name(name, **kwargs, account_id=account_id):
            print(f"{name}: already described, skipping")
            skipped += 1
            continue

        print(f"{name}: describing from {len(photos)} photo(s)...")
        try:
            description = describe_location(client, name, photos)
        except Exception as e:
            print(f"  failed: {e}", file=sys.stderr)
            failed += 1
            continue

        preprod.add_location(name, description, photo_count=len(photos), **kwargs)
        described += 1

    return {"described": described, "skipped": skipped, "failed": failed}


def main(db_path=None):
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Describe the spaces in locations/ so concepts can be grounded in them."
    )
    parser.add_argument("--locations-dir", default=LOCATIONS_DIR, type=Path)
    parser.add_argument("--force", action="store_true",
                        help="re-describe spaces that already have a description")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    path = db_path if db_path is not None else DB_PATH
    init_db(path=path)
    preprod.init(path=path)

    if not Path(args.locations_dir).is_dir():
        print(f"No locations directory at {args.locations_dir} -- create it and add "
              f"a subdirectory of photos per space.", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    result = describe_locations(args.locations_dir, client=client, db_path=path,
                                force=args.force)

    print(f"\n{result['described']} described, {result['skipped']} skipped, "
          f"{result['failed']} failed")


if __name__ == "__main__":
    main()

"""
The RAG library's `assets` shelf: every location, character, and prop
you have, as retrievable text.

The library is text-only -- `gemini-embedding-001` embeds strings and
`rag_documents` stores a `chunk` column -- so a reference photo cannot
itself be a row. What makes an asset searchable is its *description*,
which is why locations have always been described by vision on upload
and why characters and props are now too (`locations.describe_entity`).
Without that, the only retrievable thing about a character is the name
someone typed, never how they look.

One module owns the shelf so the upload path (app/api.py) and the
backfill below write byte-identical chunks under identical source keys
-- two formats on one shelf would mean re-ingesting an asset created
the other way silently duplicates it rather than replacing it.

Everything here is best-effort by the project's standing contract: the
asset's own save must never be lost because the vector store is down.
"""
from pathlib import Path
from typing import Optional

from . import db, entities, preprod, rag

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCATIONS_DIR = PROJECT_ROOT / "locations"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
PROPS_DIR = PROJECT_ROOT / "props"

DOMAIN = "assets"
KINDS = ("location", "character", "prop")

PHOTO_DIRS = {
    "location": LOCATIONS_DIR,
    "character": CHARACTERS_DIR,
    "prop": PROPS_DIR,
}

# The description keys worth putting on the shelf, in reading order.
# Locations and entities have different shapes; both flatten the same way.
DESCRIPTION_KEYS = (
    "space", "look", "light_sources", "textures", "angles", "constraints",
    "features", "materials", "continuity", "notes",
)


def source_key(kind: str, slug: str) -> str:
    """`assets/character-mike`. Stable per asset, so re-saving replaces
    that asset's chunks instead of accumulating stale copies (see
    rag.ingest_records, which deletes by source first)."""
    return f"{DOMAIN}/{kind}-{slug}"


def slugify(name: str) -> str:
    """A name becomes a directory name -- the same rule app/main.py's
    safe_space_name applies on the way in."""
    import re
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", name or "").strip().replace(" ", "-").lower()
    return cleaned.strip("-.")


def flatten_description(desc) -> str:
    """A description dict (either shape) -> one readable line. Unknown
    keys ride along after the known ones so a future vision field isn't
    silently dropped from the shelf."""
    import json as _json
    if isinstance(desc, str):
        try:
            desc = _json.loads(desc)
        except (ValueError, TypeError):
            return desc.strip()
    if not isinstance(desc, dict):
        return ""
    parts = []
    seen = set()
    for key in DESCRIPTION_KEYS:
        if key in desc:
            seen.add(key)
            value = desc[key]
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            if value:
                parts.append(f"{key.replace('_', ' ')}: {value}")
    for key, value in desc.items():
        if key in seen:
            continue
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        if value:
            parts.append(f"{key.replace('_', ' ')}: {value}")
    return " · ".join(parts)


def chunk_text(kind: str, name: str, fields: dict) -> str:
    """The exact text stored for one asset. Both writers call this."""
    lines = [f"{kind.upper()}: {name}"]
    for label, value in fields.items():
        text = flatten_description(value) if isinstance(value, dict) else (
            "" if value is None else str(value).strip())
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def ingest_one(kind: str, slug: str, name: str, fields: dict) -> dict:
    """Write one asset's chunk. Never raises -- a down store returns
    {"ok": False} so the caller can report it and move on."""
    text = chunk_text(kind, name, fields)
    try:
        conn = rag.connect()
        try:
            rag.init_store(conn)
            written = rag.ingest_records(
                [{"source": source_key(kind, slug), "text": text,
                  "domain": DOMAIN, "project": None, "source_ref": None}],
                rag.make_client(), conn,
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {"ok": True, "chunks": written, "error": None}
    except Exception as e:
        return {"ok": False, "chunks": 0, "error": str(e)}


def drop_one(kind: str, slug: str) -> None:
    """Deleting an asset drops its chunk too -- best-effort, same
    contract as the ingest above."""
    try:
        conn = rag.connect()
        try:
            rag.delete_source(conn, source_key(kind, slug))
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        pass


def photos_for(kind: str, slug: str) -> list:
    """The asset's photos on disk, newest-name-order, or []."""
    from .locations import IMAGE_EXTENSIONS
    directory = PHOTO_DIRS[kind] / slug
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)


def entity_fields(kind: str, row: dict) -> dict:
    """One character/prop row -> the labelled fields its chunk carries."""
    label = "role" if kind == "character" else "category"
    return {
        label: row.get(label) or "",
        "notes": row.get("notes") or "",
        "description": row.get("description") or {},
    }


def described(row: dict) -> bool:
    """Does this entity already carry a vision description (as opposed
    to only the notes someone typed)?"""
    desc = row.get("description") or {}
    return isinstance(desc, dict) and bool(desc.get("look"))


def backfill(db_path=None, describe: bool = False, gemini_client=None) -> dict:
    """
    Put everything already on disk onto the shelf.

    `describe=True` additionally runs the vision step on any character
    or prop that has photos but no description yet -- that is a billed
    call per asset, which is why it is opt-in and why an already
    described asset is skipped rather than re-described.

    Never raises: per-asset failures are counted and reported so one
    bad photo can't lose the rest of the run.
    """
    path = db.DB_PATH if db_path is None else db_path
    result = {"ingested": 0, "described": 0, "failed": 0,
              "skipped_no_photos": 0, "errors": []}

    def record_error(what: str, error: str) -> None:
        result["failed"] += 1
        if len(result["errors"]) < 10:
            result["errors"].append(f"{what}: {error}")

    for loc in preprod.list_locations(path=path):
        name = loc["name"]
        outcome = ingest_one("location", slugify(name), name,
                             {"description": loc.get("description") or {}})
        if outcome["ok"]:
            result["ingested"] += 1
        else:
            record_error(f"location {name}", outcome["error"])

    entity_rows = (
        [("character", r) for r in entities.list_characters(path=path)]
        + [("prop", r) for r in entities.list_props(path=path)]
    )
    for kind, row in entity_rows:
        name = row["name"]
        slug = slugify(name)
        if describe and not described(row):
            photos = photos_for(kind, slug)
            if not photos:
                result["skipped_no_photos"] += 1
            elif gemini_client is None:
                record_error(f"{kind} {name}", "no Gemini client for the vision step")
            else:
                from .locations import describe_entity
                try:
                    vision = describe_entity(gemini_client, kind, name, photos)
                    entities.set_description(kind, row["id"], vision, path=path)
                    row = {**row, "description": {**(row.get("description") or {}),
                                                  **vision}}
                    result["described"] += 1
                except Exception as e:
                    record_error(f"{kind} {name}", str(e))

        outcome = ingest_one(kind, slug, name, entity_fields(kind, row))
        if outcome["ok"]:
            result["ingested"] += 1
        else:
            record_error(f"{kind} {name}", outcome["error"])

    return result


def main(argv: Optional[list] = None) -> None:
    """`python -m src.asset_shelf [--describe]` -- the backfill from a
    terminal, the same call the Dev Studio's button makes."""
    import argparse
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Put every location, character, and prop on the RAG assets shelf.")
    parser.add_argument("--describe", action="store_true",
                        help="also run the vision step on undescribed cast/props "
                             "(one billed call each)")
    args = parser.parse_args(argv)

    client = None
    if args.describe:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            print("GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
            sys.exit(1)
        from google import genai
        client = genai.Client(api_key=api_key)

    result = backfill(describe=args.describe, gemini_client=client)
    print(f"{result['ingested']} ingested, {result['described']} described, "
          f"{result['failed']} failed, {result['skipped_no_photos']} without photos")
    for error in result["errors"]:
        print(f"  {error}", file=sys.stderr)


if __name__ == "__main__":
    main()

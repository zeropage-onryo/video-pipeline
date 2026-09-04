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

from . import entities, preprod, rag

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


def ingest_one(kind: str, slug: str, name: str, fields: dict, *,
               project: Optional[str] = None) -> dict:
    """Write one asset's chunk. Never raises -- a down store returns
    {"ok": False} so the caller can report it and move on. `project` is
    the owner's tenant slug (rag.py: the label that ranks a tenant's own
    assets first without hiding anyone's)."""
    text = chunk_text(kind, name, fields)
    try:
        conn = rag.connect()
        try:
            rag.init_store(conn)
            written = rag.ingest_records(
                [{"source": source_key(kind, slug), "text": text,
                  "domain": DOMAIN, "project": project, "source_ref": None}],
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


# The site-relative URL every reference in this pipeline travels as.
# `/characters/<slug>/photo/<file>`, `/props/...`, `/locations/...` for
# the asset bank, `/refs/<sha>.jpg` for anything the composer uploaded
# or the scout downloaded. One shape, so a photo picked by hand and a
# photo found by a crawl are indistinguishable downstream.
URL_ROOTS = {"characters": "character", "props": "prop", "locations": "location"}


def photo_url(kind: str, slug: str, filename: str) -> str:
    """The URL a photo on disk rides on. The inverse of resolve_photo."""
    plural = next(k for k, v in URL_ROOTS.items() if v == kind)
    return f"/{plural}/{slug}/photo/{filename}"


def photo_roots() -> dict:
    """The URL prefix -> directory map, by the plural names the URLs use."""
    return {plural: PHOTO_DIRS[kind] for plural, kind in URL_ROOTS.items()}


def resolve_photo(url_path: str, roots=None, refs_dir=None):
    """A reference URL -> the file on disk, or None.

    THE reason this lives in src/: the nightly graph resolves references
    at 6am with no web app running, so it cannot call app/api.py's
    version. That one now delegates here, because two implementations of
    a path-traversal guard is the shape of bug where one of them is
    weaker and nobody notices.

    Handles both shapes, and refuses anything that escapes its root --
    the URL comes off a stored shot or a crawl, so nothing has vouched
    for it. None on anything unresolvable: a reference is an
    enhancement, never a gate.

    `roots` and `refs_dir` are injectable so the WALL has one
    implementation while the directories stay the caller's: app/api.py
    passes its own `_PHOTO_ROOTS`, which is what the tests point at a
    tmp_path. Defaulting them here is what lets the graph resolve a
    reference at 6am with no app around.
    """
    from . import refbin

    roots = roots if roots is not None else photo_roots()
    refs_root = refs_dir if refs_dir is not None else refbin.REFS_DIR
    clean = (url_path or "").split("?")[0].strip("/")
    if not clean:
        return None
    parts = clean.split("/")

    # /refs/<sha>.jpg -- composer uploads and scouted research images
    if len(parts) == 2 and parts[0] == "refs":
        root = Path(refs_root).resolve()
        target = (root / parts[1]).resolve()
        if target.parent != root or not target.is_file():
            return None
        return target

    # /<characters|props|locations>/<slug>/photo/<file>
    if len(parts) != 4 or parts[2] != "photo":
        return None
    base = roots.get(parts[0])
    if base is None:
        return None
    root = Path(base).resolve()
    target = (root / parts[1] / parts[3]).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target


def catalogue(db_path=None, account_id: Optional[int] = None) -> list[dict]:
    """Every asset on file, in the shape shootgen.named_assets AND
    in_scope() read: {"category", "name", "photos", "text"}, photos as
    URLs and text as whatever notes/description asset_aliases can pull
    multi-word proper nouns out of.

    Same catalogue the Studio's media panel shows, built from src/ so
    the graph can have it too. Locations come from the locations table,
    characters and props from entities; the photos come off disk, since
    that is where they actually are -- photo_count on the row is a
    counter, not a listing. `text` mirrors app/api.py's _assets_all()
    field for field (notes/role/category, or a flattened location
    description) -- named_assets is written against that shape, and a
    catalogue that fed it a thinner one would silently lose every alias
    beyond a bare name.
    """
    from . import entities, preprod

    path = db_path
    items: list[dict] = []

    def photos(kind: str, name: str) -> list:
        slug = slugify(name)
        return [photo_url(kind, slug, f.name) for f in photos_for(kind, slug)]

    for loc in preprod.list_locations(dsn=path, account_id=account_id):
        items.append({"category": "location", "name": loc["name"],
                      "photos": photos("location", loc["name"]),
                      "text": flatten_description(
                          loc.get("description") or loc.get("description_json") or "")})
    for c in entities.list_characters(dsn=path, account_id=account_id):
        items.append({"category": "character", "name": c["name"],
                      "photos": photos("character", c["name"]),
                      "text": c.get("notes") or c.get("role") or ""})
    for pr in entities.list_props(dsn=path, account_id=account_id):
        items.append({"category": "prop", "name": pr["name"],
                      "photos": photos("prop", pr["name"]),
                      "text": pr.get("notes") or pr.get("category") or ""})
    return items


def in_scope(text: str, refs, catalogue_items: list) -> list:
    """Which assets ONE generation is allowed to ground on: named in
    `text` (a typed idea/spark, or a spark rotated in with nobody
    typing), or explicitly picked -- a photo attached via `refs`, the
    same /<kind>/<slug>/photo/... URL shape a composer click, a / pick,
    or an upload all ride on. Nothing else is offered.

    Replaces the old default everywhere a generator was shown the WHOLE
    asset bank on every single run (shootgen.cast_for's unfiltered
    entities.list_characters/list_props, generate_scene_concept's
    cast=None meaning "everything", the old picked_locations-only gate
    on rooms). A Create run now stays only as wide as the idea actually
    calls for, or as wide as what was deliberately attached to it --
    2026-09-03, Mike's call: "I want every create call to ONLY use the
    idea/spark that is written and references attached."

    Order matches shootgen.named_assets (character, then prop, then
    location, then first mention) since named() already carries that
    ordering; explicitly picked assets NOT already named are appended
    after, so a named + picked duplicate isn't listed twice and the
    anchor-priority order named() computed is never disturbed by a pick
    that agrees with it.
    """
    from . import shootgen  # local: shootgen pulls in the heavier deps

    named = shootgen.named_assets(text or "", catalogue_items)
    picked_slugs = set()
    for ref in refs or []:
        parts = str(ref).split("?")[0].strip("/").split("/")
        if len(parts) >= 2 and parts[0] in ("locations", "characters", "props"):
            picked_slugs.add(parts[1])
    if not picked_slugs:
        return named
    named_names = {a["name"] for a in named}
    picked = [a for a in catalogue_items
             if a["name"] not in named_names and slugify(a["name"]) in picked_slugs]
    return named + picked


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


def backfill(db_path=None, describe: bool = False, gemini_client=None, account_id: Optional[int] = None) -> dict:
    """
    Put everything already on disk onto the shelf.

    `describe=True` additionally runs the vision step on any character
    or prop that has photos but no description yet -- that is a billed
    call per asset, which is why it is opt-in and why an already
    described asset is skipped rather than re-described.

    Never raises: per-asset failures are counted and reported so one
    bad photo can't lose the rest of the run.
    """
    path = db_path
    result = {"ingested": 0, "described": 0, "failed": 0,
              "skipped_no_photos": 0, "errors": []}
    from . import accounts
    project = accounts.slug_of(account_id, dsn=path)

    def record_error(what: str, error: str) -> None:
        result["failed"] += 1
        if len(result["errors"]) < 10:
            result["errors"].append(f"{what}: {error}")

    for loc in preprod.list_locations(dsn=path, account_id=account_id):
        name = loc["name"]
        outcome = ingest_one("location", slugify(name), name,
                             {"description": loc.get("description") or {}},
                             project=project)
        if outcome["ok"]:
            result["ingested"] += 1
        else:
            record_error(f"location {name}", outcome["error"])

    entity_rows = (
        [("character", r) for r in entities.list_characters(dsn=path, account_id=account_id)]
        + [("prop", r) for r in entities.list_props(dsn=path, account_id=account_id)]
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
                    entities.set_description(kind, row["id"], vision, dsn=path, account_id=account_id)
                    row = {**row, "description": {**(row.get("description") or {}),
                                                  **vision}}
                    result["described"] += 1
                except Exception as e:
                    record_error(f"{kind} {name}", str(e))

        outcome = ingest_one(kind, slug, name, entity_fields(kind, row),
                             project=project)
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

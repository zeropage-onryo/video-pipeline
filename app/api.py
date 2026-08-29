"""
The JSON API behind /ui -- the ported studio.html skin. One rule from
its build spec governs everything here: every control in that UI is
backed by a working endpoint, and GET /api/capabilities is derived
from what is actually wired (key presence, store reachability), never
a static dict someone forgets to update.

Adaptations from the spec, decided 2026-08-21: the pipeline surface is
the real pre-production loop (concepts -> approve = plan a shot list,
deny = reasons + note recorded as a correction AND a RAG feedback
chunk), not the removed pitch/editgen chain. Assets are the real
grounding entities (locations, characters, props); footage ingest is a
later phase. Analytics reads the real metrics snapshots -- no daily
rollups exist yet, so no daily chart is served.
"""
import json
import os
import re
import statistics
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src import (
    asset_shelf,
    autonomy,
    autopilot,
    crag,
    db,
    entities,
    evalstore,
    inspiration,
    instagram,
    preprod,
    presets,
    rag,
    rag_eval,
    runway,
    settings,
    workflows,
    youtube,
)
from src.locations import IMAGE_EXTENSIONS

from . import jobs, workflow_runner

router = APIRouter(prefix="/api")

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
LOCATIONS_DIR = PROJECT_ROOT / "locations"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
PROPS_DIR = PROJECT_ROOT / "props"
CRAG_REWRITE_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

# The deny screen's vocabulary. An enum, not free text, so denial
# reasons aggregate instead of fragmenting into synonyms.
DENY_REASONS = (
    "wrong location", "off-tone", "character drift",
    "pacing", "retrieval missed", "too generic",
)


def _eval_k() -> int:
    """How many results the eval scores per query -- a Dev Studio
    tunable (settings -> EVAL_K env -> 5), resolved per run so a
    change takes effect on the next run, no restart."""
    return settings.eval_k(path=db.DB_PATH)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


# --- capabilities -----------------------------------------------------------

def _gemini_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _rag_reachable() -> bool:
    """A real connect, not a config guess -- localhost Postgres answers in
    single-digit ms, and 'the store is down' must gate retrieve/evals
    honestly rather than surfacing as a wall of failed fetches."""
    try:
        conn = rag.connect()
        try:
            conn.close()
        except Exception:
            pass
        return True
    except Exception:
        return False


def compute_capabilities() -> dict:
    from src import promptgen

    gemini = bool(_gemini_key())
    store = _rag_reachable()
    return {
        # per-shot polish needs the in-flight promptgen.refine_prompt to
        # have landed, plus the shelf and the key it refines with
        "polish": gemini and store and hasattr(promptgen, "refine_prompt"),
        "assets.list": True,
        "assets.create": True,
        "retrieve": store and gemini,          # query embeds with Gemini
        "pipeline.concepts": True,
        "pipeline.run": gemini,
        "pipeline.deny": True,                  # correction always lands; RAG chunk is best-effort
        "holds": True,
        "evals.golden": True,
        "evals.run": store and gemini,
        "analytics": True,
        "analytics.youtube": bool(os.environ.get("YOUTUBE_API_KEY")),
        "analytics.instagram": bool(instagram.access_token()),
        "runway.generate": runway.has_key(),
        "runway.spend": runway.spend_approved(),
        "nano.generate": gemini,               # Nano Banana rides the Gemini key
        "workflows": True,
        "jobs": True,
        # deployment posture (app/main.py's DEV_TOOLS, read live like the
        # keys above): gates /ui elements that point into the dev console,
        # e.g. the rail's "legacy" link -- on a public deployment there is
        # no /studio to link to
        "dev_tools": os.environ.get("DEV_TOOLS") == "1",
    }


@router.get("/capabilities")
def capabilities():
    return compute_capabilities()


# --- assets -----------------------------------------------------------------
# Path helpers mirror app/main.py's (photos_for / _entity_photos /
# safe_space_name); duplicated rather than imported to keep main -> api
# a one-way street.

def _slug(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip().replace(" ", "-").lower()
    return cleaned.strip("-.")


def _photo_names(base_dir: Path, folder: str) -> list:
    directory = base_dir / folder
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)


def _location_photos(space: str) -> list:
    return [f"/locations/{space}/photo/{fn}?thumb=1"
            for fn in _photo_names(LOCATIONS_DIR, space)]


def _description_text(desc) -> str:
    """locations.description_json -> one readable paragraph."""
    if isinstance(desc, str):
        try:
            desc = json.loads(desc)
        except (ValueError, TypeError):
            return desc
    if not isinstance(desc, dict):
        return ""
    parts = []
    for key in ("space", "light_sources", "textures", "angles", "constraints"):
        value = desc.get(key)
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        if value:
            parts.append(f"{key.replace('_', ' ')}: {value}")
    return " · ".join(parts)


def _assets_all() -> list:
    items = []
    for loc in preprod.list_locations(path=db.DB_PATH):
        photos = _location_photos(loc["name"])
        items.append({
            "id": f"location-{loc['id']}", "category": "location",
            "name": loc["name"], "photos": photos,
            "poster": photos[0] if photos else None,
            "text": _description_text(loc.get("description")
                                      or loc.get("description_json") or ""),
            "meta": {"photo_count": loc.get("photo_count")},
            "created_at": loc.get("created_at"),
        })
    for c in entities.list_characters(path=db.DB_PATH):
        slug = _slug(c["name"])
        photos = [f"/characters/{slug}/photo/{fn}?thumb=1"
                  for fn in _photo_names(CHARACTERS_DIR, slug)]
        items.append({
            "id": f"character-{c['id']}", "category": "character",
            "name": c["name"], "photos": photos,
            "poster": photos[0] if photos else None,
            "text": c.get("notes") or c.get("role") or "",
            "meta": {"role": c.get("role")},
            "created_at": c.get("created_at"),
        })
    for p in entities.list_props(path=db.DB_PATH):
        slug = _slug(p["name"])
        photos = [f"/props/{slug}/photo/{fn}?thumb=1"
                  for fn in _photo_names(PROPS_DIR, slug)]
        items.append({
            "id": f"prop-{p['id']}", "category": "prop",
            "name": p["name"], "photos": photos,
            "poster": photos[0] if photos else None,
            "text": p.get("notes") or p.get("category") or "",
            "meta": {"kind": p.get("category")},
            "created_at": p.get("created_at"),
        })
    return items


@router.get("/assets")
def assets_list(q: Optional[str] = None, category: Optional[str] = None,
                limit: int = 200):
    items = _assets_all()
    counts = {"all": len(items)}
    for cat in ("location", "character", "prop"):
        counts[cat] = sum(1 for i in items if i["category"] == cat)
    if category in ("location", "character", "prop"):
        items = [i for i in items if i["category"] == category]
    if q:
        needle = q.lower().strip()
        items = [i for i in items
                 if needle in (i["name"] + " " + (i["text"] or "")).lower()]
    return {"items": items[:limit], "total": len(items), "counts": counts}


@router.get("/media")
def media_list(q: Optional[str] = None, category: Optional[str] = None,
               limit: int = 500):
    """Every saved photo as one flat, newest-first list with its REAL
    file date -- what the media panel's picker grid and the Assets
    gallery group by. Dates come from the file on disk, not a guess."""
    from datetime import datetime, timezone

    items = []
    for asset in _assets_all():
        for url in asset["photos"]:
            target = _resolve_asset_photo(url)
            if target is None:
                continue
            mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)
            items.append({
                "url": url, "asset_id": asset["id"],
                "asset_name": asset["name"], "category": asset["category"],
                "haystack": (asset["name"] + " " + (asset["text"] or "")).lower(),
                "date": mtime.date().isoformat(),
                "ts": mtime.timestamp(),
            })
    items.sort(key=lambda x: x["ts"], reverse=True)
    # counts are set totals, before any filter -- same rule as /api/assets
    counts = {"all": len(items)}
    for cat in ("location", "character", "prop"):
        counts[cat] = sum(1 for i in items if i["category"] == cat)
    if category in ("location", "character", "prop"):
        items = [i for i in items if i["category"] == category]
    if q:
        needle = q.lower().strip()
        items = [i for i in items if needle in i["haystack"]]
    for item in items:
        item.pop("haystack", None)
    return {"items": items[:limit], "counts": counts}


@router.get("/assets/search")
def assets_search(q: str = "", limit: int = 8):
    """Cross-category name search over characters/props/locations -- the
    `@` mention autocomplete's endpoint. Name-prefix matches rank first,
    substring matches after; slim rows (name, category, thumb) because
    the dropdown needs nothing heavier."""
    needle = q.lower().strip()
    items = _assets_all()
    if needle:
        starts = [i for i in items if i["name"].lower().startswith(needle)]
        start_ids = {i["id"] for i in starts}
        contains = [i for i in items
                    if needle in i["name"].lower() and i["id"] not in start_ids]
        items = starts + contains
    return {"items": [{"name": i["name"], "category": i["category"],
                       "thumb": i["poster"]}
                      for i in items[:max(1, min(limit, 20))]]}


@router.get("/assets/{category}/{item_id}")
def asset_detail(category: str, item_id: int):
    asset = next((i for i in _assets_all()
                  if i["id"] == f"{category}-{item_id}"), None)
    if asset is None:
        return _error(404, "not_found", "no such asset")
    return asset


# --- asset creation ----------------------------------------------------------
# The always-on create path (2026-08-26): /ui's Assets view creates
# entities through these, so asset creation survives a public deploy
# where the dev console (and its old form routes) is never registered.
# Every save also lands a small text chunk on the RAG "assets" shelf --
# the upload IS the grounding source, closing the gap where the memory
# bank and the vector library sat side by side without talking.

ASSETS_DOMAIN = asset_shelf.DOMAIN

# The shelf's format and source keys live in src/asset_shelf.py so this
# route and the backfill there write identical chunks -- two formats on
# one shelf means a re-ingest duplicates instead of replacing.
ingest_asset_chunk = asset_shelf.ingest_one
_drop_asset_chunk = asset_shelf.drop_one


def describe_entity_photos(kind: str, name: str, photos: list) -> dict:
    """The vision step for a character or prop, mirroring what a
    location has always got on upload. This is what makes the asset
    *searchable*: the RAG library is text-only, so an undescribed
    character retrieves on its typed name alone, never on how it looks.

    Never raises -- a failed vision call must not lose the photos or
    the entity row, exactly the locations contract."""
    api_key = _gemini_key()
    if not (api_key and photos):
        return {"ok": False, "description": None,
                "error": "no photos" if api_key else "GEMINI_API_KEY not set"}
    try:
        from google import genai

        from src import locations as locations_mod
        description = locations_mod.describe_entity(
            genai.Client(api_key=api_key), kind, name, photos)
        return {"ok": True, "description": description, "error": None}
    except Exception as e:
        return {"ok": False, "description": None, "error": str(e)}


async def _save_uploaded_photos(base_dir: Path, slug: str, photos) -> tuple:
    """(first filename, count) -- mirrors the old dev-console handler."""
    images = [p for p in photos
              if getattr(p, "filename", "") and (p.content_type or "").startswith("image/")]
    if not images:
        return "", 0
    directory = base_dir / slug
    directory.mkdir(parents=True, exist_ok=True)
    for upload in images:
        (directory / Path(upload.filename).name).write_bytes(await upload.read())
    return Path(images[0].filename).name, len(images)


@router.post("/assets/locations")
async def asset_create_location(request: Request):
    """Save a space's photos and describe it (vision) -- the describe is
    best-effort so a failed model call keeps the photos on disk to
    retry, exactly the old /locations/upload contract."""
    form = await request.form()
    name = (form.get("name") or "").strip()
    slug = _slug(name)
    if not slug:
        return _error(400, "invalid_name", "a space name is required")
    photos = [p for p in form.getlist("photos") if getattr(p, "filename", "")]
    images = [p for p in photos if (p.content_type or "").startswith("image/")]
    if not images:
        return _error(400, "no_photos", "at least one photo is required")

    space_dir = LOCATIONS_DIR / slug
    space_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for upload in images:
        target = space_dir / Path(upload.filename).name
        target.write_bytes(await upload.read())
        saved.append(target)

    described = False
    note = None
    description = None
    api_key = _gemini_key()
    if not api_key:
        note = "GEMINI_API_KEY is not set, so the photos were not described"
    else:
        try:
            from google import genai

            from src import locations as locations_mod
            description = locations_mod.describe_location(
                genai.Client(api_key=api_key), slug, saved)
            all_photos = sorted(
                p for p in space_dir.iterdir()
                if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
            preprod.add_location(slug, description,
                                 photo_count=len(all_photos), path=db.DB_PATH)
            described = True
        except Exception as e:
            note = f"saved {len(saved)} photo(s) but could not describe the space: {e}"

    chunk = ingest_asset_chunk("location", slug, slug,
                               {"description": description or {}})
    return {"ok": True, "slug": slug, "described": described,
            "photos": len(saved), "note": note, "rag": chunk}


async def _create_entity(kind: str, request: Request):
    """Characters and props are the same shape: name + one labelled
    field + notes + photos. Save the photos, describe them (vision, so
    appearance is retrievable), store the row, put it on the shelf."""
    base_dir = CHARACTERS_DIR if kind == "character" else PROPS_DIR
    label = "role" if kind == "character" else "category"

    form = await request.form()
    name = (form.get("name") or "").strip()
    slug = _slug(name)
    if not slug:
        return _error(400, "invalid_name", "a name is required")
    field = (form.get(label) or "").strip()
    notes = (form.get("notes") or "").strip()
    ref, count = await _save_uploaded_photos(base_dir, slug, form.getlist("photos"))

    # resolved against THIS route's base_dir, not asset_shelf's module
    # constant -- they're the same in production, but the photos that
    # were just written are the ones to describe.
    saved_photos = [base_dir / slug / n for n in _photo_names(base_dir, slug)]
    vision = describe_entity_photos(kind, name, saved_photos)
    description = dict(vision["description"] or {})
    if notes:
        description["notes"] = notes

    add = entities.add_character if kind == "character" else entities.add_prop
    add(name=name, **{label: field},
        description=description or None,
        reference_image=ref, photo_count=count, notes=notes, path=db.DB_PATH)

    chunk = ingest_asset_chunk(kind, slug, name, {
        label: field, "notes": notes, "description": description})
    note = None if vision["ok"] else (
        f"photos saved but not described: {vision['error']}" if count
        else "no photos to describe")
    return {"ok": True, "slug": slug, "photos": count,
            "described": vision["ok"], "note": note, "rag": chunk}


@router.post("/assets/characters")
async def asset_create_character(request: Request):
    return await _create_entity("character", request)


@router.post("/assets/props")
async def asset_create_prop(request: Request):
    return await _create_entity("prop", request)


class BackfillBody(BaseModel):
    describe: bool = False


@router.post("/assets/backfill")
def assets_backfill(body: BackfillBody):
    """Put everything already on disk onto the shelf -- the catch-up for
    assets created before the shelf existed. `describe` also runs the
    vision step on undescribed cast/props: one billed call each, opt-in,
    and already-described assets are skipped rather than re-described.
    Runs as a job because a real library takes a while."""
    if body.describe and not _gemini_key():
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        client = None
        if body.describe:
            from google import genai
            client = genai.Client(api_key=_gemini_key())
        jobs.progress(job, 0.1, "walking assets")
        result = asset_shelf.backfill(db_path=db.DB_PATH, describe=body.describe,
                                      gemini_client=client)
        detail = f"{result['ingested']} on the shelf"
        if result["described"]:
            detail += f" · {result['described']} described"
        if result["failed"]:
            detail += f" · {result['failed']} failed"
        return {"detail": detail, "output": json.dumps(result)}

    job = jobs.start("backfill", "assets → rag shelf", work)
    return {"job_id": job["id"]}


@router.delete("/assets/characters/{character_id}")
def asset_delete_character(character_id: int):
    row = entities.get_character(character_id, path=db.DB_PATH)
    if row is None:
        return _error(404, "not_found", "no such character")
    entities.delete_character(character_id, path=db.DB_PATH)
    _drop_asset_chunk("character", _slug(row["name"]))
    return {"deleted": character_id}


@router.delete("/assets/props/{prop_id}")
def asset_delete_prop(prop_id: int):
    row = entities.get_prop(prop_id, path=db.DB_PATH)
    if row is None:
        return _error(404, "not_found", "no such prop")
    entities.delete_prop(prop_id, path=db.DB_PATH)
    _drop_asset_chunk("prop", _slug(row["name"]))
    return {"deleted": prop_id}


# --- retrieval --------------------------------------------------------------

class RetrieveBody(BaseModel):
    query: str
    k: int = Field(default=5, ge=1, le=20)
    domain: Optional[str] = None


@router.post("/retrieve")
def retrieve(body: RetrieveBody):
    """One endpoint serves the Studio grounding rail, the Evals probe,
    and the harness -- the same scorer everywhere, per the spec."""
    query_text = body.query.strip()
    if not query_text:
        return _error(400, "empty_query", "query text is required")
    started = time.perf_counter()
    try:
        conn = rag.connect()
        try:
            hits = rag.query(query_text, rag.make_client(), conn,
                             k=body.k, domain=body.domain or None)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        return _error(503, "retrieval_unavailable", str(e))
    return {
        "hits": hits,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model": rag.EMBED_MODEL,
    }


# --- pipeline (adapted to pre-production) -----------------------------------

def _concept_card(c: dict) -> dict:
    status = "shot" if c.get("shot_done") else (
        "planned" if c.get("has_shot_list") else "idea")
    location_names = [loc["name"] for loc in c.get("locations") or []]
    grounded = []
    for name in location_names:
        photos = _location_photos(name)
        grounded.append({"name": name,
                         "poster": photos[0] if photos else None})
    return {
        "id": c["id"], "n": f"SHOOT-{c['id']:02d}",
        "title": c.get("title"), "hook": c.get("hook"),
        "logline": c.get("logline") or c.get("hook") or "",
        "brand": c.get("brand"), "spark": c.get("spark"),
        "status": status,
        "shot_count": len(c.get("shots") or []),
        "ai_shot_count": len(c.get("ai_shots") or []),
        "warnings": c.get("warnings") or [],
        "grounded": grounded,
        "judge_overall": c.get("judge_overall"),
        "created_at": c.get("created_at"),
        # a one-shot concept IS a scene: its single prompt, the photos
        # it was written against, and whether it was picked to render
        "is_scene": c.get("is_scene", False),
        "picked": c.get("picked", False),
        "refs": c.get("refs") or [],
        "prompt": ((c.get("shots") or [{}])[0].get("prompt") or "")
                  if c.get("is_scene") else "",
        "media_url": ((c.get("shots") or [{}])[0].get("media_url") or "")
                     if c.get("is_scene") else "",
        "reference_image": ((c.get("shots") or [{}])[0].get("reference_image") or "")
                           if c.get("is_scene") else "",
    }


@router.get("/pipeline/concepts")
def pipeline_concepts(brand: Optional[str] = None, status: Optional[str] = None):
    cards = [_concept_card(c) for c in preprod.list_concepts(path=db.DB_PATH)]
    if brand in preprod.BRANDS:
        cards = [c for c in cards if c["brand"] == brand]
    if status in ("idea", "planned", "shot"):
        cards = [c for c in cards if c["status"] == status]
    return {
        "items": cards,
        "deny_reasons": list(DENY_REASONS),
        "shoot": preprod.shoot_rate(path=db.DB_PATH),
        "pick": preprod.pick_rate(path=db.DB_PATH),
    }


# --- scenes to pick between --------------------------------------------------
# One idea in, N one-shot concepts out. Not a second data model: each is
# exactly the row generate_scene_concept writes, so the scene board,
# Director, render and autopilot keep working unmodified. What is new is
# that you get SEVERAL and the pick is recorded (preprod.pick_rate).

SCENE_COUNT_MAX = 8


class ScenesRunBody(BaseModel):
    idea: str
    count: int = 4
    refs: list[str] = []       # asset photos this batch is written against
    brand: Optional[str] = None


@router.post("/scenes/run")
def scenes_run(request: Request, body: ScenesRunBody):
    """Several takes on one idea, to pick between. The references you
    attach are stored ON each scene's shot, which is what carries them
    into every node once it reaches Director."""
    idea = (body.idea or "").strip()
    if not idea:
        return _error(400, "empty_idea", "type an idea first")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    brand_raw = body.brand
    brand = brand_raw if brand_raw in preprod.BRANDS else (
        request.cookies.get("brand") if request.cookies.get("brand") in preprod.BRANDS
        else "antihero")
    count = max(1, min(SCENE_COUNT_MAX, body.count))
    refs = [r for r in body.refs if isinstance(r, str) and r][:MAX_IMAGE_REFS]

    # the same photos as bytes, so THIS call sees what it is writing for
    image_refs = []
    for picked in refs:
        target = _resolve_asset_photo(picked)
        if target is None:
            continue
        jpeg = _to_jpeg(target.read_bytes())
        if jpeg:
            image_refs.append((jpeg, "image/jpeg"))

    def work(job):
        from google import genai

        from src import shootgen

        jobs.progress(job, 0.15, "grounding in references")
        references = shootgen.reference_block(spark=idea, db_path=db.DB_PATH)
        try:
            cast = shootgen.format_cast(
                entities.list_characters(path=db.DB_PATH),
                entities.list_props(path=db.DB_PATH))
        except Exception:
            cast = None        # naming the cast is grounding, never a gate
        jobs.progress(job, 0.4, f"writing {count} scene(s)")
        result = shootgen.generate_scene_concepts(
            idea, brand, count=count,
            gemini_client=genai.Client(api_key=api_key),
            references=references, cast=cast, db_path=db.DB_PATH,
            refs=refs, image_refs=image_refs or None)
        saved = result["scenes"]
        return {"detail": f"{len(saved)} scene(s)",
                "ref_id": saved[0]["concept_id"] if saved else None}

    job = jobs.start("scenes", f"scenes · {idea[:60]}", work)
    return {"job_id": job["id"], "image_refs": len(image_refs)}


class PickBody(BaseModel):
    picked: bool = True


@router.post("/concepts/{concept_id}/pick")
def concept_pick(concept_id: int, body: PickBody):
    """The label: this scene is worth rendering."""
    try:
        preprod.set_picked(concept_id, body.picked, path=db.DB_PATH)
    except ValueError as e:
        return _error(404, "not_found", str(e))
    return {"ok": True, "picked": body.picked,
            "pick": preprod.pick_rate(path=db.DB_PATH)}


class ConceptRefsBody(BaseModel):
    refs: list[str] = []


@router.post("/concepts/{concept_id}/refs")
def concept_refs(concept_id: int, body: ConceptRefsBody):
    """The reference photos a scene grounds on -- a LIST, because a face
    and a jacket are two references. Stored on the shot itself, so they
    ride into the enhance, the keyframe and the clip."""
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None or not concept["shots"]:
        return _error(404, "not_found", "no such scene")
    shots = [dict(s) for s in concept["shots"]]
    shots[0]["refs"] = [r for r in body.refs if r][:MAX_IMAGE_REFS]
    # a plan dict, not a bare list: update_concept_shots re-validates the
    # whole plan, and carrying the existing warnings/duration through
    # keeps attaching a reference from rewriting anything else
    preprod.update_concept_shots(
        concept_id,
        {"shots": shots, "duration": concept.get("duration")},
        warnings=concept.get("warnings") or [], path=db.DB_PATH)
    return {"ok": True, "refs": shots[0]["refs"]}


@router.get("/concepts/{concept_id}")
def concept_detail(concept_id: int):
    """The scene board's data: the full shot list, each shot carrying its
    stored per-tool AI prompt plus the OpenArt Director rendering
    (pure text composition, zero model calls). This is the surface the
    plug-into-Runway loop works from: copy a shot's prompt, generate in
    the tool's own UI, paste the rendered clip's URL back onto the shot."""
    from src import shootgen

    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    # director_prompt (the OpenArt rendering) ships with in-progress
    # shootgen work; until that lands, the field is empty and the UI
    # renders no Director toggle -- degrade, don't crash.
    director = getattr(shootgen, "director_prompt", None)
    shots = []
    for shot in concept.get("shots") or []:
        shots.append({**shot,
                      "director_prompt": director(shot, concept) if director else ""})
    card = _concept_card(concept)
    return {**card, "duration": concept.get("duration"),
            "edit_note": concept.get("edit_note") or concept.get("edit"),
            "shots": shots,
            # the render button's copy is server-sourced: availability,
            # the spend gate's state, and what one clip would cost
            "runway": {"available": runway.has_key(),
                       "spend_ok": runway.spend_approved(),
                       "model": runway.DEFAULT_MODEL,
                       "estimate_usd": runway.estimate_cost(1)}}


class ShotMediaBody(BaseModel):
    url: str


@router.post("/concepts/{concept_id}/shots/{shot_n}/media")
def shot_media_attach(concept_id: int, shot_n: int, body: ShotMediaBody):
    """Attach the rendered clip's URL to one shot -- the paste-back half
    of the Runway loop, and the field autopilot.build_plan() requires
    before it will ever emit a post action."""
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        return _error(400, "invalid_url",
                      "paste the clip's public http(s) URL")
    try:
        preprod.set_shot_media_url(concept_id, shot_n, url, path=db.DB_PATH)
    except ValueError as e:
        return _error(404, "not_found", str(e))
    return {"concept_id": concept_id, "shot_n": shot_n, "media_url": url}


class DirectBody(BaseModel):
    note: str


@router.post("/concepts/{concept_id}/direct")
def concept_direct(concept_id: int, body: DirectBody):
    """Director mode: one note revises the stored scene in place --
    validated, attachments carried over, refused when the revision
    comes back broken. One billed call per note."""
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    note = body.note.strip()
    if not note:
        return _error(400, "empty_note", "an empty note directs nothing")
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return _error(404, "not_found", "no such concept")

    def work(job):
        from google import genai

        from src import director
        jobs.progress(job, 0.3, "revising the scene")
        result = director.direct_scene(
            concept_id, note, gemini_client=genai.Client(api_key=api_key),
            db_path=db.DB_PATH)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "direction failed")
        detail = result.get("summary") or "revised"
        if result.get("warnings"):
            detail += f" · {len(result['warnings'])} warning(s)"
        return {"ref_id": concept_id, "detail": detail}

    job = jobs.start("direct", f"direct · {note[:60]}", work)
    return {"job_id": job["id"]}


@router.post("/concepts/{concept_id}/shots/{shot_n}/refine")
def shot_refine(concept_id: int, shot_n: int):
    """Technique-aware polish for one shot's AI prompt, grounded in the
    ai_prompting shelf. Falls back to unchanged on anything broken."""
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return _error(404, "not_found", "no such concept")

    def work(job):
        from google import genai

        from src import director
        jobs.progress(job, 0.3, "polishing against technique references")
        result = director.refine_shot_prompt(
            concept_id, shot_n, gemini_client=genai.Client(api_key=api_key),
            db_path=db.DB_PATH)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "polish failed")
        return {"ref_id": concept_id, "detail": result.get("summary") or "polished"}

    job = jobs.start("refine", f"polish · shot {shot_n}", work)
    return {"job_id": job["id"]}


@router.post("/concepts/{concept_id}/shots/{shot_n}/generate")
def shot_generate(concept_id: int, shot_n: int):
    """One click, one render: the shot's stored prompt through the
    Runway API (anchored on its reference_image when set), the clip
    downloaded, logged as a generations row, and attached to the shot.
    Billed, capped, and spend-gated -- generate_video refuses without
    RUNWAY_SPEND_OK=1 on the server's run, so nothing here can spend
    around the module's own gate."""
    if not runway.has_key():
        return _error(503, "runway_unavailable", "RUNWAYML_API_SECRET is not set")
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return _error(404, "not_found", "no such concept")

    def work(job):
        jobs.progress(job, 0.2, "rendering via Runway")
        result = runway.generate_for_shot(concept_id, shot_n, db_path=db.DB_PATH)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "render failed")
        return {"ref_id": concept_id,
                "detail": f"clip attached to shot {shot_n}"}

    job = jobs.start("render", f"runway · {concept['title']} shot {shot_n}", work)
    return {"job_id": job["id"]}


MAX_IMAGE_REFS = 6   # cap what one Create sends to Gemini, same as /studio

_PHOTO_ROOTS = {
    "locations": LOCATIONS_DIR,
    "characters": CHARACTERS_DIR,
    "props": PROPS_DIR,
}


def _resolve_asset_photo(url_path: str) -> Optional[Path]:
    """A picked media-panel thumbnail arrives as its site-relative photo
    URL (/locations/<space>/photo/<file>, ?thumb stripped). Resolve it
    against the real photo roots with the same traversal guard the
    photo routes use -- anything that escapes is silently dropped, an
    attachment is an enhancement."""
    clean = (url_path or "").split("?")[0].strip("/")
    parts = clean.split("/")
    if len(parts) != 4 or parts[2] != "photo":
        return None
    root = _PHOTO_ROOTS.get(parts[0])
    if root is None:
        return None
    target = (root / parts[1] / parts[3]).resolve()
    if root.resolve() not in target.parents:
        return None
    if not target.is_file() or target.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    return target


MAX_VIDEO_REFS = 2   # a video ref is heavy; two is plenty of grounding

# Under this, a clip rides inline as Part.from_bytes -- the same shape
# image refs use, just a video mime. Over it, the Gemini Files API is
# the documented path (inline requests cap out around 20MB total).
INLINE_VIDEO_LIMIT = 19_000_000

VIDEO_MIMES = {
    ".mp4": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".m4v": "video/x-m4v",
}


def _video_mime(filename: str) -> Optional[str]:
    from pathlib import PurePosixPath
    return VIDEO_MIMES.get(PurePosixPath(filename or "").suffix.lower())


def video_part(client, data: bytes, mime: str):
    """One video reference -> something a Gemini call can take as vision
    input. Small clips ride inline as bytes; anything bigger goes
    through the Files API (upload, poll until ACTIVE, hand back the file
    handle -- the SDK accepts it directly in contents). None on any
    failure: a reference is an enhancement, never a gate."""
    import io
    import time as _time

    from google.genai import types

    try:
        if len(data) <= INLINE_VIDEO_LIMIT:
            return types.Part.from_bytes(data=data, mime_type=mime)
        handle = client.files.upload(file=io.BytesIO(data),
                                     config={"mime_type": mime})
        deadline = _time.time() + 120
        while getattr(handle.state, "name", str(handle.state)) == "PROCESSING" \
                and _time.time() < deadline:
            _time.sleep(2)
            handle = client.files.get(name=handle.name)
        if getattr(handle.state, "name", str(handle.state)) != "ACTIVE":
            return None
        return handle
    except Exception:
        return None


def _to_jpeg(data: bytes) -> Optional[bytes]:
    import io

    from PIL import Image
    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return None   # not a readable image -- skip, never fail the run


def scene_grounding(brand: str, spark, client=None) -> str:
    """
    Everything a scene generation grounds on, composed at the edge (the
    reference_block contract: generators stay hermetic).

    The brand's own inspiration accounts ride in front of the retrieved
    references, brand-scoped so ANTIHERO's moto/noir riffs never leak
    into Zero Page's faceless ideation. This used to live on the dev
    console's /concepts/generate; that route went with the page, and
    without it here the accounts would quietly stop steering anything.
    Both halves degrade to "" rather than failing a generation.
    """
    from src import shootgen

    references = shootgen.reference_block(spark=spark, client=client,
                                          db_path=db.DB_PATH)
    try:
        insp = inspiration.combined_grounding(brand=brand, path=db.DB_PATH)
    except Exception:
        insp = ""
    if insp:
        return insp + "\n\n" + (references or "")
    return references


@router.post("/pipeline/run")
async def pipeline_run(request: Request):
    """The Create button: one full concept from the composer's prompt,
    grounded exactly the way /concepts/generate grounds -- reference
    block first, then the generator. Multipart: `prompt` plus optional
    attached media (`files` uploads and `asset_photos` picked from the
    media panel), which ride into the generation as vision input.
    Billed, so it only exists when the key does."""
    form = await request.form()
    prompt = (form.get("prompt") or "").strip()
    if not prompt:
        return _error(400, "empty_prompt", "a prompt is required")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    brand_raw = form.get("brand")
    brand = brand_raw if brand_raw in preprod.BRANDS else (
        request.cookies.get("brand") if request.cookies.get("brand") in preprod.BRANDS
        else "antihero")

    image_refs = []
    for upload in form.getlist("files"):
        if len(image_refs) >= MAX_IMAGE_REFS:
            break
        if not getattr(upload, "filename", ""):
            continue
        jpeg = _to_jpeg(await upload.read())
        if jpeg:
            image_refs.append((jpeg, "image/jpeg"))
    for picked in form.getlist("asset_photos"):
        if len(image_refs) >= MAX_IMAGE_REFS:
            break
        target = _resolve_asset_photo(str(picked))
        if target is None:
            continue
        jpeg = _to_jpeg(target.read_bytes())
        if jpeg:
            image_refs.append((jpeg, "image/jpeg"))

    def work(job):
        from google import genai

        from src import shootgen
        gemini_client = genai.Client(api_key=api_key)
        jobs.progress(job, 0.15, "grounding in references")
        references = scene_grounding(brand, prompt, client=gemini_client)
        jobs.progress(job, 0.35,
                      "writing the scene prompt"
                      + (f" · {len(image_refs)} image ref(s)" if image_refs else ""))
        # One concept = one scene = one paste-ready prompt (2026-08-26).
        # The old idea -> shot-list split is still reachable through the
        # two-stage path; this button no longer produces it.
        result = shootgen.generate_scene_concept(
            brand=brand, spark=prompt,
            gemini_client=gemini_client,
            db_path=db.DB_PATH, references=references,
            image_refs=image_refs or None,
        )
        title = (result.get("concept") or {}).get("title") or "untitled"
        warnings = result.get("warnings") or []
        detail = f'"{title}"'
        if warnings:
            detail += f" · {len(warnings)} warning(s)"
        return {"ref_id": result.get("concept_id"), "detail": detail}

    job = jobs.start("concept", f"concept · {prompt[:60]}", work)
    return {"job_id": job["id"], "image_refs": len(image_refs)}


# --- generate tab (Higgsfield-style one-shot generation) --------------------
# One run through the same four primitives Concept uses -- Reference /
# Ground / Enhance / Generate -- for a single image or clip. The result
# is NOT a second data model: it saves as an ordinary shoot_concepts
# row with exactly one shot (or appends a shot to an existing concept),
# so teach-to-RAG, generation history, and the scene board all keep
# working unmodified.

GENERATE_OUTPUTS = ("image", "video", "prompt")


@router.get("/presets")
def presets_list():
    """The curated camera/framing scaffolds (prompts/presets.json) the
    Generate tab and Director nodes fold into the Enhance step, plus
    the enhancement instruction (prompts/enhance_system.txt) the
    Director chain seeds its Instructions node with."""
    return {"items": presets.load_presets(),
            "enhance_system": workflows._enhance_system_text()}


@router.get("/director/landing")
def director_landing(request: Request, brand: Optional[str] = None):
    """Director tab's chat-first entry: a real pre-filled sample brief
    (the gold-standard exemplar, shortened to its style + action blocks)
    plus quick-start chips. Zero Page's chips are its real format
    skeletons (ZEROPAGE_FORMATS); Antihero has no equivalent fixed list
    yet, so it leads with the sample composer alone."""
    from src import shootgen

    brand = brand if brand in preprod.BRANDS else (
        request.cookies.get("brand")
        if request.cookies.get("brand") in preprod.BRANDS else "antihero")
    sample = shootgen.gold_standard_example()
    if sample:
        paragraphs = [p for p in sample.split("\n\n") if p.strip()]
        sample = "\n\n".join(paragraphs[:2])
    chips = []
    if brand == "zeropage":
        chips = [{"label": name, "text": how}
                 for name, how in shootgen.ZEROPAGE_FORMATS[:4]]
    return {"brand": brand, "sample_prompt": sample, "chips": chips}


def _enhance_generate_prompt(gemini_client, prompt: str, *, preset=None,
                             references: str = "", image_refs=None,
                             video_refs=None) -> str:
    """The Enhance primitive for one Generate-tab run: the typed prompt,
    the picked preset's scaffold, and the RAG references folded into one
    billed Gemini call, with image/video references riding as real
    vision input. Raises on failure -- here the model call IS the
    deliverable, the promptgen contract."""
    from google.genai import types

    from src import shootgen
    from src import workflows as _workflows
    from src.gemini_utils import generate_with_retry

    blocks = [_workflows._enhance_system_text()]
    if preset:
        blocks.append("CAMERA / FRAMING SCAFFOLD -- build the prompt around "
                      f"this move:\n{preset['label']}: {preset['how']}")
    if references:
        blocks.append("REFERENCES -- ground the prompt in these:\n" + references)
    if image_refs or video_refs:
        blocks.append("(Reference media is attached above -- ground the prompt "
                      "in what it actually shows, don't ignore it.)")
    blocks.append("PROMPT TO ENHANCE:\n" + prompt)

    parts: list = [types.Part.from_bytes(data=data, mime_type=mime)
                   for data, mime in image_refs or []]
    for data, mime in video_refs or []:
        part = video_part(gemini_client, data, mime)
        if part is not None:
            parts.append(part)
    parts.append("\n\n".join(blocks))
    return generate_with_retry(gemini_client, shootgen.MODEL, parts).strip()


def _generate_title(prompt: str) -> str:
    words = prompt.split()
    title = " ".join(words[:8])
    return title + ("…" if len(words) > 8 else "")


@router.post("/generate/run")
async def generate_run(request: Request):
    """The Generate button: preset + prompt (+ attached image/video
    references) -> Ground -> Enhance -> saved one-shot concept -> the
    render. The render is best-effort and honestly gated: an image goes
    through Nano Banana (cheap, capped) and lands as the shot's
    reference_image; a video goes through Runway's spend gate and lands
    as media_url; a refusal still leaves the saved concept + prompt."""
    form = await request.form()
    prompt = (form.get("prompt") or "").strip()
    if not prompt:
        return _error(400, "empty_prompt", "a prompt is required")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    brand_raw = form.get("brand")
    brand = brand_raw if brand_raw in preprod.BRANDS else (
        request.cookies.get("brand") if request.cookies.get("brand") in preprod.BRANDS
        else "antihero")
    output = form.get("output")
    if output not in GENERATE_OUTPUTS:
        output = "image"
    preset = presets.get_preset(form.get("preset"))
    concept_id_raw = (form.get("concept_id") or "").strip()
    attach_to = int(concept_id_raw) if concept_id_raw.isdigit() else None
    if attach_to is not None and preprod.get_concept(attach_to, path=db.DB_PATH) is None:
        return _error(404, "not_found", "no such concept to attach to")

    image_refs: list = []
    video_refs: list = []
    for upload in form.getlist("files"):
        filename = getattr(upload, "filename", "")
        if not filename:
            continue
        mime = _video_mime(filename)
        if mime:
            if len(video_refs) < MAX_VIDEO_REFS:
                video_refs.append((await upload.read(), mime))
            continue
        if len(image_refs) >= MAX_IMAGE_REFS:
            continue
        jpeg = _to_jpeg(await upload.read())
        if jpeg:
            image_refs.append((jpeg, "image/jpeg"))
    for picked in form.getlist("asset_photos"):
        if len(image_refs) >= MAX_IMAGE_REFS:
            break
        target = _resolve_asset_photo(str(picked))
        if target is None:
            continue
        jpeg = _to_jpeg(target.read_bytes())
        if jpeg:
            image_refs.append((jpeg, "image/jpeg"))

    def work(job):
        from google import genai

        from src import nano_banana, shootgen
        gemini_client = genai.Client(api_key=api_key)

        jobs.progress(job, 0.1, "grounding in references")
        references = shootgen.reference_block(spark=prompt, db_path=db.DB_PATH)

        refs_note = ""
        if image_refs or video_refs:
            refs_note = f" · {len(image_refs) + len(video_refs)} ref(s)"
        jobs.progress(job, 0.3, "enhancing prompt" + refs_note)
        enhanced = _enhance_generate_prompt(
            gemini_client, prompt, preset=preset, references=references,
            image_refs=image_refs, video_refs=video_refs)
        if not enhanced:
            raise RuntimeError("enhancement came back empty")

        jobs.progress(job, 0.55, "saving concept")
        shot = {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                "desc": prompt, "prompt": enhanced}
        allowed = shootgen.ZEROPAGE_AI_TOOLS if brand == "zeropage" else None
        location_names = [loc["name"]
                          for loc in preprod.list_locations(path=db.DB_PATH)]
        if attach_to is not None:
            concept = preprod.get_concept(attach_to, path=db.DB_PATH)
            shots = list(concept.get("shots") or [])
            shot["n"] = max((s.get("n") or 0 for s in shots), default=0) + 1
            shots.append(shot)
            warnings = shootgen.validate_concept(
                {**concept, "shots": shots}, location_names,
                use_pov=bool(concept.get("use_pov")), allowed_tools=allowed)
            preprod.update_concept_shots(attach_to, {"shots": shots},
                                         warnings=warnings, path=db.DB_PATH)
            concept_id = attach_to
        else:
            concept_dict = {"title": _generate_title(prompt), "hook": "",
                            "logline": prompt, "shots": [shot]}
            warnings = shootgen.validate_concept(
                concept_dict, location_names, allowed_tools=allowed)
            concept_id = preprod.save_concept(
                concept_dict, brand=brand, spark=prompt,
                warnings=warnings, path=db.DB_PATH)

        notes = []
        if output == "image":
            jobs.progress(job, 0.7, "rendering image via Nano Banana")
            result = nano_banana.generate_from_prompt(
                enhanced, reference_image=image_refs[0][0] if image_refs else None,
                db_path=db.DB_PATH)
            if result.get("ok"):
                preprod.set_shot_reference_image(
                    concept_id, shot["n"], result["media_url"], path=db.DB_PATH)
                notes.append("image rendered → shot reference")
            else:
                notes.append(f"image render skipped: {result.get('error')}")
        elif output == "video":
            if runway.has_key():
                jobs.progress(job, 0.7, "rendering via Runway")
                result = runway.generate_from_prompt(
                    enhanced,
                    reference_image=image_refs[0][0] if image_refs else None,
                    db_path=db.DB_PATH)
                if result.get("ok"):
                    preprod.set_shot_media_url(
                        concept_id, shot["n"], result["media_url"], path=db.DB_PATH)
                    notes.append("clip rendered and attached")
                else:
                    notes.append(f"render skipped: {result.get('error')}")
            else:
                notes.append("render skipped: RUNWAYML_API_SECRET not set")

        detail = "prompt saved" if output == "prompt" else (notes[0] if notes else "saved")
        if warnings:
            detail += f" · {len(warnings)} warning(s)"
        return {"ref_id": concept_id, "detail": detail, "output": enhanced,
                "shot_n": shot["n"]}

    job = jobs.start("generate", f"generate · {prompt[:60]}", work)
    return {"job_id": job["id"],
            "image_refs": len(image_refs), "video_refs": len(video_refs)}


# --- director mode: per-shot save-back --------------------------------------

class ShotPromptBody(BaseModel):
    prompt: str


@router.post("/concepts/{concept_id}/shots/{shot_n}/prompt")
def shot_prompt_update(concept_id: int, shot_n: int, body: ShotPromptBody):
    """Persist one shot's edited prompt from the Director canvas --
    through update_concept_shots (so the picked title/hook/logline are
    never touched), re-validated the same way a fresh plan is. The
    other shots ride along unchanged."""
    from src import shootgen

    text = body.prompt.strip()
    if not text:
        return _error(400, "empty_prompt", "an empty prompt renders nothing")
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    shots = concept.get("shots") or []
    shot = next((s for s in shots if s.get("n") == shot_n), None)
    if shot is None:
        return _error(404, "not_found", f"no shot {shot_n}")
    shot["prompt"] = text
    warnings = shootgen.validate_concept(
        {**concept, "shots": shots},
        [loc["name"] for loc in preprod.list_locations(path=db.DB_PATH)],
        use_pov=bool(concept.get("use_pov")),
        allowed_tools=shootgen.ZEROPAGE_AI_TOOLS
        if concept.get("brand") == "zeropage" else None)
    preprod.update_concept_shots(concept_id, {"shots": shots},
                                 warnings=warnings, path=db.DB_PATH)
    return {"concept_id": concept_id, "shot_n": shot_n, "warnings": warnings}


class ShotReferenceBody(BaseModel):
    url: str


@router.post("/concepts/{concept_id}/shots/{shot_n}/reference")
def shot_reference_attach(concept_id: int, shot_n: int, body: ShotReferenceBody):
    """Attach (or clear, with "") an image URL as one shot's reference
    anchor -- how a Director-canvas Nano render lands back on the shot.
    The /ui JSON twin of the dev console's form route."""
    url = body.url.strip()
    if url and not url.startswith(("http://", "https://", "/")):
        return _error(400, "invalid_url",
                      "paste a public http(s) URL or a site-relative path")
    try:
        preprod.set_shot_reference_image(concept_id, shot_n, url, path=db.DB_PATH)
    except ValueError as e:
        return _error(404, "not_found", str(e))
    return {"concept_id": concept_id, "shot_n": shot_n,
            "reference_image": url or None}


@router.post("/concepts/{concept_id}/approve")
def concept_approve(concept_id: int):
    """Approve an idea = write ITS scene prompt (2026-08-26). Stage two
    used to explode an idea into a shot list; a concept is one scene now,
    so this fills in that one prompt. Only an idea needs it -- a concept
    that already carries its scene has nothing to write."""
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    if concept.get("shots"):
        return _error(409, "already_written",
                      "this concept already has its scene prompt")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        from google import genai

        from src import shootgen
        jobs.progress(job, 0.2, "grounding in references")
        references = shootgen.reference_block(
            spark=concept.get("title"), db_path=db.DB_PATH)
        jobs.progress(job, 0.4, "writing the scene prompt")
        result = shootgen.write_scene_for_concept(
            concept_id, gemini_client=genai.Client(api_key=api_key),
            references=references, db_path=db.DB_PATH,
        )
        warnings = result.get("warnings") or []
        detail = "scene written"
        if warnings:
            detail += f" · {len(warnings)} warning(s)"
        return {"ref_id": concept_id, "detail": detail}

    job = jobs.start("plan", f"scene · {concept['title']}", work)
    return {"job_id": job["id"], "concept_id": concept_id}


class DenyBody(BaseModel):
    reasons: list[str]
    note: Optional[str] = None


@router.post("/concepts/{concept_id}/deny")
def concept_deny(concept_id: int, body: DenyBody):
    """Deny records WHY, then vacates the slot: the reasons + note become
    a correction the next generation's spark folds in (autonomy's
    human_note channel, consumed once), and the same text is written to
    the RAG 'denials' shelf as evidence. The correction always lands;
    the chunk is best-effort -- a down store must not lose the label."""
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    reasons = [r for r in body.reasons if r in DENY_REASONS]
    if not reasons:
        return _error(400, "invalid_reasons",
                      f"reasons must be one or more of: {', '.join(DENY_REASONS)}")
    note = (body.note or "").strip()

    summary = f"Denied \"{concept['title']}\": {', '.join(reasons)}"
    if note:
        summary += f" — {note}"
    correction_id = autonomy.add_correction(summary, path=db.DB_PATH)

    chunk_written = 0
    chunk_error = None
    text = "\n".join(filter(None, [
        f"DENIED CONCEPT: {concept['title']}",
        f"Reasons: {', '.join(reasons)}",
        f"Note: {note}" if note else None,
        f"Logline: {concept.get('logline') or ''}",
        f"Spark: {concept.get('spark') or ''}",
        f"Brand: {concept.get('brand') or ''}",
    ]))
    try:
        conn = rag.connect()
        try:
            rag.init_store(conn)
            chunk_written = rag.ingest_records(
                [{"source": f"denials/concept-{concept_id}", "text": text,
                  "domain": "denials", "project": concept.get("brand"),
                  "source_ref": None}],
                rag.make_client(), conn,
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        chunk_error = str(e)

    preprod.delete_concept(concept_id, path=db.DB_PATH)
    return {
        "denied": concept_id,
        "correction_id": correction_id,
        "chunks_written": chunk_written,
        "chunk_error": chunk_error,
    }


# --- holds ------------------------------------------------------------------

@router.get("/holds")
def holds_list(channel: Optional[str] = None):
    held = autonomy.list_hold(status="held", path=db.DB_PATH)
    if channel:
        held = [h for h in held if h["channel"] == channel]
    return {
        "items": held,
        "agreement": autonomy.evaluator_agreement(path=db.DB_PATH),
        "gate": autonomy.prompt_gate_agreement(path=db.DB_PATH),
        "pass_rate": autonomy.first_try_pass_rate(path=db.DB_PATH),
        "channels": autonomy.list_channels(path=db.DB_PATH),
        "killed": autonomy.killed(path=db.DB_PATH),
    }


class ResolveBody(BaseModel):
    status: str


@router.post("/holds/{hold_id}/resolve")
def holds_resolve(hold_id: int, body: ResolveBody):
    row = next((h for h in autonomy.list_hold(status=None, path=db.DB_PATH)
                if h["id"] == hold_id), None)
    if row is None:
        return _error(404, "not_found", "no such hold")
    try:
        autonomy.resolve_hold(hold_id, body.status, path=db.DB_PATH)
    except ValueError as e:
        return _error(400, "invalid_status", str(e))
    # Mirror /holds' grading: the human verdict lands next to the gate's.
    run_id = (row.get("payload") or {}).get("run_id") \
        if isinstance(row.get("payload"), dict) else None
    if run_id and body.status in ("approved", "rejected"):
        autonomy.set_prompt_verdicts(
            run_id, "post" if body.status == "approved" else "reject",
            path=db.DB_PATH)
    return {"id": hold_id, "status": body.status}


@router.post("/holds/{hold_id}/post")
def holds_post(hold_id: int):
    """The explicit 'post now' -- moved here from the retired /holds dev
    page (2026-08-26) so /ui's hold queue keeps the whole ritual. One
    post action per channel target, through autopilot's unchanged
    three-condition gate; until credentials and real media exist it
    reports exactly what's missing rather than pretending."""
    row = next((h for h in autonomy.list_hold(status=None, path=db.DB_PATH)
                if h["id"] == hold_id), None)
    if row is None:
        return _error(404, "not_found", "no such hold")
    channel = autonomy.get_channel(row.get("channel", ""), path=db.DB_PATH) or {}
    targets = [t.strip() for t in (channel.get("targets") or "").split(",") if t.strip()]
    if not targets:
        return _error(400, "no_targets", "this channel has no post targets")

    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    caption = row.get("caption") or ""
    image_url = (payload.get("image_url") or "").strip()
    if image_url:
        actions = [{
            "kind": "post", "platform": platform, "concept_id": row.get("concept_id"),
            "caption": caption, "image_url": image_url,
        } for platform in targets]
    else:
        clips = payload.get("clips") or []
        media_url = next((c.get("url") for c in clips if c.get("url")), "") or ""
        is_local = bool(media_url) and not media_url.startswith("http")
        actions = [{
            "kind": "post", "platform": platform, "concept_id": row.get("concept_id"),
            "caption": caption,
            "video_url": media_url,
            "video_path": media_url if is_local else "",
        } for platform in targets]

    try:
        result = autopilot.execute({"actions": actions}, approve=True, dry_run=False)
    except Exception as e:
        return _error(502, "post_failed", str(e))

    mode = result.get("mode")
    if mode == "live" and result.get("executed"):
        autonomy.resolve_hold(hold_id, "posted", path=db.DB_PATH)
        return {"id": hold_id, "posted": True, "targets": targets, "mode": mode}
    if mode == "live":
        detail = "; ".join(result.get("skipped") or ["no rendered media to post yet"])
    elif mode == "disabled":
        detail = "posting is OFF — set ZEROPAGE_AUTOPILOT=1 and the platform credentials"
    elif mode == "killed":
        detail = "autopilot kill switch is on (data/autopilot.off)"
    else:
        detail = f"posting mode: {mode}"
    return {"id": hold_id, "posted": False, "mode": mode, "detail": detail}


# --- evals ------------------------------------------------------------------

@router.get("/evals/golden")
def evals_golden():
    return {"items": evalstore.list_golden(path=db.DB_PATH)}


class GoldenBody(BaseModel):
    query: str
    relevant: list[str]
    source: str = "probe"


@router.post("/evals/golden")
def evals_golden_add(body: GoldenBody):
    try:
        golden_id = evalstore.add_golden(body.query, body.relevant,
                                         source=body.source, path=db.DB_PATH)
    except ValueError as e:
        return _error(400, "invalid_golden", str(e))
    return {"id": golden_id}


@router.delete("/evals/golden/{golden_id}")
def evals_golden_delete(golden_id: int):
    evalstore.delete_golden(golden_id, path=db.DB_PATH)
    return {"deleted": golden_id}


@router.get("/evals/runs")
def evals_runs():
    return {"items": evalstore.list_runs(path=db.DB_PATH)}


@router.get("/evals/runs/{run_id}")
def evals_run_detail(run_id: int):
    run = evalstore.get_run(run_id, path=db.DB_PATH)
    if run is None:
        return _error(404, "not_found", "no such run")
    return run


class EvalRunBody(BaseModel):
    label: Optional[str] = None


@router.post("/evals/run")
def evals_run(body: EvalRunBody):
    """Compare one-shot retrieval with the complete CRAG retry path.

    Every metric is computed server-side and stored with the exact golden
    set, model, threshold, and reference-library identity that produced it.
    """
    golden = evalstore.list_golden(path=db.DB_PATH)
    if not golden:
        return _error(400, "empty_golden", "the golden set is empty")
    api_key = _gemini_key()
    if not (api_key and _rag_reachable()):
        return _error(503, "evals_unavailable",
                      "needs the RAG store and GEMINI_API_KEY")
    cases = [{"query": g["query"], "relevant": g["relevant"]} for g in golden]
    # the view already appends "· n queries · k=…", so the default label
    # stays bare to avoid stuttering
    label = (body.label or "").strip() or "run"
    k = _eval_k()

    def work(job):
        conn = rag.connect()
        try:
            client = rag.make_client()
            times: list[float] = []
            done = {"n": 0}

            total_steps = len(cases) * 2

            def base_retrieve(query_text, k):
                jobs.check_cancelled(job)
                started = time.perf_counter()
                hits = rag.query(query_text, client, conn, k=k)
                times.append((time.perf_counter() - started) * 1000)
                done["n"] += 1
                jobs.progress(job, done["n"] / total_steps,
                              f"{done['n']}/{total_steps} retrieval checks")
                return hits

            def crag_retrieve(query_text, k):
                jobs.check_cancelled(job)
                started = time.perf_counter()
                outcome = crag.retrieve_with_crag(
                    query_text, client, CRAG_REWRITE_MODEL, k=k,
                    threshold=settings.grade_threshold(path=db.DB_PATH),
                    record_telemetry=False,
                )
                times.append((time.perf_counter() - started) * 1000)
                done["n"] += 1
                jobs.progress(job, done["n"] / total_steps,
                              f"{done['n']}/{total_steps} retrieval checks")
                return outcome

            result = rag_eval.evaluate_comparison(
                cases, base_retrieve, crag_retrieve, k=k)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        p50 = int(statistics.median(times)) if times else None
        library = rag.reference_library_identity()
        set_fingerprint = rag_eval.case_set_fingerprint(cases)
        result.update({
            "mode": "comparison",
            "library_count": library["count"],
            "library_fingerprint": library["fingerprint"],
            "set_fingerprint": set_fingerprint,
        })
        threshold = settings.grade_threshold(path=db.DB_PATH)
        run_id = evalstore.save_run(
            label, result, p50_ms=p50,
            config={
                "k": k, "model": rag.EMBED_MODEL,
                "rewrite_model": CRAG_REWRITE_MODEL, "mode": "comparison",
                "threshold": threshold,
                "library_count": library["count"],
                "library_fingerprint": library["fingerprint"],
                "set_fingerprint": set_fingerprint,
            },
            path=db.DB_PATH)
        return {"ref_id": run_id,
                "detail": f"CRAG hit@{k} {result['hit_rate']:.2f} · "
                          f"base {result['base_hit_rate']:.2f} · "
                          f"re-query {result['requery_rate']:.0%}"}

    job = jobs.start("eval", f"eval · {len(cases)} queries", work,
                     cancellable=True)
    return {"job_id": job["id"]}


# --- analytics --------------------------------------------------------------

def _brand_rows(brand: Optional[str]) -> list:
    rows = db.latest_metrics_by_video(path=db.DB_PATH)
    if brand in preprod.BRANDS:
        # NULL-inclusive, same as /analytics: untagged legacy videos stay.
        rows = [r for r in rows if r.get("brand") in (None, brand)]
    return rows


@router.get("/analytics/summary")
def analytics_summary(brand: Optional[str] = None, platform: Optional[str] = None):
    rows = _brand_rows(brand)
    counts = {"all": len(rows)}
    for p in db.PLATFORMS:
        counts[p] = sum(1 for r in rows if r["platform"] == p)
    if platform in db.PLATFORMS:
        rows = [r for r in rows if r["platform"] == platform]
    return {
        "tiles": {
            "views": sum(r["views"] or 0 for r in rows),
            "likes": sum(r["likes"] or 0 for r in rows),
            "comments": sum(r["comments"] or 0 for r in rows),
            "saves": sum(r["saves"] or 0 for r in rows),
            "videos": len(rows),
        },
        "platform_counts": counts,
    }


@router.get("/analytics/posts")
def analytics_posts(brand: Optional[str] = None, platform: Optional[str] = None):
    rows = _brand_rows(brand)
    if platform in db.PLATFORMS:
        rows = [r for r in rows if r["platform"] == platform]
    ranked = sorted(rows, key=lambda r: (r["views"] is None, -(r["views"] or 0)))
    max_views = next((r["views"] for r in ranked if r["views"] is not None), 0)
    return {"items": [
        {**r, "pct": round((r["views"] or 0) / max_views * 100, 1) if max_views else 0}
        for r in ranked
    ]}


@router.get("/analytics/accounts")
def analytics_accounts():
    """What is actually connected: platform key presence (real config, not
    a wish list) plus the autonomy channels and their levels."""
    return {
        "apis": [
            {"platform": "youtube", "label": "YouTube Data API v3",
             "configured": bool(os.environ.get("YOUTUBE_API_KEY"))},
            {"platform": "instagram", "label": "Instagram Graph API",
             "configured": bool(instagram.access_token())},
        ],
        "channels": autonomy.list_channels(path=db.DB_PATH),
    }


@router.post("/videos/{video_id}/refresh")
def video_refresh(video_id: int):
    video = db.get_video(video_id, path=db.DB_PATH)
    if video is None:
        return _error(404, "not_found", "video not found")
    if video["platform"] == "instagram":
        result = instagram.refresh_metrics_for_video(
            video, token=instagram.access_token(), db_path=db.DB_PATH)
    else:
        result = youtube.refresh_metrics_for_video(
            video, api_key=os.environ.get("YOUTUBE_API_KEY"), db_path=db.DB_PATH)
    if not result.get("ok"):
        return _error(502, "refresh_failed", str(result.get("error")))
    return result


# --- workflows --------------------------------------------------------------
# The node-graph canvas. A workflow row is LiteGraph's serialize() JSON
# stored whole; execution (Run all) walks it server-side in topological
# order through app/workflow_runner.py, one node at a time -- billed
# calls are sequential on purpose. The Generate node goes through
# runway.generate_from_prompt, whose spend gate (RUNWAY_SPEND_OK inside
# generate_video) means this surface cannot become a second, ungated
# route to spend.

class WorkflowBody(BaseModel):
    name: Optional[str] = None
    graph: Optional[dict] = None
    brand: Optional[str] = None


@router.get("/workflows")
def workflows_list(brand: Optional[str] = None):
    return {"items": workflows.list_workflows(brand=brand or None, path=db.DB_PATH)}


@router.post("/workflows")
def workflows_create(body: WorkflowBody, request: Request):
    brand = body.brand if body.brand in preprod.BRANDS else (
        request.cookies.get("brand")
        if request.cookies.get("brand") in preprod.BRANDS else "antihero")
    workflow_id = workflows.create_workflow(
        body.name or "Untitled workflow", body.graph or {},
        brand=brand, path=db.DB_PATH)
    return {"id": workflow_id}


# the exec routes sit above /workflows/{workflow_id} so "exec" is never
# read as an id -- the /jobs/stream registration-order rule.

class GroundBody(BaseModel):
    spark: str = ""


@router.post("/workflows/exec/ground")
def workflow_exec_ground(body: GroundBody):
    """The Ground in References node: the existing RAG-grounding step
    (shootgen.reference_block) as a visible, wireable call. Degrades to
    "" with the store down, same as everywhere else."""
    from src import shootgen

    references = shootgen.reference_block(
        spark=body.spark.strip() or None, db_path=db.DB_PATH)
    return {"references": references}


class EnhanceBody(BaseModel):
    system: str = ""
    user: str = ""
    images: list[str] = []
    references: str = ""
    ground: bool = False   # pull the RAG block server-side (Director chain)


@router.post("/workflows/exec/enhance")
def workflow_exec_enhance(body: EnhanceBody):
    """The Gemini 2.5 Flash enhance node's own Run: one billed Gemini
    call through generate_with_retry, images riding as vision input and
    the Ground node's references folded in as grounding. A job, so the
    canvas lights the node from the same SSE feed everything uses."""
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        from google import genai

        from src import shootgen
        references = body.references
        if body.ground and not references:
            jobs.progress(job, 0.15, "grounding in references")
            references = shootgen.reference_block(
                spark=body.user.strip() or None, db_path=db.DB_PATH)
        jobs.progress(job, 0.3, "enhancing prompt")
        text = workflow_runner.enhance(
            body.system, body.user, images=body.images or None,
            references=references,
            gemini_client=genai.Client(api_key=api_key),
            resolve_photo=_resolve_asset_photo)
        return {"detail": text[:80], "output": text}

    job = jobs.start("enhance", f"enhance · {(body.user or body.system)[:50]}", work)
    return {"job_id": job["id"]}


class WfGenerateBody(BaseModel):
    prompt: str
    image: Optional[str] = None


@router.post("/workflows/exec/generate")
def workflow_exec_generate(body: WfGenerateBody):
    """The Generate node's own Run: one Runway render from a free-
    standing prompt + optional reference. Billed, capped, and
    spend-gated -- generate_video refuses without RUNWAY_SPEND_OK=1 on
    the server's run, exactly as the scene board's render button."""
    if not runway.has_key():
        return _error(503, "runway_unavailable", "RUNWAYML_API_SECRET is not set")

    def work(job):
        jobs.progress(job, 0.2, "rendering via Runway")
        reference = workflow_runner.image_for_runway(
            body.image, resolve_photo=_resolve_asset_photo)
        result = runway.generate_from_prompt(
            body.prompt, reference_image=reference, db_path=db.DB_PATH)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "render failed")
        return {"detail": "clip rendered", "output": result["media_url"]}

    job = jobs.start("render", f"runway · {body.prompt[:50]}", work)
    return {"job_id": job["id"]}


@router.post("/workflows/exec/nano")
def workflow_exec_nano(body: WfGenerateBody):
    """The Nano Banana node's own Run: one Gemini image render from a
    free-standing prompt + optional reference. Billed on the same
    GEMINI_API_KEY as everything else, capped by NANO_DAILY_CAP inside
    generate_from_prompt -- no separate spend gate, an image costs
    cents where a Runway render burns credits."""
    from src import nano_banana

    if not nano_banana.has_key():
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        jobs.progress(job, 0.2, "rendering via Nano Banana")
        reference = workflow_runner.image_bytes_for_gemini(
            body.image, resolve_photo=_resolve_asset_photo)
        result = nano_banana.generate_from_prompt(
            body.prompt, reference_image=reference, db_path=db.DB_PATH)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "render failed")
        return {"detail": "image rendered", "output": result["media_url"]}

    job = jobs.start("render", f"nano · {body.prompt[:50]}", work)
    return {"job_id": job["id"]}


@router.get("/workflows/{workflow_id}")
def workflows_get(workflow_id: int):
    workflow = workflows.get_workflow(workflow_id, path=db.DB_PATH)
    if workflow is None:
        return _error(404, "not_found", "no such workflow")
    return workflow


@router.put("/workflows/{workflow_id}")
def workflows_update(workflow_id: int, body: WorkflowBody):
    if not workflows.update_workflow(workflow_id, name=body.name,
                                     graph=body.graph, path=db.DB_PATH):
        return _error(404, "not_found", "no such workflow")
    return {"id": workflow_id}


@router.delete("/workflows/{workflow_id}")
def workflows_delete(workflow_id: int):
    if not workflows.delete_workflow(workflow_id, path=db.DB_PATH):
        return _error(404, "not_found", "no such workflow")
    return {"deleted": workflow_id}


@router.post("/workflows/{workflow_id}/run")
def workflows_run(workflow_id: int):
    """Run all: topological order over the SAVED graph (the client saves
    before it runs), sequential, every node's state pushed over the jobs
    SSE feed so the canvas lights up as nodes complete."""
    workflow = workflows.get_workflow(workflow_id, path=db.DB_PATH)
    if workflow is None:
        return _error(404, "not_found", "no such workflow")
    graph = workflow.get("graph") or {}
    if not graph.get("nodes"):
        return _error(400, "empty_graph", "the workflow has no nodes to run")
    api_key = _gemini_key()

    def work(job):
        gemini_client = None
        if api_key:
            from google import genai
            gemini_client = genai.Client(api_key=api_key)

        def emit(states, fraction, detail):
            jobs.update(job["id"], node_states=states)
            jobs.progress(job, fraction, detail)

        result = workflow_runner.execute_graph(
            graph, gemini_client=gemini_client,
            resolve_photo=_resolve_asset_photo, db_path=db.DB_PATH,
            emit=emit, check_cancelled=lambda: jobs.check_cancelled(job))
        jobs.update(job["id"], node_states=result["nodes"])
        failed = [s for s in result["nodes"].values() if s["status"] == "failed"]
        if failed:
            raise RuntimeError(f"{len(failed)} node(s) failed — "
                               + (failed[0].get("error") or "see the board"))
        done = sum(1 for s in result["nodes"].values() if s["status"] == "done")
        return {"ref_id": workflow_id, "detail": f"{done} node(s) executed"}

    job = jobs.start("workflow", f"workflow · {workflow['name']}", work,
                     cancellable=True)
    return {"job_id": job["id"]}


# --- jobs -------------------------------------------------------------------

@router.get("/jobs")
def jobs_list(active: Optional[bool] = None):
    return {"items": jobs.list_jobs(active=active)}


@router.get("/jobs/stream")
async def jobs_stream():
    """SSE. The job rail, the queue view, and the pipeline cards all
    subscribe here -- the only push channel, nothing polls. Registered
    before /jobs/{job_id} so 'stream' isn't captured as an id."""
    queue = jobs.subscribe()

    async def gen():
        import asyncio
        try:
            # current state first, so a fresh subscriber isn't blind
            for job in jobs.list_jobs():
                yield f"event: job\ndata: {json.dumps(job)}\n\n"
            while True:
                try:
                    job = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"event: job\ndata: {json.dumps(job)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            jobs.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/jobs/{job_id}")
def job_detail(job_id: int):
    job = jobs.get(job_id)
    if job is None:
        return _error(404, "not_found", "no such job")
    return job


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: int):
    job = jobs.cancel(job_id)
    if job is None:
        return _error(404, "not_found", "no such job")
    return jobs.snapshot(job)


@router.delete("/jobs/{job_id}")
def job_clear(job_id: int):
    if not jobs.remove(job_id):
        return _error(409, "not_finished", "only finished jobs can be cleared")
    return {"deleted": job_id}

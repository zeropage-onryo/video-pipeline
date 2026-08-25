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
    autonomy,
    db,
    entities,
    evalstore,
    instagram,
    preprod,
    rag,
    rag_eval,
    runway,
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

# The deny screen's vocabulary. An enum, not free text, so denial
# reasons aggregate instead of fragmenting into synonyms.
DENY_REASONS = (
    "wrong location", "off-tone", "character drift",
    "pacing", "retrieval missed", "too generic",
)

EVAL_K = 5


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
        "workflows": True,
        "jobs": True,
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


@router.get("/assets/{category}/{item_id}")
def asset_detail(category: str, item_id: int):
    asset = next((i for i in _assets_all()
                  if i["id"] == f"{category}-{item_id}"), None)
    if asset is None:
        return _error(404, "not_found", "no such asset")
    return asset


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
        "shortlist": preprod.shortlist_rate(path=db.DB_PATH),
        "shoot": preprod.shoot_rate(path=db.DB_PATH),
    }


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
        jobs.progress(job, 0.15, "grounding in references")
        references = shootgen.reference_block(spark=prompt, client=None,
                                              db_path=db.DB_PATH)
        jobs.progress(job, 0.35,
                      "generating concept"
                      + (f" · {len(image_refs)} image ref(s)" if image_refs else ""))
        result = shootgen.generate_concept(
            brand=brand, spark=prompt,
            gemini_client=genai.Client(api_key=api_key),
            use_pov=True, db_path=db.DB_PATH, references=references,
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


@router.post("/concepts/{concept_id}/approve")
def concept_approve(concept_id: int):
    """Approve = worth planning. Queues stage two (the shot list), which
    is exactly the pick shortlist_rate measures."""
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return _error(404, "not_found", "no such concept")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        from google import genai

        from src import shootgen
        jobs.progress(job, 0.3, "planning shot list")
        result = shootgen.generate_shot_list(
            concept_id, gemini_client=genai.Client(api_key=api_key),
            db_path=db.DB_PATH,
        )
        warnings = result.get("warnings") or []
        detail = f"{len((result.get('plan') or {}).get('shots', []))} shots"
        if warnings:
            detail += f" · {len(warnings)} warning(s)"
        return {"ref_id": concept_id, "detail": detail}

    job = jobs.start("plan", f"shot list · {concept['title']}", work)
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
    """The harness: every golden query against the live store, Hit@k and
    MRR computed server-side (rag_eval), the run stored with its config.
    The client never calculates a metric."""
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

    def work(job):
        conn = rag.connect()
        try:
            client = rag.make_client()
            times: list[float] = []
            done = {"n": 0}

            def retrieve_fn(query_text, k):
                jobs.check_cancelled(job)
                started = time.perf_counter()
                hits = rag.query(query_text, client, conn, k=k)
                times.append((time.perf_counter() - started) * 1000)
                done["n"] += 1
                jobs.progress(job, done["n"] / len(cases),
                              f"{done['n']}/{len(cases)} queries")
                return hits

            result = rag_eval.evaluate(cases, retrieve_fn, k=EVAL_K)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        p50 = int(statistics.median(times)) if times else None
        run_id = evalstore.save_run(
            label, result, p50_ms=p50,
            config={"k": EVAL_K, "model": rag.EMBED_MODEL},
            path=db.DB_PATH)
        return {"ref_id": run_id,
                "detail": f"hit@{EVAL_K} {result['hit_rate']:.2f} · MRR {result['mrr']:.2f}"}

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


@router.post("/workflows/exec/enhance")
def workflow_exec_enhance(body: EnhanceBody):
    """The LLM Enhance node's own Run: one billed Gemini call through
    generate_with_retry, images riding as vision input. A job, so the
    canvas lights the node from the same SSE feed everything uses."""
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")

    def work(job):
        from google import genai
        jobs.progress(job, 0.3, "enhancing prompt")
        text = workflow_runner.enhance(
            body.system, body.user, images=body.images or None,
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

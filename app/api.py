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
    youtube,
)
from src.locations import IMAGE_EXTENSIONS

from . import jobs

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
    gemini = bool(_gemini_key())
    store = _rag_reachable()
    return {
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


class RunBody(BaseModel):
    prompt: str
    brand: Optional[str] = None


@router.post("/pipeline/run")
def pipeline_run(body: RunBody, request: Request):
    """The Create button: one full concept from the composer's prompt,
    grounded exactly the way /concepts/generate grounds -- reference
    block first, then the generator. Billed, so it only exists when the
    key does."""
    prompt = body.prompt.strip()
    if not prompt:
        return _error(400, "empty_prompt", "a prompt is required")
    api_key = _gemini_key()
    if not api_key:
        return _error(503, "generation_unavailable", "GEMINI_API_KEY not set")
    brand = body.brand if body.brand in preprod.BRANDS else (
        request.cookies.get("brand") if request.cookies.get("brand") in preprod.BRANDS
        else "antihero")

    def work(job):
        from google import genai

        from src import shootgen
        jobs.progress(job, 0.15, "grounding in references")
        references = shootgen.reference_block(spark=prompt, client=None,
                                              db_path=db.DB_PATH)
        jobs.progress(job, 0.35, "generating concept")
        result = shootgen.generate_concept(
            brand=brand, spark=prompt,
            gemini_client=genai.Client(api_key=api_key),
            use_pov=True, db_path=db.DB_PATH, references=references,
        )
        title = (result.get("concept") or {}).get("title") or "untitled"
        warnings = result.get("warnings") or []
        detail = f'"{title}"'
        if warnings:
            detail += f" · {len(warnings)} warning(s)"
        return {"ref_id": result.get("concept_id"), "detail": detail}

    job = jobs.start("concept", f"concept · {prompt[:60]}", work)
    return {"job_id": job["id"]}


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

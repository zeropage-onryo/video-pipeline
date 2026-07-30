"""
The web app: reads the same database the pipeline writes to. No build
step, no framework, no component library -- vanilla Jinja2 and CSS.

This session is the skeleton only: the dashboard route, reading real
data through src/db.py, proving it reaches the page. The full
dashboard design (top performers, sparklines, pick rate) is Session 4.
"""
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai

from src import db, locations, preprod, shootgen, youtube

from .sparkline import render_sparkline

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
LOCATIONS_DIR = PROJECT_ROOT / "locations"
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# "Posted in the last" control -> posted_within_days. "all" -> no cutoff.
POSTED_WINDOWS = {"3": 90, "6": 180, "12": 365, "all": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(path=db.DB_PATH)
    preprod.init(path=db.DB_PATH)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def benchmark_class(score, median) -> str:
    """
    "above median" / "below median" per BUILD_SPEC's Design Direction --
    neutral (no class) when either value is missing or they're equal,
    so a lone video isn't coloured against itself.
    """
    if score is None or median is None:
        return ""
    if score > median:
        return "good"
    if score < median:
        return "bad"
    return ""


@app.get("/")
def dashboard(request: Request, at_days: int = 7, posted_within: str = "6",
              message: Optional[str] = None):
    counts = db.summary(path=db.DB_PATH)
    pick_rate = db.selection_rate(path=db.DB_PATH)

    posted_within_days = POSTED_WINDOWS.get(posted_within, 180)
    top = db.get_top_performers(
        at_days=at_days, posted_within_days=posted_within_days, limit=10, path=db.DB_PATH,
    )
    # Same window as top, or the colouring lies -- an all-time median would
    # make an average recent video look artificially good against the
    # long tail, or artificially bad against an old outlier.
    bench = db.benchmark(
        at_days=at_days, posted_within_days=posted_within_days, path=db.DB_PATH,
    )

    rows = []
    for t in top:
        history = db.get_video_history(t["video_id"], path=db.DB_PATH)
        rows.append({
            **t,
            "sparkline": render_sparkline(history),
            "css_class": benchmark_class(t["score"], bench["median"]),
        })

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "counts": counts,
            "pick_rate": pick_rate,
            "rows": rows,
            "at_days": at_days,
            "posted_within": posted_within,
            "message": message,
        },
    )


def parse_video_form(form: dict) -> dict:
    """
    Raw form strings -> db.add_video kwargs. Blank optional fields become
    None, not "" -- an empty string stored as a topic is worse than no
    topic at all.
    """
    def clean(key):
        value = (form.get(key) or "").strip()
        return value or None

    idea_id_raw = (form.get("idea_id") or "").strip()
    return {
        "title": form["title"].strip(),
        "platform": form["platform"],
        "posted_at": form["posted_at"],
        "url": clean("url"),
        "timeline": clean("timeline"),
        "topic": clean("topic"),
        "hook_type": clean("hook_type"),
        "idea_id": int(idea_id_raw) if idea_id_raw else None,
    }


@app.get("/videos/new")
def videos_new_form(request: Request):
    return templates.TemplateResponse(
        request,
        "videos_new.html",
        {
            "platforms": db.PLATFORMS,
            "topics": db.distinct_video_field_values("topic", path=db.DB_PATH),
            "hook_types": db.distinct_video_field_values("hook_type", path=db.DB_PATH),
        },
    )


@app.post("/videos/new")
async def videos_new_submit(request: Request):
    form = dict(await request.form())
    parsed = parse_video_form(form)
    try:
        db.add_video(**parsed, path=db.DB_PATH)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/", status_code=303)


@app.post("/videos/import/youtube")
async def videos_import_youtube(request: Request):
    form = dict(await request.form())
    handle = (form.get("handle") or "").strip()
    if not handle:
        raise HTTPException(status_code=400, detail="a channel handle is required")

    api_key = os.environ.get("YOUTUBE_API_KEY")
    result = youtube.import_channel_videos(handle, api_key=api_key, db_path=db.DB_PATH)

    if result["ok"]:
        message = f"Imported {result['added']} video(s) from {handle}"
    else:
        message = f"Could not import from {handle}: {result['error']}"

    return RedirectResponse(f"/?message={quote(message)}", status_code=303)


METRICS_FIELDS = ("views", "likes", "comments", "saves")


def parse_metrics_form(form: dict, video_ids: list) -> dict:
    """
    Which videos got a new number typed in, and what. A video with
    nothing typed is entirely absent from the result -- that's what
    "one save writes every changed row" means: empty means "no change
    this week," not "zero views."
    """
    changed = {}
    for vid in video_ids:
        entry = {}
        for field in METRICS_FIELDS:
            raw = (form.get(f"{field}_{vid}") or "").strip()
            if raw:
                entry[field] = int(raw)
        if entry:
            changed[vid] = entry
    return changed


@app.get("/metrics/new")
def metrics_new_form(request: Request, updated: Optional[int] = None, message: Optional[str] = None):
    rows = db.latest_metrics_by_video(path=db.DB_PATH)
    return templates.TemplateResponse(
        request,
        "metrics_new.html",
        {"rows": rows, "updated": updated, "message": message},
    )


@app.post("/metrics/new")
async def metrics_new_submit(request: Request):
    form = dict(await request.form())
    video_ids = [r["video_id"] for r in db.latest_metrics_by_video(path=db.DB_PATH)]
    changed = parse_metrics_form(form, video_ids)
    for vid, fields in changed.items():
        db.record_metrics(vid, path=db.DB_PATH, **fields)
    return RedirectResponse(f"/metrics/new?updated={len(changed)}", status_code=303)


@app.post("/metrics/refresh/{video_id}")
def metrics_refresh(video_id: int):
    video = db.get_video(video_id, path=db.DB_PATH)
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")

    api_key = os.environ.get("YOUTUBE_API_KEY")
    result = youtube.refresh_metrics_for_video(video, api_key=api_key, db_path=db.DB_PATH)

    if result["ok"]:
        message = f"Refreshed {video['title']}: {result['views']} views"
    else:
        message = f"Could not refresh {video['title']}: {result['error']}"

    return RedirectResponse(f"/metrics/new?message={quote(message)}", status_code=303)


@app.get("/videos/{video_id}")
def video_detail(request: Request, video_id: int):
    video = db.get_video(video_id, path=db.DB_PATH)
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")
    history = db.get_video_history(video_id, path=db.DB_PATH)
    return templates.TemplateResponse(
        request,
        "video_detail.html",
        {
            "video": video,
            "history": history,
            "sparkline": render_sparkline(history, width=480, height=120),
        },
    )


def group_pitches_by_run(pitches: list) -> list:
    """
    get_labelled_pitches() already returns rows ordered run_id DESC,
    number ASC -- this just buckets the flat list into per-run groups,
    preserving that order (runs newest first).
    """
    runs = []
    current_run_id = object()  # sentinel that can't equal a real run_id
    for p in pitches:
        if p["run_id"] != current_run_id:
            runs.append({
                "run_id": p["run_id"],
                "run_created_at": p["run_created_at"],
                "model": p.get("model"),
                "prompt_hash": p.get("prompt_hash"),
                "pitches": [],
            })
            current_run_id = p["run_id"]
        runs[-1]["pitches"].append(p)
    return runs


@app.get("/pitches")
def pitches_list(request: Request):
    pitches = db.get_labelled_pitches(limit=200, path=db.DB_PATH)
    rate = db.selection_rate(path=db.DB_PATH)
    return templates.TemplateResponse(
        request,
        "pitches.html",
        {"runs": group_pitches_by_run(pitches), "by_prompt": rate["by_prompt"]},
    )


def photos_for(space: str) -> list:
    """Web paths for a space's photos, so the page can actually show
    them rather than just naming a count."""
    space_dir = LOCATIONS_DIR / space
    if not space_dir.is_dir():
        return []
    return [
        f"/locations/{space}/photo/{p.name}"
        for p in sorted(space_dir.iterdir())
        if p.is_file() and p.suffix.lower() in locations.IMAGE_EXTENSIONS
    ]


@app.get("/locations")
def locations_list(request: Request, message: Optional[str] = None):
    spaces = preprod.list_locations(path=db.DB_PATH)
    for space in spaces:
        space["photos"] = photos_for(space["name"])
    return templates.TemplateResponse(
        request,
        "locations.html",
        {"locations": spaces, "message": message},
    )


@app.get("/locations/{space}/photo/{filename}")
def location_photo(space: str, filename: str):
    """
    Serve one photo. Both segments are resolved and checked against the
    locations dir -- a path that climbs out of it is refused rather
    than served, however it was encoded.
    """
    target = (LOCATIONS_DIR / space / filename).resolve()
    root = LOCATIONS_DIR.resolve()
    if root not in target.parents:
        raise HTTPException(status_code=404, detail="not found")
    if not target.is_file() or target.suffix.lower() not in locations.IMAGE_EXTENSIONS:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(target)


def safe_space_name(name: str) -> str:
    """
    A space name becomes a directory name, so it can't be allowed to
    contain separators or climb out of the locations dir.
    """
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip().replace(" ", "-").lower()
    return cleaned.strip("-.")


@app.post("/locations/upload")
async def locations_upload(name: str = Form(...), photos: List[UploadFile] = File(default=[])):
    space = safe_space_name(name)
    if not space:
        raise HTTPException(status_code=400, detail="a space name is required")

    images = [p for p in photos if p.filename and (p.content_type or "").startswith("image/")]
    if not images:
        raise HTTPException(status_code=400, detail="at least one photo is required")

    space_dir = LOCATIONS_DIR / space
    space_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for upload in images:
        target = space_dir / Path(upload.filename).name
        target.write_bytes(await upload.read())
        saved.append(target)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return RedirectResponse(
            f"/locations?message={quote('Photos saved, but GEMINI_API_KEY is not set so they were not described')}",
            status_code=303,
        )

    # Describing is the deliverable, but a failed vision call shouldn't
    # lose the photos or 500 the page -- they stay on disk to retry.
    try:
        gemini_client = genai.Client(api_key=api_key)
        description = locations.describe_location(gemini_client, space, saved)
        all_photos = sorted(
            p for p in space_dir.iterdir()
            if p.is_file() and p.suffix.lower() in locations.IMAGE_EXTENSIONS
        )
        preprod.add_location(space, description, photo_count=len(all_photos), path=db.DB_PATH)
        message = f"Described {space} from {len(all_photos)} photo(s)"
    except Exception as e:
        message = f"Saved {len(saved)} photo(s) to {space} but could not describe it: {e}"

    return RedirectResponse(f"/locations?message={quote(message)}", status_code=303)


@app.get("/concepts")
def concepts_list(request: Request, message: Optional[str] = None):
    return templates.TemplateResponse(
        request,
        "concepts.html",
        {
            "concepts": preprod.list_concepts(path=db.DB_PATH),
            "rate": preprod.shoot_rate(path=db.DB_PATH),
            "shortlist": preprod.shortlist_rate(path=db.DB_PATH),
            "brands": preprod.BRANDS,
            "has_locations": bool(preprod.list_locations(path=db.DB_PATH)),
            "message": message,
        },
    )


@app.post("/concepts/generate")
async def concepts_generate(request: Request):
    form = dict(await request.form())
    brand = form.get("brand") or "antihero"
    spark = (form.get("spark") or "").strip() or None
    client_name = (form.get("client") or "").strip() or None

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return RedirectResponse(
            f"/concepts?message={quote('GEMINI_API_KEY not set')}", status_code=303,
        )

    # Generating is the deliverable, but a failed generation should leave
    # the screen usable rather than 500 -- same contract as the YouTube import.
    try:
        gemini_client = genai.Client(api_key=api_key)
        if (form.get("mode") or "").strip() == "ideas":
            result = shootgen.generate_concept_ideas(
                brand=brand, client=client_name, spark=spark,
                gemini_client=gemini_client, db_path=db.DB_PATH,
            )
            message = f"Generated {len(result['ideas'])} ideas — plan the ones worth shooting"
        else:
            result = shootgen.generate_concept(
                brand=brand, client=client_name, spark=spark,
                gemini_client=gemini_client, db_path=db.DB_PATH,
            )
            message = f"Generated \"{result['concept']['title']}\""
            if result["warnings"]:
                message += f" ({len(result['warnings'])} warning(s))"
    except Exception as e:
        message = f"Could not generate: {e}"

    return RedirectResponse(f"/concepts?message={quote(message)}", status_code=303)


@app.post("/concepts/{concept_id}/shotlist")
def concepts_shotlist(concept_id: int):
    """Stage two. Bothering to plan a shoot for an idea is the pick
    shortlist_rate measures."""
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return RedirectResponse(
            f"/concepts?message={quote('GEMINI_API_KEY not set')}", status_code=303,
        )

    try:
        gemini_client = genai.Client(api_key=api_key)
        result = shootgen.generate_shot_list(
            concept_id, gemini_client=gemini_client, db_path=db.DB_PATH,
        )
        message = f"Planned \"{concept['title']}\""
        if result["warnings"]:
            message += f" ({len(result['warnings'])} warning(s))"
    except Exception as e:
        message = f"Could not plan {concept['title']}: {e}"

    return RedirectResponse(f"/concepts?message={quote(message)}", status_code=303)


@app.post("/concepts/{concept_id}/shot")
def concepts_mark_shot(concept_id: int):
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")

    preprod.mark_shot(concept_id, shot=not concept["shot_done"], path=db.DB_PATH)
    return RedirectResponse("/concepts", status_code=303)

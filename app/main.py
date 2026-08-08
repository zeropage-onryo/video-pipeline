"""
The web app: reads the same database the pipeline writes to. No build
step, no framework, no component library -- vanilla Jinja2 and CSS.

The app is one page: /studio is the workspace, and the older
per-stage screens (/concepts, /locations, /library, /analytics,
/pitches) stay reachable as the engine behind it. /  is the public
landing and the only indexed URL.
"""
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai

from src import autonomy, db, entities, instagram, locations, preprod, rag, shootgen, youtube

from . import seo
from .sparkline import render_sparkline

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
LOCATIONS_DIR = PROJECT_ROOT / "locations"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
PROPS_DIR = PROJECT_ROOT / "props"
THUMB_DIR = PROJECT_ROOT / "data" / "thumbs"
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def clean_title(title: str) -> str:
    """
    Display form of a video title: the stored title is whatever YouTube
    has, hashtags and all; on screen the tags are noise. A title that is
    nothing but hashtags keeps its raw form rather than going blank.
    """
    stripped = re.sub(r"#\S+", "", title or "").strip()
    stripped = re.sub(r"\s{2,}", " ", stripped)
    return stripped if stripped else title


templates.env.filters["clean_title"] = clean_title

# "Posted in the last" control -> posted_within_days. "all" -> no cutoff.
POSTED_WINDOWS = {"3": 90, "6": 180, "12": 365, "all": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(path=db.DB_PATH)
    preprod.init(path=db.DB_PATH)
    entities.init(path=db.DB_PATH)
    autonomy.init(path=db.DB_PATH)
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


def performance_rows(at_days: int = 7, posted_within: str = "6") -> dict:
    """
    The feedback loop: what's performing, compared at equal age. The
    benchmark uses the same window as the ranking or the colouring
    lies -- an all-time median would make an average recent video look
    good against the long tail, or bad against one old outlier. The
    current skin doesn't render the strip, but the discipline is pinned
    by tests here so a future skin inherits it rather than reinventing
    it wrong.
    """
    posted_within_days = POSTED_WINDOWS.get(posted_within, 180)
    top = db.get_top_performers(
        at_days=at_days, posted_within_days=posted_within_days, limit=5, path=db.DB_PATH,
    )
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
    return {"rows": rows, "at_days": at_days}


@app.get("/")
def landing(request: Request):
    """
    The marketing front door and the only indexed page. A template rather
    than a static file purely so the canonical URL and the JSON-LD graph
    are built from SITE_URL -- hardcoding a domain into the markup is how
    a canonical tag ends up pointing at localhost in production. The
    workspace lives at /studio.
    """
    return templates.TemplateResponse(
        request,
        "landing.html",
        {"site_url": seo.site_url(), "schema_json": seo.homepage_schema_json()},
    )


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt():
    """Public page open to everyone including the AI crawlers; the app
    itself kept out of the index."""
    return seo.robots_txt()


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt():
    """A markdown brief for language models: what the product is, what
    'grounded' means here, and the hard specs — the answer we'd want cited
    when someone asks an assistant about grounded pre-production."""
    return seo.llms_txt()


@app.get("/sitemap.xml")
def sitemap_xml():
    return Response(content=seo.sitemap_xml(), media_type="application/xml")


@app.get("/dashboard")
def dashboard():
    """
    Gone. The app is one page now: what the dashboard showed -- counts,
    pick rate, top performers at equal age -- lives on the studio canvas,
    where it sits next to the work that produced it instead of on a
    screen you had to remember to visit. Kept as a redirect because it
    was the app's front door for months and is in muscle memory.
    """
    return RedirectResponse("/studio", status_code=308)


# The assistant's vocabulary. Each intent is one pipeline stage; the
# phrases are what a person actually types when they mean it. Order
# matters -- the first intent with a matching phrase wins, so the more
# specific stages are checked before the catch-all.
INTENT_PHRASES = [
    ("room", ("room", "space", "location", "photograph", "photo of", "scout")),
    ("plan", ("plan", "shot list", "shotlist", "storyboard", "board it", "break it down")),
    ("concept", ("full concept", "one concept", "whole concept", "concept for",
                 "make one", "single idea")),
    ("ideas", ("idea", "deal", "pitch", "options", "slate", "give me")),
]

DEFAULT_INTENT = "ideas"


def route_intent(text: str, explicit: Optional[str] = None) -> str:
    """
    What did the person just ask for? A chip sends its intent outright;
    free text is matched against INTENT_PHRASES.

    This is keyword routing, not a model call, and that is the point: the
    assistant orchestrates stages that each cost a real API call, so the
    routing itself has to be free, instant, and inspectable. A miss lands
    on ideas -- the cheapest stage and the one an unclear request almost
    always means -- rather than silently spending a generation on the
    wrong thing.
    """
    if explicit in {name for name, _ in INTENT_PHRASES}:
        return explicit
    lowered = (text or "").lower()
    for intent, phrases in INTENT_PHRASES:
        if any(phrase in lowered for phrase in phrases):
            return intent
    return DEFAULT_INTENT


def next_unplanned_concept(concepts: list) -> Optional[dict]:
    """
    The idea "plan that one" means when no card was clicked: the most
    recent one that is still just an idea. list_concepts returns newest
    first, so the first match is the right one.
    """
    return next((c for c in concepts if not c.get("has_shot_list")), None)


@app.get("/studio")
def studio(request: Request, message: Optional[str] = None):
    """
    The workspace. Pre-production only now: the Workflow library
    (characters, rooms, props) reads the DB, the canvas shows the
    latest AI shots, and the assistant runs the ideation stages under
    the hood. Reading is free of model calls and renders even when
    every source is absent.
    """
    spaces = preprod.list_locations(path=db.DB_PATH)
    for space in spaces:
        space["photos"] = [f"{u}?thumb=1" for u in photos_for(space["name"])]

    # Characters and props for the Workflow library, photos resolved the
    # same way their own screens do it.
    characters = entities.list_characters(path=db.DB_PATH)
    for c in characters:
        slug = safe_space_name(c["name"])
        c["photos"] = [f"/characters/{slug}/photo/{fn}?thumb=1"
                       for fn in _entity_photos(CHARACTERS_DIR, slug)]
    props = entities.list_props(path=db.DB_PATH)
    for p in props:
        slug = safe_space_name(p["name"])
        p["photos"] = [f"/props/{slug}/photo/{fn}?thumb=1"
                       for fn in _entity_photos(PROPS_DIR, slug)]

    shoot_concepts = preprod.list_concepts(path=db.DB_PATH)
    # the AI shots of the most recent concept that has any -- a concept
    # can carry several now, so this is a list, not a single slot
    latest_ai = next(
        (c["ai_shots"] for c in shoot_concepts if c.get("ai_shots")), []
    )

    return templates.TemplateResponse(
        request,
        "studio.html",
        {
            "spaces": spaces,
            "characters": characters,
            "props": props,
            "shoot_concepts": shoot_concepts,
            "latest_ai": latest_ai,
            "active_nav": "home",
            "message": message,
        },
    )


def run_ideation(intent: str, *, brand: str, client_name, spark, use_pov: bool) -> str:
    """
    The two stages that generate from rooms. Split out of the route so
    the intent routing above can be read without the API plumbing
    underneath it. Returns the line to show on the canvas.
    """
    references = shootgen.reference_block(spark=spark, client=client_name,
                                          db_path=db.DB_PATH)
    gemini_client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    if intent == "concept":
        result = shootgen.generate_concept(
            brand=brand, client=client_name, spark=spark,
            gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
            references=references,
        )
        message = f"Generated \"{result['concept']['title']}\""
        if result["warnings"]:
            message += f" ({len(result['warnings'])} warning(s))"
        return message

    result = shootgen.generate_concept_ideas(
        brand=brand, client=client_name, spark=spark,
        gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
        references=references,
    )
    return f"Dealt {len(result['ideas'])} ideas — keep the ones worth planning"


@app.post("/studio/assist")
async def studio_assist(request: Request):
    """
    The assistant. One box and a row of chips stand in for the whole
    pipeline: this reads the intent, runs the stage it names, and lands
    back on the canvas with the result. Same contract as every other
    model-touching route -- a missing key or a failed call becomes a
    message, never a 500 -- and validation still happens inside
    shootgen.validate_concept, because prompts request and code enforces.

    Stages it can't run itself say so plainly instead of pretending: a
    cut list needs ingested footage and a pitch run, which are CLI steps.
    """
    form = dict(await request.form())
    text = (form.get("text") or "").strip()
    intent = route_intent(text, (form.get("intent") or "").strip() or None)

    brand = form.get("brand") or "antihero"
    client_name = (form.get("client") or "").strip() or None
    use_pov = bool(form.get("use_pov"))
    # The typed text is the spark for a generation; for a chip pressed
    # with an empty box there simply isn't one. Selected ingredients
    # (rooms, clips, references from the tray) and preferred platforms
    # ride along as extra spark lines — they steer both the RAG query
    # and the prompt's creative-spark section through the existing
    # grounding path, with no generator signature changes.
    spark = text or None
    ingredients = (form.get("ingredients") or "").strip()
    if ingredients:
        spark = f"{spark or ''}\nGround on: {ingredients}".strip()
    platforms = (form.get("platforms") or "").strip()
    if platforms:
        spark = f"{spark or ''}\nPreferred AI platforms: {platforms}".strip()

    if intent == "room":
        return RedirectResponse(
            "/studio?message=" + quote(
                "Open the ingredients tray — photograph the space and it gets described."
            ),
            status_code=303,
        )

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return RedirectResponse(
            f"/studio?message={quote('GEMINI_API_KEY not set')}", status_code=303,
        )

    if intent == "plan":
        target = next_unplanned_concept(preprod.list_concepts(path=db.DB_PATH))
        if target is None:
            message = "Nothing left to plan — deal some ideas first."
        else:
            message = plan_concept(target["id"])
        return RedirectResponse(f"/studio?message={quote(message)}", status_code=303)

    try:
        message = run_ideation(intent, brand=brand, client_name=client_name,
                               spark=spark, use_pov=use_pov)
    except Exception as e:
        message = f"Could not generate: {e}"
    return RedirectResponse(f"/studio?message={quote(message)}", status_code=303)


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
    return RedirectResponse("/studio", status_code=303)


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

    return RedirectResponse(f"/studio?message={quote(message)}", status_code=303)


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


@app.get("/library")
def library(request: Request, q: Optional[str] = None,
            domain: Optional[str] = None, message: Optional[str] = None):
    """
    The reference library: what's on the shelves, semantic search over
    it, and a form to add to it. The whole page must render when
    Postgres is down -- the library is optional everywhere else, so it
    can't be the one screen that 500s.
    """
    context = {"available": False, "sources": [], "results": [],
               "domains": [], "q": q, "domain": domain,
               "message": message, "error": None, "active_nav": "workflow"}
    conn = None
    try:
        conn = rag.connect()
        context["sources"] = rag.list_sources(conn)
        context["domains"] = sorted({s["domain"] for s in context["sources"]})
        context["available"] = True
        if q:
            try:
                context["results"] = rag.query(
                    q, rag.make_client(), conn, k=5, domain=domain or None
                )
            except Exception as e:
                context["error"] = f"search failed: {e}"
    except Exception as e:
        context["error"] = f"library unavailable: {e}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return templates.TemplateResponse(request, "library.html", context)


@app.post("/library/ingest")
def library_ingest(source: str = Form(""), domain: str = Form(""),
                   project: str = Form(""), source_ref: str = Form(""),
                   text: str = Form("")):
    if not (source.strip() and domain.strip() and text.strip()):
        return RedirectResponse(
            "/library?message=" + quote("source, domain, and text are all required"),
            status_code=303,
        )
    try:
        conn = rag.connect()
        rag.init_store(conn)
        written = rag.ingest_records(
            [{"source": source.strip(), "text": text,
              "domain": domain.strip(), "project": project.strip() or None,
              "source_ref": source_ref.strip() or None}],
            rag.make_client(), conn,
        )
        conn.close()
        message = f"stored {written} chunk(s) under '{domain.strip()}'"
    except Exception as e:
        message = f"ingest failed: {e}"
    return RedirectResponse("/library?message=" + quote(message), status_code=303)


@app.post("/library/delete")
def library_delete(source: str = Form(...)):
    try:
        conn = rag.connect()
        removed = rag.delete_source(conn, source)
        conn.close()
        message = f"removed '{source}' ({removed} chunk(s))"
    except Exception as e:
        message = f"delete failed: {e}"
    return RedirectResponse("/library?message=" + quote(message), status_code=303)


@app.get("/holds")
def holds_list(request: Request, message: Optional[str] = None):
    """
    The morning ritual: what the graph wanted to post while you weren't
    looking, and the approve/reject that grades the evaluator. The
    agreement number is the credit gate -- ~0.9 over a real stretch is
    what earns a channel its promotion to auto.
    """
    concepts_by_id = {c["id"]: c for c in preprod.list_concepts(path=db.DB_PATH)}
    held = autonomy.list_hold(status="held", path=db.DB_PATH)
    for row in held:
        row["concept"] = concepts_by_id.get(row.get("concept_id"))
    return templates.TemplateResponse(
        request,
        "holds.html",
        {
            "held": held,
            "agreement": autonomy.evaluator_agreement(path=db.DB_PATH),
            "channels": autonomy.list_channels(path=db.DB_PATH),
            "killed": autonomy.killed(path=db.DB_PATH),
            "active_nav": "home",
            "message": message,
        },
    )


@app.post("/holds/{hold_id}/resolve")
async def holds_resolve(hold_id: int, request: Request):
    """Approved = "I would have posted this" (the evaluator was right);
    rejected = "glad it held". Either way the row leaves the queue and
    feeds the agreement number."""
    form = dict(await request.form())
    status = (form.get("status") or "").strip()
    try:
        autonomy.resolve_hold(hold_id, status, path=db.DB_PATH)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/holds", status_code=303)


@app.get("/analytics")
@app.get("/metrics/new")   # old URL, kept so bookmarks and habits still land
def analytics(request: Request, updated: Optional[int] = None, message: Optional[str] = None):
    rows = db.latest_metrics_by_video(path=db.DB_PATH)

    # One measure (views) across named videos: a sorted bar list, each
    # bar scaled against the current best. Totals are headline numbers,
    # not charts.
    ranked = sorted((r for r in rows if r["views"] is not None),
                    key=lambda r: r["views"], reverse=True)
    max_views = ranked[0]["views"] if ranked else 0
    bars = [
        {**r,
         "pct": round(r["views"] / max_views * 100, 1) if max_views else 0,
         "views_fmt": f"{r['views']:,}"}
        for r in ranked
    ]
    tiles = {
        "views": f"{sum(r['views'] or 0 for r in rows):,}",
        "likes": f"{sum(r['likes'] or 0 for r in rows):,}",
        "comments": f"{sum(r['comments'] or 0 for r in rows):,}",
        "videos": len(rows),
    }
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {"rows": rows, "bars": bars, "tiles": tiles,
         "updated": updated, "message": message, "active_nav": "scoreboard"},
    )


@app.post("/metrics/new")
async def metrics_new_submit(request: Request):
    form = dict(await request.form())
    video_ids = [r["video_id"] for r in db.latest_metrics_by_video(path=db.DB_PATH)]
    changed = parse_metrics_form(form, video_ids)
    for vid, fields in changed.items():
        db.record_metrics(vid, path=db.DB_PATH, **fields)
    return RedirectResponse(f"/analytics?updated={len(changed)}", status_code=303)


@app.post("/metrics/refresh/{video_id}")
def metrics_refresh(video_id: int):
    """One dispatch on the video's platform; every branch returns a
    result dict, so a missing key or failed call is a message on the
    analytics page and manual entry keeps working."""
    video = db.get_video(video_id, path=db.DB_PATH)
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")

    if video["platform"] == "instagram":
        result = instagram.refresh_metrics_for_video(
            video, token=instagram.access_token(), db_path=db.DB_PATH,
        )
    else:
        api_key = os.environ.get("YOUTUBE_API_KEY")
        result = youtube.refresh_metrics_for_video(video, api_key=api_key,
                                                   db_path=db.DB_PATH)

    if result["ok"]:
        message = f"Refreshed {video['title']}: {result['views']} views"
    else:
        message = f"Could not refresh {video['title']}: {result['error']}"

    return RedirectResponse(f"/analytics?message={quote(message)}", status_code=303)


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


def thumbnail_for(source: Path) -> Path:
    """
    A cached small copy. Camera originals are multi-megabyte; sending
    one down the wire to be drawn at 72px is the difference between a
    page that feels built and one that feels slow. Falls back to the
    original if the file can't be read as an image.
    """
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    stat = source.stat()
    cached = THUMB_DIR / f"{source.parent.name}__{source.stem}__{int(stat.st_mtime)}.jpg"
    if cached.is_file():
        return cached

    try:
        from PIL import Image, ImageOps

        with Image.open(source) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((480, 480))
            img.save(cached, format="JPEG", quality=82)
        return cached
    except Exception:
        return source


@app.get("/locations")
def locations_list(request: Request, message: Optional[str] = None):
    spaces = preprod.list_locations(path=db.DB_PATH)
    for space in spaces:
        space["photos"] = photos_for(space["name"])
    return templates.TemplateResponse(
        request,
        "locations.html",
        {"locations": spaces, "message": message, "active_nav": "locations"},
    )


@app.get("/locations/{space}/photo/{filename}")
def location_photo(space: str, filename: str, thumb: Optional[int] = None):
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
    return FileResponse(thumbnail_for(target) if thumb else target)


def safe_space_name(name: str) -> str:
    """
    A space name becomes a directory name, so it can't be allowed to
    contain separators or climb out of the locations dir.
    """
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip().replace(" ", "-").lower()
    return cleaned.strip("-.")


@app.post("/locations/upload")
async def locations_upload(name: str = Form(...), next: str = Form(""),
                           photos: List[UploadFile] = File(default=[])):
    destination = safe_next(next, "/locations")
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
            f"{destination}?message={quote('Photos saved, but GEMINI_API_KEY is not set so they were not described')}",
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


# --- characters & props ----------------------------------------------------
# Pre-production entities, same shape as locations: a name-slug directory of
# photos plus a row in the shared DB. Photo serving reuses the locations
# path-traversal guard exactly.

def _entity_photos(base_dir, slug):
    directory = base_dir / slug
    if not directory.is_dir():
        return []
    return sorted(
        p.name for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in locations.IMAGE_EXTENSIONS
    )


async def _save_entity_photos(base_dir, slug, photos):
    images = [p for p in photos if p.filename and (p.content_type or "").startswith("image/")]
    if not images:
        return "", 0
    directory = base_dir / slug
    directory.mkdir(parents=True, exist_ok=True)
    for upload in images:
        (directory / Path(upload.filename).name).write_bytes(await upload.read())
    return Path(images[0].filename).name, len(images)


def _entity_photo_response(base_dir, slug, filename, thumb):
    target = (base_dir / slug / filename).resolve()
    root = base_dir.resolve()
    if root not in target.parents:
        raise HTTPException(status_code=404, detail="not found")
    if not target.is_file() or target.suffix.lower() not in locations.IMAGE_EXTENSIONS:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(thumbnail_for(target) if thumb else target)


@app.get("/characters")
def characters_list(request: Request, message: Optional[str] = None):
    items = entities.list_characters(path=db.DB_PATH)
    for c in items:
        slug = safe_space_name(c["name"])
        c["photos"] = [f"/characters/{slug}/photo/{fn}?thumb=1"
                       for fn in _entity_photos(CHARACTERS_DIR, slug)]
    return templates.TemplateResponse(
        request, "characters.html",
        {"characters": items, "message": message, "active_nav": "characters"},
    )


@app.get("/characters/{slug}/photo/{filename}")
def character_photo(slug: str, filename: str, thumb: Optional[int] = None):
    return _entity_photo_response(CHARACTERS_DIR, slug, filename, thumb)


@app.post("/characters/new")
async def characters_new(name: str = Form(...), role: str = Form(""),
                         notes: str = Form(""),
                         photos: List[UploadFile] = File(default=[])):
    slug = safe_space_name(name)
    if not slug:
        raise HTTPException(status_code=400, detail="a name is required")
    ref, count = await _save_entity_photos(CHARACTERS_DIR, slug, photos)
    entities.add_character(
        name=name, role=role,
        description={"notes": notes} if notes else None,
        reference_image=ref, photo_count=count, notes=notes, path=db.DB_PATH,
    )
    return RedirectResponse(f"/characters?message={quote('Added ' + name)}", status_code=303)


@app.post("/characters/{character_id}/delete")
def characters_delete(character_id: int):
    entities.delete_character(character_id, path=db.DB_PATH)
    return RedirectResponse(f"/characters?message={quote('Deleted')}", status_code=303)


@app.get("/props")
def props_list(request: Request, message: Optional[str] = None):
    items = entities.list_props(path=db.DB_PATH)
    for p in items:
        slug = safe_space_name(p["name"])
        p["photos"] = [f"/props/{slug}/photo/{fn}?thumb=1"
                       for fn in _entity_photos(PROPS_DIR, slug)]
    return templates.TemplateResponse(
        request, "props.html",
        {"props": items, "message": message, "active_nav": "props"},
    )


@app.get("/props/{slug}/photo/{filename}")
def prop_photo(slug: str, filename: str, thumb: Optional[int] = None):
    return _entity_photo_response(PROPS_DIR, slug, filename, thumb)


@app.post("/props/new")
async def props_new(name: str = Form(...), category: str = Form(""),
                    notes: str = Form(""),
                    photos: List[UploadFile] = File(default=[])):
    slug = safe_space_name(name)
    if not slug:
        raise HTTPException(status_code=400, detail="a name is required")
    ref, count = await _save_entity_photos(PROPS_DIR, slug, photos)
    entities.add_prop(
        name=name, category=category,
        description={"notes": notes} if notes else None,
        reference_image=ref, photo_count=count, notes=notes, path=db.DB_PATH,
    )
    return RedirectResponse(f"/props?message={quote('Added ' + name)}", status_code=303)


@app.post("/props/{prop_id}/delete")
def props_delete(prop_id: int):
    entities.delete_prop(prop_id, path=db.DB_PATH)
    return RedirectResponse(f"/props?message={quote('Deleted')}", status_code=303)


@app.get("/concepts")
def concepts_list(request: Request, message: Optional[str] = None):
    spaces = preprod.list_locations(path=db.DB_PATH)
    for space in spaces:
        space["photos"] = photos_for(space["name"])
    return templates.TemplateResponse(
        request,
        "concepts.html",
        {
            "concepts": preprod.list_concepts(path=db.DB_PATH),
            "rate": preprod.shoot_rate(path=db.DB_PATH),
            "shortlist": preprod.shortlist_rate(path=db.DB_PATH),
            "brands": preprod.BRANDS,
            "spaces": spaces,
            "has_locations": bool(spaces),
            "characters": entities.list_characters(path=db.DB_PATH),
            "props": entities.list_props(path=db.DB_PATH),
            "active_nav": "tools",
            "message": message,
        },
    )


def cast_from_picks(char_ids: list, prop_ids: list):
    """
    The generate form's optional picker -> the {cast} block. Nothing
    picked returns None, which generate_concept treats as "everything
    on file" -- the behavior the form had before the picker existed.
    Unknown ids are dropped rather than erroring: a row deleted between
    page load and submit shouldn't kill the generation.
    """
    char_ids = [int(x) for x in char_ids if str(x).strip()]
    prop_ids = [int(x) for x in prop_ids if str(x).strip()]
    if not char_ids and not prop_ids:
        return None
    characters = [c for c in (entities.get_character(i, path=db.DB_PATH)
                              for i in char_ids) if c]
    props = [p for p in (entities.get_prop(i, path=db.DB_PATH)
                         for i in prop_ids) if p]
    return shootgen.format_cast(characters, props)


@app.post("/concepts/generate")
async def concepts_generate(request: Request):
    form_data = await request.form()
    form = dict(form_data)
    brand = form.get("brand") or "antihero"
    spark = (form.get("spark") or "").strip() or None
    client_name = (form.get("client") or "").strip() or None
    # an unchecked checkbox submits nothing, so absence means off
    use_pov = bool(form.get("use_pov"))
    cast = cast_from_picks(form_data.getlist("characters"), form_data.getlist("props"))

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return RedirectResponse(
            f"/concepts?message={quote('GEMINI_API_KEY not set')}", status_code=303,
        )

    # Grounding is an enhancement, never a dependency: reference_block
    # degrades to "" (with a stderr note) if the library is unreachable.
    references = shootgen.reference_block(spark=spark, client=client_name,
                                          db_path=db.DB_PATH)

    # Generating is the deliverable, but a failed generation should leave
    # the screen usable rather than 500 -- same contract as the YouTube import.
    try:
        gemini_client = genai.Client(api_key=api_key)
        if (form.get("mode") or "").strip() == "ideas":
            result = shootgen.generate_concept_ideas(
                brand=brand, client=client_name, spark=spark,
                gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
                references=references,
            )
            message = f"Generated {len(result['ideas'])} ideas — plan the ones worth shooting"
        else:
            result = shootgen.generate_concept(
                brand=brand, client=client_name, spark=spark,
                gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
                references=references, cast=cast,
            )
            message = f"Generated \"{result['concept']['title']}\""
            if result["warnings"]:
                message += f" ({len(result['warnings'])} warning(s))"
    except Exception as e:
        message = f"Could not generate: {e}"

    return RedirectResponse(f"/concepts?message={quote(message)}", status_code=303)


def plan_concept(concept_id: int) -> str:
    """
    Stage two for one idea, as a message. Shared by the concepts screen
    and the studio assistant so both record the same pick the same way --
    the shortlist label can't depend on which screen you were standing on
    when you decided.
    """
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        return "That concept no longer exists."
    try:
        gemini_client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
        result = shootgen.generate_shot_list(
            concept_id, gemini_client=gemini_client, db_path=db.DB_PATH,
        )
        message = f"Planned \"{concept['title']}\""
        if result["warnings"]:
            message += f" ({len(result['warnings'])} warning(s))"
        return message
    except Exception as e:
        return f"Could not plan {concept['title']}: {e}"


def safe_next(value: Optional[str], default: str) -> str:
    """
    Which screen a form wants to land on. Only a site-relative path is
    honoured -- a `next` that names another host would turn every button
    in the app into an open redirect.
    """
    candidate = (value or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return default


@app.post("/concepts/{concept_id}/shotlist")
def concepts_shotlist(concept_id: int, next: str = Form("")):
    """Stage two. Bothering to plan a shoot for an idea is the pick
    shortlist_rate measures."""
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")

    destination = safe_next(next, "/concepts")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return RedirectResponse(
            f"{destination}?message={quote('GEMINI_API_KEY not set')}", status_code=303,
        )

    message = plan_concept(concept_id)
    return RedirectResponse(f"{destination}?message={quote(message)}", status_code=303)


@app.post("/concepts/{concept_id}/shot")
def concepts_mark_shot(concept_id: int, next: str = Form("")):
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")

    preprod.mark_shot(concept_id, shot=not concept["shot_done"], path=db.DB_PATH)
    return RedirectResponse(safe_next(next, "/concepts"), status_code=303)

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
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai
from starlette.middleware.sessions import SessionMiddleware

from src import accounts as accounts_mod
from src import (
    autonomy,
    autopilot,
    db,
    entities,
    evalstore,
    generative,
    inspiration,
    instagram,
    locations,
    preprod,
    rag,
    shootgen,
    taste_judge,
    winners,
    workflows,
    youtube,
)

from . import api, auth, seo
from .sparkline import render_sparkline

load_dotenv()

# Deployment posture. DEV_TOOLS=1 (the local .env) is the dev machine:
# the legacy dev-console pages -- /studio and every per-stage screen --
# register on top of /ui. Unset is a public deployment: those routes are
# never registered at all, so /studio 404s the same as any undefined
# path rather than being a page someone could find by guessing the URL.
# Read once at startup; /api/capabilities reports the same flag live so
# /ui can hide its "legacy" link (data-cap="dev_tools").
DEV_TOOLS = os.environ.get("DEV_TOOLS") == "1"

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

# --- Brands: two separate concepts, one switchable "active brand" ----------
# ANTIHERO = Michael's personal brand (he is the star); Zero Page = the viral
# auto-posting engine (product/trend is the star). They must never blur, so
# the active brand rides a cookie: it drives generation, filters which
# channel's holds and which brand's analytics you see, and shows a distinct
# label + accent everywhere.
BRANDS = tuple(preprod.BRANDS)
DEFAULT_BRAND = "antihero"
BRAND_META = {
    "antihero": {"label": "ANTIHERO", "accent": "#d64550",
                 "note": "personal brand — Michael is the star"},
    "zeropage": {"label": "Zero Page Films", "accent": "#8b5cf6",
                 "note": "viral engine — the product / trend is the star"},
}


def active_brand(request: Request) -> str:
    """The brand the studio is currently 'in', from the cookie. Validated
    against the real brand set, defaulting to ANTIHERO."""
    brand = request.cookies.get("brand", DEFAULT_BRAND)
    return brand if brand in BRANDS else DEFAULT_BRAND


# Jinja globals so the switcher + accent render on every page without
# threading the brand through each route's context.
templates.env.globals["active_brand"] = active_brand
templates.env.globals["BRAND_META"] = BRAND_META
templates.env.globals["BRANDS"] = BRANDS

# "Posted in the last" control -> posted_within_days. "all" -> no cutoff.
POSTED_WINDOWS = {"3": 90, "6": 180, "12": 365, "all": None}


def seed_gold_standard():
    """Record the canonical example prompt (prompts/gold_standard.md) as a
    winning prompt once, so the RAG loop reinforces it. Idempotent (keyed on
    the note), best-effort ingest -- never blocks startup."""
    text = shootgen.gold_standard_example()
    if not text:
        return
    try:
        already = any((w.get("note") or "").startswith("gold standard")
                      for w in winners.list_all(path=db.DB_PATH))
        if not already:
            winners.record_and_learn(
                "runway", text, note="gold standard structural exemplar",
                verdict="worked", path=db.DB_PATH)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(path=db.DB_PATH)
    preprod.init(path=db.DB_PATH)
    entities.init(path=db.DB_PATH)
    autonomy.init(path=db.DB_PATH)
    winners.init(path=db.DB_PATH)
    inspiration.init(path=db.DB_PATH)   # seeds the researched accounts if empty
    evalstore.init(path=db.DB_PATH)     # golden set seeded from eval_cases.json
    workflows.init(path=db.DB_PATH)     # saved node graphs for /ui Workflows
    workflows.seed_default(path=db.DB_PATH)  # "Prompt enhancement" starter canvas
    generative.init(path=db.DB_PATH)    # generations log the render caps count
    accounts_mod.init(path=db.DB_PATH)  # users / identities / accounts / members
    seed_gold_standard()                # records the canonical example as a winner
    yield


class NoCacheStaticFiles(StaticFiles):
    """Static assets revalidate on every load (ETag round-trip, cheap on
    localhost). Without a Cache-Control header the browser applies
    heuristic freshness and serves stale JS modules for minutes after an
    edit -- on a single-operator dev tool, correctness beats the saved
    round-trip."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(lifespan=lifespan)
# Starlette session middleware: used ONLY for the OAuth state/nonce dance
# (Authlib stores its CSRF state here). The login session itself is the
# separate signed zp_session cookie in app/auth.py.
app.add_middleware(SessionMiddleware, secret_key=auth._session_secret(),
                   same_site="lax", https_only=False)
app.mount("/static", NoCacheStaticFiles(directory=str(APP_DIR / "static")), name="static")
# Rendered clips (data/renders/, gitignored with the rest of data/) --
# what the scene board plays when no public R2 URL exists yet.
RENDERS_DIR = PROJECT_ROOT / "data" / "renders"
RENDERS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/renders", NoCacheStaticFiles(directory=str(RENDERS_DIR)), name="renders")
# Every /api route now requires a session -- the /ui shell is gated, so
# its backing endpoints are too (401 JSON, which shared.js surfaces as a
# stateline). The legacy /studio pages stay open as the dev console.
app.include_router(api.router, dependencies=[Depends(auth.require_user_api)])
app.include_router(auth.router)


@app.get("/signin")
def signin(request: Request, error: Optional[str] = None,
           mode: Optional[str] = None, email: Optional[str] = None):
    """The sign-in screen: Google + Discord + email/password. Already
    signed in -> straight to the shell."""
    if auth.current_user(request):
        return RedirectResponse("/ui", status_code=303)
    return templates.TemplateResponse(
        request, "signin.html",
        {"error": error, "mode": mode if mode in ("signin", "signup") else "signin",
         "email": email,
         # live key presence, the /api/capabilities rule applied to the
         # modal: a provider button only renders when it can actually work
         "providers": {"google": auth._provider_configured("google"),
                       "discord": auth._provider_configured("discord")}})


@app.get("/ui/accounts")
def ui_accounts(request: Request):
    """The account picker -- or, for a signed-in user with no
    account_members row, the explicit no-access state. Membership is
    granted by members, never by signing up (the gate)."""
    user = auth.current_user(request)
    if user is None:
        return RedirectResponse("/signin", status_code=303)
    member_of = accounts_mod.memberships(user["id"], path=db.DB_PATH)
    return templates.TemplateResponse(
        request, "accounts.html", {"user": user, "member_of": member_of})


@app.get("/ui")
def ui(request: Request):
    """
    The ported ZPF Studio skin (prototype/studio.html made real): one
    shell, client-side views, every control backed by /api and gated by
    /api/capabilities. Requires a session; the active brand comes from
    real membership (current_account), not the raw cookie.
    """
    user = auth.current_user(request)
    if user is None:
        return RedirectResponse("/signin", status_code=303)
    account = auth.current_account(request, user)
    if account is None:
        # signed in, zero memberships: the no-access state, never a
        # silent grant into the real accounts
        return RedirectResponse("/ui/accounts", status_code=303)
    return templates.TemplateResponse(
        request, "zpf.html", {"brand": account["slug"], "user": user})


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
    # The CTA points at whichever workspace exists on this deployment:
    # /studio on the dev machine, /ui (behind sign-in) everywhere else --
    # a public front door must not link into a 404.
    return templates.TemplateResponse(
        request,
        "landing.html",
        {"site_url": seo.site_url(), "schema_json": seo.homepage_schema_json(),
         "studio_href": "/studio" if DEV_TOOLS else "/ui"},
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


# The assistant's vocabulary. Each intent is one pipeline stage; the
# phrases are what a person actually types when they mean it. Order
# matters -- the first intent with a matching phrase wins, so the more
# specific stages are checked before the catch-all.
#
# "ideas" phrases are deliberately plural/explicit ("ideas", "options",
# "slate") rather than the bare word "idea" -- someone describing one
# idea in the box ("I have an idea for...") should land on DEFAULT_INTENT
# (one concept for exactly that), not the multi-idea batch stage.
INTENT_PHRASES = [
    ("room", ("room", "space", "location", "photograph", "photo of", "scout")),
    ("plan", ("plan", "shot list", "shotlist", "storyboard", "board it", "break it down")),
    ("concept", ("full concept", "one concept", "whole concept", "concept for",
                 "make one", "single idea")),
    ("ideas", ("ideas", "deal", "pitch me", "options", "slate", "give me some")),
]

DEFAULT_INTENT = "concept"


def route_intent(text: str, explicit: Optional[str] = None) -> str:
    """
    What did the person just ask for? A chip sends its intent outright;
    free text is matched against INTENT_PHRASES.

    This is keyword routing, not a model call, and that is the point: the
    assistant orchestrates stages that each cost a real API call, so the
    routing itself has to be free, instant, and inspectable. A miss lands
    on concept -- one fully-formed idea for exactly what was typed (and
    whatever was attached), which is what "describe an idea, hit
    generate" almost always means. Ask for a slate explicitly ("give me
    some options") when a batch to sift through is actually wanted.
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


@app.post("/brand/{name}")
def set_brand(name: str, next: str = Form("/studio")):
    """Flip the active brand. Persists in a cookie so generation and the
    holds / analytics views follow it until you switch back."""
    brand = name if name in BRANDS else DEFAULT_BRAND
    resp = RedirectResponse(safe_next(next, "/studio"), status_code=303)
    resp.set_cookie("brand", brand, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


# --- the dev console --------------------------------------------------------
# Every route from here to the end of the file registers on `dev`, not
# `app`: /studio and the per-stage screens are the operator's engine
# room, and they exist only in the dev posture (the conditional
# include_router at the bottom of the file). The rule is "anything that
# isn't /ui, /api, auth, or the public landing surface is dev-only" --
# a new legacy-style page belongs on this router, not on `app`.
dev = APIRouter()


@dev.get("/dashboard")
def dashboard():
    """
    Gone. The app is one page now: what the dashboard showed -- counts,
    pick rate, top performers at equal age -- lives on the studio canvas,
    where it sits next to the work that produced it instead of on a
    screen you had to remember to visit. Kept as a redirect because it
    was the app's front door for months and is in muscle memory.
    """
    return RedirectResponse("/studio", status_code=308)


STUDIO_TABS = ("characters", "locations", "props", "director")


@dev.get("/studio")
def studio(request: Request, message: Optional[str] = None, tab: Optional[str] = None):
    """
    The workspace. Pre-production only now: the Workflow library
    (characters, rooms, props, and Director-ready AI shots) reads the
    DB, the canvas shows the latest AI shots, and the assistant runs the
    ideation stages under the hood. Reading is free of model calls and
    renders even when every source is absent.
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

    # Director tab: every planned AI shot for the ACTIVE BRAND only, with
    # its Director-ready prompt attached -- the same pure text composition
    # _with_director_prompts already does for /concepts (zero model calls,
    # so doing this on every page load costs nothing). Pulled out of the
    # dense per-concept storyboard into its own list, per Michael's call
    # that Director mode belongs under the Workflow tab rather than
    # buried in each concept card. ai_shots entries are the SAME dict
    # objects as in each concept's shots list (see preprod._concept_row),
    # so stamping director_prompt via _with_director_prompts also lands
    # on the ai_shots copies below -- one pass, not two.
    brand = active_brand(request)
    director_concepts = _with_director_prompts(
        [c for c in shoot_concepts if c.get("brand") == brand]
    )
    director_shots = []
    for c in director_concepts:
        for s in c.get("ai_shots") or []:
            s["concept_id"] = c["id"]
            s["concept_title"] = c.get("title")
            director_shots.append(s)

    active_tab = tab if tab in STUDIO_TABS else "characters"

    return templates.TemplateResponse(
        request,
        "studio.html",
        {
            "spaces": spaces,
            "characters": characters,
            "props": props,
            "shoot_concepts": shoot_concepts,
            "latest_ai": latest_ai,
            "director_shots": director_shots,
            "active_tab": active_tab,
            "active_nav": "home",
            "message": message,
        },
    )


def run_ideation(intent: str, *, brand: str, client_name, spark, use_pov: bool,
                  image_refs=None, picked_sources=None) -> str:
    """
    The two stages that generate from rooms. Split out of the route so
    the intent routing above can be read without the API plumbing
    underneath it. Returns the line to show on the canvas.

    `image_refs` (concept intent only) is a list of (bytes, mime_type)
    pairs -- ad hoc images dropped into the composer for this one
    generation. Dealing a slate of ideas is a batch operation; a photo
    only makes sense as grounding for the single concept it was
    attached to, so `ideas` never receives it.

    `picked_sources` names exact RAG source identifiers -- from the
    references picker (/references/pick) -- to ground this run on top
    of the automatic craft-advice layer. See shootgen.reference_block.
    """
    references = shootgen.reference_block(spark=spark, client=client_name,
                                          db_path=db.DB_PATH, picked_sources=picked_sources)
    gemini_client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    if intent == "concept":
        result = shootgen.generate_concept(
            brand=brand, client=client_name, spark=spark,
            gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
            references=references, image_refs=image_refs,
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


MAX_STUDIO_REFS = 6  # cap what a single composer submission sends to Gemini


async def _split_studio_references(files: List[UploadFile]) -> tuple:
    """
    Ad hoc references dropped into the composer for one generation --
    separate from the Workflow library's ingest-and-describe path.
    Images come back as (jpeg_bytes, "image/jpeg") pairs, ready to ride
    straight into the Gemini call as vision input. Video isn't fed to
    the model frame-by-frame (that needs the Files API, a bigger
    change than this composer warrants); instead each clip is pushed to
    R2 and its URL is folded into the spark text as a named reference,
    so it's still attached to the generation, just not literally seen.
    """
    import io
    import uuid

    from PIL import Image

    from src import storage

    image_refs = []
    video_note_lines = []
    for upload in files[:MAX_STUDIO_REFS]:
        filename = getattr(upload, "filename", "") or ""
        if not filename:
            continue
        content_type = (upload.content_type or "").lower()
        data = await upload.read()
        if content_type.startswith("image/"):
            try:
                jpeg = Image.open(io.BytesIO(data)).convert("RGB")
                buf = io.BytesIO()
                jpeg.save(buf, "JPEG", quality=90)
                image_refs.append((buf.getvalue(), "image/jpeg"))
            except Exception:
                continue  # not a real image -- skip rather than fail the whole generation
        elif content_type.startswith("video/") and storage.configured():
            try:
                tmp = Path("/tmp") / f"studio-ref-{uuid.uuid4().hex}{Path(filename).suffix}"
                tmp.write_bytes(data)
                url = storage.upload_file(
                    tmp, key=f"studio-refs/{tmp.name}", content_type=content_type)
                video_note_lines.append(f"Reference video ({filename}): {url}")
            except Exception:
                continue
    return image_refs, video_note_lines


@dev.post("/studio/assist")
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
    raw_form = await request.form()
    reference_files = [f for f in raw_form.getlist("references") if isinstance(f, UploadFile)]
    # exact RAG source names picked off /references/pick (a popup opened
    # from the composer's References button) -- the opt-in asset layer,
    # separate from the ad hoc image/video attachments above.
    picked_references = [s for s in raw_form.getlist("picked_references") if s.strip()]
    form = dict(raw_form)
    text = (form.get("text") or "").strip()
    intent = route_intent(text, (form.get("intent") or "").strip() or None)

    brand = form.get("brand") or active_brand(request)
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

    image_refs = None
    if reference_files:
        image_refs, video_notes = await _split_studio_references(reference_files)
        image_refs = image_refs or None
        if video_notes:
            spark = f"{spark or ''}\n" + "\n".join(video_notes)
            spark = spark.strip()

    try:
        message = run_ideation(intent, brand=brand, client_name=client_name,
                               spark=spark, use_pov=use_pov, image_refs=image_refs,
                               picked_sources=picked_references or None)
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


@dev.get("/videos/new")
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


@dev.post("/videos/new")
async def videos_new_submit(request: Request):
    form = dict(await request.form())
    parsed = parse_video_form(form)
    parsed.setdefault("brand", active_brand(request))  # tag to the active brand
    try:
        db.add_video(**parsed, path=db.DB_PATH)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/studio", status_code=303)


@dev.post("/videos/import/youtube")
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


@dev.get("/library")
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


@dev.post("/library/ingest")
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


@dev.post("/library/delete")
def library_delete(source: str = Form(...)):
    try:
        conn = rag.connect()
        removed = rag.delete_source(conn, source)
        conn.close()
        message = f"removed '{source}' ({removed} chunk(s))"
    except Exception as e:
        message = f"delete failed: {e}"
    return RedirectResponse("/library?message=" + quote(message), status_code=303)


@dev.get("/evals")
def evals_page(request: Request):
    """
    The retrieval-eval harness, dev-console edition: hit-rate history,
    the golden set, and the probe tool, on the legacy skin. Moved out of
    /ui (2026-08-25) -- evals are a developer instrument, not part of
    the signed-in product surface, which is also why it registers on
    `dev`: a public deployment has no /evals at all. The page is a
    shell; its data and actions come from the same /api/evals/* and
    /api/retrieve endpoints the old view used, so nothing is
    reimplemented here. Those routes require a session, and the page
    says so when it gets a 401 rather than pretending to be empty.
    """
    return templates.TemplateResponse(
        request, "evals.html", {"active_nav": "evals"})


@dev.get("/references/pick")
def references_pick(request: Request, message: Optional[str] = None):
    """
    The references picker: a focused page, opened as a popup from the
    Studio composer's or the Concepts form's References button, for
    grounding ONE generation on named assets from the RAG library --
    the opt-in counterpart to the always-on marketing/ai_prompting
    craft-advice layer (see shootgen.AUTO_IDEATION_DOMAINS /
    ASSET_IDEATION_DOMAINS). Selecting sources here never touches
    generation by itself; the page posts the selection back to the
    opener window (postMessage) and the opener rides it along as
    picked_references on its next Generate.
    """
    context = {"available": False, "sources": [], "domains": [],
              "message": message, "error": None, "active_nav": "workflow"}
    conn = None
    try:
        conn = rag.connect()
        context["sources"] = rag.list_sources(conn)
        context["domains"] = sorted({s["domain"] for s in context["sources"]})
        context["available"] = True
    except Exception as e:
        context["error"] = f"library unavailable: {e}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    # informational grouping only, so the picker can show "these already
    # ground automatically" -- picking one anyway is harmless, just
    # redundant, since fetch_by_sources and the automatic query would
    # both surface it.
    context["auto_domains"] = set(shootgen.AUTO_IDEATION_DOMAINS) | {"ai_prompting"}

    # Cast & props: the checkbox row that used to live directly on the
    # Concepts form now lives here instead, right next to the media
    # upload form -- one picker for everything a generation can be
    # grounded on, not two separate systems. Photo resolution mirrors
    # /studio's Workflow library exactly.
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
    context["characters"] = characters
    context["props"] = props

    return templates.TemplateResponse(request, "references_pick.html", context)


@dev.post("/references/pick/upload")
async def references_pick_upload(file: Optional[UploadFile] = File(None), domain: str = Form(""),
                                 project: str = Form(""), source_ref: str = Form("")):
    """
    Add a file straight from your computer to the RAG library, from the
    picker page -- the file-upload counterpart to /library/ingest's
    paste-text form. The uploaded bytes are never written into the repo;
    the file's own name becomes the source identifier, same as a manual
    /library entry lets you type any source name you like. Stays on the
    picker page (not /library) so you can immediately check the box for
    what you just added.
    """
    filename = (file.filename or "").strip() if file is not None else ""
    if not (filename and domain.strip()):
        return RedirectResponse(
            "/references/pick?message=" + quote("a file and a shelf (domain) are both required"),
            status_code=303,
        )
    try:
        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")
        if not text.strip():
            raise ValueError("file has no readable text")
        conn = rag.connect()
        rag.init_store(conn)
        written = rag.ingest_records(
            [{"source": filename, "text": text, "domain": domain.strip(),
              "project": project.strip() or None, "source_ref": source_ref.strip() or None}],
            rag.make_client(), conn,
        )
        conn.close()
        message = f"stored {written} chunk(s) from '{filename}' under '{domain.strip()}'"
    except Exception as e:
        message = f"upload failed: {e}"
    return RedirectResponse("/references/pick?message=" + quote(message), status_code=303)


@dev.get("/post-image")
def post_image_page(request: Request, url: Optional[str] = None,
                    caption: Optional[str] = None, message: Optional[str] = None):
    """A one-off publish surface: preview an image + caption, then post it
    to Instagram through the pipeline's gated autopilot path. Prefilled
    via ?url= & ?caption= so the trigger can hand it a hosted image."""
    return templates.TemplateResponse(
        request, "post_image.html",
        {"url": url or "", "caption": caption or "", "message": message,
         "active_nav": ""})


@dev.post("/post-image")
async def post_image_fire(request: Request):
    """Fire the post: one instagram post action through autopilot's
    three-condition gate (ZEROPAGE_AUTOPILOT=1 + this approve + no
    data/autopilot.off). instagram.execute_post_action posts an image
    when the action carries image_url."""
    form = dict(await request.form())
    image_url = (form.get("image_url") or "").strip()
    caption = (form.get("caption") or "").strip()

    def back(msg):
        return RedirectResponse(
            f"/post-image?message={quote(msg)}&url={quote(image_url)}"
            f"&caption={quote(caption)}", status_code=303)

    if not image_url:
        return back("Need a public image URL.")
    action = {"kind": "post", "platform": "instagram",
              "image_url": image_url, "caption": caption}
    try:
        result = autopilot.execute({"actions": [action]}, approve=True, dry_run=False)
    except Exception as e:
        return back(f"Post failed: {e}")
    mode = result.get("mode")
    if mode == "live" and result.get("executed"):
        media = (action.get("result") or {}).get("media_id")
        return back(f"Posted to Instagram ✅  (media id {media}).")
    if mode == "disabled":
        return back("Posting is OFF — set ZEROPAGE_AUTOPILOT=1 and restart.")
    if mode == "killed":
        return back("Autopilot kill switch is on (data/autopilot.off).")
    return back(f"Not posted (mode: {mode}).")


@dev.post("/post-image/queue")
async def post_image_queue(request: Request):
    """Semi-auto Midjourney path (BACKLOG #6): take a generated still -- an
    uploaded file or a public URL -- plus a caption, host it on R2 as a JPEG
    if it's a file (Meta rejects PNG/HEIC), and QUEUE it as a held image post
    on the Zero Page channel. You approve it on /holds and it publishes
    through the same gate. One-tap, not fully auto."""
    form = await request.form()
    caption = (form.get("caption") or "").strip()
    image_url = (form.get("image_url") or "").strip()
    channel = (form.get("channel") or "zeropage").strip() or "zeropage"
    upload = form.get("image_file")

    def back(msg):
        return RedirectResponse(
            f"/post-image?message={quote(msg)}&caption={quote(caption)}"
            f"&url={quote(image_url)}", status_code=303)

    # An uploaded file wins over a pasted URL: convert to JPEG and push to R2.
    if getattr(upload, "filename", ""):
        try:
            import io
            import uuid

            from PIL import Image

            from src import storage
            data = await upload.read()
            jpeg = Image.open(io.BytesIO(data)).convert("RGB")
            tmp = Path("/tmp") / f"mj-{uuid.uuid4().hex}.jpg"
            jpeg.save(tmp, "JPEG", quality=92)
            image_url = storage.upload_file(
                tmp, key=f"images/{tmp.name}", content_type="image/jpeg")
        except Exception as e:
            return back(f"Upload failed: {e}")

    if not image_url:
        return back("Add a Midjourney image — upload a file or paste a public JPEG URL.")

    hold_id = autonomy.to_hold(
        channel, "Midjourney image queued for approval", caption=caption,
        payload={"image_url": image_url}, status="held", path=db.DB_PATH)
    return RedirectResponse(
        "/holds?message=" + quote(f"Queued image post #{hold_id} for approval."),
        status_code=303)


@dev.get("/winners")
def winners_page(request: Request, prompt: Optional[str] = None,
                 tool: Optional[str] = None, verdict: Optional[str] = None,
                 message: Optional[str] = None):
    """Your outcome loop: paste the final, edited prompt that actually
    worked -- the one behind a finished piece you liked and that did well
    -- and it is saved and taught to the pipeline via the RAG
    'winning_prompts' shelf shootgen grounds on. Arrives prefilled when
    you hand a prompt over from /holds (?prompt=...)."""
    winners.init(path=db.DB_PATH)
    return templates.TemplateResponse(
        request, "winners.html",
        {"winners": winners.list_all(path=db.DB_PATH),
         "prefill_prompt": prompt or "",
         "prefill_tool": (tool or "runway").lower(),
         "prefill_verdict": (verdict or "worked").lower(),
         "message": message, "active_nav": "winners"},
    )


@dev.post("/winners")
async def winners_add(request: Request):
    """Save the winner durably, then teach it to the pipeline. Saving
    always succeeds; the RAG ingest is best-effort so a down store never
    loses the winner -- it just re-ingests later."""
    winners.init(path=db.DB_PATH)
    form = dict(await request.form())
    prompt = (form.get("prompt") or "").strip()
    if not prompt:
        return RedirectResponse(
            f"/winners?message={quote('A winning prompt cannot be empty.')}",
            status_code=303)
    result = winners.record_and_learn(
        form.get("tool") or "runway", prompt,
        note=form.get("note") or "", video_ref=form.get("video_ref") or "",
        verdict=form.get("verdict") or "worked", path=db.DB_PATH)
    verb = "avoid" if result.get("verdict") == "didnt_work" else "imitate"
    if result.get("ingested"):
        message = f"Saved and taught — future generations will {verb} it."
    else:
        message = ("Saved. Teaching is pending — start Postgres and re-save to "
                   f"ingest it into RAG. ({result.get('error') or 'store unavailable'})")
    return RedirectResponse(f"/winners?message={quote(message)}", status_code=303)


@dev.get("/holds")
def holds_list(request: Request, message: Optional[str] = None):
    """
    The morning ritual: what the graph wanted to post while you weren't
    looking, and the approve/reject that grades the evaluator. The
    agreement number is the credit gate -- ~0.9 over a real stretch is
    what earns a channel its promotion to auto.
    """
    # Full brand separation: show only the active brand's channel so the two
    # queues never blur (brand name maps 1:1 to channel name).
    brand = active_brand(request)
    concepts_by_id = {c["id"]: c for c in _with_director_prompts(
        preprod.list_concepts(path=db.DB_PATH))}
    held = [h for h in autonomy.list_hold(status="held", path=db.DB_PATH)
            if h["channel"] == brand]
    for row in held:
        row["concept"] = concepts_by_id.get(row.get("concept_id"))
    channels = autonomy.list_channels(path=db.DB_PATH)
    # a channel is postable when it may post AND names where to
    postable = {c["name"] for c in channels
                if c.get("autonomy") in ("queue", "auto")
                and (c.get("targets") or "").strip()}
    return templates.TemplateResponse(
        request,
        "holds.html",
        {
            "held": held,
            "agreement": autonomy.evaluator_agreement(path=db.DB_PATH),
            "gate": autonomy.prompt_gate_agreement(path=db.DB_PATH),
            "pass_rate": autonomy.first_try_pass_rate(path=db.DB_PATH),
            "channels": channels,
            "postable": postable,
            "killed": autonomy.killed(path=db.DB_PATH),
            "active_nav": "home",
            "message": message,
        },
    )


@dev.post("/holds/{hold_id}/resolve")
async def holds_resolve(hold_id: int, request: Request):
    """Approved = "I would have posted this" (the evaluator was right);
    rejected = "glad it held". Either way the row leaves the queue and
    feeds the agreement number -- and the same verdict lands next to the
    run's prompt scores, so the credit gate is graded against you too."""
    form = dict(await request.form())
    status = (form.get("status") or "").strip()
    row = next((h for h in autonomy.list_hold(status=None, path=db.DB_PATH)
                if h["id"] == hold_id), None)
    try:
        autonomy.resolve_hold(hold_id, status, path=db.DB_PATH)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    run_id = ((row or {}).get("payload") or {}).get("run_id") \
        if isinstance((row or {}).get("payload"), dict) else None
    if run_id and status in ("approved", "rejected"):
        autonomy.set_prompt_verdicts(
            run_id, "post" if status == "approved" else "reject", path=db.DB_PATH)
    return RedirectResponse("/holds", status_code=303)


@dev.post("/holds/{hold_id}/post")
async def holds_post(hold_id: int, request: Request):
    """Your explicit 'post now' -- the approval to publish. Builds one
    post action per channel target from the hold, then runs it through
    autopilot's three-condition gate (ZEROPAGE_AUTOPILOT=1 + this approve
    + no data/autopilot.off). Nothing uploads until real media and
    platform credentials exist; until then it reports exactly what's
    missing rather than pretending."""
    row = next((h for h in autonomy.list_hold(status=None, path=db.DB_PATH)
                if h["id"] == hold_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="no such hold")
    channel = autonomy.get_channel(row.get("channel", ""), path=db.DB_PATH) or {}
    targets = [t.strip() for t in (channel.get("targets") or "").split(",") if t.strip()]
    if not targets:
        return RedirectResponse(
            f"/holds?message={quote('This channel has no post targets.')}",
            status_code=303)

    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    caption = row.get("caption") or ""
    image_url = (payload.get("image_url") or "").strip()
    if image_url:
        # A queued Midjourney still: post it as an image, not a video.
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
            "video_url": media_url,                       # instagram fetches a public URL
            "video_path": media_url if is_local else "",  # youtube uploads a local file
        } for platform in targets]

    try:
        result = autopilot.execute({"actions": actions}, approve=True, dry_run=False)
    except Exception as e:
        return RedirectResponse(
            f"/holds?message={quote('Post failed: ' + str(e))}", status_code=303)

    mode = result.get("mode")
    if mode == "live" and result.get("executed"):
        autonomy.resolve_hold(hold_id, "posted", path=db.DB_PATH)
        msg = f"Posted to {', '.join(targets)}."
    elif mode == "live":
        msg = "Live, but nothing posted: " + "; ".join(
            result.get("skipped") or ["no rendered media to post yet"])
    elif mode == "disabled":
        msg = ("Posting is OFF — set ZEROPAGE_AUTOPILOT=1 and the platform "
               "credentials to go live.")
    elif mode == "killed":
        msg = "Autopilot kill switch is on (data/autopilot.off)."
    else:
        msg = f"Posting mode: {mode} — nothing was posted."
    return RedirectResponse(f"/holds?message={quote(msg)}", status_code=303)


@dev.post("/holds/note")
async def holds_note(request: Request):
    """A standing correction for the next run -- the human_note channel.
    The orchestrator folds pending notes into the next generation's
    spark and consumes them, so each note steers exactly once."""
    form = dict(await request.form())
    note = (form.get("note") or "").strip()
    if note:
        autonomy.add_correction(note, path=db.DB_PATH)
        message = "Noted — the next run folds it in."
    else:
        message = "An empty note steers nothing."
    return RedirectResponse(f"/holds?message={quote(message)}", status_code=303)


@dev.post("/channels/{name}/autonomy")
async def channels_autonomy(name: str, request: Request):
    """The promotion (or demotion): one row change. shadow -> queue ->
    auto is earned left to right by the agreement number; moving right
    is a deliberate click, never a default."""
    form = dict(await request.form())
    level = (form.get("autonomy") or "").strip()
    if autonomy.get_channel(name, path=db.DB_PATH) is None:
        raise HTTPException(status_code=404, detail="no such channel")
    try:
        autonomy.set_autonomy(name, level, path=db.DB_PATH)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(
        f"/holds?message={quote(f'{name} is now {level}')}", status_code=303)


@dev.post("/kill")
async def kill_toggle():
    """One place to pull the plug -- and to put it back. Global on
    purpose: every channel holds while it's on."""
    if autonomy.killed(path=db.DB_PATH):
        autonomy.unkill(path=db.DB_PATH)
        message = "Kill switch OFF — channels follow their own autonomy again."
    else:
        autonomy.kill("killed from /holds", path=db.DB_PATH)
        message = "Kill switch ON — everything holds."
    return RedirectResponse(f"/holds?message={quote(message)}", status_code=303)


@dev.get("/analytics")
@dev.get("/metrics/new")   # old URL, kept so bookmarks and habits still land
def analytics(request: Request, updated: Optional[int] = None, message: Optional[str] = None):
    # Scope to the active brand (NULL-inclusive: untagged legacy videos still
    # show, so nothing disappears while the pipeline tags new posts).
    brand = active_brand(request)
    rows = [r for r in db.latest_metrics_by_video(path=db.DB_PATH)
            if r.get("brand") in (None, brand)]

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


@dev.post("/metrics/new")
async def metrics_new_submit(request: Request):
    form = dict(await request.form())
    video_ids = [r["video_id"] for r in db.latest_metrics_by_video(path=db.DB_PATH)]
    changed = parse_metrics_form(form, video_ids)
    for vid, fields in changed.items():
        db.record_metrics(vid, path=db.DB_PATH, **fields)
    return RedirectResponse(f"/analytics?updated={len(changed)}", status_code=303)


@dev.post("/metrics/refresh/{video_id}")
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


@dev.get("/videos/{video_id}")
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


def _redirect_with_message(destination: str, message: str) -> RedirectResponse:
    """Every mutating route in this file ends with `?message=...` tacked
    onto wherever it's sending the person next. Split out so the join
    (`?` the first time, `&` after) is right regardless of whether
    `destination` already carries a query string -- `/assets?tab=props`
    plus a message needs `&`, a bare `/assets` needs `?`."""
    sep = "&" if "?" in destination else "?"
    return RedirectResponse(f"{destination}{sep}message={quote(message)}", status_code=303)


ASSET_TABS = ("locations", "characters", "props")


@dev.get("/assets")
def assets_list(request: Request, tab: Optional[str] = None, message: Optional[str] = None):
    """
    Locations, characters, and props were three separate rail items
    pointing at three near-identical CRUD pages -- same grid, same
    add-dialog, same "a name and some photos" shape. They're one
    concept (what a concept can be grounded in or cast with), so they
    live under one Assets item now, tab-switched client-side. The old
    /locations, /characters, /props URLs still work below -- they just
    redirect here on the matching tab, so nothing bookmarked breaks.
    """
    active_tab = tab if tab in ASSET_TABS else "locations"

    spaces = preprod.list_locations(path=db.DB_PATH)
    for space in spaces:
        space["photos"] = photos_for(space["name"])

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

    return templates.TemplateResponse(
        request,
        "assets.html",
        {
            "locations": spaces,
            "characters": characters,
            "props": props,
            "active_tab": active_tab,
            "active_nav": "assets",
            "message": message,
        },
    )


def _redirect_to_assets_tab(tab: str, message: Optional[str]) -> RedirectResponse:
    url = f"/assets?tab={tab}"
    if message:
        url += f"&message={quote(message)}"
    return RedirectResponse(url, status_code=308)


@dev.get("/locations")
def locations_list(message: Optional[str] = None):
    return _redirect_to_assets_tab("locations", message)


@dev.get("/locations/{space}/photo/{filename}")
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


@dev.post("/locations/upload")
async def locations_upload(name: str = Form(...), next: str = Form(""),
                           photos: List[UploadFile] = File(default=[])):
    destination = safe_next(next, "/assets?tab=locations")
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
        return _redirect_with_message(
            destination,
            "Photos saved, but GEMINI_API_KEY is not set so they were not described",
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

    # `destination` (not a hardcoded /locations) so a caller who passed a
    # `next` -- the Studio composer, /assets?tab=locations -- actually
    # lands back where they asked to, not on the old standalone page.
    return _redirect_with_message(destination, message)


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


@dev.get("/characters")
def characters_list(message: Optional[str] = None):
    return _redirect_to_assets_tab("characters", message)


@dev.get("/characters/{slug}/photo/{filename}")
def character_photo(slug: str, filename: str, thumb: Optional[int] = None):
    return _entity_photo_response(CHARACTERS_DIR, slug, filename, thumb)


@dev.post("/characters/new")
async def characters_new(name: str = Form(...), role: str = Form(""),
                         notes: str = Form(""), next: str = Form(""),
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
    destination = safe_next(next, "/assets?tab=characters")
    return _redirect_with_message(destination, "Added " + name)


@dev.post("/characters/{character_id}/delete")
def characters_delete(character_id: int, next: str = Form("")):
    entities.delete_character(character_id, path=db.DB_PATH)
    destination = safe_next(next, "/assets?tab=characters")
    return _redirect_with_message(destination, "Deleted")


@dev.get("/props")
def props_list(message: Optional[str] = None):
    return _redirect_to_assets_tab("props", message)


@dev.get("/props/{slug}/photo/{filename}")
def prop_photo(slug: str, filename: str, thumb: Optional[int] = None):
    return _entity_photo_response(PROPS_DIR, slug, filename, thumb)


@dev.post("/props/new")
async def props_new(name: str = Form(...), category: str = Form(""),
                    notes: str = Form(""), next: str = Form(""),
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
    destination = safe_next(next, "/assets?tab=props")
    return _redirect_with_message(destination, "Added " + name)


@dev.post("/props/{prop_id}/delete")
def props_delete(prop_id: int, next: str = Form("")):
    entities.delete_prop(prop_id, path=db.DB_PATH)
    destination = safe_next(next, "/assets?tab=props")
    return _redirect_with_message(destination, "Deleted")


def _with_director_prompts(concepts: list) -> list:
    """Attach the OpenArt Director rendering to every planned shot --
    pure text composition (shootgen.director_prompt), zero model calls,
    so doing it for every card on every page load costs nothing. Jinja
    can't call functions, so the route computes what the template shows."""
    for c in concepts:
        for s in c.get("shots") or []:
            s["director_prompt"] = shootgen.director_prompt(s, c)
    return concepts


@dev.post("/concepts/{concept_id}/shots/{shot_n}/reference")
async def concept_shot_reference(concept_id: int, shot_n: int, request: Request):
    """Attach (or clear) the real capture behind one shot -- the acting
    take or room plate its AI generation anchors on. A file is hosted on
    R2 as a JPEG (the /post-image/queue shape exactly); a pasted public
    URL is stored as-is. Every shot is AI-generated now -- a capture is
    reference material feeding the generation, not the delivered shot."""
    form = await request.form()
    destination = safe_next(form.get("next") or "", "/concepts")

    def back(msg):
        return _redirect_with_message(destination, msg)

    try:
        if form.get("remove"):
            preprod.set_shot_reference_image(concept_id, shot_n, "", path=db.DB_PATH)
            return back(f"Reference cleared from shot {shot_n}.")

        image_url = (form.get("reference_url") or "").strip()
        upload = form.get("reference_file")
        if getattr(upload, "filename", ""):
            try:
                import io
                import uuid

                from PIL import Image

                from src import storage
                data = await upload.read()
                jpeg = Image.open(io.BytesIO(data)).convert("RGB")
                tmp = Path("/tmp") / f"ref-{uuid.uuid4().hex}.jpg"
                jpeg.save(tmp, "JPEG", quality=92)
                image_url = storage.upload_file(
                    tmp, key=f"references/{tmp.name}", content_type="image/jpeg")
            except Exception as e:
                return back(f"Reference upload failed: {e}")
        if not image_url:
            return back("Attach a capture — a file, or a public image URL.")
        preprod.set_shot_reference_image(concept_id, shot_n, image_url, path=db.DB_PATH)
    except ValueError as e:
        return back(str(e))
    return back(f"Reference attached to shot {shot_n} — the AI generation anchors on it.")


@dev.post("/concepts/{concept_id}/verdict")
async def concept_verdict(concept_id: int, request: Request):
    """Subtle approve/deny on a whole concept or idea, with the idea text
    editable right there -- records straight through winners.py's existing
    teaching loop (the same one /winners already exposes as its own page),
    so a click on the card is a click on /winners without leaving it. Worked
    -> winning_prompts (future ideation imitates it); Didn't work ->
    avoid_prompts (future ideation is told to steer away from it)."""
    form = dict(await request.form())
    destination = safe_next(form.get("next") or "", "/concepts")
    text = (form.get("text") or "").strip()
    if not text:
        return _redirect_with_message(destination, "Nothing to record — the text was empty.")
    verdict = "didnt_work" if (form.get("verdict") or "worked") == "didnt_work" else "worked"
    result = winners.record_and_learn(
        "concept", text, note=form.get("note") or "",
        video_ref=f"concept-{concept_id}", verdict=verdict, path=db.DB_PATH)
    verb = "steer away from" if verdict == "didnt_work" else "imitate"
    if result.get("ingested"):
        message = f"Recorded SHOOT-{concept_id:02d} — future ideation will {verb} it."
    else:
        message = ("Saved. Teaching is pending — start Postgres and try again to "
                   f"ingest it into RAG. ({result.get('error') or 'store unavailable'})")
    return _redirect_with_message(destination, message)


@dev.post("/concepts/{concept_id}/shots/{shot_n}/verdict")
async def concept_shot_verdict(concept_id: int, shot_n: int, request: Request):
    """Subtle approve/deny on one AI shot's render prompt, with the prompt
    text editable right there before it's taught -- same winners.py loop as
    above, scoped to the exact prompt that would go to Runway/Higgsfield."""
    form = dict(await request.form())
    destination = safe_next(form.get("next") or "", "/concepts")
    text = (form.get("text") or "").strip()
    if not text:
        return _redirect_with_message(destination, "Nothing to record — the prompt was empty.")
    verdict = "didnt_work" if (form.get("verdict") or "worked") == "didnt_work" else "worked"
    tool = (form.get("tool") or "runway").strip().lower()
    result = winners.record_and_learn(
        tool, text, note=form.get("note") or "",
        video_ref=f"concept-{concept_id}-shot-{shot_n}", verdict=verdict, path=db.DB_PATH)
    verb = "avoid" if verdict == "didnt_work" else "imitate"
    if result.get("ingested"):
        message = f"Recorded shot {shot_n} — future generations will {verb} it."
    else:
        message = ("Saved. Teaching is pending — start Postgres and try again to "
                   f"ingest it into RAG. ({result.get('error') or 'store unavailable'})")
    return _redirect_with_message(destination, message)


@dev.get("/concepts")
def concepts_list(request: Request, message: Optional[str] = None):
    spaces = preprod.list_locations(path=db.DB_PATH)
    for space in spaces:
        space["photos"] = photos_for(space["name"])
    return templates.TemplateResponse(
        request,
        "concepts.html",
        {
            # Brand-scoped (BACKLOG #7): switching the active brand changes
            # which concepts you see, so the switch is visible here too.
            "concepts": _with_director_prompts(
                [c for c in preprod.list_concepts(path=db.DB_PATH)
                 if c["brand"] == active_brand(request)]),
            "rate": preprod.shoot_rate(path=db.DB_PATH),
            "shortlist": preprod.shortlist_rate(path=db.DB_PATH),
            "inspirations": inspiration.list_accounts(path=db.DB_PATH),
            "scene_briefs": preprod.list_scene_briefs(brand=active_brand(request),
                                                      path=db.DB_PATH),
            "brands": preprod.BRANDS,
            "spaces": spaces,
            "has_locations": bool(spaces),
            "characters": entities.list_characters(path=db.DB_PATH),
            "props": entities.list_props(path=db.DB_PATH),
            "active_nav": "tools",
            "message": message,
        },
    )


@dev.post("/concepts/{concept_id}/grade")
def concepts_grade(concept_id: int):
    """Score one concept on taste fit + predicted performance (BACKLOG #5)
    against your own history, and store it so the card shows it. One billed
    model call, on your click -- never automatic."""
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        raise HTTPException(status_code=404, detail="no such concept")
    judge = taste_judge.score_concept(concept, db_path=db.DB_PATH)
    preprod.save_judge_score(concept_id, judge, path=db.DB_PATH)
    if judge.get("graded"):
        msg = (f"Graded SHOOT-{concept_id:02d}: {judge['overall']:.0f}/10 "
               f"(taste {judge['taste_fit']:.0f}, perf {judge['performance']:.0f})")
    else:
        msg = f"SHOOT-{concept_id:02d}: " + (judge.get("reasons") or ["not graded"])[0]
    return RedirectResponse(f"/concepts?message={quote(msg)}", status_code=303)


@dev.post("/concepts/{concept_id}/discard")
def concepts_discard(concept_id: int):
    """Discard a concept you don't want. Deletes it (locations cascade)."""
    if preprod.get_concept(concept_id, path=db.DB_PATH) is None:
        raise HTTPException(status_code=404, detail="no such concept")
    preprod.delete_concept(concept_id, path=db.DB_PATH)
    return RedirectResponse(
        "/concepts?message=" + quote(f"Discarded SHOOT-{concept_id:02d}."),
        status_code=303)


@dev.post("/concepts/discard-all")
def concepts_discard_all(request: Request):
    """Clear every concept for the active brand -- a fresh slate when the
    generator's slate isn't landing."""
    brand = active_brand(request)
    n = preprod.delete_all_concepts(brand=brand, path=db.DB_PATH)
    return RedirectResponse(
        "/concepts?message=" + quote(f"Discarded all {n} {brand} concept(s)."),
        status_code=303)


@dev.post("/concepts/grade-all")
def concepts_grade_all():
    """Grade every not-yet-graded concept against your history. Each is one
    billed call, so this is an explicit button, not automatic. Signals are
    gathered once and reused across the batch."""
    concepts = preprod.list_concepts(path=db.DB_PATH)
    signals = taste_judge.gather_signals(db_path=db.DB_PATH)
    graded = 0
    for c in concepts:
        if c.get("judge_overall") is None:
            judge = taste_judge.score_concept(c, signals=signals, db_path=db.DB_PATH)
            preprod.save_judge_score(c["id"], judge, path=db.DB_PATH)
            graded += 1
    return RedirectResponse(
        "/concepts?message=" + quote(f"Graded {graded} concept(s)."), status_code=303)


@dev.post("/concepts/scene-brief/{brief_id}/delete")
def scene_brief_delete(brief_id: int):
    preprod.delete_scene_brief(brief_id, path=db.DB_PATH)
    return RedirectResponse(
        "/concepts?message=" + quote(f"Discarded scene brief #{brief_id}."),
        status_code=303)


@dev.post("/inspiration/add")
def inspiration_add(handle: str = Form(...), note: str = Form(""), profile: str = Form(...)):
    """Add or update an inspiration account -- e.g. once you've pasted posts
    for an account I couldn't reach."""
    try:
        inspiration.add(handle, note, profile, path=db.DB_PATH)
        msg = f"Saved inspiration @{handle.lstrip('@').strip().lower()}."
    except ValueError as e:
        msg = str(e)
    return RedirectResponse("/concepts?message=" + quote(msg), status_code=303)


@dev.post("/inspiration/{handle}/delete")
def inspiration_delete(handle: str):
    inspiration.delete(handle, path=db.DB_PATH)
    return RedirectResponse(
        "/concepts?message=" + quote(f"Removed inspiration @{handle}."), status_code=303)


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


@dev.post("/concepts/generate")
async def concepts_generate(request: Request):
    form_data = await request.form()
    form = dict(form_data)
    brand = form.get("brand") or active_brand(request)
    spark = (form.get("spark") or "").strip() or None
    client_name = (form.get("client") or "").strip() or None
    # an unchecked checkbox submits nothing, so absence means off
    use_pov = bool(form.get("use_pov"))
    cast = cast_from_picks(form_data.getlist("characters"), form_data.getlist("props"))
    # None picked means every room on file (unchanged default); picking one
    # or more is a deliberate "shoot here" for this run, not a shortage --
    # see shootgen._apply_location_lock.
    only_locations = form_data.getlist("locations") or None
    # exact RAG source names picked off /references/pick -- the opt-in
    # asset layer, on top of reference_block's automatic craft-advice one.
    picked_references = [s for s in form_data.getlist("picked_references") if s.strip()]

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return RedirectResponse(
            f"/concepts?message={quote('GEMINI_API_KEY not set')}", status_code=303,
        )

    # Grounding is an enhancement, never a dependency: reference_block
    # degrades to "" (with a stderr note) if the library is unreachable.
    references = shootgen.reference_block(spark=spark, client=client_name,
                                          db_path=db.DB_PATH,
                                          picked_sources=picked_references or None)

    # Under the hood: every brand grounds automatically on its own
    # inspiration accounts (no button) -- brand-scoped so ANTIHERO's
    # moto/noir personal-brand riffs never leak into Zero Page's
    # faceless/uncanny ideation, and vice versa. Injected as reference
    # grounding so it steers the ideas without polluting the stored spark.
    insp = inspiration.combined_grounding(brand=brand, path=db.DB_PATH)
    if insp:
        references = insp + "\n\n" + (references or "")

    # Generating is the deliverable, but a failed generation should leave
    # the screen usable rather than 500 -- same contract as the YouTube import.
    try:
        gemini_client = genai.Client(api_key=api_key)
        mode = (form.get("mode") or "").strip()
        if mode == "scene":
            result = shootgen.generate_scene_brief(
                brand=brand, spark=spark, gemini_client=gemini_client,
                references=references, cast=cast,
            )
            preprod.save_scene_brief(brand, result["title"], result["brief"],
                                     spark=spark, path=db.DB_PATH)
            message = f'Wrote scene brief "{result["title"]}" — copy it into your video model'
        elif mode == "ideas":
            result = shootgen.generate_concept_ideas(
                brand=brand, client=client_name, spark=spark,
                gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
                references=references, only_locations=only_locations,
            )
            message = f"Generated {len(result['ideas'])} ideas — plan the ones worth shooting"
        else:
            result = shootgen.generate_concept(
                brand=brand, client=client_name, spark=spark,
                gemini_client=gemini_client, use_pov=use_pov, db_path=db.DB_PATH,
                references=references, cast=cast, only_locations=only_locations,
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


@dev.post("/concepts/{concept_id}/shotlist")
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


@dev.post("/concepts/{concept_id}/shot")
def concepts_mark_shot(concept_id: int, next: str = Form("")):
    concept = preprod.get_concept(concept_id, path=db.DB_PATH)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")

    preprod.mark_shot(concept_id, shot=not concept["shot_done"], path=db.DB_PATH)
    return RedirectResponse(safe_next(next, "/concepts"), status_code=303)


# The posture switch (see DEV_TOOLS at the top): on a public deployment
# this include never runs, so the dev console isn't hidden -- it doesn't
# exist. This must stay the last statement so every @dev route above is
# already registered on the router when it lands on the app.
if DEV_TOOLS:
    app.include_router(dev)

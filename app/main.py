"""
The web app: reads the same database the pipeline writes to. No build
step, no framework, no component library -- vanilla Jinja2 and CSS.

This session is the skeleton only: the dashboard route, reading real
data through src/db.py, proving it reaches the page. The full
dashboard design (top performers, sparklines, pick rate) is Session 4.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src import db

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(path=db.DB_PATH)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.get("/")
def dashboard(request: Request):
    counts = db.summary(path=db.DB_PATH)
    pitches = db.get_labelled_pitches(limit=10, path=db.DB_PATH)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"counts": counts, "pitches": pitches},
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

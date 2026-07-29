"""
The web app: reads the same database the pipeline writes to. No build
step, no framework, no component library -- vanilla Jinja2 and CSS.

This session is the skeleton only: the dashboard route, reading real
data through src/db.py, proving it reaches the page. The full
dashboard design (top performers, sparklines, pick rate) is Session 4.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src import db

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.get("/")
def dashboard(request: Request):
    counts = db.summary()
    pitches = db.get_labelled_pitches(limit=10)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"counts": counts, "pitches": pitches},
    )

#!/usr/bin/env python3
"""
src/framebank.py -- Michael's own footage, as searchable reference stills.

    footage/*.mov  --ffmpeg-->  data/frames/*.jpg  --Gemini-->  captions
                                                                   |
                                          imagesearch.search() <---'

WHY THIS EXISTS. On 2026-09-02 the research agent banked eleven
reference images and every one was wrong: it had no image-search tool,
so it guessed stock URLs from memory, and a generic CDN serves *a* photo
for almost any guess. `refbin.fetch` succeeded eleven times while
banking a sunny tree for "bark texture" and a branded Harley product
shot onto a faceless-brand scene -- with six Unsplash source pages that
404. Nothing in the chain checked that the bytes matched the intent.

The fix is not a better prompt. It is a CLOSED SET: the agent may only
bank an image the server itself found and can hand back by id, so there
is no URL field for it to invent. This module supplies the half of that
set which is genuinely his -- 149GB of ProRes in `footage/`, shot on his
own camera, in his own garage, with nobody's licence to worry about.

WHAT IS ACTUALLY IN THERE (probed 2026-09-02, by looking): 37 clips,
~70 minutes. `A037_*` is the cinema camera at 3072x1728; `DJI_*` is a
pocket camera at 1920x1440 (4:3, and shot physically sideways on some
takes -- there is no rotation metadata to correct, that is just how it
was held). Every clip is motorcycle build and garage work, which makes
this an ANTIHERO source. Zero Page gets nothing from it and is served by
`imagesearch`'s outside lanes instead.

THE CONTRAST PASS IS A LEGIBILITY FIX, NOT A GRADE. The clips are tagged
bt709 on every colour field and still come out milky -- a log profile
baked in and mislabelled. Left alone, every frame reads as washed-out
haze and a model grounded on one learns the haze. The `eq` filter below
only restores enough contrast for the frame to describe its own
composition; it deliberately does not try to be the brand's night grade,
because a reference that asserts a grade competes with the prompt that
specifies one.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from . import db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FOOTAGE_DIR = PROJECT_ROOT / "footage"
FRAMES_DIR = PROJECT_ROOT / "data" / "frames"

# One frame every this many seconds. 30s over ~70 minutes is ~140
# frames, which is a searchable bank and a survivable captioning bill;
# denser sampling buys near-duplicates, because these are long locked-off
# takes rather than cut sequences.
EVERY_SECONDS = 30
# Nothing from the first or last moment of a take -- those are the frames
# with a hand still on the camera.
EDGE_TRIM = 2.0
FRAME_WIDTH = 960
# Modest, and the same for every frame so the bank stays internally
# consistent. See the module docstring on why this is not a grade.
CONTRAST_FILTER = "eq=contrast=1.30:saturation=1.12:gamma=0.97"

SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    clip       TEXT NOT NULL,
    t_sec      REAL NOT NULL,
    path       TEXT NOT NULL,
    caption    TEXT,
    tags       TEXT,
    brand      TEXT
);
CREATE INDEX IF NOT EXISTS idx_frames_clip ON frames (clip, t_sec);
"""


def init(path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def frame_id(clip: str, t_sec: float) -> str:
    """Stable per (clip, second), so re-running the build updates a row
    rather than growing a second one for the same moment."""
    return hashlib.sha1(f"{clip}@{t_sec:.1f}".encode()).hexdigest()[:16]


def clips(footage_dir: Optional[Path] = None) -> list[Path]:
    d = footage_dir or FOOTAGE_DIR
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir()
                  if p.suffix.lower() in (".mov", ".mp4", ".m4v"))


def duration(clip: Path) -> float:
    """Seconds, or 0.0 for anything ffprobe cannot read. Never raises --
    an unreadable clip is one clip skipped, not a failed build."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(clip)],
            capture_output=True, text=True, timeout=60)
        return float((out.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def sample_times(length: float, every: float = EVERY_SECONDS) -> list[float]:
    """Where to cut. Starts one interval in rather than at zero: the
    first frame of a take is the one with a hand still on the camera."""
    if length <= EDGE_TRIM * 2:
        return [round(length / 2, 1)] if length > 0 else []
    t, out = every, []
    while t < length - EDGE_TRIM:
        out.append(round(t, 1))
        t += every
    return out or [round(length / 2, 1)]


def extract(clip: Path, times: list[float], out_dir: Optional[Path] = None) -> list[dict]:
    """One jpg per timestamp. `-ss` BEFORE `-i` so ffmpeg seeks instead
    of decoding to the mark -- on a 3.5GB ProRes file that is the
    difference between a second and a minute, and this runs 140 times.

    Never raises. A clip that fails is reported by its absence.
    """
    out_dir = out_dir or FRAMES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for t in times:
        fid = frame_id(clip.name, t)
        dest = out_dir / f"{fid}.jpg"
        if not dest.is_file():
            try:
                subprocess.run(
                    ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(t),
                     "-i", str(clip), "-frames:v", "1",
                     "-vf", f"scale={FRAME_WIDTH}:-2,{CONTRAST_FILTER}",
                     "-q:v", "4", "-y", str(dest)],
                    capture_output=True, timeout=120)
            except Exception:
                continue
        if dest.is_file() and dest.stat().st_size > 0:
            made.append({"id": fid, "clip": clip.name, "t_sec": t,
                         "path": str(dest)})
    return made


CAPTION_PROMPT = """These are frames from a filmmaker's own footage, to be used as
REFERENCE for AI video generation -- what the camera is doing, what the light is
doing, what is in the frame.

For each image in order, return one line of JSON:
{"n": <index>, "caption": "<one sentence: subject, framing, light>",
 "tags": ["<4-8 short tags: surfaces, objects, camera position, light>"]}

Describe what is THERE. Do not invent a story, do not name people, do not
guess a brand. If a frame is unusable -- a hand over the lens, pure blur,
a blank wall with nothing in it -- say so in the caption and tag it
"unusable", because a bank that keeps those wastes a reference slot.

Return one JSON object per line, nothing else."""


def caption(frames: list[dict], client, model: str, batch: int = 8) -> list[dict]:
    """Ask a vision model what each frame shows. Batched, because 140
    single-image calls is 140 round trips for a job that is one prompt
    and a list.

    Frames it cannot caption keep `caption=None` and stay in the bank
    uncaptioned -- searchable by clip name, and re-captionable on the
    next build without re-extracting.
    """
    from google.genai import types

    out = []
    for i in range(0, len(frames), batch):
        chunk = frames[i:i + batch]
        parts = [CAPTION_PROMPT]
        for n, f in enumerate(chunk, 1):
            try:
                data = Path(f["path"]).read_bytes()
            except OSError:
                continue
            parts.append(f"--- image {n} ---")
            parts.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
        try:
            resp = client.models.generate_content(model=model, contents=parts)
            lines = [ln for ln in (getattr(resp, "text", "") or "").splitlines()
                     if ln.strip().startswith("{")]
        except Exception:
            lines = []
        by_n = {}
        for ln in lines:
            try:
                row = json.loads(ln)
                by_n[int(row.get("n", 0))] = row
            except Exception:
                continue
        for n, f in enumerate(chunk, 1):
            row = by_n.get(n) or {}
            out.append({**f,
                        "caption": (row.get("caption") or "").strip() or None,
                        "tags": [str(t) for t in (row.get("tags") or [])]})
    return out


def record(frame: dict, brand: str = "antihero", path=db.DB_PATH) -> None:
    init(path)
    with db.connect(path) as conn:
        conn.execute(
            "INSERT INTO frames (id, created_at, clip, t_sec, path, caption, "
            "tags, brand) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET caption=excluded.caption, "
            "tags=excluded.tags, path=excluded.path",
            (frame["id"], _now(), frame["clip"], float(frame["t_sec"]),
             frame["path"], frame.get("caption"),
             json.dumps(frame.get("tags") or []), brand))


_WORD = re.compile(r"[a-z0-9]+")


def _score(query: str, caption: str, tags: list) -> float:
    """Token overlap, tags weighted double.

    Deliberately not embeddings. The bank is ~140 rows of one-sentence
    captions; a vector store would be a dependency, a migration and a
    second thing that can be stale, to rank a list short enough to read.
    """
    q = set(_WORD.findall((query or "").lower()))
    if not q:
        return 0.0
    cap = set(_WORD.findall((caption or "").lower()))
    tag = set(_WORD.findall(" ".join(tags or []).lower()))
    return (len(q & cap) + 2 * len(q & tag)) / len(q)


def search(query: str, brand: Optional[str] = None, limit: int = 6,
           path=db.DB_PATH) -> list[dict]:
    """Best-matching frames, highest first. Never raises: a missing table
    means this lane contributes nothing, which is a thin search rather
    than a failed one."""
    try:
        init(path)
        with db.connect(path) as conn:
            sql = "SELECT * FROM frames"
            args: list = []
            if brand:
                sql += " WHERE brand = ?"
                args.append(brand)
            rows = [dict(r) for r in conn.execute(sql, args)]
    except Exception:
        return []
    scored = []
    for r in rows:
        try:
            tags = json.loads(r.get("tags") or "[]")
        except Exception:
            tags = []
        # An unusable frame stays in the table (so the next build does not
        # re-extract it) and never reaches a search result.
        if "unusable" in [t.lower() for t in tags]:
            continue
        s = _score(query, r.get("caption") or "", tags)
        if s > 0:
            scored.append((s, {**r, "tags": tags}))
    scored.sort(key=lambda p: -p[0])
    return [r for _s, r in scored[:max(1, limit)]]


def build(brand: str = "antihero", client=None, model: str = "",
          footage_dir: Optional[Path] = None, path=db.DB_PATH,
          every: float = EVERY_SECONDS, limit_clips: int = 0) -> dict:
    """Extract, caption and record the whole bank. Idempotent: a frame
    already on disk is not re-cut, and `record` upserts, so a re-run
    after adding footage costs only the new clips."""
    init(path)
    found = clips(footage_dir)
    if limit_clips:
        found = found[:limit_clips]
    made: list[dict] = []
    for clip in found:
        length = duration(clip)
        if length <= 0:
            continue
        made += extract(clip, sample_times(length, every))
    captioned = (caption(made, client, model) if client and made
                 else [{**f, "caption": None, "tags": []} for f in made])
    for f in captioned:
        record(f, brand=brand, path=path)
    return {"clips": len(found), "frames": len(captioned),
            "captioned": len([f for f in captioned if f.get("caption")])}

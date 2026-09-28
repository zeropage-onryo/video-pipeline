"""
app/cut_routes.py -- /api/cut, the Export button's server half (Assemble v0,
docs/tasks/CUT_ASSEMBLE_V0.md).

    GET  /api/cut/ready                  rendered scenes a cut can be made from
    POST /api/cut/assemble               concept -> timeline v(N+1) -> MP4 (a job)
    POST /api/cut/media                  upload a music bed / voiceover -> asset:<id>
    GET  /api/cut/{concept_id}/timeline  the head doc + the version chain
    POST /api/cut/{concept_id}/rollback  move the head; nothing is deleted

Included into app/api.py's router at the bottom of that file, so every
route sits under /api, behind the session gate, and inside
tests/test_tenancy.py's route audit. Every route resolves the account
through `auth.current_account_id` and passes it down; the store and the
source lookups are scoped by it, so another account's concept, timeline
or upload answers exactly like a missing one.

Nothing here spends: the render is ffmpeg on this box, and no ledger hold
is taken. A refusal the person can act on (a shot with no clip yet, a
clip missing from the Asset Bank) is answered BEFORE a job starts.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Optional, Union

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src import preprod
from src.cut import assemble as cut_assemble
from src.cut import render as cut_render
from src.cut import sources as cut_sources
from src.cut import store as cut_store
from src.cut.doc import parse_handle

from . import auth, jobs

router = APIRouter(prefix="/cut")

MEDIA_DIR = cut_render.CUT_DIR / "media"
MAX_MEDIA_BYTES = 100 * 1024 * 1024
AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
               ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac"}


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, **extra}})


def _mint(stored: Optional[str], account_id: Optional[int]) -> Optional[str]:
    if not stored:
        return None
    from src import media
    return media.url_for(stored, account_id)


# --------------------------------------------------------------------------
# what can be cut
# --------------------------------------------------------------------------

@router.get("/ready")
def cut_ready(brand: Optional[str] = None,
              account_id: int = Depends(auth.current_account_id)):
    """Concepts whose every slot has a clip, not archived -- the scenes
    that left the Queue by being rendered. Each carries the head
    version's export, if there is one."""
    rows = preprod.list_concepts(100, account_id=account_id, brand=brand, lean=True)
    ready = []
    for c in rows:
        if c.get("archived_at"):
            continue
        slots = cut_assemble.clip_slots(c)
        if not slots or not all(s["media_url"] for s in slots):
            continue
        ready.append({"concept_id": c["id"], "title": c.get("title") or f"Concept #{c['id']}",
                      "brand": c.get("brand"), "clips": len(slots),
                      "poster": (c.get("shots") or [{}])[0].get("reference_image")})
    exports = cut_store.latest_exports(
        [cut_store.project_for_concept(r["concept_id"]) for r in ready], account_id=account_id)
    for r in ready:
        head = exports.get(cut_store.project_for_concept(r["concept_id"]))
        r["export"] = ({"timeline_id": head["timeline_id"], "version": head["version"],
                        "url": _mint(head.get("export_url"), account_id)} if head else None)
    return {"ready": ready, "ffmpeg": bool(cut_sources.ffmpeg_bin()),
            "captions_burn": cut_render.can_burn_captions()}


# --------------------------------------------------------------------------
# assemble + export
# --------------------------------------------------------------------------

class Cue(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=400)


class AssembleBody(BaseModel):
    concept_id: int
    music: Optional[str] = Field(default=None, max_length=40)
    voice: Optional[str] = Field(default=None, max_length=40)
    captions: Optional[Union[str, list[Cue]]] = None


def _check_asset(handle: Optional[str], account_id: int) -> Optional[str]:
    if handle is None:
        return None
    parsed = parse_handle(handle)
    if not parsed or parsed[0] != "asset":
        return f"{handle!r} is not an asset:<id> handle"
    if cut_store.get_media(parsed[1], account_id=account_id) is None:
        return f"no uploaded media {handle}"
    return None


@router.post("/assemble")
def cut_assemble_route(body: AssembleBody,
                       account_id: int = Depends(auth.current_account_id)):
    try:
        planned = cut_assemble.plan(body.concept_id, account_id=account_id)
    except LookupError:
        return _error(404, "not_found", f"no concept {body.concept_id}")
    except cut_assemble.AssembleError as e:
        return _error(409, "not_ready", str(e), missing=e.problems)
    if planned["missing"]:
        return _error(409, "not_ready", "this cut is not ready: "
                      + "; ".join(planned["missing"]), missing=planned["missing"])
    for handle in (body.music, body.voice):
        problem = _check_asset(handle, account_id)
        if problem:
            return _error(400, "bad_media", problem)
    if not cut_sources.ffmpeg_bin():
        return _error(503, "no_ffmpeg", "ffmpeg is not installed on this server")

    captions = body.captions
    if isinstance(captions, list):
        captions = [q.model_dump() for q in captions]
    concept_id = body.concept_id
    title = planned["concept"].get("title") or f"#{concept_id}"

    def work(job):
        jobs.progress(job, 0.1, "fetching the clips")
        with tempfile.TemporaryDirectory(prefix="zpf-assemble-") as tmp:
            out = cut_assemble.assemble(concept_id, account_id=account_id,
                                        workdir=Path(tmp), music=body.music,
                                        voice=body.voice, captions=captions)
            tl = out["timeline"]
            jobs.progress(job, 0.4, f"rendering version {tl['version']}")
            result = cut_render.render(tl["doc"], account_id=account_id,
                                       name=f"concept-{concept_id}-v{tl['version']}-{tl['id']}",
                                       paths=out["paths"], media=out["media"])
        cut_store.set_export(tl["id"], result["stored"], account_id=account_id)
        notes = out["notes"] + result["notes"]
        detail = f"cut v{tl['version']} · {result['seconds']:.1f}s"
        for note in notes:
            detail += f" · {note}"
        return {"detail": detail, "timeline_id": tl["id"], "version": tl["version"],
                "mp4_url": result["url"], "seconds": result["seconds"],
                "notes": notes, "ref_id": concept_id}

    job = jobs.start("cut", f"cut · {title[:60]}", work, account_id=account_id)
    return {"job_id": job["id"], "clips": len(planned["clips"]), "notes": planned["notes"]}


# --------------------------------------------------------------------------
# uploads: what an asset:<id> handle names
# --------------------------------------------------------------------------

@router.post("/media")
async def cut_media_upload(request: Request,
                           account_id: int = Depends(auth.current_account_id)):
    form = await request.form()
    upload = form.get("file")
    if not getattr(upload, "filename", ""):
        return _error(400, "no_file", "send the audio as `file`")
    ext = Path(upload.filename).suffix.lower()
    if ext not in AUDIO_TYPES:
        return _error(400, "bad_type", f"audio only: {', '.join(sorted(AUDIO_TYPES))}")
    data = await upload.read()
    if not data:
        return _error(400, "empty", "the file is empty")
    if len(data) > MAX_MEDIA_BYTES:
        return _error(413, "too_big", f"over {MAX_MEDIA_BYTES // (1024 * 1024)}MB")
    sha = hashlib.sha256(data).hexdigest()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    target = MEDIA_DIR / f"{sha[:24]}{ext}"
    target.write_bytes(data)
    try:
        info = cut_sources.probe(target, 30)
    except cut_sources.SourceError as e:
        target.unlink(missing_ok=True)
        return _error(400, "unreadable", str(e))
    if not info["audio"]:
        target.unlink(missing_ok=True)
        return _error(400, "no_audio", "that file has no sound in it")
    from src import media
    stored = f"/renders/cut/media/{target.name}"
    media.mirror(target, stored.lstrip("/"), account_id, content_type=AUDIO_TYPES[ext],
                 derive=False)
    row = cut_store.add_media(account_id=account_id, kind="audio",
                              filename=Path(upload.filename).name[:200], media_url=stored,
                              output_path=str(target), seconds=info["seconds"], sha256=sha)
    return {"handle": f"asset:{row['id']}", "seconds": info["seconds"],
            "filename": row["filename"]}


# --------------------------------------------------------------------------
# versions
# --------------------------------------------------------------------------

@router.get("/{concept_id}/timeline")
def cut_timeline(concept_id: int, account_id: int = Depends(auth.current_account_id)):
    project = cut_store.project_for_concept(concept_id)
    head = cut_store.head(project, account_id=account_id)
    if head is None:
        return _error(404, "not_found", f"concept {concept_id} has no cut yet")
    head["export_url"] = _mint(head.get("export_url"), account_id)
    versions = cut_store.history(project, account_id=account_id)
    for row in versions:
        row["export_url"] = _mint(row.get("export_url"), account_id)
    return {"head": head, "versions": versions}


class RollbackBody(BaseModel):
    timeline_id: int


@router.post("/{concept_id}/rollback")
def cut_rollback(concept_id: int, body: RollbackBody,
                 account_id: int = Depends(auth.current_account_id)):
    row = cut_store.rollback(cut_store.project_for_concept(concept_id), body.timeline_id,
                             account_id=account_id)
    if row is None:
        return _error(404, "not_found", f"no version {body.timeline_id} of concept {concept_id}")
    return {"head": {"id": row["id"], "version": row["version"],
                     "export_url": _mint(row.get("export_url"), account_id)}}

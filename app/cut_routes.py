"""
app/cut_routes.py -- /api/cut, the Export button's server half (Assemble v0,
docs/tasks/CUT_ASSEMBLE_V0.md).

    GET  /api/cut/ready                  rendered scenes a cut can be made from
    POST /api/cut/assemble               concept -> timeline v(N+1) -> MP4 (a job)
    POST /api/cut/media                  upload a music bed / voiceover -> asset:<id>
    POST /api/cut/index                  index a concept's clips (or all of them) -- a job
    GET  /api/cut/search?q=              search the index: the shot, the line, the moment
    GET  /api/cut/{concept_id}/timeline  the head doc + the version chain
    POST /api/cut/{concept_id}/rollback  move the head; nothing is deleted

The editor (phase B, 2026-09-28 -- web/src/app/studio/cut/ reads these):

    GET    /api/cut/projects                   the account's projects, newest-edited first
    POST   /api/cut/projects                   new scratch project, or a concept's (create-or-return)
    GET    /api/cut/projects/{id}              project + head doc + versions + measured media
    PATCH  /api/cut/projects/{id}              rename
    DELETE /api/cut/projects/{id}              soft delete; the versions stay
    POST   /api/cut/projects/{id}/ops          one op against base_id -> a new version
    POST   /api/cut/projects/{id}/undo|redo    move the head along the chain
    POST   /api/cut/projects/{id}/rollback     put any version on top (clears redo)
    GET    /api/cut/projects/{id}/media        the bin: renders (gen:) + uploads (asset:)
    POST   /api/cut/projects/{id}/export       render any version (a job)
    GET    /api/cut/projects/{id}/exports      the versions that have an MP4
    GET    /api/cut/media/{handle}/preview     proxy + filmstrip + waveform (builds on first ask)

The agent (phase E, 2026-09-28 -- every edit is a PROPOSAL the person
Keeps or Undoes; nothing below saves a version except /agent/keep):

    POST   /api/cut/projects/{id}/agent        one agent turn (a job): a reply, maybe a proposal
    POST   /api/cut/projects/{id}/agent/keep   save a proposal's ops as ONE version by "agent"
    POST   /api/cut/projects/{id}/cleanup      silences + filler words -> a proposal (no model)
    POST   /api/cut/projects/{id}/captions     cues from the word timings -> a proposal (no model)
    POST   /api/cut/projects/{id}/index        index this cut's media not indexed yet (a job)

A project's path segments never collide with `/{concept_id}/...`: those
take an int and exactly one of `timeline` / `rollback` after it.

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
from typing import Literal, Optional, Union

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src import preprod
from src.cut import agent_tools as cut_agent
from src.cut import assemble as cut_assemble
from src.cut import cleanup as cut_cleanup
from src.cut import doc as cut_doc
from src.cut import index as cut_index
from src.cut import moments as cut_moments
from src.cut import ops as cut_ops
from src.cut import otio as cut_otio
from src.cut import preview as cut_preview
from src.cut import projects as cut_projects
from src.cut import render as cut_render
from src.cut import sources as cut_sources
from src.cut import store as cut_store
from src.cut.doc import parse_handle

from . import auth, jobs

router = APIRouter(prefix="/cut")

MEDIA_DIR = cut_render.CUT_DIR / "media"
MAX_MEDIA_BYTES = 100 * 1024 * 1024
# footage is bigger than a music bed; still one request, so still capped
MAX_VIDEO_BYTES = 500 * 1024 * 1024
AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
               ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac"}
VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
               ".m4v": "video/x-m4v"}
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".webp": "image/webp"}
UPLOAD_TYPES = {**AUDIO_TYPES, **VIDEO_TYPES, **IMAGE_TYPES}


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, **extra}})


def _create_gate(account_id: Optional[int]) -> Optional[JSONResponse]:
    """api._create_gate's twin (this router does not import app.api): the
    index and the agent spend model calls -- cents, free per click -- so an
    account with no plan and no credit balance is refused, 402, before any
    job starts (2026-10-08, the spend holes)."""
    from src import charge
    reason = charge.create_refusal(account_id)
    return _error(402, "subscribe_or_top_up", reason) if reason else None


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

def _kind_of_upload(ext: str) -> Optional[str]:
    if ext in AUDIO_TYPES:
        return "audio"
    if ext in VIDEO_TYPES:
        return "video"
    if ext in IMAGE_TYPES:
        return "image"
    return None


def _bin_item(r: dict, account_id: Optional[int]) -> dict:
    """One store.media_bin row (or an upload shaped like one) -> M, the
    bin tile. Every URL minted here, for this reader; a still has no
    length (`seconds` null) even though the editor may hold it for
    d.STILL_SECONDS."""
    from src import media, render_assets
    kind = r["kind"]
    render = r.get("origin") == "render"
    url = r.get("media_url") or ""
    if render:
        handle = f"gen:{r['id']}"
        name = f"{render_assets._label(r.get('tool') or '', r.get('model') or '')} #{r['id']}"
    else:
        handle = f"asset:{r['id']}"
        name = r.get("filename") or handle
    if kind == "image":
        poster = media.url_for(url, account_id)
    elif kind == "video":
        poster = (media.thumb_url_for(url, account_id) if render else None) \
            or _mint(r.get("poster_url"), account_id)
    else:
        poster = None
    has_video = r.get("has_video")
    has_audio = r.get("has_audio")
    if has_video is None:
        has_video = kind in ("video", "image")
    if kind == "image":
        has_audio = False
    elif kind == "audio":
        has_video = False
        if has_audio is None:
            has_audio = True
    seconds = None if kind == "image" else r.get("seconds")
    return {"handle": handle, "kind": kind, "name": name,
            "seconds": round(float(seconds), 3) if seconds is not None else None,
            "width": r.get("width"), "height": r.get("height"),
            "has_video": bool(has_video), "has_audio": has_audio,
            "size_bytes": r.get("size_bytes"), "url": media.url_for(url, account_id),
            "poster": poster, "created_at": r.get("created_at"),
            "source": "render" if render else "upload"}


def _start_preview(handle: str, source: str, account_id: Optional[int]) -> bool:
    """Claim and start the preview build for one handle, if nobody has
    (the claim is a compare-and-set, so two polls start one job)."""
    if not cut_sources.ffmpeg_bin():
        return False
    if not cut_store.claim_preview(handle, source, account_id=account_id,
                                   stale_before=cut_preview.stale_before()):
        return False

    def work(job):
        jobs.progress(job, 0.1, f"previews for {handle}")
        out = cut_preview.ensure(handle, account_id=account_id)
        if out["status"] != "ready":
            raise RuntimeError(out.get("note") or "preview failed")
        return {"detail": f"previews ready · {handle}", "handle": handle}

    jobs.start("cut_preview", f"previews · {handle}", work, account_id=account_id)
    return True


@router.post("/media")
async def cut_media_upload(request: Request,
                           account_id: int = Depends(auth.current_account_id)):
    """Upload a music bed, voiceover, piece of footage or still -> an
    `asset:<id>` handle. Probed on the way in (a file ffprobe cannot read
    is refused here, not at the first edit that uses it), the probe
    written to the cache so the first op on it downloads nothing, and the
    preview build started."""
    form = await request.form()
    upload = form.get("file")
    if not getattr(upload, "filename", ""):
        return _error(400, "no_file", "send the media as `file`")
    ext = Path(upload.filename).suffix.lower()
    kind = _kind_of_upload(ext)
    if kind is None:
        return _error(400, "bad_type", "audio, video or an image: "
                      f"{', '.join(sorted(UPLOAD_TYPES))}")
    data = await upload.read()
    if not data:
        return _error(400, "empty", "the file is empty")
    cap = MAX_VIDEO_BYTES if kind == "video" else MAX_MEDIA_BYTES
    if len(data) > cap:
        return _error(413, "too_big", f"over {cap // (1024 * 1024)}MB")
    sha = hashlib.sha256(data).hexdigest()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    target = MEDIA_DIR / f"{sha[:24]}{ext}"
    target.write_bytes(data)
    try:
        info = cut_sources.probe(target, 30)
    except cut_sources.SourceError as e:
        target.unlink(missing_ok=True)
        return _error(400, "unreadable", str(e))
    refusal = None
    if kind == "audio" and not info["audio"]:
        refusal = ("no_audio", "that file has no sound in it")
    elif kind == "video" and (not info["video"] or info.get("still")):
        refusal = ("no_video", "that file has no moving picture in it")
    elif kind == "image" and not info.get("still"):
        refusal = ("not_an_image", "that file is not a still image")
    if refusal:
        target.unlink(missing_ok=True)
        return _error(400, *refusal)
    from src import media
    stored = f"/renders/cut/media/{target.name}"
    media.mirror(target, stored.lstrip("/"), account_id, content_type=UPLOAD_TYPES[ext],
                 derive=False)
    row = cut_store.add_media(account_id=account_id, kind=kind,
                              filename=Path(upload.filename).name[:200], media_url=stored,
                              output_path=str(target),
                              seconds=None if kind == "image" else info["seconds"], sha256=sha)
    handle = f"asset:{row['id']}"
    cut_store.put_probe(handle, stored, info, account_id=account_id, size_bytes=len(data),
                        sha256=sha)
    _start_preview(handle, stored, account_id)
    item = _bin_item({**row, "origin": "upload", "width": info.get("width"),
                      "height": info.get("height"), "has_video": info["video"],
                      "has_audio": info["audio"], "size_bytes": len(data)}, account_id)
    return {"handle": handle, "kind": kind, "seconds": item["seconds"],
            "filename": row["filename"], "item": item}


# --------------------------------------------------------------------------
# the index (phase 2): what is in each clip, and search over it
# --------------------------------------------------------------------------

class IndexBody(BaseModel):
    concept_id: Optional[int] = None
    force: bool = False


@router.post("/index")
def cut_index_route(body: IndexBody, account_id: int = Depends(auth.current_account_id)):
    """Index one concept's clips, or (no concept_id) every clip and upload
    not indexed yet. A job: each clip is a Gemini call and, when someone
    speaks, a fal Whisper call -- cents, metered, not charged in credits."""
    refused = _create_gate(account_id)
    if refused is not None:
        return refused
    if body.concept_id is not None:
        try:
            handles = cut_index.handles_for_concept(body.concept_id, account_id=account_id)
        except LookupError:
            return _error(404, "not_found", f"no concept {body.concept_id}")
        if not handles:
            return _error(409, "nothing_to_index",
                          f"concept {body.concept_id} has no clip in the Asset Bank yet")
    else:
        handles = cut_index.all_handles(account_id=account_id)
        if not handles:
            return _error(409, "nothing_to_index", "there are no clips to index yet")
    if not cut_sources.ffmpeg_bin():
        return _error(503, "no_ffmpeg", "ffmpeg is not installed on this server")
    label = f"index · concept {body.concept_id}" if body.concept_id else "index · every clip"
    job = _index_job(handles, label, account_id=account_id, force=body.force,
                     ref_id=body.concept_id)
    return {"job_id": job["id"], "handles": handles}


def _index_job(handles: list[str], label: str, *, account_id: int, force: bool = False,
               ref_id=None) -> dict:
    """The indexing job both index routes start: one index_media per
    handle, cancellable between clips, a failure reported and not fatal."""
    def work(job):
        done = []
        for i, h in enumerate(handles):
            jobs.check_cancelled(job)
            jobs.progress(job, i / len(handles), f"indexing {h}")
            done.append(cut_index.index_media(h, account_id=account_id, force=force))
        indexed = [r for r in done if r.get("status") == "done" and not r.get("skipped")]
        failed = [r for r in done if r.get("status") == "failed"]
        detail = (f"{len(indexed)} indexed · {len(done) - len(indexed) - len(failed)} already current"
                  + (f" · {len(failed)} failed: " + "; ".join(
                      f"{r['media']}: {r.get('notes')}" for r in failed)[:400] if failed else ""))
        return {"detail": detail,
                "indexed": [{"media": r["media"], "status": r.get("status"),
                             "skipped": r.get("skipped"), "shots": r.get("shots"),
                             "words": r.get("words"), "speech": r.get("speech"),
                             "notes": r.get("notes")} for r in done],
                "ref_id": ref_id}

    return jobs.start("index", label, work, cancellable=True, account_id=account_id)


@router.get("/search")
def cut_search(q: str = "", k: int = 8, account_id: int = Depends(auth.current_account_id)):
    if not q.strip():
        return _error(400, "empty", "say what to look for")
    out = cut_index.find(q, account_id=account_id, k=k)
    for h in out["results"]:
        h["media_url"] = _mint(h.get("media_url"), account_id)
    return out


# --------------------------------------------------------------------------
# the editor (phase B): projects, edits, undo, the bin, previews, export
# --------------------------------------------------------------------------

Aspect = Literal["9:16", "16:9", "1:1"]


class RollbackBody(BaseModel):
    timeline_id: int


def _project_or_404(project_id: str, account_id: int):
    row = cut_store.get_project(project_id, account_id=account_id)
    if row is None:
        return None, _error(404, "not_found", f"no project {project_id}")
    return row, None


def _head_or_409(project: dict, account_id: int):
    head = cut_store.head(project["timeline_key"], account_id=account_id)
    if head is None:
        # only reachable for a project whose versions were never written
        return None, _error(409, "no_head", "this project has no version yet")
    return head, None


class NewProject(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    aspect: Aspect = "9:16"
    concept_id: Optional[int] = None
    # phase F: start the cut from these, in order (the bin's "New cut from selection")
    handles: Optional[list[str]] = Field(default=None, max_length=cut_projects.MAX_START_MEDIA)


@router.get("/projects")
def cut_projects_list(account_id: int = Depends(auth.current_account_id)):
    return {"projects": cut_projects.cards(account_id=account_id)}


@router.post("/projects")
def cut_projects_create(body: NewProject, account_id: int = Depends(auth.current_account_id)):
    """A scratch project, or -- with `concept_id` -- the concept's cut,
    created or returned (Mike's D2: its key is `concept:<id>`, so it
    shares the history Export already wrote). With `handles` (and no
    concept) the scratch project's v1 already holds those media, in
    order; one that is not this account's is 404 `bad_media` and no
    project is made."""
    if body.concept_id is not None:
        try:
            row = cut_projects.open_concept(body.concept_id, account_id=account_id)
        except LookupError:
            return _error(404, "not_found", f"no concept {body.concept_id}")
    elif body.handles:
        try:
            row = cut_projects.create_from_media(account_id=account_id, handles=body.handles,
                                                 title=body.title, aspect=body.aspect)
        except cut_projects.BadMedia as e:
            return _error(404, "bad_media", str(e))
        except cut_ops.OpError as e:
            return _error(422, "invalid", str(e), problems=e.problems)
    else:
        row = cut_projects.create_scratch(account_id=account_id, title=body.title,
                                          aspect=body.aspect)
    return {"project": _project_card(row, account_id)}


def _project_card(row: dict, account_id: int, head: Optional[dict] = None) -> dict:
    head = head or cut_store.head(row["timeline_key"], account_id=account_id)
    first = cut_projects.first_picture(head["doc"]) if head else None
    posters = cut_projects.poster_urls([first], account_id=account_id) if first else {}
    return cut_projects.card(row, account_id=account_id, head=head, poster=posters.get(first))


@router.get("/projects/{project_id}")
def cut_project_get(project_id: str, account_id: int = Depends(auth.current_account_id)):
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    head, err = _head_or_409(project, account_id)
    if err:
        return err
    versions = cut_store.history(project["timeline_key"], account_id=account_id)
    out = cut_projects.state(project, head, account_id=account_id)
    return {"project": _project_card(project, account_id, head), "head": out["head"],
            "versions": [cut_projects.version_view(v, account_id=account_id) for v in versions],
            "can_undo": out["can_undo"], "can_redo": out["can_redo"], "media": out["media"]}


class ProjectPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)


@router.patch("/projects/{project_id}")
def cut_project_patch(project_id: str, body: ProjectPatch,
                      account_id: int = Depends(auth.current_account_id)):
    title = body.title.strip() if body.title else None
    row = cut_store.update_project(project_id, account_id=account_id, title=title or None)
    if row is None:
        return _error(404, "not_found", f"no project {project_id}")
    return {"project": _project_card(row, account_id)}


@router.delete("/projects/{project_id}")
def cut_project_delete(project_id: str, account_id: int = Depends(auth.current_account_id)):
    """Soft: the project leaves the list; its versions and exports stay."""
    if not cut_store.delete_project(project_id, account_id=account_id):
        return _error(404, "not_found", f"no project {project_id}")
    return {"ok": True}


@router.post("/projects/{project_id}/restore")
def cut_project_restore(project_id: str, account_id: int = Depends(auth.current_account_id)):
    """The Undo on a removed project (2026-10-08). 409 `taken` when its
    scene's cut was opened again since -- that project is the same history."""
    row, why = cut_store.restore_project(project_id, account_id=account_id)
    if why == "taken":
        return _error(409, "taken", "this scene's cut is already open as another project")
    if row is None:
        return _error(404, "not_found", f"no removed project {project_id}")
    return {"project": _project_card(row, account_id)}


class OpBody(BaseModel):
    base_id: int
    op: str = Field(min_length=1, max_length=40)
    args: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/ops")
def cut_project_op(project_id: str, body: OpBody,
                   account_id: int = Depends(auth.current_account_id)):
    """One edit: the op runs against the version the client edited
    (`base_id`, which must still be the head), is validated against the
    measured media, and is saved as a new version. 409 `stale` when the
    head has moved (the client refetches); 422 `invalid` with every
    problem when the op or its result is refused."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    try:
        head = cut_projects.edit(project, base_id=body.base_id, op=body.op, args=body.args,
                                 account_id=account_id)
    except cut_projects.StaleEdit as e:
        return _error(409, "stale", str(e), head_id=e.head_id)
    except cut_ops.OpError as e:
        return _error(422, "invalid", str(e), problems=e.problems)
    return cut_projects.state(project, head, account_id=account_id)


@router.post("/projects/{project_id}/undo")
def cut_project_undo(project_id: str, account_id: int = Depends(auth.current_account_id)):
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    head = cut_store.undo(project["timeline_key"], account_id=account_id)
    if head is None:
        return _error(409, "nothing_to_undo", "this is the first version")
    cut_store.update_project(project["id"], account_id=account_id)
    return cut_projects.state(project, head, account_id=account_id)


@router.post("/projects/{project_id}/redo")
def cut_project_redo(project_id: str, account_id: int = Depends(auth.current_account_id)):
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    head = cut_store.redo(project["timeline_key"], account_id=account_id)
    if head is None:
        return _error(409, "nothing_to_redo", "there is nothing to redo")
    cut_store.update_project(project["id"], account_id=account_id)
    return cut_projects.state(project, head, account_id=account_id)


@router.post("/projects/{project_id}/rollback")
def cut_project_rollback(project_id: str, body: RollbackBody,
                         account_id: int = Depends(auth.current_account_id)):
    """Put any version back on top. It clears redo -- a rollback is new
    history -- and deletes nothing."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    if cut_store.rollback(project["timeline_key"], body.timeline_id,
                          account_id=account_id) is None:
        return _error(404, "not_found", f"no version {body.timeline_id} of this project")
    cut_store.update_project(project["id"], account_id=account_id)
    head = cut_store.head(project["timeline_key"], account_id=account_id)
    return cut_projects.state(project, head, account_id=account_id)


@router.get("/projects/{project_id}/media")
def cut_project_media(project_id: str, account_id: int = Depends(auth.current_account_id)):
    """The bin: this account's renders (gen:) and uploads (asset:). The
    project only scopes the question today -- every project of an account
    sees the same bin -- but it is in the path so a per-project bin later
    is not a new route."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    rows = cut_store.media_bin(account_id=account_id)
    items = [_bin_item(r, account_id) for r in rows]
    items.sort(key=lambda i: str(i.get("created_at") or ""), reverse=True)
    return {"items": items}


@router.get("/media/{handle}/preview")
def cut_media_preview(handle: str, account_id: int = Depends(auth.current_account_id)):
    """The proxy, filmstrip and waveform for one handle. Starts the build
    the first time it is asked for (or when the handle now points at a
    different file) and answers `pending` until it lands; `unavailable`
    when this box has no ffmpeg to build with."""
    if parse_handle(handle) is None:
        return _error(404, "not_found", f"no media {handle}")
    source = cut_store.handle_sources([handle], account_id=account_id).get(handle)
    if source is None:
        return _error(404, "not_found", f"no media {handle}")
    stored = source.get("media_url") or ""
    row = cut_store.cached([handle], account_id=account_id).get(handle)
    if row and row.get("source") == stored and row.get("preview_status") == "ready":
        return cut_preview.view(row, account_id)
    if not cut_sources.ffmpeg_bin():
        return {"status": "unavailable", "proxy": None, "filmstrip": None, "waveform": None,
                "note": "ffmpeg is not installed on this server"}
    if cut_preview.needs_build(row, stored):
        _start_preview(handle, stored, account_id)
        row = cut_store.cached([handle], account_id=account_id).get(handle)
    return cut_preview.view(row, account_id)


@router.get("/media/{handle}/transcript")
def cut_media_transcript(handle: str, account_id: int = Depends(auth.current_account_id)):
    """What the index heard and saw in one file, for the Source viewer's
    Transcript tab: its words (click one to seek, drag across them to mark
    In/Out) and its shots. Times are SECONDS, not frames: the index runs
    at its own fps (media_index.fps), and a client converting someone
    else's frames is how a word ends up a frame off. Not indexed answers
    `not_indexed` -- the tab offers the index, it never runs it."""
    if parse_handle(handle) is None:
        return _error(404, "not_found", f"no media {handle}")
    if cut_store.handle_sources([handle], account_id=account_id).get(handle) is None:
        return _error(404, "not_found", f"no media {handle}")
    row = cut_moments.indexed(handle, account_id=account_id)
    if row is None or row.get("status") != "done":
        return {"status": "not_indexed", "speech": None, "words": [], "shots": []}
    fps = float(row.get("fps") or 30)
    words, shots = [], []
    for m in cut_moments.moments_for(handle, account_id=account_id):
        span = {"start": round(m["start_f"] / fps, 3), "end": round(m["end_f"] / fps, 3)}
        if m["kind"] == "word":
            words.append({**span, "text": m.get("text") or "", "speaker": m.get("speaker")})
        elif m["kind"] == "shot":
            shots.append({**span, "text": m.get("text") or ""})
    return {"status": "indexed", "speech": row.get("speech"), "words": words, "shots": shots}


class ExportBody(BaseModel):
    timeline_id: Optional[int] = None
    aspect: Optional[Aspect] = None
    # what to make: the MP4 (default), its sound alone (.m4a), the frame at
    # `frame` (.png), or an editable project (.otio + .srt) for an NLE
    format: Literal["mp4", "audio", "still", "project"] = "mp4"
    frame: Optional[int] = Field(default=None, ge=0)


def _project_files(doc: dict, *, name: str, title: str, account_id: int) -> dict:
    """The editable project: OTIO (media by URL, named) and an SRT of the
    captions, written beside the renders and mirrored like them."""
    import json

    from src import media as media_mod
    handles = cut_doc.handles(doc)
    sources = cut_store.handle_sources(handles, account_id=account_id)
    names = cut_store.handle_names(handles, account_id=account_id)
    refs = {h: {"url": _mint((sources.get(h) or {}).get("media_url"), account_id),
                "name": (names.get(h) or {}).get("name") or h}
            for h in handles}
    out_dir = cut_render.CUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    otio_path = out_dir / f"{name}.otio"
    otio_path.write_text(json.dumps(cut_otio.timeline(doc, refs, name=title), indent=2), encoding="utf-8")
    files["otio"] = otio_path
    subs = cut_otio.srt(doc)
    if subs:
        srt_path = out_dir / f"{name}.srt"
        srt_path.write_text(subs, encoding="utf-8")
        files["srt"] = srt_path
    urls = {}
    for kind, path in files.items():
        stored = f"/renders/cut/{path.name}"
        media_mod.mirror(path, f"renders/cut/{path.name}", account_id,
                         content_type="application/json" if kind == "otio" else "text/plain",
                         derive=False)
        urls[kind] = _mint(stored, account_id)
    offline = sorted(h for h, r in refs.items() if not r["url"])
    return {"urls": urls, "offline": offline}


@router.post("/projects/{project_id}/export")
def cut_project_export(project_id: str, body: ExportBody,
                       account_id: int = Depends(auth.current_account_id)):
    """Render any version -- the head by default -- to an MP4 (a job, like
    /assemble). An `aspect` other than the version's first becomes a NEW
    user version (`set_canvas` on that version) and that is what renders:
    an export must always be of a version that exists, or its export_url
    would describe a doc nobody can open. Nothing spends: ffmpeg here."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    key = project["timeline_key"]
    if body.timeline_id is not None:
        target = cut_store.get(body.timeline_id, account_id=account_id)
        if target is None or target.get("project_id") != key:
            return _error(404, "not_found", f"no version {body.timeline_id} of this project")
    else:
        target, err = _head_or_409(project, account_id)
        if err:
            return err
    if body.format != "project" and not cut_sources.ffmpeg_bin():
        return _error(503, "no_ffmpeg", "ffmpeg is not installed on this server")
    doc = target["doc"]
    if doc.get("duration", 0) <= 0:
        return _error(409, "empty", "there is nothing on this timeline to export")
    if body.aspect and cut_doc.aspect_of(doc["size"]) != body.aspect:
        w, h = cut_doc.ASPECT_SIZES[body.aspect]
        try:
            new = cut_ops.apply(doc, "set_canvas", {"width": w, "height": h})
        except cut_ops.OpError as e:
            return _error(422, "invalid", str(e), problems=e.problems)
        target = cut_store.save_version(
            key, new, account_id=account_id, author="user", parent_id=target["id"],
            op_summary=f"{cut_ops.describe('set_canvas', {'width': w, 'height': h})} "
                       f"({body.aspect}) for export")
        cut_store.update_project(project["id"], account_id=account_id)
    tl_id, version, doc = target["id"], target["version"], target["doc"]
    name = f"{key.replace(':', '-')}-v{version}-{tl_id}"
    fmt = body.format
    if fmt == "still":
        frame = body.frame if body.frame is not None else 0
        if frame >= doc["duration"]:
            return _error(422, "invalid", f"frame {frame} is past the end of the cut ({doc['duration']} frames)")
        name += f"-f{frame}"
    else:
        frame = 0

    if fmt == "project":
        def work(job):
            jobs.progress(job, 0.3, "writing the project")
            got = _project_files(doc, name=name, title=f"{project['title']} v{version}",
                                 account_id=account_id)
            detail = f"project v{version} · .otio" + (" + .srt" if "srt" in got["urls"] else "")
            if got["offline"]:
                detail += f" · {len(got['offline'])} media without a public URL (relink by name)"
            return {"detail": detail, "timeline_id": tl_id, "version": version, "format": fmt,
                    "otio_url": got["urls"]["otio"], "srt_url": got["urls"].get("srt"),
                    "ref_id": project["id"]}

        job = jobs.start("cut", f"project · {project['title'][:60]} v{version}", work,
                         account_id=account_id)
        return {"job_id": job["id"], "timeline_id": tl_id, "version": version}

    def work(job):
        jobs.progress(job, 0.1, "fetching the media")
        with tempfile.TemporaryDirectory(prefix="zpf-export-") as tmp:
            paths, media = cut_sources.gather(cut_doc.handles(doc), account_id=account_id,
                                              fps=doc["fps"], workdir=Path(tmp))
            jobs.progress(job, 0.4, f"rendering version {version}")
            result = cut_render.render(doc, account_id=account_id, name=name,
                                       paths=paths, media=media, fmt=fmt, frame=frame)
        if fmt == "mp4":
            # export_url is the version's MP4; a still or the sound alone
            # is a derivative the dialog hands over, not the export of record
            cut_store.set_export(tl_id, result["stored"], account_id=account_id)
        what = {"mp4": "export", "audio": "audio", "still": "still"}[fmt]
        detail = f"{what} v{version}" + (f" · {result['seconds']:.1f}s" if fmt != "still"
                                         else f" · frame {frame}")
        for note in result["notes"]:
            detail += f" · {note}"
        return {"detail": detail, "timeline_id": tl_id, "version": version, "format": fmt,
                "mp4_url": result["url"] if fmt == "mp4" else None,
                "file_url": result["url"], "seconds": result["seconds"],
                "notes": result["notes"], "ref_id": project["id"]}

    label = {"mp4": "export", "audio": "audio", "still": "still"}[fmt]
    job = jobs.start("cut", f"{label} · {project['title'][:60]} v{version}", work,
                     account_id=account_id)
    return {"job_id": job["id"], "timeline_id": tl_id, "version": version}


@router.get("/projects/{project_id}/exports")
def cut_project_exports(project_id: str, account_id: int = Depends(auth.current_account_id)):
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    return {"exports": [
        {"timeline_id": v["id"], "version": v["version"],
         "export_url": _mint(v["export_url"], account_id), "created_at": v["created_at"],
         "op_summary": v["op_summary"]}
        for v in cut_store.history(project["timeline_key"], account_id=account_id)
        if v.get("export_url")]}


# --------------------------------------------------------------------------
# the agent (phase E): proposals the person Keeps or Undoes
# --------------------------------------------------------------------------

class AgentBody(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    playhead: Optional[int] = Field(default=None, ge=0)
    selection: Optional[list[str]] = Field(default=None, max_length=200)


@router.post("/projects/{project_id}/agent")
def cut_project_agent(project_id: str, body: AgentBody,
                      account_id: int = Depends(auth.current_account_id)):
    """One agent turn, as a job (a model turn takes seconds). The job's
    result is {reply, proposal, tool_runs, notes, ref_id}: a proposal has
    already passed ops.apply against the head it names as base_id, and
    NOTHING is saved -- Keep is its own route, and Undo is the client
    dropping the card. The turn degrades rather than fails: no key or a
    dead model finishes the job with a reply that says so."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    head, err = _head_or_409(project, account_id)
    if err:
        return err
    message = body.message.strip()
    if not message:
        return _error(400, "empty", "say what to change")
    refused = _create_gate(account_id)
    if refused is not None:
        return refused
    selection = [str(s)[:40] for s in (body.selection or [])]

    def work(job):
        jobs.progress(job, 0.1, "reading the timeline")
        out = cut_agent.run_turn(project, head, message, account_id=account_id,
                                 playhead=body.playhead, selection=selection)
        return {**out, "detail": (out["reply"] or "")[:160]}

    job = jobs.start("cut_agent", f"agent · {project['title'][:60]}", work,
                     account_id=account_id)
    return {"job_id": job["id"]}


class ProposedOp(BaseModel):
    op: str = Field(min_length=1, max_length=40)
    args: dict = Field(default_factory=dict)


class KeepBody(BaseModel):
    base_id: int
    ops: list[ProposedOp] = Field(min_length=1, max_length=cut_projects.MAX_OPS)
    summary: str = Field(default="", max_length=2000)
    kind: Optional[str] = Field(default=None, max_length=20)


@router.post("/projects/{project_id}/agent/keep")
def cut_project_agent_keep(project_id: str, body: KeepBody,
                           account_id: int = Depends(auth.current_account_id)):
    """Keep a proposal: its ops are RE-APPLIED against the head (the doc
    the card showed is never trusted) and saved as ONE version by "agent",
    under the card's summary. Clears redo, like any new version. Answers
    exactly what /ops answers; 409 `stale` when the head moved since the
    proposal was made, 422 `invalid` when an op no longer applies."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    try:
        head = cut_projects.keep(project, base_id=body.base_id,
                                 op_list=[o.model_dump() for o in body.ops],
                                 summary=body.summary, account_id=account_id)
    except cut_projects.StaleEdit as e:
        return _error(409, "stale", str(e), head_id=e.head_id)
    except cut_ops.OpError as e:
        return _error(422, "invalid", str(e), problems=e.problems)
    return cut_projects.state(project, head, account_id=account_id)


class CleanupBody(BaseModel):
    base_id: Optional[int] = None
    min_silence: float = Field(default=cut_cleanup.DEFAULT_MIN_SILENCE, ge=0.1, le=10)
    fillers: bool = True


@router.post("/projects/{project_id}/cleanup")
def cut_project_cleanup(project_id: str, body: CleanupBody,
                        account_id: int = Depends(auth.current_account_id)):
    """Silences and filler words, off the index's word timings, as ONE
    proposal of ops that remove them. No model call, nothing saved;
    `needs_index` lists the media on the timeline the index has not seen
    (index them with /index, then ask again)."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    try:
        return cut_cleanup.propose_cleanup(project, account_id=account_id, base_id=body.base_id,
                                           min_silence=body.min_silence, fillers=body.fillers)
    except cut_cleanup.Stale as e:
        return _error(409, "stale", str(e), head_id=e.head_id)
    except cut_ops.OpError as e:
        return _error(422, "invalid", str(e), problems=e.problems)


class CaptionsBody(BaseModel):
    base_id: Optional[int] = None
    track_id: Optional[str] = Field(default=None, min_length=1, max_length=20)
    max_words: int = Field(default=cut_cleanup.DEFAULT_MAX_WORDS, ge=1, le=20)


@router.post("/projects/{project_id}/captions")
def cut_project_captions(project_id: str, body: CaptionsBody,
                         account_id: int = Depends(auth.current_account_id)):
    """Caption cues from the words of the sound on the timeline, as ONE
    proposal: a new caption track, or -- when `track_id` names a caption
    track that exists -- set_cue for every cue that does not overlap one
    already there. No model call, nothing saved."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    try:
        return cut_cleanup.propose_captions(project, account_id=account_id, base_id=body.base_id,
                                            track_id=body.track_id, max_words=body.max_words)
    except cut_cleanup.Stale as e:
        return _error(409, "stale", str(e), head_id=e.head_id)
    except cut_ops.OpError as e:
        return _error(422, "invalid", str(e), problems=e.problems)


@router.post("/projects/{project_id}/index")
def cut_project_index(project_id: str, account_id: int = Depends(auth.current_account_id)):
    """Index the media on this cut's head that the index has not finished
    -- and nothing else. Spends cents (a Gemini shot log, fal Whisper when
    someone speaks); the click is the approval, as on /api/cut/index."""
    project, err = _project_or_404(project_id, account_id)
    if err:
        return err
    head, err = _head_or_409(project, account_id)
    if err:
        return err
    handles = []
    for h in cut_doc.handles(head["doc"]):
        row = cut_moments.indexed(h, account_id=account_id)
        if row is None or row.get("status") != "done":
            handles.append(h)
    if not handles:
        return _error(409, "nothing_to_index", "everything on this cut is indexed already")
    refused = _create_gate(account_id)
    if refused is not None:
        return refused
    if not cut_sources.ffmpeg_bin():
        return _error(503, "no_ffmpeg", "ffmpeg is not installed on this server")
    job = _index_job(handles, f"index · {project['title'][:60]}", account_id=account_id,
                     ref_id=project["id"])
    return {"job_id": job["id"], "handles": handles}


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


@router.post("/{concept_id}/rollback")
def cut_rollback(concept_id: int, body: RollbackBody,
                 account_id: int = Depends(auth.current_account_id)):
    row = cut_store.rollback(cut_store.project_for_concept(concept_id), body.timeline_id,
                             account_id=account_id)
    if row is None:
        return _error(404, "not_found", f"no version {body.timeline_id} of concept {concept_id}")
    return {"head": {"id": row["id"], "version": row["version"],
                     "export_url": _mint(row.get("export_url"), account_id)}}

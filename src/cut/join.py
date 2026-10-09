"""
Join clips into one video, from a chat (2026-10-09, docs/tasks/
task-mcp-studio-v2.md step 2a).

The MCP's `assemble_clips` names some `gen:<id>` clips off the Assets wall
and asks for them back as one MP4. Nothing new is invented for it: the
cut is a SCRATCH project in the editor (`cut:<uuid>`, version 1 by the
person) built by `assemble.build_doc` -- the same pure builder Assemble
uses, through the same ops, so the joined cut is one the editor could
have made and can open -- validated by `validate.validate`, rendered by
`render.render`, and filed on the Assets wall like any render, so it is a
`gen:<id>` the next tool can name. It is NOT `assemble.assemble`, which is
bound to a concept's timed shots.

WHAT IS REFUSED, before anything is written:
- an id that is not a `gen:<id>` of this account's, a soft-deleted render,
  an image, or a file that cannot be read;
- clips of different shapes (a 9:16 beside a 16:9) -- unless `letterbox`
  says to fit them all inside the FIRST clip's frame with black bars,
  which is what the renderer does with a mismatched clip anyway. Refusing
  by default because a person asking to "join these" rarely means "put
  bars on half of them", and saying so costs one word;
- a crossfade longer than half the shortest clip (a clip in the middle is
  overlapped from both sides, and two fades must not meet);
- music that is not an `asset:<id>` audio upload of this account's (the
  editor's bin; `renders(kind="audio")` lists them).

WHAT IT COSTS: nothing. ffmpeg runs on this server, no provider is
called, no credit is held, and the result says so rather than quoting
zero. The wall's generations row carries `cost_usd` NULL, the manual
lane's "free" spelling, under its own log tool, `cut`.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

from . import assemble, render, sources, store
from . import doc as d

MIN_CLIPS = 2
MAX_CLIPS = 20                  # projects.MAX_START_MEDIA: the editor's own start limit
TRANSITIONS = ("cut", "crossfade")
CROSSFADE_DEFAULT = 0.5
CROSSFADE_MIN = 0.1
CROSSFADE_MAX = 2.0
ASPECT_TOLERANCE = 0.01         # d.aspect_of's: 720x1280 and 1080x1920 are one shape
LOG_TOOL = "cut"                # generative.CUT_TOOLS
FREE_NOTE = "Joined on the studio's server with ffmpeg -- no credits were spent."


class JoinRefused(ValueError):
    """A join that will not be made, and why -- a caller error, answered
    before anything is written or rendered."""


def _ratio(info: dict) -> Optional[float]:
    w, h = info.get("width"), info.get("height")
    return (w / h) if w and h else None


def _shape(info: dict) -> str:
    w, h = info.get("width"), info.get("height")
    return d.aspect_of((w, h)) if w and h else "unknown"


def plan(handles: list[str], *, account_id: Optional[int], transition: str = "cut",
         crossfade_s: float = CROSSFADE_DEFAULT, music: Optional[str] = None,
         letterbox: bool = False, fps: int = d.DEFAULT_FPS,
         dsn: Optional[str] = None) -> dict[str, Any]:
    """Every check, and the cut that would render. Writes nothing (the
    probe cache aside). Raises JoinRefused."""
    from .. import render_assets
    handles = [str(h).strip() for h in (handles or []) if str(h).strip()]
    if len(handles) < MIN_CLIPS:
        raise JoinRefused(f"name at least {MIN_CLIPS} clips to join (gen:<id> from `renders`)")
    if len(handles) > MAX_CLIPS:
        raise JoinRefused(f"at most {MAX_CLIPS} clips in one join, got {len(handles)}")
    transition = (transition or "cut").strip().lower()
    if transition not in TRANSITIONS:
        raise JoinRefused(f"transition must be one of {list(TRANSITIONS)}, got {transition!r}")

    for h in dict.fromkeys(handles):
        parsed = d.parse_handle(h)
        if parsed is None or parsed[0] != "gen":
            raise JoinRefused(f"{h!r}: a clip is gen:<id> -- a video on your Assets wall "
                              "(see `renders`). URLs are never taken")
        row = render_assets.get(parsed[1], dsn, account_id=account_id)
        if not row or row.get("deleted_at"):
            raise JoinRefused(f"no render {parsed[1]} on this account -- ids come from `renders`")
        if row.get("media_kind") != "video":
            raise JoinRefused(f"{h} is an {row.get('media_kind')}; only clips can be joined")
    if music is not None:
        parsed = d.parse_handle(str(music).strip())
        if parsed is None or parsed[0] != "asset":
            raise JoinRefused("music is an asset:<id> -- an audio file you uploaded to the "
                              "editor (`renders` with kind=audio lists them)")
        music = f"asset:{parsed[1]}"
        upload = store.get_media(parsed[1], account_id=account_id, dsn=dsn)
        if not upload or upload.get("kind") != "audio":
            raise JoinRefused(f"no audio upload {parsed[1]} on this account -- "
                              "`renders` with kind=audio lists them")

    wanted = list(dict.fromkeys(handles + ([music] if music else [])))
    media = sources.measure(wanted, account_id=account_id, fps=fps, dsn=dsn)
    for h in wanted:
        if media.get(h) is None:
            raise JoinRefused(f"could not read {h} -- its file is not reachable right now")
    for h in dict.fromkeys(handles):
        info = media[h]
        if not info.get("video") or info.get("still"):
            raise JoinRefused(f"{h} has no moving picture; only clips can be joined")
    if music and (media[music].get("video") or not media[music].get("audio")):
        raise JoinRefused(f"{music} is not an audio file")

    first = media[handles[0]]
    base = _ratio(first)
    odd = [h for h in dict.fromkeys(handles[1:])
           if base is None or _ratio(media[h]) is None
           or abs(_ratio(media[h]) - base) > ASPECT_TOLERANCE * base]
    if odd and not letterbox:
        shapes = ", ".join(f"{h} is {_shape(media[h])}" for h in [handles[0], *odd])
        raise JoinRefused(f"these clips are not one shape ({shapes}). Join clips of one shape, "
                          "or pass letterbox=true to fit the others inside the first clip's "
                          "frame with black bars")

    frames = 0
    if transition == "crossfade":
        try:
            seconds = float(crossfade_s)
        except (TypeError, ValueError):
            raise JoinRefused(f"crossfade_s must be a number of seconds, got {crossfade_s!r}") from None
        if not CROSSFADE_MIN <= seconds <= CROSSFADE_MAX:
            raise JoinRefused(f"crossfade_s must be {CROSSFADE_MIN}-{CROSSFADE_MAX} seconds")
        frames = max(1, round(seconds * fps))
        shortest = min(handles, key=lambda h: media[h]["frames"])
        if frames * 2 > media[shortest]["frames"]:
            raise JoinRefused(
                f"a {seconds:g}s crossfade needs every clip at least {2 * seconds:g}s long; "
                f"{shortest} is {media[shortest]['frames'] / fps:.1f}s")

    try:
        doc, notes = assemble.build_doc([{"handle": h, "label": h} for h in handles], media,
                                        fps=fps, music=music, transition_frames=frames)
    except (assemble.AssembleError, ValueError) as e:
        raise JoinRefused(f"these clips cannot be joined: {e}") from e
    return {"doc": doc, "media": media, "notes": notes, "handles": handles, "music": music,
            "transition": transition, "crossfade_frames": frames, "fps": fps,
            "canvas": {"width": doc["size"][0], "height": doc["size"][1],
                       "aspect": d.aspect_of(doc["size"])},
            "letterboxed": odd if letterbox else [],
            "seconds": round(doc["duration"] / fps, 2)}


def describe(planned: dict) -> str:
    """The prompt the wall files the joined cut under."""
    text = f"Joined {len(planned['handles'])} clips: {', '.join(planned['handles'])}"
    if planned["crossfade_frames"]:
        text += f" (crossfade {planned['crossfade_frames'] / planned['fps']:g}s)"
    if planned["music"]:
        text += f" + music {planned['music']}"
    return text


def join(planned: dict, *, account_id: Optional[int], title: Optional[str] = None,
         project_id: Optional[int] = None, dsn: Optional[str] = None) -> dict[str, Any]:
    """Save the planned cut as version 1 of a new scratch project, render
    it, file the MP4 on the Assets wall. Returns {"ok", "media_url",
    "asset_id", "ref", "generation_id", "seconds", "cut_project", "notes",
    "note"}; raises render.RenderError / sources.SourceError with a reason."""
    from .. import generative, render_assets
    from .. import media as media_mod
    from ..shot import Shot
    doc, fps = planned["doc"], planned["fps"]
    n = len(planned["handles"])
    title = (title or "").strip()[:200] or f"Joined {n} clips"
    row = store.create_project(account_id=account_id, title=title, fps=fps, dsn=dsn)
    tl = store.save_version(row["timeline_key"], doc, account_id=account_id, author="user",
                           op_summary=f"joined {n} clips" + (
                               f", crossfade {planned['crossfade_frames']}f"
                               if planned["crossfade_frames"] else ""), dsn=dsn)
    name = f"{row['timeline_key'].replace(':', '-')}-v{tl['version']}-{tl['id']}"
    with tempfile.TemporaryDirectory(prefix="zpf-join-") as tmp:
        paths, media = sources.gather(d.handles(doc), account_id=account_id, fps=fps,
                                      workdir=Path(tmp), dsn=dsn)
        result = render.render(doc, account_id=account_id, name=name, paths=paths,
                               media=media, dsn=dsn)
    store.set_export(tl["id"], result["stored"], account_id=account_id, dsn=dsn)
    stored = result["stored"] or result["url"]
    try:                                    # the wall's tile, as fal._publish draws one
        media_mod.mirror_poster(Path(result["path"]), f"renders/cut/{Path(result['path']).name}",
                                account_id)
    except Exception:                       # noqa: BLE001 -- the tile falls back to the clip
        pass

    text = describe(planned)
    params = {"provider": LOG_TOOL, "model": "join", "source": "mcp",
              "clips": planned["handles"], "transition": planned["transition"],
              "crossfade_frames": planned["crossfade_frames"], "music": planned["music"],
              "letterboxed": planned["letterboxed"], "canvas": planned["canvas"],
              "cut_project": row["id"], "timeline_id": tl["id"],
              "seconds": result["seconds"],
              **({"project_id": int(project_id)} if project_id else {})}
    shot_id = generative.add_shot(Shot(subject=title[:100], action="joined"),
                                  notes="joined by the studio MCP (assemble_clips)",
                                  dsn=dsn, account_id=account_id)
    generation_id = generative.record_generation(
        shot_id, LOG_TOOL, text, params=params, output_path=result["path"],
        cost_usd=None, notes="joined locally with ffmpeg -- no provider, no credits",
        dsn=dsn, account_id=account_id)
    asset = render_assets.record_best_effort(
        account_id=account_id, generation_id=generation_id, tool=LOG_TOOL, model="join",
        media_kind="video", prompt=text, media_url=stored, output_path=result["path"],
        metadata=params, dsn=dsn)
    asset_id = asset.get("id")
    return {"ok": True, "media_url": media_mod.url_for(stored, account_id) if stored else None,
            "asset_id": asset_id, "ref": f"gen:{asset_id}" if asset_id else None,
            "generation_id": generation_id, "media_kind": "video",
            "seconds": result["seconds"], "canvas": planned["canvas"],
            "cut_project": {"id": row["id"], "title": title, "version": tl["version"]},
            "notes": planned["notes"] + result["notes"], "credits": 0, "note": FREE_NOTE}


__all__ = ["JoinRefused", "plan", "join", "describe", "TRANSITIONS", "FREE_NOTE"]

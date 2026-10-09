"""
src/cut/assemble.py -- Assembly for ZPF's own work (docs/CUT_EDITOR.md 5.4.1).

For generated work, "assembly" means putting a concept's approved Queue
clips on the timeline in the order the scene was written: `timeline.py`'s
parts in window order for a timed scene, the shot's one clip otherwise
(and a legacy multi-shot concept's shots in order). Picture on V1 as hard
cuts -- the windows were WRITTEN as cuts, so a crossfade would be an
editorial decision nobody made; `add_transition` is there when one is
wanted. Each clip's own diegetic sound rides on A1 (role `sfx`), linked.

Optional, and only from uploaded `asset:` media (nothing in the pipeline
makes either yet):

- a music bed on A2 at MUSIC_GAIN_DB, trimmed to the picture, ducked under
  the voiceover when there is one and under the clips' own sound when
  there is not -- generated clips carry dialogue often enough that a bed
  running flat over it is the thing a person would fix first;
- a voiceover on A3, and captions on T1 when there is VO: cues given in
  seconds, or a plain script spread across the VO by length.

Two refusals, both with the list of what is wrong, and never a fallback:
a part with no clip yet (a cut with a hole in it is not a first cut), and
a clip with no generated_assets row (its handle would have to be a URL,
which is exactly what a doc may not carry).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from . import doc as d
from . import ops, sources, store
from . import validate as v

MUSIC_GAIN_DB = -12
MIN_CUE_FRAMES = 15


class AssembleError(ValueError):
    def __init__(self, reason: str, problems: Optional[list[str]] = None):
        self.problems = list(problems or [])
        super().__init__(reason + (": " + "; ".join(self.problems) if self.problems else ""))


# --------------------------------------------------------------------------
# which clips, in which order
# --------------------------------------------------------------------------

def clip_slots(concept: dict) -> list[dict[str, Any]]:
    """Every slot the cut needs a clip for, in order:
    [{"label", "media_url", "shot_n", "part"}]."""
    slots = []
    for i, shot in enumerate(concept.get("shots") or [], start=1):
        n = shot.get("n", i)
        tl = shot.get("timeline") or {}
        parts = sorted(tl.get("parts") or [], key=lambda p: p.get("n", 0))
        if parts:
            for p in parts:
                slots.append({"label": f"shot {n} part {p.get('n')}",
                              "media_url": (p.get("media_url") or "").strip() or None,
                              "shot_n": n, "part": p.get("n")})
        else:
            slots.append({"label": f"shot {n}",
                          "media_url": (shot.get("media_url") or "").strip() or None,
                          "shot_n": n, "part": None})
    return slots


def _asset_index(account_id: Optional[int], dsn: Optional[str]) -> dict[str, dict]:
    """media_url (and its storage tail) -> generated_assets row. Soft-
    deleted rows count: a render removed from the wall still plays in the
    concept that carries it, and so still cuts."""
    from .. import media, render_assets
    index: dict[str, dict] = {}
    for row in reversed(render_assets.list_all(dsn, account_id=account_id,
                                               include_deleted=True)):
        if row.get("media_kind") != "video":
            continue
        url = (row.get("media_url") or "").strip()
        for key in (url, media.tail_for(url)):
            if key:
                index[key] = row          # newest wins: list_all is newest first
    return index


def plan(concept_id: int, *, account_id: Optional[int],
         dsn: Optional[str] = None) -> dict[str, Any]:
    """The cheap half: which handles, in which order, and what is missing.
    No file is fetched or probed -- the route answers a refusal from this
    before starting a job."""
    from .. import media, preprod, timeline
    concept = preprod.get_concept(concept_id, dsn, account_id=account_id)
    if concept is None:
        raise LookupError(f"no concept {concept_id}")
    slots = clip_slots(concept)
    if not slots:
        raise AssembleError(f"concept {concept_id} has no shots")
    index = _asset_index(account_id, dsn)
    missing, clips = [], []
    for s in slots:
        if not s["media_url"]:
            missing.append(f"{s['label']} has no clip yet")
            continue
        row = index.get(s["media_url"]) or index.get(media.tail_for(s["media_url"]) or "")
        if row is None:
            missing.append(f"{s['label']}'s clip is not in the Asset Bank")
            continue
        clips.append({**s, "handle": d.handle("gen", row["id"])})
    notes = []
    for i, shot in enumerate(concept.get("shots") or [], start=1):
        if shot.get("timeline") and not timeline.is_current(shot):
            notes.append(f"shot {shot.get('n', i)}'s timeline is stale (its prompt changed "
                         "after planning) -- assembled the clips that were rendered")
    return {"concept": concept, "clips": clips, "missing": missing, "notes": notes}


# --------------------------------------------------------------------------
# captions
# --------------------------------------------------------------------------

def _script_cues(script: str, frames: int) -> list[dict]:
    """A plain script -> cues spread across `frames` in proportion to each
    sentence's length. Without word timestamps (the index, phase 2) this
    is an estimate, and it is labelled as one where it is used."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", script or "") if s.strip()]
    if not sentences or frames <= 0:
        return []
    total = sum(len(s) for s in sentences)
    cues, at = [], 0
    for k, s in enumerate(sentences):
        end = frames if k == len(sentences) - 1 else at + max(
            MIN_CUE_FRAMES, round(frames * len(s) / total))
        end = min(end, frames)
        if end <= at:
            break
        cues.append({"start": at, "end": end, "text": s})
        at = end
    return cues


def caption_cues(captions, fps: int, frames: int) -> list[dict]:
    """`captions` is a script string, or [{start, end, text}] in SECONDS
    (a person or a transcript speaks seconds; the doc speaks frames)."""
    if isinstance(captions, str):
        return _script_cues(captions, frames)
    cues = []
    for q in captions or []:
        start = min(d.to_frames(q["start"], fps), frames)
        end = min(d.to_frames(q["end"], fps), frames)
        if end > start and str(q.get("text") or "").strip():
            cues.append({"start": start, "end": end, "text": str(q["text"]).strip()})
    return cues


# --------------------------------------------------------------------------
# the doc
# --------------------------------------------------------------------------

def _even(x: int) -> int:
    return max(2, int(x) // 2 * 2)


def build_doc(clips: list[dict], media: dict[str, dict], *, fps: int = d.DEFAULT_FPS,
              music: Optional[str] = None, voice: Optional[str] = None,
              captions=None, transition_frames: int = 0,
              transition_style: str = d.DEFAULT_TRANSITION_STYLE) -> tuple[dict, list[str]]:
    """Pure: ordered clips ({"handle", "label"}) + probed media -> (doc,
    notes). Built through the ops, so the assembler cannot make a doc the
    agent could not.

    `transition_frames` (2026-10-09, the MCP's assemble_clips) crossfades
    INTO every clip after the first -- added as each clip lands, so its
    marker and everything laid after it (the music bed, trimmed to the
    picture) see the shortened cut. 0, Assemble's own use, is hard cuts:
    a concept's windows were written as cuts."""
    if not clips:
        raise AssembleError("nothing to assemble")
    notes: list[str] = []
    first = media[clips[0]["handle"]]
    size = ((_even(first["width"]), _even(first["height"]))
            if first.get("width") and first.get("height") else d.DEFAULT_SIZE)
    doc = d.new_doc(fps, size)
    doc["tracks"] = [{"id": "V1", "kind": "video", "clips": []},
                     {"id": "A1", "kind": "audio", "role": "sfx", "clips": []}]
    for i, c in enumerate(clips):
        info = media[c["handle"]]
        doc = ops.insert(doc, "V1", {"media": c["handle"], "src_in": 0,
                                     "src_out": info["frames"]},
                         sound_track="A1" if info.get("audio") else None)
        landed = d.track(doc, "V1")["clips"][-1]["id"]
        if transition_frames and i:
            doc = ops.add_transition(doc, landed, int(transition_frames),
                                     style=transition_style)
        start = next(x for x in d.track(doc, "V1")["clips"] if x["id"] == landed)["at"]
        doc = ops.add_marker(doc, start, c.get("label") or c["handle"])
    picture = doc["duration"]
    has_sfx = bool(d.track(doc, "A1")["clips"])

    if voice:
        vinfo = media[voice]
        doc["tracks"].append({"id": "A3", "kind": "audio", "role": "voice", "clips": []})
        doc = ops.insert(doc, "A3", {"media": voice, "src_in": 0,
                                     "src_out": min(vinfo["frames"], picture), "gain_db": 0},
                         at=0, ripple=False)
        if vinfo["frames"] > picture:
            notes.append(f"the voiceover runs {vinfo['frames'] - picture} frames past the picture "
                         "and was trimmed to it")
    if music:
        minfo = media[music]
        doc["tracks"].insert(2, {"id": "A2", "kind": "audio", "role": "music", "clips": []})
        doc = ops.insert(doc, "A2", {"media": music, "src_in": 0,
                                     "src_out": min(minfo["frames"], picture),
                                     "gain_db": MUSIC_GAIN_DB}, at=0, ripple=False)
        if minfo["frames"] < picture:
            notes.append("the music bed is shorter than the picture and ends early")
        under = "voice" if voice else ("sfx" if has_sfx else None)
        if under:
            doc = ops.duck(doc, "A2", under)
    if captions and not voice:
        notes.append("captions were given without a voiceover and were left out")
    elif captions:
        cues = caption_cues(captions, fps, min(picture, media[voice]["frames"]))
        if cues:
            doc = ops.add_caption_track(doc, cues, track_id="T1")
            if isinstance(captions, str):
                notes.append("caption timing is estimated from the script, not from the audio")
    if not d.track(doc, "A1")["clips"]:
        doc["tracks"] = [t for t in doc["tracks"] if t["id"] != "A1"]
    v.validate(doc, media)
    return doc, notes


def assemble(concept_id: int, *, account_id: Optional[int], workdir: Path,
             music: Optional[str] = None, voice: Optional[str] = None,
             captions=None, fps: int = d.DEFAULT_FPS, author: str = "assemble",
             dsn: Optional[str] = None) -> dict[str, Any]:
    """Build and store version N+1 of the concept's cut. Returns
    {"timeline", "paths", "media", "notes"}; `paths` point into `workdir`
    (or at local renders), so the caller renders before cleaning it up."""
    planned = plan(concept_id, account_id=account_id, dsn=dsn)
    if planned["missing"]:
        raise AssembleError("this cut is not ready", planned["missing"])
    for name, h in (("music", music), ("voice", voice)):
        if h is not None and (d.parse_handle(h) or ("",))[0] != "asset":
            raise AssembleError(f"{name} must be an asset:<id> handle")
    handles = [c["handle"] for c in planned["clips"]] + [h for h in (music, voice) if h]
    paths, media = sources.gather(handles, account_id=account_id, fps=fps,
                                  workdir=Path(workdir), dsn=dsn)
    doc, notes = build_doc(planned["clips"], media, fps=fps, music=music,
                           voice=voice, captions=captions)
    summary = f"assembled {len(planned['clips'])} clip(s)"
    if music:
        summary += " + music bed"
    if voice:
        summary += " + voiceover"
    row = store.save_version(store.project_for_concept(concept_id), doc,
                             account_id=account_id, author=author,
                             op_summary=summary, dsn=dsn)
    return {"timeline": row, "paths": paths, "media": media,
            "notes": planned["notes"] + notes}

"""
src/cut/otio.py -- the editable-project export (2026-10-01): a timeline doc
as OpenTimelineIO JSON (`.otio`), the interchange DaVinci Resolve (18.5+),
Premiere (through its OTIO adapter) and most NLEs read. doc.py was made
"OTIO-shaped" for exactly this, so the conversion is a straight walk: no
library, no I/O -- a doc and {handle: {"url", "name"}} in, a dict out.

What carries over, exactly:
- every picture and sound track, in order, its clips at their frames, and
  the GAPS between them;
- a clip's source range (src_in / span) against its media, by URL;
- a transition: our incoming clip starts `frames` early over the outgoing
  one. OTIO items abut and a transition borrows media across the cut, so
  the outgoing clip ends AT the incoming clip's start (`frames` shorter)
  and the transition's in_offset is those `frames` of the outgoing media
  past the cut. Same frames on screen, same total length;
- speed and reverse, as a LinearTimeWarp (negative for reverse) on an item
  whose duration is its TIMELINE length, starting at src_in (src_out when
  reversed) -- OTIO counts source_range.duration on the track and applies
  the warp to the media;
- markers, at their frames.

What does not (OTIO has no field for it): keyframes, crop, opacity, fades,
gains, the mixer, ducking. Every clip and track keeps its ZPF fields under
metadata["zpf"], so nothing is LOST -- an NLE ignores them, a round trip
back here can read them. Captions travel as an .srt beside the .otio
(`srt`), which every NLE imports.
"""
from __future__ import annotations

from typing import Any, Optional

from . import doc as d

SCHEMA_RT = "RationalTime.1"


def _rt(frames: float, fps: int) -> dict:
    return {"OTIO_SCHEMA": SCHEMA_RT, "rate": float(fps), "value": float(frames)}


def _range(start: float, duration: float, fps: int) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start, fps), "duration": _rt(duration, fps)}


def _gap(frames: int, fps: int) -> dict:
    return {"OTIO_SCHEMA": "Gap.1", "name": "", "source_range": _range(0, frames, fps),
            "effects": [], "markers": [], "metadata": {}}


def _zpf(obj: dict, drop: tuple[str, ...]) -> dict:
    return {k: v for k, v in obj.items() if k not in drop}


def _clip(c: dict, fps: int, media: dict[str, dict], length: int) -> dict:
    """One clip covering `length` timeline frames from its own start (a
    clip followed by a transition is cut short by it)."""
    info = media.get(c.get("media")) or {}
    # OTIO's convention: an item's source_range DURATION is its length on
    # the track (timeline frames) and its START is where in the media it
    # begins; a LinearTimeWarp says how fast the media is read from there
    # (negative: backwards from the end of the span)
    start = int(c["src_out"]) if c.get("reverse") else int(c["src_in"])
    used = length
    effects = []
    if d.is_retimed(c):
        effects.append({"OTIO_SCHEMA": "LinearTimeWarp.1", "name": "speed", "effect_name": "LinearTimeWarp",
                        "time_scalar": round(d.speed_of(c) * (-1 if c.get("reverse") else 1), 6),
                        "metadata": {}})
    ref = ({"OTIO_SCHEMA": "ExternalReference.1", "name": info.get("name") or c.get("media"),
            "target_url": info["url"], "available_range": None, "metadata": {}}
           if info.get("url") else
           {"OTIO_SCHEMA": "MissingReference.1", "name": info.get("name") or c.get("media"),
            "available_range": None, "metadata": {}})
    return {
        "OTIO_SCHEMA": "Clip.1",
        "name": info.get("name") or c.get("id"),
        "source_range": _range(start, used, fps),
        "media_reference": ref,
        "effects": effects,
        "markers": [],
        "metadata": {"zpf": _zpf(c, ("src_in", "src_out", "at"))},
    }


def _transition(frames: int, fps: int, style: Optional[str]) -> dict:
    return {"OTIO_SCHEMA": "Transition.1", "name": style or d.DEFAULT_TRANSITION_STYLE,
            "transition_type": "SMPTE_Dissolve",
            "in_offset": _rt(frames, fps), "out_offset": _rt(0, fps),
            "metadata": {"zpf": {"style": style or d.DEFAULT_TRANSITION_STYLE}}}


def _track(t: dict, fps: int, media: dict[str, dict]) -> dict:
    clips = sorted(t.get("clips") or [], key=lambda c: c["at"])
    children: list[dict] = []
    cursor = 0
    for i, c in enumerate(clips):
        nxt = clips[i + 1] if i + 1 < len(clips) else None
        tr = (nxt or {}).get("transition_in") or {}
        cut_short = int(tr.get("frames") or 0)
        if c["at"] > cursor:
            children.append(_gap(c["at"] - cursor, fps))
        length = d.clip_length(c) - cut_short
        children.append(_clip(c, fps, media, length))
        if cut_short:
            children.append(_transition(cut_short, fps, tr.get("style")))
        cursor = c["at"] + length
    kind = "Video" if t.get("kind") == "video" else "Audio"
    return {"OTIO_SCHEMA": "Track.1", "name": t.get("id"), "kind": kind, "children": children,
            "source_range": None, "effects": [], "markers": [],
            "metadata": {"zpf": _zpf(t, ("clips", "id", "kind"))}}


def timeline(doc: dict, media: dict[str, dict], *, name: str) -> dict[str, Any]:
    """The whole doc as one OTIO Timeline. `media` maps each handle to
    {"url", "name"}; a handle missing from it becomes a MissingReference
    (an NLE shows it offline, to be relinked by name)."""
    fps = int(doc["fps"])
    tracks = [_track(t, fps, media) for t in doc.get("tracks", [])
              if t.get("kind") in ("video", "audio")]
    markers = [{"OTIO_SCHEMA": "Marker.2", "name": m.get("label") or "", "color": "RED",
                "marked_range": _range(int(m["frame"]), 0, fps), "comment": "", "metadata": {}}
               for m in doc.get("markers") or []]
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": name,
        "global_start_time": _rt(0, fps),
        "metadata": {"zpf": {"fps": fps, "size": list(doc["size"]), "duration": doc["duration"]}},
        "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": tracks,
                   "source_range": None, "effects": [], "markers": markers, "metadata": {}},
    }


def _srt_time(frames: int, fps: int) -> str:
    ms = round(frames * 1000 / fps)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(doc: dict) -> Optional[str]:
    """Every caption cue as SubRip, in time order; None with no cues."""
    fps = int(doc["fps"])
    cues = sorted((q for t in d.tracks_of(doc, "caption") for q in t.get("cues") or []),
                  key=lambda q: (q["start"], q["end"]))
    if not cues:
        return None
    return "\n".join(f"{i}\n{_srt_time(q['start'], fps)} --> {_srt_time(q['end'], fps)}\n{q['text']}\n"
                     for i, q in enumerate(cues, 1))

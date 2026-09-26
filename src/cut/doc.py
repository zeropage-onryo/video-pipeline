"""
src/cut/doc.py -- the timeline document (docs/CUT_EDITOR.md section 5.1).

OTIO-shaped, so an interchange export later is a straight conversion, and
TIME IS INTEGER FRAMES at the project fps -- there are no float seconds
anywhere in the edit model. Seconds exist only at the two edges: a probe
turning a file's length into frames (`to_frames`), and the renderer turning
frames back into the seconds ffmpeg takes.

    {"fps": 30, "size": [720, 1280], "duration": 300,
     "tracks": [
       {"id": "V1", "kind": "video", "clips": [
          {"id": "c1", "media": "gen:812", "src_in": 0, "src_out": 150,
           "at": 0, "speed": 1, "transition_in": {"kind": "xfade", "frames": 8}}]},
       {"id": "A1", "kind": "audio", "role": "sfx", "clips": [
          {"id": "c1a", "media": "gen:812", ..., "link": "c1", "gain_db": 0}]},
       {"id": "A2", "kind": "audio", "role": "music", "duck_under": "sfx",
        "clips": [...]},
       {"id": "T1", "kind": "caption", "style": "preset:bold_center",
        "cues": [{"id": "q1", "start": 0, "end": 45, "text": "..."}]}],
     "markers": [{"frame": 150, "label": "Shot 2"}]}

A clip covers timeline frames [at, at + (src_out - src_in)). `src_in` /
`src_out` are frames INTO the media, at the project fps. `link` ties a
clip to a partner on another track (a video clip's own sound): the ops
move, trim, split and delete partners together, so picture and its sound
cannot drift apart.

`transition_in` is how a crossfade is spelled: the incoming clip starts
`frames` early, overlapping the tail of the clip before it by exactly that
much. That is the ONE overlap the validator allows on a track.

Pure module: no I/O, no database. What a handle points at is sources.py's
business.
"""
from __future__ import annotations

import re
from typing import Any, Optional

DEFAULT_FPS = 30
DEFAULT_SIZE = (720, 1280)          # 9:16, what every renderer here makes

TRACK_KINDS = ("video", "audio", "caption")
# Three fixed roles, no bus UI (CUT_EDITOR.md section 4). `sfx` is where a
# generated clip's own diegetic sound lands.
AUDIO_ROLES = ("voice", "music", "sfx")
TRANSITION_KINDS = ("xfade",)

# `gen:` is a generated_assets row (a render this pipeline paid for);
# `asset:` is a cut_media row (an uploaded music bed or voiceover).
HANDLE_KINDS = ("gen", "asset")
_HANDLE_RE = re.compile(r"^(gen|asset):([1-9][0-9]*)$")

DEFAULT_CAPTION_STYLE = "preset:bold_center"


def parse_handle(handle: Any) -> Optional[tuple[str, int]]:
    """`"gen:812"` -> `("gen", 812)`; anything else -> None. A URL is
    anything else, on purpose."""
    if not isinstance(handle, str):
        return None
    m = _HANDLE_RE.match(handle.strip())
    return (m.group(1), int(m.group(2))) if m else None


def handle(kind: str, id_: int) -> str:
    if kind not in HANDLE_KINDS:
        raise ValueError(f"unknown handle kind {kind!r}")
    return f"{kind}:{int(id_)}"


def to_frames(seconds: float, fps: int) -> int:
    """Seconds -> whole frames. Floors, so a clip is never claimed to be
    longer than the file actually is (a src_out one frame past the end is
    exactly what the validator refuses)."""
    return max(0, int(float(seconds) * fps + 1e-6))


def new_doc(fps: int = DEFAULT_FPS, size=DEFAULT_SIZE) -> dict:
    return {"fps": int(fps), "size": [int(size[0]), int(size[1])],
            "duration": 0, "tracks": [], "markers": []}


def clip_length(clip: dict) -> int:
    return int(clip["src_out"]) - int(clip["src_in"])


def clip_end(clip: dict) -> int:
    return int(clip["at"]) + clip_length(clip)


def track(doc: dict, track_id: str) -> Optional[dict]:
    for t in doc.get("tracks", []):
        if t.get("id") == track_id:
            return t
    return None


def tracks_of(doc: dict, kind: str, role: Optional[str] = None) -> list[dict]:
    return [t for t in doc.get("tracks", [])
            if t.get("kind") == kind and (role is None or t.get("role") == role)]


def all_clips(doc: dict):
    """(track, clip) for every clip on a video or audio track."""
    for t in doc.get("tracks", []):
        for c in t.get("clips", []) or []:
            yield t, c


def find_clip(doc: dict, clip_id: str) -> Optional[tuple[dict, dict]]:
    for t, c in all_clips(doc):
        if c.get("id") == clip_id:
            return t, c
    return None


def partners(doc: dict, clip_id: str) -> list[tuple[dict, dict]]:
    """The clip and everything linked to it, either direction: a video
    clip and its own sound are one unit to every op that moves time."""
    found = find_clip(doc, clip_id)
    if not found:
        return []
    root = found[1].get("link") or clip_id
    return [(t, c) for t, c in all_clips(doc)
            if c.get("id") == root or c.get("link") == root]


def compute_duration(doc: dict) -> int:
    """The last frame anything occupies. Markers do not extend a cut."""
    end = 0
    for t in doc.get("tracks", []):
        for c in t.get("clips", []) or []:
            end = max(end, clip_end(c))
        for q in t.get("cues", []) or []:
            end = max(end, int(q["end"]))
    return end


def sort_track(t: dict) -> None:
    if "clips" in t:
        t["clips"].sort(key=lambda c: (int(c["at"]), c.get("id", "")))
    if "cues" in t:
        t["cues"].sort(key=lambda q: (int(q["start"]), q.get("id", "")))


def used_ids(doc: dict) -> set[str]:
    ids = {c.get("id") for _, c in all_clips(doc)}
    for t in doc.get("tracks", []):
        ids |= {q.get("id") for q in t.get("cues", []) or []}
    return {i for i in ids if i}


def fresh_id(doc: dict, stem: str = "c", taken=()) -> str:
    """An id nothing in the doc uses yet -- nor anything in `taken`, which
    is how one op hands out several before any of them is in the doc."""
    taken = used_ids(doc) | set(taken)
    n = 1
    while f"{stem}{n}" in taken:
        n += 1
    return f"{stem}{n}"


def handles(doc: dict) -> list[str]:
    """Every media handle the doc names, in first-use order."""
    out: list[str] = []
    for _, c in all_clips(doc):
        h = c.get("media")
        if h not in out:
            out.append(h)
    return out

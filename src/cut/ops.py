"""
src/cut/ops.py -- the edits (docs/CUT_EDITOR.md section 5.2).

Every op is a PURE function: it takes a doc and returns a new one, and the
doc it was handed is never touched (a deep copy is made first). That is
what makes versions free -- the old doc is still the old doc -- and what
lets an agent's proposed edit be computed, shown as a diff card and thrown
away without anything having happened.

The v0 set: insert, ripple_delete, trim, split, move, set_gain, duck,
add_caption_track, add_marker, add_transition. The editor (phase B,
2026-09-28) added what a person at a timeline reaches for that an
assembler never needed: lift (delete and leave the gap), set_canvas,
and the caption edits set_cue / delete_cue / set_caption_style. The
first live walk (T25, 2026-09-29) added add_track: a cut Assemble made
has V1 and A1 only, so a music bed had nowhere to land but behind the
clips' own sound. The rest
of section 5.2's list (swap_take, apply_look, match_grade, reframe)
arrives with the phases that need it. Keyframes, crop and opacity landed
2026-10-01 (set_key ...), and speed and reverse the same day (set_speed,
set_reverse): trim and split take TIMELINE frames on a sped clip and round
only the source point, so the timeline stays exact.

`describe(op, args, fps)` is the one-line summary a version is stored
under ("split c3 at 4.2s") -- written here, beside the ops, so a new op
cannot land without a way to say what it did.

Two rules every op keeps:

- **A clip and its linked partners are one unit** (`doc.partners`). Moving,
  trimming, splitting or deleting a video clip does the same to its own
  sound on the audio track, so picture and sound cannot drift.
- **An op raises `OpError` with a reason** when it cannot do what it was
  asked (no such clip, a split outside the clip), and `apply` runs the
  validator on the result. What an op does NOT do is second-guess a
  well-formed request that produces a bad doc -- that is the validator's
  job, and keeping it in one place is what makes the reason an agent gets
  back consistent whichever op it came from.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Optional

from . import doc as d
from . import lanes as ln
from . import validate as v


class OpError(ValueError):
    def __init__(self, reason, problems: Optional[list[str]] = None):
        self.problems = list(problems or [str(reason)])
        super().__init__(str(reason))


def _copy(doc: dict) -> dict:
    return copy.deepcopy(doc)


def _finish(doc: dict) -> dict:
    for t in doc.get("tracks", []):
        d.sort_track(t)
    doc["duration"] = d.compute_duration(doc)
    return doc


def _need_clip(doc: dict, clip_id: str) -> tuple[dict, dict]:
    found = d.find_clip(doc, clip_id)
    if not found:
        raise OpError(f"no clip {clip_id}")
    return found


def _need_track(doc: dict, track_id: str, kind: Optional[str] = None) -> dict:
    t = d.track(doc, track_id)
    if t is None:
        raise OpError(f"no track {track_id}")
    if kind and t.get("kind") != kind:
        raise OpError(f"track {track_id} is a {t.get('kind')} track, not {kind}")
    return t


def _need_int(name: str, value) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise OpError(f"{name} must be a whole frame number, got {value!r}")
    return value


def _after(t: dict, clip: dict) -> list[dict]:
    """The clips that come after `clip` on its track, in order."""
    ordered = sorted(t["clips"], key=lambda c: (c["at"], c.get("id", "")))
    i = next(i for i, c in enumerate(ordered) if c is clip)
    return ordered[i + 1:]


def _before(t: dict, clip: dict) -> Optional[dict]:
    ordered = sorted(t["clips"], key=lambda c: (c["at"], c.get("id", "")))
    i = next(i for i, c in enumerate(ordered) if c is clip)
    return ordered[i - 1] if i else None


def _shift(clips, delta: int) -> None:
    for c in clips:
        c["at"] += delta


# --------------------------------------------------------------------------
# the ops
# --------------------------------------------------------------------------

def insert(doc: dict, track_id: str, clip: dict, at: Optional[int] = None, *,
           ripple: bool = True, sound_track: Optional[str] = None) -> dict:
    """Put `clip` ({media, src_in, src_out}) on `track_id` at frame `at`
    (default: the end of the track). With `ripple`, everything from `at`
    onward on that track -- and on `sound_track` -- moves right by the
    clip's length. `sound_track` also places a linked copy on that audio
    track, which is how a clip arrives with its own sound.

    `at` must be a cut point: inserting into the middle of a clip is two
    ops (split, then insert), and doing it silently here would be a split
    nobody asked for."""
    doc = _copy(doc)
    t = _need_track(doc, track_id)
    if t.get("kind") == "caption":
        raise OpError("captions are cues, not clips -- use add_caption_track")
    for key in ("src_in", "src_out"):
        _need_int(key, clip.get(key))
    new = {k: copy.deepcopy(val) for k, val in clip.items() if k != "link"}
    new.setdefault("speed", 1)
    new.pop("transition_in", None)
    if not new.get("id") or new["id"] in d.used_ids(doc):
        new["id"] = d.fresh_id(doc)
    length = d.clip_length(new)
    if length <= 0:
        raise OpError("src_out must be after src_in")
    if at is None:
        at = max([d.clip_end(c) for c in t["clips"]] or [0])
    _need_int("at", at)
    targets = [t]
    sound = None
    if sound_track:
        sound = _need_track(doc, sound_track, "audio")
        targets.append(sound)
    for tr in targets:
        for c in tr["clips"]:
            if c["at"] < at < d.clip_end(c):
                raise OpError(f"frame {at} is inside clip {c['id']} on {tr['id']} -- split it first")
    if ripple:
        moved: dict[str, dict] = {}
        for tr in targets:
            for c in tr["clips"]:
                if c["at"] >= at:
                    for _, p in d.partners(doc, c["id"]):
                        moved[p["id"]] = p
        _shift(moved.values(), length)
    new["at"] = at
    t["clips"].append(new)
    if sound is not None:
        partner = {k: copy.deepcopy(val) for k, val in new.items() if k != "id"}
        partner["id"] = d.fresh_id(doc, stem=new["id"] + "a")
        partner["link"] = new["id"]
        partner.setdefault("gain_db", 0)
        sound["clips"].append(partner)
    return _finish(doc)


def ripple_delete(doc: dict, clip_id: str) -> dict:
    """Remove a clip (and its partners) and close the hole it leaves, on
    every track it was on. A gap that was already there before the clip
    stays -- only the clip's own span closes. The clip after it loses its
    transition_in, since what it faded from is gone."""
    doc = _copy(doc)
    _need_clip(doc, clip_id)
    for t, gone in d.partners(doc, clip_id):
        followers = _after(t, gone)
        tr = gone.get("transition_in") or {}
        start = gone["at"] + int(tr.get("frames") or 0)
        t["clips"] = [c for c in t["clips"] if c is not gone]
        if followers:
            nxt = followers[0]
            if nxt.get("transition_in"):
                # it overlapped the clip that is gone: it takes that
                # clip's place exactly, on a hard cut
                nxt.pop("transition_in", None)
                _shift(followers, start - nxt["at"])
            else:
                _shift(followers, start - d.clip_end(gone))
    return _finish(doc)


def trim(doc: dict, clip_id: str, *, head: int = 0, tail: int = 0,
         ripple: bool = False) -> dict:
    """Shorten (positive) or extend (negative) a clip's head and tail by
    whole frames. Without `ripple` the clip's frames stay where they are
    on the timeline (a head trim moves `at` forward). With `ripple` the
    clip keeps its start and everything after it moves to close, or make
    room for, the change."""
    doc = _copy(doc)
    _need_int("head", head)
    _need_int("tail", tail)
    _need_clip(doc, clip_id)
    for t, c in d.partners(doc, clip_id):
        followers = _after(t, c)
        before = d.clip_length(c)
        if d.is_retimed(c):
            # head / tail are timeline frames; the source moves by the
            # speed, and a reversed clip's head is the END of its source
            sp = d.speed_of(c)
            sh, st = round(head * sp), round(tail * sp)
            if c.get("reverse"):
                sh, st = st, sh
            c["src_in"] += sh
            c["src_out"] -= st
            c["dur"] = before - head - tail
            if c["dur"] <= 0 or d.span(c) <= 0:
                raise OpError(f"trimming {head}+{tail} frames leaves nothing of {c['id']}")
        else:
            c["src_in"] += head
            c["src_out"] -= tail
        if d.clip_length(c) <= 0:
            raise OpError(f"trimming {head}+{tail} frames leaves nothing of {c['id']}")
        if c.get("lanes"):
            # the keys are clip-relative: what remains keeps the motion it
            # had over that stretch, with a key at each new edge
            c["lanes"] = ln.window(c["lanes"], head, before - tail)
        if ripple:
            _shift(followers, -(head + tail))
        else:
            c["at"] += head
    return _finish(doc)


def split(doc: dict, clip_id: str, frame: int) -> dict:
    """Cut a clip in two at timeline `frame` (strictly inside it). The
    first half keeps the id and the transition in; the second half gets a
    fresh id, and its partners are split at the same frame and linked to
    it."""
    doc = _copy(doc)
    _need_int("frame", frame)
    _, root = _need_clip(doc, clip_id)
    if not root["at"] < frame < d.clip_end(root):
        raise OpError(f"frame {frame} is not inside clip {clip_id} "
                      f"({root['at']}-{d.clip_end(root)})")
    group = d.partners(doc, clip_id)
    root_id = root.get("link") or root["id"]
    ids: dict[str, str] = {}
    for _, c in group:
        ids[c["id"]] = d.fresh_id(doc, stem=c["id"] + "_", taken=ids.values())
    for t, c in group:
        if not c["at"] < frame < d.clip_end(c):
            raise OpError(f"frame {frame} is not inside linked clip {c['id']}")
        second = copy.deepcopy(c)
        second["id"] = ids[c["id"]]
        second.pop("transition_in", None)
        cut = frame - c["at"]
        whole = d.clip_length(c)
        second["at"] = frame
        if d.is_retimed(c):
            # the timeline splits exactly at `cut`; only the source point
            # rounds, kept inside the span so both halves have picture
            if d.span(c) < 2:
                raise OpError(f"clip {c['id']} is too short in its source to split")
            sc = min(max(round(cut * d.speed_of(c)), 1), d.span(c) - 1)
            if c.get("reverse"):
                second["src_out"] = c["src_out"] - sc
                c["src_in"] = c["src_out"] - sc
            else:
                second["src_in"] = c["src_in"] + sc
                c["src_out"] = c["src_in"] + sc
            c["dur"], second["dur"] = cut, whole - cut
        else:
            second["src_in"] = c["src_in"] + cut
            c["src_out"] = c["src_in"] + cut
        if c.get("lanes"):
            # each half keeps exactly the motion it had in the whole clip
            second["lanes"] = ln.window(c["lanes"], cut, whole)
            c["lanes"] = ln.window(c["lanes"], 0, cut)
        if c["id"] != root_id:
            second["link"] = ids[root_id]
        t["clips"].append(second)
    return _finish(doc)


def move(doc: dict, clip_id: str, at: int, *, track_id: Optional[str] = None) -> dict:
    """Slide a clip (and its partners, by the same amount) to `at`, and
    optionally onto another track of the same kind. Nothing else moves --
    a move is not a ripple -- and a transition stays with its clip; if the
    new place does not honour it, the validator says so."""
    doc = _copy(doc)
    _need_int("at", at)
    src, root = _need_clip(doc, clip_id)
    delta = at - root["at"]
    for _, c in d.partners(doc, clip_id):
        c["at"] += delta
    if track_id and track_id != src["id"]:
        dest = _need_track(doc, track_id)
        if dest.get("kind") != src.get("kind"):
            raise OpError(f"cannot move a {src.get('kind')} clip onto {track_id} "
                          f"({dest.get('kind')})")
        src["clips"] = [c for c in src["clips"] if c is not root]
        dest["clips"].append(root)
    return _finish(doc)


def set_gain(doc: dict, clip_id: str, db: float) -> dict:
    doc = _copy(doc)
    t, c = _need_clip(doc, clip_id)
    if t.get("kind") != "audio":
        raise OpError(f"clip {clip_id} is on {t['id']}, not an audio track -- "
                      "set the gain on its sound")
    if not isinstance(db, (int, float)) or isinstance(db, bool):
        raise OpError(f"gain must be a number of dB, got {db!r}")
    c["gain_db"] = round(float(db), 2)
    return _finish(doc)


def duck(doc: dict, track_id: str, under: Optional[str]) -> dict:
    """Make an audio track drop under another role (`sidechaincompress` at
    render), or stop ducking with `under=None`."""
    doc = _copy(doc)
    t = _need_track(doc, track_id, "audio")
    if under is None:
        t.pop("duck_under", None)
    else:
        if under not in d.AUDIO_ROLES:
            raise OpError(f"duck under must be one of {list(d.AUDIO_ROLES)}")
        t["duck_under"] = under
    return _finish(doc)


def add_caption_track(doc: dict, cues: list, *, track_id: Optional[str] = None,
                      style: str = d.DEFAULT_CAPTION_STYLE) -> dict:
    """A new caption track from `[{start, end, text}]` (frames). An EMPTY
    list is allowed when it is passed explicitly -- the editor adds a T
    track first and types cues onto it with set_cue -- but `cues` itself
    is still required, so an agent cannot add a track by forgetting it."""
    doc = _copy(doc)
    if not isinstance(cues, list):
        raise OpError("cues must be a list of {start, end, text} (it may be empty)")
    if style not in d.CAPTION_STYLES:
        raise OpError(f"caption style must be one of {list(d.CAPTION_STYLES)}")
    if track_id is None:
        n = 1
        while d.track(doc, f"T{n}"):
            n += 1
        track_id = f"T{n}"
    elif d.track(doc, track_id):
        raise OpError(f"track {track_id} already exists")
    made: list[dict] = []
    for q in cues:
        if not isinstance(q, dict):
            raise OpError(f"a cue is {{start, end, text}}, got {q!r}")
        made.append({"id": d.fresh_id(doc, stem="q", taken=[m["id"] for m in made]),
                     "start": q.get("start"), "end": q.get("end"),
                     "text": (q.get("text") or "").strip()})
    doc["tracks"].append({"id": track_id, "kind": "caption", "style": style, "cues": made})
    return _finish(doc)


def add_marker(doc: dict, frame: int, label: str) -> dict:
    doc = _copy(doc)
    _need_int("frame", frame)
    doc.setdefault("markers", []).append({"frame": frame, "label": str(label)})
    doc["markers"].sort(key=lambda m: m["frame"])
    return _finish(doc)


def add_transition(doc: dict, clip_id: str, frames: int, kind: str = "xfade") -> dict:
    """Turn the hard cut INTO `clip_id` into a crossfade of `frames`. The
    clip (and everything after it) slides left by `frames` so it overlaps
    the clip before by exactly that much -- the one overlap the validator
    permits. The cut must be a clean butt join: a gap has nothing to fade
    from, and an existing transition is changed by removing it first."""
    doc = _copy(doc)
    _need_int("frames", frames)
    if frames < 1:
        raise OpError("a transition is at least one frame")
    if kind not in d.TRANSITION_KINDS:
        raise OpError(f"transition kind must be one of {list(d.TRANSITION_KINDS)}")
    t, root = _need_clip(doc, clip_id)
    prev = _before(t, root)
    if prev is None or d.clip_end(prev) != root["at"] or root.get("transition_in"):
        raise OpError(f"clip {clip_id} does not start on a hard cut from the clip before it")
    for tr, c in d.partners(doc, clip_id):
        p = _before(tr, c)
        followers = _after(tr, c)
        if p is not None and d.clip_end(p) == c["at"]:
            c["transition_in"] = {"kind": kind, "frames": frames}
        c["at"] -= frames
        _shift(followers, -frames)
    return _finish(doc)


def lift(doc: dict, clip_id: str) -> dict:
    """Remove a clip (and its partners) and LEAVE THE GAP -- the other
    half of ripple_delete, the one an editor reaches for when timing
    after the clip is already right. Nothing moves. The clip after it
    loses its transition_in: what it faded from is gone, and a fade out
    of black was nobody's decision."""
    doc = _copy(doc)
    _need_clip(doc, clip_id)
    for t, gone in d.partners(doc, clip_id):
        followers = _after(t, gone)
        t["clips"] = [c for c in t["clips"] if c is not gone]
        if followers and followers[0].get("transition_in"):
            followers[0].pop("transition_in", None)
    return _finish(doc)


def overwrite(doc: dict, track_id: str, clip: dict, at: int, *,
              sound_track: Optional[str] = None) -> dict:
    """Lay `clip` on `track_id` at frame `at` OVER whatever is there, the
    Source viewer's Overwrite (Resolve's F10): nothing after it moves.
    Whatever occupies [at, at + length) on the target tracks is cleared
    first -- a clip straddling either edge is split there, and every piece
    inside is lifted -- so the place is empty when the clip lands. Clips
    are cleared as LINK GROUPS (split and lift both carry partners), so a
    picture is never overwritten out from under its own sound.

    Composed from split, lift and insert rather than written fresh: the
    validator already trusts those three, and a new op that re-derived
    their rules is how the rules would drift apart."""
    doc = _copy(doc)
    _need_track(doc, track_id)
    for key in ("src_in", "src_out"):
        _need_int(key, clip.get(key))
    _need_int("at", at)
    if at < 0:
        raise OpError("at cannot be negative")
    if int(clip["src_out"]) <= int(clip["src_in"]):
        raise OpError("src_out must be after src_in")
    length = d.clip_length(clip)
    end = at + length
    targets = [track_id] + ([sound_track] if sound_track else [])
    if sound_track:
        _need_track(doc, sound_track, "audio")
    # straddlers first: split at each edge, so every piece is either wholly
    # inside the region or wholly outside it
    for edge in (at, end):
        for tid in targets:
            for c in list(d.track(doc, tid)["clips"]):
                if c["at"] < edge < d.clip_end(c):
                    doc = split(doc, c["id"], edge)
    for tid in targets:
        while True:
            inside = [c for c in d.track(doc, tid)["clips"]
                      if c["at"] >= at and d.clip_end(c) <= end]
            if not inside:
                break
            doc = lift(doc, inside[0]["id"])
    return insert(doc, track_id, clip, at, ripple=False, sound_track=sound_track)


def set_speed(doc: dict, clip_id: str, speed: float, *, ripple: bool = True) -> dict:
    """Play a clip (and its linked sound) at `speed`x: 0.25 to 4, 1 to
    reset. The clip keeps its source span and takes `round(span / speed)`
    timeline frames. With `ripple` (the default, invideo's "Ripple
    timeline") what follows on each track moves to close or make room;
    without it, a clip that grows into its neighbour is the validator's to
    refuse. Keys stay at the same place IN THE CLIP (rescaled), so an
    animation keeps its shape at the new speed."""
    doc = _copy(doc)
    if not isinstance(speed, (int, float)) or isinstance(speed, bool):
        raise OpError(f"speed must be a number, got {speed!r}")
    if not d.MIN_SPEED <= speed <= d.MAX_SPEED:
        raise OpError(f"speed must be {d.MIN_SPEED:g} to {d.MAX_SPEED:g}, got {speed:g}")
    _need_clip(doc, clip_id)
    for t, c in d.partners(doc, clip_id):
        followers = _after(t, c)
        before = d.clip_length(c)
        dur = max(1, round(d.span(c) / speed))
        c.pop("speed", None)
        if dur == d.span(c):
            c.pop("dur", None)
        else:
            c["dur"] = dur
        if c.get("lanes") and before:
            for lane in c["lanes"]:
                seen: dict[int, dict] = {}
                for k in lane["keys"]:
                    seen[round(k["frame"] * dur / before)] = {**k, "frame": round(k["frame"] * dur / before)}
                lane["keys"] = [seen[f] for f in sorted(seen)]
        if ripple:
            _shift(followers, dur - before)
    return _finish(doc)


def set_reverse(doc: dict, clip_id: str, on: bool = True) -> dict:
    """Play a clip (and its linked sound) backwards, or forwards again.
    Its place and length on the timeline do not change."""
    doc = _copy(doc)
    if not isinstance(on, bool):
        raise OpError(f"on must be true or false, got {on!r}")
    _need_clip(doc, clip_id)
    for _, c in d.partners(doc, clip_id):
        if on:
            c["reverse"] = True
        else:
            c.pop("reverse", None)
    return _finish(doc)


def _need_picture(doc: dict, clip_id: str) -> dict:
    t, c = _need_clip(doc, clip_id)
    if t.get("kind") != "video":
        raise OpError(f"clip {clip_id} is on {t['id']}: keyframes, crop and opacity "
                      "belong to picture clips")
    return c


def _need_path(path: str) -> None:
    if path not in ln.PATHS:
        raise OpError(f"path must be one of {list(ln.PATHS)}, got {path!r}")


def set_key(doc: dict, clip_id: str, path: str, frame: int, value: float,
            ease: str = "linear") -> dict:
    """Put a key on one of a picture clip's lanes at a CLIP-RELATIVE frame
    (0 is its first frame on the timeline), replacing a key already there.
    A lane with one key is a constant -- setting a property while it is not
    animated is a key at frame 0."""
    doc = _copy(doc)
    c = _need_picture(doc, clip_id)
    _need_path(path)
    _need_int("frame", frame)
    if not 0 <= frame <= d.clip_length(c):
        raise OpError(f"frame {frame} is outside clip {clip_id} (0-{d.clip_length(c)})")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise OpError(f"{path} must be a number, got {value!r}")
    if ease not in ln.EASES:
        raise OpError(f"ease must be one of {list(ln.EASES)}")
    lanes = c.setdefault("lanes", [])
    lane = next((x for x in lanes if x.get("path") == path), None)
    if lane is None:
        lane = {"path": path, "keys": []}
        lanes.append(lane)
    lane["keys"] = sorted([k for k in lane["keys"] if k["frame"] != frame]
                          + [{"frame": frame, "value": round(float(value), 6), "ease": ease}],
                          key=lambda k: k["frame"])
    return _finish(doc)


def delete_key(doc: dict, clip_id: str, path: str, frame: int) -> dict:
    """Remove one key. The last key going takes the lane with it (the
    property returns to its default)."""
    doc = _copy(doc)
    c = _need_picture(doc, clip_id)
    _need_path(path)
    lane = ln.lane(c, path)
    if not lane or not any(k["frame"] == frame for k in lane["keys"]):
        raise OpError(f"no {path} key at frame {frame} on {clip_id}")
    lane["keys"] = [k for k in lane["keys"] if k["frame"] != frame]
    if not lane["keys"]:
        c["lanes"] = [x for x in c["lanes"] if x is not lane]
        if not c["lanes"]:
            c.pop("lanes")
    return _finish(doc)


def clear_lane(doc: dict, clip_id: str, path: str) -> dict:
    """Reset one property: its lane goes, it is back at its default."""
    doc = _copy(doc)
    c = _need_picture(doc, clip_id)
    _need_path(path)
    if ln.lane(c, path) is None:
        raise OpError(f"{clip_id} has no {path} to reset")
    c["lanes"] = [x for x in c["lanes"] if x.get("path") != path]
    if not c["lanes"]:
        c.pop("lanes")
    return _finish(doc)


def set_crop(doc: dict, clip_id: str, left: float = 0, right: float = 0,
             top: float = 0, bottom: float = 0) -> dict:
    """Cut each edge of the picture in, as a fraction of its own width or
    height (0.1 = a tenth). All zero removes the crop. Static per clip."""
    doc = _copy(doc)
    c = _need_picture(doc, clip_id)
    sides = {"left": left, "right": right, "top": top, "bottom": bottom}
    for k, x in sides.items():
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            raise OpError(f"crop {k} must be a number, got {x!r}")
    if all(x == 0 for x in sides.values()):
        c.pop("crop", None)
    else:
        c["crop"] = {k: round(float(x), 4) for k, x in sides.items()}
    return _finish(doc)


def set_opacity(doc: dict, clip_id: str, value: float) -> dict:
    """The picture's opacity, 0 to 1 (1 removes it). Static per clip."""
    doc = _copy(doc)
    c = _need_picture(doc, clip_id)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise OpError(f"opacity must be a number, got {value!r}")
    if value >= 1:
        c.pop("opacity", None)
    else:
        c["opacity"] = round(float(value), 4)
    return _finish(doc)


def set_canvas(doc: dict, width: int, height: int) -> dict:
    """Change the frame size. Every clip is fitted into the new frame at
    render (scale to fit, pad black), so nothing on the timeline moves;
    the validator holds the size to even numbers."""
    doc = _copy(doc)
    doc["size"] = [_need_int("width", width), _need_int("height", height)]
    return _finish(doc)


def _need_caption_track(doc: dict, track_id: str) -> dict:
    t = _need_track(doc, track_id, "caption")
    t.setdefault("cues", [])
    return t


def set_cue(doc: dict, track_id: str, start: int, end: int, text: str,
            cue_id: Optional[str] = None) -> dict:
    """Add a cue to a caption track, or (with `cue_id`) replace that
    cue's timing and text. Creates nothing else: the track must exist
    (add_caption_track makes one), and an unknown cue_id is an error
    rather than a quiet add -- an edit to a cue that is gone should say so."""
    doc = _copy(doc)
    t = _need_caption_track(doc, track_id)
    _need_int("start", start)
    _need_int("end", end)
    if not isinstance(text, str):
        raise OpError(f"cue text must be text, got {text!r}")
    if cue_id is None:
        t["cues"].append({"id": d.fresh_id(doc, stem="q"), "start": start, "end": end,
                          "text": text.strip()})
    else:
        cue = next((q for q in t["cues"] if q.get("id") == cue_id), None)
        if cue is None:
            raise OpError(f"no cue {cue_id} on {track_id}")
        cue.update({"start": start, "end": end, "text": text.strip()})
    return _finish(doc)


def delete_cue(doc: dict, track_id: str, cue_id: str) -> dict:
    doc = _copy(doc)
    t = _need_caption_track(doc, track_id)
    if not any(q.get("id") == cue_id for q in t["cues"]):
        raise OpError(f"no cue {cue_id} on {track_id}")
    t["cues"] = [q for q in t["cues"] if q.get("id") != cue_id]
    return _finish(doc)


def add_track(doc: dict, kind: str, role: Optional[str] = None,
              track_id: Optional[str] = None) -> dict:
    """An empty track: `video`, `audio` (with a `role`) or `caption`. Its id
    is the next free V<n> / A<n> / T<n> unless one is asked for. A cut
    made by Assemble has no music track, and a bed laid on the sfx track
    would sit behind the clips' own sound and could not be ducked under it
    -- this is how the editor gives it a place of its own."""
    doc = _copy(doc)
    if kind not in d.TRACK_KINDS:
        raise OpError(f"track kind must be one of {list(d.TRACK_KINDS)}")
    if kind == "audio":
        if role not in d.AUDIO_ROLES:
            raise OpError(f"an audio track needs a role, one of {list(d.AUDIO_ROLES)}")
    elif role is not None:
        raise OpError(f"only audio tracks have a role, not {kind} tracks")
    prefix = {"video": "V", "audio": "A", "caption": "T"}[kind]
    if track_id is None:
        n = 1
        while d.track(doc, f"{prefix}{n}"):
            n += 1
        track_id = f"{prefix}{n}"
    elif d.track(doc, track_id):
        raise OpError(f"track {track_id} already exists")
    t: dict[str, Any] = {"id": track_id, "kind": kind}
    if kind == "audio":
        t["role"] = role
        t["clips"] = []
    elif kind == "caption":
        t["style"] = d.DEFAULT_CAPTION_STYLE
        t["cues"] = []
    else:
        t["clips"] = []
    doc["tracks"].append(t)
    return _finish(doc)


def set_caption_style(doc: dict, track_id: str, style: str) -> dict:
    doc = _copy(doc)
    t = _need_caption_track(doc, track_id)
    if style not in d.CAPTION_STYLES:
        raise OpError(f"caption style must be one of {list(d.CAPTION_STYLES)}")
    t["style"] = style
    return _finish(doc)


OPS: dict[str, Callable[..., dict]] = {
    "insert": insert,
    "ripple_delete": ripple_delete,
    "lift": lift,
    "set_canvas": set_canvas,
    "set_cue": set_cue,
    "delete_cue": delete_cue,
    "set_caption_style": set_caption_style,
    "trim": trim,
    "split": split,
    "move": move,
    "set_gain": set_gain,
    "duck": duck,
    "add_caption_track": add_caption_track,
    "add_marker": add_marker,
    "add_transition": add_transition,
    "add_track": add_track,
    "overwrite": overwrite,
    "set_key": set_key,
    "delete_key": delete_key,
    "clear_lane": clear_lane,
    "set_crop": set_crop,
    "set_opacity": set_opacity,
    "set_speed": set_speed,
    "set_reverse": set_reverse,
}


def apply(doc: dict, op: str, args: Optional[dict[str, Any]] = None, *,
          media: Optional[dict] = None) -> dict:
    """THE entry point for anything that is not this module's own tests:
    run one named op and validate what comes out. The agent's retry loop
    reads `OpError.problems`."""
    fn = OPS.get(op)
    if fn is None:
        raise OpError(f"unknown op {op!r}; the ops are {sorted(OPS)}")
    try:
        out = fn(doc, **(args or {}))
    except OpError:
        raise
    except TypeError as e:
        raise OpError(f"{op}: {e}") from None
    found = v.problems(out, media)
    if found:
        raise OpError(f"{op} would leave an invalid timeline", found)
    return out


def _secs(frames, fps: int) -> str:
    try:
        return f"{int(frames) / fps:.1f}s"
    except (TypeError, ValueError):
        return "?"


def describe(op: str, args: Optional[dict[str, Any]] = None, fps: int = d.DEFAULT_FPS) -> str:
    """A version's op_summary, in the words the version list shows:
    "split c3 at 4.2s", "trim c1 -10f head". Never raises -- a summary is
    a label, and a missing one must not fail an edit that validated."""
    a = args or {}
    clip_id = a.get("clip_id", "?")
    try:
        if op == "insert":
            c = a.get("clip") or {}
            where = f" at {_secs(a['at'], fps)}" if a.get("at") is not None else " at the end"
            return f"insert {c.get('media', '?')} on {a.get('track_id', '?')}{where}"
        if op in ("ripple_delete", "lift"):
            return f"{'delete' if op == 'ripple_delete' else 'lift'} {clip_id}"
        if op == "trim":
            parts = [f"{k} {int(a[k]):+d}f" for k in ("head", "tail") if a.get(k)]
            return f"trim {clip_id} " + (" ".join(parts) or "0f") + (" ripple" if a.get("ripple") else "")
        if op == "split":
            return f"split {clip_id} at {_secs(a.get('frame'), fps)}"
        if op == "move":
            to = f" to {a['track_id']}" if a.get("track_id") else ""
            return f"move {clip_id}{to} at {_secs(a.get('at'), fps)}"
        if op == "set_gain":
            return f"gain {clip_id} {float(a.get('db', 0)):+g} dB"
        if op == "duck":
            under = a.get("under")
            return (f"duck {a.get('track_id', '?')} under {under}" if under
                    else f"stop ducking {a.get('track_id', '?')}")
        if op == "add_caption_track":
            n = len(a.get("cues") or [])
            return f"add caption track ({n} cue{'s' if n != 1 else ''})"
        if op == "add_marker":
            return f"marker '{str(a.get('label', ''))[:30]}' at {_secs(a.get('frame'), fps)}"
        if op == "add_transition":
            return f"crossfade into {clip_id} ({a.get('frames', '?')}f)"
        if op == "set_key":
            return (f"{a.get('path', '?')} {float(a.get('value', 0)):g} on {clip_id} "
                    f"at +{_secs(a.get('frame'), fps)}")
        if op == "delete_key":
            return f"remove {a.get('path', '?')} key on {clip_id} at +{_secs(a.get('frame'), fps)}"
        if op == "clear_lane":
            return f"reset {a.get('path', '?')} on {clip_id}"
        if op == "set_crop":
            sides = [f"{k[0]}{float(a.get(k, 0)) * 100:.0f}%" for k in ("left", "right", "top", "bottom")
                     if a.get(k)]
            return f"crop {clip_id} " + (" ".join(sides) or "off")
        if op == "set_opacity":
            return f"opacity {clip_id} {float(a.get('value', 1)) * 100:.0f}%"
        if op == "set_speed":
            return f"speed {float(a.get('speed', 1)):g}x on {clip_id}"
        if op == "set_reverse":
            return f"{'reverse' if a.get('on', True) else 'play forwards'} {clip_id}"
        if op == "overwrite":
            c = a.get("clip") or {}
            return f"overwrite {c.get('media', '?')} on {a.get('track_id', '?')} at {_secs(a.get('at'), fps)}"
        if op == "add_track":
            what = a.get("role") or a.get("kind", "?")
            return f"add {what} track" + (f" {a['track_id']}" if a.get("track_id") else "")
        if op == "set_canvas":
            return f"canvas {a.get('width', '?')}x{a.get('height', '?')}"
        if op == "set_cue":
            verb = f"edit cue {a['cue_id']}" if a.get("cue_id") else "add cue"
            return f"{verb} on {a.get('track_id', '?')}: \"{str(a.get('text', ''))[:30]}\""
        if op == "delete_cue":
            return f"delete cue {a.get('cue_id', '?')} on {a.get('track_id', '?')}"
        if op == "set_caption_style":
            return (f"caption style {str(a.get('style', '?')).removeprefix('preset:')} "
                    f"on {a.get('track_id', '?')}")
    except (TypeError, ValueError, KeyError):
        pass
    return op

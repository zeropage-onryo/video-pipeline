"""
src/cut/validate.py -- the safety rail (docs/CUT_EDITOR.md section 5.2).

Every doc passes through here before it is stored or rendered, whoever
wrote it: `assemble`, a hand edit, and later an agent. That last one is why
this module exists at all. invideo's `stage@1` runtime refuses anything it
cannot prove well-formed; this is our version, and it is what makes an
agent's edit trustworthy the way id-only references made image sourcing
trustworthy. A rejected op goes back to the agent WITH THE REASON, so every
problem is a sentence naming the thing it is about.

`problems(doc, media)` returns every problem it finds (not just the first:
an agent retrying once should fix them all in one go). `validate` raises
`InvalidDoc` carrying the list.

`media` is optional: without it the structure is checked; with it
(handle -> {"frames", "video", "audio"}, from sources.probe) the doc is
also checked against what the files really are -- unknown handles,
src_out past the end of the media, a picture clip on a file with no
picture, sound from a file with no sound. A handle mapped to None is
KNOWN BUT UNMEASURED (a clip already on the timeline whose file could not
be probed this time): it is not called unknown, and nothing is checked
against it -- refusing every edit to a cut because one of its files is
briefly unreachable would make the whole cut uneditable.

Speed is `dur` (timeline frames) against the source span, 0.25x-4x, and
`reverse` a bool (2026-10-01); the old `speed` key is refused unless it is
1, because a doc carrying it would render as something other than what it
says. Keyframe lanes, crop and opacity
(lanes.py, 2026-10-01) are checked by lanes.check, on picture clips only.
"""
from __future__ import annotations

from typing import Optional

from . import doc as d
from . import lanes

MIN_GAIN_DB = -60.0
MAX_GAIN_DB = 12.0
MAX_FPS = 120
MAX_EDGE = 4096


class InvalidDoc(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems) or "invalid timeline")


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _check_header(doc: dict, out: list[str]) -> None:
    fps = doc.get("fps")
    if not _is_int(fps) or not 1 <= fps <= MAX_FPS:
        out.append(f"fps must be a whole number 1-{MAX_FPS}, got {fps!r}")
    size = doc.get("size")
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or not all(_is_int(v) and 2 <= v <= MAX_EDGE and v % 2 == 0 for v in size)):
        out.append(f"size must be [width, height], even whole numbers up to {MAX_EDGE}, got {size!r}")
    if not isinstance(doc.get("tracks"), list):
        out.append("tracks must be a list")
    if not isinstance(doc.get("markers", []), list):
        out.append("markers must be a list")


def _check_clip(t: dict, c: dict, media: Optional[dict], out: list[str]) -> bool:
    """Field checks for one clip. False when its numbers are unusable, so
    the overlap pass does not do arithmetic on garbage."""
    cid = c.get("id") or "?"
    where = f"clip {cid} on {t.get('id')}"
    ok = True
    for key in ("src_in", "src_out", "at"):
        if not _is_int(c.get(key)):
            out.append(f"{where}: {key} must be a whole frame number, got {c.get(key)!r}")
            ok = False
    if ok:
        if c["src_in"] < 0 or c["at"] < 0:
            out.append(f"{where}: src_in and at cannot be negative")
            ok = False
        if c["src_out"] <= c["src_in"]:
            out.append(f"{where}: src_out ({c['src_out']}) must be after src_in ({c['src_in']})")
            ok = False
    if c.get("speed", 1) != 1:
        out.append(f"{where}: speed is set with set_speed (a clip's dur), "
                   f"the speed key must be 1, got {c.get('speed')!r}")
    if c.get("dur") is not None:
        dur = c["dur"]
        if not _is_int(dur) or dur < 1:
            out.append(f"{where}: dur must be a whole number of frames >= 1, got {dur!r}")
            ok = False
        elif ok:
            sp = d.span(c) / dur
            if not d.MIN_SPEED - 1e-9 <= sp <= d.MAX_SPEED + 1e-9:
                out.append(f"{where}: speed {sp:.2f}x is outside {d.MIN_SPEED:g}x-{d.MAX_SPEED:g}x")
    if c.get("reverse") is not None and not isinstance(c["reverse"], bool):
        out.append(f"{where}: reverse must be true or false, got {c['reverse']!r}")
    if c.get("crop") is not None or c.get("opacity") is not None:
        if t.get("kind") != "video":
            out.append(f"{where}: crop and opacity belong to picture clips")
    if c.get("lanes") is not None or c.get("crop") is not None or c.get("opacity") is not None:
        paths = lanes.PATHS if t.get("kind") == "video" else lanes.AUDIO_PATHS
        out.extend(lanes.check(c, d.clip_length(c) if ok else 0, where, paths))
    for key in ("fade_in", "fade_out"):
        f = c.get(key)
        if f is None:
            continue
        if t.get("kind") != "audio":
            out.append(f"{where}: {key} belongs to sound clips")
        elif not _is_int(f) or f < 0 or (ok and f > d.clip_length(c)):
            out.append(f"{where}: {key} must be 0 to the clip's length in frames, got {f!r}")
    gain = c.get("gain_db", 0)
    if not isinstance(gain, (int, float)) or isinstance(gain, bool) \
            or not MIN_GAIN_DB <= gain <= MAX_GAIN_DB:
        out.append(f"{where}: gain_db must be {MIN_GAIN_DB:g} to {MAX_GAIN_DB:g} dB, got {gain!r}")
    tr = c.get("transition_in")
    if tr is not None:
        if not isinstance(tr, dict) or tr.get("kind") not in d.TRANSITION_KINDS:
            out.append(f"{where}: transition_in kind must be one of {list(d.TRANSITION_KINDS)}")
        elif tr.get("style", d.DEFAULT_TRANSITION_STYLE) not in d.TRANSITION_STYLES:
            out.append(f"{where}: transition style {tr.get('style')!r} is not one this editor renders")
        elif not _is_int(tr.get("frames")) or tr["frames"] < 1:
            out.append(f"{where}: transition_in frames must be a whole number >= 1")
        elif ok and tr["frames"] >= d.clip_length(c):
            out.append(f"{where}: a {tr['frames']}-frame transition is as long as the clip")

    h = c.get("media")
    if d.parse_handle(h) is None:
        out.append(f"{where}: media must be a gen:<id> or asset:<id> handle, got {h!r}")
    elif media is not None and not (h in media and media[h] is None):
        info = media.get(h)
        if info is None:
            out.append(f"{where}: unknown media handle {h}")
        else:
            if ok and c["src_out"] > int(info.get("frames", 0)):
                out.append(f"{where}: src_out {c['src_out']} is past the end of {h} "
                           f"({info.get('frames', 0)} frames)")
            if t.get("kind") == "video" and not info.get("video"):
                out.append(f"{where}: {h} has no picture")
            if t.get("kind") == "audio" and not info.get("audio"):
                out.append(f"{where}: {h} has no sound")
    return ok


def _check_overlaps(t: dict, clips: list[dict], out: list[str]) -> None:
    """Sorted by `at`: each clip may start no earlier than the previous
    one ends, except by EXACTLY its own transition_in -- a crossfade is a
    deliberate overlap of a stated length, anything else is two clips
    fighting for the same frames."""
    ordered = sorted(clips, key=lambda c: c["at"])
    prev = None
    for c in ordered:
        tr = c.get("transition_in") or {}
        frames = tr.get("frames") if _is_int(tr.get("frames")) else 0
        if prev is None:
            if frames:
                out.append(f"clip {c.get('id')} on {t.get('id')}: a transition needs a clip before it")
        else:
            prev_end = d.clip_end(prev)
            if frames:
                if c["at"] != prev_end - frames:
                    out.append(f"clip {c.get('id')} on {t.get('id')}: its {frames}-frame transition "
                               f"must start {frames} frames before {prev.get('id')} ends "
                               f"(at {prev_end - frames}, not {c['at']})")
                elif frames >= d.clip_length(prev):
                    out.append(f"clip {c.get('id')} on {t.get('id')}: its transition is longer "
                               f"than {prev.get('id')}")
            elif c["at"] < prev_end:
                out.append(f"clips {prev.get('id')} and {c.get('id')} overlap on {t.get('id')} "
                           f"(frames {c['at']}-{prev_end})")
        prev = c


def _check_cues(t: dict, out: list[str]) -> None:
    style = t.get("style", d.DEFAULT_CAPTION_STYLE)
    if style not in d.CAPTION_STYLES:
        out.append(f"caption track {t.get('id')}: style must be one of "
                   f"{list(d.CAPTION_STYLES)}, got {style!r}")
    cues = t.get("cues")
    if not isinstance(cues, list):
        out.append(f"caption track {t.get('id')}: cues must be a list")
        return
    good = []
    for q in cues:
        qid = q.get("id") or "?"
        if not (_is_int(q.get("start")) and _is_int(q.get("end"))):
            out.append(f"cue {qid} on {t.get('id')}: start and end must be whole frames")
            continue
        if q["start"] < 0 or q["end"] <= q["start"]:
            out.append(f"cue {qid} on {t.get('id')}: end must be after start, and start >= 0")
            continue
        if not isinstance(q.get("text"), str) or not q["text"].strip():
            out.append(f"cue {qid} on {t.get('id')}: text is empty")
        good.append(q)
    good.sort(key=lambda q: q["start"])
    for a, b in zip(good, good[1:]):
        if b["start"] < a["end"]:
            out.append(f"cues {a.get('id')} and {b.get('id')} overlap on {t.get('id')}")


def problems(doc: dict, media: Optional[dict] = None) -> list[str]:
    out: list[str] = []
    if not isinstance(doc, dict):
        return ["a timeline must be an object"]
    _check_header(doc, out)
    if not isinstance(doc.get("tracks"), list):
        return out

    seen_tracks: set = set()
    seen_ids: set = set()
    clip_ids: set = set()
    usable = True
    for t in doc["tracks"]:
        tid = t.get("id")
        if not tid or not isinstance(tid, str):
            out.append("every track needs a string id")
        elif tid in seen_tracks:
            out.append(f"track id {tid} is used twice")
        seen_tracks.add(tid)
        kind = t.get("kind")
        if kind not in d.TRACK_KINDS:
            out.append(f"track {tid}: kind must be one of {list(d.TRACK_KINDS)}, got {kind!r}")
            continue
        if kind == "caption":
            _check_cues(t, out)
            for q in t.get("cues") or []:
                if q.get("id") in seen_ids:
                    out.append(f"id {q.get('id')} is used twice")
                seen_ids.add(q.get("id"))
            continue
        if kind == "audio":
            if t.get("role") not in d.AUDIO_ROLES:
                out.append(f"audio track {tid}: role must be one of {list(d.AUDIO_ROLES)}")
            g = t.get("gain_db", 0)
            if not isinstance(g, (int, float)) or isinstance(g, bool) or not MIN_GAIN_DB <= g <= MAX_GAIN_DB:
                out.append(f"audio track {tid}: gain_db must be {MIN_GAIN_DB:g} to {MAX_GAIN_DB:g} dB, got {g!r}")
            pan = t.get("pan", 0)
            if not isinstance(pan, (int, float)) or isinstance(pan, bool) or not -1 <= pan <= 1:
                out.append(f"audio track {tid}: pan must be -1 (left) to 1 (right), got {pan!r}")
        elif t.get("gain_db") is not None or t.get("pan") is not None:
            out.append(f"track {tid}: only an audio track has a fader and pan")
        clips = t.get("clips")
        if not isinstance(clips, list):
            out.append(f"track {tid}: clips must be a list")
            continue
        fine = []
        for c in clips:
            cid = c.get("id")
            if not cid or not isinstance(cid, str):
                out.append(f"a clip on {tid} has no id")
            elif cid in seen_ids:
                out.append(f"id {cid} is used twice")
            seen_ids.add(cid)
            clip_ids.add(cid)
            if _check_clip(t, c, media, out):
                fine.append(c)
            else:
                usable = False
        _check_overlaps(t, fine, out)

    for t in doc["tracks"]:
        if t.get("kind") != "audio":
            continue
        under = t.get("duck_under")
        if under is None:
            continue
        if under not in d.AUDIO_ROLES:
            out.append(f"audio track {t.get('id')}: duck_under must be a role, got {under!r}")
        elif under == t.get("role"):
            out.append(f"audio track {t.get('id')}: cannot duck under its own role")
    for t, c in d.all_clips(doc):
        link = c.get("link")
        if link is not None and link not in clip_ids:
            out.append(f"clip {c.get('id')}: links to {link}, which is not a clip")

    duration = doc.get("duration")
    if not _is_int(duration):
        out.append(f"duration must be a whole frame count, got {duration!r}")
    elif usable:
        actual = d.compute_duration(doc)
        if duration != actual:
            out.append(f"duration says {duration} frames but the tracks end at {actual}")
    for m in doc.get("markers") or []:
        if not isinstance(m, dict) or not _is_int(m.get("frame")) or m["frame"] < 0:
            out.append(f"marker {m!r}: frame must be a whole number >= 0")
        elif _is_int(duration) and m["frame"] > duration:
            out.append(f"marker at {m['frame']} is past the end ({duration})")
        elif not isinstance(m.get("label"), str):
            out.append(f"marker at {m['frame']}: label must be text")
    return out


def validate(doc: dict, media: Optional[dict] = None) -> dict:
    found = problems(doc, media)
    if found:
        raise InvalidDoc(found)
    return doc

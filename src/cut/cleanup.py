"""
src/cut/cleanup.py -- Clean up and Captions, the two agent jobs that need
no model (docs/CUT_EDITOR.md 5.4 job 3, phase E, 2026-09-28).

Both read the index's WORD timings (moments.py: `media_moments` rows of
kind `word`, frames at the index fps on `media_index`) and turn them into
ops -- the LLM decides and the helpers do the arithmetic, and here there
is nothing to decide. Neither saves anything: each answers a Proposal
(agent_tools.proposal) the person Keeps or Undoes, exactly like an
agent turn, and its ops have already passed ops.apply against the head.

Clean up: for every clip whose SOUND is on the timeline (a picture clip
with its linked sound, or a clip of its own on a voice track), the
silences between consecutive words inside the part of the file the clip
uses -- longer than `min_silence`, trimmed to leave AIR_S of air each
side -- and the filler words, each removed from the timeline:

- in the middle of a clip: split at the region's start, split the new
  piece at its end, ripple_delete the middle piece;
- touching a clip's head or tail: a ripple trim;
- the whole clip: ripple_delete.

Regions are applied from the END of the timeline backwards, so the frame
numbers computed off the base doc stay true for every region still to
come (a ripple only moves what is after it). Each region's ops are run
through ops.apply as they are built; a region whose ops would leave an
invalid timeline (a marker the cut would strand past the end, a sound
clip that was trimmed apart from its picture) is skipped with a note and
the rest still land. A region inside a crossfade's overlap is clipped out
of it -- cutting inside a transition is not a cleanup decision.

Captions: the words of the sound actually on the timeline, mapped
through each clip's src_in / at (a word outside the used part of the
file is dropped), grouped into cues of at most `max_words` words and
MAX_CUE_S seconds, broken at any pause over PAUSE_S.
"""
from __future__ import annotations

import string
from typing import Any, Optional

from . import agent_tools, moments, ops, projects, store
from . import doc as d

AIR_S = 0.12
DEFAULT_MIN_SILENCE = 0.6
FILLERS = ("um", "uh", "erm", "er", "ah", "hmm")
MAX_CUE_S = 2.5
PAUSE_S = 0.4
DEFAULT_MAX_WORDS = 6


class Stale(RuntimeError):
    def __init__(self, head_id: Optional[int]):
        self.head_id = head_id
        super().__init__("this cut has changed since you loaded it")


def _norm(word: str) -> str:
    return str(word or "").strip().strip(string.punctuation + "…“”’").lower()


# --------------------------------------------------------------------------
# the words
# --------------------------------------------------------------------------

def word_timings(handles, *, account_id: Optional[int],
                 dsn: Optional[str] = None) -> tuple[dict[str, dict], list[str]]:
    """({handle: {"fps", "words"}}, needs_index) for the handles asked
    about. A handle with no finished index row is listed in needs_index,
    never guessed at."""
    found: dict[str, dict] = {}
    needs: list[str] = []
    for h in dict.fromkeys(handles):
        row = moments.indexed(h, account_id=account_id, dsn=dsn)
        if row is None or row.get("status") != "done":
            needs.append(h)
            continue
        found[h] = {"fps": int(row["fps"] or d.DEFAULT_FPS),
                    "words": moments.moments_for(h, account_id=account_id, kind="word", dsn=dsn)}
    return found, needs


def _words_in(clip: dict, timing: dict, fps: int, *,
              context: bool = False) -> list[tuple[int, int, str]]:
    """The words of `clip`'s media inside the part of the file it uses,
    as (start, end, text) in PROJECT frames of the source, sorted.

    `context` also keeps the nearest word on either side of that span.
    A silence is measured between two words, and a cut placed in a pause
    -- the most natural place to cut -- leaves each half of the pause in
    a different clip with only ONE of its two words: without the
    neighbour, the half at a clip's head or tail is invisible. Callers
    clamp to the clip's span, so a neighbour only ever bounds a gap."""
    scale = fps / (timing.get("fps") or fps)
    every = []
    for w in timing.get("words") or []:
        a = int(round(int(w["start_f"]) * scale))
        b = int(round(int(w["end_f"]) * scale))
        every.append((a, max(b, a + 1), str(w.get("text") or "")))
    every.sort()
    inside = [w for w in every if w[1] > clip["src_in"] and w[0] < clip["src_out"]]
    if not context:
        return inside
    before = [w for w in every if w[1] <= clip["src_in"]]
    after = [w for w in every if w[0] >= clip["src_out"]]
    return before[-1:] + inside + after[:1]


# --------------------------------------------------------------------------
# clean up
# --------------------------------------------------------------------------

def sound_units(doc: dict, media: dict) -> tuple[list[tuple[dict, dict]], list[str]]:
    """(track, clip) for every piece of sound Clean up may cut, and a
    note for each picture clip whose file has sound that is not on the
    timeline (its words cannot be cut without cutting sound nobody hears).
    A still, or footage with no sound at all, is skipped quietly."""
    units, notes, seen = [], [], set()
    for t in d.tracks_of(doc, "video"):
        for c in t.get("clips") or []:
            group = d.partners(doc, c["id"])
            root = c.get("link") or c["id"]
            if root in seen:
                continue
            seen.add(root)
            sound = [(tr, x) for tr, x in group if tr.get("kind") == "audio"]
            if sound and d.is_retimed(sound[0][1]):
                notes.append(f"skipped {c['id']}: its sound is sped up, slowed or reversed")
                continue
            if sound:
                units.append(sound[0])
                continue
            info = media.get(c.get("media"))
            if info is not None and (info.get("still") or not info.get("audio")):
                continue
            notes.append(f"skipped {c['id']} ({c.get('media')}): its sound is not on the timeline")
    for t in d.tracks_of(doc, "audio", "voice"):
        for c in t.get("clips") or []:
            if len(d.partners(doc, c["id"])) == 1:
                if d.is_retimed(c):
                    notes.append(f"skipped {c['id']}: its sound is sped up, slowed or reversed")
                    continue
                units.append((t, c))
    return units, notes


def _safe_zone(doc: dict, clip: dict) -> tuple[int, int]:
    """The timeline frames of `clip` (and every clip linked to it) that
    are NOT inside a crossfade's overlap."""
    lo, hi = clip["at"], d.clip_end(clip)
    for t, c in d.partners(doc, clip["id"]):
        tr = int((c.get("transition_in") or {}).get("frames") or 0)
        lo = max(lo, c["at"] + tr)
        end = d.clip_end(c)
        for other in t.get("clips") or []:
            if other is not c and c["at"] < other["at"] < end:
                end = min(end, other["at"])
        hi = min(hi, end)
    return lo, hi


def find_regions(doc: dict, timings: dict[str, dict], units, *,
                 min_silence: float = DEFAULT_MIN_SILENCE,
                 fillers: bool = True) -> list[dict]:
    """Every region to remove, in TIMELINE frames of the base doc:
    {"from", "to", "track_id", "silences", "fillers"}, sorted by start.
    Pure."""
    fps = int(doc["fps"])
    air = int(round(AIR_S * fps))
    min_gap = min_silence * fps
    out = []
    for t, c in units:
        timing = timings.get(c.get("media"))
        if not timing:
            continue
        words = _words_in(c, timing, fps, context=True)
        found: list[list] = []
        for (_, a_end, _), (b_start, _, _) in zip(words, words[1:]):
            # a silence is measured word to word, even when a cut splits
            # it; the air is left beside a WORD, never beside a clip edge
            if b_start - a_end <= min_gap:
                continue
            lo = a_end + air if a_end >= c["src_in"] else c["src_in"]
            hi = b_start - air if b_start <= c["src_out"] else c["src_out"]
            if hi > lo:
                found.append([lo, hi, 1, 0])
        if fillers:
            for a, b, text in words:
                if _norm(text) in FILLERS:
                    a, b = max(a, c["src_in"]), min(b, c["src_out"])
                    if b > a:
                        found.append([a, b, 0, 1])
        found.sort()
        merged: list[list] = []
        for r in found:
            if merged and r[0] <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], r[1])
                merged[-1][2] += r[2]
                merged[-1][3] += r[3]
            else:
                merged.append(list(r))
        lo, hi = _safe_zone(doc, c)
        for a, b, n_sil, n_fill in merged:
            ta = max(c["at"] + (a - c["src_in"]), lo)
            tb = min(c["at"] + (b - c["src_in"]), hi)
            if tb > ta:
                out.append({"from": ta, "to": tb, "track_id": t["id"],
                            "silences": n_sil, "fillers": n_fill})
    return sorted(out, key=lambda r: (r["from"], r["track_id"]))


def _clip_at(doc: dict, track_id: str, frame: int) -> Optional[dict]:
    t = d.track(doc, track_id)
    for c in (t or {}).get("clips") or []:
        if c["at"] <= frame < d.clip_end(c):
            return c
    return None


def _region_ops(work: dict, r: dict, media: dict) -> tuple[list[dict], dict]:
    """The ops that remove one region from `work`, and the doc after
    them -- each op run through ops.apply, so a failure raises OpError
    here and never reaches a proposal."""
    c = _clip_at(work, r["track_id"], r["from"])
    if c is None:
        raise ops.OpError(f"no clip at frame {r['from']} on {r['track_id']}")
    ta, tb, start, end = r["from"], min(r["to"], d.clip_end(c)), c["at"], d.clip_end(c)
    steps: list[dict] = []

    def run(op, **args):
        nonlocal work
        work = ops.apply(work, op, args, media=media)
        steps.append({"op": op, "args": args})

    if ta == start and tb == end:
        run("ripple_delete", clip_id=c["id"])
    elif ta == start:
        run("trim", clip_id=c["id"], head=tb - ta, ripple=True)
    elif tb == end:
        run("trim", clip_id=c["id"], tail=tb - ta, ripple=True)
    else:
        before = {x["id"] for x in d.track(work, r["track_id"])["clips"]}
        run("split", clip_id=c["id"], frame=ta)
        middle = next(x for x in d.track(work, r["track_id"])["clips"]
                      if x["id"] not in before and x["at"] == ta)
        run("split", clip_id=middle["id"], frame=tb)
        run("ripple_delete", clip_id=middle["id"])
    return steps, work


def _fmt(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def cleanup(doc: dict, *, account_id: Optional[int], media: dict,
            min_silence: float = DEFAULT_MIN_SILENCE, fillers: bool = True,
            dsn: Optional[str] = None) -> dict[str, Any]:
    """{"ops", "doc", "needs_index", "found", "notes", "summary"} for one
    doc -- the ops already applied cleanly, in order, from the base."""
    units, notes = sound_units(doc, media)
    timings, needs = word_timings([c["media"] for _, c in units],
                                  account_id=account_id, dsn=dsn)
    regions = find_regions(doc, timings, units, min_silence=min_silence, fillers=fillers)
    fps = int(doc["fps"])
    work, op_list, sil, fil = doc, [], 0, 0
    for r in sorted(regions, key=lambda r: r["from"], reverse=True):
        try:
            steps, after = _region_ops(work, r, media)
        except (ops.OpError, StopIteration) as e:
            notes.append(f"left the {'filler' if r['fillers'] else 'silence'} at "
                         f"{r['from'] / fps:.1f}s alone: {e}"[:300])
            continue
        work = after
        op_list += steps
        sil += r["silences"]
        fil += r["fillers"]
    if op_list and any(q["end"] > regions[0]["from"] for t in d.tracks_of(doc, "caption")
                       for q in t.get("cues") or []):
        notes.append("captions were not moved with the cuts -- make them again after keeping this")
    parts = [p for p in (_fmt(sil, "silence") if sil else "",
                         _fmt(fil, "filler word") if fil else "") if p]
    delta = int(work.get("duration") or 0) - int(doc.get("duration") or 0)
    summary = (f"Removed {' and '.join(parts)}, {agent_tools.delta_label(delta, fps)}"
               if parts else "")
    if not op_list and not needs:
        notes.append(f"no silence over {min_silence:g}s"
                     + (" and no filler words" if fillers else "") + " to remove")
    return {"ops": op_list, "doc": work, "needs_index": needs,
            "found": {"silences": sil, "fillers": fil}, "notes": notes, "summary": summary}


# --------------------------------------------------------------------------
# captions
# --------------------------------------------------------------------------

def timeline_words(doc: dict, timings: dict[str, dict]) -> list[tuple[int, int, str]]:
    """Every word of the sound on the timeline (not the music) in
    TIMELINE frames: mapped through each clip's src_in / at (and its
    speed), and a word that starts outside the used part of its file
    dropped. A reversed clip's words are not captioned -- they are not
    words any more."""
    fps = int(doc["fps"])
    out = []
    for t in d.tracks_of(doc, "audio"):
        if t.get("role") == "music":
            continue
        for c in t.get("clips") or []:
            timing = timings.get(c.get("media"))
            if not timing or c.get("reverse"):
                continue
            for a, b, text in _words_in(c, timing, fps):
                if not c["src_in"] <= a < c["src_out"] or not text.strip():
                    continue
                b = min(b, c["src_out"])
                ta = int(round(d.timeline_frame(c, a)))
                tb = max(ta + 1, min(int(round(d.timeline_frame(c, b))), d.clip_end(c)))
                out.append((ta, tb, text.strip()))
    return sorted(out)


def group_cues(words: list[tuple[int, int, str]], fps: int, *,
               max_words: int = DEFAULT_MAX_WORDS) -> list[dict]:
    """Words -> [{start, end, text}]: at most `max_words` words and
    MAX_CUE_S seconds a cue, a new cue at any pause over PAUSE_S, and no
    cue overlapping the one before (two voices at once share the screen
    in turn, never on top of each other)."""
    max_len, pause = MAX_CUE_S * fps, PAUSE_S * fps
    groups: list[list] = []
    for w in words:
        g = groups[-1] if groups else None
        if (g is None or len(g) >= max(1, max_words) or w[0] - g[-1][1] > pause
                or w[1] - g[0][0] > max_len):
            groups.append([w])
        else:
            g.append(w)
    cues, prev_end = [], 0
    for g in groups:
        start, end = max(g[0][0], prev_end), max(w[1] for w in g)
        if end <= start:
            continue
        cues.append({"start": start, "end": end, "text": " ".join(w[2] for w in g)})
        prev_end = end
    return cues


def captions(doc: dict, *, account_id: Optional[int], track_id: Optional[str] = None,
             max_words: int = DEFAULT_MAX_WORDS, dsn: Optional[str] = None) -> dict[str, Any]:
    """{"ops", "cues", "needs_index", "notes", "summary"}. A new caption
    track, or -- when `track_id` names a caption track that exists -- one
    set_cue per cue that does not overlap a cue already on it. Raises
    ops.OpError when `track_id` names a track that is not a caption track."""
    notes: list[str] = []
    handles = [c["media"] for t in d.tracks_of(doc, "audio") if t.get("role") != "music"
               for c in t.get("clips") or []]
    timings, needs = word_timings(handles, account_id=account_id, dsn=dsn)
    fps = int(doc["fps"])
    cues = group_cues(timeline_words(doc, timings), fps, max_words=max_words)
    existing = d.track(doc, track_id) if track_id else None
    if existing is not None and existing.get("kind") != "caption":
        raise ops.OpError(f"track {track_id} is a {existing.get('kind')} track, not captions")
    op_list: list[dict] = []
    if existing is not None:
        taken = [(q["start"], q["end"]) for q in existing.get("cues") or []]
        fresh = [q for q in cues if not any(q["start"] < b and a < q["end"] for a, b in taken)]
        if len(fresh) < len(cues):
            notes.append(f"{len(cues) - len(fresh)} cue(s) left out: {track_id} already has "
                         "captions there")
        op_list = [{"op": "set_cue", "args": {"track_id": track_id, **q}} for q in fresh]
        cues = fresh
    elif cues:
        args: dict[str, Any] = {"cues": cues}
        if track_id:
            args["track_id"] = track_id
        op_list = [{"op": "add_caption_track", "args": args}]
    if not cues and not needs:
        notes.append("no spoken words on the timeline to caption")
    where = track_id if existing is not None else "a new caption track"
    summary = f"Captions: {_fmt(len(cues), 'cue')} on {where}" if cues else ""
    return {"ops": op_list, "cues": len(cues), "needs_index": needs, "notes": notes,
            "summary": summary}


# --------------------------------------------------------------------------
# against a project's head
# --------------------------------------------------------------------------

def _base(project: dict, base_id: Optional[int], *, account_id: Optional[int],
          dsn: Optional[str]) -> dict:
    head = store.head(project["timeline_key"], account_id=account_id, dsn=dsn)
    if head is None or (base_id is not None and head["id"] != base_id):
        raise Stale(head["id"] if head else None)
    return head


def propose_cleanup(project: dict, *, account_id: Optional[int], base_id: Optional[int] = None,
                    min_silence: float = DEFAULT_MIN_SILENCE, fillers: bool = True,
                    dsn: Optional[str] = None) -> dict[str, Any]:
    head = _base(project, base_id, account_id=account_id, dsn=dsn)
    doc = head["doc"]
    media = projects.media_for(doc, account_id=account_id, dsn=dsn)
    out = cleanup(doc, account_id=account_id, media=media, min_silence=min_silence,
                  fillers=fillers, dsn=dsn)
    prop = None
    if out["ops"]:
        after = projects.apply_all(doc, out["ops"], media=media)
        prop = agent_tools.proposal(head, out["ops"], after, summary=out["summary"],
                                    kind="cleanup")
    return {"proposal": prop, "needs_index": out["needs_index"], "found": out["found"],
            "notes": out["notes"]}


def propose_captions(project: dict, *, account_id: Optional[int], base_id: Optional[int] = None,
                     track_id: Optional[str] = None, max_words: int = DEFAULT_MAX_WORDS,
                     dsn: Optional[str] = None) -> dict[str, Any]:
    head = _base(project, base_id, account_id=account_id, dsn=dsn)
    doc = head["doc"]
    out = captions(doc, account_id=account_id, track_id=track_id, max_words=max_words, dsn=dsn)
    prop = None
    if out["ops"]:
        media = projects.media_for(doc, account_id=account_id, dsn=dsn)
        after = projects.apply_all(doc, out["ops"], media=media)
        prop = agent_tools.proposal(head, out["ops"], after, summary=out["summary"],
                                    kind="captions")
    return {"proposal": prop, "needs_index": out["needs_index"], "cues": out["cues"],
            "notes": out["notes"]}

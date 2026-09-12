#!/usr/bin/env python3
"""
src/timeline.py -- a scene's timed windows, as the separate shots that get
rendered (2026-09-10, Mike's call).

A scene prompt may now carry several shots, cuts and locations, each in its
own time window -- (0-3s) one shot, (3-7s) a different one. That is how the
scene is WRITTEN. It is not how it is RENDERED: every window becomes its own
clip, rendered one after another, each by a model that has never seen the
others. So between the scene and the renderer sits one planning step, run on
the same brain the scene was written on:

    scene prompt + its reference photos
        -> continuity   the scene's memory, written once and put in front of
                        every shot (same face, same clothes, same prop, same
                        light), because nothing else carries over
        -> parts        one standalone prompt per window, each with ONLY the
                        reference photos that shot shows

Stored on the scene's ONE shot as `shot["timeline"]`, which keeps a concept
exactly the unit it has been since 2026-08-26 -- one row, one scene, one
entry in `shots`. `is_scene`, pick_rate, the Queue and the board all keep
reading `len(shots) == 1`; the parts live one level down.

Three rules worth keeping:

- **Refs are chosen by NUMBER from the scene's own set, never by URL** (the
  closed-set rule image sourcing already follows). A part can only narrow
  the scene's references, never add one -- so the reference gate asked of the
  scene still covers every part, and order within a part keeps the scene's
  order (identity first, which is what an anchor slot needs).
- **Staleness is checked on READ.** A timeline records a hash of the prompt
  and refs it was planned from; a Director edit, a Polish or a new ref makes
  it stale and `ensure` re-plans. The saved-canvas lesson (`seed_hash`): a
  route added later that rewrites a prompt cannot forget to invalidate this.
- **No timed windows means no timeline**, and the scene renders as one clip
  exactly as before. Every scene written before 2026-09-10 is that case.

Never raises. A failed planning call degrades to a deterministic split (the
window's own sentence, the rest of the scene as context, every ref), and a
scene that cannot be split at all is simply not split.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Callable, Optional

from . import preprod

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "shot_timeline_prompt.txt"

# The whole-scene length the writers are asked to fill. One number the
# composer, the night and the MCP `generate` all default to, read per call
# like every other ZEROPAGE_* posture.
SCENE_SECONDS_ENV = "ZEROPAGE_SCENE_SECONDS"
DEFAULT_SCENE_SECONDS = 10
# Bounds on what a person may ask for. The floor is one shot's worth; the
# ceiling is not a renderer limit (each window renders on its own) but a
# planning one: past ~30s a "scene" is a sequence, and the writer starts
# padding windows to fill the clock.
MIN_SCENE_SECONDS = 4
MAX_SCENE_SECONDS = 30
SCENE_SECONDS_CHOICES = (5, 10, 15, 20, 30)
# The most parts one scene is split into. A 30s scene in 2s windows is 15
# clips, 15 stills and 15 renders; nobody asked for that, and the writer is
# told windows of 2-10s, so this only ever trims a runaway answer.
MAX_PARTS = 8

# --- WHAT A VIDEO MODEL IS ACTUALLY FOR (2026-09-12) ----------------------
# Every renderer this repo drives is image-to-video: it is handed a frame and
# a prompt. The frame already says what the shot LOOKS like -- so a prompt
# that describes the scene again is spending its whole budget restating what
# the model can see, and saying nothing about the only thing it has to
# invent, which is what changes across the window. Worse on the reference
# lane (runway.reference_mode), where there is no locked first frame at all
# and the prompt is carrying MORE of the load, not less.
#
# Two rules, both from the shot-prompt playbook and both things the models
# get wrong by default: a clip that starts and stops from a dead stop reads
# as an obvious generation, and a camera that moves independently of the
# subject reads as arbitrary. prompts/shot_timeline_prompt.txt already ASKS
# the planner for "Start mid-motion"; this is the same rule enforced at the
# render boundary, where asking is no longer good enough -- the planner is a
# model too, and a scene written before this line existed never heard it.
#
# Deliberately ~130 characters. The gen4 cap is 1000 (runway.PROMPT_LIMITS)
# and a director's prompt with its continuity block already runs close to
# it, so anything longer would start turning working renders into refusals.
# ZEROPAGE_MOTION_DIRECTIVE=0 turns it off for a prompt that needs the room.
MOTION_DIRECTIVE = (
    "RENDER THE CHANGE, not the frame: open already mid-motion, end still "
    "moving, and move the camera only with the subject."
)


def motion_directive() -> str:
    """The directive, or "" when it is switched off. Read per call like
    every other ZEROPAGE_* posture, so a test can set it either way."""
    if (os.environ.get("ZEROPAGE_MOTION_DIRECTIVE") or "").strip() == "0":
        return ""
    return MOTION_DIRECTIVE


def for_render(prompt: str) -> str:
    """One prompt, as a VIDEO renderer should receive it: the directive
    first, because these models weight the top of a prompt most heavily,
    then whatever the scene or the part already said.

    Applied in render_target and nowhere else, on purpose. render_prompt
    also feeds scene_chain's keyframe draw, and telling a STILL to open
    mid-motion is noise at best -- the frame is the one thing in this
    pipeline that is supposed to hold still."""
    prompt = (prompt or "").strip()
    directive = motion_directive()
    if not prompt or not directive:
        return prompt
    return f"{directive}\n\n{prompt}"


def scene_seconds(value=None) -> int:
    """The total length a scene is written to. `value` wins (the composer's
    select, an explicit graph argument); then ZEROPAGE_SCENE_SECONDS; then
    the default. Clamped, never refused: this is read from a form field and
    an env var on a 3:30am job, and a typo must write a 10s scene rather
    than fail the night -- the resolve_brain rule."""
    for raw in (value, os.environ.get(SCENE_SECONDS_ENV)):
        try:
            if raw is not None and str(raw).strip():
                seconds = int(float(str(raw).strip()))
                return max(MIN_SCENE_SECONDS, min(MAX_SCENE_SECONDS, seconds))
        except (TypeError, ValueError):
            continue
    return DEFAULT_SCENE_SECONDS


# "(0-3s)", "(0s-3s)", "(3–7 s)", "(7 - 10 sec)". At least one "s" is
# required so an ordinary parenthetical range -- "(2-3 people)" -- is not
# read as a clock.
_WINDOW = re.compile(
    r"\(\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds)?\s*(?:-|–|—|to)\s*"
    r"(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds)?\s*\)",
    re.IGNORECASE)
# Where the BEATS section ends and the sound / avoid blocks begin, so the
# last window's text does not swallow them.
_SECTION_BREAK = re.compile(
    r"\n\s*(?:\d\.\s*)?(?:SOUND|AVOID|AUDIO|NEGATIVE)\b|\n\s*[45]\.\s", re.IGNORECASE)


def parse_windows(prompt: str) -> list[dict]:
    """The timed windows a scene prompt carries, in order, each with the
    text that follows its marker: [{"start", "end", "seconds", "text"}].

    [] when the prompt has fewer than two windows -- a single window is one
    shot, which is what the scene already is, and splitting it would buy a
    planning call and nothing else. Windows that run backwards or have no
    length are dropped rather than repaired: they are model output, and
    guessing what it meant is how a 3s shot becomes a 30s render."""
    prompt = prompt or ""
    marks = [m for m in _WINDOW.finditer(prompt) if m.group(2) or m.group(4)]
    windows = []
    for i, m in enumerate(marks):
        start, end = float(m.group(1)), float(m.group(3))
        if end <= start:
            continue
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(prompt)
        text = prompt[m.end():stop]
        brk = _SECTION_BREAK.search(text)
        if brk:
            text = text[:brk.start()]
        windows.append({"start": _num(start), "end": _num(end),
                        "seconds": _num(end - start),
                        "text": " ".join(text.split()).strip(" .;,-") })
    windows.sort(key=lambda w: w["start"])
    return windows[:MAX_PARTS] if len(windows) >= 2 else []


def _num(x: float):
    return int(x) if float(x).is_integer() else round(float(x), 2)


def source_hash(prompt: str, refs) -> str:
    """What a timeline was planned FROM. A change to either the prompt or
    the scene's refs makes it stale -- a part cannot name a reference the
    scene no longer carries."""
    blob = (prompt or "").strip() + "\n" + "\n".join(refs or [])
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def is_current(shot: dict) -> bool:
    tl = (shot or {}).get("timeline") or {}
    return bool(tl.get("parts")) and tl.get("source") == source_hash(
        shot.get("prompt") or "", shot.get("refs") or [])


def _default_brain():
    """The tier a re-plan runs on when nobody named one: the one the
    timeline was first planned with, else the night's (ZEROPAGE_BRAIN).
    Read here rather than imported from orchestrator, which imports this
    module's callers."""
    return (os.environ.get("ZEROPAGE_BRAIN") or "").strip().lower() or None


# --- planning ---------------------------------------------------------------

def build_prompt(scene: str, windows: list, refs: list, *, seconds) -> str:
    from . import shootgen
    listed = "\n".join(f"- {w['start']}-{w['end']}s: {w['text']}" for w in windows)
    numbered = "\n".join(f"[{i}] {shootgen.reference_label(url)}"
                         for i, url in enumerate(refs, start=1)) or "(none attached)"
    return (PROMPT_PATH.read_text()
            .replace("{seconds}", str(seconds))
            .replace("{scene}", (scene or "").strip())
            .replace("{windows}", listed)
            .replace("{references}", numbered))


def parse_response(text: str, windows: list, refs: list) -> Optional[dict]:
    """Model text -> {"continuity", "parts"} checked against reality, or None.

    The WINDOWS come from the scene, never from the answer: the model is
    told to keep them and the code keeps them either way (prompts request,
    code enforces). So the answer has to give one shot per window, in
    order; anything else is a different scene, and None sends the caller
    to the deterministic split rather than to a timeline that disagrees
    with the prompt it claims to be.

    Ref numbers outside the scene's set are dropped, duplicates collapse,
    and what is left is put back in the SCENE's order -- identity first,
    because the first ref of a part is what its still is drawn against."""
    from .gemini_utils import strip_fences
    try:
        data = json.loads(strip_fences(text or ""))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    shots = data.get("shots")
    if not isinstance(shots, list) or len(shots) != len(windows):
        return None
    parts = []
    for n, (window, item) in enumerate(zip(windows, shots), start=1):
        if not isinstance(item, dict):
            return None
        prompt = " ".join(str(item.get("prompt") or "").split())
        if not prompt:
            return None
        picked = set()
        for raw in item.get("refs") or []:
            try:
                i = int(raw)
            except (TypeError, ValueError):
                continue
            if 1 <= i <= len(refs):
                picked.add(i)
        parts.append(_part(n, window, prompt, [refs[i - 1] for i in sorted(picked)]))
    continuity = " ".join(str(data.get("continuity") or "").split())
    return {"continuity": continuity, "parts": parts}


def _part(n: int, window: dict, prompt: str, refs: list) -> dict:
    # `text` is the scene's OWN sentence for this window, kept so a re-plan
    # can tell which parts the edit actually touched (see ensure).
    return {"n": n, "start": window["start"], "end": window["end"],
            "seconds": window["seconds"], "text": window.get("text") or "",
            "prompt": prompt, "refs": list(refs),
            "reference_image": None, "media_url": None}


def fallback(scene: str, windows: list, refs: list) -> dict:
    """The split with no model in it: each window's own sentence is the
    shot, the scene with EVERY window's sentence cut out is the continuity
    (its look, sound and avoid-list without its action), and every shot
    gets all the scene's refs -- over-grounding a shot costs a little
    fidelity, under-grounding it costs the face."""
    context = scene or ""
    for w in windows:
        if w["text"]:
            context = context.replace(w["text"], "")
    context = _WINDOW.sub("", context)
    context = " ".join(context.split())
    return {"continuity": context,
            "parts": [_part(n, w, w["text"] or f"shot {n}", refs)
                      for n, w in enumerate(windows, start=1)]}


def _reference_contents(refs: list, resolve_photo=None) -> list:
    """Each ref as a numbered caption followed by its bytes, for a model
    that has to SEE what it is choosing between. A ref that does not
    resolve keeps its number (the text lists it) and simply has no
    picture -- renumbering would point every later number at the wrong
    photograph."""
    from google.genai import types

    from . import imagery, shootgen
    from .gemini_utils import sniff_mime
    out = []
    for i, url in enumerate(refs, start=1):
        data = imagery.image_bytes_for_gemini(url, resolve_photo=resolve_photo)
        if data:
            out.append(f"[{i}] {shootgen.reference_label(url)}")
            out.append(types.Part.from_bytes(data=data, mime_type=sniff_mime(data)))
    return out


def plan(scene: str, refs: list, *, brain=None, gemini_client=None,
         resolve_photo: Optional[Callable] = None,
         account_id: Optional[int] = None) -> Optional[dict]:
    """A scene prompt -> its timeline, or None when it has no timed windows.

    One call on `brain` (the tier the scene was written on -- "the create
    reasoning model"), shown every reference photograph under its number.
    Any failure -- no key, a refused tier, an answer that does not fit the
    windows -- falls back to the deterministic split, and says which it
    was in `planner` so a card can tell a planned timeline from a guessed
    one. Never raises."""
    refs = list(refs or [])
    windows = parse_windows(scene)
    if not windows:
        return None
    total = _num(sum(w["seconds"] for w in windows))
    result, planner, error = None, "split", None
    try:
        from . import shootgen
        from .gemini_utils import generate_with_retry
        client = gemini_client
        if client is None:
            key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if key:
                from google import genai
                client = genai.Client(api_key=key)
        if client is not None:
            text = build_prompt(scene, windows, refs, seconds=total)
            contents = [*_reference_contents(refs, resolve_photo), text] if refs else text
            model, config, fallbacks = shootgen.brain_call(shootgen.MODEL, brain)
            answer = generate_with_retry(client, model, contents, stage="timeline",
                                         config=config, fallbacks=fallbacks,
                                         account_id=account_id)
            result = parse_response(answer, windows, refs)
            if result is not None:
                planner = brain or "fast"
            else:
                error = "the planner's answer did not fit the scene's windows"
    except Exception as e:
        error = f"planner unavailable: {e}"
    if result is None:
        if error:
            print(f"note: shot timeline fell back to a plain split: {error}",
                  file=sys.stderr)
        result = fallback(scene, windows, refs)
    return {"seconds": total, "planner": planner,
            "source": source_hash(scene, refs),
            "continuity": result["continuity"], "parts": result["parts"],
            **({"error": error} if error else {})}


# --- the stored timeline ----------------------------------------------------

def _shot(concept: Optional[dict], shot_n=None) -> Optional[dict]:
    shots = (concept or {}).get("shots") or []
    if shot_n is None:
        return shots[0] if shots else None
    return next((s for s in shots if s.get("n") == shot_n), None)


def _save(concept_id: int, concept: dict, shots: list, *, db_path=None,
          account_id: Optional[int] = None) -> None:
    """update_concept_shots rewrites ai_json and warnings from what it is
    handed, so hand it back what the row already had."""
    preprod.update_concept_shots(
        concept_id, {"shots": shots, "duration": concept.get("duration"),
                     "ai": concept.get("ai")},
        warnings=concept.get("warnings") or [], dsn=db_path, account_id=account_id)


def ensure(concept_id: int, shot_n=None, *, brain=None, gemini_client=None,
           resolve_photo: Optional[Callable] = None, db_path=None,
           account_id: Optional[int] = None, force: bool = False) -> Optional[dict]:
    """The scene's current timeline, planned now if it is missing or stale.

    Returns None for a scene with no timed windows (it renders as one clip)
    and never raises -- a scene that could not be split is still a scene.
    Renders already attached to a part are CARRIED OVER when the re-plan
    keeps the same window with the same sentence in the scene, so an edit
    to shot 3 does not throw away the clip of shot 1 -- keyed on the
    scene's words and not the planner's, which a re-plan rewrites anyway.
    Carried only if the part's refs are unchanged too: a still drawn
    against a face the shot no longer shows is not that shot's still."""
    try:
        concept = preprod.get_concept(concept_id, dsn=db_path, account_id=account_id)
        shot = _shot(concept, shot_n)
        if not shot:
            return None
        if not force and is_current(shot):
            return shot["timeline"]
        old = shot.get("timeline") or {}
        new = plan(shot.get("prompt") or "", shot.get("refs") or [],
                   brain=brain or old.get("brain") or _default_brain(),
                   gemini_client=gemini_client, resolve_photo=resolve_photo,
                   account_id=account_id)
        if new is None:
            if old:
                shots = [dict(s) for s in concept["shots"]]
                target = _shot({"shots": shots}, shot.get("n"))
                target.pop("timeline", None)
                _save(concept_id, concept, shots, db_path=db_path, account_id=account_id)
            return None
        new["brain"] = brain or old.get("brain") or _default_brain()
        kept = {(p.get("start"), p.get("end"), p.get("text"), tuple(p.get("refs") or [])): p
                for p in old.get("parts") or []}
        for part in new["parts"]:
            prev = kept.get((part["start"], part["end"], part["text"], tuple(part["refs"])))
            if prev:
                part["reference_image"] = prev.get("reference_image")
                part["media_url"] = prev.get("media_url")
        # Re-read before writing: planning is a model call, and the row
        # may have gained a keyframe or a ref while it ran.
        concept = preprod.get_concept(concept_id, dsn=db_path, account_id=account_id)
        shots = [dict(s) for s in concept["shots"]]
        target = _shot({"shots": shots}, shot.get("n"))
        if target is None:
            return None
        if new["source"] != source_hash(target.get("prompt") or "", target.get("refs") or []):
            return new          # edited while we planned; the next read re-plans
        target["timeline"] = new
        target["seconds"] = new["seconds"]
        _save(concept_id, concept, shots, db_path=db_path, account_id=account_id)
        return new
    except Exception as e:
        print(f"note: shot timeline not planned: {e}", file=sys.stderr)
        return None


def render_prompt(part: dict, timeline: dict) -> str:
    """What a renderer is handed for one part: the scene's memory first,
    then this shot. Composed here, in code, rather than trusted to the
    planner's wording -- continuity that depends on a model remembering to
    repeat it is continuity that drifts on the fourth shot."""
    total = len((timeline or {}).get("parts") or []) or 1
    head = (timeline or {}).get("continuity") or ""
    shot = (f"SHOT {part.get('n')} OF {total} ({part.get('start')}-{part.get('end')}s, "
            f"{part.get('seconds')}s): {part.get('prompt') or ''}").strip()
    if head:
        return f"CONTINUITY -- the same scene as every other shot, keep it identical: {head}\n\n{shot}"
    return shot


def render_target(shot: dict, part: Optional[int] = None) -> Optional[dict]:
    """The prompt, anchor frame and refs one render reads.

    `part=None` is the whole scene -- the shot's own prompt and keyframe,
    exactly what every adapter read before timelines. A part number reads
    that part: its composed prompt, ITS still as the anchor, ITS refs. None
    when the part does not exist, so an adapter can refuse cleanly rather
    than render the wrong thing.

    Both prompts go out through `for_render`, which is what makes this the
    render boundary: everything downstream of here is a video model being
    handed a frame, and the motion directive belongs to all four adapters
    rather than to whichever one remembered to add it."""
    if not shot:
        return None
    if part is None:
        return {"prompt": for_render(shot.get("prompt")),
                "reference_image": shot.get("reference_image"),
                "refs": list(shot.get("refs") or []), "seconds": shot.get("seconds")}
    tl = shot.get("timeline") or {}
    entry = next((p for p in tl.get("parts") or [] if p.get("n") == part), None)
    if entry is None:
        return None
    return {"prompt": for_render(render_prompt(entry, tl)),
            "reference_image": entry.get("reference_image"),
            "refs": list(entry.get("refs") or []), "seconds": entry.get("seconds")}


def attach_part(concept_id: int, shot_n, part: int, field: str, url: str, *,
                db_path=None, account_id: Optional[int] = None) -> bool:
    """Write one part's `media_url` or `reference_image`.

    When the LAST part gets its clip, the scene's own `media_url` is set to
    shot 1's clip. That is what every existing reader means by "rendered"
    -- the Queue drops the card, the board counts it -- and it is shot 1
    ON PURPOSE rather than a stitched cut: the edit is Mike's, in Resolve
    (the L1 hold), and the parts are on the card in order for exactly that.
    A partly rendered scene stays in the Queue, so a render that stops at
    the daily cap is resumed by approving again rather than restarted."""
    if field not in ("media_url", "reference_image") or not (url or "").strip():
        raise ValueError("a part takes a media_url or a reference_image")
    concept = preprod.get_concept(concept_id, dsn=db_path, account_id=account_id)
    if concept is None:
        raise ValueError(f"no concept {concept_id}")
    shots = [dict(s) for s in concept["shots"]]
    shot = _shot({"shots": shots}, shot_n)
    if shot is None:
        raise ValueError(f"concept {concept_id} has no shot {shot_n}")
    tl = dict(shot.get("timeline") or {})
    parts = [dict(p) for p in tl.get("parts") or []]
    entry = next((p for p in parts if p.get("n") == part), None)
    if entry is None:
        raise ValueError(f"shot {shot_n} has no part {part}")
    entry[field] = url.strip()
    tl["parts"] = parts
    shot["timeline"] = tl
    if field == "media_url" and all(p.get("media_url") for p in parts):
        shot["media_url"] = parts[0]["media_url"]
    _save(concept_id, concept, shots, db_path=db_path, account_id=account_id)
    return True


def pending_parts(shot: dict) -> list:
    """The parts still without a clip, in order -- what an approve renders."""
    return [p for p in ((shot or {}).get("timeline") or {}).get("parts") or []
            if not p.get("media_url")]


def fit_seconds(axis: dict, seconds) -> int:
    """A part's window -> the length a model can actually render.

    A window is the length the SHOT is on screen; a render is what the
    model will make. Runway makes 5s or 10s and nothing between, so a 3s
    window renders at 5s and is trimmed in the edit -- rounding UP, never
    down, because a render shorter than its window is a hole in the cut
    and a longer one is a handle. The three kinds are the catalogue's
    (providers._choices / _span / _fixed), and this is the one place that
    turns a window into a legal length for each."""
    want = max(1, math.ceil(float(seconds or 0) or 1))
    kind = (axis or {}).get("kind")
    if kind == "range":
        return int(min(max(want, axis["min"]), axis["max"]))
    values = sorted(int(v) for v in (axis or {}).get("values") or [])
    if not values:
        return want
    if kind == "fixed":
        return values[0]
    return next((v for v in values if v >= want), values[-1])

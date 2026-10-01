"""
src/cut/agent_tools.py -- the editing agent's brain (docs/CUT_EDITOR.md 5.2
and 5.6, phase E, 2026-09-28).

One turn: a person on /studio/cut types "tighten the gap after the first
line"; the model reads the head version as text, may search the footage,
and either answers or PROPOSES a list of ops. It never edits. A proposal
is a card the person Keeps or Undoes -- the click is the approval, the
same rule as spend -- and Keep is a separate route that re-applies the
ops against the head (projects.keep). Undo is the client dropping the
card: nothing was saved, so there is nothing to discard.

Mike's D4, which is the whole shape of this module:

- The agent may ONLY emit the ops already in ops.OPS and call
  `search_footage`. The catalogue it is shown is DERIVED from ops.OPS
  (each op's signature plus one line), so a new op reaches the agent by
  landing in ops.py with a line in OP_NOTES, and an op that is not there
  cannot be asked for -- apply refuses an unknown name.
- A proposal is validated with ops.apply, against the head and the
  measured media, BEFORE it is shown. A refused one goes back to the
  model with the validator's own reasons ONCE (section 5.2); a second
  refusal ends the turn with no proposal and the reasons in `notes`.
- Nothing here raises into the job. No key, a dead model, a malformed
  answer: the turn still finishes, with a reply that says so.

The model call is ONE seam, `call_model(system, turns, tools, *,
account_id)`, which a test replaces -- the loop, the tools and the
validation all run for real around a fake. The turns it is handed are
plain dicts; the Gemini-shaped history is built inside the seam, which
keeps each model turn's own Content (a Gemini 3 function call carries a
thought signature that must be sent back byte for byte).

The Proposal shape (the React panel reads it; do not change it without
changing web/src/lib/cut):

    {"summary": str, "ops": [{"op", "args"}], "base_id": int,
     "region": {"from", "to"} | None, "duration_delta": int,
     "doc": <the doc after every op>, "kind": "agent"|"cleanup"|"captions"}
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from . import doc as d
from . import ops, projects, store

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "cut" / "agent.txt"

# model steps per turn (tool calls included); a turn is an answer, not a crawl
MAX_STEPS = 6
# the fast tier: an edit turn is short, and the validator -- not a bigger
# model -- is what makes a proposal trustworthy
BRAIN = "fast"
SUMMARY_MAX = 200
KINDS = ("agent", "cleanup", "captions")

# One line per op, in the words the model reads. Written here rather than
# lifted from every docstring because several ops have none and the rest
# explain themselves to a programmer, not to a model choosing between them.
OP_NOTES = {
    "insert": "put a clip of media on a track at a cut point (default: the end); "
              "clip = {media, src_in, src_out}; sound_track also lays its own sound there",
    "ripple_delete": "remove a clip (and its linked sound) and close the gap",
    "lift": "remove a clip (and its linked sound) and LEAVE the gap",
    "trim": "shorten (+) or extend (-) a clip's head/tail by frames; ripple=true closes the gap",
    "split": "cut a clip in two at a timeline frame strictly inside it (the second half gets a new id)",
    "move": "slide a clip (and its sound) to a new start frame, optionally onto another track",
    "set_gain": "set an AUDIO clip's gain in dB (-60 to +12)",
    "duck": "make an audio track dip under a role (voice|music|sfx), or under=null to stop",
    "add_caption_track": "a new caption track from cues [{start, end, text}] in frames",
    "set_cue": "add a cue to a caption track, or with cue_id change that cue",
    "delete_cue": "remove one cue from a caption track",
    "set_caption_style": "caption look: preset:bold_center | preset:lower_third | preset:minimal_top",
    "add_marker": "a labelled marker at a frame",
    "add_transition": "turn the hard cut INTO a clip into a crossfade of N frames",
    "set_canvas": "change the frame size (even numbers), e.g. 720x1280 for 9:16",
    "overwrite": "lay a clip {media, src_in, src_out} on a track at a frame OVER what is there "
                 "(nothing after it moves); sound_track also lays its own sound",
    "set_key": "animate a PICTURE clip: a key on path zoom (0.1-4) | x | y (-1..1, fraction of the "
               "frame) | rotation (degrees) at a clip-relative frame; ease linear|ease|hold. One key = a "
               "constant",
    "delete_key": "remove one key from a picture clip's lane",
    "clear_lane": "reset a picture clip's zoom | x | y | rotation to its default",
    "set_crop": "crop a picture clip's edges: left/right/top/bottom as fractions (0-0.45)",
    "set_opacity": "a picture clip's opacity, 0-1",
    "add_track": "an empty track: kind video|audio|caption; an audio track needs role voice|music|sfx",
}


class AgentUnavailable(RuntimeError):
    """No model to ask (no key on this server). The reply says so."""


# --------------------------------------------------------------------------
# what the model is shown
# --------------------------------------------------------------------------

def _secs(frames: int, fps: int) -> str:
    return f"{frames / fps:.1f}s"


def op_catalogue() -> str:
    """Every op in ops.OPS as `name(arg: type = default, ...) -- what it
    does`, derived from the functions themselves so it cannot drift from
    what apply will actually accept."""
    lines = []
    for name, fn in ops.OPS.items():
        params = list(inspect.signature(fn).parameters.values())[1:]      # not `doc`
        args = []
        for p in params:
            ann = str(p.annotation) if p.annotation is not inspect.Parameter.empty else ""
            if ann.startswith("Optional[") and ann.endswith("]"):
                ann = ann[len("Optional["):-1]
            text = f"{p.name}: {ann}" if ann else p.name
            if p.default is not inspect.Parameter.empty:
                text += f" = {json.dumps(p.default)}"
            args.append(text)
        note = OP_NOTES.get(name) or (inspect.getdoc(fn) or "").split(".")[0]
        lines.append(f"- {name}({', '.join(args)}) -- {note}")
    return "\n".join(lines)


def read_timeline(doc: dict, names: Optional[dict] = None) -> str:
    """The head doc as compact text: the header, every track with its
    clips (id, media and what it is, where, how long, what part of the
    file, what it is linked to), cues and markers. Frames first -- the ops
    take frames -- with seconds beside them for the model's own sense of
    time."""
    names = names or {}
    fps = int(doc.get("fps") or d.DEFAULT_FPS)
    size = doc.get("size") or list(d.DEFAULT_SIZE)
    dur = int(doc.get("duration") or 0)
    lines = [f"fps {fps} · {size[0]}x{size[1]} ({d.aspect_of(size)}) · "
             f"duration {dur}f ({_secs(dur, fps)})"]
    for t in doc.get("tracks", []):
        kind = t.get("kind")
        head = f"{t.get('id')} ({kind}"
        if kind == "audio":
            head += f", {t.get('role')}" + (f", ducks under {t['duck_under']}"
                                            if t.get("duck_under") else "")
        if kind == "caption":
            head += f", {t.get('style')}"
        lines.append(head + "):")
        if kind == "caption":
            for q in t.get("cues") or []:
                lines.append(f"  {q.get('id')} {q.get('start')}-{q.get('end')}f "
                             f"({_secs(int(q.get('start') or 0), fps)}-"
                             f"{_secs(int(q.get('end') or 0), fps)}) \"{q.get('text')}\"")
            if not t.get("cues"):
                lines.append("  (no cues)")
            continue
        for c in t.get("clips") or []:
            n = names.get(c.get("media")) or {}
            what = f" \"{n['name']}\"" if n.get("name") else ""
            if n.get("about"):
                what += f" ({n['about'][:70]})"
            length = d.clip_length(c)
            line = (f"  {c['id']} {c.get('media')}{what} at {c['at']}f-{d.clip_end(c)}f "
                    f"({_secs(c['at'], fps)}-{_secs(d.clip_end(c), fps)}, {_secs(length, fps)}) "
                    f"src {c['src_in']}-{c['src_out']}f")
            if c.get("link"):
                line += f" · linked to {c['link']}"
            if c.get("transition_in"):
                line += f" · crossfades in over {c['transition_in'].get('frames')}f"
            if kind == "audio" and c.get("gain_db"):
                line += f" · gain {c['gain_db']:+g} dB"
            lines.append(line)
        if not t.get("clips"):
            lines.append("  (empty)")
    marks = doc.get("markers") or []
    if marks:
        lines.append("markers: " + "; ".join(
            f"{m.get('frame')}f ({_secs(int(m.get('frame') or 0), fps)}) \"{m.get('label')}\""
            for m in marks))
    return "\n".join(lines)


def context_text(doc: dict, head: dict, *, names: dict, message: str,
                 playhead: Optional[int] = None, selection: Optional[list] = None) -> str:
    fps = int(doc.get("fps") or d.DEFAULT_FPS)
    parts = [f"THE TIMELINE (version {head.get('version')}):\n{read_timeline(doc, names)}"]
    if playhead is not None:
        parts.append(f"PLAYHEAD: frame {playhead} ({_secs(playhead, fps)})")
    if selection:
        parts.append("SELECTED: " + ", ".join(selection))
    parts.append("THE OPS YOU MAY PROPOSE (args by name; every frame a whole number):\n"
                 + op_catalogue())
    parts.append("THE PERSON SAYS:\n" + message)
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# the tools the model may call
# --------------------------------------------------------------------------

READ_SPEC = {
    "name": "read_timeline",
    "description": "The current timeline as text: tracks, clips with ids, media, where they "
                   "sit and how long, cues, markers, fps and duration. Costs nothing.",
    "input_schema": {"type": "object", "properties": {}},
}

PROPOSE_SPEC = {
    "name": "propose_ops",
    "description": (
        "Propose ONE edit: ops applied in order, and a one-line summary for the card the "
        "person Keeps or Undoes. It is checked against the timeline first; a refused "
        "proposal comes back with the reasons and you may fix it once."),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string",
                        "description": "One line a person reads, e.g. 'Removed 3 silences, -0:04'."},
            "ops": {"type": "array", "items": {
                "type": "object",
                "properties": {"op": {"type": "string", "enum": sorted(ops.OPS)},
                               "args": {"type": "object"}},
                "required": ["op", "args"]}},
        },
        "required": ["summary", "ops"],
    },
}


def tool_specs() -> list[dict]:
    from .. import assistant_brain
    return [READ_SPEC, dict(assistant_brain.SEARCH_SPEC), PROPOSE_SPEC]


def search_footage(args: dict, *, account_id: Optional[int], dsn: Optional[str] = None) -> str:
    """The pill's own tool, through its own checks: index.find, read back
    as handles and times -- never URLs."""
    from .. import assistant_brain, guide_tools
    args = guide_tools.check_args("search_footage", dict(args or {}))
    return assistant_brain.footage_for_model(assistant_brain.search_footage(
        args["query"], k=args["k"], account_id=account_id, dsn=dsn))


# --------------------------------------------------------------------------
# proposals
# --------------------------------------------------------------------------

def _changed(a: dict, b: dict, keys) -> bool:
    return any(a.get(k) != b.get(k) for k in keys)


def region(before: dict, after: dict) -> Optional[dict]:
    """The span of the BASE timeline an edit touches, in frames, or None
    when it touches no place in particular (a canvas change, a duck).

    Read off a diff of the two docs, so it works for any op list: a clip
    removed or re-cut (media / src / transition), a cue or marker added,
    changed or removed. A clip that only SLID counts only when nothing
    was re-cut -- a ripple slides everything after the cut, and the
    card should point at the cut, not at the rest of the timeline; a
    plain move is nothing but a slide, so there it is the change."""
    spans: list[tuple[int, int]] = []
    slides: list[tuple[int, int]] = []
    old = {c["id"]: c for _, c in d.all_clips(before)}
    new = {c["id"]: c for _, c in d.all_clips(after)}
    for cid, c in old.items():
        n = new.get(cid)
        if n is None or _changed(c, n, ("media", "src_in", "src_out", "transition_in")):
            spans.append((c["at"], d.clip_end(c)))
        elif n["at"] != c["at"]:
            slides += [(c["at"], d.clip_end(c)), (n["at"], d.clip_end(n))]
    for cid, n in new.items():
        if cid not in old:
            spans.append((n["at"], d.clip_end(n)))
    old_q = {(t["id"], q.get("id")): q for t in before.get("tracks", []) for q in t.get("cues") or []}
    new_q = {(t["id"], q.get("id")): q for t in after.get("tracks", []) for q in t.get("cues") or []}
    for k in set(old_q) | set(new_q):
        a, b = old_q.get(k), new_q.get(k)
        if a != b:
            for q in (a, b):
                if q:
                    spans.append((int(q["start"]), int(q["end"])))
    old_m = {(m.get("frame"), m.get("label")) for m in before.get("markers") or []}
    for m in after.get("markers") or []:
        if (m.get("frame"), m.get("label")) not in old_m:
            spans.append((int(m["frame"]), int(m["frame"])))
    spans = spans or slides
    if not spans:
        return None
    return {"from": max(0, min(a for a, _ in spans)), "to": max(b for _, b in spans)}


def delta_label(frames: int, fps: int) -> str:
    """-0:04 / +1:02 / -0.4s: what a card says the edit did to the length."""
    sign = "−" if frames < 0 else "+"
    secs = abs(frames) / fps
    if secs < 1:
        return f"{sign}{secs:.1f}s"
    total = int(round(secs))
    return f"{sign}{total // 60}:{total % 60:02d}"


def proposal(base: dict, op_list: list, after: dict, *, summary: str,
             kind: str = "agent") -> dict[str, Any]:
    """A validated edit as the card reads it. `base` is the head version
    row it was computed against (its id is the Keep route's base_id)."""
    before = base["doc"]
    delta = int(after.get("duration") or 0) - int(before.get("duration") or 0)
    summary = " ".join(str(summary or "").split())[:SUMMARY_MAX]
    if not summary:
        fps = int(before.get("fps") or d.DEFAULT_FPS)
        said = "; ".join(ops.describe(o["op"], o.get("args"), fps) for o in op_list[:3])
        summary = (said + (f" (+{len(op_list) - 3} more)" if len(op_list) > 3 else ""))[:SUMMARY_MAX]
    return {"summary": summary, "ops": op_list, "base_id": base["id"],
            "region": region(before, after), "duration_delta": delta, "doc": after,
            "kind": kind if kind in KINDS else "agent"}


def _ints(value):
    """Model JSON -> op args: an integral float is a frame number that went
    through a JSON number (Gemini's function-call args arrive as doubles),
    so 150.0 becomes 150. A real fraction stays a fraction, and the op
    refuses it with its own reason."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _ints(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ints(v) for v in value]
    return value


def _normalise_ops(raw) -> list:
    if not isinstance(raw, list):
        return raw
    out = []
    for item in raw:
        if isinstance(item, dict):
            out.append({"op": item.get("op"), "args": _ints(item.get("args") or {})})
        else:
            out.append(item)
    return out


# --------------------------------------------------------------------------
# the model seam
# --------------------------------------------------------------------------

def _plain(value):
    return json.loads(json.dumps(value, default=str))


def call_model(system: str, turns: list[dict], tools: list[dict], *,
               account_id: Optional[int] = None) -> dict[str, Any]:
    """ONE model step -> {"text": str, "calls": [{"name", "args"}],
    "content": <the model turn, to send back>}. THE seam a test replaces.

    `turns` are plain dicts: {"role": "user", "text"}, {"role": "model",
    "calls", "text", "content"}, {"role": "tool", "results": [{"name",
    "result"}]}. Metered through generate_with_retry, stage `cut_agent`.
    Raises AgentUnavailable with no key; any other failure is the
    caller's to turn into a reply."""
    from google.genai import types

    from .. import gemini_utils
    if not gemini_utils.api_key_for(account_id):
        raise AgentUnavailable("this server has no Gemini key")
    client = gemini_utils.client_for(account_id)
    brain = gemini_utils.resolve_brain(BRAIN)
    config = brain["config"] or types.GenerateContentConfig()
    config.system_instruction = system
    config.tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=t["name"], description=t["description"],
                                  parameters_json_schema=t["input_schema"]) for t in tools])]
    contents = []
    for t in turns:
        if t["role"] == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=t["text"])]))
        elif t["role"] == "model":
            contents.append(t.get("content") or types.Content(role="model", parts=(
                [types.Part.from_text(text=t["text"])] if t.get("text") else []) + [
                types.Part.from_function_call(name=c["name"], args=c["args"])
                for c in t.get("calls") or []]))
        else:
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=r["name"], response={"result": r["result"]})
                for r in t["results"]]))
    response = gemini_utils.generate_with_retry(
        client, brain["model"], contents, config=config, fallbacks=brain["fallbacks"],
        stage="cut_agent", account_id=account_id, raw=True)
    calls = [{"name": fc.name, "args": _plain(dict(fc.args or {}))}
             for fc in (response.function_calls or [])]
    content = response.candidates[0].content if response.candidates else None
    text = "".join(p.text for p in (getattr(content, "parts", None) or [])
                   if getattr(p, "text", None) and not getattr(p, "thought", False))
    return {"text": text.strip(), "calls": calls, "content": content}


def system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text().strip()
    except OSError:
        return "You are the editing agent inside a video editor. Propose edits as ops."


# --------------------------------------------------------------------------
# one turn
# --------------------------------------------------------------------------

def _clean_reply(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:1500]


def run_turn(project: dict, head: dict, message: str, *, account_id: Optional[int],
             playhead: Optional[int] = None, selection: Optional[list] = None,
             dsn: Optional[str] = None,
             model: Optional[Callable[..., dict]] = None) -> dict[str, Any]:
    """One agent turn against `head` (the version row the person is
    looking at). Returns {"reply", "proposal", "tool_runs", "notes",
    "ref_id"}. Never raises."""
    ask = model or call_model
    doc = head["doc"]
    tool_runs: list[dict] = []
    notes: list[str] = []
    out = {"reply": "", "proposal": None, "tool_runs": tool_runs, "notes": notes, "ref_id": None}
    try:
        names = store.handle_names(d.handles(doc), account_id=account_id, dsn=dsn)
    except Exception:                                   # noqa: BLE001 -- names are a nicety
        names = {}
    turns: list[dict] = [{"role": "user", "text": context_text(
        doc, head, names=names, message=message, playhead=playhead, selection=selection)}]
    system, tools = system_prompt(), tool_specs()
    refusals = 0
    try:
        for _ in range(MAX_STEPS):
            said = ask(system, turns, tools, account_id=account_id)
            calls = said.get("calls") or []
            if not calls:
                out["reply"] = _clean_reply(said.get("text")) or "Done -- nothing to change."
                return out
            turns.append({"role": "model", "calls": calls, "text": said.get("text") or "",
                          "content": said.get("content")})
            results = []
            for call in calls:
                name, args = call.get("name"), dict(call.get("args") or {})
                if name == "propose_ops":
                    op_list = _normalise_ops(args.get("ops"))
                    try:
                        after = projects.check_ops(doc, op_list, account_id=account_id, dsn=dsn)
                    except ops.OpError as e:
                        refusals += 1
                        tool_runs.append({"tool": name, "args": args, "ok": False})
                        if refusals > 1:
                            notes.extend(e.problems)
                            out["reply"] = ("I couldn't make a valid edit for that: "
                                            + "; ".join(e.problems[:3]))[:1500]
                            return out
                        results.append({"name": name, "result": (
                            "REFUSED -- nothing was shown to the person. The validator said:\n"
                            + "\n".join(f"- {p}" for p in e.problems)
                            + "\nFix exactly these and call propose_ops again (this is your "
                              "one retry).")[:8000]})
                        continue
                    tool_runs.append({"tool": name, "args": args, "ok": True})
                    out["proposal"] = proposal(head, op_list, after,
                                               summary=args.get("summary") or "", kind="agent")
                    out["reply"] = (_clean_reply(said.get("text"))
                                    or out["proposal"]["summary"])
                    return out
                ok = True
                try:
                    if name == "read_timeline":
                        result = read_timeline(doc, names)
                    elif name == "search_footage":
                        result = search_footage(args, account_id=account_id, dsn=dsn)
                    else:
                        result, ok = (f"error: there is no tool {name!r}; the tools are "
                                      "read_timeline, search_footage, propose_ops"), False
                except Exception as e:                  # a tool error IS the result
                    result, ok = f"error: {e}", False
                tool_runs.append({"tool": name, "args": args, "ok": ok})
                results.append({"name": name, "result": str(result)[:12000]})
            turns.append({"role": "tool", "results": results})
        out["reply"] = "I ran out of steps before settling on an edit -- try asking more narrowly."
        return out
    except AgentUnavailable as e:
        out["reply"] = f"The editing agent is unavailable: {e}."
        notes.append(str(e))
        return out
    except Exception as e:                              # noqa: BLE001 -- degrade, never 500
        out["reply"] = "The editing agent is unavailable right now -- try again in a moment."
        notes.append(f"{type(e).__name__}: {e}"[:300])
        return out

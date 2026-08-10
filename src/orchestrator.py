"""
src/orchestrator.py — the autonomous content graph over pre-production:

    planner -> ensure_locations -> ground_entities -> ground_rag
        -> gen_concept -> evaluate -> structure_prompt -> generate_render
                ^_____________|            -> qc_clip -> caption -> publish
                (corrective re-run)                 \\-> hold  (park, don't post)

The left third (ensure_locations -> gen_concept -> evaluate and its
retry edge) is the original evaluate-and-retry loop, unchanged in
behavior. The right two-thirds is the posting line, gated hard:

- generate_render and the posting APIs are DELIBERATE STUBS. The credit
  gate: real generation stays off until first-try prompt acceptance
  clears the bar, and publish never uploads anywhere yet. Until then a
  run that reaches the end of the line PARKS in autonomy.hold_queue
  with its reason -- the dead-man log every run writes.
- Autonomy is per-channel (autonomy.channels), never a global flag, and
  both channels seed as "shadow": everything holds, and each morning's
  approve/reject on the queue grades the evaluator. ~0.9 agreement
  (autonomy.evaluator_agreement) is the bar for promoting a channel.
- The kill switch (autonomy.killed(): settings row or ZEROPAGE_KILL=1)
  forces every run on every channel to hold. _post_gate is the last
  code-enforced check -- clips QC'd, caption non-empty, no warnings,
  under the channel's rate cap. Code, not a prompt.

The evaluator combines the code-enforced `warnings` (prompts request,
code enforces) with an optional LLM-judge (JUDGE=1) scoring solo-shoot
feasibility.

Deps:   pip install langgraph langsmith
Env:    GEMINI_API_KEY            (required, already used by your stages)
        JUDGE=1                   (optional) turn the LLM-judge on
        GEMINI_MODEL=...          (optional) judge model; match your other stages
        ZEROPAGE_KILL=1           (optional) kill switch without a DB write
        LANGSMITH_TRACING=true    (optional) auto-trace the graph to LangSmith
        LANGSMITH_API_KEY=...     (optional) with the line above
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional, TypedDict

from google import genai
from langgraph.graph import END, START, StateGraph

from . import autonomy, crag, db, entities, preprod, rag, scheduling, shootgen
from .gemini_utils import generate_with_retry

MAX_ATTEMPTS = 3
JUDGE_MIN = 0.6
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", shootgen.MODEL)  # match the other stages
PROMPT_GATE_MIN = int(os.environ.get("PROMPT_GATE_MIN", "7"))  # of 10; raise as you learn


class GenState(TypedDict, total=False):
    # inputs
    goal: str
    brand: str
    client: Optional[str]
    spark: Optional[str]
    use_pov: bool
    channel: str
    picked_locations: list          # ids; empty/absent = all on file
    picked_characters: list
    picked_props: list
    # grounding
    cast: str                       # formatted characters/props block
    references: str                 # CRAG-graded library block
    # the loop
    concept: dict
    concept_id: int
    critique: dict                  # {"ok": bool, "issues": [...], "score": float}
    attempts: int
    # the posting line
    run_id: str
    prompts: list                   # [{"tool", "prompt"}] for the AI shots
    prompt_scores: list             # [{prompt, score, pass, reason, dims}]
    clips: list                     # [{"tool", "prompt", "url", "ok"}]
    caption: str
    posted: list                    # [{"platform", "id", "url"}] once real posting exists
    autonomy: str                   # the channel's setting at run time
    hold_id: int
    held_reason: str
    error: Optional[str]


def _client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return genai.Client(api_key=key)


def _judge(concept: dict) -> tuple[float, list[str]]:
    """Optional LLM-judge. Never blocks: any failure returns a passing score."""
    try:
        payload = {
            "title": concept.get("title"),
            "logline": concept.get("logline"),
            "shots": [
                {"type": s.get("type"), "desc": s.get("desc"), "location": s.get("location")}
                for s in concept.get("shots", [])
            ],
        }
        prompt = (
            "You are a tough solo-filmmaker producer. Score this shoot concept for a "
            "ONE-operator, two-camera house shoot of at most 6 shots. Lower the score for "
            "shots needing a crew, impossible coverage, or vague direction. "
            'Return ONLY JSON: {"score": <0..1>, "issues": ["short issue", ...]}.\n\n'
            + json.dumps(payload)
        )
        resp = _client().models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = (resp.text or "").strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
        data = json.loads(text)
        return float(data.get("score", 1.0)), list(data.get("issues", []))
    except Exception:
        return 1.0, []


# --- nodes: the left third (the original loop) ----------------------------

def planner(state: GenState) -> GenState:
    """BUILD stub -- for now: straight to a full plan, autonomy read from
    the channel row (defaulting to shadow if the table isn't seeded).
    Also mints the run_id everything downstream logs against."""
    channel = state.get("channel") or "zeropage"
    row = autonomy.get_channel(channel, path=db.DB_PATH)
    return {
        "channel": channel,
        "autonomy": (row or {}).get("autonomy", "shadow"),
        "run_id": state.get("run_id") or uuid.uuid4().hex,
    }


def ensure_locations(state: GenState) -> GenState:
    if not preprod.list_locations(path=db.DB_PATH):
        return {"error": "No described locations — photograph a space first."}
    return {}


def ground_entities(state: GenState) -> GenState:
    """The chosen characters/props (or everything on file when nothing
    was picked), formatted the way the concept prompt's {cast} section
    expects. Data layer was already live; this is the socket."""
    picked_chars = state.get("picked_characters") or []
    picked_props = state.get("picked_props") or []
    if picked_chars:
        characters = [c for c in (entities.get_character(i, path=db.DB_PATH)
                                  for i in picked_chars) if c]
    else:
        characters = entities.list_characters(path=db.DB_PATH)
    if picked_props:
        props = [p for p in (entities.get_prop(i, path=db.DB_PATH)
                             for i in picked_props) if p]
    else:
        props = entities.list_props(path=db.DB_PATH)
    return {"cast": shootgen.format_cast(characters, props)}


def ground_rag(state: GenState) -> GenState:
    """The library block, CRAG-graded: weak retrieval gets one query
    rewrite before it's allowed to ground a run. Never raises -- an
    unreachable store degrades to an ungrounded run with a note, the
    same contract reference_block keeps."""
    locations = preprod.list_locations(path=db.DB_PATH)
    query = shootgen.build_reference_query(
        locations, spark=state.get("spark"), client=state.get("client"))
    if not query.strip():
        return {"references": ""}

    result = crag.retrieve_with_crag(
        query, _client(), GEMINI_MODEL, domain=shootgen.IDEATION_DOMAINS)
    if result["ok"] and result["references"]:
        note = f"Grounding in {len(result['references'])} retrieved reference(s)"
        if result.get("rewritten_query"):
            note += " (query rewritten after a weak first pass)"
        print(note, file=sys.stderr)
        return {"references": rag.format_references(result["references"])}

    reason = result.get("error", "reference library is empty")
    print(f"note: generating without references: {reason}", file=sys.stderr)
    return {"references": ""}


def gen_concept(state: GenState) -> GenState:
    # On a retry, fold the evaluator's feedback into the spark so the re-run improves.
    spark = state.get("spark")
    crit = state.get("critique")
    if crit and not crit.get("ok"):
        spark = f"{spark or ''}\nFix these issues: {'; '.join(crit.get('issues', []))}".strip()

    # human_note: standing corrections (dropped on /holds or via
    # autonomy.add_correction) fold into the spark the same way the
    # evaluator's do, and are consumed so each note steers once.
    notes = autonomy.pending_corrections(path=db.DB_PATH)
    if notes:
        spark = (f"{spark or ''}\nNotes from the filmmaker: "
                 + "; ".join(n["note"] for n in notes)).strip()
        for n in notes:
            autonomy.consume_correction(n["id"], path=db.DB_PATH)

    result = shootgen.generate_concept(
        brand=state.get("brand", "antihero"),
        client=state.get("client"),
        spark=spark,
        gemini_client=_client(),
        use_pov=state.get("use_pov", True),
        db_path=db.DB_PATH,
        references=state.get("references", ""),
        cast=state.get("cast"),
    )
    # generate_concept returns warnings BESIDE the concept, not inside it;
    # fold them in so evaluate's code-enforced check actually sees them.
    concept = {**result["concept"], "warnings": result["warnings"]}
    return {"concept": concept, "concept_id": result["concept_id"],
            "attempts": state.get("attempts", 0) + 1}


def evaluate(state: GenState) -> GenState:
    concept = state.get("concept", {}) or {}
    issues = list(concept.get("warnings", []) or [])   # code-enforced
    score = 1.0
    if os.environ.get("JUDGE") == "1":
        score, judge_issues = _judge(concept)
        issues += judge_issues
    ok = (not concept.get("warnings")) and (score >= JUDGE_MIN)
    return {"critique": {"ok": ok, "issues": issues, "score": score}}


def route_after_eval(state: GenState) -> str:
    if state.get("critique", {}).get("ok"):
        return "pass"
    if state.get("attempts", 0) < MAX_ATTEMPTS:
        return "retry"
    return "hold"                   # out of retries -> park it, don't post it


# --- nodes: the posting line ----------------------------------------------

def structure_prompt(state: GenState) -> GenState:
    """The AI shots' paste-ready prompts. shootgen already writes these
    into the concept (validate_concept flags an AI shot without one), so
    this extracts rather than re-billing promptgen per shot -- the
    structured prompt already exists."""
    shots = [s for s in (state.get("concept", {}) or {}).get("shots", [])
             if s.get("source") == "AI" and s.get("prompt")]
    return {"prompts": [{"tool": s.get("tool"), "prompt": s["prompt"]} for s in shots]}


# --- the prompt gate: nothing spends a credit until its prompt clears ------

def _structural_check(text: str) -> tuple[bool, str]:
    """Layer 1, deterministic, zero model calls -- the cheap failures:
    empty, too thin, over-stuffed, leftover template tokens."""
    t = (text or "").strip()
    n = len(t.split())
    if n < 15:
        return False, "too thin — under 15 words"
    if n > 130:
        return False, "over-stuffed — 130+ words, the model will drop detail"
    if re.search(r"\{.*?\}|\[.*?\]|TODO|TBD", t):
        return False, "leftover placeholder / template token"
    return True, ""


_PROMPT_RUBRIC = """You grade AI VIDEO prompts (Veo/Runway/Kling). Score how likely THIS prompt
yields a usable clip on the FIRST render. Be harsh — a paid credit is spent on your say-so.

Rate each 0-2:
- subject: main subject concrete and unambiguous?
- camera: framing/lens/angle specified (close-up, 35mm, low angle)?
- motion: ONE clear action, not several competing ones?
- lighting: light / mood / time of day specified?
- coherence: free of contradictions the model can't resolve?

Return ONLY JSON:
{"subject":0,"camera":0,"motion":0,"lighting":0,"coherence":0,"reason":"one clause naming the weakest part"}"""

_PROMPT_DIMS = ("subject", "camera", "motion", "lighting", "coherence")


def _extract_json(raw: str) -> str:
    match = re.search(r"\{.*\}", raw, re.S)
    return match.group(0) if match else raw


def _judge_prompt(prompt: str) -> dict:
    """Layer 2, the strict judge -- FAIL-CLOSED: a verdict that can't be
    read scores 0, because a credit must never be spent on an unreadable
    judgment. The model can only ever be stricter than the floor."""
    try:
        raw = generate_with_retry(_client(), GEMINI_MODEL,
                                  _PROMPT_RUBRIC + "\n\nPROMPT:\n" + prompt)
        data = json.loads(_extract_json(raw))
        vals = {k: max(0, min(2, int(data.get(k, 0)))) for k in _PROMPT_DIMS}
        return {"score": sum(vals.values()), "dims": vals,
                "reason": str(data.get("reason", ""))[:200]}
    except Exception as e:
        return {"score": 0, "dims": {},
                "reason": f"judge unreadable ({e}) — failed closed"}


def score_prompts(state: GenState) -> GenState:
    """The credit gate. Every extracted prompt gets the deterministic
    floor, then the judge; every score is logged before any credit could
    be spent, so the gate-vs-you agreement number accumulates from run
    one -- long before rendering is even on."""
    scored = []
    for p in state.get("prompts", []):
        text = p.get("prompt", "")
        ok, why = _structural_check(text)
        if not ok:
            scored.append({"prompt": text, "tool": p.get("tool"), "score": 0,
                           "pass": False, "reason": why, "dims": {}})
            continue
        verdict = _judge_prompt(text)
        scored.append({"prompt": text, "tool": p.get("tool"),
                       "score": verdict["score"],
                       "pass": verdict["score"] >= PROMPT_GATE_MIN,
                       "reason": verdict["reason"], "dims": verdict["dims"]})
    autonomy.log_prompt_scores(state.get("run_id"), scored, path=db.DB_PATH)
    return {"prompt_scores": scored}


def route_after_score(state: GenState) -> str:
    """Every AI shot must clear the bar or the whole run holds -- no
    half-rendered credit burn. (Camera-only concepts have no scores and
    hold too; render has nothing for them either.)"""
    scores = state.get("prompt_scores", [])
    if scores and all(x["pass"] for x in scores):
        return "generate_render"
    return "hold"


def generate_render(state: GenState) -> GenState:
    """The credit gate, now explicit: ZEROPAGE_RENDER=1 turns on real
    Veo generation (one candidate per AI shot, through veo.py's daily
    cap and genlog logging). Anything else -- the default -- is the
    dry-run stub: every clip comes back url=None, ok=False, and the run
    parks downstream. Tools without an adapter (KLING/RUNWAY/...) stay
    dry even when rendering is on, honestly marked."""
    prompts = state.get("prompts", [])
    if os.environ.get("ZEROPAGE_RENDER") != "1":
        return {"clips": [{**p, "url": None, "ok": False} for p in prompts]}

    from . import veo
    out_root = (Path(db.DB_PATH).parent.parent / "footage" / "generated"
                / f"concept-{state.get('concept_id', 'x')}")
    clips = []
    for index, p in enumerate(prompts, start=1):
        if (p.get("tool") or "").upper() != "VEO":
            clips.append({**p, "url": None, "ok": False,
                          "error": f"no adapter wired for {p.get('tool')}"})
            continue
        result = veo.generate_candidates(
            p["prompt"], out_root / f"shot{index}", n=1, db_path=db.DB_PATH)
        if result["ok"] and result["candidates"]:
            clips.append({**p, "url": result["candidates"][0]["path"], "ok": True})
        else:
            clips.append({**p, "url": None, "ok": False, "error": result.get("error")})
    return {"clips": clips}


def qc_clip(state: GenState) -> GenState:
    """A clip may post only if the file is really there and really a
    video: exists, non-trivial size, and (when ffprobe is on the box) a
    positive duration. Code, not a prompt."""
    clips = [dict(c) for c in state.get("clips", [])]
    for clip in clips:
        clip["ok"] = _clip_passes_qc(clip.get("url"))
    return {"clips": clips}


def _clip_passes_qc(url) -> bool:
    if not url:
        return False
    path = Path(url)
    if not path.is_file() or path.stat().st_size < 1024:
        return False
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            return float((out.stdout or "0").strip() or 0) > 0.5
        except Exception:
            return False
    return True


def route_after_qc(state: GenState) -> str:
    clips = state.get("clips", [])
    return "caption" if clips and any(c.get("ok") for c in clips) else "hold"


def caption(state: GenState) -> GenState:
    """Grounded caption via scheduling.build_caption, degrading to the
    concept's own title+hook -- a publish can't be blocked by the
    caption model being down."""
    concept = state.get("concept", {}) or {}
    fallback = " — ".join(x for x in (concept.get("title"), concept.get("hook")) if x)
    return {"caption": scheduling.build_caption(fallback, db_path=db.DB_PATH)}


def _post_gate(state: GenState, channel_row: dict) -> tuple[bool, str]:
    """The last code-enforced check before any upload. Code, not a
    prompt -- the same line validate_concept holds."""
    clips = state.get("clips", [])
    if not clips or not all(c.get("ok") for c in clips):
        return False, "clip QC failed"
    if not (state.get("caption") or "").strip():
        return False, "caption is empty"
    if (state.get("concept", {}) or {}).get("warnings"):
        return False, "concept carries warnings"
    cap = channel_row.get("rate_cap", 1)
    if autonomy.posts_today(state.get("channel", ""), path=db.DB_PATH) >= cap:
        return False, f"rate cap reached ({cap}/day)"
    return True, ""


def _park(state: GenState, reason: str) -> GenState:
    hold_id = autonomy.to_hold(
        state.get("channel", "zeropage"), reason,
        concept_id=state.get("concept_id"),
        caption=state.get("caption", ""),
        payload={"run_id": state.get("run_id"),
                 "prompts": state.get("prompts", []),
                 "prompt_scores": state.get("prompt_scores", []),
                 "critique": state.get("critique"),
                 "error": state.get("error")},
        path=db.DB_PATH,
    )
    return {"hold_id": hold_id, "held_reason": reason}


def publish(state: GenState) -> GenState:
    """BUILD -- the autonomy gap. Reads the CHANNEL's autonomy, never a
    global flag. No posting API is wired yet, so even a channel promoted
    to auto parks with an explicit reason rather than pretending."""
    channel_row = autonomy.get_channel(state.get("channel", "zeropage"),
                                       path=db.DB_PATH) or {"autonomy": "shadow",
                                                            "rate_cap": 1}
    if autonomy.killed(path=db.DB_PATH):
        return _park(state, "kill switch is on")

    ok, why = _post_gate(state, channel_row)
    if not ok:
        return _park(state, f"failed post-gate: {why}")

    mode = channel_row.get("autonomy", "shadow")
    if mode == "auto":
        return _park(state, "auto: posting API not wired yet")
    if mode == "queue":
        return _park(state, "awaiting your approval")
    return _park(state, "shadow — grading only")


def hold(state: GenState) -> GenState:
    """A run that failed a gate parks with its reason instead of posting."""
    failed_scores = [x for x in state.get("prompt_scores", []) if not x.get("pass")]
    if state.get("error"):
        reason = state["error"]
    elif not (state.get("critique", {}) or {}).get("ok") and \
            (state.get("critique", {}) or {}).get("issues"):
        reason = "eval stop: " + "; ".join(
            str(i) for i in state["critique"]["issues"])
    elif failed_scores:
        # the judge's own one-liner, so /holds says why the credit
        # wouldn't have been spent
        reason = "prompt gate: " + "; ".join(
            f"{x['reason']} ({x['score']}/10)" for x in failed_scores)
    elif not state.get("prompts"):
        reason = "no AI shots to render (camera-only concept)"
    elif not state.get("clips"):
        reason = "held before render"
    else:
        reason = "no usable clips (render is a dry-run stub)"
    return _park(state, reason)


# --- graph ----------------------------------------------------------------

def _build():
    g = StateGraph(GenState)
    for name, fn in [
        ("planner", planner), ("ensure_locations", ensure_locations),
        ("ground_entities", ground_entities), ("ground_rag", ground_rag),
        ("gen_concept", gen_concept), ("evaluate", evaluate),
        ("structure_prompt", structure_prompt), ("score_prompts", score_prompts),
        ("generate_render", generate_render),
        ("qc_clip", qc_clip), ("caption", caption), ("publish", publish),
        ("hold", hold),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "planner")
    g.add_conditional_edges("planner",
        lambda s: "go", {"go": "ensure_locations"})
    g.add_conditional_edges("ensure_locations",
        lambda s: "stop" if s.get("error") else "go",
        {"stop": "hold", "go": "ground_entities"})
    g.add_edge("ground_entities", "ground_rag")
    g.add_edge("ground_rag", "gen_concept")
    g.add_edge("gen_concept", "evaluate")
    g.add_conditional_edges("evaluate", route_after_eval, {
        "pass": "structure_prompt",
        "retry": "gen_concept",
        "hold": "hold",
    })
    g.add_edge("structure_prompt", "score_prompts")
    g.add_conditional_edges("score_prompts", route_after_score, {
        "generate_render": "generate_render",
        "hold": "hold",
    })
    g.add_edge("generate_render", "qc_clip")
    g.add_conditional_edges("qc_clip", route_after_qc, {
        "caption": "caption", "hold": "hold",
    })
    g.add_edge("caption", "publish")
    g.add_edge("publish", END)
    g.add_edge("hold", END)
    return g.compile()


GRAPH = _build()


def run(goal: str, *, brand: str = "antihero", spark: Optional[str] = None,
        client: Optional[str] = None, use_pov: bool = True,
        channel: str = "zeropage", picked_locations=None,
        picked_characters=None, picked_props=None) -> dict:
    autonomy.init(path=db.DB_PATH)
    return GRAPH.invoke({
        "goal": goal, "brand": brand, "spark": spark or goal,
        "client": client, "use_pov": use_pov, "channel": channel,
        "picked_locations": picked_locations or [],
        "picked_characters": picked_characters or [],
        "picked_props": picked_props or [],
        "attempts": 0,
    })

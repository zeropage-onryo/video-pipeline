"""
src/orchestrator.py — the autonomous content graph over pre-production:

    scout -> planner -> ensure_locations -> ground_entities -> ground_rag
        -> gen_concept -> evaluate -> structure_prompt -> generate_render
                ^_____________|            -> qc_clip -> caption -> publish
                (corrective re-run)                 \\-> hold  (park, don't post)

`scout` is the research agent's socket (src/scout.py): asked for, it
replaces the caller's rotated spark with one discovered by crawling;
unasked, or with an empty bank, it is a no-op and the run proceeds on
whatever spark it was given. It runs before planner so the direction is
traced beside the concept it produced.

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

The run takes photos as well as a direction. `reference_photos` is a
list of site-relative URLs -- `/refs/<sha>.jpg` from the research
scout's bin, or asset-bank photo URLs -- and they reach BOTH models:
as bytes the scene writer can look at, and as the shot's `refs`, which
is what the keyframe and the clip anchor on. Deliberately NOT
`picked_references`, which names RAG SOURCES: one is what the models
look at, the other is what they read.

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

from . import (
    autonomy,
    crag,
    db,
    entities,
    preprod,
    promptgen,
    rag,
    scene_chain,
    scheduling,
    settings,
    shootgen,
    winners,
)
from . import (
    scout as scout_mod,
)
from .gemini_utils import generate_with_retry

MAX_ATTEMPTS = 3
JUDGE_MIN = 0.6
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", shootgen.MODEL)  # match the other stages


def prompt_gate_min() -> int:
    """The gate's bar (of 10), read per run: the Dev Studio Settings tab
    (settings table) wins, then PROMPT_GATE_MIN in the env, then 7 --
    so raising the bar no longer needs a restart."""
    return settings.prompt_gate_min(path=db.DB_PATH)
MAX_PROMPT_REWORKS = 1  # one targeted rewrite per failing shot before it holds


class GenState(TypedDict, total=False):
    # inputs
    goal: str
    brand: str
    client: Optional[str]
    spark: Optional[str]
    scout: bool                     # ask the research agent for the spark
    scout_finding_id: int           # which banked finding seeded this run
    scout_rationale: str            # why the scout chose it (stored, never injected)
    use_pov: bool
    channel: str
    picked_locations: list          # ids; empty/absent = all on file
    picked_characters: list
    picked_props: list
    picked_references: list         # asset-shelf source identifiers; empty/absent = no asset
    reference_photos: list          # PHOTO urls the run was handed -- /refs/<sha>.jpg
                                    # from the research scout, or asset-bank photo
                                    # URLs. Deliberately NOT picked_references, which
                                    # names RAG SOURCES: one is what the models look
                                    # at, the other is what they read.
                                    # grounding (craft/structuring advice still auto-grounds
                                    # -- see ground_rag)
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
    prompt_rework_attempts: int     # bounded per-shot rewrite passes, not concept retries
    refs: list                      # the photo urls attached to the scene's shot
    keyframes: list                 # [{"n", "ok", "url", "error"}] -- the stills
    parked_reason: str              # what the Queue card says it is waiting on
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

def scout(state: GenState) -> GenState:
    """The research agent's socket. Claims a spark discovered by
    src/scout.py -- or leaves the run exactly as it found it.

    Three reasons this is a node rather than a step in trigger.py:
    the choice of direction is then traced in LangSmith beside the
    concept it produced (so a bad night can be read back to the signal
    that caused it); a LangGraph-dev invocation gets the same behaviour
    as the cron path without duplicating it; and `scout_finding_id`
    rides the run state to `hold`, so the Queue card can say what the
    idea came from.

    The guard is inside the node, not on a conditional edge, on
    purpose: this must be a no-op for every existing caller. An
    explicit `spark=` (a Director re-fire, a hand-typed direction, the
    16 sparks run_morning_prompts.sh walks) already knows what it
    wants, and silently overriding it with a crawl result would make
    `--spark` a lie. So the node acts only when asked -- state["scout"]
    -- and even then falls straight through when the bank has nothing
    at or above scout.SCORE_FLOOR, leaving the caller's spark (which is
    sparks.txt's rotation) untouched. A thin crawl night costs the run
    nothing.

    Never raises: the whole point of the fallback is that research is
    an enhancement over a rotation that already works.
    """
    if not state.get("scout"):
        return {}
    try:
        finding = scout_mod.next_spark(state.get("brand") or "zeropage", path=db.DB_PATH)
    except Exception as e:
        print(f"note: scout unavailable, keeping the rotated spark: {e}", file=sys.stderr)
        return {}
    if not finding:
        print("note: scout bank empty above the floor — keeping the rotated spark",
              file=sys.stderr)
        return {}
    print(f"scout: spark={finding['spark']!r} score={finding.get('score')}", file=sys.stderr)
    return {"spark": finding["spark"],
            "goal": finding["spark"],
            "scout_finding_id": finding["id"],
            "scout_rationale": finding.get("rationale") or ""}


def planner(state: GenState) -> GenState:
    """BUILD stub -- for now: straight to a full plan, autonomy read from
    the channel row (defaulting to shadow if the table isn't seeded).
    Also mints the run_id everything downstream logs against."""
    channel = state.get("channel") or "zeropage"
    row = autonomy.get_channel(channel, path=db.DB_PATH)
    run_id = state.get("run_id") or uuid.uuid4().hex
    # Claim the scouted spark here, not in the scout node: the run_id it
    # is stamped with is minted on this line, and a finding marked used
    # before a run exists to point at is how the same spark gets served
    # twice after a crash between the two.
    if state.get("scout_finding_id"):
        scout_mod.mark_used(state["scout_finding_id"], run_id=run_id, path=db.DB_PATH)
    return {
        "channel": channel,
        "autonomy": (row or {}).get("autonomy", "shadow"),
        "run_id": run_id,
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
    """Two layers (narrowed again 2026-08-20 from the first
    opt-in-everything pass, once it was clear that threw out craft
    guidance along with the brand's own assets):

    - Craft/structuring advice (shootgen.AUTO_IDEATION_DOMAINS -- the
      marketing shelf: platform mechanics, edit anatomy, what earns a
      swipe) stays automatic, CRAG-graded off the spark, same as it
      always was. This isn't the brand's own material, so there's
      nothing to leak by grounding on it every run.
    - The brand's own assets (personal_brand voice, cinematography
      look, proven_results/winning_prompts performance history) stay
      opt-in only: picked_references names exact source identifiers
      (as shown on /library or rag.list_sources), pulled verbatim with
      rag.fetch_by_sources -- no embedding call, no similarity
      ranking, because the selection already happened. Nothing picked
      means nothing from these shelves, not even an attempt.

    Never raises on either layer: an unreachable store, an empty
    spark, or picks that don't match anything all degrade to that
    layer contributing nothing, never a crash."""
    references = []

    query = (state.get("spark") or state.get("goal") or "").strip()
    if query:
        craft = crag.retrieve_with_crag(query, _client(), GEMINI_MODEL,
                                        domain=shootgen.AUTO_IDEATION_DOMAINS)
        if craft.get("ok") and craft.get("references"):
            print(f"Grounding in {len(craft['references'])} craft reference(s)", file=sys.stderr)
            references.extend(craft["references"])
        elif not craft.get("ok"):
            print(f"note: no craft-advice grounding: {craft.get('error', 'unavailable')}",
                  file=sys.stderr)

    picked = state.get("picked_references") or []
    if picked:
        result = rag.fetch_by_sources(picked)
        if result["ok"] and result["references"]:
            print(f"Grounding in {len(result['references'])} selected asset reference(s)",
                  file=sys.stderr)
            references.extend(result["references"])
        elif not result["ok"]:
            reason = result.get("error", "none of the selected sources were found")
            print(f"note: generating without selected assets: {reason}", file=sys.stderr)

    return {"references": rag.format_references(references)}


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

    # standing negative steer: patterns you've marked "didn't work" are
    # folded in so the next batch avoids repeating them (winners.avoid_guidance).
    avoid = winners.avoid_guidance(path=db.DB_PATH)
    if avoid:
        spark = f"{spark or ''}\n{avoid}".strip()

    # ONE scene, ONE prompt -- the same unit the Studio has produced
    # since 2026-08-26, not the legacy multi-shot concept this node used
    # to write. That divergence stopped being cosmetic on 2026-08-29,
    # when the night's output started parking in the Queue: the Queue
    # (and pick_rate, and the scene board) key on is_scene, which is
    # len(shots) == 1, so a six-shot concept would have been generated,
    # scored, keyframed and then invisible to the surface meant to
    # approve it. `use_pov` has no meaning here -- the scene brief
    # neither offers nor names a camera -- so it stops being passed
    # rather than being passed and ignored.
    # Photos the run was handed -- the scout's bin, normally -- as bytes
    # the writer can actually look at. A scene written FROM a photograph
    # beats one told a photograph exists, which is the whole reason
    # format_cast's "(reference photos on file)" was not enough.
    handed = list(state.get("reference_photos") or [])
    image_refs = scene_chain.as_image_refs(handed) if handed else None

    result = shootgen.generate_scene_concept(
        brand=state.get("brand", "antihero"),
        spark=spark,
        gemini_client=_client(),
        db_path=db.DB_PATH,
        references=state.get("references", ""),
        cast=state.get("cast"),
        image_refs=image_refs,
    )
    # the generator returns warnings BESIDE the concept, not inside it;
    # fold them in so evaluate's code-enforced check actually sees them.
    concept = {**result["concept"], "warnings": result["warnings"]}

    # The photos this scene renders against, stored on its shot: the
    # assets it NAMED first (identity holds the anchor slot Runway reads),
    # the handed-in research images after. Never fatal -- an ungrounded
    # scene is still a scene, and attach_refs says so by returning [].
    refs = []
    try:
        refs = scene_chain.attach_refs(result["concept_id"], handed,
                                       db_path=db.DB_PATH)
        if refs:
            concept["shots"][0]["refs"] = refs
    except Exception as e:
        print(f"note: references not attached: {e}", file=sys.stderr)

    return {"concept": concept, "concept_id": result["concept_id"],
            "refs": refs, "attempts": state.get("attempts", 0) + 1}


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

_STILL_RUBRIC = """Write a Midjourney prompt for a single STILL that will be the
reference / first frame of this video shot. Describe ONLY what's in the frame --
subject, composition, framing/lens, lighting, mood, style. NO motion, NO camera
movement (the still is a frozen frame). One vivid sentence, then Midjourney flags.
End with: --ar 9:16 --style raw
Return ONLY the prompt line, nothing else."""


def _midjourney_still(shot_prompt: str) -> str:
    """The Midjourney still that anchors a Runway shot -- a motion-free
    frame prompt derived from the video prompt. It is the reference frame
    Runway builds from AND an image post in its own right. No gate:
    stills cost nothing to prompt and, per policy, need no approval."""
    try:
        raw = generate_with_retry(_client(), GEMINI_MODEL,
                                  _STILL_RUBRIC + "\n\nVIDEO SHOT:\n" + shot_prompt)
        line = next((ln.strip() for ln in (raw or "").splitlines() if ln.strip()), "")
        if line and "--ar" not in line:
            line = line + " --ar 9:16 --style raw"
        return line
    except Exception:
        return ""


def _technique_references(tool: str) -> str:
    """AI-video prompt-syntax guidance for this shot's tool, CRAG-graded
    off the ai_prompting shelf -- the same never-raises degrade contract
    ground_rag keeps. Its own retrieval, separate from ground_rag's:
    ground_rag answers "what should we shoot," this answers "how do we
    phrase it for this specific tool." An unreachable store or a weak
    match just means no refinement happens, same as an ungrounded run."""
    query = (f"{tool} prompting technique for photorealistic AI video generation"
             if tool else "AI video prompting technique for photorealistic generation")
    result = crag.retrieve_with_crag(query, _client(), GEMINI_MODEL, domain=promptgen.REFINE_DOMAIN)
    if result.get("ok") and result.get("references"):
        return rag.format_references(result["references"])
    return ""


def structure_prompt(state: GenState) -> GenState:
    """The AI shots' paste-ready prompts. shootgen already writes a
    first draft into the concept (validate_concept flags an AI shot
    without one); each draft is then run through promptgen.refine_prompt,
    which polishes it against real tool-specific prompting technique
    guidance (Seedance/Runway/Veo/etc. cheat codes on the ai_prompting
    RAG shelf) before it's scored. Refinement is an enhancement, never
    a gate -- a missing store, a bad client, or a rejected refinement
    all fall back to the original prompt untouched, same contract as
    ground_rag.

    Also drafts the Midjourney still that anchors each shot: the reference
    frame Runway generates from, and an image post in its own right.
    Stills need no approval, so this step is never gated.

    Every shot with a prompt is AI-eligible (the all-AI move,
    2026-08-20): source == "CAMERA" now means Michael captures reference
    material -- an acting take, a room plate -- that anchors the
    generation via the shot's reference_image, not that the shot escapes
    the pipeline. Until a reference exists the shot generates from its
    text prompt alone, same as any other; a reference is an enhancement,
    never a gate, exactly like RAG grounding. A shot with no prompt at
    all still drops out -- there is nothing to structure. When a shot
    carries a real capture, the Midjourney still is skipped: the still's
    whole job is being the anchor frame, and the capture IS one."""
    shots = [s for s in (state.get("concept", {}) or {}).get("shots", [])
             if s.get("prompt")]
    prompts = []
    for s in shots:
        tool = s.get("tool") or ""
        references = _technique_references(tool)
        refined = promptgen.refine_prompt(s["prompt"], tool, _client(),
                                          model=GEMINI_MODEL, references=references)
        reference_image = (s.get("reference_image") or "").strip()
        entry = {"tool": s.get("tool"), "prompt": refined,
                 "still": "" if reference_image else _midjourney_still(refined)}
        # carried only when attached, same as on the shot dict itself
        if reference_image:
            entry["reference_image"] = reference_image
        prompts.append(entry)
    return {"prompts": prompts}


# --- the prompt gate: nothing spends a credit until its prompt clears ------

def _structural_check(text: str) -> tuple[bool, str]:
    """Layer 1, deterministic, zero model calls -- the cheap failures:
    empty, too thin, leftover template tokens.

    NO UPPER LENGTH BOUND, deliberately (removed 2026-08-14). A ceiling
    was here (130 words, "the model will drop detail") and it was the
    wrong tool in the wrong layer: length is a quality judgment, not a
    broken-output signal, and this layer exists to catch output that is
    broken. The evidence said so too -- across the first 17 scored
    prompts (33-75 words, median 46) the ceiling never once fired, while
    six of eight judge failures were the OPPOSITE problem: missing
    camera framing, missing lens, no specified motion. Detail is what
    the gate is short of, so nothing here should push toward brevity.
    Over-stuffing, if it ever shows up, is the judge's `coherence`
    dimension to grade, not this function's to reject."""
    t = (text or "").strip()
    n = len(t.split())
    if n < 15:
        return False, "too thin — under 15 words"
    if re.search(r"\{.*?\}|\[.*?\]|TODO|TBD", t):
        return False, "leftover placeholder / template token"
    return True, ""


_PROMPT_RUBRIC = """You grade AI VIDEO prompts (Runway). Score how likely THIS prompt
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
        # rides along so the hold card can show the capture beside the
        # prompt it anchors; present only when the shot carries one
        ref = ({"reference_image": p["reference_image"]}
               if p.get("reference_image") else {})
        ok, why = _structural_check(text)
        if not ok:
            scored.append({"prompt": text, "tool": p.get("tool"),
                           "still": p.get("still"), "score": 0,
                           "pass": False, "reason": why, "dims": {}, **ref})
            continue
        verdict = _judge_prompt(text)
        scored.append({"prompt": text, "tool": p.get("tool"),
                       "still": p.get("still"),
                       "score": verdict["score"],
                       "pass": verdict["score"] >= prompt_gate_min(),
                       "reason": verdict["reason"], "dims": verdict["dims"],
                       **ref})
    autonomy.log_prompt_scores(state.get("run_id"), scored, path=db.DB_PATH)
    return {"prompt_scores": scored}


def _rework_shot_prompt(original_prompt: str, verdict: dict) -> str:
    """Rewrite ONE AI shot prompt to fix exactly what the judge flagged --
    the named weak dimension(s) and its reason -- rather than regenerating
    the concept from scratch. Keeps the fix as small and targeted as the
    diagnosis it's based on."""
    weak = [d for d, v in (verdict.get("dims") or {}).items() if v < 2]
    weakness = f"{', '.join(weak) or 'unspecified'} -- {verdict.get('reason', '')}".strip(" -")
    instruction = (
        "Rewrite the following AI video generation prompt to fix EXACTLY the "
        "weakness named below. Keep the same subject, setting, tool, and "
        "grade -- change only how precisely it's specified (add the missing "
        "camera/lens/framing, resolve the competing actions into one clear "
        "action, add the missing light/mood, whatever the weakness names). "
        "Keep the same grounded-realism recipe: handheld imperfection, "
        "practical light, diegetic sound, and the negative clause at the end "
        "(no glossy CGI, no plastic AI sheen, no dramatic slow motion, no "
        "smooth commercial camera moves, no over-grading).\n\n"
        f"WEAKNESS TO FIX: {weakness}\n\n"
        f"ORIGINAL PROMPT:\n{original_prompt}\n\n"
        "Return ONLY the rewritten prompt text -- no preamble, no quotes, no "
        "markdown fences."
    )
    return generate_with_retry(_client(), GEMINI_MODEL, instruction).strip()


def revise_prompts(state: GenState) -> GenState:
    """One bounded rework pass over score_prompts' output: shots that
    already passed are left untouched; shots that failed get rewritten
    against the judge's own diagnosis and re-scored. Keeps `prompts` and
    the saved `concept`'s shots in sync with whatever text actually
    cleared the gate, so render (and the concept a human eventually
    reviews) reflect the reworked prompt, not the original weak one."""
    scores = state.get("prompt_scores", [])
    prompts = list(state.get("prompts", []))
    concept = dict(state.get("concept", {}))
    shots = list(concept.get("shots") or [])
    # MUST mirror structure_prompt's filter exactly -- these indices map
    # score entries back onto concept shots, and every shot with a
    # prompt is AI-eligible now, whatever its source (see structure_prompt)
    ai_shot_indices = [i for i, s in enumerate(shots) if s.get("prompt")]
    # Same scene-consistency anchor generate_concept/generate_shot_list
    # prepend up front -- reapplied here because the rework instruction
    # only *asks* the model to keep the same subject/setting/grade; a
    # rewrite is free to drop the exact bible wording, and this shot
    # still has to match every other shot in the concept when it renders.
    bible = shootgen.derive_scene_bible(concept.get("title"), concept.get("logline"),
                                        concept.get("grade"))

    revised = []
    for i, entry in enumerate(scores):
        if entry["pass"]:
            revised.append(entry)
            continue
        try:
            new_text = _rework_shot_prompt(entry["prompt"], entry)
            if bible and not new_text.startswith(bible):
                new_text = f"{bible}. {new_text}"
        except Exception as e:
            # couldn't get a rewrite -- leave the original score as-is,
            # route_after_score will hold once the attempt is spent
            revised.append(entry)
            print(f"note: prompt rework failed, keeping original: {e}", file=sys.stderr)
            continue

        ok, why = _structural_check(new_text)
        if not ok:
            new_entry = {**entry, "prompt": new_text, "pass": False, "reason": why}
        else:
            verdict = _judge_prompt(new_text)
            new_entry = {"prompt": new_text, "tool": entry.get("tool"),
                        "still": entry.get("still"), "score": verdict["score"],
                        "pass": verdict["score"] >= prompt_gate_min(),
                        "reason": verdict["reason"], "dims": verdict["dims"],
                        **({"reference_image": entry["reference_image"]}
                           if entry.get("reference_image") else {})}
        revised.append(new_entry)

        if i < len(prompts):
            prompts[i] = {**prompts[i], "prompt": new_entry["prompt"]}
        if i < len(ai_shot_indices):
            shots[ai_shot_indices[i]]["prompt"] = new_entry["prompt"]

    concept["shots"] = shots
    autonomy.log_prompt_scores(state.get("run_id"), revised, path=db.DB_PATH)
    return {
        "prompt_scores": revised,
        "prompts": prompts,
        "concept": concept,
        "prompt_rework_attempts": state.get("prompt_rework_attempts", 0) + 1,
    }


def route_after_score(state: GenState) -> str:
    """Every AI shot must clear the bar before it renders -- no
    half-rendered credit burn. Unlike a plain gate, a failing shot isn't
    an automatic hold: the judge already names exactly what's weak
    (dims + reason), so one bounded rewrite pass gets to fix that
    specific thing before the whole concept -- including whatever shots
    already passed -- is thrown away over one fixable line. (Camera-only
    concepts have no scores and hold too; render has nothing for them
    either.)"""
    scores = state.get("prompt_scores", [])
    if not scores:
        return "hold"
    if all(x["pass"] for x in scores):
        return "generate_render"
    if state.get("prompt_rework_attempts", 0) < MAX_PROMPT_REWORKS:
        return "rework"
    return "hold"


def keyframe(state: GenState) -> GenState:
    """What the automation actually produces overnight: a scene with its
    scored prompt stored on it, a still to look at, and a place in the
    Queue.

    Before this the right-hand side of the graph was all stub -- every
    run ended "no usable clips (render is a dry-run stub)" in the hold
    queue, so the nightly loop was structurally complete and produced
    nothing anyone could judge. A keyframe costs cents and a clip costs
    real money, so the automation goes as far as the still and stops:
    approving in the Queue is what spends.

    Two things happen here, both through src/scene_chain.py so the
    request path, the canvas and this graph share one implementation:

    - the prompt structure_prompt refined is PERSISTED onto the shot.
      It was only ever in the run's state before, which meant the row
      Runway would render from still held shootgen's first draft while
      the version that passed the gate lived in a job payload.
    - a Nano keyframe is rendered from that prompt and attached as the
      shot's reference_image -- the frame the clip will anchor on.

    Gated by the prompt gate above it, deliberately: only a scene whose
    prompt cleared the judge earns an image. Never fatal -- a keyframe
    that fails (usually NANO_DAILY_CAP, 20/day shared with every
    Director render) parks the scene as text-to-video with the reason
    on its card, which is the honest version of the same run.
    """
    concept_id = state.get("concept_id")
    if not concept_id:
        return {"keyframes": []}

    shots = [s for s in (state.get("concept", {}) or {}).get("shots", [])
             if s.get("prompt")]
    prompts = state.get("prompts", [])
    done = []
    for shot, refined in zip(shots, prompts):
        shot_n = shot.get("n", 1)
        try:
            scene_chain.persist_prompt(concept_id, shot_n,
                                       refined.get("prompt", ""),
                                       db_path=db.DB_PATH)
        except Exception as e:
            done.append({"n": shot_n, "ok": False, "error": f"prompt not stored: {e}"})
            continue
        if os.environ.get("ZEROPAGE_KEYFRAME") == "0":
            done.append({"n": shot_n, "ok": False, "error": "keyframes disabled"})
            continue
        result = scene_chain.keyframe_scene(concept_id, shot_n, db_path=db.DB_PATH)
        done.append({"n": shot_n, "ok": bool(result.get("ok")),
                     "url": result.get("media_url"),
                     "error": result.get("error")})

    rendered = [k for k in done if k["ok"]]
    failed = [k for k in done if not k["ok"]]
    reason = ("keyframe rendered — approve in the Queue to spend on the clip"
              if rendered else
              "no keyframe: " + (failed[0].get("error") or "unknown")
              if failed else "no shot to keyframe")
    try:
        scene_chain.park_scene(concept_id, reason, db_path=db.DB_PATH)
    except Exception:
        pass       # a scene that cannot be parked is still on the board
    return {"keyframes": done, "parked_reason": reason}


def generate_render(state: GenState) -> GenState:
    """The credit gate: rendering is dry by default (ZEROPAGE_RENDER != 1)
    -- every clip comes back url=None, ok=False and the run parks
    downstream, so no credits are ever spent. With ZEROPAGE_RENDER=1,
    tool==RUNWAY routes through runway.py (wired 2026-08-12), which has
    its own second gate: no RUNWAY_SPEND_OK=1 means the clip comes back
    ok=False with "render it in the app" as the reason -- the Runway API
    has no Explore Mode, so API credits are always a deliberate, per-run
    human approval.

    tool==HIGGSFIELD routes through higgsfield.py (wired 2026-08-31),
    which has the same two gates -- and until it existed every night a
    shot planned for Higgsfield came back "no adapter wired for
    HIGGSFIELD" and parked, though shootgen names HIGGSFIELD first in
    ZEROPAGE_AI_TOOLS and shot.py already compiled its prompt.

    tool==VEO keeps the legacy veo.py path for when Veo
    returns to the registry; anything else is honestly "no adapter
    wired"."""
    prompts = state.get("prompts", [])
    if os.environ.get("ZEROPAGE_RENDER") != "1":
        return {"clips": [{**p, "url": None, "ok": False} for p in prompts]}

    from . import higgsfield, runway, veo
    connectors = {"VEO": veo, "RUNWAY": runway, "HIGGSFIELD": higgsfield}
    out_root = (Path(db.DB_PATH).parent.parent / "footage" / "generated"
                / f"concept-{state.get('concept_id', 'x')}")
    clips = []
    for index, p in enumerate(prompts, start=1):
        connector = connectors.get((p.get("tool") or "").upper())
        if connector is None:
            clips.append({**p, "url": None, "ok": False,
                          "error": f"no adapter wired for {p.get('tool')}"})
            continue
        result = connector.generate_candidates(
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
    dest = (channel_row.get("targets") or "").replace(",", " + ").strip()
    if mode == "auto":
        return _park(state, f"auto: posting adapter not wired for {dest or 'this channel'} yet")
    if mode == "queue":
        return _park(state, f"awaiting your approval to post → {dest or 'review'}")
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
    elif state.get("parked_reason"):
        # the run got as far as it can without spending: the scene is in
        # the Queue with (usually) a still, waiting on a human. Saying
        # "no usable clips" here was true and useless -- it described
        # the stub rather than what the night produced.
        reason = state["parked_reason"]
    elif not state.get("clips"):
        reason = "held before render"
    else:
        reason = "no usable clips (render is a dry-run stub)"
    return _park(state, reason)


# --- graph ----------------------------------------------------------------

def _build():
    g = StateGraph(GenState)
    for name, fn in [
        ("scout", scout),
        ("planner", planner), ("ensure_locations", ensure_locations),
        ("ground_entities", ground_entities), ("ground_rag", ground_rag),
        ("gen_concept", gen_concept), ("evaluate", evaluate),
        ("structure_prompt", structure_prompt), ("score_prompts", score_prompts),
        ("revise_prompts", revise_prompts),
        ("keyframe", keyframe), ("generate_render", generate_render),
        ("qc_clip", qc_clip), ("caption", caption), ("publish", publish),
        ("hold", hold),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "scout")
    g.add_edge("scout", "planner")
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
    # revise_prompts re-scores only the shots it rewrote (leaving shots that
    # already passed untouched), so it routes back through the SAME judge --
    # never back through score_prompts, which would re-bill every already-
    # passing shot's judge call for nothing.
    # the gate's pass branch goes to `keyframe` first: the still is what
    # the morning approval actually looks at, and it is the last step
    # that does not spend real money
    g.add_conditional_edges("score_prompts", route_after_score, {
        "generate_render": "keyframe",
        "rework": "revise_prompts",
        "hold": "hold",
    })
    g.add_conditional_edges("revise_prompts", route_after_score, {
        "generate_render": "keyframe",
        "rework": "revise_prompts",  # unreachable while MAX_PROMPT_REWORKS == 1;
                                      # kept so raising that constant later just works
        "hold": "hold",
    })
    g.add_edge("keyframe", "generate_render")
    g.add_edge("generate_render", "qc_clip")
    g.add_conditional_edges("qc_clip", route_after_qc, {
        "caption": "caption", "hold": "hold",
    })
    g.add_edge("caption", "publish")
    g.add_edge("publish", END)
    g.add_edge("hold", END)
    return g.compile()


GRAPH = _build()


def run(goal: str, *, brand: Optional[str] = None, spark: Optional[str] = None,
        client: Optional[str] = None, use_pov: bool = False,
        channel: str = "zeropage", picked_locations=None,
        picked_characters=None, picked_props=None, picked_references=None,
        reference_photos=None,
        scout: bool = False) -> dict:
    """
    `brand` defaults to `channel` rather than a hardcoded value on
    purpose: `channel` decides where the run gets FILED (which
    hold_queue row, which autonomy/rate-cap row), `brand` decides which
    engine actually GENERATES (real cast/locations for Antihero,
    faceless format-driven for Zero Page). They used to default
    independently (channel="zeropage", brand="antihero") -- call `run(x)`
    or `run(x, channel="zeropage")` with nothing else and you'd silently
    get a full Antihero concept (real names, real gear) filed and
    displayed under a card labeled ZEROPAGE. That's exactly what
    happened to hold_queue row 13 / concept 111 on 2026-08-14: a manual
    trigger invocation set --channel without --brand and got bitten by
    it. Passing brand explicitly (as run_morning_prompts.sh always does)
    still lets channel and brand differ on purpose when that's really
    what's wanted -- this only changes what happens when brand is
    omitted.

    `scout=True` asks the research agent for the direction instead of
    using the one passed in. Off by default and never inferred: an
    explicit spark stays authoritative, and a caller that wants a
    crawled idea has to say so. The spark passed alongside it is still
    required -- it is what the run falls back to when the scout's bank
    is empty or every finding sits below scout.SCORE_FLOOR.
    """
    if brand is None:
        brand = channel
    elif brand != channel:
        print(f"note: channel={channel!r} but brand={brand!r} -- filing under "
              f"one channel, generating with the other engine, on purpose",
              file=sys.stderr)
    autonomy.init(path=db.DB_PATH)
    winners.init(path=db.DB_PATH)
    scout_mod.init(path=db.DB_PATH)
    return GRAPH.invoke({
        "goal": goal, "brand": brand, "spark": spark or goal, "scout": scout,
        "client": client, "use_pov": use_pov, "channel": channel,
        "picked_locations": picked_locations or [],
        "picked_characters": picked_characters or [],
        "picked_props": picked_props or [],
        "picked_references": picked_references or [],
        "reference_photos": reference_photos or [],
        "attempts": 0,
    })

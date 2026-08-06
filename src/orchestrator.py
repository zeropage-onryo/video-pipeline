"""
src/orchestrator.py — LangGraph orchestrator + evaluator over the kept
pre-production stages:

    ensure_locations -> shootgen -> evaluate -> finalize
                             ^__________|  (corrective re-run on fail)

The evaluator combines a code-enforced check (shootgen already attaches
`warnings` — prompts request, code enforces) with an optional LLM-judge that
scores feasibility for a solo two-camera house shoot.

Deps:   pip install langgraph langsmith
Env:    GEMINI_API_KEY            (required, already used by your stages)
        JUDGE=1                   (optional) turn the LLM-judge on
        GEMINI_MODEL=...          (optional) judge model; match your other stages
        LANGSMITH_TRACING=true    (optional) auto-trace the graph to LangSmith
        LANGSMITH_API_KEY=...     (optional) with the line above
"""
from __future__ import annotations

import json
import os
from typing import Optional, TypedDict

from google import genai
from langgraph.graph import END, START, StateGraph

from . import db, preprod, shootgen

MAX_ATTEMPTS = 3
JUDGE_MIN = 0.6
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", shootgen.MODEL)  # match the other stages


class GenState(TypedDict, total=False):
    goal: str
    brand: str
    client: Optional[str]
    spark: Optional[str]
    use_pov: bool
    references: str
    concept: dict
    critique: dict          # {"ok": bool, "issues": [...], "score": float}
    attempts: int
    shot_prompts: list
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


# --- nodes ---------------------------------------------------------------

def ensure_locations(state: GenState) -> GenState:
    if not preprod.list_locations(path=db.DB_PATH):
        return {"error": "No described locations — photograph a space first."}
    return {}


def gen_concept(state: GenState) -> GenState:
    # On a retry, fold the evaluator's feedback into the spark so the re-run improves.
    spark = state.get("spark")
    crit = state.get("critique")
    if crit and not crit.get("ok"):
        spark = f"{spark or ''}\nFix these issues: {'; '.join(crit.get('issues', []))}".strip()

    references = shootgen.reference_block(
        spark=spark, client=state.get("client"), db_path=db.DB_PATH
    )
    result = shootgen.generate_concept(
        brand=state.get("brand", "antihero"),
        client=state.get("client"),
        spark=spark,
        gemini_client=_client(),
        use_pov=state.get("use_pov", True),
        db_path=db.DB_PATH,
        references=references,
    )
    # generate_concept returns warnings BESIDE the concept, not inside it;
    # fold them in so evaluate's code-enforced check actually sees them.
    concept = {**result["concept"], "warnings": result["warnings"]}
    return {"concept": concept, "references": references,
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
    return "retry" if state.get("attempts", 0) < MAX_ATTEMPTS else "stop"


def finalize(state: GenState) -> GenState:
    shots = [s for s in (state.get("concept", {}) or {}).get("shots", [])
             if s.get("source") == "AI" and s.get("prompt")]
    return {"shot_prompts": [{"tool": s.get("tool"), "prompt": s["prompt"]} for s in shots]}


# --- graph ---------------------------------------------------------------

def _build():
    g = StateGraph(GenState)
    g.add_node("ensure_locations", ensure_locations)
    g.add_node("shootgen", gen_concept)
    g.add_node("evaluate", evaluate)
    g.add_node("finalize", finalize)

    g.add_edge(START, "ensure_locations")
    g.add_conditional_edges("ensure_locations",
        lambda s: "stop" if s.get("error") else "go",
        {"stop": END, "go": "shootgen"})
    g.add_edge("shootgen", "evaluate")
    g.add_conditional_edges("evaluate", route_after_eval,
        {"pass": "finalize", "retry": "shootgen", "stop": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()


GRAPH = _build()


def run(goal: str, *, brand: str = "antihero", spark: Optional[str] = None,
        client: Optional[str] = None, use_pov: bool = True) -> dict:
    return GRAPH.invoke({"goal": goal, "brand": brand, "spark": spark or goal,
                         "client": client, "use_pov": use_pov, "attempts": 0})

#!/usr/bin/env python3
"""
The LangGraph orchestrator over pre-production: generate a concept,
evaluate it against reality, and retry with the evaluator's notes fed
back before saving the best attempt.

This changes nothing about what a stage *is* -- it composes the pure
seams shootgen already exposes (build_concept_prompt,
parse_concept_response, validate_concept) into an explicit graph:

    load_rooms -> generate -> evaluate --clean or out of retries--> save
                      ^            |
                      +---retry----+

The evaluator is validate_concept, unchanged: "prompts request, code
advises" still holds, but the orchestrator now *uses* the advice --
warnings go back into the next attempt's prompt as evaluator notes,
and only the best attempt (fewest warnings) is saved, once, with its
warnings still attached for the human. A concept that never validates
cleanly is saved anyway after MAX_ATTEMPTS, warnings and all, because
it is worth looking at and deciding on -- the loop retries, it never
rejects.

Hermetic by the same rule as shootgen: RAG retrieval stays at the edge
(main() calls reference_block; the graph takes a plain `references`
string), and the model call goes through gemini_utils.generate_with_retry,
which tests patch at graph.generate_with_retry.
"""
import argparse
import os
import sys
from typing import Any, List, Optional, TypedDict

from dotenv import load_dotenv
from google import genai
from langgraph.graph import END, START, StateGraph

from . import preprod, shootgen
from .db import DB_PATH, init_db
from .gemini_utils import generate_with_retry

MAX_ATTEMPTS = 3


class ConceptState(TypedDict, total=False):
    # inputs
    brand: str
    client: Optional[str]
    spark: Optional[str]
    use_pov: bool
    references: str
    db_path: Any
    gemini_client: Any
    model: str
    max_attempts: int
    # working
    locations: List[dict]
    location_names: List[str]
    prompt_template: str
    attempts: int
    concept: dict
    warnings: List[str]
    best_concept: dict
    best_warnings: List[str]
    # output
    concept_id: int


def _db_kwargs(state: ConceptState) -> dict:
    return {"path": state["db_path"]} if state.get("db_path") is not None else {}


def load_rooms(state: ConceptState) -> dict:
    """Grounding starts here, same contract as every generator: no
    described rooms is a loud error, not an ungrounded guess."""
    locations = preprod.list_locations(**_db_kwargs(state))
    if not locations:
        raise ValueError(
            "no locations described yet -- run `python -m src.locations` first"
        )
    return {
        "locations": locations,
        "location_names": [loc["name"] for loc in locations],
    }


def generate(state: ConceptState) -> dict:
    """
    One attempt. The base prompt is identical to shootgen's -- what's
    new is the evaluator feedback appended on retries, so the model is
    told exactly which rules its last attempt broke. The stored
    prompt_template stays the base prompt: the feedback varies per run,
    and hashing it in would fragment the per-prompt rates the pick
    labels are measured against.
    """
    prompt = shootgen.build_concept_prompt(
        state["locations"], state["brand"], state.get("client"), state.get("spark"),
        use_pov=state.get("use_pov", True), references=state.get("references", ""),
    )
    attempt_prompt = prompt
    if state.get("warnings"):
        attempt_prompt += (
            "\n\nEVALUATOR NOTES -- your previous attempt broke these rules. "
            "Fix every one:\n" + "\n".join(f"- {w}" for w in state["warnings"])
        )
    concept = shootgen.parse_concept_response(
        generate_with_retry(
            state.get("gemini_client"), state.get("model", shootgen.MODEL), attempt_prompt
        )
    )
    return {
        "concept": concept,
        "prompt_template": prompt,
        "attempts": state.get("attempts", 0) + 1,
    }


def evaluate(state: ConceptState) -> dict:
    """The evaluator is validate_concept, unchanged. Track the best
    attempt so a retry that gets *worse* can't overwrite a better one."""
    warnings = shootgen.validate_concept(
        state["concept"], state["location_names"], use_pov=state.get("use_pov", True)
    )
    update = {"warnings": warnings}
    if "best_warnings" not in state or len(warnings) < len(state["best_warnings"]):
        update["best_concept"] = state["concept"]
        update["best_warnings"] = warnings
    return update


def verdict(state: ConceptState) -> str:
    """Clean, or out of retries -> save. Otherwise go again."""
    if not state["warnings"]:
        return "save"
    if state["attempts"] >= state.get("max_attempts", MAX_ATTEMPTS):
        return "save"
    return "retry"


def save(state: ConceptState) -> dict:
    """One DB write per run, whatever the loop did: the best attempt,
    its warnings still visible on the saved concept."""
    concept = state.get("best_concept") or state["concept"]
    warnings = state.get("best_warnings")
    if warnings is None:
        warnings = state.get("warnings", [])
    used = {shot.get("location") for shot in concept.get("shots") or []}
    location_ids = [loc["id"] for loc in state["locations"] if loc["name"] in used]
    concept_id = preprod.save_concept(
        concept, brand=state["brand"], client=state.get("client"),
        spark=state.get("spark"), location_ids=location_ids,
        prompt_template=state.get("prompt_template"),
        warnings=warnings, use_pov=state.get("use_pov", True),
        **_db_kwargs(state),
    )
    return {"concept": concept, "warnings": warnings, "concept_id": concept_id}


def build_graph():
    graph = StateGraph(ConceptState)
    graph.add_node("load_rooms", load_rooms)
    graph.add_node("generate", generate)
    graph.add_node("evaluate", evaluate)
    graph.add_node("save", save)
    graph.add_edge(START, "load_rooms")
    graph.add_edge("load_rooms", "generate")
    graph.add_edge("generate", "evaluate")
    graph.add_conditional_edges("evaluate", verdict, {"retry": "generate", "save": "save"})
    graph.add_edge("save", END)
    return graph.compile()


def run_concept_graph(brand: str, client=None, spark=None, gemini_client=None,
                      model: str = shootgen.MODEL, use_pov: bool = True,
                      db_path=None, references: str = "",
                      max_attempts: int = MAX_ATTEMPTS) -> dict:
    """
    The callable seam: same signature family as shootgen.generate_concept,
    plus max_attempts. Returns the final state -- concept, concept_id,
    warnings, attempts.
    """
    return build_graph().invoke({
        "brand": brand, "client": client, "spark": spark,
        "gemini_client": gemini_client, "model": model, "use_pov": use_pov,
        "db_path": db_path, "references": references,
        "max_attempts": max_attempts,
    })


def main(db_path=None):
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Generate one concept through the evaluate-and-retry graph."
    )
    parser.add_argument("--brand", choices=preprod.BRANDS, default="antihero")
    parser.add_argument("--client", default=None)
    parser.add_argument("--spark", default=None)
    parser.add_argument("--no-pov", action="store_true", help="no ACTION5 this shoot")
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    path = db_path if db_path is not None else DB_PATH
    init_db(path=path)
    preprod.init(path=path)

    references = shootgen.reference_block(spark=args.spark, client=args.client,
                                          db_path=path)
    try:
        result = run_concept_graph(
            brand=args.brand, client=args.client, spark=args.spark,
            gemini_client=genai.Client(api_key=api_key),
            use_pov=not args.no_pov, db_path=path, references=references,
            max_attempts=args.max_attempts,
        )
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    print(f"\nConcept {result['concept_id']} "
          f"(attempt {result['attempts']}/{args.max_attempts}, "
          f"{len(result['warnings'])} warning(s))")
    print(shootgen.format_concept_as_text(result["concept"], result["warnings"]))


if __name__ == "__main__":
    main()

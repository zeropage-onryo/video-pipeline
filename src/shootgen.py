#!/usr/bin/env python3
"""
Generate shoot concepts from the spaces you actually have.

The rest of the pipeline is footage-first: it reasons about clips that
already exist. This runs before any of that -- it takes the described
locations and proposes concepts and shot lists for footage you haven't
shot yet, grounded in real rooms rather than an imagined set.

Two layers, same discipline as promptgen.py: the model's only job is
producing a concept. validate_concept is what enforces the rules --
"prompts request, code enforces". A concept that breaks a rule is
still saved, with its warnings attached, because it's worth looking at
and deciding on rather than silently discarding.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from . import preprod, rag
from . import shot as shot_module
from .db import DB_PATH, init_db
from .gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

MODEL = "gemini-3-flash-preview"

DEFAULT_IDEA_COUNT = 8
SHOT_TYPES = ("CHARACTER", "BROLL")
SHOT_SOURCES = ("CAMERA", "AI")
CAMERAS = ("BMPCC", "ACTION5")
# The legal AI tool set is the shot.py platform registry — uppercase to
# match how concepts name tools. One registry, no second list to drift.
AI_TOOLS = tuple(t.upper() for t in shot_module.TOOLS)

NO_LOCATIONS_NOTE = (
    "note: no described locations -- generating ungrounded. Photograph and "
    "describe a space to ground concepts in real rooms."
)

NO_REFERENCES_NOTE = (
    "(no reference library available -- generate from the rooms and brand alone)"
)

# Ideation grounds in brand/cinematography (what the concept has to look and
# feel like), marketing (what actually earns a swipe/watch), and
# proven_results (what actually worked for us, per promote_winners) -- but
# never ai_prompting, which is AI-video-tool prompt syntax for a later stage
# (promptgen.py), not "what should we shoot" material.
IDEATION_DOMAINS = ("personal_brand", "cinematography", "marketing", "proven_results")


def build_reference_query(locations: list, spark=None, client=None,
                          max_chars: int = 4000) -> str:
    """
    The retrieval query for ideation: the creative direction actually in
    play -- the spark, the client/spec, and the mood of the described
    rooms (their space, textures, constraints) -- so the library returns
    tone/structure notes close to what's being made. The ideation
    analogue of pitch.py's build_reference_query, which queries with the
    footage itself.
    """
    parts: list = []
    if spark:
        parts.append(spark)
    if client:
        parts.append(client)
    for loc in locations:
        description = loc.get("description") or {}
        if description.get("space"):
            parts.append(description["space"])
        for key in ("textures", "constraints"):
            value = description.get(key)
            if isinstance(value, list):
                parts.extend(value)
            elif value:
                parts.append(value)
    return " ".join(str(p) for p in parts)[:max_chars]


def reference_block(spark=None, client=None, db_path=None) -> str:
    """
    Retrieve grounding references for an ideation run and return the
    formatted block, or "" if the library is unavailable. Never raises --
    the same enhancement-not-dependency contract pitch.py keeps. This is
    the *edge* helper: call it from entry points (CLI, web routes), not
    from inside the tested generate functions, so those stay hermetic.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    query = build_reference_query(locations, spark=spark, client=client)
    if not query.strip():
        return ""

    retrieval = rag.retrieve_references(query, domain=IDEATION_DOMAINS)
    if retrieval["ok"] and retrieval["references"]:
        print(f"Grounding in {len(retrieval['references'])} retrieved reference(s)",
              file=sys.stderr)
        return rag.format_references(retrieval["references"])

    reason = retrieval.get("error", "reference library is empty")
    print(f"note: generating without references: {reason}", file=sys.stderr)
    return ""


def load_brand(brand: str) -> str:
    """
    One brand block out of prompts/brands.txt, keyed by [name]. Kept in
    a text file rather than Python so the wording is editable without
    touching code, same as brief.txt.
    """
    if brand not in preprod.BRANDS:
        raise ValueError(f"brand must be one of {preprod.BRANDS}, got {brand!r}")

    text = (PROMPTS_DIR / "brands.txt").read_text()
    marker = f"[{brand}]"
    if marker not in text:
        raise ValueError(f"no [{brand}] block in prompts/brands.txt")

    block = text.split(marker, 1)[1]
    # stop at the next [block] header, if any
    for line in block.splitlines():
        if line.startswith("[") and line.rstrip().endswith("]"):
            block = block.split(line, 1)[0]
            break
    return block.strip()


def format_locations(locations: list) -> str:
    """The described spaces, as the model sees them."""
    lines = []
    for loc in locations:
        description = loc.get("description") or {}
        lines.append(f"- {loc['name']}: {description.get('space', 'no description')}")
        for key in ("light_sources", "textures", "angles"):
            values = description.get(key)
            if values:
                lines.append(f"    {key.replace('_', ' ')}: {', '.join(values)}")
        if description.get("constraints"):
            lines.append(f"    constraints: {description['constraints']}")
    return "\n".join(lines)


POV_ON = ('- Camera B ("ACTION5"): DJI Osmo Action 5 Pro, for POV / body-mount\n'
          "  shots.")
POV_OFF = "- No POV camera available this shoot — BMPCC only."


def apply_pov(template: str, use_pov: bool) -> str:
    """
    The POV camera is a real physical constraint, so it has to reach
    both the prompt and the validator. Off means the model is never
    offered ACTION5 and never told it is a legal value.
    """
    return (
        template
        .replace("{pov}", POV_ON if use_pov else POV_OFF)
        .replace("{cam_rule}", '- Every shot\'s "cam" is exactly '
                 + ("BMPCC or ACTION5." if use_pov else "BMPCC."))
        .replace("{cam_values}", '"BMPCC or ACTION5"' if use_pov else '"BMPCC"')
    )


def build_concept_prompt(locations: list, brand: str, client=None, spark=None,
                         use_pov: bool = True, references: str = "") -> str:
    template = apply_pov((PROMPTS_DIR / "concept_prompt.txt").read_text(), use_pov)
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{spark}", f"CREATIVE SPARK FROM THE FILMMAKER: {spark}" if spark else "")
        .replace("{references}", references or NO_REFERENCES_NOTE)
    )


def build_ideas_prompt(locations: list, brand: str, client=None, spark=None,
                       count: int = DEFAULT_IDEA_COUNT, references: str = "") -> str:
    template = (PROMPTS_DIR / "concept_ideas_prompt.txt").read_text()
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{spark}", f"CREATIVE SPARK FROM THE FILMMAKER: {spark}" if spark else "")
        .replace("{count}", str(count))
        .replace("{references}", references or NO_REFERENCES_NOTE)
    )


def parse_ideas_response(text: str) -> list:
    """Stage one's testable seam: raw model text -> a list of ideas."""
    data = json.loads(strip_fences(text))
    ideas = data.get("ideas", data if isinstance(data, list) else [])
    if not ideas:
        raise ValueError("no ideas in response")
    for i, idea in enumerate(ideas, start=1):
        if not (idea.get("title") or "").strip():
            raise ValueError(f"idea {i} has no title")
    return ideas


def build_shotlist_prompt(locations: list, brand: str, client, concept: dict,
                          use_pov: bool = True) -> str:
    template = apply_pov((PROMPTS_DIR / "shotlist_prompt.txt").read_text(), use_pov)
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{title}", concept.get("title") or "")
        .replace("{hook}", concept.get("hook") or "")
        .replace("{logline}", concept.get("logline") or "")
    )


def parse_plan_response(text: str) -> dict:
    """Stage two's testable seam: raw model text -> the shot plan."""
    data = json.loads(strip_fences(text))
    plan = data.get("plan", data)
    if not plan.get("shots"):
        raise ValueError("plan has no shots")
    return plan


def generate_concept_ideas(brand: str, client=None, spark=None, gemini_client=None,
                           model: str = MODEL, count: int = DEFAULT_IDEA_COUNT,
                           use_pov: bool = True, db_path=None,
                           references: str = "") -> dict:
    """
    Stage one: several cheap ideas in a single call, so they can be
    varied against each other rather than rolled independently. No shot
    lists -- an idea you discard shouldn't have cost shot detail.

    `references` is passed in already retrieved, by the caller at the
    edge (reference_block), so this stays pure with respect to the
    reference library and testable without a store.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    if not locations:
        # Grounding is an enhancement, never a gate -- the same degrade
        # contract reference_block keeps when the library is down.
        print(NO_LOCATIONS_NOTE, file=sys.stderr)

    prompt = build_ideas_prompt(locations, brand, client, spark, count,
                                references=references)
    ideas = parse_ideas_response(generate_with_retry(gemini_client, model, prompt))

    concept_ids = preprod.save_concept_ideas(
        ideas, brand=brand, client=client, spark=spark,
        prompt_template=prompt, use_pov=use_pov, **kwargs,
    )
    return {"concept_ids": concept_ids, "ideas": ideas}


def generate_shot_list(concept_id: int, gemini_client=None, model: str = MODEL,
                       use_pov=None, db_path=None) -> dict:
    """
    Stage two: the shot list for an idea you chose. This call is the
    pick -- bothering to plan a shoot for an idea is the signal
    shortlist_rate measures.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    concept = preprod.get_concept(concept_id, **kwargs)
    if concept is None:
        raise ValueError(f"no concept with id {concept_id}")

    # The camera choice was made when the idea was generated; planning
    # happens later, so it has to come from the concept rather than a
    # default that quietly turns the camera back on.
    if use_pov is None:
        use_pov = concept.get("use_pov", True)

    locations = preprod.list_locations(**kwargs)
    if not locations:
        print(NO_LOCATIONS_NOTE, file=sys.stderr)

    prompt = build_shotlist_prompt(locations, concept["brand"], concept.get("client"),
                                   concept, use_pov=use_pov)
    plan = parse_plan_response(generate_with_retry(gemini_client, model, prompt))

    location_names = [loc["name"] for loc in locations]
    warnings = validate_concept(plan, location_names, use_pov=use_pov)

    used = {shot.get("location") for shot in plan.get("shots") or []}
    location_ids = [loc["id"] for loc in locations if loc["name"] in used]

    preprod.update_concept_shots(concept_id, plan, location_ids=location_ids,
                                 warnings=warnings, **kwargs)
    return {"concept_id": concept_id, "plan": plan, "warnings": warnings}


def parse_concept_response(text: str) -> dict:
    """The testable seam: raw model text -> the concept dict."""
    data = json.loads(strip_fences(text))
    concept = data.get("concept", data)
    if not concept.get("title"):
        raise ValueError("concept has no title")
    return concept


def validate_concept(concept: dict, location_names: list, use_pov: bool = True) -> list:
    """
    Check the model's output against what the prompt asked for and
    return visible warnings. Nothing here blocks: a concept that breaks
    a rule is still saved with its warnings attached, because it is
    worth looking at and deciding on. Grounding shapes the generation;
    a mismatch is advice to the human, not a gate.

    A shot's source is CAMERA (you capture it; `cam` names the body) or
    AI (a platform generates it; `tool` + `prompt` say how). No source
    means CAMERA -- every concept written before the de-cap.
    """
    warnings = []
    shots = concept.get("shots") or []

    if not shots:
        warnings.append("concept has no shots")

    for i, shot in enumerate(shots, start=1):
        n = shot.get("n", i)
        if shot.get("type") not in SHOT_TYPES:
            warnings.append(f"shot {n}: type must be one of {SHOT_TYPES}, got {shot.get('type')!r}")

        source = shot.get("source", "CAMERA")
        if source not in SHOT_SOURCES:
            warnings.append(
                f"shot {n}: source must be one of {SHOT_SOURCES}, got {source!r}"
            )
        elif source == "AI":
            # cam names a physical body; an AI shot doesn't have one.
            if shot.get("tool") not in AI_TOOLS:
                warnings.append(
                    f"shot {n}: AI tool must be one of {AI_TOOLS}, got {shot.get('tool')!r}"
                )
            if not (shot.get("prompt") or "").strip():
                warnings.append(f"shot {n}: AI shot has no generation prompt")
        else:
            allowed_cams = CAMERAS if use_pov else ("BMPCC",)
            if shot.get("cam") not in allowed_cams:
                warnings.append(
                    f"shot {n}: cam must be one of {allowed_cams}, got {shot.get('cam')!r}"
                )

        location = shot.get("location")
        if location not in location_names:
            warnings.append(f"shot {n}: unknown location {location!r} -- not a described space")

    # legacy shape: one concept-level ai dict instead of per-shot source
    ai = concept.get("ai")
    if ai and ai.get("tool") not in AI_TOOLS:
        warnings.append(f"ai tool must be one of {AI_TOOLS}, got {ai.get('tool')!r}")

    return warnings


def generate_concept(brand: str, client=None, spark=None, gemini_client=None,
                     model: str = MODEL, use_pov: bool = True, db_path=None,
                     references: str = "") -> dict:
    """
    One concept, grounded in the described locations, validated and
    saved. Returns {"concept_id", "concept", "warnings"}.

    Like generate_concept_ideas, `references` arrives already retrieved
    from the edge rather than being fetched here.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    if not locations:
        print(NO_LOCATIONS_NOTE, file=sys.stderr)

    prompt = build_concept_prompt(locations, brand, client, spark, use_pov=use_pov,
                                  references=references)
    concept = parse_concept_response(generate_with_retry(gemini_client, model, prompt))

    location_names = [loc["name"] for loc in locations]
    warnings = validate_concept(concept, location_names, use_pov=use_pov)

    used = {shot.get("location") for shot in concept.get("shots") or []}
    location_ids = [loc["id"] for loc in locations if loc["name"] in used]

    concept_id = preprod.save_concept(
        concept, brand=brand, client=client, spark=spark,
        location_ids=location_ids, prompt_template=prompt,
        warnings=warnings, use_pov=use_pov, **kwargs,
    )
    return {"concept_id": concept_id, "concept": concept, "warnings": warnings}


def format_concept_as_text(concept: dict, warnings=None) -> str:
    """Readable on the day, next to the camera."""
    lines = [
        concept.get("title", "untitled"),
        f"  {concept.get('duration', '?')} — {concept.get('logline', '')}",
        f"  HOOK: {concept.get('hook', '')}",
        "",
    ]
    for shot in concept.get("shots") or []:
        lines.append(
            f"  {shot.get('n', '?'):>2}. [{shot.get('type', '?')}/{shot.get('cam', '?')}] "
            f"{shot.get('location', '?')}"
        )
        lines.append(f"      {shot.get('desc', '')}")
        if shot.get("light"):
            lines.append(f"      light: {shot['light']}")

    ai = concept.get("ai")
    if ai:
        lines += ["", f"  AI [{ai.get('tool', '?')}]: {ai.get('technique', '')}",
                  f"      {ai.get('prompt', '')}"]
    if concept.get("edit"):
        lines += ["", f"  EDIT: {concept['edit']}"]
    if concept.get("grade"):
        lines.append(f"  GRADE: {concept['grade']}")
    for warning in warnings or []:
        lines.append(f"  WARNING: {warning}")
    return "\n".join(lines)


def main(db_path=None):
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Generate shoot concepts grounded in your described locations. "
                    "Two stages: ideas first, then a shot list for the ones you pick."
    )
    parser.add_argument("--brand", choices=preprod.BRANDS, default="antihero")
    parser.add_argument("--client", default=None, help="client or spec type (zeropage only)")
    parser.add_argument("--spark", default=None, help="a direction to build the ideas around")
    parser.add_argument("--count", type=int, default=DEFAULT_IDEA_COUNT,
                        help="how many ideas to generate (one call regardless)")
    parser.add_argument("--shotlist", type=int, default=None, metavar="CONCEPT_ID",
                        help="skip idea generation and plan the shoot for this concept id")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    path = db_path if db_path is not None else DB_PATH
    init_db(path=path)
    preprod.init(path=path)

    gemini_client = genai.Client(api_key=api_key)

    if args.shotlist is not None:
        try:
            result = generate_shot_list(
                args.shotlist, gemini_client=gemini_client, db_path=path,
            )
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

        concept = preprod.get_concept(args.shotlist, path=path)
        print(f"\nConcept {args.shotlist}")
        print(format_concept_as_text(concept, result["warnings"]))
        return

    references = reference_block(spark=args.spark, client=args.client, db_path=path)
    try:
        result = generate_concept_ideas(
            brand=args.brand, client=args.client, spark=args.spark,
            gemini_client=gemini_client, count=args.count, db_path=path,
            references=references,
        )
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    print(f"\n{len(result['ideas'])} ideas — pick the ones worth shooting:\n")
    for concept_id, idea in zip(result["concept_ids"], result["ideas"]):
        print(f"  [{concept_id}] {idea['title']}")
        print(f"       hook: {idea.get('hook', '')}")
        print(f"       {idea.get('logline', '')}")
        if idea.get("why"):
            print(f"       ({idea['why']})")
        print()

    print("Plan a shoot for one:")
    print(f"  venv/bin/python -m src.shootgen --shotlist {result['concept_ids'][0]}")


if __name__ == "__main__":
    main()

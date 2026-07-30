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

from . import preprod
from .db import DB_PATH, init_db
from .gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

MODEL = "gemini-3-flash-preview"

MAX_SHOTS = 6
SHOT_TYPES = ("CHARACTER", "BROLL")
CAMERAS = ("BMPCC", "ACTION5")
AI_TOOLS = ("KLING", "RUNWAY")


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


def build_concept_prompt(locations: list, brand: str, client=None, spark=None) -> str:
    template = (PROMPTS_DIR / "concept_prompt.txt").read_text()
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{spark}", f"CREATIVE SPARK FROM THE FILMMAKER: {spark}" if spark else "")
    )


def parse_concept_response(text: str) -> dict:
    """The testable seam: raw model text -> the concept dict."""
    data = json.loads(strip_fences(text))
    concept = data.get("concept", data)
    if not concept.get("title"):
        raise ValueError("concept has no title")
    return concept


def validate_concept(concept: dict, location_names: list) -> list:
    """
    Check the model's output against the rules the prompt asked for.
    Returns warnings; an empty list means it's clean.

    The location check is the one that matters: a concept set in a room
    that doesn't exist defeats the entire point of describing real
    spaces first.
    """
    warnings = []
    shots = concept.get("shots") or []

    if not shots:
        warnings.append("concept has no shots")
    if len(shots) > MAX_SHOTS:
        warnings.append(f"at most {MAX_SHOTS} shots, got {len(shots)}")

    for i, shot in enumerate(shots, start=1):
        n = shot.get("n", i)
        if shot.get("type") not in SHOT_TYPES:
            warnings.append(f"shot {n}: type must be one of {SHOT_TYPES}, got {shot.get('type')!r}")
        if shot.get("cam") not in CAMERAS:
            warnings.append(f"shot {n}: cam must be one of {CAMERAS}, got {shot.get('cam')!r}")
        location = shot.get("location")
        if location not in location_names:
            warnings.append(f"shot {n}: unknown location {location!r} -- not a described space")

    ai = concept.get("ai")
    if ai and ai.get("tool") not in AI_TOOLS:
        warnings.append(f"ai tool must be one of {AI_TOOLS}, got {ai.get('tool')!r}")

    return warnings


def generate_concept(brand: str, client=None, spark=None, gemini_client=None,
                     model: str = MODEL, db_path=None) -> dict:
    """
    One concept, grounded in the described locations, validated and
    saved. Returns {"concept_id", "concept", "warnings"}.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    if not locations:
        raise ValueError(
            "no locations described yet -- run `python -m src.locations` first"
        )

    prompt = build_concept_prompt(locations, brand, client, spark)
    concept = parse_concept_response(generate_with_retry(gemini_client, model, prompt))

    location_names = [loc["name"] for loc in locations]
    warnings = validate_concept(concept, location_names)

    used = {shot.get("location") for shot in concept.get("shots") or []}
    location_ids = [loc["id"] for loc in locations if loc["name"] in used]

    concept_id = preprod.save_concept(
        concept, brand=brand, client=client, spark=spark,
        location_ids=location_ids, prompt_template=prompt, **kwargs,
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
        description="Generate a shoot concept grounded in your described locations."
    )
    parser.add_argument("--brand", choices=preprod.BRANDS, default="antihero")
    parser.add_argument("--client", default=None, help="client or spec type (zeropage only)")
    parser.add_argument("--spark", default=None, help="a direction to build the concept around")
    parser.add_argument("--count", type=int, default=1, help="how many concepts to generate")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    path = db_path if db_path is not None else DB_PATH
    init_db(path=path)
    preprod.init(path=path)

    gemini_client = genai.Client(api_key=api_key)
    for _ in range(args.count):
        try:
            result = generate_concept(
                brand=args.brand, client=args.client, spark=args.spark,
                gemini_client=gemini_client, db_path=path,
            )
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

        print(f"\nConcept {result['concept_id']}")
        print(format_concept_as_text(result["concept"], result["warnings"]))


if __name__ == "__main__":
    main()

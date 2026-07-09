#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "manifest.json"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PITCHES_PATH = PROJECT_ROOT / "pitches.json"
CONCEPTS_PATH = PROJECT_ROOT / "concepts.json"

MODEL = "gemini-3-flash-preview"
MIN_RUNTIME = 13
MAX_RUNTIME = 17


def load_json(path: Path):
    return json.loads(path.read_text())


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def build_prompt(manifest: list[dict], selected_pitches: list[dict]) -> str:
    brief = (PROMPTS_DIR / "brief.txt").read_text()
    settings = (PROMPTS_DIR / "settings.txt").read_text()
    template = (PROMPTS_DIR / "edit_prompt.txt").read_text()
    manifest_json = json.dumps(manifest, indent=2)
    pitches_json = json.dumps(selected_pitches, indent=2)

    return (
        template
        .replace("{brief}", brief)
        .replace("{settings}", settings)
        .replace("{manifest}", manifest_json)
        .replace("{selected_pitches}", pitches_json)
    )


def cut_field(cut: dict, *keys):
    for key in keys:
        if key in cut:
            return cut[key]
    return None


def validate_edit(edit: dict, manifest_by_name: dict) -> list[str]:
    warnings = []
    edit_list = edit.get("edit_list", [])
    total = 0.0

    for cut in edit_list:
        filename = cut_field(cut, "clip", "filename", "file")
        in_point = cut_field(cut, "in", "in_point", "start")
        out_point = cut_field(cut, "out", "out_point", "end")

        if filename not in manifest_by_name:
            warnings.append(f"unknown clip '{filename}'")
            continue
        if in_point is None or out_point is None:
            warnings.append(f"missing in/out point for '{filename}'")
            continue

        duration = manifest_by_name[filename].get("duration_seconds") or 0
        if in_point < 0 or out_point > duration or out_point <= in_point:
            warnings.append(
                f"'{filename}' cut [{in_point}, {out_point}] outside real duration ({duration}s)"
            )
        total += max(0, out_point - in_point)

    if not (MIN_RUNTIME <= total <= MAX_RUNTIME):
        warnings.append(f"total runtime {total:.1f}s outside {MIN_RUNTIME}-{MAX_RUNTIME}s window")

    return warnings


def main():
    load_dotenv()

    if len(sys.argv) < 2:
        print("Usage: python src/editgen.py <pitch-number> [pitch-number ...]", file=sys.stderr)
        sys.exit(1)

    try:
        selected_numbers = [int(n) for n in sys.argv[1:]]
    except ValueError:
        print("Pitch numbers must be integers", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY (or GEMINI_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    manifest = load_json(MANIFEST_PATH)
    manifest_by_name = {entry["filename"]: entry for entry in manifest}

    if not PITCHES_PATH.exists():
        print(f"{PITCHES_PATH} not found — run src/pitch.py first", file=sys.stderr)
        sys.exit(1)

    pitches = load_json(PITCHES_PATH)
    selected_pitches = [p for p in pitches if p["number"] in selected_numbers]
    missing = set(selected_numbers) - {p["number"] for p in selected_pitches}
    if missing:
        print(f"Pitch number(s) not found in {PITCHES_PATH}: {sorted(missing)}", file=sys.stderr)
        sys.exit(1)

    prompt = build_prompt(manifest, selected_pitches)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=MODEL, contents=prompt)

    text = strip_fences(response.text)
    edits = json.loads(text)

    for edit in edits:
        warnings = validate_edit(edit, manifest_by_name)
        existing_warnings = edit.get("warnings") or []
        edit["warnings"] = list(existing_warnings) + warnings

        cut_count = len(edit.get("edit_list", []))
        print(f"{edit.get('title')}: {cut_count} cuts")
        for w in edit["warnings"]:
            print(f"  WARNING: {w}")

    CONCEPTS_PATH.write_text(json.dumps(edits, indent=2))
    print(f"Saved {len(edits)} edits to {CONCEPTS_PATH}")


if __name__ == "__main__":
    main()

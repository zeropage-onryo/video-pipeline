#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from beat_sync import detect_beats, snap_edit_to_beats, synthetic_beats
from gemini_utils import generate_with_retry, strip_fences

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

    parser = argparse.ArgumentParser(description="Generate full edit specs for selected pitches.")
    parser.add_argument("pitch_numbers", type=int, nargs="+", help="Pitch numbers from pitches.json to edit")
    parser.add_argument(
        "--music", type=Path,
        help="Path to a music file; snaps cut transitions to the nearest detected beat",
    )
    parser.add_argument(
        "--bpm", type=float,
        help="Tempo to snap to when you don't have the audio file itself "
             "(e.g. a platform-native sound) — generates a synthetic beat grid instead",
    )
    parser.add_argument(
        "--bpm-offset", type=float, default=0.0,
        help="Seconds to the first downbeat, if not at t=0 (only used with --bpm)",
    )
    args = parser.parse_args()
    if args.music and args.bpm:
        print("Use --music or --bpm, not both", file=sys.stderr)
        sys.exit(1)
    selected_numbers = args.pitch_numbers

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
    response_text = generate_with_retry(client, MODEL, prompt)

    text = strip_fences(response_text)
    edits = json.loads(text)

    beat_times = []
    if args.music:
        if not args.music.exists():
            print(f"Music file not found: {args.music}", file=sys.stderr)
        else:
            print(f"Detecting beats in {args.music.name}...")
            beat_times = detect_beats(str(args.music))
            print(f"  found {len(beat_times)} beats")
    elif args.bpm:
        print(f"Generating a synthetic {args.bpm} BPM beat grid (offset {args.bpm_offset}s)...")
        beat_times = synthetic_beats(args.bpm, args.bpm_offset)

    for edit in edits:
        beat_warnings = snap_edit_to_beats(edit, beat_times, manifest_by_name, cut_field) if beat_times else []
        warnings = validate_edit(edit, manifest_by_name) + beat_warnings
        existing_warnings = edit.get("warnings") or []
        edit["warnings"] = list(existing_warnings) + warnings

        cut_count = len(edit.get("edit_list", []))
        synced = " (beat-synced)" if beat_times else ""
        print(f"{edit.get('title')}: {cut_count} cuts{synced}")
        for w in edit["warnings"]:
            print(f"  WARNING: {w}")

    CONCEPTS_PATH.write_text(json.dumps(edits, indent=2))
    print(f"Saved {len(edits)} edits to {CONCEPTS_PATH}")


if __name__ == "__main__":
    main()

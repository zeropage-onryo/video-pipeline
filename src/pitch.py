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

MODEL = "gemini-3-flash-preview"


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text())


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def build_prompt(manifest: list[dict]) -> str:
    brief = (PROMPTS_DIR / "brief.txt").read_text()
    settings = (PROMPTS_DIR / "settings.txt").read_text()
    template = (PROMPTS_DIR / "pitch_prompt.txt").read_text()
    manifest_json = json.dumps(manifest, indent=2)

    return (
        template
        .replace("{brief}", brief)
        .replace("{settings}", settings)
        .replace("{manifest}", manifest_json)
    )


def validate_pitches(pitches: list, manifest: list[dict]) -> None:
    filenames = [entry["filename"] for entry in manifest]
    for pitch in pitches:
        note = pitch.get("story_note", "")
        if not any(name in note for name in filenames):
            print(
                f"  warning: story {pitch.get('number')} ('{pitch.get('title')}') "
                f"doesn't clearly reference a known clip filename in its story_note",
                file=sys.stderr,
            )


def main():
    load_dotenv()

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY (or GEMINI_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest()
    prompt = build_prompt(manifest)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=MODEL, contents=prompt)

    text = strip_fences(response.text)
    pitches = json.loads(text)

    validate_pitches(pitches, manifest)

    for p in pitches:
        print(f"{p['number']}. {p['title']}")
        print(f"   {p['logline']}")
        print(f"   {p['story_note']}")
        print()

    PITCHES_PATH.write_text(json.dumps(pitches, indent=2))
    print(f"Saved {len(pitches)} pitches to {PITCHES_PATH}")


if __name__ == "__main__":
    main()

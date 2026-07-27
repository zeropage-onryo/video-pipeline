#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "manifest.json"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PITCHES_PATH = PROJECT_ROOT / "pitches.json"

MODEL = "gemini-3-flash-preview"


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text())


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


CLIP_REF_PATTERN = re.compile(r"[A-Z0-9]+_\d+_C\d{3}|DJI_\d+_\d+_D")


def validate_pitches(pitches: list, manifest: list[dict]) -> None:
    base_names = {entry["filename"].rsplit(".", 1)[0] for entry in manifest}
    for pitch in pitches:
        note = pitch.get("story_note", "")
        refs = CLIP_REF_PATTERN.findall(note)
        if not refs:
            print(
                f"  warning: story {pitch.get('number')} ('{pitch.get('title')}') "
                f"doesn't clearly reference a known clip filename in its story_note",
                file=sys.stderr,
            )
            continue
        for ref in refs:
            if ref not in base_names:
                print(
                    f"  warning: story {pitch.get('number')} ('{pitch.get('title')}') "
                    f"references '{ref}', which doesn't match any clip in the manifest",
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
    response_text = generate_with_retry(client, MODEL, prompt)

    text = strip_fences(response_text)
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

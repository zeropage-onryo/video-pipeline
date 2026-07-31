#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from . import db, rag
from .gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "manifest.json"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PITCHES_PATH = PROJECT_ROOT / "pitches.json"

MODEL = "gemini-3-flash-preview"


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text())


NO_REFERENCES_NOTE = (
    "(no reference library available -- pitch from the footage alone)"
)


def build_reference_query(manifest: list[dict], max_chars: int = 6000) -> str:
    """
    The retrieval query is the footage itself: every clip's beats and
    arc joined into one text, capped so an enormous manifest doesn't
    blow the embedding input. Handles both description shapes --
    {beats, arc} from current ingests, flat strings from old ones.
    """
    parts = []
    for entry in manifest:
        description = entry.get("description")
        if isinstance(description, dict):
            parts.extend(description.get("beats") or [])
            if description.get("arc"):
                parts.append(description["arc"])
        elif isinstance(description, str):
            parts.append(description)
    return " ".join(parts)[:max_chars]


def build_prompt(manifest: list[dict], references_block: str = "") -> str:
    brief = (PROMPTS_DIR / "brief.txt").read_text()
    settings = (PROMPTS_DIR / "settings.txt").read_text()
    template = (PROMPTS_DIR / "pitch_prompt.txt").read_text()
    manifest_json = json.dumps(manifest, indent=2)

    return (
        template
        .replace("{brief}", brief)
        .replace("{settings}", settings)
        .replace("{manifest}", manifest_json)
        .replace("{references}", references_block or NO_REFERENCES_NOTE)
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


def record_pitch_run(pitches: list, manifest: list[dict], db_path=None) -> None:
    """
    Save this run to the database: the pitches, the model, how many clips
    were in the manifest, and the raw prompt/brief/settings text.

    A pick is a label -- ten pitches, a few marked good -- and it is the
    only ground truth here that doesn't require waiting for a video to be
    posted. But recording it must never be able to stop the pipeline:
    generating pitches must not depend on bookkeeping, so a database
    problem here prints a warning and nothing more.
    """
    try:
        kwargs = {"path": db_path} if db_path is not None else {}
        # A fresh clone has no data/pipeline.db. Without this the label
        # capture -- the whole point of this call -- fails to one stderr
        # line buried under the printed output.
        db.init_db(**kwargs)
        run_id = db.save_pitch_run(
            pitches,
            model=MODEL,
            clip_count=len(manifest),
            brief=(PROMPTS_DIR / "brief.txt").read_text(),
            settings=(PROMPTS_DIR / "settings.txt").read_text(),
            prompt_template=(PROMPTS_DIR / "pitch_prompt.txt").read_text(),
            **kwargs,
        )
        print(f"Recorded pitch run {run_id} in the database")
    except Exception as e:
        print(f"warning: could not record pitch run in database: {e}", file=sys.stderr)


def main(db_path=None):
    load_dotenv()

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY (or GEMINI_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest()

    # Grounding is an enhancement: a missing reference library must
    # never stop a pitch run, only be said out loud.
    retrieval = rag.retrieve_references(build_reference_query(manifest))
    if retrieval["ok"] and retrieval["references"]:
        references_block = rag.format_references(retrieval["references"])
        print(f"Grounding in {len(retrieval['references'])} retrieved reference(s)")
    else:
        references_block = ""
        reason = retrieval.get("error", "reference library is empty")
        print(f"note: pitching without references: {reason}", file=sys.stderr)

    prompt = build_prompt(manifest, references_block)

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

    record_pitch_run(pitches, manifest, db_path=db_path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from . import crag, db, rag
from .gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "manifest.json"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PITCHES_PATH = PROJECT_ROOT / "pitches.json"

MODEL = "gemini-3-flash-preview"

# Post-production pitching grounds in what the footage/brand actually is --
# never in marketing or AI-video-prompting material, which are shelves for
# other stages of the pipeline (see shootgen.py and promptgen.py) and would
# just dilute a pitch's grounding with off-topic chunks if left unscoped.
PITCH_DOMAINS = ("personal_brand", "cinematography")


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
            for beat in description.get("beats") or []:
                # ingest writes {"t": seconds, "text": "..."}; older
                # manifests and hand edits sometimes hold a bare string
                if isinstance(beat, dict):
                    text = beat.get("text")
                elif isinstance(beat, str):
                    text = beat
                else:
                    text = None
                if text:
                    parts.append(text)
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


# Bounded to one regeneration attempt for the same reason
# editgen.py's MAX_REVISE_ATTEMPTS is bounded: a batch that's still
# ungrounded after a fresh sample from the same prompt more likely
# means the reference library doesn't cover this manifest than that
# another paid attempt will fix it.
MAX_PITCH_REVISE_ATTEMPTS = 1
PITCH_FAITHFULNESS_FLOOR = 0.6


def pitches_text(pitches: list) -> str:
    return "\n".join(
        f"{p.get('title', '')}: {p.get('logline', '')} {p.get('story_note', '')}"
        for p in pitches
    )


def revise_pitch_until_grounded(
    client, model: str, manifest: list[dict], references_block: str,
    references: list, query_used: str, pitches: list,
    max_attempts: int = MAX_PITCH_REVISE_ATTEMPTS,
) -> tuple[list, dict]:
    """
    Evaluator-optimizer loop over the whole pitch batch: the critic is
    a real faithfulness score against the retrieved references
    (src.quality.score_generation -- the same function evals/
    uses to gate CI), not the model grading its own output. Scores the
    batch as one block, not per-pitch, so this costs one extra judge
    call per attempt instead of ten.

    Returns (pitches, check) where check is
    {"checked": bool, "faithfulness": float | None, "needs_review": bool,
    "attempts": int, "reason": str | None}. A batch still below
    PITCH_FAITHFULNESS_FLOOR after max_attempts comes back with
    needs_review=True -- this escalates to you in the printed output,
    it does not keep spending money chasing a score.
    """
    if not references:
        return pitches, {"checked": False, "reason": "no references to check faithfulness against"}

    from . import quality  # deepeval is an eval-only dependency; only import it if this runs

    retrieval_context = [r["chunk"] for r in references]
    current = pitches
    attempts = 0

    while True:
        attempts += 1
        try:
            result = quality.score_generation(
                query=query_used, actual_output=pitches_text(current),
                retrieval_context=retrieval_context,
            )
        except Exception as e:
            return current, {"checked": False, "reason": f"quality scoring failed: {e}"}

        faithfulness = result["scores"]["faithfulness"]
        if faithfulness >= PITCH_FAITHFULNESS_FLOOR or attempts >= max_attempts:
            return current, {
                "checked": True, "faithfulness": faithfulness,
                "needs_review": faithfulness < PITCH_FAITHFULNESS_FLOOR,
                "attempts": attempts,
                "reason": None if faithfulness >= PITCH_FAITHFULNESS_FLOOR
                else result["reasons"].get("faithfulness"),
            }

        # A fresh sample from the same grounded prompt, not a targeted
        # fix -- faithfulness reasons are prose explaining what claim
        # wasn't supported, not a structural diff like validate_edit's
        # warnings, so there's no specific defect to point a revision
        # prompt at the way editgen.py's revise_until_valid can.
        response_text = generate_with_retry(client, model, build_prompt(manifest, references_block))
        current = json.loads(strip_fences(response_text))


def main(db_path=None, self_correct=False):
    load_dotenv()

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY (or GEMINI_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest()
    client = genai.Client(api_key=api_key)

    # Grounding is an enhancement: a missing reference library must
    # never stop a pitch run, only be said out loud. retrieve_with_crag
    # grades the retrieved set and rewrites the query once if it's weak
    # -- same never-raises contract as rag.retrieve_references.
    query = build_reference_query(manifest)
    retrieval = crag.retrieve_with_crag(query, client, MODEL, domain=PITCH_DOMAINS)
    references = retrieval.get("references") or []
    if retrieval["ok"] and references:
        references_block = rag.format_references(references)
        rewrite_note = " (query rewritten after a weak first retrieval)" if retrieval.get("rewritten_query") else ""
        print(f"Grounding in {len(references)} retrieved reference(s){rewrite_note}")
    else:
        references_block = ""
        reason = retrieval.get("error", "reference library is empty")
        print(f"note: pitching without references: {reason}", file=sys.stderr)

    prompt = build_prompt(manifest, references_block)
    response_text = generate_with_retry(client, MODEL, prompt)

    text = strip_fences(response_text)
    pitches = json.loads(text)

    if self_correct:
        pitches, check = revise_pitch_until_grounded(
            client, MODEL, manifest, references_block, references, query, pitches
        )
        if check.get("checked"):
            if check["needs_review"]:
                print(
                    f"note: pitch batch faithfulness {check['faithfulness']:.2f} is below the "
                    f"{PITCH_FAITHFULNESS_FLOOR} floor after {check['attempts']} attempt(s) -- "
                    f"needs_review: {check['reason']}",
                    file=sys.stderr,
                )
            else:
                print(f"Faithfulness check passed: {check['faithfulness']:.2f}")
        else:
            print(f"note: self-correction skipped: {check.get('reason')}", file=sys.stderr)

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
    parser = argparse.ArgumentParser(
        description="Generate pitches grounded in the footage manifest and reference library."
    )
    parser.add_argument(
        "--self-correct", action="store_true",
        help="grade the pitch batch's faithfulness to retrieved references and regenerate once "
             "if it's weak -- costs extra judge-model calls and needs deepeval installed "
             "(pip install -r evals/requirements.txt); see src/quality.py",
    )
    args = parser.parse_args()
    main(self_correct=args.self_correct)

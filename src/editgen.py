#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from . import db
from .gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "manifest.json"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PITCHES_PATH = PROJECT_ROOT / "pitches.json"
CONCEPTS_PATH = PROJECT_ROOT / "concepts.json"

MODEL = "gemini-3-flash-preview"
MIN_RUNTIME = 13
MAX_RUNTIME = 17

# The self-correction loop below is bounded, not open-ended: each retry is
# a paid Gemini call, and an edit that's still broken after a couple of
# tries is more likely fighting a real footage gap than a fixable mistake.
# At that point the loop should stop and hand the warnings to Mike rather
# than keep spending money chasing them.
MAX_REVISE_ATTEMPTS = 2


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


def build_revision_prompt(pitch: dict, manifest: list[dict], edit: dict, warnings: list[str]) -> str:
    """
    The revise half of the level-3 loop: same grounding as the original
    generation (brand, locked settings, footage library) plus the specific
    story it's still working from, the broken edit itself, and the exact
    problems validate_edit found -- so the model is fixing named defects,
    not guessing what's wrong from scratch.
    """
    brief = (PROMPTS_DIR / "brief.txt").read_text()
    settings = (PROMPTS_DIR / "settings.txt").read_text()
    template = (PROMPTS_DIR / "edit_revise_prompt.txt").read_text()
    manifest_json = json.dumps(manifest, indent=2)
    pitch_json = json.dumps(pitch, indent=2)
    edit_json = json.dumps(edit, indent=2)
    warnings_block = "\n".join(f"- {w}" for w in warnings)

    return (
        template
        .replace("{brief}", brief)
        .replace("{settings}", settings)
        .replace("{manifest}", manifest_json)
        .replace("{pitch}", pitch_json)
        .replace("{previous_edit}", edit_json)
        .replace("{warnings}", warnings_block)
    )


def cut_field(cut: dict, *keys):
    for key in keys:
        if key in cut:
            return cut[key]
    return None


def validate_edit(edit: dict, manifest_by_name: dict) -> list[str]:
    """
    Any edit_list entry may be a generative slot ("source": "generate")
    instead of a real clip -- real footage and AI clips are co-inputs
    to the same cut, with no per-edit ceiling. A generative slot is
    exempt from the unknown-clip check, but everything else about it is
    still advised on: it needs a shot description and sane in/out
    points, and it still counts toward total runtime, since the
    generated clip has to fit the cut like any other.

    Everything returned here is advisory -- visible warnings the human
    weighs, never a gate. The in/out-inside-duration and runtime checks
    are kept because they catch genuinely broken cuts, not because a
    cut "doesn't count" until it passes.
    """
    warnings = []
    edit_list = edit.get("edit_list", [])
    total = 0.0

    for cut in edit_list:
        is_generative = cut.get("source") == "generate"
        filename = cut_field(cut, "clip", "filename", "file")
        in_point = cut_field(cut, "in", "in_point", "start")
        out_point = cut_field(cut, "out", "out_point", "end")

        if is_generative:
            description = cut_field(cut, "description")
            if not description or not str(description).strip():
                warnings.append("generative slot is missing a shot description")
        elif filename not in manifest_by_name:
            warnings.append(f"unknown clip '{filename}'")
            continue

        if in_point is None or out_point is None:
            warnings.append(f"missing in/out point for '{filename or 'generative slot'}'")
            continue

        # The model sometimes returns timecode strings ("0:02"). Raising
        # here would discard the whole generation, since concepts.json is
        # written after this loop -- so it's a warning like any other.
        try:
            in_point = float(in_point)
            out_point = float(out_point)
        except (TypeError, ValueError):
            warnings.append(
                f"'{filename or 'generative slot'}' in/out is not a number: "
                f"{in_point!r}, {out_point!r}"
            )
            continue

        if is_generative:
            if in_point < 0 or out_point <= in_point:
                warnings.append(f"generative slot cut [{in_point}, {out_point}] is invalid")
        else:
            duration = manifest_by_name[filename].get("duration_seconds") or 0
            if in_point < 0 or out_point > duration or out_point <= in_point:
                warnings.append(
                    f"'{filename}' cut [{in_point}, {out_point}] outside real duration ({duration}s)"
                )
        total += max(0, out_point - in_point)

    if not (MIN_RUNTIME <= total <= MAX_RUNTIME):
        warnings.append(f"total runtime {total:.1f}s outside {MIN_RUNTIME}-{MAX_RUNTIME}s window")

    return warnings


def format_edit_as_text(edit: dict) -> str:
    """
    Render one edit's cut list as plain text: clip, in, out, duration,
    running total. concepts.json is machine-readable JSON; this is what
    you read yourself, working beside Resolve.
    """
    lines = [edit.get("title", "untitled")]
    total = 0.0

    for cut in edit.get("edit_list", []):
        filename = cut_field(cut, "clip", "filename", "file") or "?"
        in_point = cut_field(cut, "in", "in_point", "start")
        out_point = cut_field(cut, "out", "out_point", "end")

        if in_point is None or out_point is None:
            lines.append(f"  {filename:<28} in ?       out ?       dur  ?    total {total:6.2f}s")
            continue

        duration = out_point - in_point
        total += duration
        lines.append(
            f"  {filename:<28} in {in_point:7.2f}  out {out_point:7.2f}  "
            f"dur {duration:5.2f}s  total {total:6.2f}s"
        )

    return "\n".join(lines)


def record_selection(run_id, numbers: list, db_path=None) -> None:
    """
    Mark these pitch numbers as selected against a pitch run. run_id
    resolves to the most recent run in the database if not given
    explicitly -- the common case of editing right after the pitch run
    that produced these numbers.

    A cut list is already saved to concepts.json by the time this runs;
    a database problem here must not undo that. It prints a warning and
    nothing more.
    """
    try:
        kwargs = {"path": db_path} if db_path is not None else {}
        # A fresh clone has no data/pipeline.db. Without this the label
        # capture -- the whole point of this call -- fails to one stderr
        # line buried under the printed output.
        db.init_db(**kwargs)
        resolved_run_id = run_id
        if resolved_run_id is None:
            resolved_run_id = db.most_recent_run_id(**kwargs)
        if resolved_run_id is None:
            print("warning: no pitch runs recorded yet; skipping selection bookkeeping", file=sys.stderr)
            return
        updated = db.mark_selected_by_number(resolved_run_id, numbers, **kwargs)
        print(f"Marked {updated} pitch(es) selected in run {resolved_run_id}")
    except Exception as e:
        print(f"warning: could not record selection in database: {e}", file=sys.stderr)


def merge_warnings(edit: dict, generated_warnings: list[str]) -> list[str]:
    """
    Combine the model's own "warnings" field with the ones validate_edit
    generated. The model sometimes writes a single string there instead
    of a list -- wrapping it, rather than iterating it into one warning
    per character, is the whole reason this function exists.
    """
    existing = edit.get("warnings") or []
    if isinstance(existing, str):
        existing = [existing]
    return list(existing) + generated_warnings


def revise_until_valid(client, model: str, pitch: dict, manifest: list[dict],
                        manifest_by_name: dict, edit: dict,
                        max_attempts: int = MAX_REVISE_ATTEMPTS) -> tuple[dict, list[str]]:
    """
    The decide -> act -> check loop: validate_edit is the check, a fresh
    Gemini call scoped to just the named problems is the action, and it
    repeats until the edit passes clean or the attempt budget runs out.

    A revision is only kept if it's not worse than what came before --
    the model can trade one problem for another instead of actually
    fixing it, and this loop must not let that regression through
    silently just because it happened on the "fixed" pass. If a
    response can't even be parsed as JSON, that attempt is discarded
    and the best edit found so far is kept; a malformed revision is a
    failed attempt, not grounds to lose the last good edit.

    Returns the best (edit, warnings) pair found, same contract as
    validate_edit alone would have given the caller -- callers that
    don't want the loop can still call validate_edit directly.
    """
    best_edit, best_warnings = edit, validate_edit(edit, manifest_by_name)
    attempts = 0

    while best_warnings and attempts < max_attempts:
        attempts += 1
        prompt = build_revision_prompt(pitch, manifest, best_edit, best_warnings)
        response_text = generate_with_retry(client, model, prompt)
        try:
            candidate = json.loads(strip_fences(response_text))
        except json.JSONDecodeError:
            continue  # unusable response; try again if attempts remain

        candidate_warnings = validate_edit(candidate, manifest_by_name)
        if len(candidate_warnings) <= len(best_warnings):
            best_edit, best_warnings = candidate, candidate_warnings

    best_edit["revision_attempts"] = attempts
    return best_edit, best_warnings


def main(db_path=None):
    load_dotenv()

    parser = argparse.ArgumentParser(description="Generate full edit specs for selected pitches.")
    parser.add_argument("pitch_numbers", type=int, nargs="+", help="Pitch numbers from pitches.json to edit")
    parser.add_argument(
        "--print", dest="print_text", action="store_true",
        help="Also render each edit's cut list as plain text, to read beside Resolve",
    )
    parser.add_argument(
        "--run-id", type=int, default=None,
        help="pitch_runs id to mark these numbers selected against; "
             "defaults to the most recent run",
    )
    args = parser.parse_args()
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

    # edit_prompt.txt asks for "the full edit" per approved story, in the
    # order selected_pitches was given -- so edits[i] is expected to be
    # the cut for selected_pitches[i]. That pairing only holds when the
    # counts match; if the model dropped or added one, revision has no
    # story to ground itself in, so it's skipped rather than guessed at.
    pitches_for_edits = selected_pitches if len(edits) == len(selected_pitches) else None
    if pitches_for_edits is None:
        print(
            f"  note: model returned {len(edits)} edit(s) for {len(selected_pitches)} "
            "selected pitch(es); skipping self-correction, can't match edits to stories",
            file=sys.stderr,
        )

    for index, edit in enumerate(edits):
        warnings = validate_edit(edit, manifest_by_name)
        if warnings and pitches_for_edits is not None:
            edit, warnings = revise_until_valid(
                client, MODEL, pitches_for_edits[index], manifest, manifest_by_name, edit
            )
            edits[index] = edit
        edit["warnings"] = merge_warnings(edit, warnings)

        cut_count = len(edit.get("edit_list", []))
        attempts = edit.get("revision_attempts", 0)
        attempts_note = f", {attempts} revision attempt(s)" if attempts else ""
        print(f"{edit.get('title')}: {cut_count} cuts{attempts_note}")
        for w in edit["warnings"]:
            print(f"  WARNING: {w}")
        if args.print_text:
            print(format_edit_as_text(edit))

    CONCEPTS_PATH.write_text(json.dumps(edits, indent=2))
    print(f"Saved {len(edits)} edits to {CONCEPTS_PATH}")

    record_selection(args.run_id, selected_numbers, db_path=db_path)


if __name__ == "__main__":
    main()

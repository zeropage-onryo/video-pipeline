"""Give every scene concept a card line that FITS the card's one line.

Two kinds of row need one (2026-08-31):

  * written before either writer was asked for a card line, so the board
    falls back to preprod.derive_logline and shows a clause off the
    BEATS block -- scannable, but not a summary;
  * carrying only a `logline`, which on the scene-brief path is 2-4
    sentences of idea record on purpose (86-152 characters), so the card
    trimmed most of it away and the line read as cut off.

It writes `card_line` and NEVER touches `logline`: the idea record is
not a long card label, and squeezing one out of the other is the bug
this exists to undo.

Both get one asked off the prompt the concept already has, under the
same CARD_LINE_RULES both writers now follow. Costs one small text call
per rewritten concept and touches nothing else -- the prompt is never
rewritten, and a row whose card line already fits is skipped, so
re-running is free. Run from the project root:

    python -m ops.backfill_loglines           # report only
    python -m ops.backfill_loglines --write
"""
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from google import genai

from src import accounts, db, preprod, shootgen


def needs_one(concept: dict) -> bool:
    """One-shot scenes only -- a legacy multi-shot concept is a different
    artifact and its title/hook are already its label.

    "Needs one" means the card cannot print it whole: no card line at
    all, or one over the budget concept_summary would trim. Asking whether
    the summary got trimmed, rather than re-checking the numbers here,
    keeps ONE definition of what fits."""
    shots = concept.get("shots") or []
    if len(shots) != 1 or not (shots[0].get("prompt") or "").strip():
        return False
    card_line = (concept.get("card_line") or "").strip()
    if not card_line:
        return True
    return preprod.concept_summary(card_line).endswith("…")


def main(write: bool, account_id: Optional[int] = None) -> int:
    # A one-off ops script has no session. Without this it acts as
    # nobody, and after the tenancy backfill nobody owns no rows --
    # so it would report zero work and look like a clean run.
    if account_id is None:
        account_id = accounts.resolve_account()
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
        return 0
    client = genai.Client(api_key=api_key)

    wanted, titles = {}, {}
    for row in preprod.list_concepts(limit=1000, path=db.DB_PATH, account_id=account_id):
        concept = preprod.get_concept(row["id"], path=db.DB_PATH, account_id=account_id)
        if needs_one(concept):
            wanted[concept["id"]] = concept["shots"][0]["prompt"]
            titles[concept["id"]] = concept["title"]
    if not wanted:
        print("every concept already has a card line that fits")
        return 0

    lines = shootgen.write_card_lines(wanted, gemini_client=client)
    touched = 0
    for concept_id in wanted:
        line = lines.get(concept_id)
        if not line:                       # a row the model skipped, left as it was
            print(f"  SHOOT-{concept_id:02d} {titles[concept_id][:26]:<28} — no line came back")
            continue
        fitted = preprod.concept_summary(line)
        flag = " (still long — the card will trim it)" if fitted.endswith("…") else ""
        print(f"  SHOOT-{concept_id:02d} {titles[concept_id][:26]:<28} — {line}{flag}")
        if write:
            with preprod.connect(db.DB_PATH) as conn:
                conn.execute(
                    "UPDATE shoot_concepts SET card_line = ? "
                    "WHERE id = ? AND account_id IS ?",
                    (line, concept_id, account_id))
        touched += 1
    print(f"\n{touched} concept(s) {'updated' if write else 'would be updated'}")
    return touched


if __name__ == "__main__":
    main("--write" in sys.argv)

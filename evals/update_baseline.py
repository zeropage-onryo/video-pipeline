#!/usr/bin/env python3
"""
Seed or refresh evals/baseline_scores.json against the current
generation prompt/model. This is a deliberate action, not something
that happens as a side effect of a passing test -- a baseline that
updates itself on every green run can never catch a regression, since
it would just adopt the regression as the new normal. Run this
by hand (or as an explicit CI step gated behind a human merge) after
a generation-prompt change you've reviewed and are satisfied with,
never automatically.

Each judge-model case makes several real API calls (faithfulness,
answer relevancy, contextual precision/recall), and Gemini
occasionally returns a transient 503 under load. A single blip used
to kill the whole run and lose everything scored so far. This now
retries a failing case a few times with backoff, and writes
baseline_scores.json after every case (not just at the end) so a
re-run resumes from where it left off instead of starting over --
delete a case's entry from baseline_scores.json if you want to
force it to be rescored.

Usage:
    venv/bin/python -m evals.update_baseline
"""
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.grounded_answer import generate_grounded_answer  # noqa: E402
from src.quality import score_generation  # noqa: E402

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.json"
BASELINE_PATH = Path(__file__).resolve().parent / "baseline_scores.json"

MAX_ATTEMPTS = 4
RETRY_DELAYS = [10, 30, 60]  # seconds, between attempts 1->2, 2->3, 3->4


def _score_case_with_retry(case: dict) -> dict:
    """Score one golden case, retrying on transient judge-model errors.
    Non-transient failures still raise after MAX_ATTEMPTS."""
    last_exc = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            actual_output = generate_grounded_answer(case["query"], case["ideal_context"])
            return score_generation(
                query=case["query"],
                actual_output=actual_output,
                retrieval_context=case["ideal_context"],
                expected_output=case["expected_output"],
                context=case["ideal_context"],
            )
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, see module docstring
            last_exc = exc
            if attempt == MAX_ATTEMPTS:
                raise
            delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
            print(f"  {case['id']}: attempt {attempt} failed ({exc.__class__.__name__}: {exc}) -- retrying in {delay}s")
            time.sleep(delay)
    raise last_exc  # pragma: no cover -- unreachable, loop always returns or raises


def main() -> None:
    load_dotenv()
    cases = json.loads(GOLDEN_SET_PATH.read_text())

    baseline = json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else {}
    if baseline:
        print(f"Resuming -- {len(baseline)} case(s) already scored in {BASELINE_PATH}")

    for case in cases:
        if case["id"] in baseline:
            print(f"{case['id']}: already scored, skipping")
            continue
        result = _score_case_with_retry(case)
        baseline[case["id"]] = result["scores"]
        print(f"{case['id']}: {result['scores']}")
        BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n")  # save after every case

    print(f"\nWrote baseline for {len(baseline)} case(s) to {BASELINE_PATH}")


if __name__ == "__main__":
    main()

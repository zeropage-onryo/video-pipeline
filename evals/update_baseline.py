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

Usage:
    venv/bin/python -m evals.update_baseline
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.grounded_answer import generate_grounded_answer  # noqa: E402
from src.quality import score_generation  # noqa: E402

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.json"
BASELINE_PATH = Path(__file__).resolve().parent / "baseline_scores.json"


def main() -> None:
    load_dotenv()
    cases = json.loads(GOLDEN_SET_PATH.read_text())

    baseline = {}
    for case in cases:
        actual_output = generate_grounded_answer(case["query"], case["ideal_context"])
        result = score_generation(
            query=case["query"],
            actual_output=actual_output,
            retrieval_context=case["ideal_context"],
            expected_output=case["expected_output"],
            context=case["ideal_context"],
        )
        baseline[case["id"]] = result["scores"]
        print(f"{case['id']}: {result['scores']}")

    BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n")
    print(f"\nWrote baseline for {len(baseline)} case(s) to {BASELINE_PATH}")


if __name__ == "__main__":
    main()

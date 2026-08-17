"""
The generation-side quality gate: for every case in golden_set.json,
generate a real answer from the ideal context and score it with
DeepEval's Faithfulness, AnswerRelevancy, ContextualPrecision, and
ContextualRecall metrics (the same four RAGAS popularized).

retrieval_context is fixed to each case's ideal_context rather than
pulled from a live rag.query() call on purpose: retrieval quality is
already gated separately by rag_eval.py's hit@k/MRR harness (which CI
runs against a freshly-ingested ephemeral Postgres -- see
.github/workflows/ci.yml). This suite isolates the other half of the
pipeline -- given good context, is the *generation* faithful and
relevant? -- so a bad day for the embedding model or a chunking change
can't cause a spurious failure here, and a bad generation-prompt change
can't hide behind a lucky retrieval.

Every case checks two things:
  1. An absolute floor (FLOOR) -- a sanity backstop so a baseline that
     was seeded too low can't quietly become meaningless.
  2. A regression check against evals/baseline_scores.json, if that
     case has a recorded baseline -- current score must not fall more
     than REGRESSION_TOLERANCE below it. Judge-model scoring has real
     run-to-run noise, so this is a tolerance band, not an exact
     match; see evals/update_baseline.py for how baselines get set.
"""
import json
from pathlib import Path

import pytest

from src.grounded_answer import generate_grounded_answer
from src.quality import score_generation

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.json"
BASELINE_PATH = Path(__file__).resolve().parent / "baseline_scores.json"

FLOOR = 0.6
REGRESSION_TOLERANCE = 0.2

GOLDEN_CASES = json.loads(GOLDEN_SET_PATH.read_text())
BASELINE = json.loads(BASELINE_PATH.read_text())


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c["id"])
def test_generation_is_faithful_and_relevant(case):
    actual_output = generate_grounded_answer(case["query"], case["ideal_context"])

    result = score_generation(
        query=case["query"],
        actual_output=actual_output,
        retrieval_context=case["ideal_context"],
        expected_output=case["expected_output"],
        context=case["ideal_context"],
    )
    scores = result["scores"]
    baseline_for_case = BASELINE.get(case["id"], {})

    failures = []
    for metric, score in scores.items():
        if score is None:
            continue
        if score < FLOOR:
            failures.append(
                f"{metric}={score:.2f} is below the {FLOOR} floor "
                f"(reason: {result['reasons'].get(metric)})"
            )
        baseline_score = baseline_for_case.get(metric)
        if baseline_score is not None and score < baseline_score - REGRESSION_TOLERANCE:
            failures.append(
                f"{metric}={score:.2f} regressed more than {REGRESSION_TOLERANCE} "
                f"below baseline {baseline_score:.2f} "
                f"(reason: {result['reasons'].get(metric)})"
            )

    assert not failures, (
        f"case '{case['id']}' failed quality gate for query {case['query']!r}:\n"
        f"actual_output: {actual_output!r}\n" + "\n".join(f"  - {f}" for f in failures)
    )


def test_every_golden_case_has_a_baseline():
    """
    A case with no baseline entry only gets the absolute-floor check
    above, not a regression check -- silent for one run, easy to miss.
    This turns "no baseline yet" into a visible, actionable failure
    instead: run `python -m evals.update_baseline` and commit the
    result once you're satisfied with the current generation quality.
    """
    missing = [c["id"] for c in GOLDEN_CASES if c["id"] not in BASELINE]
    assert not missing, (
        f"{len(missing)} golden case(s) have no recorded baseline: {missing}. "
        "Run `python -m evals.update_baseline` and commit evals/baseline_scores.json."
    )

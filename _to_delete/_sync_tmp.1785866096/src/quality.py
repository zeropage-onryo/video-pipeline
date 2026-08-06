"""
Shared answer-quality scoring: faithfulness (does the generated text
only claim what the retrieved context actually supports?) and answer
relevancy, via DeepEval's LLM-judge metrics running on the same Gemini
models the rest of this pipeline already uses. Contextual precision
and recall are the same idea applied to the retrieved chunks
themselves, and only run when a labeled "ideal" answer/context is
available -- they're defined relative to a golden case, not to an
arbitrary runtime call.

One scorer, two callers, on purpose: evals/test_generation_quality.py
uses it to gate CI against a checked-in golden set, and pitch.py's
self-correction loop (see revise_pitch_until_grounded) uses the exact
same function to grade a real generation before deciding whether to
retry. A runtime critic that "looks good" by a different yardstick
than the CI gate would defeat the point of grounding it in a real
signal -- the whole reason this isn't a second model just asked "is
this good?" is that it's the *same* measurement everywhere.

deepeval is imported lazily inside score_generation, not at module
level, so importing this module (or pitch.py, which imports it for
the optional self-correction path) doesn't require deepeval installed
unless a caller actually asks for a score. Most pitch.py runs never
touch this file's contents.

This raises on judge-model failure rather than degrading gracefully --
unlike rag.retrieve_references, a broken score here has no sensible
"ungrounded" fallback, so it's the caller's job to decide what a
failed measurement means (the CI gate should fail loudly; pitch.py's
self-correction wrapper catches it and skips the retry rather than
blocking a pitch run over a judge-model hiccup).
"""
import os
from typing import Optional

DEFAULT_MODEL = "gemini-3-flash-preview"


def _judge_model(model: str = DEFAULT_MODEL):
    from deepeval.models import GeminiModel

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    return GeminiModel(model=model, api_key=api_key)


def score_generation(
    query: str,
    actual_output: str,
    retrieval_context: list,
    expected_output: Optional[str] = None,
    context: Optional[list] = None,
    judge_model: str = DEFAULT_MODEL,
) -> dict:
    """
    Faithfulness and answer relevancy always run -- they only need the
    query, the generated answer, and what was retrieved. Contextual
    precision/recall additionally need expected_output and context
    (the golden "this is what a good answer/context looks like"
    pair), so they're skipped for a runtime call that doesn't have a
    golden case to compare against.

    Returns {"faithfulness": 0..1, "answer_relevancy": 0..1,
    "contextual_precision": 0..1 | None, "contextual_recall": 0..1 | None,
    "reasons": {metric_name: str}}.
    """
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        FaithfulnessMetric,
    )
    from deepeval.test_case import LLMTestCase

    model = _judge_model(judge_model)
    test_case = LLMTestCase(
        input=query,
        actual_output=actual_output,
        retrieval_context=list(retrieval_context),
        expected_output=expected_output,
        context=list(context) if context else None,
    )

    metrics = [
        ("faithfulness", FaithfulnessMetric(model=model, include_reason=True)),
        ("answer_relevancy", AnswerRelevancyMetric(model=model, include_reason=True)),
    ]
    if expected_output and context:
        metrics += [
            ("contextual_precision", ContextualPrecisionMetric(model=model, include_reason=True)),
            ("contextual_recall", ContextualRecallMetric(model=model, include_reason=True)),
        ]

    scores: dict = {"contextual_precision": None, "contextual_recall": None}
    reasons: dict = {}
    for name, metric in metrics:
        metric.measure(test_case)
        scores[name] = metric.score
        reasons[name] = metric.reason

    return {"scores": scores, "reasons": reasons}

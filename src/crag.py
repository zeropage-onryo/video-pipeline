"""
CRAG-style retrieval grading: before a retrieved reference set gets
handed to generation, grade whether it actually looks strong enough to
ground an answer, and if it doesn't, rewrite the query once and retry
-- rather than silently generating from weak context and hoping.

Grading uses the cosine similarity score rag.query() already returns
for free (no extra call) as the primary signal: below GRADE_THRESHOLD
on the best hit means the closest thing retrieval found still isn't
very close. That's cheaper and more honest than asking an LLM "is this
relevant?" on every single call, which is its own noisy judgment call
and would double the API cost of every pitch/ideation run for a
question the retrieved score mostly already answers.

Bounded to a single rewrite attempt on purpose -- same reasoning as
editgen.py's MAX_REVISE_ATTEMPTS: an unbounded "keep rewriting until it
looks better" loop either converges immediately or burns paid calls
chasing a reference library that genuinely doesn't have the answer.
One rewrite is enough to catch a badly-phrased query; past that, the
honest outcome is "the library doesn't have this," not "keep trying."
"""
from typing import Optional

from . import rag
from .gemini_utils import generate_with_retry, strip_fences

GRADE_THRESHOLD = 0.55

REWRITE_PROMPT = """The following search query returned weak results from a reference library \
(best match score: {score:.2f} out of 1.0). Rewrite it as a single, more specific search query \
that's more likely to find relevant material -- same intent, different phrasing or added \
specificity. Return ONLY the rewritten query text, nothing else.

Original query: {query}"""


def grade_retrieval(references: list, threshold: float = GRADE_THRESHOLD) -> dict:
    """
    references: rag.query()-shaped list (each item has a "score").
    "strong" if there's at least one reference and its best score
    clears threshold; "weak" otherwise -- including nothing coming
    back at all, which is the weakest case there is.
    """
    if not references:
        return {"strong": False, "best_score": 0.0, "reason": "no references retrieved"}
    best_score = max(r.get("score", 0.0) for r in references)
    strong = best_score >= threshold
    reason = (
        f"best match score {best_score:.2f} "
        f"{'clears' if strong else 'is below'} the {threshold} floor"
    )
    return {"strong": strong, "best_score": best_score, "reason": reason}


def rewrite_query(original_query: str, best_score: float, client, model: str) -> str:
    prompt = REWRITE_PROMPT.format(score=best_score, query=original_query)
    return strip_fences(generate_with_retry(client, model, prompt)).strip()


def retrieve_with_crag(
    query: str,
    client,
    model: str,
    k: int = 5,
    domain=None,
    project: Optional[str] = None,
    db_url: Optional[str] = None,
    threshold: float = GRADE_THRESHOLD,
) -> dict:
    """
    Never raises -- same contract as rag.retrieve_references, since
    this wraps it and callers (pitch.py, shootgen.py) depend on a
    missing/weak reference library degrading a run, not stopping it.

    Returns retrieve_references' normal shape plus:
      "grade": the grade_retrieval() verdict for the references actually returned
      "rewritten_query": the query that was actually used, if a rewrite happened and helped; else None
    """
    result = rag.retrieve_references(query, k=k, db_url=db_url, domain=domain, project=project)
    if not result["ok"]:
        return {**result, "grade": None, "rewritten_query": None}

    grade = grade_retrieval(result["references"], threshold=threshold)
    if grade["strong"]:
        return {**result, "grade": grade, "rewritten_query": None}

    try:
        rewritten = rewrite_query(query, grade["best_score"], client, model)
    except Exception:
        # a failed rewrite call falls back to the original (weak) result
        # rather than losing it -- something grounded beats nothing.
        return {**result, "grade": grade, "rewritten_query": None}

    retried = rag.retrieve_references(rewritten, k=k, db_url=db_url, domain=domain, project=project)
    if not retried["ok"] or not retried["references"]:
        # the rewrite came back empty or the connection broke -- keep
        # whatever the original weak attempt found rather than nothing.
        return {**result, "grade": grade, "rewritten_query": rewritten}

    retried_grade = grade_retrieval(retried["references"], threshold=threshold)
    # only adopt the rewrite's results if they actually graded better --
    # a rewrite that finds a different but equally weak set of chunks
    # isn't worth silently swapping in for the original.
    if retried_grade["best_score"] > grade["best_score"]:
        return {**retried, "grade": retried_grade, "rewritten_query": rewritten}
    return {**result, "grade": grade, "rewritten_query": rewritten}

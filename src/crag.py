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
import re
from typing import Optional

from . import db, evalstore, rag
from .gemini_utils import generate_with_retry, strip_fences

# What promote_winners.source_key writes: "proven_results/video-42.txt".
# Matched rather than imported so this module keeps depending on nothing
# that depends on it.
_PROVEN_SOURCE = re.compile(r"^proven_results/video-(\d+)\.txt$")

# The shipped default. The effective threshold is resolved per call via
# src/settings.py (Dev Studio Settings tab -> GRADE_THRESHOLD env ->
# this constant), so tuning it no longer needs a code change.
GRADE_THRESHOLD = 0.55


def _effective_threshold() -> float:
    try:
        from . import settings
        return settings.grade_threshold()
    except Exception:
        return GRADE_THRESHOLD

REWRITE_PROMPT = """The following search query returned weak results from a reference library \
(best match score: {score:.2f} out of 1.0). Rewrite it as a single, more specific search query \
that's more likely to find relevant material -- same intent, different phrasing or added \
specificity. Return ONLY the rewritten query text, nothing else.

Original query: {query}"""


def grade_retrieval(references: list, threshold: Optional[float] = None) -> dict:
    """
    references: rag.query()-shaped list (each item has a "score").
    "strong" if there's at least one reference and its best score
    clears threshold; "weak" otherwise -- including nothing coming
    back at all, which is the weakest case there is. threshold=None
    resolves the tunable (settings -> env -> GRADE_THRESHOLD).
    """
    if threshold is None:
        threshold = _effective_threshold()
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
    return strip_fences(generate_with_retry(client, model, prompt, stage="crag")).strip()


def drop_legacy_references(references: list, dsn=None) -> list:
    """Drop proven_results docs promoted from pre-pipeline uploads.

    This is the read side of the same rule promote_winners applies when
    it writes: only posts the pipeline produced may teach the loop
    (2026-09-07). The write side stops NEW legacy winners reaching the
    shelf; this stops the ones promoted before the rule existed from
    grounding tonight's concept, without a migration that deletes
    documents somebody may still want to read on /library.

    Applied before grading on purpose -- the grade has to describe the
    references actually handed to generation, or a strong score from a
    chunk that gets thrown away would suppress the rewrite that would
    have found a usable one.

    Fails OPEN: if the pipeline database can't be reached, the
    references pass through untouched. Retrieval degrading a run and
    never stopping one is the contract every caller depends on, and an
    unreachable database is not a reason to generate ungrounded.
    """
    if not db.excludes_legacy(False):   # ZEROPAGE_LEARN_FROM_LEGACY=1
        return references
    by_source = {}
    for ref in references:
        m = _PROVEN_SOURCE.match((ref.get("source") or "").strip())
        if m:
            by_source[(ref.get("source") or "").strip()] = int(m.group(1))
    if not by_source:
        return references
    try:
        with db.connect(dsn) as conn:
            rows = conn.execute(
                "SELECT id FROM videos WHERE legacy AND id = ANY(%s)",
                (sorted(set(by_source.values())),),
            ).fetchall()
        legacy_ids = {row["id"] for row in rows}
    except Exception:
        return references
    dropped = {src for src, vid in by_source.items() if vid in legacy_ids}
    if not dropped:
        return references
    return [r for r in references
            if (r.get("source") or "").strip() not in dropped]


def retrieve_with_crag(
    query: str,
    client,
    model: str,
    k: int = 5,
    domain=None,
    project: Optional[str] = None,
    db_url: Optional[str] = None,
    threshold: Optional[float] = None,
    record_telemetry: bool = True,
    telemetry_path=None,
    prefer_project: Optional[str] = None,
) -> dict:
    """
    Never raises -- same contract as rag.retrieve_references, since
    this wraps it and callers (pitch.py, shootgen.py) depend on a
    missing/weak reference library degrading a run, not stopping it.

    Returns retrieve_references' normal shape plus:
      "grade": the grade_retrieval() verdict for the references actually returned
      "rewritten_query": the proposed retry query, when rewrite succeeded
      "telemetry": scores and decisions for observability/evaluation
    """
    if threshold is None:
        threshold = _effective_threshold()
    library = rag.reference_library_identity()
    event = {
        "original_query": query,
        "rewritten_query": None,
        "initial_score": None,
        "retry_score": None,
        "final_score": None,
        "score_change": None,
        "rewrite_attempted": False,
        "requery_triggered": False,
        "score_improved": False,
        "rewrite_adopted": False,
        "threshold": threshold,
        "domain": domain,
        "project": project,
        "prefer_project": prefer_project,
        "library_count": library["count"],
        "library_fingerprint": library["fingerprint"],
        "error": None,
    }

    def finish(response: dict) -> dict:
        if record_telemetry:
            try:
                evalstore.log_crag_retrieval(event, dsn=telemetry_path)
            except Exception:
                # Observability must never turn a usable retrieval into a
                # failed generation. The returned telemetry still exposes it.
                pass
        return {**response, "telemetry": dict(event)}

    result = rag.retrieve_references(query, k=k, db_url=db_url, domain=domain, project=project,
                                     prefer_project=prefer_project)
    if not result["ok"]:
        event["error"] = result.get("error")
        return finish({**result, "grade": None, "rewritten_query": None})

    result = {**result, "references": drop_legacy_references(result["references"])}
    grade = grade_retrieval(result["references"], threshold=threshold)
    event["initial_score"] = grade["best_score"]
    event["final_score"] = grade["best_score"]
    if grade["strong"]:
        return finish({**result, "grade": grade, "rewritten_query": None})

    event["rewrite_attempted"] = True
    try:
        rewritten = rewrite_query(query, grade["best_score"], client, model)
        event["rewritten_query"] = rewritten
    except Exception as exc:
        # a failed rewrite call falls back to the original (weak) result
        # rather than losing it -- something grounded beats nothing.
        event["error"] = f"rewrite failed: {exc}"
        return finish({**result, "grade": grade, "rewritten_query": None})

    event["requery_triggered"] = True
    retried = rag.retrieve_references(rewritten, k=k, db_url=db_url, domain=domain, project=project,
                                      prefer_project=prefer_project)
    if retried["ok"]:
        retried = {**retried,
                   "references": drop_legacy_references(retried["references"])}
    if not retried["ok"] or not retried["references"]:
        # the rewrite came back empty or the connection broke -- keep
        # whatever the original weak attempt found rather than nothing.
        event["error"] = retried.get("error") or "re-query returned no references"
        return finish({**result, "grade": grade, "rewritten_query": rewritten})

    retried_grade = grade_retrieval(retried["references"], threshold=threshold)
    event["retry_score"] = retried_grade["best_score"]
    event["score_change"] = round(
        retried_grade["best_score"] - grade["best_score"], 4)
    event["score_improved"] = event["score_change"] > 0
    # only adopt the rewrite's results if they actually graded better --
    # a rewrite that finds a different but equally weak set of chunks
    # isn't worth silently swapping in for the original.
    if retried_grade["best_score"] > grade["best_score"]:
        event["rewrite_adopted"] = True
        event["final_score"] = retried_grade["best_score"]
        return finish({**retried, "grade": retried_grade,
                       "rewritten_query": rewritten})
    return finish({**result, "grade": grade, "rewritten_query": rewritten})

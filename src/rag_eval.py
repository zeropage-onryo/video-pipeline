#!/usr/bin/env python3
"""
Retrieval eval harness: hit@k and MRR over a labeled case file, so a
chunking, embedding, or k change is measured against numbers instead
of argued about -- the same reasoning as shortlist_rate, applied to
retrieval.

Cases are document-level judgments: a case names the *sources* that
should come back for a query, because that's what a human can actually
label ("this query should surface the brand brief"), and chunk ids
change on every re-ingest. Rankings are therefore deduplicated to
first-appearance source order before scoring, so three chunks of one
document count as one ranked result, not three.

Case file shape:
    [{"query": "...", "relevant": ["brief.txt", "notes.md"]}, ...]

Run against the live store:
    venv/bin/python -m src.rag_eval cases.json [--k 5]
"""
import argparse
import hashlib
import json
from pathlib import Path

from dotenv import load_dotenv


def _source_ranking(retrieved: list) -> list:
    """Chunk results -> source names, first appearance order."""
    seen = []
    for item in retrieved:
        source = item["source"] if isinstance(item, dict) else item
        if source not in seen:
            seen.append(source)
    return seen


def hit_at_k(retrieved: list, relevant: list, k: int) -> int:
    """1 if any relevant source ranks in the top k, else 0."""
    ranking = _source_ranking(retrieved)[:k]
    return 1 if any(source in relevant for source in ranking) else 0


def reciprocal_rank(retrieved: list, relevant: list) -> float:
    """1/rank of the best-ranked relevant source; 0.0 if none appear."""
    for rank, source in enumerate(_source_ranking(retrieved), start=1):
        if source in relevant:
            return 1.0 / rank
    return 0.0


def evaluate(cases: list, retrieve_fn, k: int = 5) -> dict:
    """
    retrieve_fn(query, k) -> rag.query-shaped results. Returns the
    aggregate plus a per-query breakdown, so a bad average is
    immediately attributable to the queries that dragged it down.
    """
    if not cases:
        raise ValueError("no eval cases -- an empty eval can't say anything")
    per_query = []
    for case in cases:
        retrieved = retrieve_fn(case["query"], k)
        per_query.append({
            "query": case["query"],
            "relevant": case["relevant"],
            "retrieved": _source_ranking(retrieved)[:k],
            "hit": hit_at_k(retrieved, case["relevant"], k),
            "reciprocal_rank": round(reciprocal_rank(retrieved, case["relevant"]), 4),
        })
    return {
        "n": len(cases),
        "k": k,
        "hit_rate": round(sum(q["hit"] for q in per_query) / len(cases), 4),
        "mrr": round(sum(q["reciprocal_rank"] for q in per_query) / len(cases), 4),
        "per_query": per_query,
    }


def case_set_fingerprint(cases: list) -> str:
    """Stable identity for the exact labels used by an eval run."""
    payload = json.dumps(cases, sort_keys=True,
                         separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def evaluate_comparison(cases: list, base_retrieve_fn, crag_retrieve_fn,
                        k: int = 5) -> dict:
    """Compare one-shot retrieval with the complete CRAG retry path.

    crag_retrieve_fn(query, k) returns retrieve_with_crag's result. The
    scorer keeps similarity improvement separate from correctness: a retry
    can score higher without retrieving a human-labelled relevant source.
    """
    if not cases:
        raise ValueError("no eval cases -- an empty eval can't say anything")

    per_query = []
    for case in cases:
        base_hits = base_retrieve_fn(case["query"], k)
        crag_result = crag_retrieve_fn(case["query"], k)
        crag_hits = crag_result.get("references", []) if crag_result.get("ok") else []
        telemetry = crag_result.get("telemetry") or {}
        base_hit = hit_at_k(base_hits, case["relevant"], k)
        crag_hit = hit_at_k(crag_hits, case["relevant"], k)
        requery = bool(telemetry.get("requery_triggered"))
        per_query.append({
            "query": case["query"],
            "relevant": case["relevant"],
            "retrieved": _source_ranking(crag_hits)[:k],
            "base_retrieved": _source_ranking(base_hits)[:k],
            "hit": crag_hit,
            "base_hit": base_hit,
            "reciprocal_rank": round(reciprocal_rank(crag_hits, case["relevant"]), 4),
            "base_reciprocal_rank": round(
                reciprocal_rank(base_hits, case["relevant"]), 4),
            "requery_triggered": requery,
            "score_improved": bool(telemetry.get("score_improved")),
            "rewrite_adopted": bool(telemetry.get("rewrite_adopted")),
            "initial_score": telemetry.get("initial_score"),
            "retry_score": telemetry.get("retry_score"),
            "final_score": telemetry.get("final_score"),
            "score_change": telemetry.get("score_change"),
            "requery_retrieved_expected": bool(requery and crag_hit),
            "requery_corrected_miss": bool(requery and not base_hit and crag_hit),
        })

    n = len(per_query)
    retried = [row for row in per_query if row["requery_triggered"]]
    changes = [row["score_change"] for row in retried
               if row["score_change"] is not None]
    return {
        "n": n,
        "k": k,
        "hit_rate": round(sum(row["hit"] for row in per_query) / n, 4),
        "mrr": round(sum(row["reciprocal_rank"] for row in per_query) / n, 4),
        "base_hit_rate": round(sum(row["base_hit"] for row in per_query) / n, 4),
        "base_mrr": round(sum(row["base_reciprocal_rank"] for row in per_query) / n, 4),
        "requery_rate": round(len(retried) / n, 4),
        "requery_success_rate": round(
            sum(row["score_improved"] for row in retried) / len(retried), 4
        ) if retried else 0.0,
        "avg_score_improvement": round(sum(changes) / len(changes), 4)
        if changes else 0.0,
        "requery_adoption_rate": round(
            sum(row["rewrite_adopted"] for row in retried) / len(retried), 4
        ) if retried else 0.0,
        "requery_expected_source_rate": round(
            sum(row["requery_retrieved_expected"] for row in retried) / len(retried), 4
        ) if retried else 0.0,
        "per_query": per_query,
    }


def main(argv=None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="rag_eval", description="score retrieval against labeled cases"
    )
    parser.add_argument("cases", type=Path, help="JSON: [{query, relevant: [...]}]")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)

    # loud on purpose, like the rag CLI: the eval is the deliverable
    from . import rag
    client = rag.make_client()
    conn = rag.connect()

    def retrieve(query, k):
        return rag.query(query, client, conn, k=k)

    report = evaluate(json.loads(args.cases.read_text()), retrieve, k=args.k)
    conn.close()

    print(json.dumps(report, indent=2))
    print(f"\nhit@{report['k']}: {report['hit_rate']:.2f}   "
          f"MRR: {report['mrr']:.2f}   over {report['n']} queries")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
CI's retrieval regression gate: runs rag_eval.evaluate() against the
freshly-ingested ephemeral store (see .github/workflows/ci.yml's
eval-gate job) and fails the build if hit@5/MRR drop below fixed
floors.

A fixed floor rather than a baseline-scores.json like
evals/test_generation_quality.py's generation gate -- eval_cases.json
is small enough that a hand-picked floor is easier to reason about
than a second baseline file to keep in sync, and a genuine
ingest/chunking/embedding regression still fails this either way.

Usage:
    venv/bin/python -m evals.check_retrieval_regression [--k 5]
"""
import argparse
import json
import sys
from pathlib import Path

from src.rag import connect, make_client, query
from src.rag_eval import evaluate

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_CASES_PATH = PROJECT_ROOT / "eval_cases.json"

HIT_FLOOR = 0.7
MRR_FLOOR = 0.6


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)

    client = make_client()
    conn = connect()

    def retrieve(q, k):
        return query(q, client, conn, k=k)

    cases = json.loads(EVAL_CASES_PATH.read_text())
    report = evaluate(cases, retrieve, k=args.k)
    conn.close()

    print(json.dumps(report, indent=2))

    if report["hit_rate"] < HIT_FLOOR or report["mrr"] < MRR_FLOOR:
        print(
            f"::error::retrieval regressed: hit@{args.k}={report['hit_rate']} "
            f"(floor {HIT_FLOOR}), mrr={report['mrr']} (floor {MRR_FLOOR})"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

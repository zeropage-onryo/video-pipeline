"""
The taste + performance judge. Scores a concept against THIS creator's own
record -- what they approved vs rejected on /holds, what they hand-marked
worked vs didn't-work, and the traits of their winning vs losing posts -- to
predict "they'll like this" and "this will travel," so a slate can rank
itself toward what the creator actually likes and what actually works.

Distinct from the other judges on purpose: score_prompts (the credit gate)
and the JUDGE=1 evaluator grade CRAFT against fixed rubrics; this one grades
against the creator's HISTORY. Every input already exists -- this wires the
passive feedback (grades, winners, analytics) into an active scorer.

Same split the rest of the codebase keeps: gather_signals is pure (SQLite +
post_seo, no network, hermetic in tests); score_concept isolates the one LLM
call and never raises -- a missing key, thin history, or a bad model reply
degrades to a neutral score that says why, never an exception that takes a
slate down.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import db, post_seo, preprod, winners
from .gemini_utils import generate_with_retry, strip_fences

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
NEUTRAL = 5.0
HISTORY_LIMIT = 12   # recent graded items per side to show the judge


def _graded_concepts(status: str, limit: int, path) -> list[dict]:
    """Titles/hooks/loglines of concepts whose hold you graded `status`."""
    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT c.title, c.hook, c.logline FROM hold_queue h "
            "JOIN shoot_concepts c ON c.id = h.concept_id "
            "WHERE h.status = ? AND h.concept_id IS NOT NULL "
            "ORDER BY h.created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def gather_signals(db_path=None) -> dict:
    """Everything the judge scores against -- pure, no network."""
    path = db_path or db.DB_PATH
    wins = winners.list_all(path=path)
    return {
        "liked": _graded_concepts("approved", HISTORY_LIMIT, path),
        "disliked": _graded_concepts("rejected", HISTORY_LIMIT, path),
        "winners": [w for w in wins if w.get("verdict") != "didnt_work"][:HISTORY_LIMIT],
        "avoid": [w for w in wins if w.get("verdict") == "didnt_work"][:HISTORY_LIMIT],
        "perf": post_seo.derive_signals(db_path=db_path),
    }


def has_history(signals: dict) -> bool:
    """True once there's anything real to score against -- otherwise the
    judge honestly returns neutral instead of inventing a preference."""
    return bool(signals["liked"] or signals["disliked"]
                or signals["winners"] or signals["avoid"]
                or signals["perf"].get("sample", 0) >= 1)


def _fmt_concepts(rows: list[dict]) -> str:
    if not rows:
        return "(none yet)"
    return "\n".join(
        f"- {r.get('title') or 'untitled'}: {(r.get('hook') or '').strip()}".rstrip(": ")
        for r in rows)


def _fmt_prompts(rows: list[dict]) -> str:
    if not rows:
        return "(none yet)"
    out = []
    for r in rows:
        note = f" — {r['note']}" if r.get("note") else ""
        out.append(f"- [{r.get('tool') or 'runway'}]{note}")
    return "\n".join(out)


def _fmt_traits(*counters_labels) -> str:
    parts = []
    for counter, label in counters_labels:
        if counter:
            top = counter.most_common(6) if hasattr(counter, "most_common") else list(counter.items())[:6]
            if top:
                parts.append(f"{label}: " + ", ".join(f"{k} ({v})" for k, v in top))
    return "; ".join(parts)


def build_prompt(concept: dict, signals: dict) -> str:
    perf = signals["perf"]
    win_traits = _fmt_traits((perf.get("winning_topics"), "topics"),
                             (perf.get("winning_hooks"), "hooks")) or "(no winning-post data yet)"
    lose_traits = _fmt_traits((perf.get("losing_topics"), "topics"),
                              (perf.get("losing_hooks"), "hooks")) or "(no losing-post data yet)"
    concept_str = (f"Title: {concept.get('title')}\nHook: {concept.get('hook')}\n"
                   f"Logline: {concept.get('logline')}\nBrand: {concept.get('brand')}")
    template = (PROMPTS_DIR / "taste_judge_prompt.txt").read_text()
    return (template
            .replace("{liked}", _fmt_concepts(signals["liked"]))
            .replace("{disliked}", _fmt_concepts(signals["disliked"]))
            .replace("{winners}", _fmt_prompts(signals["winners"]))
            .replace("{avoid}", _fmt_prompts(signals["avoid"]))
            .replace("{winning_traits}", win_traits)
            .replace("{losing_traits}", lose_traits)
            .replace("{concept}", concept_str))


def _clamp(v) -> float:
    try:
        return max(0.0, min(10.0, float(v)))
    except (TypeError, ValueError):
        return NEUTRAL


def _client():
    from google import genai
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY")
                        or os.environ.get("GOOGLE_API_KEY"))


def score_concept(concept: dict, signals=None, gemini_client=None, db_path=None) -> dict:
    """Score one concept 0-10 on taste_fit + performance. Never raises: no
    key / thin history / a bad model reply all degrade to a neutral score
    whose reason says why."""
    if signals is None:
        signals = gather_signals(db_path=db_path)
    if not has_history(signals):
        return {"taste_fit": NEUTRAL, "performance": NEUTRAL, "overall": NEUTRAL,
                "reasons": ["no graded history or performance data yet -- neutral; "
                            "grade holds and record a few posts to teach this judge"],
                "graded": False}
    try:
        client = gemini_client or _client()
        raw = generate_with_retry(client, MODEL, build_prompt(concept, signals))
        data = json.loads(strip_fences(raw))
        taste, perf = _clamp(data.get("taste_fit")), _clamp(data.get("performance"))
        overall = _clamp(data.get("overall", (taste + perf) / 2))
        reasons = [str(r) for r in (data.get("reasons") or [])][:4]
        return {"taste_fit": taste, "performance": perf, "overall": overall,
                "reasons": reasons, "graded": True}
    except Exception as e:
        return {"taste_fit": NEUTRAL, "performance": NEUTRAL, "overall": NEUTRAL,
                "reasons": [f"judge unavailable ({e}) -- neutral score"], "graded": False}


def rank(concepts: list[dict], signals=None, gemini_client=None, db_path=None) -> list[dict]:
    """Score every concept and return them best-first. Stable sort, so ties
    keep input order."""
    if signals is None:
        signals = gather_signals(db_path=db_path)
    scored = [{**c, "judge": score_concept(c, signals=signals,
                                           gemini_client=gemini_client, db_path=db_path)}
              for c in concepts]
    return sorted(scored, key=lambda c: c["judge"]["overall"], reverse=True)


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Rank recent concepts by predicted taste fit + performance.")
    parser.add_argument("--limit", type=int, default=8,
                        help="how many recent concepts to score")
    parser.add_argument("--concept-id", type=int, help="score just this concept id")
    args = parser.parse_args(argv)

    signals = gather_signals()
    if not has_history(signals):
        print("No graded history yet -- grade some holds and record a few posted "
              "videos, then this judge has something to score against.", file=sys.stderr)

    if args.concept_id:
        c = preprod.get_concept(args.concept_id)
        if not c:
            print(f"no concept {args.concept_id}", file=sys.stderr)
            return 1
        concepts = [c]
    else:
        concepts = preprod.list_concepts(limit=args.limit)

    for c in rank(concepts, signals=signals):
        j = c["judge"]
        print(f"[{j['overall']:.1f}] taste {j['taste_fit']:.1f} / perf {j['performance']:.1f}"
              f"  —  {c.get('title')}")
        for r in j["reasons"]:
            print(f"      · {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

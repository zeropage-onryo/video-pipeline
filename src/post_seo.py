"""
Post-level performance signal: which titles, hooks and topics actually
earn reach, derived from this channel's own numbers, and a scorer the
autonomy loop can optimize against.

Naming note -- two "seo"s, deliberately separate: app/seo.py is the
*site's* machine-readable surface (robots.txt, llms.txt, JSON-LD) for
crawlers reading the marketing page. This module scores *posts* --
the titles/hooks/topics of the videos themselves. Same word, different
subject, kept in different modules for the same reason concepts.json
and shoot_concepts stay distinct.

Everything here is pure against SQLite. derive_signals reads the same
tables db.benchmark reads, at the same equal-age discipline (a video is
judged at what it had done by at_days, so an old video can't win on
accumulated totals); score_post is a pure function of its arguments.
No network, no model call, so the loop can score a hundred drafts for
free before anything billed runs.
"""
import re
from collections import Counter
from typing import Any, Optional

from . import db

# A trait tally below this many scored videos is noise, not signal --
# the same "structurally correct, statistically meaningless" caveat the
# rates carry until real use accumulates.
MIN_SAMPLE = 4

BASELINE = 0.5

# words that carry no editorial signal in a title
STOPWORDS = {
    "a", "an", "and", "at", "by", "for", "from", "i", "in", "is", "it",
    "my", "of", "on", "or", "the", "this", "to", "with", "you", "your",
}

WEIGHT_TOPIC = 0.15
WEIGHT_HOOK = 0.15
WEIGHT_TITLE_WORDS = 0.2
PENALTY_NO_TITLE = 0.2


def title_words(title: str) -> list[str]:
    """Signal-bearing words of a title: lowercased, hashtags and
    stopwords dropped."""
    words = re.findall(r"[a-z0-9']+", (title or "").lower())
    return [w for w in words if w not in STOPWORDS and not w.isdigit()]


def derive_signals(
    at_days: int = 7,
    posted_within_days: Optional[int] = 180,
    metric: str = "views",
    db_path=None,
    account_id: Optional[int] = None,
) -> dict[str, Any]:
    """
    Split every scored video at the window median and tally the traits
    of each side: topics, hook types, title words. The output is plain
    counts plus the evidence context (median, sample size), so a reason
    string can always say *why* -- "3 of the window's winners" -- rather
    than just asserting goodness.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    bench = db.benchmark(
        at_days=at_days, posted_within_days=posted_within_days,
        metric=metric, **kwargs,
    
        account_id=account_id,)
    rows = db.get_top_performers(
        at_days=at_days, posted_within_days=posted_within_days,
        metric=metric, limit=1000, **kwargs,
    
        account_id=account_id,)

    signals: dict[str, Any] = {
        "sample": len(rows), "median": bench["median"],
        "at_days": at_days, "metric": metric,
        "winning_topics": Counter(), "losing_topics": Counter(),
        "winning_hooks": Counter(), "losing_hooks": Counter(),
        "winning_title_words": Counter(),
    }
    if not rows or bench["median"] is None:
        signals["sample"] = 0
        return signals

    for row in rows:
        won = (row.get("score") or 0) > bench["median"]
        side = "winning" if won else "losing"
        if row.get("topic"):
            signals[f"{side}_topics"][row["topic"]] += 1
        if row.get("hook_type"):
            signals[f"{side}_hooks"][row["hook_type"]] += 1
        if won:
            for word in set(title_words(row.get("title") or "")):
                signals["winning_title_words"][word] += 1
    return signals


def _evidence(count: int, signals: dict) -> str:
    return (
        f"{count} of {signals['sample']} scored videos (median "
        f"{signals['median']:,.0f} {signals['metric']} at {signals['at_days']}d)"
    )


def score_post(
    title: str,
    topic: Optional[str] = None,
    hook_type: Optional[str] = None,
    signals: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Score a draft post against the derived signals. Returns
    {"score": 0..1, "reasons": [...]} where every score movement names
    the evidence behind it. No signals (or too small a sample) means a
    neutral score that says so -- an honest null, not fake confidence.
    """
    reasons: list[str] = []
    score = BASELINE

    if not (title or "").strip():
        score -= PENALTY_NO_TITLE
        reasons.append("no title -- nothing for search or the feed to index")

    if not signals or signals.get("sample", 0) < MIN_SAMPLE:
        reasons.append(
            "no performance data yet (fewer than "
            f"{MIN_SAMPLE} scored videos) -- neutral score, post and measure"
        )
        return {"score": max(0.0, min(1.0, score)), "reasons": reasons}

    if topic:
        wins = signals["winning_topics"].get(topic, 0)
        losses = signals["losing_topics"].get(topic, 0)
        if wins > losses:
            score += WEIGHT_TOPIC
            reasons.append(f"topic '{topic}' beat the median in {_evidence(wins, signals)}")
        elif losses > wins:
            score -= WEIGHT_TOPIC
            reasons.append(f"topic '{topic}' fell below the median in {_evidence(losses, signals)}")

    if hook_type:
        wins = signals["winning_hooks"].get(hook_type, 0)
        losses = signals["losing_hooks"].get(hook_type, 0)
        if wins > losses:
            score += WEIGHT_HOOK
            reasons.append(f"hook '{hook_type}' beat the median in {_evidence(wins, signals)}")
        elif losses > wins:
            score -= WEIGHT_HOOK
            reasons.append(f"hook '{hook_type}' fell below the median in {_evidence(losses, signals)}")

    overlap = [w for w in set(title_words(title))
               if signals["winning_title_words"].get(w)]
    if overlap:
        # scaled by how many winning titles share the words, capped
        strength = min(1.0, sum(signals["winning_title_words"][w] for w in overlap)
                       / max(1, signals["sample"]))
        score += WEIGHT_TITLE_WORDS * strength
        reasons.append(
            "title shares words with winning titles: "
            + ", ".join(sorted(overlap))
        )

    return {"score": max(0.0, min(1.0, score)), "reasons": reasons}

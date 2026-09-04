"""
The four numbers on /costs, each of which can change a decision
(docs/tasks/task-cost-tracker.md step 4). Pure reads over tables that
already exist -- generations, llm_calls, prompt_scores, hold_queue -- so
a hundred page loads cost nothing and every figure can be checked
against the table it came from.

1. Cost per kept clip, per tool  -- generative.tool_scoreboard /
   attempts_to_keeper, computed since the table was written and surfaced
   nowhere until 2026-09-04. A prompt that lands in 2 tries beats one
   that lands in 6, and the losers on the same shot are part of the price.
2. Cost per stage, per night      -- spend.by_stage / by_run, the LLM meter.
3. Wasted spend                   -- autonomy.prompt_gate_agreement's
   passed-but-rejected (a credit burned on a clip never used), rejected
   attempts' cost, and what the hold queue never posted.
4. Today against the caps         -- generative.used_today per tool, per
   account and installation-wide, against each tool's DAILY_CAP /
   GLOBAL_DAILY_CAP; plus today's LLM spend. What makes a cap a budget.

Two honesty rules the numbers keep: a render with cost_usd NULL was paid
for by a subscription (ops/render_queue.py) and is reported as FREE with
a count, never as $0.00 spend and never backfilled; and every dollar here
is an estimate written at call time, labelled as such on the page.
"""
from __future__ import annotations

from typing import Any, Optional

from . import autonomy, db, generative, spend

NOTES = (
    "Every figure is an estimate written at call time from a price table "
    "(src/spend.py PRICES, src/<tool>.py COST_*), never an invoice.",
    "A render with no price was paid for by a subscription, not per call; it "
    "is counted as free, not as $0.00 spend.",
    "Embeddings (gemini-embedding-001, the RAG library) are not metered.",
)


def _tools() -> list[tuple[str, Any]]:
    from . import higgsfield, midjourney, nano_banana, runway, veo
    return [("runway", runway), ("veo", veo), ("higgsfield", higgsfield),
            ("midjourney", midjourney), ("nano", nano_banana)]


def render_costs(dsn: Optional[str] = None, *, account_id: Optional[int]) -> dict[str, Any]:
    """Number 1, plus the free-render count the honesty rule needs."""
    with db.connect(dsn) as conn:
        row = conn.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE cost_usd IS NULL), "
            "COALESCE(SUM(cost_usd), 0), COALESCE(SUM(kept), 0), "
            "COALESCE(SUM(cost_usd) FILTER (WHERE reject_reason IS NOT NULL), 0) "
            "FROM generations WHERE account_id IS NOT DISTINCT FROM %s",
            (account_id,),
        ).fetchone()
    return {
        "scoreboard": generative.tool_scoreboard(dsn, account_id=account_id),
        "keepers": generative.attempts_to_keeper(dsn=dsn, account_id=account_id),
        "attempts": row[0],
        "free": row[1] or 0,
        "spend": round(float(row[2]), 2),
        "kept": int(row[3] or 0),
        "rejected_spend": round(float(row[4]), 2),
    }


def waste(dsn: Optional[str] = None, *, account_id: Optional[int]) -> dict[str, Any]:
    """Number 3. `passed_but_rejected` is the expensive disagreement: the
    gate would have spent a credit on a clip you rejected."""
    gate = autonomy.prompt_gate_agreement(dsn=dsn)
    holds = autonomy.list_hold(status=None, dsn=dsn, account_id=account_id)
    by_status: dict[str, int] = {}
    for h in holds:
        by_status[h["status"]] = by_status.get(h["status"], 0) + 1
    with db.connect(dsn) as conn:
        rejected = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM generations "
            "WHERE reject_reason IS NOT NULL AND account_id IS NOT DISTINCT FROM %s",
            (account_id,),
        ).fetchone()
    return {
        "gate": gate,
        "holds": by_status,
        "never_posted": sum(n for s, n in by_status.items() if s != "posted"),
        "rejected_attempts": rejected[0],
        "rejected_spend": round(float(rejected[1]), 2),
    }


def today(dsn: Optional[str] = None, *, account_id: Optional[int]) -> dict[str, Any]:
    """Number 4: today's renders per tool against both walls, and
    today's LLM spend for this account and for the installation."""
    tools = []
    for name, module in _tools():
        used = generative.used_today(name, dsn, account_id=account_id)
        everyone = generative.used_today(name, dsn, everyone=True)
        tools.append({
            "tool": name,
            "used": used, "cap": module.DAILY_CAP,
            "everyone": everyone, "ceiling": module.GLOBAL_DAILY_CAP,
            "gated": bool(getattr(module, "SPEND_ENV", None)),
            "spend_env": getattr(module, "SPEND_ENV", None),
        })
    return {
        "tools": tools,
        "llm": spend.spent_today(dsn, account_id=account_id),
        "llm_everyone": spend.spent_today_everyone(dsn),
    }


def summary(dsn: Optional[str] = None, *, account_id: Optional[int],
            runs: int = 14) -> dict[str, Any]:
    """Everything /costs and GET /api/costs show, from one function so
    the page and the JSON cannot disagree."""
    per_run = spend.by_run(dsn, account_id=account_id, limit=runs)
    latest = next((r for r in per_run if r.get("run_id")), None)
    return {
        "render": render_costs(dsn, account_id=account_id),
        "llm": {
            "by_stage": spend.by_stage(dsn, account_id=account_id),
            "by_run": per_run,
            "latest_run": ({"run_id": latest["run_id"],
                            "by_stage": spend.by_stage(dsn, account_id=account_id,
                                                       run_id=latest["run_id"])}
                           if latest else None),
        },
        "waste": waste(dsn, account_id=account_id),
        "today": today(dsn, account_id=account_id),
        "stages": list(spend.STAGES),
        "notes": list(NOTES),
    }

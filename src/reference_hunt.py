"""The hunt: a spark's references, one NEED at a time (2026-09-24).

`scout.illustrate` is the backstop this replaces for the new path: one
query off the whole spark, first readable image wins, nobody looks at it.
A hunt runs the three pieces built today in order --
`reference_needs.plan` (what does this scene need photographs OF),
`imagesearch.search` per need, `refcheck.screen` over what comes back --
and banks only frames something has actually looked at.

The decisions, all of which are this module's and not the pieces':

- **A hunt refuses to bank what it could not check.** `require_check` is
  True by default: no key, no client or a failed vision call means that
  need contributes nothing and the report says why. `illustrate` keeps
  its old behaviour untouched, so a missing key degrades the NEW path and
  leaves the existing one exactly as it was — the fail-open/fail-closed
  split is deliberate and it is the whole reason these are two functions.
- **One round per need.** Their Referencer caps at two unproductive
  rounds and then says why it failed; this caps at one, because a second
  query written by the same planner off the same spark is the same query.
  A need that finds nothing is reported as bare, never retried silently.
- **The spark's bin cap is the budget.** `scout.MAX_BIN_IMAGES` for the
  whole hunt, `KEEP_PER_NEED` per need, so one greedy need cannot spend
  the whole bin and leave the wardrobe unillustrated.
- **It never raises.** Every dependency is injectable, which is also how
  the tests drive it without a database or a model.
"""
from __future__ import annotations

from typing import Optional

NEEDS_PER_HUNT = 4        # a contact sheet each; more is a chore, not coverage
CANDIDATES_PER_NEED = 6   # what one query is asked for
KEEP_PER_NEED = 2         # so no single need eats the bin


def _report(need: dict, found: int = 0, kept: int = 0, banked: int = 0,
            note: str = "") -> dict:
    return {"role": need.get("role", ""), "query": need.get("query", ""),
            "found": found, "kept": kept, "banked": banked, "note": note}


def hunt(finding_id: int, *, dsn=None, client=None, model: str = "",
         require_check: bool = True, account_id=None,
         plan=None, search=None, screen=None, bank=None, cap=None) -> dict:
    """Illustrate one spark, by need, with every frame looked at.

    Returns {"ok", "banked", "checked", "planner", "needs", "note"}.
    `checked` False means at least one need went unlooked-at; with
    `require_check` on, those needs banked nothing.
    """
    from . import scout

    finding = scout.get_finding(finding_id, dsn=dsn)
    if not finding:
        return {"ok": False, "banked": 0, "checked": False, "planner": "",
                "needs": [], "note": f"no finding {finding_id}"}

    brand = finding.get("brand") or ""
    spark = finding.get("spark") or ""
    cap = scout.MAX_BIN_IMAGES if cap is None else cap
    room = cap - len(scout.bin_for_finding(finding_id, dsn=dsn))
    if room <= 0:
        return {"ok": True, "banked": 0, "checked": True, "planner": "",
                "needs": [], "note": f"bin already holds {cap} image(s)"}

    if plan is None:
        from .reference_needs import plan
    if search is None:
        from .imagesearch import search
    if screen is None:
        from .refcheck import screen
    if bank is None:
        from .scout import bank_candidate as bank

    from . import reference_needs

    mapped = plan(spark, brand=brand, client=client, model=model,
                  account_id=account_id)
    needs = reference_needs.open_needs(mapped.get("needs") or [])[:NEEDS_PER_HUNT]
    if not needs:
        return {"ok": False, "banked": 0, "checked": True,
                "planner": mapped.get("planner", ""), "needs": [],
                "note": "nothing to hunt for"}

    reports, banked_total, unchecked = [], 0, 0
    for need in needs:
        if room <= 0:
            reports.append(_report(need, note="bin full"))
            continue
        try:
            candidates = search(need["query"], brand,
                                limit=CANDIDATES_PER_NEED, dsn=dsn)
        except Exception as e:                  # pragma: no cover - defensive
            reports.append(_report(need, note=f"search failed: {e}"))
            continue
        if not candidates:
            # The distinction `images_for` draws and this keeps: a dark
            # lane and an empty result are different failures.
            reports.append(_report(need, note="no lane configured, or nothing matched"))
            continue
        looked = screen(candidates, need, brand=brand, client=client,
                        model=model, account_id=account_id)
        kept = looked.get("keepers") or []
        if not looked.get("checked"):
            unchecked += 1
            if require_check:
                reports.append(_report(need, found=len(candidates),
                                       note=f"not looked at — {looked.get('note', '')}".strip()))
                continue
        banked_here = 0
        for keeper in kept[:KEEP_PER_NEED]:
            if room <= 0:
                break
            result = bank(finding, {**keeper, "lane": "hunt"}, dsn=dsn)
            if result.get("ok"):
                banked_here += 1
                banked_total += 1
                room -= 1
        reports.append(_report(need, found=len(candidates), kept=len(kept),
                               banked=banked_here,
                               note=looked.get("note", "") if not banked_here else ""))

    covered = sum(1 for r in reports if r["banked"])
    return {
        "ok": banked_total > 0,
        "banked": banked_total,
        "checked": unchecked == 0,
        "planner": mapped.get("planner", ""),
        "needs": reports,
        "note": f"{covered} of {len(reports)} need(s) covered, "
                f"{banked_total} image(s) banked"
                + (f"; {unchecked} not looked at" if unchecked else ""),
    }


def hunt_bare(brand: str, *, limit: int = 20, dsn=None, log=None, **kwargs) -> dict:
    """Hunt every unused spark of a brand that has no pictures yet.

    `illustrate_bare`'s shape, and the same reason it exists: the number
    worth printing is what is still unservable afterwards, not how many
    sparks were written.
    """
    from . import scout

    checked = hunted = bare = 0
    for row in scout.list_findings(brand=brand, unused_only=True,
                                   limit=limit, dsn=dsn):
        if scout.bin_for_finding(row["id"], dsn=dsn):
            continue
        checked += 1
        result = hunt(row["id"], dsn=dsn, **kwargs)
        if result.get("banked"):
            hunted += 1
        else:
            bare += 1
            if log:
                log(f"hunt: spark {row['id']} left bare — {result['note']}")
    return {"checked": checked, "hunted": hunted, "bare": bare}

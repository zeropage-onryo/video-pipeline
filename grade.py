#!/usr/bin/env python3
"""
Fast morning grader for the shadow-run hold queue — the two-minute ritual
that fills the credit gate.

  python grade.py                 list ungraded holds + gate progress
  python grade.py <id>            full detail of one hold (concept + scored prompts)
  python grade.py <id> approve    you'd have posted it -> hold 'approved', prompts 'post'
  python grade.py <id> reject     glad it held         -> hold 'rejected', prompts 'reject'

Grading writes BOTH numbers the credit gate reads: the hold's status
(autonomy.evaluator_agreement) and the run's prompt verdicts
(autonomy.prompt_gate_agreement). Nothing here spends a credit — it only
records your judgment so the agreement number can accumulate.
"""
import sys

from src import autonomy, db

TARGET = 25        # your bar: ~20-30 graded holds at ~0.9 agreement
CHANNEL = None     # None = all channels; set e.g. "antihero" to focus one


def _run_id_for(hold):
    p = hold.get("payload")
    return p.get("run_id") if isinstance(p, dict) else None


def _concept(cid):
    if not cid:
        return {}
    with db.connect() as c:
        r = c.execute(
            "SELECT title, hook, logline, spark, brand FROM shoot_concepts WHERE id=?",
            (cid,)).fetchone()
    return dict(r) if r else {}


def _progress():
    ev = autonomy.evaluator_agreement(channel=CHANNEL)
    pg = autonomy.prompt_gate_agreement()
    graded, agree = ev["graded"], ev["agreement"]
    agree_s = f"{agree:.0%}" if agree is not None else "—"
    gate_s = f"{pg['agreement']:.0%}" if pg["agreement"] is not None else "—"
    scope = f" [{CHANNEL}]" if CHANNEL else ""
    print(f"\nGATE PROGRESS{scope}   graded {graded}/{TARGET}"
          f"   you-would-post {agree_s}   gate-vs-you {gate_s}")
    if pg.get("passed_but_rejected"):
        print(f"  !! {pg['passed_but_rejected']} passed-but-you'd-reject "
              f"— each of these would burn a credit once live")
    if graded < TARGET:
        print(f"  {TARGET - graded} more graded to clear the count bar.")
    else:
        print("  count bar met — confirm agreement is ~0.9 before ZEROPAGE_RENDER=1.")


def list_holds():
    holds = [h for h in autonomy.list_hold(status="held")
             if CHANNEL is None or h["channel"] == CHANNEL]
    if not holds:
        print("No ungraded holds. Let the nightly trigger fill the queue.")
    else:
        print(f"\nUNGRADED HOLDS ({len(holds)})  —  grade: python grade.py <id> approve|reject\n")
        for h in holds:
            c = _concept(h.get("concept_id"))
            print(f"  [{h['id']:>3}] {h['channel']:<9} {c.get('title') or '(no concept)'}")
            hook = (c.get("hook") or "").strip()
            if hook:
                print(f"        hook: {hook[:88]}")
            print(f"        gate: {(h.get('reason') or '')[:96]}")
    _progress()


def detail(hid):
    h = next((x for x in autonomy.list_hold(status=None) if x["id"] == hid), None)
    if not h:
        print(f"no hold #{hid}")
        return
    c = _concept(h.get("concept_id"))
    print(f"\nHOLD #{hid}  [{h['channel']}]  status={h['status']}")
    print(f"  title  : {c.get('title')}")
    print(f"  spark  : {c.get('spark')}")
    print(f"  hook   : {c.get('hook')}")
    print(f"  logline: {c.get('logline')}")
    print(f"  gate   : {h.get('reason')}")
    rid = _run_id_for(h)
    if rid:
        with db.connect() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT score, passed, reason, human_verdict FROM prompt_scores "
                "WHERE run_id=? ORDER BY id", (rid,))]
        if rows:
            print("  scored prompts:")
            for r in rows:
                mark = "PASS" if r["passed"] else "held"
                hv = f"  (you: {r['human_verdict']})" if r["human_verdict"] else ""
                print(f"    - {mark} {r['score']}/10 — {(r['reason'] or '')[:80]}{hv}")
    print("\n  grade:  python grade.py {0} approve   |   python grade.py {0} reject".format(hid))


def grade(hid, word):
    h = next((x for x in autonomy.list_hold(status=None) if x["id"] == hid), None)
    if not h:
        print(f"no hold #{hid}")
        return
    approve = word.lower() in ("approve", "a", "post", "yes", "y")
    status = "approved" if approve else "rejected"
    autonomy.resolve_hold(hid, status)
    rid = _run_id_for(h)
    n = autonomy.set_prompt_verdicts(rid, "post" if approve else "reject") if rid else 0
    print(f"hold #{hid} -> {status}   ({n} prompt score(s) recorded)")
    _progress()


def main(argv):
    if not argv:
        list_holds()
    elif len(argv) == 1:
        detail(int(argv[0]))
    else:
        grade(int(argv[0]), argv[1])


if __name__ == "__main__":
    main(sys.argv[1:])

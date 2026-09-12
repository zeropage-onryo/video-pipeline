#!/usr/bin/env python3
"""
The manual (subscription) render lane, and the one gate in front of it.

WHAT THE LANE IS. Runway's API has exactly one billing path: developer
portal credits at $0.01 each (src/runway.py's header). The Unlimited/Max
plan's free-but-queued **Explore Mode is a web-app toggle with no API
parameter**, so no adapter in this repo can reach it -- the only way to
spend that subscription is a human (or a Claude session) driving Chrome
and dragging the keyframe in by hand. `ops/render_queue.py` is the repo
side of that: `list` says what is waiting, the human renders it, `import`
files the mp4 back into data/renders/ where /renders can serve it.

WHY IT NEEDS A GATE, WHICH THE HIGGSFIELD LANE NEVER HAD.
The subscription being spent is the OPERATOR'S PERSONAL CONSUMER PLAN.
Rendering a paying customer's shot on it is reselling a consumer
subscription: the plan's own terms, not ours, and the penalty is not a
refund but termination of the account -- which on a multi-tenant install
takes EVERY tenant's render path down at once, not just the one whose
shot was rendered. So the lane is deliberately not a feature: it is the
operator's own hands, and the account id is what says so.

THE RULES THIS MODULE EXISTS TO KEEP IN ONE PLACE:

- **The check is server-side, against the account id.** Never a flag, a
  header, a query parameter or a CLI switch a caller could set. Every
  surface calls `manual_lane_allowed(account_id)` (or `require`), and
  there is exactly one of those so a second surface cannot invent a
  second rule that is subtly wider.
- **It fails closed.** A database nobody has been turned on in means
  NOBODY, including the bootstrap account, including the unowned pool
  (`account_id is None`, which is what a fresh or unseeded database hands
  a CLI). A gate that opens the moment its configuration goes missing --
  an unreadable table, a column that is not there yet -- is not a gate;
  and the failure mode of being too closed is an operator running one
  command, while the failure mode of being too open is the paragraph
  above.
- **A refusal is the SAME refusal for everyone.** `REFUSAL` is the whole
  message, byte for byte, whoever asks and whatever the reason -- so it
  cannot be used to probe whether some other account has the lane, or
  whether an operator is configured at all. What it may say, because it
  is true on every install and reveals nothing about this one, is what
  governs the lane: someone who hits this on their own machine needs to
  know what to run, and naming the column and the command tells an
  outsider only what this repo's source already tells them. What it must
  never carry is an account, a slug, an id or an email.

CONFIGURATION -- ONE COLUMN, AND NOTHING ELSE. `accounts.manual_lane_operator`,
a boolean on the account row, set by hand:

    python -m src.accounts operator zeropage --on

Until 2026-09-08 this was two env vars (`ZEROPAGE_OPERATOR_ACCOUNTS` and
`_EMAILS`) and they are GONE, not kept as a fallback. Two reasons, and
the second is the one that decided it:

- **The environment is not a gate.** Anyone who can set a variable on the
  process -- a deploy config, a `.env` on a shared box, a wrapper script,
  a shell one directory up -- could name themselves operator, and nothing
  anywhere recorded who was on the list when a clip was rendered. A
  column has to be written from inside the database.
- **A gate with two doors is one door.** A fallback would mean the
  weaker door decides, while everyone reading the stronger one believes
  the gate is stronger than it is. So the column is the only truth, and
  an install that has not run the command refuses everybody -- which is
  the fail-closed rule above, not a new one.

MEMBERSHIP IS NO LONGER TRANSITIVE, BY CONSTRUCTION. The email spelling
resolved to every account that person was a MEMBER of, so adding the
operator to a pilot user's account to debug something silently made that
account an operator account. The flag is on the account row, so being a
member of an account says nothing about whether that account may spend
the subscription -- there is no longer a code path that could make it
say so, which is why the fix is a column and not a narrower query.

Read fresh on every call rather than cached, because the CLI, the app
and the tests each reach a different database at a different moment and
a cached answer from one is a wrong answer about another. A read that
fails -- no table, no database, no column -- is a refusal: the set only
ever shrinks on error, and erring there widens nothing.
"""
from __future__ import annotations

from typing import Optional

from . import render_specs
from .db import connect

# The column that IS the gate (src/db.py's add_manual_lane_operator_column).
OPERATOR_COLUMN = "manual_lane_operator"

# The command that moves it, named in the refusal below because a person
# who hits that refusal on their own machine has to be able to act on it.
OPERATOR_COMMAND = "python -m src.accounts operator <slug> --on"

# What every surface says when the answer is no. ONE string, identical
# for every caller and every reason -- see the module docstring for what
# it may and may not carry. It names the COLUMN and the COMMAND, which
# are true on every install and are in this repo's source anyway; it
# never names an account, a slug, an id or an email.
REFUSAL = ("no manual render lane on this account -- the subscription lanes are "
           "operator-only (accounts.manual_lane_operator, set with "
           f"`{OPERATOR_COMMAND}`, see docs/RUNBOOK.md)")

# The marker that goes in `generations.params_json` for a render filed
# through this lane, beside the `key_source` field the adapters write.
# `src/ledger.py` reads it (`is_billable`) and `src/costs.py`'s honesty
# rule reads its consequence (cost_usd NULL == FREE, never $0).
SOURCE = "manual-unlimited"
LANES = {
    "runway": "runway-explore",
    # The Higgsfield MCP lane predates this module and writes its own
    # marker; named here so the ledger has one list to read.
    "higgsfield": "higgsfield-mcp",
}

# Every `params.source` that means "a subscription already paid for this
# clip, outside the ledger". `mcp-subscription` is what
# ops/render_queue.py has written for the Higgsfield lane since it was
# built; it is the same structural fact under an older name, so it is
# listed rather than migrated.
SUBSCRIPTION_SOURCES = frozenset({SOURCE, "mcp-subscription"})

# What the Runway web app is asked for on this lane. BOTH are
# src/render_specs.py's, which is also where src/runway.py's DEFAULT_RATIO
# comes from -- one literal, so the by-hand render and the API render ask
# for the same frame and there is nothing left to drift. Re-exported here
# because every caller in the lane already speaks to this module.
LANE_RATIO = render_specs.LANE_RATIO
LANE_DURATION = render_specs.LANE_DURATION


class LaneRefused(PermissionError):
    """Raised by `require`. Carries REFUSAL and nothing else."""


def operator_accounts(dsn: Optional[str] = None) -> frozenset[int]:
    """Every account id the column names.

    For humans and tests -- the CLI printing who is on, an assertion
    about a whole database. THE GATE DOES NOT USE IT: `manual_lane_allowed`
    asks about one account id, because a gate that builds a set is a gate
    that anything widening the set widens too.

    Empty is the normal, correct answer on any install where nobody has
    run the command -- see the fail-closed rule.
    """
    try:
        with connect(dsn) as conn:
            rows = conn.execute(
                f"SELECT id FROM accounts WHERE {OPERATOR_COLUMN}").fetchall()
            return frozenset(int(r["id"]) for r in rows)
    except Exception:
        # No accounts table, no column, no database: a fresh install and
        # a broken one both mean nobody, never everybody.
        return frozenset()


def manual_lane_allowed(account_id: Optional[int], dsn: Optional[str] = None) -> bool:
    """THE gate. True only for an account whose own row says so.

    `None` -- the unowned pool a fresh database hands a CLI -- is never
    allowed: "nobody owns these rows" is not evidence that the person at
    the keyboard owns the subscription.

    One row, asked for by id. Nothing about MEMBERSHIP is consulted, and
    that is the point: being a member of an account -- even by the
    operator, even to debug something -- must not make that account an
    operator account.
    """
    if account_id is None:
        return False
    try:
        wanted = int(account_id)
    except (TypeError, ValueError):
        return False
    try:
        with connect(dsn) as conn:
            row = conn.execute(
                f"SELECT {OPERATOR_COLUMN} FROM accounts WHERE id = %s",
                (wanted,)).fetchone()
            return bool(row and row[OPERATOR_COLUMN])
    except Exception:
        return False


def require(account_id: Optional[int], dsn: Optional[str] = None) -> None:
    """`manual_lane_allowed`, as a raise. For call sites where letting
    the refusal fall through a boolean is how a surface forgets."""
    if not manual_lane_allowed(account_id, dsn=dsn):
        raise LaneRefused(REFUSAL)


def is_subscription_source(source: Optional[str]) -> bool:
    """Whether this `params.source` means the clip was paid for by a
    subscription rather than per call. `src/ledger.py` is the caller
    that matters."""
    return bool(source) and source in SUBSCRIPTION_SOURCES


__all__ = [
    "OPERATOR_COLUMN", "OPERATOR_COMMAND", "REFUSAL", "SOURCE", "LANES",
    "SUBSCRIPTION_SOURCES", "LANE_RATIO", "LANE_DURATION",
    "LaneRefused", "operator_accounts", "manual_lane_allowed", "require",
    "is_subscription_source",
]

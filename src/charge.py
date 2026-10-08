"""
One render's credit hold, carried from the layer that records the
generation into the layer that submits it (2026-09-18, phase 1 of
docs/tasks/task-stripe-billing.md -- the wiring `ledger.hold_for_render`
was written for and nothing called).

THE SANDWICH, and where each slice lives:

    charge = Charge(...)              # generate_for_shot / generate_candidates:
                                      #   the layer that will write the row
    charge.take()                     # generate_video, after the spend gate,
                                      #   BEFORE the submit -- InsufficientCredit
                                      #   here means no HTTP call is ever made
    charge.submitted()                # generate_video, the LAST line before
                                      #   the provider call
    <provider submit>
    charge.release("...")             # generate_video, on any raise after
                                      #   take(): the customer pays nothing
    generative.record_failure(...)    # back in the caller, when the raise
                                      #   came after submitted()
                                      #   (`charge.attempted`): every attempt
                                      #   is a row, a failed one included
    charge.settle(actual, gen_id)     # back in the caller, once the
                                      #   generations row exists -- the link
                                      #   from money to clip

WHY AN OBJECT AND NOT FOUR CALLS AT THE CALL SITE. `generate_video` is
the raising thin wrapper in every adapter and the one place the spend
gate lives ("so no caller can spend around it"); the hold has to live
there too, or a path that calls `generate_video` directly -- the CLI, the
nightly graph, `generate_candidates` -- would render for free. But the
generation id the settle needs only exists in the CALLER, after the row
is written. So the caller builds the Charge and hands it down; a caller
that hands nothing down gets one built inside `generate_video` from its
own arguments and settled there, at the estimate, with no generation
link -- charged, which is the failure mode we can live with, rather
than free, which is the one we cannot.

WHAT IS HELD (2026-09-21). When the route verified a signed quote it
hands the `pricing.Quote` down (`generate_for_shot(..., quote=)` ->
`Charge(quote=)`), and `take()` holds `quote.credits` -- the number the
person was shown and the server signed -- and `settle()` closes at it.
Before that the route verified the Quote and dropped it, and the hold
re-derived the price from the adapter's estimate: the same number only
because both went through `pricing.credits_for`. The estimate is still
the fallback for callers nobody quoted: the nightly graph, the CLI.
A Quote for another account or provider raises in `take()`, before the
hold and so before the submit.

WHAT IS NOT CHARGED, decided in ONE place and not here: `ledger.
hold_for_render` returns None on a manual-lane import and for a
credit-exempt account (the operator), and every method below is a
no-op on a Charge with no hold. (BYOK renders took no hold either until
2026-09-26, when BYOK was removed: every other render holds.)
`settle` is capped at what was held -- the quoted price is the price
rendered, and an estimator that guessed low is our error, not the
customer's (task-pricing-and-quotes.md, "the ledger sandwich").

`ref` IS THE IDEMPOTENCY KEY, and it is the output file's name: unique
per attempt, already written into the generations row's `output_path`,
and merged into its params through `ledger.ref_params` so the reaper can
match a hold to the row it paid for.
"""

from __future__ import annotations

import contextvars
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import ledger

# WHO IS TOLD WHAT A RENDER COST (2026-10-08, the studio's activity tray).
# A job never learned what it spent: the hold's ref is the output file's
# name, which the job never sees, and no route lists ledger entries. So the
# job runner (app/jobs.py) binds a listener here, in its worker thread, and
# every Charge made inside that job reports to it as it moves:
#
#   ("hold",    held, held,  True)   the credits taken before the submit
#   ("settle",  debited, held, True) what the hold closed at
#   ("release", 0, held, True)       the hold given back
#   ("spent",   would, 0, False)     an UNCHARGED render that ran (the
#                                    operator's exempt account): what it
#                                    would have cost, as the Queue shows it
#
# A contextvar, like spend.bind's, so a thread started with a copied context
# (scene_chain's parallel keyframes) still reports to its job. A listener
# that raises is ignored: this is bookkeeping beside the money, never on it.
Meter = Callable[[str, int, int, bool], None]
_meter: contextvars.ContextVar[Optional[Meter]] = contextvars.ContextVar("charge_meter", default=None)


def metering(listener: Optional[Meter]) -> contextvars.Token:
    """Report every Charge in this context to `listener`; returns the
    token to reset with."""
    return _meter.set(listener)


def _tell(event: str, credits: int, held: int, charged: bool) -> None:
    listener = _meter.get()
    if listener is None:
        return
    try:
        listener(event, int(credits or 0), int(held or 0), charged)
    except Exception:  # noqa: BLE001 -- never let the tray touch the money path
        pass


class Charge:
    __slots__ = ("account_id", "provider", "ref", "estimate_usd", "key_source",
                 "source", "dsn", "quote", "hold_id", "held", "attempted", "_done")

    def __init__(self, account_id: Optional[int], *, provider: str, ref: str,
                 estimate_usd, key_source: Optional[str] = None,
                 source: Optional[str] = None, dsn: Optional[str] = None,
                 quote=None):
        self.account_id = account_id
        self.provider = provider
        self.ref = str(ref)
        self.estimate_usd = estimate_usd
        self.key_source = key_source
        self.source = source
        self.dsn = dsn
        # The verified pricing.Quote the route has in hand, or None. When
        # there is one, IT is what is held and settled -- the number the
        # person was shown and the server signed -- and the estimate is
        # only the fallback for callers nobody quoted (the nightly graph,
        # the CLI). Duck-typed: this module never imports
        # pricing (pricing -> providers -> the adapters -> here).
        self.quote = quote
        self.hold_id: Optional[int] = None
        self.held: int = 0
        # True once submitted() ran -- i.e. the provider was about to be
        # called, hold or no hold (exempt renders submit too). It
        # is how the caller that writes the generations row knows a raise
        # out of generate_video was an ATTEMPT, which owes a row, and not
        # a gate or an empty balance, which does not (BACKLOG #18).
        self.attempted = False
        self._done = False

    # -- the four slices ----------------------------------------------------

    def take(self) -> Optional[int]:
        """Hold the Quote's credits when one is in hand, else the estimate;
        or raise ledger.InsufficientCredit / LedgerError.
        Idempotent: a second call returns the first hold."""
        if self.hold_id is not None:
            return self.hold_id
        if self.account_id is not None:
            # the ledger's tables exist only once something has made them;
            # app startup does, a route's test may not have
            ledger.init(self.dsn)
            # a yearly plan's month that is due lands BEFORE the balance is
            # read: a dead cron must not refuse a render somebody paid for.
            # Best-effort here -- the hold below is the money path, and a
            # release that fails is picked up by the next run.
            try:
                from . import billing
                billing.release_due(self.account_id, dsn=self.dsn)
            except Exception as e:  # pragma: no cover - logged, never fatal
                print(f"[charge] release_due failed for account {self.account_id}: {e}",
                      file=sys.stderr)
        credits = self._quoted()
        self.hold_id = ledger.hold_for_render(
            self.account_id, ref=self.ref, provider=self.provider,
            estimate_usd=self.estimate_usd, key_source=self.key_source,
            source=self.source, credits=credits, dsn=self.dsn)
        if self.hold_id is not None:
            self.held = (credits if credits is not None
                         else ledger.charge_credits(self.estimate_usd))
            _tell("hold", self.held, self.held, True)
        return self.hold_id

    def _quoted(self) -> Optional[int]:
        """The Quote's credits, or None to fall back to the estimate.
        A Quote for another account or another provider is a caller's bug
        and is refused HERE, before the hold and so before the submit:
        holding a price somebody else was quoted is not a rounding error."""
        if self.quote is None:
            return None
        if (self.quote.account_id != self.account_id
                or self.quote.provider != self.provider):
            raise ledger.LedgerError(
                f"this quote is for account {self.quote.account_id!r} on "
                f"{self.quote.provider!r}, not account {self.account_id!r} on "
                f"{self.provider!r} -- nothing was held or submitted")
        return int(self.quote.credits)

    def submitted(self) -> None:
        """The last line before the provider call."""
        self.attempted = True
        if self.hold_id is not None:
            ledger.mark_submitted(self.hold_id, dsn=self.dsn)

    def settle(self, actual_usd=None, *, generation_id: Optional[int] = None) -> int:
        """Close the hold at the actual cost (the estimate when None),
        never above what was held. Returns credits debited, 0 when
        nothing was held. Idempotent through the ledger's own guard."""
        if self._done:
            return 0
        if self.hold_id is None:
            # nothing held -- the operator's exempt account, the unowned
            # pool. A render that RAN still says what it would have cost,
            # marked not charged, so the tray agrees with the Queue's
            # "87 cr · not charged"; one that never reached the provider
            # says nothing.
            if self.attempted:
                self._done = True
                _tell("spent", self._would_cost(), 0, False)
            return 0
        self._done = True
        if actual_usd is None and self.quote is not None:
            credits = self.held          # the quoted price is the price rendered
        else:
            usd = self.estimate_usd if actual_usd is None else actual_usd
            credits = ledger.charge_credits(usd)
        debited = ledger.settle(self.hold_id, credits=credits,
                                generation_id=generation_id, cap=self.held, dsn=self.dsn)
        _tell("settle", debited, self.held, True)
        return debited

    def _would_cost(self) -> int:
        """What this render would have held: the Quote's credits, else the
        estimate's. 0 when neither can be priced."""
        try:
            if self.quote is not None:
                return int(self.quote.credits)
            return int(ledger.charge_credits(self.estimate_usd))
        except Exception:  # noqa: BLE001 -- an unpriceable render costs nothing to say
            return 0

    def release(self, reason: str) -> int:
        """Give the whole hold back. Returns credits restored."""
        if self.hold_id is None or self._done:
            return 0
        self._done = True
        restored = ledger.release(self.hold_id, reason, dsn=self.dsn)
        _tell("release", 0, self.held, True)
        return restored

    # -- bookkeeping ----------------------------------------------------------

    @property
    def billed(self) -> bool:
        return self.hold_id is not None

    def params(self) -> dict:
        """The fragment for the generations row -- `{"ledger_ref": ref}` when
        a hold was taken, nothing otherwise, so an unbilled row does not
        claim a hold the reaper will then look for."""
        return ledger.ref_params(self.ref) if self.hold_id is not None else {}


def attempt_ref(out_path) -> str:
    """A ref for an output path that is NOT unique per attempt.

    generate_for_shot and generate_from_prompt stamp their file names, so
    the name is the ref. generate_candidates writes `cand1.mp4` into
    whatever directory it is handed, every run -- and `ledger.hold` is
    idempotent on the ref, so the second night's `cand1.mp4` was handed
    the FIRST night's hold back, already settled, and rendered for
    nothing. The name plus the microsecond it was asked for is unique.
    """
    path = Path(out_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"{path.parent.name}-{path.stem}-{stamp}{path.suffix}"


def refusal(e: ledger.InsufficientCredit, what: str = "this render") -> str:
    """The message a route returns for an empty balance -- the same shape
    as generative.cap_error's: a sentence with the numbers in it and what
    to do, never a stack. `what` names the thing refused ("this scene",
    "this still") now that renders are not the only thing charged."""
    return (f"out of credits: {what} needs {e.requested} and the account has "
            f"{e.available} -- top up to continue")


CREATE_REFUSAL = ("Create is included with a plan -- subscribe or top up "
                  "credits to continue")


def create_refusal(account_id: Optional[int], *, dsn: Optional[str] = None) -> Optional[str]:
    """Why this account may not Create (write a scene), or None when it may.

    A Create costs no credits (2026-09-29, Mike's call: it is included in
    the subscription, its Gemini cost priced into the plans rather than
    debited per click). "Included" still needs something to be included
    IN: an account may Create while it has an active plan or any credit
    balance -- the 100-credit trial counts -- and is refused with
    CREATE_REFUSAL once it has neither. The operator's exempt accounts and
    the unowned pool (the CLI, the nightly walk) are never refused.

    Fails OPEN on a read error, with a stderr line: a Create is free per
    click, so a flaky balance read must not take the composer down; the
    renders and stills behind it still hold credit and still refuse."""
    if account_id is None:
        return None
    try:
        from . import accounts
        if accounts.is_credit_exempt(account_id, dsn=dsn):
            return None
        if accounts.plan_of(account_id, dsn=dsn):
            return None
        if ledger.available(account_id, dsn=dsn) > 0:
            return None
    except Exception as e:  # noqa: BLE001 -- see docstring
        import sys
        print(f"[charge] create gate unreadable for account {account_id}: {e}",
              file=sys.stderr)
        return None
    return CREATE_REFUSAL


__all__ = ["Charge", "CREATE_REFUSAL", "attempt_ref", "create_refusal", "refusal"]

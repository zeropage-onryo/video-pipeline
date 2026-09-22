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
the fallback for callers nobody quoted: the nightly graph, the CLI, a
BYOK click (which takes no hold anyway). A Quote for another account or
provider raises in `take()`, before the hold and so before the submit.

WHAT IS NOT CHARGED, decided in ONE place and not here: `ledger.
hold_for_render` returns None on BYOK, on a manual-lane import and for
a credit-exempt account (the operator), and every method below is a
no-op on a Charge with no hold. `settle` is capped at what was held --
the quoted price is the price rendered, and an estimator that guessed
low is our error, not the customer's (task-pricing-and-quotes.md, "the
ledger sandwich").

`ref` IS THE IDEMPOTENCY KEY, and it is the output file's name: unique
per attempt, already written into the generations row's `output_path`,
and merged into its params through `ledger.ref_params` so the reaper can
match a hold to the row it paid for.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import ledger


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
        # the CLI, a BYOK click). Duck-typed: this module never imports
        # pricing (pricing -> providers -> the adapters -> here).
        self.quote = quote
        self.hold_id: Optional[int] = None
        self.held: int = 0
        # True once submitted() ran -- i.e. the provider was about to be
        # called, hold or no hold (BYOK and exempt renders submit too). It
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
        if self.hold_id is None or self._done:
            return 0
        self._done = True
        if actual_usd is None and self.quote is not None:
            credits = self.held          # the quoted price is the price rendered
        else:
            usd = self.estimate_usd if actual_usd is None else actual_usd
            credits = ledger.charge_credits(usd)
        return ledger.settle(self.hold_id, credits=credits,
                             generation_id=generation_id, cap=self.held, dsn=self.dsn)

    def release(self, reason: str) -> int:
        """Give the whole hold back. Returns credits restored."""
        if self.hold_id is None or self._done:
            return 0
        self._done = True
        return ledger.release(self.hold_id, reason, dsn=self.dsn)

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


def refusal(e: ledger.InsufficientCredit) -> str:
    """The message a route returns for an empty balance -- the same shape
    as generative.cap_error's: a sentence with the numbers in it and what
    to do, never a stack."""
    return (f"out of credits: this render needs {e.requested} and the account has "
            f"{e.available} -- top up, or add your own renderer key to render on it")


__all__ = ["Charge", "attempt_ref", "refusal"]

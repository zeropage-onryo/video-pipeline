"""The exemption's refusal and failure paths (2026-09-18) -- the ones an
exempt operator never walks, and tests/test_charge.py does not.

test_charge.py proves the exemption WORKS: an exempt account takes no
hold, the flag flips both ways, the row is still written. Ported here
from the superseded PR #38 is what proves it cannot leak:

- nobody starts exempt, the bootstrap account included, and a database
  from before the column gains it FALSE (no backfill);
- every failure of the predicate reads NOT exempt -- "charged", never
  "free";
- it is ONE account's: exempting Mike's leaves a stranger refused;
- --off is a real way back: the operator is refused like anyone.
"""

import pytest

from src import accounts, db, generative, ledger


@pytest.fixture
def led(pg):
    generative.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    mine = accounts.upsert_account("zeropage", "Zero Page", dsn=pg)
    theirs = accounts.upsert_account("pilot", "A Pilot", dsn=pg)
    return pg, int(mine), int(theirs)


def ask(dsn, account, ref="render-1"):
    return ledger.hold_for_render(account, ref=ref, provider="runway",
                                  estimate_usd=0.25, key_source="env", dsn=dsn)


# guards: DEFAULT FALSE and the absence of any backfill
def test_nobody_starts_exempt_including_the_bootstrap_account(led):
    dsn, _, _ = led
    assert accounts.credit_exempt_accounts(dsn=dsn) == []
    with db.connect(dsn) as conn:
        ids = [int(r["id"]) for r in conn.execute("SELECT id FROM accounts")]
    assert len(ids) >= 2 and not any(ledger.credit_exempt(i, dsn=dsn) for i in ids)


# guards: the additive ALTER in db.add_billing_columns
def test_a_database_from_before_the_column_gains_it_false(led):
    dsn, mine, _ = led
    with db.connect(dsn) as conn:
        conn.execute("ALTER TABLE accounts DROP COLUMN credit_exempt")
    assert ledger.credit_exempt(mine, dsn=dsn) is False    # no column: a no, not a raise
    assert accounts.credit_exempt_accounts(dsn=dsn) == []
    with db.connect(dsn) as conn:
        assert db.CREDIT_EXEMPT_COLUMN in db.add_billing_columns(conn)
        assert db.CREDIT_EXEMPT_COLUMN not in db.add_billing_columns(conn)
    assert ledger.credit_exempt(mine, dsn=dsn) is False


# guards: every early return and the except in accounts.is_credit_exempt
def test_every_failure_reads_as_charged_never_free(led):
    dsn, mine, _ = led
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ledger.credit_exempt(mine, dsn=dsn) is True
    assert ledger.credit_exempt(None, dsn=dsn) is False
    assert ledger.credit_exempt("mine", dsn=dsn) is False
    assert ledger.credit_exempt(10_000_000, dsn=dsn) is False        # no such account
    assert ledger.credit_exempt(mine, dsn="postgresql://localhost:1/none") is False


# guards: the hold() call in hold_for_render -- THE refusal at zero credit
def test_a_non_exempt_account_with_no_credit_is_refused_and_nothing_is_held(led):
    dsn, _, theirs = led
    with pytest.raises(ledger.InsufficientCredit):
        ask(dsn, theirs)
    assert ledger.entries(theirs, dsn, ref="render-1") == []


# guards: the predicate asking about THIS account's row
def test_exempting_one_account_exempts_only_that_one(led):
    dsn, mine, theirs = led
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ask(dsn, mine) is None
    assert ledger.entries(mine, dsn) == []
    with pytest.raises(ledger.InsufficientCredit):
        ask(dsn, theirs)


def test_an_exempt_account_with_credit_keeps_it(led):
    dsn, mine, _ = led
    ledger.grant(mine, 500, "promo", dsn=dsn)
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ask(dsn, mine) is None
    assert ledger.available(mine, dsn) == 500


# guards: --off being a real way back. An untested way back is not one.
def test_turning_it_off_puts_the_operator_in_front_of_the_refusal(led):
    dsn, mine, _ = led
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ask(dsn, mine) is None
    accounts.set_credit_exempt("zeropage", False, dsn=dsn)
    with pytest.raises(ledger.InsufficientCredit):
        ask(dsn, mine)


# guards: charge_credits in hold_for_render -- the CHARGE is held, not the cost
def test_a_charged_render_holds_the_marked_up_figure(led):
    dsn, _, theirs = led
    ledger.grant(theirs, 500, "purchase", dsn=dsn)
    assert isinstance(ask(dsn, theirs), int)
    assert ledger.charge_credits(0.25) == 60 != ledger.credits_for_usd(0.25)
    assert ledger.available(theirs, dsn) == 440

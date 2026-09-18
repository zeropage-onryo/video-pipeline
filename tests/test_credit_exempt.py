"""The operator's credit exemption (2026-09-18, Mike's call: zero credit
refuses a render on the operator's key, and his own accounts are the
exemption). docs/tasks/task-pricing-and-quotes.md, "Step 6 design".

What is proven here:

- the gate is `accounts.credit_exempt`, FALSE for everyone -- the
  bootstrap account included -- until `python -m src.accounts credits
  <slug> --on`; the unowned pool and every failure read as NOT exempt;
- it is applied inside ledger.hold_for_render, after the BYOK question
  and before the hold, and nowhere else;
- THE REFUSAL PATH, which an exempt operator never walks: a non-exempt
  account with no credit is refused, and turning the flag back off puts
  the operator in front of the same refusal.
"""

import pytest

from src import accounts, db, generative, ledger, manual_lane


@pytest.fixture
def led(pg):
    accounts.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    generative.init(pg)
    ledger.init(pg)
    mine = accounts.upsert_account("zeropage", "Zero Page", dsn=pg)
    theirs = accounts.upsert_account("pilot", "A Pilot", dsn=pg)
    return pg, int(mine), int(theirs)


def ask(dsn, account, **kw):
    kw.setdefault("key_source", "env")
    return ledger.hold_for_render(account, ref="render-1", provider="runway",
                                  credits=60, dsn=dsn, **kw)


# guards: no backfill in add_credit_exempt_column, and DEFAULT FALSE
def test_nobody_starts_exempt_including_the_bootstrap_account(led):
    dsn, mine, theirs = led
    assert accounts.credit_exempt_accounts(dsn=dsn) == []
    with db.connect(dsn) as conn:
        ids = [int(r["id"]) for r in conn.execute("SELECT id FROM accounts")]
    assert len(ids) >= 2 and not any(ledger.credit_exempt(i, dsn) for i in ids)


# guards: the additive ALTER, for a database that predates the column
def test_a_database_from_before_the_column_gains_it_false(led):
    dsn, mine, _ = led
    with db.connect(dsn) as conn:
        conn.execute("ALTER TABLE accounts DROP COLUMN credit_exempt")
    assert ledger.credit_exempt(mine, dsn) is False      # no column: a no, not a raise
    with db.connect(dsn) as conn:
        assert db.add_credit_exempt_column(conn) is True
        assert db.add_credit_exempt_column(conn) is False
    assert ledger.credit_exempt(mine, dsn) is False


def test_the_cli_verb_is_idempotent_two_way_and_names_the_account(led, capsys, monkeypatch):
    dsn, mine, _ = led
    monkeypatch.setenv("DATABASE_URL", dsn)
    result = accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert result == {"slug": "zeropage", "account_id": mine,
                      "was": False, "now": True, "changed": True}
    assert accounts.set_credit_exempt("zeropage", True, dsn=dsn)["changed"] is False
    assert accounts.credit_exempt_accounts(dsn=dsn) == [
        {"account_id": mine, "slug": "zeropage"}]
    accounts.main(["credits", "zeropage", "--off"])
    assert "ON -> OFF" in capsys.readouterr().out
    assert ledger.credit_exempt(mine, dsn) is False
    with pytest.raises(ValueError):
        accounts.set_credit_exempt("nobody", True, dsn=dsn)


# guards: every early return and the except in ledger.credit_exempt
def test_it_fails_closed(led):
    dsn, mine, _ = led
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ledger.credit_exempt(mine, dsn) is True
    assert ledger.credit_exempt(None, dsn) is False           # the unowned pool
    assert ledger.credit_exempt("mine", dsn) is False
    assert ledger.credit_exempt(10_000_000, dsn) is False     # no such account
    assert ledger.credit_exempt(mine, "postgresql://localhost:1/none") is False


# guards: the hold() call in hold_for_render -- THE refusal, which the
# exempt operator never walks
def test_a_non_exempt_account_with_no_credit_is_refused(led):
    dsn, _, theirs = led
    with pytest.raises(ledger.InsufficientCredit):
        ask(dsn, theirs)
    assert ledger.entries(theirs, dsn, ref="render-1") == []


# guards: the credit_exempt line in hold_for_render
def test_an_exempt_account_renders_at_zero_credit_and_nothing_is_held(led):
    dsn, mine, theirs = led
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ask(dsn, mine) == ledger.RenderHold(None, "exempt")
    assert ledger.entries(mine, dsn) == []
    # and it is THIS account's, not everybody's
    with pytest.raises(ledger.InsufficientCredit):
        ask(dsn, theirs)


def test_an_exempt_account_with_credit_keeps_it(led):
    dsn, mine, _ = led
    ledger.grant(mine, 500, "promo", dsn=dsn)
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ask(dsn, mine).reason == "exempt"
    assert ledger.available(mine, dsn) == 500


# guards: --off being a real way back
def test_turning_it_off_puts_the_operator_in_front_of_the_refusal(led):
    dsn, mine, _ = led
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ask(dsn, mine).reason == "exempt"
    accounts.set_credit_exempt("zeropage", False, dsn=dsn)
    with pytest.raises(ledger.InsufficientCredit):
        ask(dsn, mine)


# guards: is_billable being asked BEFORE credit_exempt
def test_an_exempt_account_on_its_own_key_is_still_byok(led):
    dsn, mine, _ = led
    accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert ask(dsn, mine, key_source="account") == ledger.RenderHold(None, "byok")
    assert ask(dsn, mine, key_source=None, source=manual_lane.SOURCE).reason == "subscription"


# guards: `credits` being what is held, and NOT reconciled against the
# 1.0x estimate inside hold()
def test_a_charged_render_holds_the_quotes_credits_not_the_estimates(led):
    dsn, _, theirs = led
    ledger.grant(theirs, 500, "purchase", dsn=dsn)
    held = ledger.hold_for_render(theirs, ref="render-2", provider="runway",
                                  estimate_usd=0.25, credits=60, key_source="env", dsn=dsn)
    assert held.reason == "held" and isinstance(held.hold_id, int)
    assert ledger.available(theirs, dsn) == 440          # 60, not credits_for_usd(0.25) == 25


def test_the_row_marker_says_what_it_would_have_cost():
    assert ledger.exempt_params(60) == {"credit_exempt": True, "quote_credits": 60}
    assert ledger.exempt_params(None) == {"credit_exempt": True, "quote_credits": None}

"""
The prepaid credit ledger (src/ledger.py, docs/CREDIT_LEDGER_DESIGN.md).

Every test here runs against the throwaway Postgres, and the reason is
the first one: the atomicity test is the point of the module, and a
mocked lock proves nothing about a lock. `pg` gives each test its own
schema, so the concurrency test can take a real `pg_advisory_xact_lock`
on a real connection in a real second thread without any other test
seeing it.
"""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from src import accounts, db, generative, ledger
from src.shot import Shot


@pytest.fixture
def led(pg):
    """A ledger on a seeded schema, and the account that owns it.

    Seeded rather than run against the unowned pool, because the FOREIGN
    KEY db.own_table declares means an account_id has to exist -- and
    because "whose credit is this" is the question the whole module is
    about.
    """
    accounts.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    generative.init(pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"]
    return pg, int(account_id)


def _stamp(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------
# the unit
# --------------------------------------------------------------------------

def test_dollars_become_credits_by_rounding_up():
    """A cent is the unit and the half-cent always goes to the house.
    Rounded down, the fraction eaten on each of ten thousand renders is
    real money that appears in no row."""
    assert ledger.credits_for_usd(0) == 0
    assert ledger.credits_for_usd(0.29) == 29
    assert ledger.credits_for_usd(1) == 100
    assert ledger.credits_for_usd(0.4501) == 46
    assert ledger.credits_for_usd(0.001) == 1
    assert ledger.credits_for_usd("2.675") == 268


def test_a_price_that_is_not_a_price_raises():
    for bad in (None, "banana", -1.0):
        with pytest.raises(ledger.LedgerError):
            ledger.credits_for_usd(bad)


# --------------------------------------------------------------------------
# grant
# --------------------------------------------------------------------------

def test_a_grant_shows_up_as_available_credit(led):
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    assert ledger.available(account, dsn) == 500


def test_a_webhook_delivered_twice_grants_once(led):
    """Stripe delivers at least once. The unique index on
    (account_id, kind, source_ref) is what makes the second delivery a
    no-op instead of a free 500 credits."""
    dsn, account = led
    first = ledger.grant(account, 500, "purchase", source_ref="pi_abc", dsn=dsn)
    second = ledger.grant(account, 500, "purchase", source_ref="pi_abc", dsn=dsn)
    assert first == second
    assert ledger.available(account, dsn) == 500
    assert len(ledger.lots(account, dsn)) == 1


def test_a_grant_defaults_to_two_months(led):
    dsn, account = led
    ledger.grant(account, 100, "subscription", granted_at="2026-09-08T12:00:00+00:00",
                 dsn=dsn)
    assert ledger.lots(account, dsn)[0]["expires_at"].startswith("2026-11-08")


def test_the_expiry_month_arithmetic_clamps_the_day(led):
    """31 December + 2 months is 28 February, not 3 March. A lot must
    never expire LATER than the policy says."""
    dsn, account = led
    ledger.grant(account, 100, "promo", granted_at="2026-12-31T12:00:00+00:00", dsn=dsn)
    assert ledger.lots(account, dsn)[0]["expires_at"].startswith("2027-02-28")


def test_a_nonsense_grant_raises_rather_than_writing_something_odd(led):
    dsn, account = led
    with pytest.raises(ledger.LedgerError):
        ledger.grant(account, 0, "subscription", dsn=dsn)
    with pytest.raises(ledger.LedgerError):
        ledger.grant(account, -5, "subscription", dsn=dsn)
    with pytest.raises(ledger.LedgerError):
        ledger.grant(account, 100, "vibes", dsn=dsn)
    assert ledger.available(account, dsn) == 0


# --------------------------------------------------------------------------
# hold: atomicity, the point of the whole exercise
# --------------------------------------------------------------------------

def test_two_simultaneous_holds_on_one_balance_that_fits_one(led, monkeypatch):
    """THE TEST THIS MODULE EXISTS FOR.

    Real threads, real connections, the real advisory lock. The
    read-then-act window is widened by making the balance read sleep,
    so a hold WITHOUT `pg_advisory_xact_lock` would deterministically
    let both threads read 500 and both insert -- which is exactly the
    bug `generative.cap_error` still has, where two simultaneous
    approvals both pass a cap of six. Mocked, this test would pass
    against no lock at all.
    """
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)

    real_available = ledger._available

    def slow_available(conn, account_id, now=None):
        value = real_available(conn, account_id, now)
        time.sleep(0.4)
        return value

    monkeypatch.setattr(ledger, "_available", slow_available)

    barrier = threading.Barrier(2)
    results: list = [None, None]

    def take(i):
        barrier.wait()
        try:
            results[i] = ledger.hold(account, 400, ref=f"render-{i}",
                                     provider="runway", dsn=dsn)
        except Exception as e:                       # noqa: BLE001 - recorded, asserted below
            results[i] = e

    threads = [threading.Thread(target=take, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    won = [r for r in results if isinstance(r, int)]
    lost = [r for r in results if isinstance(r, ledger.InsufficientCredit)]
    assert len(won) == 1, f"expected exactly one winner, got {results}"
    assert len(lost) == 1, f"expected exactly one refusal, got {results}"
    assert ledger.available(account, dsn) == 100
    assert ledger.outstanding(account, dsn) == 400


def test_a_retried_hold_with_the_same_ref_debits_once(led):
    """`ref` is the idempotency key: a caller that retries across a
    network blip gets the same hold back, not a second debit."""
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    first = ledger.hold(account, 200, ref="render-7", provider="runway", dsn=dsn)
    second = ledger.hold(account, 200, ref="render-7", provider="runway", dsn=dsn)
    assert first == second
    assert ledger.available(account, dsn) == 300
    assert len([e for e in ledger.entries(account, dsn) if e["kind"] == "hold"]) == 1


def test_a_hold_that_does_not_fit_raises_insufficient_credit(led):
    dsn, account = led
    ledger.grant(account, 100, "subscription", dsn=dsn)
    with pytest.raises(ledger.InsufficientCredit) as caught:
        ledger.hold(account, 101, ref="render-1", provider="veo", dsn=dsn)
    assert caught.value.requested == 101
    assert caught.value.available == 100
    assert ledger.available(account, dsn) == 100


def test_the_hold_and_the_estimate_have_to_be_the_same_number(led):
    """One conversion site means one conversion. A caller that converts
    its own dollars and passes both is told, rather than silently
    holding a number that does not match the estimate the reaper will
    read back."""
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    with pytest.raises(ledger.LedgerError):
        ledger.hold(account, 100, ref="r", provider="runway", estimate_usd=2.00, dsn=dsn)


def test_a_hold_needs_a_ref(led):
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    with pytest.raises(ledger.LedgerError):
        ledger.hold(account, 10, ref="", provider="runway", dsn=dsn)


# --------------------------------------------------------------------------
# consumption order
# --------------------------------------------------------------------------

def test_credit_burns_soonest_expiry_first_across_lots(led):
    """"Your monthly allowance burns before the credit you paid for" is
    true because of the ORDER BY, not because anybody remembers it."""
    dsn, account = led
    late = ledger.grant(account, 300, "purchase", expires_at=_stamp(60), dsn=dsn)
    soon = ledger.grant(account, 200, "subscription", expires_at=_stamp(5), dsn=dsn)
    middle = ledger.grant(account, 100, "promo", expires_at=_stamp(30), dsn=dsn)

    ledger.hold(account, 250, ref="render-1", provider="runway", dsn=dsn)

    remaining = {lot["id"]: lot["credits_remaining"] for lot in ledger.lots(account, dsn)}
    assert remaining[soon] == 0       # emptied first
    assert remaining[middle] == 50    # then the next to expire
    assert remaining[late] == 300     # the cash lot is untouched


def test_one_hold_may_span_several_lots(led):
    dsn, account = led
    ledger.grant(account, 100, "subscription", expires_at=_stamp(5), dsn=dsn)
    ledger.grant(account, 100, "purchase", expires_at=_stamp(50), dsn=dsn)
    hold_id = ledger.hold(account, 150, ref="render-1", provider="veo", dsn=dsn)
    held = [e for e in ledger.entries(account, dsn, ref="render-1") if e["kind"] == "hold"]
    assert [e["delta"] for e in held] == [-100, -50]
    assert hold_id == held[0]["id"]
    assert ledger.available(account, dsn) == 50


# --------------------------------------------------------------------------
# settle and release
# --------------------------------------------------------------------------

def test_settle_adjusts_the_debit_to_what_it_actually_cost(led):
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway",
                          estimate_usd=3.00, dsn=dsn)
    assert ledger.settle(hold_id, 3.00, generation_id=11, dsn=dsn) == 300
    assert ledger.available(account, dsn) == 700
    assert ledger.outstanding(account, dsn) == 0
    settles = [e for e in ledger.entries(account, dsn, ref="render-1")
               if e["kind"] == "settle"]
    assert settles and all(e["generation_id"] == 11 for e in settles)


def test_an_over_estimate_refunds_the_difference(led):
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    ledger.settle(hold_id, 1.20, generation_id=12, dsn=dsn)
    assert ledger.available(account, dsn) == 880


def test_a_refund_goes_back_to_the_lots_it_came_from(led):
    """Reverse order of consumption, capped at what each lot gave -- a
    refund must not put credit onto a lot that never funded the hold."""
    dsn, account = led
    soon = ledger.grant(account, 100, "subscription", expires_at=_stamp(5), dsn=dsn)
    late = ledger.grant(account, 100, "purchase", expires_at=_stamp(50), dsn=dsn)
    hold_id = ledger.hold(account, 150, ref="render-1", provider="veo", dsn=dsn)
    ledger.settle(hold_id, 1.10, dsn=dsn)          # 110 credits actual, 40 back
    remaining = {lot["id"]: lot["credits_remaining"] for lot in ledger.lots(account, dsn)}
    assert remaining[soon] == 0        # the lot that gave 100 is still empty
    assert remaining[late] == 90       # the 40 came back to the lot that gave 50


def test_an_under_estimate_overdraws_and_the_next_hold_is_refused(led):
    """The money is already spent. Recording anything else is the lie
    that breaks reconciliation, so the balance goes negative and the
    NEXT hold is what refuses."""
    dsn, account = led
    ledger.grant(account, 300, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    ledger.settle(hold_id, 5.00, generation_id=13, dsn=dsn)      # 500 actual
    assert ledger.available(account, dsn) == -200
    with pytest.raises(ledger.InsufficientCredit):
        ledger.hold(account, 1, ref="render-2", provider="runway", dsn=dsn)


def test_an_extra_debit_is_taken_in_the_ordinary_order(led):
    """A settle that beat its estimate is an ORDINARY debit: soonest
    expiry first, exactly as a hold allocates. The first version put it
    all on the last lot the hold touched, which meant a render that
    over-ran drove the customer's PURCHASED credit negative while an
    already-empty subscription lot sat at zero -- the debt landing on
    the credit they still owned rather than the credit they were
    spending.
    """
    dsn, account = led
    soon = ledger.grant(account, 100, "subscription", expires_at=_stamp(5), dsn=dsn)
    later = ledger.grant(account, 100, "promo", expires_at=_stamp(20), dsn=dsn)
    cash = ledger.grant(account, 500, "purchase", expires_at=_stamp(50), dsn=dsn)

    hold_id = ledger.hold(account, 100, ref="render-1", provider="runway", dsn=dsn)
    ledger.settle(hold_id, 2.50, dsn=dsn)          # 250 actual against a 100 hold

    remaining = {lot["id"]: lot["credits_remaining"] for lot in ledger.lots(account, dsn)}
    assert remaining[soon] == 0, "the hold emptied it and the extra debit moved on"
    assert remaining[later] == 0, "the next-to-expire lot absorbed the overrun"
    assert remaining[cash] == 450, "purchased credit gave up only what was left to give"
    assert ledger.available(account, dsn) == 450


def test_a_true_overdraft_lands_on_the_soonest_expiring_lot_the_hold_used(led):
    """When nothing is left anywhere -- the usual case, since the hold
    just emptied those lots -- the debt has no lot with credit to sit
    on. It goes where the burn-down was, which is also the lot whose
    expiry `_available` clamps from above only, so the debt survives
    instead of evaporating with it."""
    dsn, account = led
    soon = ledger.grant(account, 60, "subscription", expires_at=_stamp(5), dsn=dsn)
    later = ledger.grant(account, 40, "purchase", expires_at=_stamp(50), dsn=dsn)

    hold_id = ledger.hold(account, 100, ref="render-1", provider="runway", dsn=dsn)
    ledger.settle(hold_id, 3.00, dsn=dsn)          # 300 actual, 200 of it overdrawn

    remaining = {lot["id"]: lot["credits_remaining"] for lot in ledger.lots(account, dsn)}
    assert remaining[soon] == -200, "the debt sits with the credit that was being spent"
    assert remaining[later] == 0
    assert ledger.available(account, dsn) == -200
    assert all(r["drift"] == 0 for r in ledger.reconcile(account, dsn))


def test_a_debt_survives_the_expiry_of_the_lot_it_sits_on(led):
    """The other half of choosing the soonest-expiring lot: an expired
    lot is clamped to zero from ABOVE only, so parking a debt there is
    safe. If it were clamped both ways, an overdrawn customer would
    wait two months for the debt to evaporate."""
    dsn, account = led
    ledger.grant(account, 100, "subscription", expires_at=_stamp(1), dsn=dsn)
    hold_id = ledger.hold(account, 100, ref="render-1", provider="runway", dsn=dsn)
    ledger.settle(hold_id, 3.00, dsn=dsn)
    with db.connect(dsn) as conn:
        conn.execute("UPDATE credit_lots SET expires_at = %s "
                     "WHERE account_id IS NOT DISTINCT FROM %s", (_stamp(-1), account))
    assert ledger.available(account, dsn) == -200


def test_release_restores_the_whole_hold(led):
    dsn, account = led
    ledger.grant(account, 100, "subscription", expires_at=_stamp(5), dsn=dsn)
    ledger.grant(account, 100, "purchase", expires_at=_stamp(50), dsn=dsn)
    hold_id = ledger.hold(account, 150, ref="render-1", provider="veo", dsn=dsn)
    assert ledger.release(hold_id, "provider error: 500", dsn=dsn) == 150
    assert ledger.available(account, dsn) == 200
    assert ledger.outstanding(account, dsn) == 0
    assert all(lot["credits_remaining"] == 100 for lot in ledger.lots(account, dsn))


def test_release_is_idempotent_and_a_settled_hold_cannot_be_released(led):
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    a = ledger.hold(account, 100, ref="render-1", provider="veo", dsn=dsn)
    ledger.release(a, "timeout", dsn=dsn)
    ledger.release(a, "timeout", dsn=dsn)             # second call changes nothing
    assert ledger.available(account, dsn) == 500

    b = ledger.hold(account, 100, ref="render-2", provider="veo", dsn=dsn)
    ledger.settle(b, 1.00, dsn=dsn)
    with pytest.raises(ledger.LedgerError):
        ledger.release(b, "too late", dsn=dsn)


def test_a_release_without_a_reason_is_refused(led):
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 100, ref="render-1", provider="veo", dsn=dsn)
    with pytest.raises(ledger.LedgerError):
        ledger.release(hold_id, "", dsn=dsn)


def test_settling_a_hold_that_does_not_exist_raises(led):
    dsn, _ = led
    with pytest.raises(ledger.LedgerError):
        ledger.settle(4242, 1.00, dsn=dsn)


# --------------------------------------------------------------------------
# expiry and lapse
# --------------------------------------------------------------------------

def test_an_expired_lot_contributes_nothing_before_anyone_sweeps(led):
    """Enforced on READ, so the balance is right in the window between
    the date passing and expire_due() running."""
    dsn, account = led
    ledger.grant(account, 400, "subscription", expires_at=_stamp(-1), dsn=dsn)
    ledger.grant(account, 100, "purchase", expires_at=_stamp(30), dsn=dsn)
    assert ledger.available(account, dsn) == 100
    with pytest.raises(ledger.InsufficientCredit):
        ledger.hold(account, 200, ref="render-1", provider="runway", dsn=dsn)


def test_expire_due_sweeps_past_date_lots_and_leaves_a_trail(led):
    dsn, account = led
    stale = ledger.grant(account, 400, "subscription", expires_at=_stamp(-1), dsn=dsn)
    ledger.grant(account, 100, "purchase", expires_at=_stamp(30), dsn=dsn)

    assert ledger.expire_due(dsn=dsn) == 400
    assert ledger.available(account, dsn) == 100
    expired = [e for e in ledger.entries(account, dsn) if e["kind"] == "expire"]
    assert [(e["lot_id"], e["delta"]) for e in expired] == [(stale, -400)]
    # the lot is still there, carrying its history -- never zeroed in place
    lot = [x for x in ledger.lots(account, dsn) if x["id"] == stale][0]
    assert lot["credits_granted"] == 400 and lot["credits_remaining"] == 0
    assert ledger.expire_due(dsn=dsn) == 0            # idempotent


def test_expiry_two_months_out_is_the_policy(led):
    """The rule changed to two months on 2026-09-08. A lot granted
    nine weeks ago is gone; one granted seven weeks ago is not."""
    dsn, account = led
    assert ledger.EXPIRY_MONTHS == 2
    old = ledger.grant(account, 400, "subscription", granted_at=_stamp(-63), dsn=dsn)
    fresh = ledger.grant(account, 100, "subscription", granted_at=_stamp(-49), dsn=dsn)
    assert ledger.expire_due(dsn=dsn) == 400
    remaining = {lot["id"]: lot["credits_remaining"] for lot in ledger.lots(account, dsn)}
    assert remaining[old] == 0
    assert remaining[fresh] == 100


def test_a_lapse_expires_subscription_purchase_and_promo_and_spares_refund(led):
    dsn, account = led
    assert ledger.LAPSE_POLICY == {"subscription": True, "purchase": True,
                                   "promo": True, "refund": False}
    kept = ledger.grant(account, 70, "refund", dsn=dsn)
    adjustment = ledger.grant(account, 30, "adjustment", dsn=dsn)
    for kind in ("subscription", "purchase", "promo"):
        ledger.grant(account, 100, kind, dsn=dsn)
    assert ledger.available(account, dsn) == 400

    assert ledger.on_subscription_lapsed(account, dsn=dsn) == 300
    assert ledger.available(account, dsn) == 100
    remaining = {lot["id"]: lot["credits_remaining"] for lot in ledger.lots(account, dsn)}
    assert remaining[kept] == 70
    assert remaining[adjustment] == 30, "a kind absent from LAPSE_POLICY survives"


def test_a_lapse_writes_expire_entries_so_a_restore_stays_possible(led):
    """The doc's open question -- restore on resubscribe -- is only
    answerable while the movement is a row. Zeroing the lot in place
    would have destroyed the number a restore has to give back."""
    dsn, account = led
    ledger.grant(account, 250, "subscription", dsn=dsn)
    ledger.on_subscription_lapsed(account, dsn=dsn)
    expired = [e for e in ledger.entries(account, dsn) if e["kind"] == "expire"]
    assert [e["delta"] for e in expired] == [-250]


def test_expiry_never_hands_an_overdrawn_account_a_gift(led):
    """A lot with a negative remainder is not expired: taking a negative
    remainder would write a POSITIVE delta, so waiting two months would
    clear the debt."""
    dsn, account = led
    ledger.grant(account, 100, "subscription", expires_at=_stamp(1), dsn=dsn)
    hold_id = ledger.hold(account, 100, ref="render-1", provider="runway", dsn=dsn)
    ledger.settle(hold_id, 3.00, dsn=dsn)               # 300 actual on a 100 hold
    assert ledger.available(account, dsn) == -200

    with db.connect(dsn) as conn:
        conn.execute("UPDATE credit_lots SET expires_at = %s "
                     "WHERE account_id IS NOT DISTINCT FROM %s", (_stamp(-1), account))
    assert ledger.expire_due(dsn=dsn) == 0
    assert ledger.available(account, dsn) == -200, "the debt survived its lot's expiry"


# --------------------------------------------------------------------------
# BYOK
# --------------------------------------------------------------------------

def test_a_byok_render_takes_no_hold(led):
    """The customer paid their provider directly. Debiting them again
    is charging twice for one clip."""
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    assert ledger.hold_for_render(account, ref="render-1", provider="runway",
                                  estimate_usd=2.00, key_source="account",
                                  dsn=dsn) == ledger.RenderHold(None, "byok")
    assert ledger.available(account, dsn) == 500
    assert ledger.entries(account, dsn, ref="render-1") == []


def test_a_render_on_the_installations_key_does_take_a_hold(led):
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    hold_id, reason = ledger.hold_for_render(account, ref="render-1", provider="runway",
                                             estimate_usd=2.00, key_source="env", dsn=dsn)
    assert isinstance(hold_id, int) and reason == "held"
    assert ledger.available(account, dsn) == 300


def test_an_unknown_key_source_is_billable(led):
    """Wrong in the recoverable direction: a hold that should not have
    been taken is released, while a render given away free on the
    installation's key is found at the invoice."""
    assert ledger.is_billable(None) is True
    assert ledger.is_billable("env") is True
    assert ledger.is_billable("account") is False
    assert ledger.BYOK_KEY_SOURCE == "account"


def test_the_byok_constant_is_the_one_account_keys_writes():
    from src import account_keys
    assert ledger.BYOK_KEY_SOURCE == account_keys.SOURCE_ACCOUNT


# --------------------------------------------------------------------------
# the reaper
# --------------------------------------------------------------------------

def _generation(dsn, account, ref, *, output_path=None, cost_usd=None,
                reject_reason=None):
    """A generations row carrying the ledger ref the way an adapter will."""
    shot_id = generative.add_shot(Shot(subject="a bike", action="idles"),
                                 dsn=dsn, account_id=account)
    gen_id = generative.record_generation(
        shot_id, "runway", "a prompt",
        params={**ledger.ref_params(ref), "key_source": "env"},
        output_path=output_path, cost_usd=cost_usd, dsn=dsn, account_id=account)
    if reject_reason:
        with db.connect(dsn) as conn:
            conn.execute("UPDATE generations SET reject_reason = %s WHERE id = %s "
                         "AND account_id IS NOT DISTINCT FROM %s",
                         (reject_reason, gen_id, account))
    return gen_id


def test_the_ref_an_adapter_writes_is_findable_in_its_params():
    """The reaper matches on the stored text, so the shape json.dumps
    produces is part of the contract."""
    stored = json.dumps({**ledger.ref_params("render-1"), "key_source": "env"})
    assert '"ledger_ref": "render-1"' in stored


def test_reap_settles_a_hold_whose_render_landed(led):
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway",
                          estimate_usd=3.00, dsn=dsn)
    gen_id = _generation(dsn, account, "render-1", output_path="/tmp/a.mp4",
                         cost_usd=2.50)

    result = ledger.reap(datetime.now(timezone.utc) + timedelta(minutes=1), dsn=dsn)
    assert result == {"settled": [hold_id], "released": [], "orphaned": []}
    assert ledger.available(account, dsn) == 750       # settled at the ACTUAL cost
    settles = [e for e in ledger.entries(account, dsn, ref="render-1")
               if e["kind"] == "settle"]
    assert all(e["generation_id"] == gen_id for e in settles)


def test_reap_releases_a_hold_whose_render_failed(led):
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    _generation(dsn, account, "render-1", reject_reason="provider error")

    result = ledger.reap(datetime.now(timezone.utc) + timedelta(minutes=1), dsn=dsn)
    assert result == {"settled": [], "released": [hold_id], "orphaned": []}
    assert ledger.available(account, dsn) == 1000


def test_reap_releases_a_hold_that_was_never_submitted(led):
    """No stamp means the provider was never called: the process died
    between the hold and the submit, or the caller raised first. Nothing
    was billed, so the credit goes back quietly and needs no
    attention."""
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)

    result = ledger.reap(datetime.now(timezone.utc) + timedelta(minutes=1), dsn=dsn)
    assert result == {"settled": [], "released": [hold_id], "orphaned": []}
    assert ledger.available(account, dsn) == 1000


def test_a_submitted_hold_with_no_row_is_orphaned_not_released(led, capsys):
    """THE REVENUE LEAK THIS STAMP CLOSES.

    Submitted, so the provider billed; no generations row, so nothing
    here recorded it. Releasing would hand the customer back credit for
    a render you paid for AND erase the only evidence the discrepancy
    happened -- a released hold looks exactly like a refunded failure.
    So it stays outstanding, loudly, until a person decides.
    """
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    ledger.mark_submitted(hold_id, dsn=dsn)

    result = ledger.reap(datetime.now(timezone.utc) + timedelta(minutes=1), dsn=dsn)
    assert result == {"settled": [], "released": [], "orphaned": [hold_id]}
    assert ledger.outstanding(account, dsn) == 300, "the hold was NOT released"
    assert ledger.available(account, dsn) == 700
    assert "ORPHAN HOLD" in capsys.readouterr().err


def test_an_orphan_is_reported_again_on_every_sweep(led):
    """On purpose: a real-money discrepancy that stops being mentioned
    is one nobody fixes."""
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    ledger.mark_submitted(hold_id, dsn=dsn)
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert ledger.reap(cutoff, dsn=dsn)["orphaned"] == [hold_id]
    assert ledger.reap(cutoff, dsn=dsn)["orphaned"] == [hold_id]


def test_an_orphan_can_be_closed_by_hand_either_way(led):
    """The two exits the docstring names, both still available on a
    hold the reaper deliberately left open."""
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    ledger.mark_submitted(hold_id, dsn=dsn)
    ledger.reap(datetime.now(timezone.utc) + timedelta(minutes=1), dsn=dsn)
    ledger.release(hold_id, "orphan: provider has no record", dsn=dsn)
    assert ledger.available(account, dsn) == 1000
    assert ledger.outstanding(account, dsn) == 0


def test_a_submitted_hold_whose_render_landed_still_settles(led):
    """The stamp changes nothing when the row IS there."""
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    ledger.mark_submitted(hold_id, dsn=dsn)
    _generation(dsn, account, "render-1", output_path="/tmp/a.mp4", cost_usd=2.50)
    result = ledger.reap(datetime.now(timezone.utc) + timedelta(minutes=1), dsn=dsn)
    assert result["settled"] == [hold_id] and result["orphaned"] == []


def test_the_submit_stamp_is_written_once_and_never_moves(led):
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 100, ref="render-1", provider="veo", dsn=dsn)
    assert all(e["submitted_at"] is None
               for e in ledger.entries(account, dsn, ref="render-1"))
    first = ledger.mark_submitted(hold_id, dsn=dsn)
    assert ledger.mark_submitted(hold_id, dsn=dsn) == first
    assert all(e["submitted_at"] == first
               for e in ledger.entries(account, dsn, ref="render-1"))


def test_the_stamp_covers_every_lot_a_hold_spans(led):
    dsn, account = led
    ledger.grant(account, 100, "subscription", expires_at=_stamp(5), dsn=dsn)
    ledger.grant(account, 100, "purchase", expires_at=_stamp(50), dsn=dsn)
    hold_id = ledger.hold(account, 150, ref="render-1", provider="veo", dsn=dsn)
    stamp = ledger.mark_submitted(hold_id, dsn=dsn)
    held = [e for e in ledger.entries(account, dsn, ref="render-1") if e["kind"] == "hold"]
    assert len(held) == 2 and all(e["submitted_at"] == stamp for e in held)


def test_marking_a_hold_that_does_not_exist_raises(led):
    dsn, _ = led
    with pytest.raises(ledger.LedgerError):
        ledger.mark_submitted(9999, dsn=dsn)


def test_reap_leaves_a_render_that_is_merely_slow_alone(led):
    """The default age is well past the longest provider poll loop in
    the repo; reaping inside it would settle a render still running."""
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    assert ledger.reap(timedelta(hours=6), dsn=dsn) == {
        "settled": [], "released": [], "orphaned": []}
    assert ledger.outstanding(account, dsn) == 300


def test_reap_ignores_holds_already_closed(led):
    dsn, account = led
    ledger.grant(account, 1000, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 300, ref="render-1", provider="runway", dsn=dsn)
    ledger.release(hold_id, "qc failure", dsn=dsn)
    assert ledger.reap(datetime.now(timezone.utc) + timedelta(minutes=1),
                       dsn=dsn) == {"settled": [], "released": [], "orphaned": []}


# --------------------------------------------------------------------------
# the invariant, attacked directly
# --------------------------------------------------------------------------
#
# `credit_lots.credits_remaining` is derived by the triggers
# `db.add_ledger_balance_trigger` installs, so these tests do not go
# through the module at all: they write the corruption by hand, in raw
# SQL, the way a future writer who forgot the entry would, and then ask
# the database what it thinks the lot is worth.


def _remaining(dsn, lot_id):
    with db.connect(dsn) as conn:
        return int(conn.execute(
            "SELECT credits_remaining FROM credit_lots WHERE id = %s "
            "AND account_id IS NOT NULL", (lot_id,)).fetchone()["credits_remaining"])


def test_a_lot_updated_without_its_entry_does_not_keep_the_number(led):
    """THE TEST THE TRIGGERS EXIST FOR. Before them this UPDATE stood:
    the column was a denormalisation kept in step by careful code, and
    a writer who skipped the entry gave an account credit that no
    movement paid for -- silently, and in money."""
    dsn, account = led
    lot = ledger.grant(account, 500, "subscription", dsn=dsn)
    with db.connect(dsn) as conn:
        conn.execute(
            "UPDATE credit_lots SET credits_remaining = 999999 "
            "WHERE id = %s AND account_id IS NOT DISTINCT FROM %s", (lot, account))
    assert _remaining(dsn, lot) == 500, "the entries are the truth and they said 500"
    assert ledger.available(account, dsn) == 500
    assert all(r["drift"] == 0 for r in ledger.reconcile(account, dsn))


def test_a_lot_inserted_with_credit_nothing_granted_is_worth_nothing(led):
    """The same violation at INSERT: a lot conjured with a balance and
    no `grant` entry behind it. The lot is written -- rows are not the
    ledger's business to refuse -- and it is worth exactly the zero its
    entries say."""
    dsn, account = led
    with db.connect(dsn) as conn:
        lot = conn.execute(
            "INSERT INTO credit_lots (account_id, kind, credits_granted, "
            "credits_remaining, granted_at) VALUES (%s, 'promo', 500, 500, 't') "
            "RETURNING id", (account,)).fetchone()["id"]
    assert _remaining(dsn, lot) == 0
    assert ledger.available(account, dsn) == 0
    with pytest.raises(ledger.InsufficientCredit):
        ledger.hold(account, 10, ref="render-1", provider="runway", dsn=dsn)


def test_reconcile_still_catches_the_lot_nobody_wrote_an_entry_for(led):
    """What reconciliation is for now. Drift can no longer be non-zero,
    so the check was re-pointed at the one corruption a derived column
    cannot express: a lot with no entries behind it derives a perfectly
    consistent zero, and is still a row somebody wrote wrong."""
    dsn, account = led
    good = ledger.grant(account, 500, "subscription", dsn=dsn)
    with db.connect(dsn) as conn:
        bad = conn.execute(
            "INSERT INTO credit_lots (account_id, kind, credits_granted, "
            "credits_remaining, granted_at) VALUES (%s, 'promo', 500, 0, 't') "
            "RETURNING id", (account,)).fetchone()["id"]
    rows = {r["lot_id"]: r for r in ledger.reconcile(account, dsn)}
    assert all(r["drift"] == 0 for r in rows.values())
    assert rows[good]["orphan"] is False and rows[good]["entry_count"] == 1
    assert rows[bad]["orphan"] is True, "a lot with no movement behind it"


def test_deleting_an_entry_takes_its_credit_with_it(led):
    """The append-only rule is the module's, not the database's. If a
    row is deleted anyway -- a cleanup script, a hand-typed DELETE --
    the lot follows the entries rather than keeping a figure that now
    has nothing behind it."""
    dsn, account = led
    lot = ledger.grant(account, 500, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 200, ref="render-1", provider="runway", dsn=dsn)
    assert _remaining(dsn, lot) == 300
    with db.connect(dsn) as conn:
        conn.execute("DELETE FROM credit_entries WHERE id = %s "
                     "AND account_id IS NOT DISTINCT FROM %s", (hold_id, account))
    assert _remaining(dsn, lot) == 500
    assert ledger.available(account, dsn) == 500
    assert all(r["drift"] == 0 for r in ledger.reconcile(account, dsn))


def test_stamping_a_submit_does_not_disturb_the_balance(led):
    """`mark_submitted` is the one UPDATE the entries table takes, and
    the trigger that watches for a moved delta is deliberately not
    armed on it -- a submit stamp is not money."""
    dsn, account = led
    lot = ledger.grant(account, 500, "subscription", dsn=dsn)
    hold_id = ledger.hold(account, 200, ref="render-1", provider="runway", dsn=dsn)
    ledger.mark_submitted(hold_id, dsn=dsn)
    assert _remaining(dsn, lot) == 300
    assert ledger.available(account, dsn) == 300


def test_installing_the_triggers_is_idempotent_and_says_what_it_did(led):
    """`add_nightly_runs_table`'s contract: True the first time, False
    when they were already there, and safe on every dev-server reload
    in between."""
    dsn, account = led
    with db.connect(dsn) as conn:
        assert db.add_ledger_balance_trigger(conn) is False, "ledger.init put them in"
        assert db.add_ledger_balance_trigger(conn) is False
    ledger.grant(account, 100, "subscription", dsn=dsn)
    assert ledger.available(account, dsn) == 100


def test_the_triggers_are_installed_on_a_database_that_predates_them(pg):
    """The migration half. A database whose ledger tables were created
    before the triggers existed gets them from `init()` -- the additive
    shape `submitted_at` already uses, because the CREATEs cover a fresh
    database and this covers the one on the machine you are typing on."""
    accounts.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        conn.execute("DROP TRIGGER ledger_lot_balance ON credit_lots")
        conn.execute("DROP TRIGGER ledger_entry_syncs_lot_ins ON credit_entries")
        conn.execute("DROP TRIGGER ledger_entry_syncs_lot_del ON credit_entries")
        conn.execute("DROP TRIGGER ledger_entry_syncs_lot_upd ON credit_entries")
        assert db.add_ledger_balance_trigger(conn) is True
        account = conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"]
    ledger.grant(int(account), 500, "subscription", dsn=pg)
    with db.connect(pg) as conn:
        conn.execute("UPDATE credit_lots SET credits_remaining = 4 "
                     "WHERE account_id IS NOT DISTINCT FROM %s", (account,))
    assert ledger.available(int(account), pg) == 500


def test_a_trigger_on_a_database_without_the_tables_is_a_no_op(pg_factory):
    """Order is not this function's to enforce: a trigger cannot be put
    on a table that is not there, and saying so with False is better
    than raising at somebody else's init."""
    dsn = pg_factory()
    with db.connect(dsn) as conn:
        assert db.add_ledger_balance_trigger(conn) is False


# --------------------------------------------------------------------------
# it raises, and the two views agree
# --------------------------------------------------------------------------

def test_a_ledger_write_raises_rather_than_swallowing(led, monkeypatch):
    """The single most important difference between this module and
    spend.record_call, which never raises on purpose. A lost meter row
    costs a number on a dashboard; a lost ledger row costs money."""
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)

    def broken(*args, **kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(ledger.db, "connect", broken)
    for call in (
        lambda: ledger.grant(account, 100, "purchase", dsn=dsn),
        lambda: ledger.hold(account, 10, ref="render-1", provider="runway", dsn=dsn),
        lambda: ledger.settle(1, 1.00, dsn=dsn),
        lambda: ledger.release(1, "because", dsn=dsn),
        lambda: ledger.expire_due(dsn=dsn),
        lambda: ledger.on_subscription_lapsed(account, dsn=dsn),
        lambda: ledger.available(account, dsn),
    ):
        with pytest.raises(RuntimeError):
            call()


def test_the_entries_and_the_running_figure_never_disagree(led):
    """`credit_lots.credits_remaining` is a denormalised convenience and
    the entries are the truth. Every operation in the module, in one
    sequence, then the two views compared."""
    dsn, account = led
    ledger.grant(account, 400, "subscription", expires_at=_stamp(5), dsn=dsn)
    ledger.grant(account, 400, "purchase", expires_at=_stamp(50), dsn=dsn)
    ledger.grant(account, 100, "promo", expires_at=_stamp(-1), dsn=dsn)

    a = ledger.hold(account, 500, ref="render-1", provider="runway", dsn=dsn)
    ledger.settle(a, 6.00, generation_id=1, dsn=dsn)          # under-estimated
    b = ledger.hold(account, 100, ref="render-2", provider="veo", dsn=dsn)
    ledger.settle(b, 0.40, generation_id=2, dsn=dsn)          # over-estimated
    c = ledger.hold(account, 50, ref="render-3", provider="veo", dsn=dsn)
    ledger.release(c, "qc failure", dsn=dsn)
    ledger.expire_due(dsn=dsn)
    ledger.on_subscription_lapsed(account, dsn=dsn)

    rows = ledger.reconcile(account, dsn)
    assert rows and all(r["drift"] == 0 for r in rows), rows
    assert not any(r["orphan"] for r in rows), "every lot got its grant entry"
    assert sum(e["delta"] for e in ledger.entries(account, dsn)) == \
        sum(r["credits_remaining"] for r in rows)


def test_outstanding_everyone_is_the_operators_liability(led):
    dsn, account = led
    ledger.grant(account, 500, "subscription", dsn=dsn)
    ledger.hold(account, 120, ref="render-1", provider="runway", dsn=dsn)
    assert ledger.outstanding(account, dsn) == 120
    assert ledger.outstanding_everyone(dsn) == 120


def test_one_accounts_balance_is_invisible_to_another(led):
    dsn, account = led
    # accounts.seed makes both brands, so there is always a second one
    with db.connect(dsn) as conn:
        other = conn.execute(
            "SELECT id FROM accounts WHERE id <> %s ORDER BY id LIMIT 1",
            (account,)).fetchone()["id"]
    ledger.grant(account, 500, "subscription", dsn=dsn)
    assert ledger.available(other, dsn) == 0
    assert ledger.lots(other, dsn) == []
    with pytest.raises(ledger.InsufficientCredit):
        ledger.hold(other, 10, ref="render-1", provider="runway", dsn=dsn)


def test_init_is_idempotent(led):
    dsn, account = led
    ledger.grant(account, 100, "subscription", dsn=dsn)
    ledger.init(dsn)
    ledger.init(dsn)
    assert ledger.available(account, dsn) == 100

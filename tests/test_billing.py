"""
Stripe in front of the ledger (2026-09-18, src/billing.py + app/billing.py).

The suite blocks the network and that stays true: every event here is a
fixture, signed with the test webhook secret so stripe's own
construct_event runs for real, and the one Stripe client call the
checkout makes is a fake handed in through billing._stripe.

Guards, from docs/tasks/task-stripe-billing.md's test list:
- a valid event grants once; THE SAME EVENT DELIVERED TWICE GRANTS ONCE
  (the ledger's unique index, asserted end to end through the route)
- a bad signature writes nothing (400)
- an unknown customer acks (200) without granting
- a subscription-deleted event expires the lots LAPSE_POLICY says die
  and leaves `adjustment` alone
- a paid invoice grants the plan's allowance and records the plan
- the checkout route answers 503 naming the variable when unconfigured,
  and a URL when a Price exists; every customer-facing route declares
  its account
"""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import accounts, billing, db, ledger, pricing

client = TestClient(app)
WHSEC = "whsec_test_secret_for_the_suite"


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "zeropage", "display_name": "ZERO PAGE"})


@pytest.fixture
def shop(pg, monkeypatch):
    """A seeded account, the ledger, the webhook secret and a Price per
    item -- everything but STRIPE_SECRET_KEY, which only the checkout
    tests set."""
    monkeypatch.setenv("DATABASE_URL", pg)
    accounts.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    monkeypatch.setenv(billing.WEBHOOK_ENV, WHSEC)
    for key, item in billing.products().items():
        monkeypatch.setenv(item.price_env, f"price_{key}")
        if billing.is_plan(key):
            monkeypatch.setenv(item.price_env_yearly, f"price_{key}_year")
    with db.connect(pg) as conn:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"]
    # the routes act as THIS account (tests/test_tenancy.py's pattern)
    app.dependency_overrides[auth.current_account_id] = lambda: int(account_id)
    yield {"dsn": pg, "account_id": int(account_id)}
    app.dependency_overrides.pop(auth.current_account_id, None)


def signed(event: dict, secret: str = WHSEC, ts: int | None = None) -> tuple[bytes, str]:
    """A body and the Stripe-Signature header stripe's construct_event
    accepts: `t=<ts>,v1=<hmac_sha256(secret, "<ts>.<body>")>`."""
    body = json.dumps(event).encode()
    ts = int(ts or time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={mac}"


def post(event: dict, **kw):
    body, header = signed(event, **kw)
    return client.post("/billing/webhook", content=body,
                       headers={"stripe-signature": header, "content-type": "application/json"})


def event(kind: str, obj: dict, eid: str = "evt_1") -> dict:
    return {"id": eid, "object": "event", "type": kind, "data": {"object": obj}}


def checkout_paid(account_id: int, *, item="topup", customer="cus_1", intent="pi_1"):
    return event("checkout.session.completed", {
        "id": "cs_1", "object": "checkout.session", "mode": "payment",
        "customer": customer, "payment_intent": intent,
        "client_reference_id": str(account_id),
        "metadata": {"account_id": str(account_id), "item": item},
    })


def invoice_paid(*, customer="cus_1", price="price_creator", invoice="in_1"):
    return event("invoice.paid", {
        "id": invoice, "object": "invoice", "customer": customer,
        "lines": {"data": [{"price": {"id": price}}]},
    })


# --- the webhook -------------------------------------------------------------

def test_a_paid_checkout_grants_once_even_when_delivered_twice(shop):
    acct = shop["account_id"]
    first = post(checkout_paid(acct))
    assert first.status_code == 200, first.text
    assert first.json()["action"] == "granted"
    assert first.json()["credits"] == pricing.TOPUP.credits
    assert ledger.available(acct, shop["dsn"]) == pricing.TOPUP.credits
    # the first checkout bound the customer to the account
    assert accounts.stripe_customer_of(acct, dsn=shop["dsn"]) == "cus_1"
    assert accounts.account_for_stripe_customer("cus_1", dsn=shop["dsn"]) == acct

    again = post(checkout_paid(acct))                    # Stripe retries; same payment_intent
    assert again.status_code == 200
    assert ledger.available(acct, shop["dsn"]) == pricing.TOPUP.credits
    assert len(ledger.lots(acct, shop["dsn"])) == 1


def test_a_bad_signature_writes_nothing(shop):
    acct = shop["account_id"]
    body, _ = signed(checkout_paid(acct))
    forged = client.post("/billing/webhook", content=body,
                         headers={"stripe-signature": "t=1,v1=deadbeef"})
    assert forged.status_code == 400
    assert forged.json()["error"]["code"] == "bad_signature"
    wrong_secret = post(checkout_paid(acct), secret="whsec_somebody_else")
    assert wrong_secret.status_code == 400
    assert ledger.lots(acct, shop["dsn"]) == []
    assert accounts.stripe_customer_of(acct, dsn=shop["dsn"]) is None


def test_an_unknown_customer_is_acked_and_not_granted(shop):
    r = post(invoice_paid(customer="cus_nobody"))
    assert r.status_code == 200
    assert r.json() == {"received": True, "action": "unknown_customer"}
    assert ledger.lots(shop["account_id"], shop["dsn"]) == []


def test_a_paid_invoice_grants_the_plans_allowance_and_records_the_plan(shop):
    acct, dsn = shop["account_id"], shop["dsn"]
    # the subscription checkout binds the customer and names the plan ...
    sub = post(event("checkout.session.completed", {
        "id": "cs_2", "object": "checkout.session", "mode": "subscription",
        "customer": "cus_1", "subscription": "sub_1",
        "metadata": {"account_id": str(acct), "item": "creator"}}))
    assert sub.status_code == 200 and sub.json()["action"] == "subscribed"
    assert accounts.plan_of(acct, dsn=dsn) == "creator"
    assert ledger.available(acct, dsn) == 0                  # nothing until the invoice
    # ... and the invoice is what grants: one lot per period, by invoice id
    r = post(invoice_paid(price="price_creator", invoice="in_1"))
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "granted" and r.json()["plan"] == "creator"
    assert ledger.available(acct, dsn) == pricing.PLANS["creator"].credits
    assert pricing.tier_for(acct, dsn=dsn) == "creator"
    post(invoice_paid(price="price_creator", invoice="in_1"))    # redelivered
    assert len(ledger.lots(acct, dsn)) == 1
    post(invoice_paid(price="price_creator", invoice="in_2"))    # next period
    assert len(ledger.lots(acct, dsn)) == 2
    assert ledger.available(acct, dsn) == 2 * pricing.PLANS["creator"].credits


def test_a_lapsed_subscription_expires_what_the_policy_says_and_clears_the_plan(shop):
    acct, dsn = shop["account_id"], shop["dsn"]
    post(checkout_paid(acct, item="topup"))                       # binds cus_1; a purchase lot
    post(invoice_paid(price="price_starter"))                     # a subscription lot
    ledger.grant(acct, 77, "adjustment", source_ref="by-hand", dsn=dsn)
    assert accounts.plan_of(acct, dsn=dsn) == "starter"
    before = ledger.available(acct, dsn)

    r = post(event("customer.subscription.deleted", {
        "id": "sub_1", "object": "subscription", "customer": "cus_1", "status": "canceled"}))
    assert r.status_code == 200 and r.json()["action"] == "lapsed"
    assert accounts.plan_of(acct, dsn=dsn) is None
    assert pricing.tier_for(acct, dsn=dsn) is None
    dead = {k for k, dies in ledger.LAPSE_POLICY.items() if dies}
    survivors = sum(lot["credits_remaining"] for lot in ledger.lots(acct, dsn, include_expired=False))
    expected = 77 + (0 if "purchase" in dead else pricing.TOPUP.credits) \
        + (0 if "subscription" in dead else pricing.PLANS["starter"].credits)
    assert survivors == expected
    assert r.json()["credits_expired"] == before - expected
    # `adjustment` is never a billing event's to undo
    assert any(lot["kind"] == "adjustment" and lot["credits_remaining"] == 77
               for lot in ledger.lots(acct, dsn, include_expired=False))


def test_a_past_due_update_is_noted_not_lapsed(shop):
    acct, dsn = shop["account_id"], shop["dsn"]
    post(invoice_paid(customer="cus_1"))                          # unknown customer: acked
    post(checkout_paid(acct))                                     # now bound
    post(invoice_paid(price="price_studio"))
    r = post(event("customer.subscription.updated", {
        "id": "sub_1", "object": "subscription", "customer": "cus_1", "status": "past_due",
        "items": {"data": [{"price": {"id": "price_studio"}}]}}))
    assert r.status_code == 200 and r.json()["action"] == "plan_changed"
    assert accounts.plan_of(acct, dsn=dsn) == "studio"
    assert ledger.available(acct, dsn) == pricing.TOPUP.credits + pricing.PLANS["studio"].credits


def test_a_refund_is_logged_and_not_clawed_back(shop, capsys):
    acct, dsn = shop["account_id"], shop["dsn"]
    post(checkout_paid(acct))
    r = post(event("charge.refunded", {"id": "ch_1", "object": "charge", "customer": "cus_1",
                                       "amount_refunded": 1000}))
    assert r.status_code == 200 and r.json()["action"] == "logged"
    assert ledger.available(acct, dsn) == pricing.TOPUP.credits
    assert "NOT clawed back" in capsys.readouterr().err


def test_an_unrelated_event_type_is_ignored(shop):
    r = post(event("payment_method.attached", {"id": "pm_1", "object": "payment_method"}))
    assert r.status_code == 200 and r.json()["action"] == "ignored"


def test_no_webhook_secret_is_503_not_open(shop, monkeypatch):
    monkeypatch.delenv(billing.WEBHOOK_ENV, raising=False)
    r = post(checkout_paid(shop["account_id"]))
    assert r.status_code == 503
    assert billing.WEBHOOK_ENV in r.json()["error"]["message"]
    assert ledger.lots(shop["account_id"], shop["dsn"]) == []


# --- the customer-facing routes ---------------------------------------------

def test_checkout_is_503_naming_the_variable_when_unconfigured(shop, monkeypatch):
    monkeypatch.delenv(billing.SECRET_ENV, raising=False)
    r = client.post("/api/billing/checkout", json={"item": "creator"})
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "billing_unconfigured"
    assert billing.SECRET_ENV in r.json()["error"]["message"]

    monkeypatch.setenv(billing.SECRET_ENV, "sk_test_x")
    monkeypatch.delenv(pricing.PLANS["creator"].price_env, raising=False)
    r = client.post("/api/billing/checkout", json={"item": "creator"})
    assert r.status_code == 503
    assert pricing.PLANS["creator"].price_env in r.json()["error"]["message"]

    r = client.post("/api/billing/checkout", json={"item": "platinum"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_item"


def test_checkout_makes_a_session_for_this_account_and_binds_the_customer(shop, monkeypatch):
    monkeypatch.setenv(billing.SECRET_ENV, "sk_test_x")
    calls = {}

    class FakeStripe:
        class Customer:
            @staticmethod
            def create(**kw):
                calls["customer"] = kw
                return {"id": "cus_new"}

        class checkout:
            class Session:
                @staticmethod
                def create(**kw):
                    calls["session"] = kw
                    return {"url": "https://checkout.stripe.test/s/1"}

        class billing_portal:
            class Session:
                @staticmethod
                def create(**kw):
                    calls["portal"] = kw
                    return {"url": "https://portal.stripe.test/p/1"}

    monkeypatch.setattr(billing, "_stripe", lambda: FakeStripe)
    r = client.post("/api/billing/checkout", json={"item": "creator"})
    assert r.status_code == 200, r.text
    assert r.json() == {"url": "https://checkout.stripe.test/s/1"}
    acct = shop["account_id"]
    assert calls["customer"]["metadata"] == {"account_id": str(acct)}
    assert calls["session"]["mode"] == "subscription"
    assert calls["session"]["customer"] == "cus_new"
    assert calls["session"]["line_items"] == [{"price": "price_creator", "quantity": 1}]
    assert calls["session"]["metadata"] == {"account_id": str(acct), "item": "creator", "interval": "month"}
    assert calls["session"]["success_url"].endswith("/pricing?checkout=success")
    assert accounts.stripe_customer_of(acct, dsn=shop["dsn"]) == "cus_new"

    r = client.post("/api/billing/checkout", json={"item": "topup"})
    assert r.status_code == 200
    assert calls["session"]["mode"] == "payment"
    assert "customer" not in calls or calls["session"]["customer"] == "cus_new"   # reused, not recreated

    r = client.post("/api/billing/portal")
    assert r.status_code == 200 and r.json()["url"].startswith("https://portal")
    assert calls["portal"]["customer"] == "cus_new"


def test_portal_needs_a_customer(shop, monkeypatch):
    monkeypatch.setenv(billing.SECRET_ENV, "sk_test_x")
    r = client.post("/api/billing/portal")
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_billing"


def test_balance_reports_credits_plan_and_whether_checkout_is_configured(shop, monkeypatch):
    acct = shop["account_id"]
    monkeypatch.delenv(billing.SECRET_ENV, raising=False)
    r = client.get("/api/billing/balance")
    assert r.status_code == 200, r.text
    assert r.json()["available"] == 0 and r.json()["plan"] is None
    assert r.json()["checkout_configured"] is False and r.json()["portal"] is False
    assert r.json()["exempt"] is False

    post(checkout_paid(acct))
    post(invoice_paid(price="price_studio"))
    monkeypatch.setenv(billing.SECRET_ENV, "sk_test_x")
    r = client.get("/api/billing/balance").json()
    assert r["available"] == pricing.TOPUP.credits + pricing.PLANS["studio"].credits
    assert r["plan"]["key"] == "studio" and r["plan"]["tier"] == "premium"
    assert r["checkout_configured"] is True and r["portal"] is True
    assert {lot["kind"] for lot in r["lots"]} == {"purchase", "subscription"}


def test_the_return_url_is_the_public_site(monkeypatch):
    monkeypatch.delenv(billing.RETURN_ENV, raising=False)
    monkeypatch.setenv("STUDIO_URL", "https://zpf-web.vercel.app/")
    assert billing.return_url("/pricing") == "https://zpf-web.vercel.app/pricing"
    monkeypatch.setenv(billing.RETURN_ENV, "https://zeropage.example")
    assert billing.return_url("/pricing?checkout=success") == \
        "https://zeropage.example/pricing?checkout=success"


# --- yearly: a schedule, not a lot ------------------------------------------

def _months_later(stamp: str, n: int) -> str:
    return ledger._plus_months(stamp, n)


def test_a_yearly_invoice_grants_month_one_and_schedules_eleven_more(shop, monkeypatch):
    acct, dsn = shop["account_id"], shop["dsn"]
    monkeypatch.setenv(billing.SECRET_ENV, "sk_test_x")
    post(checkout_paid(acct))                                     # binds cus_1
    r = post(invoice_paid(price="price_creator_year", invoice="in_year"))
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "scheduled"
    assert r.json() == {**r.json(), "scheduled": 12, "released_now": 1, "plan": "creator"}
    plan = pricing.PLANS["creator"]
    assert ledger.available(acct, dsn) == pricing.TOPUP.credits + plan.credits   # month one only
    sched = billing.schedules(acct, dsn=dsn)
    assert len(sched) == 1
    assert sched[0]["months_released"] == 1 and sched[0]["months_total"] == 12
    assert sched[0]["next_release_at"] == _months_later(sched[0]["started_at"], 1)
    lots = [lot for lot in ledger.lots(acct, dsn) if lot["kind"] == "subscription"]
    assert [lot["source_ref"] for lot in lots] == ["in_year:m1"]
    # the plan (and its tier) is recorded as on a monthly plan
    assert accounts.plan_of(acct, dsn=dsn) == "creator"
    # a redelivered invoice changes nothing
    post(invoice_paid(price="price_creator_year", invoice="in_year"))
    assert len(billing.schedules(acct, dsn=dsn)) == 1
    assert ledger.available(acct, dsn) == pricing.TOPUP.credits + plan.credits
    b = client.get("/api/billing/balance").json()
    assert b["schedules"] == [{"plan": "creator", "months_released": 1, "months_total": 12,
                               "next_release_at": sched[0]["next_release_at"]}]
    assert b["yearly_configured"] is True


def test_each_month_lands_on_its_date_as_its_own_lot_and_never_twice(shop):
    acct, dsn = shop["account_id"], shop["dsn"]
    post(checkout_paid(acct))
    post(invoice_paid(price="price_starter_year", invoice="in_y"))
    plan = pricing.PLANS["starter"]
    started = billing.schedules(acct, dsn=dsn)[0]["started_at"]

    assert billing.release_due(acct, now=_months_later(started, 1), dsn=dsn) == 1
    assert billing.release_due(acct, now=_months_later(started, 1), dsn=dsn) == 0   # idempotent
    assert ledger.available(acct, dsn) == pricing.TOPUP.credits + 2 * plan.credits
    # a cron that slept three months releases three months, each with its
    # own granted_at and therefore its own expiry
    assert billing.release_due(None, now=_months_later(started, 4), dsn=dsn) == 3
    lots = sorted((lot for lot in ledger.lots(acct, dsn) if lot["kind"] == "subscription"),
                  key=lambda lot: lot["id"])
    assert [lot["source_ref"] for lot in lots] == [f"in_y:m{n}" for n in range(1, 6)]
    assert lots[4]["granted_at"] == _months_later(started, 4)
    assert lots[4]["expires_at"] == _months_later(_months_later(started, 4), ledger.EXPIRY_MONTHS)
    # ... and the twelfth month closes the schedule
    assert billing.release_due(acct, now=_months_later(started, 30), dsn=dsn) == 7
    sched = billing.schedules(acct, dsn=dsn)[0]
    assert sched["months_released"] == 12 and sched["next_release_at"] is None
    assert billing.release_due(acct, now=_months_later(started, 40), dsn=dsn) == 0
    assert billing.main(["release"]) is None


def test_a_lapse_cancels_the_schedule(shop):
    acct, dsn = shop["account_id"], shop["dsn"]
    post(checkout_paid(acct))
    post(invoice_paid(price="price_studio_year", invoice="in_y"))
    started = billing.schedules(acct, dsn=dsn)[0]["started_at"]
    r = post(event("customer.subscription.deleted", {
        "id": "sub_1", "object": "subscription", "customer": "cus_1", "status": "canceled"}))
    assert r.json()["schedules_cancelled"] == 1
    assert billing.release_due(acct, now=_months_later(started, 6), dsn=dsn) == 0
    assert billing.schedules(acct, dsn=dsn)[0]["cancelled_at"]
    assert accounts.plan_of(acct, dsn=dsn) is None


def test_a_due_month_lands_before_a_hold_is_taken(shop, monkeypatch):
    """The lazy release on the money path: a dead cron never refuses a
    render somebody paid for."""
    from src import charge as charging
    acct, dsn = shop["account_id"], shop["dsn"]
    post(invoice_paid(price="price_starter_year", invoice="in_y", customer="cus_1"))
    assert ledger.lots(acct, dsn) == []                            # unknown customer: acked
    post(checkout_paid(acct, item="topup"))                       # binds; +1000 purchase
    post(invoice_paid(price="price_starter_year", invoice="in_y"))
    started = billing.schedules(acct, dsn=dsn)[0]["started_at"]
    # pretend a month passed: rewind the schedule's next date into the past
    with db.connect(dsn) as conn:
        conn.execute("UPDATE credit_schedules SET next_release_at = %s WHERE account_id = %s",
                     (ledger._plus_months(started, -1), acct))
    before = ledger.available(acct, dsn)
    c = charging.Charge(acct, provider="runway", ref="r1", estimate_usd=1.0, key_source="env", dsn=dsn)
    c.take()
    assert ledger.available(acct, dsn) == before + pricing.PLANS["starter"].credits - c.held


def test_yearly_checkout_uses_the_yearly_price(shop, monkeypatch):
    monkeypatch.setenv(billing.SECRET_ENV, "sk_test_x")
    calls = {}

    class FakeStripe:
        class Customer:
            @staticmethod
            def create(**kw):
                return {"id": "cus_y"}

        class checkout:
            class Session:
                @staticmethod
                def create(**kw):
                    calls["session"] = kw
                    return {"url": "https://checkout.stripe.test/y"}

    monkeypatch.setattr(billing, "_stripe", lambda: FakeStripe)
    r = client.post("/api/billing/checkout", json={"item": "studio", "interval": "year"})
    assert r.status_code == 200, r.text
    assert calls["session"]["line_items"] == [{"price": "price_studio_year", "quantity": 1}]
    assert calls["session"]["metadata"]["interval"] == "year"
    assert billing.item_for_price("price_studio_year") == ("studio", "year")
    assert billing.item_for_price("price_topup") == ("topup", "month")
    r = client.post("/api/billing/checkout", json={"item": "studio", "interval": "decade"})
    assert r.status_code == 400
    monkeypatch.delenv(pricing.PLANS["studio"].price_env_yearly)
    r = client.post("/api/billing/checkout", json={"item": "studio", "interval": "year"})
    assert r.status_code == 503 and "STRIPE_PRICE_STUDIO_YEAR" in r.json()["error"]["message"]
    # the top-up has no interval and ignores one
    r = client.post("/api/billing/checkout", json={"item": "topup", "interval": "year"})
    assert r.status_code == 200

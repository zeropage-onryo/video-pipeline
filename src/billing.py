"""
Stripe in front of the ledger (2026-09-18, phase 2 of
docs/tasks/task-stripe-billing.md; Mike: "make stripe in front of ledger").

A person signs in, buys a plan or a top-up with a card, and renders. The
money side of that is three things, and this module is the middle one:

  the ledger (src/ledger.py)   what an account has -- built, tested, and
                               since today actually HELD against by every
                               adapter (src/charge.py)
  THIS MODULE                  the pure half of Stripe: which Price is which
                               plan, what a webhook event means for the
                               ledger, and the Checkout / Portal calls
  app/billing.py               the HTTP half: the webhook route (outside
                               /api -- Stripe cannot sign in) and the
                               customer-facing routes under /api/billing

THE FACTS THIS IS BUILT ON, all decided before it (the task doc, section 0):

- Webhook idempotency is the ledger's unique index on (account_id, kind,
  source_ref): the same event delivered twice calls grant() twice and the
  second call returns the first lot. No second guard is built here.
- Stripe customer -> account is `accounts.stripe_customer_id`, written
  the first time a checkout for that account completes. An event for a
  customer nobody knows is LOGGED AND ACKED (200) -- never retried
  forever, never guessed at.
- grant() raises by design. A real failure is a 500 so Stripe retries;
  only unknown-customer and unhandled-type are 200s.
- A subscription lot is granted per PAID INVOICE with the invoice id as
  its source_ref -- one per billing period, which is what makes "your
  monthly allowance" a monthly lot with the ledger's own expiry.
- `charge.refunded` does NOT claw credit back (the documented decision):
  a refund is the operator's call, made through Stripe, and the ledger
  keeps what was granted so the trail stays whole. Log it.

CONFIGURATION is environment only, never a table: STRIPE_SECRET_KEY,
STRIPE_WEBHOOK_SECRET, and one STRIPE_PRICE_* per plan and pack
(pricing.PLANS / pricing.TOPUP name them). `configured()` is what the
routes and the site ask; an unconfigured install answers 503 with the
variable to set, and the plan buttons say "checkout not configured"
rather than pointing at a dead link. Test-mode keys until the whole flow
has passed end to end.

Every network call is behind `_stripe()` so the suite -- which blocks
the network -- exercises everything else with events built as fixtures
and signed with the test secret (stripe's own construct_event runs for
real; see tests/test_billing.py).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from . import accounts, ledger, pricing

SECRET_ENV = "STRIPE_SECRET_KEY"
WEBHOOK_ENV = "STRIPE_WEBHOOK_SECRET"
RETURN_ENV = "BILLING_RETURN_URL"

# The events this module acts on. Anything else is acknowledged and
# ignored -- Stripe sends dozens of types and a webhook that 500s on a
# type it never asked for is a webhook Stripe eventually disables.
HANDLED_EVENTS = (
    "checkout.session.completed",
    "invoice.paid",
    "customer.subscription.deleted",
    "customer.subscription.updated",
    "charge.refunded",
)
# subscription statuses at which the allowance dies (LAPSE_POLICY decides
# which lots); "past_due" is deliberately NOT here -- Stripe is still
# retrying the card and the person is still a customer
LAPSED_STATUSES = ("canceled", "unpaid", "incomplete_expired")


class BillingUnconfigured(RuntimeError):
    def __init__(self, what: str):
        super().__init__(f"{what} is not set -- Stripe checkout is not configured on this install")
        self.what = what


class UnknownCustomer(LookupError):
    """An event for a Stripe customer no account pays as."""


def configured() -> bool:
    return bool((os.environ.get(SECRET_ENV) or "").strip())


def webhook_configured() -> bool:
    return bool((os.environ.get(WEBHOOK_ENV) or "").strip())


def _log(message: str) -> None:
    print(f"[billing] {message}", file=sys.stderr)


# --------------------------------------------------------------------------
# prices <-> plans
# --------------------------------------------------------------------------

def products() -> dict[str, Any]:
    """Every buyable thing by key: the three plans and the top-up."""
    out: dict[str, Any] = dict(pricing.PLANS)
    out[pricing.TOPUP.key] = pricing.TOPUP
    return out


def price_id(key: str) -> Optional[str]:
    """The Stripe Price for a plan or pack key, from its named env var, or
    None when that var is unset -- which the checkout reports as
    unconfigured rather than sending a person to a Price that does not
    exist."""
    item = products().get(key)
    if item is None:
        return None
    return (os.environ.get(item.price_env) or "").strip() or None


def key_for_price(price: Optional[str]) -> Optional[str]:
    """The plan or pack a Stripe Price id sells, or None. Read off the
    environment at call time so a rotated Price takes effect on the next
    event, not the next deploy."""
    if not price:
        return None
    for key, item in products().items():
        if (os.environ.get(item.price_env) or "").strip() == price:
            return key
    return None


def is_plan(key: Optional[str]) -> bool:
    return key in pricing.PLANS


# --------------------------------------------------------------------------
# checkout / portal -- the only network here
# --------------------------------------------------------------------------

def _stripe():
    if not configured():
        raise BillingUnconfigured(SECRET_ENV)
    import stripe  # imported lazily: the suite never needs it configured

    stripe.api_key = os.environ[SECRET_ENV].strip()
    return stripe


def return_url(path: str = "/pricing") -> str:
    """Where Checkout and the Portal send the person back to: the public
    site (BILLING_RETURN_URL, else STUDIO_URL, else SITE_URL) plus a
    path. The pricing page lives on the Next site, not on this origin."""
    base = (os.environ.get(RETURN_ENV) or os.environ.get("STUDIO_URL")
            or os.environ.get("SITE_URL") or "http://127.0.0.1:3000").strip().rstrip("/")
    return f"{base}{path}"


def _customer_for(account_id: int, email: Optional[str], dsn: Optional[str] = None) -> str:
    """The Stripe customer this account pays as, created on first use and
    bound to the row so every later event resolves to this tenant."""
    have = accounts.stripe_customer_of(account_id, dsn=dsn)
    if have:
        return have
    stripe = _stripe()
    customer = stripe.Customer.create(
        email=email or None,
        metadata={"account_id": str(account_id)},
    )
    accounts.set_stripe_customer(account_id, customer["id"], dsn=dsn)
    return customer["id"]


def checkout_url(account_id: int, key: str, *, email: Optional[str] = None,
                 dsn: Optional[str] = None) -> str:
    """A Stripe Checkout Session URL for one plan or pack. Raises
    BillingUnconfigured (no key, or no Price for this item) and
    ValueError (no such item)."""
    item = products().get(key)
    if item is None:
        raise ValueError(f"no such plan or pack: {key!r}")
    price = price_id(key)
    if not price:
        raise BillingUnconfigured(item.price_env)
    stripe = _stripe()
    customer = _customer_for(account_id, email, dsn=dsn)
    mode = "subscription" if is_plan(key) else "payment"
    session = stripe.checkout.Session.create(
        mode=mode,
        customer=customer,
        line_items=[{"price": price, "quantity": 1}],
        success_url=return_url("/pricing?checkout=success"),
        cancel_url=return_url("/pricing?checkout=cancelled"),
        client_reference_id=str(account_id),
        # the webhook reads these back: which account, which item -- so a
        # one-time pack can be granted without a second API call to list
        # the session's line items
        metadata={"account_id": str(account_id), "item": key},
        **({"subscription_data": {"metadata": {"account_id": str(account_id), "item": key}}}
           if mode == "subscription" else
           {"payment_intent_data": {"metadata": {"account_id": str(account_id), "item": key}}}),
        allow_promotion_codes=True,
    )
    return session["url"]


def portal_url(account_id: int, *, dsn: Optional[str] = None) -> str:
    """The Customer Portal (change plan, cancel, invoices). Raises
    BillingUnconfigured; ValueError when the account has never paid."""
    customer = accounts.stripe_customer_of(account_id, dsn=dsn)
    if not customer:
        raise ValueError("this account has no billing yet -- choose a plan first")
    stripe = _stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer, return_url=return_url("/pricing"))
    return session["url"]


# --------------------------------------------------------------------------
# the webhook -- verify, then act
# --------------------------------------------------------------------------

def verify(payload: bytes, signature: Optional[str]) -> dict:
    """The event, as a dict, or raise. stripe.Webhook.construct_event does
    the HMAC and the timestamp tolerance; this only supplies the secret.
    Raises BillingUnconfigured (no secret) or ValueError (bad signature
    or body)."""
    secret = (os.environ.get(WEBHOOK_ENV) or "").strip()
    if not secret:
        raise BillingUnconfigured(WEBHOOK_ENV)
    import json

    import stripe
    from stripe import SignatureVerificationError

    try:
        stripe.Webhook.construct_event(payload, signature or "", secret)
    except SignatureVerificationError as e:
        raise ValueError(f"bad signature: {e}") from e
    except ValueError as e:
        raise ValueError(f"bad payload: {e}") from e
    # the verified bytes, as plain data: handle_event wants dicts, not the
    # SDK's resource objects, so the fixtures in the suite are the wire shape
    return json.loads(payload.decode("utf-8"))


def _account_for(obj: dict, dsn: Optional[str]) -> int:
    """The account an event's object belongs to: the customer binding
    first, the metadata the checkout wrote second (the FIRST checkout is
    what creates the binding, so its own event may arrive before it)."""
    customer = obj.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if customer:
        found = accounts.account_for_stripe_customer(customer, dsn=dsn)
        if found is not None:
            return found
    meta = obj.get("metadata") or {}
    ref = meta.get("account_id") or obj.get("client_reference_id")
    if ref:
        try:
            account_id = int(ref)
        except (TypeError, ValueError):
            account_id = None
        if account_id is not None:
            if customer:
                try:
                    accounts.set_stripe_customer(account_id, customer, dsn=dsn)
                except ValueError as e:
                    _log(f"could not bind customer {customer} to account {account_id}: {e}")
            return account_id
    raise UnknownCustomer(f"no account pays as customer {customer!r}")


def _line_price(obj: dict) -> Optional[str]:
    """The Price id on an invoice's first line, whichever shape Stripe
    sent it in (a string id, or the expanded object)."""
    lines = (obj.get("lines") or {}).get("data") or []
    for line in lines:
        price = line.get("price") or (line.get("pricing") or {}).get("price_details", {}).get("price")
        if isinstance(price, dict):
            price = price.get("id")
        if price:
            return price
    return None


def handle_event(event: dict, *, dsn: Optional[str] = None) -> dict:
    """Act on ONE verified event. Returns what happened, for the route to
    log and answer with. Raises UnknownCustomer (route: 200 + log) and
    lets ledger errors propagate (route: 500, Stripe retries).

    Pure against the database -- no Stripe call is made here, which is
    what makes it testable with fixture events.
    """
    kind = event.get("type") or ""
    obj = ((event.get("data") or {}).get("object")) or {}
    if kind not in HANDLED_EVENTS:
        return {"type": kind, "action": "ignored"}

    if kind == "checkout.session.completed":
        account_id = _account_for(obj, dsn)
        item = (obj.get("metadata") or {}).get("item")
        if obj.get("mode") == "payment":
            pack = products().get(item or "")
            if pack is None or is_plan(item):
                _log(f"checkout {obj.get('id')} paid for unknown item {item!r} -- not granted")
                return {"type": kind, "action": "unknown_item", "account_id": account_id}
            ref = obj.get("payment_intent") or obj.get("id")
            lot = ledger.grant(account_id, pack.credits, "purchase", source_ref=str(ref),
                               note=f"stripe checkout {obj.get('id')} ({pack.key})", dsn=dsn)
            return {"type": kind, "action": "granted", "account_id": account_id,
                    "credits": pack.credits, "lot": lot}
        # a subscription checkout: the plan is recorded now, the credit
        # arrives with invoice.paid (which Stripe sends for the first
        # period too, so nothing is granted twice)
        if is_plan(item):
            accounts.set_plan(account_id, item, dsn=dsn)
        return {"type": kind, "action": "subscribed", "account_id": account_id, "plan": item}

    if kind == "invoice.paid":
        account_id = _account_for(obj, dsn)
        key = key_for_price(_line_price(obj))
        if key is None:
            meta = ((obj.get("subscription_details") or {}).get("metadata")
                    or obj.get("metadata") or {})
            key = meta.get("item")
        plan = pricing.PLANS.get(key or "")
        if plan is None:
            _log(f"invoice {obj.get('id')} paid for no known plan (price "
                 f"{_line_price(obj)!r}) -- not granted")
            return {"type": kind, "action": "unknown_plan", "account_id": account_id}
        lot = ledger.grant(account_id, plan.credits, "subscription", source_ref=str(obj.get("id")),
                           note=f"stripe invoice {obj.get('id')} ({plan.key})", dsn=dsn)
        accounts.set_plan(account_id, plan.key, dsn=dsn)
        return {"type": kind, "action": "granted", "account_id": account_id,
                "plan": plan.key, "credits": plan.credits, "lot": lot}

    if kind in ("customer.subscription.deleted", "customer.subscription.updated"):
        account_id = _account_for(obj, dsn)
        status = obj.get("status")
        if kind == "customer.subscription.updated" and status not in LAPSED_STATUSES:
            # a plan change lands here too: keep the plan column current
            key = key_for_price(_line_price(obj.get("items") and {"lines": obj["items"]} or {}))
            if is_plan(key):
                accounts.set_plan(account_id, key, dsn=dsn)
                return {"type": kind, "action": "plan_changed", "account_id": account_id, "plan": key}
            return {"type": kind, "action": "noted", "account_id": account_id, "status": status}
        expired = ledger.on_subscription_lapsed(account_id, dsn=dsn)
        accounts.set_plan(account_id, None, dsn=dsn)
        return {"type": kind, "action": "lapsed", "account_id": account_id,
                "credits_expired": expired}

    if kind == "charge.refunded":
        # documented decision: no clawback -- see the module docstring
        try:
            account_id = _account_for(obj, dsn)
        except UnknownCustomer:
            account_id = None
        _log(f"charge {obj.get('id')} refunded ({obj.get('amount_refunded')} cents) for "
             f"account {account_id!r} -- credit NOT clawed back; adjust by hand if wanted")
        return {"type": kind, "action": "logged", "account_id": account_id}

    return {"type": kind, "action": "ignored"}  # pragma: no cover


# --------------------------------------------------------------------------
# what the UI shows
# --------------------------------------------------------------------------

def balance(account_id: int, *, dsn: Optional[str] = None) -> dict:
    """Available, committed and the lots, plus the plan -- the numbers the
    studio's account row and the pricing page's "your plan" state print."""
    plan_key = accounts.plan_of(account_id, dsn=dsn)
    plan = pricing.PLANS.get(plan_key or "")
    lots = [{"id": lot["id"], "kind": lot["kind"],
             "credits": lot["credits_granted"],
             "remaining": lot["credits_remaining"], "granted_at": lot["granted_at"],
             "expires_at": lot["expires_at"]}
            for lot in ledger.lots(account_id, dsn, include_expired=False)]
    return {
        "available": ledger.available(account_id, dsn),
        "outstanding": ledger.outstanding(account_id, dsn),
        "plan": ({"key": plan.key, "name": plan.name, "tier": plan.tier,
                  "credits": plan.credits, "monthly_usd": plan.monthly_usd}
                 if plan else None),
        "exempt": accounts.is_credit_exempt(account_id, dsn=dsn),
        "lots": lots,
        "checkout_configured": configured() and all(price_id(k) for k in pricing.PLANS),
        "portal": bool(accounts.stripe_customer_of(account_id, dsn=dsn)),
    }


__all__ = [
    "SECRET_ENV", "WEBHOOK_ENV", "RETURN_ENV", "HANDLED_EVENTS", "LAPSED_STATUSES",
    "BillingUnconfigured", "UnknownCustomer",
    "configured", "webhook_configured", "products", "price_id", "key_for_price", "is_plan",
    "checkout_url", "portal_url", "return_url", "verify", "handle_event", "balance",
]

"""
The HTTP half of Stripe (2026-09-18; the pure half is src/billing.py).

TWO ROUTERS, AND THE SPLIT IS THE SECURITY MODEL:

- `webhook` is NOT under /api. app/main.py includes the API router as
  `include_router(api.router, dependencies=[Depends(auth.require_user_api)])`,
  and Stripe cannot sign in. So the webhook lives at /billing/webhook,
  included beside auth.router, with no session dependency and no
  mutation header: its authentication is the Stripe signature over the
  RAW body and nothing else. A failed signature is a 400 that writes
  nothing.
- `API_ROUTES` is the customer-facing set, registered ONTO api.router
  (app/api.py, bottom) so it inherits the session gate and is scanned by
  tests/test_tenancy.py's route audit: every handler declares
  `Depends(auth.current_account_id)`, the parameter it cannot act without.

  POST /api/billing/checkout {"item": "starter"|"creator"|"studio"|"topup"}
       -> {"url"}: a Checkout Session for THIS account
  POST /api/billing/portal -> {"url"}: the Customer Portal
  GET  /api/billing/balance -> src/billing.balance: credits, plan, lots

An unconfigured install (no STRIPE_SECRET_KEY, or no Price for the item)
answers 503 `billing_unconfigured` naming the variable, in the same
JSON error shape every other /api refusal uses, so the plan buttons can
say so instead of pointing at a dead link.
"""

from __future__ import annotations

import sys

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src import billing, ledger

from . import auth


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


# --------------------------------------------------------------------------
# the webhook -- outside /api
# --------------------------------------------------------------------------

webhook = APIRouter(tags=["billing"])


@webhook.post("/billing/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()          # RAW, before anything parses it
    signature = request.headers.get("stripe-signature")
    try:
        event = billing.verify(payload, signature)
    except billing.BillingUnconfigured as e:
        return _error(503, "billing_unconfigured", str(e))
    except ValueError as e:
        return _error(400, "bad_signature", str(e))
    try:
        result = billing.handle_event(event)
    except billing.UnknownCustomer as e:
        # acked, never retried forever, never guessed at
        print(f"[billing] {event.get('type')}: {e}", file=sys.stderr)
        return {"received": True, "action": "unknown_customer"}
    except ledger.LedgerError as e:
        # a real failure: 500 so Stripe retries the delivery
        print(f"[billing] {event.get('type')} FAILED: {e}", file=sys.stderr)
        return _error(500, "ledger_error", str(e))
    print(f"[billing] {result}", file=sys.stderr)
    return {"received": True, **result}


# --------------------------------------------------------------------------
# customer-facing -- under /api, through api.router
# --------------------------------------------------------------------------

class CheckoutBody(BaseModel):
    item: str


def _no_account():
    # the dev posture resolves the unowned pool for a member of nothing;
    # there is nobody to bill there and nothing to show
    return _error(403, "no_account", "sign in to an account to manage billing")


def billing_checkout(body: CheckoutBody, request: Request,
                     account_id: int = Depends(auth.current_account_id)):
    if account_id is None:
        return _no_account()
    user = auth.current_user(request) or {}
    try:
        url = billing.checkout_url(account_id, body.item.strip().lower(),
                                   email=user.get("email"))
    except billing.BillingUnconfigured as e:
        return _error(503, "billing_unconfigured", str(e))
    except ValueError as e:
        return _error(400, "bad_item", str(e))
    return {"url": url}


def billing_portal(account_id: int = Depends(auth.current_account_id)):
    if account_id is None:
        return _no_account()
    try:
        url = billing.portal_url(account_id)
    except billing.BillingUnconfigured as e:
        return _error(503, "billing_unconfigured", str(e))
    except ValueError as e:
        return _error(400, "no_billing", str(e))
    return {"url": url}


def billing_balance(account_id: int = Depends(auth.current_account_id)):
    if account_id is None:
        return _no_account()
    return billing.balance(account_id)


# (path under /api, handler, methods) -- app/api.py registers these
API_ROUTES = (
    ("/billing/checkout", billing_checkout, ["POST"]),
    ("/billing/portal", billing_portal, ["POST"]),
    ("/billing/balance", billing_balance, ["GET"]),
)

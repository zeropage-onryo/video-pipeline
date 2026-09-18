# Billing — what was built on 2026-09-18, and how to switch it on

Mike's calls that day: three plans "based on the pricing already set in the backend",
the plan cards shaped like Runway / LTX / Higgsfield's, and "make stripe in front of
ledger". Zero credits with a renderer key on file **falls through to BYOK**.

## The money path, end to end

```
/pricing  (web/src/app/pricing)            the site, generated off pricing.json
   │ Get <plan>  -> POST /api/billing/checkout {item}
   ▼
app/billing.py  -> src/billing.checkout_url   Stripe Checkout (customer bound to the account)
   │ card
   ▼
Stripe -> POST /billing/webhook (signature over the raw body, no session)
   │ checkout.session.completed (payment)   -> ledger.grant(kind="purchase",  source_ref=payment_intent)
   │ invoice.paid                           -> ledger.grant(kind="subscription", source_ref=invoice id) + accounts.plan
   │ customer.subscription.deleted/unpaid   -> ledger.on_subscription_lapsed + plan cleared
   │ charge.refunded                        -> logged, NOT clawed back (documented decision)
   ▼
Queue: Approve -> pricing.quote (MARKUP 2.4, the account's tier from its plan)
   ▼
adapter.generate_video:  spend gate -> Charge.take() [hold] -> Charge.submitted() -> submit
                          -> settle(min(actual, held), generation_id) | release on failure
```

Every hold and every quote convert through ONE function, `ledger.charge_credits`
(= `pricing.credits_for(pricing.usd_micros(usd))`), so the number on the card is the
number debited by construction. Tests: `tests/test_charge.py`, `tests/test_billing.py`,
`tests/test_plans.py`, plus the updated `test_ledger.py` / `test_pricing.py`.

## The plans (src/pricing.PLANS)

| key | tier | $/mo | credits/mo | unlocks |
|---|---|---|---|---|
| starter | standard | 15 | 1,500 | LTX 2.3, Runway Gen-4 Turbo / 4.5, Wan 3.0 |
| creator | creator | 35 | 3,500 | + Kling 2.5 / 3 Turbo Pro, Seedance 2.0 / Fast |
| studio | premium | 95 | 9,500 | + Veo 3 |
| topup | — | 10 (one-time) | 1,000 | a `purchase` lot |

1 credit = 1¢ of charge; a render = provider estimate × 2.4, rounded up, floor 10.
Lots expire 2 months after they land (`ledger.EXPIRY_MONTHS`). **No yearly billing yet**:
a year's credit granted on one invoice would die ten months early under that expiry;
it needs a monthly-release job first.

`web/src/content/pricing.json` is generated: `venv/bin/python -m src.pricing export`.
Change a plan, the markup, a band or a rate card → re-export → commit, or
`tests/test_plans.py` fails naming the drift.

## Who is not charged (one predicate: `ledger.hold_for_render`)

- BYOK — `key_source == "account"`: the provider bills them directly.
- The manual lanes — a `params.source` in `manual_lane.SUBSCRIPTION_SOURCES`.
- The unowned pool — `account_id is None` (the CLI, the nightly walk): nobody's bill.
- **The operator** — `accounts.credit_exempt`, a column, fails closed. Turn yours on
  ONCE, before the first approve on this branch, or your own Queue refuses you:

  ```bash
  venv/bin/python -m src.accounts credits zeropage --on
  ```

  The daily caps still apply to an exempt account.

## Switching Stripe on (test mode first)

1. Stripe dashboard → Products: create four Prices (recurring monthly $15 / $35 / $95,
   one-time $10). The amounts MUST equal `pricing.PLANS` / `TOPUP` — the site prints
   pricing.py's numbers, Stripe charges the Price's.
2. `.env` (and Fly secrets): `STRIPE_SECRET_KEY`, `STRIPE_PRICE_STARTER`,
   `STRIPE_PRICE_CREATOR`, `STRIPE_PRICE_STUDIO`, `STRIPE_PRICE_TOPUP`,
   `BILLING_RETURN_URL=https://zpf-web.vercel.app` (where Checkout sends people back;
   defaults to `STUDIO_URL`). Until these are set the plan buttons say "Checkout isn't
   configured on this install yet" and nothing else changes.
3. The webhook. Locally: `stripe listen --forward-to localhost:8000/billing/webhook`
   prints a `whsec_…` → `STRIPE_WEBHOOK_SECRET`. On Fly: dashboard → Webhooks → endpoint
   `https://zeropage-studio.fly.dev/billing/webhook`, events
   `checkout.session.completed`, `invoice.paid`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `charge.refunded` → its signing secret.
4. `venv/bin/pip install -r requirements.txt` (adds `stripe`). Restart the API:
   `accounts.init()` adds `credit_exempt`, `stripe_customer_id`, `plan` to `accounts`
   on Supabase (additive ALTERs, no backfill).
5. Buy Starter with a test card (4242…). `GET /api/billing/balance` shows the lot;
   approve a render; `ledger.entries` shows hold → settle with the generation id.

The Customer Portal (`POST /api/billing/portal`) needs the portal enabled once in the
Stripe dashboard (Settings → Billing → Customer portal).

## Still open

- Yearly plans (above). Phase 4 of the Stripe task doc — a per-account daily Gemini
  budget for accounts holding no credit — is not built; the ledger is the wall for
  anyone with a plan, and a stranger's ideation still bills the operator's key.
- The studio shell does not show the balance yet; `GET /api/billing/balance` is
  there for it.
- Negative balances (settle can overdraw; the next hold refuses), downgrade timing
  (portal default: at period end), and escheatment are the design doc's open calls,
  unchanged.

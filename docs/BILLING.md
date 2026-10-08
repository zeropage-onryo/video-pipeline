# Billing — what was built on 2026-09-18, and how to switch it on

Mike's calls that day: three plans "based on the pricing already set in the backend",
the plan cards shaped like Runway / LTX / Higgsfield's, and "make stripe in front of
ledger". Zero credits with a renderer key on file **falls through to BYOK**.

## The money path, end to end

```
/pricing  (web/src/app/pricing)            the site, generated off pricing.json
   │ Get <plan>  -> POST /api/billing/checkout {item, interval: month|year}
   ▼
app/billing.py  -> src/billing.checkout_url   Stripe Checkout (customer bound to the account)
   │ card
   ▼
Stripe -> POST /billing/webhook (signature over the raw body, no session)
   │ checkout.session.completed (payment)   -> ledger.grant(kind="purchase",  source_ref=payment_intent)
   │ invoice.paid (monthly)                 -> ledger.grant(kind="subscription", source_ref=invoice id) + accounts.plan
   │ invoice.paid (yearly)                  -> month one granted + a credit_schedules row; release_due does the rest
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
| topup | — | 10 (one-time) | 750 | a `purchase` lot; **plan holders only** |

1 credit = 1¢ of charge on a plan; a render = provider estimate × 2.4, rounded up, floor 10.
**The top-up is dearer and plan-only (2026-09-29, Mike's call):** 750 credits for $10
(1.33¢ a credit against a plan's 1.0¢), and `billing.checkout_url` refuses it for an
account with no plan (`403 plan_required`, before any Stripe call). At 1,000 for $10 it was
the same rate as Starter, which gave nobody a reason to subscribe. The Stripe Price stays
$10; only the grant changed, so no Stripe edit is needed.
Lots expire 2 months after they land (`ledger.EXPIRY_MONTHS`).

**Yearly = 12 months at 20% off** (Starter $144, Creator $336, Studio $912 — $12 / $28 /
$76 a month, the toggle on /pricing), **billed once, released monthly.** A year's credit
on one lot would die ten months early under the expiry, so a yearly `invoice.paid`
grants month one and writes a `credit_schedules` row (an OWNED table); each later month
lands on its date as its own `subscription` lot, source_ref `<invoice>:m<n>`, so a
release is idempotent through the ledger's unique index. Releases run three ways, any
one of which is enough: `venv/bin/python -m src.billing release` (put it on a daily
cron / LaunchAgent), lazily in `GET /api/billing/balance`, and lazily in
`charge.Charge.take()` right before a hold — so a dead cron never refuses a render
somebody paid for. A lapse cancels the schedule; months already released follow
`LAPSE_POLICY`.

`web/src/content/pricing.json` is generated: `venv/bin/python -m src.pricing export`.
Change a plan, the markup, a band or a rate card → re-export → commit, or
`tests/test_plans.py` fails naming the drift.

## What costs credits besides a render (2026-09-28 / 09-29)

- **A still** (a Nano Banana keyframe, a Director Nano node, an element's
  reference sheet): its provider price x 2.4, floor 10 — 10 cr on Flash, 33 on
  Pro (`pricing.still_credits`), held in `nano_banana.generate_from_prompt`.
- **A generated reference** (`refgen`, the MCP `imagine_reference` tool,
  2026-09-29): the still that drew it — 10 cr on Nano Flash, 33 on Pro (Michael's
  face), 65 via Midjourney — held at the dearest provider that can actually run,
  settled at the one that did. The scout's own crawl passes no account, so it is
  nobody's bill.
- **A Create** (writing a scene): **0 credits**. Mike, 2026-09-29: it is
  included in the subscription, its Gemini cost (~$0.04) priced into the plans
  rather than debited per click. A Starter plan spent entirely on renders leaves
  ~$8.75 of margin, ~580 Creates a month. Create is **refused** (402
  `subscribe_or_top_up`) only for an account with no plan and no balance —
  `charge.create_refusal`, which the MCP `research` / `generate` tools ask too.
- **The trial**: a new open sign-up gets **100 credits once**
  (`ZEROPAGE_SIGNUP_CREDITS`, default 100; 0 turns it off), InVideo's shape.
  **Its thinking is included once, too** (2026-10-08, Mike: "fix the trial"):
  an account that has never had credit the trial did not give it
  (`ledger.beyond_trial` -- no subscription, purchase or adjustment lot) may
  spend `pricing.trial_thinking_usd()` of model text, $1.00 by default
  (`ZEROPAGE_TRIAL_THINKING_USD`), measured by the meter (`spend.thinking_spent`,
  stills excluded -- they are charged in credits). Then the Guide, Create and the
  rest answer 402 `trial_thinking_used`. Thinking is never debited from the
  balance: on a plan the brain stays free, its cost carried by the render markup.
- **No image cap**: `NANO_DAILY_CAP` is gone (2026-09-29) — for everyone,
  exempt accounts included. The balance is the limit.

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

**Steps 1–3 are one command since 2026-09-30:** put `STRIPE_SECRET_KEY` in `.env`, then
`venv/bin/python -m ops.stripe_setup` (add `--fly` to push the same values to Fly,
`--live` for an `sk_live_` key). It creates the seven Prices off `pricing.PLANS`/`TOPUP`
(idempotent by lookup key `zpf_<item>_<month|year|once>`), the Fly webhook endpoint with
`billing.HANDLED_EVENTS` pinned to the SDK's API version, and writes the `STRIPE_PRICE_*`
ids, `STRIPE_WEBHOOK_SECRET`, `STRIPE_WEBHOOK_ENDPOINT` (the id that secret belongs to --
a secret is only reused for the endpoint it was issued for) and
`BILLING_RETURN_URL=https://zeropage.studio`. Prices change in `pricing.py`, never in the
dashboard: edit, rerun, and the lookup key moves to a new Price. The manual steps below
are what it does, kept for reference.

1. Stripe dashboard → Products: create seven Prices — recurring monthly $15 / $35 /
   $95, recurring yearly $144 / $336 / $912, one-time $10. The amounts MUST equal
   `pricing.PLANS` (`monthly_usd`, `yearly_usd`) / `TOPUP` — the site prints pricing.py's
   numbers, Stripe charges the Price's.
2. `.env` (and Fly secrets): `STRIPE_SECRET_KEY`, `STRIPE_PRICE_STARTER`,
   `STRIPE_PRICE_CREATOR`, `STRIPE_PRICE_STUDIO`, their `_YEAR` twins,
   `STRIPE_PRICE_TOPUP`,
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

6. Daily: `venv/bin/python -m src.billing release` (yearly months; harmless when there
   are none).

## Walking it in test mode (`ops/billing_walkthrough.py`, 2026-09-29)

The whole paid path, once, as a customer would meet it, before anyone real pays. It runs
on its OWN schema (`billwalk`) on the local throwaway Postgres, on port 8021, with R2 and
fal blanked. It refuses any Stripe key that is not a test key, and it needs no Stripe CLI:
`relay` reads the test account's events off the Stripe API and signs them to the local
webhook the way Stripe does. All commands run from the checkout root:

1. **Stripe dashboard, Test mode** (the toggle top right) → Developers → API keys → reveal
   the *Secret key* (`sk_test_…`). Put it in `.env.billing-walk` at the checkout root as
   `STRIPE_SECRET_KEY=sk_test_…`. That file is gitignored (`.env.*`) and is created with
   owner-only permissions by `seed`.
2. `venv/bin/python -m ops.billing_walkthrough seed --fresh`: the schema, a user
   (`walkthrough@example.test`) and two NON-exempt accounts. It also writes a session
   secret and the local webhook secret into the file.
3. `venv/bin/python -m ops.billing_walkthrough prices`: creates the seven test Prices
   from `pricing.PLANS` / `TOPUP`, found by lookup key so it never duplicates them, and
   writes their ids into the file. It refuses if Stripe's amount disagrees with
   `pricing.py`.
4. `venv/bin/python -m ops.billing_walkthrough serve`: prints the server command. Run
   what it prints in its own terminal.
5. In a second terminal: `venv/bin/python -m ops.billing_walkthrough relay --watch 1800`.
6. `venv/bin/python -m ops.billing_walkthrough checkout starter`: it opens nothing, it
   prints a Stripe Checkout URL. Open it and pay with the test card
   `4242 4242 4242 4242`, any future date, any CVC.
7. `venv/bin/python -m ops.billing_walkthrough status`. **Expect** `plan: starter`,
   `available: 1500`, and one `grant` entry of 1500.
8. `venv/bin/python -m ops.billing_walkthrough create`. This is one real Gemini call,
   about $0.04. **Expect** the job to finish, then `status` shows a `hold` of −15 and a
   `settle`, and 1485 available.
9. Redelivery: `venv/bin/python -m ops.billing_walkthrough relay --again`. **Expect**
   every event to answer 200 and `status` to show no second grant.
10. Top-up: `checkout topup`, pay again. **Expect** +750. (Before step 6, while the
    account has no plan, `checkout topup` should be refused: `plan_required`.)
11. Cancel: enable the Customer Portal once (Stripe → Settings → Billing → Customer
    portal), then cancel the Starter subscription from the Stripe dashboard (Customers →
    the walk's customer → subscription → Cancel immediately). **Expect** after `relay`
    the plan cleared and the subscription lot expired per `LAPSE_POLICY`, with the
    top-up lot untouched.

Not in the walk: an API-billed render. The render hold → settle was verified live on
fal separately; `serve --with-render` keeps `FAL_KEY` for anyone who wants it here too,
at real cost.

Dry-run on 2026-09-29, without a Stripe key, on the local server:
- A hand-built top-up event, signed as `relay` signs, granted 1,000.
- A redelivery returned the same lot, with no second entry.
- A wrong signature got a 400.
- The walk's customer read `exempt: false`, `available: 0` before the grant.

## Still open

- Phase 4 of the Stripe task doc — a per-account daily Gemini budget — is not
  built, and will not be (2026-10-08, Mike: the cost goes into the plan prices).
  An account on a plan thinks free per click, without a daily cap; the trial's
  thinking is capped once (above).
- The studio shell does not show the balance yet; `GET /api/billing/balance` is
  there for it.
- Negative balances (settle can overdraw; the next hold refuses), downgrade timing
  (portal default: at period end), and escheatment are the design doc's open calls,
  unchanged.

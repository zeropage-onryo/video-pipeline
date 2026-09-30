# Handoff — switch Stripe on for zeropage.studio (test mode first)

**From:** a Cowork session, 2026-09-29/30. **For:** Claude Code, in this repo on Mike's Mac.
**Mike's call:** TEST MODE FIRST (sk_test_ keys, 4242 card), live only after the whole flow passes.

## State right now

- The billing code is DONE and merged (2026-09-18): `app/billing.py`, `src/billing.py`,
  `src/charge.py`, `src/ledger.py`, plans in `src/pricing.PLANS` / `TOPUP`. Read
  `docs/BILLING.md` first — it is the spec and the switch-on checklist.
- NOTHING is configured: `.env` has no `STRIPE_*` or `BILLING_RETURN_URL`; Fly secrets unknown.
- `zeropage.studio` is a verified production domain on the Vercel project `zpf-web`
  (alongside `zpf-web.vercel.app`). The API is still `zeropage-studio.fly.dev`.
- NEW, UNCOMMITTED: `ops/stripe_setup.py` — written by the Cowork session, compiles, NEVER RUN.
  Review it before trusting it (see "Check the script" below).
- **Stale `.git/index.lock` (0 bytes, 2026-09-30 14:32)** left by the Cowork VM, which cannot
  delete files. No git process is running — `rm .git/index.lock` before any git command.

## What `ops/stripe_setup.py` does

`venv/bin/python -m ops.stripe_setup [--fly] [--live] [--rotate]`

1. Reads `STRIPE_SECRET_KEY` from `.env` (the only manual input). Refuses an sk_live_ key
   without `--live`, and `--live` with a test key.
2. Creates/reuses 7 Prices from `pricing.PLANS` + `TOPUP` (monthly $15/$35/$95, yearly
   $144/$336/$912 via `yearly_usd`, one-time $10), idempotent by lookup_key
   `zpf_<item>_<month|year|once>`; an amount change creates a new Price, moves the lookup key,
   archives the old one. Products found by `metadata.zpf_item`.
3. Webhook endpoint `https://zeropage-studio.fly.dev/billing/webhook` (direct to Fly — the
   Next rewrites don't proxy `/billing`, and the signature is over the raw body). Events:
   checkout.session.completed, invoice.paid, customer.subscription.updated,
   customer.subscription.deleted, charge.refunded. Secret is only shown at creation, so it
   reuses an existing endpoint only if `.env` already holds `STRIPE_WEBHOOK_SECRET`, else
   deletes + recreates.
4. Writes `STRIPE_PRICE_*` (+ `_YEAR`), `STRIPE_WEBHOOK_SECRET`,
   `BILLING_RETURN_URL=https://zeropage.studio` into `.env` (backup `.env.bak.stripe.<ts>`).
5. `--fly`: pipes the same values + `STRIPE_SECRET_KEY` into
   `fly secrets import -a zeropage-studio` (stdin, never argv). Prints no secret values.

## Check the script before running it

- stripe pinned `>=15,<16` in requirements.txt. Confirm on the installed version:
  `Price.list(lookup_keys=..., active=True)`, `Product.search(query="metadata['zpf_item']:'x'")`,
  `Price.create(..., transfer_lookup_key=True)`, `WebhookEndpoint.list/create/modify/delete`.
- Product.search is eventually consistent (can lag ~1 min after creation) — a fast rerun
  could create a duplicate Product. Harmless, but tidy it if it happens.
- Confirm the event list matches what `src/billing.handle_event` actually switches on.
- Consider a unit test with stripe mocked (the suite blocks the network — see
  `tests/conftest.py`), then commit on a branch, not main.

## Steps

0. `rm .git/index.lock`; branch `feat/stripe-setup`.
1. Mike: Stripe dashboard, Test mode ON → Developers → API keys → put
   `STRIPE_SECRET_KEY=sk_test_...` in `.env`. (Never paste it into chat; never print it.)
2. `venv/bin/pip install -r requirements.txt`
3. `venv/bin/python -m ops.stripe_setup` (local .env only) → check output, then `--fly`.
4. Confirm Fly secret `FRONTEND_ORIGINS` includes `https://zeropage.studio` (and
   `STUDIO_URL` is sensible) — `fly secrets list -a zeropage-studio` shows names/digests only;
   ask Mike if values are unknown. Without it, sign-in handoff / Checkout return on the new
   domain may break. See CLAUDE.md "The React studio gets its session through a handoff".
5. Mike, dashboard (test mode): Settings → Billing → Customer portal → Save.
6. After the Fly redeploy: API restart runs `accounts.init()` (adds `credit_exempt`,
   `stripe_customer_id`, `plan` columns — additive).
7. End-to-end test on https://zeropage.studio/pricing with card 4242 4242 4242 4242:
   - Stripe dashboard → Webhooks → endpoint shows 2xx deliveries.
   - `GET /api/billing/balance` shows a 1,500-credit `subscription` lot (Starter).
   - Use a NON-exempt account (Mike's `zeropage`/`antihero` are `credit_exempt` — a render
     there takes no hold). Either a second test account, or flip exemption off/on like
     2026-09-26: `set -a && source .env && set +a && venv/bin/python -m src.accounts credits zeropage --off` (then `--on`).
   - Approve ONE cheap render (LTX 2.3) ONLY WITH MIKE'S OK — his rule: no renders/generations
     unless he explicitly says so. Check `ledger.entries`: hold → settle with generation id.
   - Also test top-up (one-time) and the Customer Portal button.
8. Daily yearly-release job: `python -m src.billing release`. Nothing schedules it; `Charge.take()`
   and `balance()` release lazily so it isn't blocking. Ask Mike before adding it to the Fly
   cron (the token keeper is currently "the only scheduled job", by his choice).

## Going live (later, Mike decides)

Stripe account activated → `sk_live_` key in `.env` →
`venv/bin/python -m ops.stripe_setup --live --fly` → Customer portal Save in live mode →
one real small purchase → refund it (refunds are logged, NOT clawed back — docs/BILLING.md).

## Don't

- Don't print or commit keys; `.env` is gitignored, keep it that way.
- Don't point the webhook at zeropage.studio (Vercel) — it must hit Fly.
- Don't kick off renders or generations without Mike saying so.
- Don't change prices in Stripe by hand — change `pricing.PLANS`, `python -m src.pricing export`,
  rerun the script.

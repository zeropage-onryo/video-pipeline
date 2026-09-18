# Task — Stripe capture, the ledger wiring, and the operator's exemption

**Goal.** A person who is not versed in API keys signs in, buys credit or a
subscription with a card, and renders. One Gemini key — the operator's — serves
everybody. The operator's own account spends without being charged.

**Status when this was written (2026-09-16):** nothing here is started. The
ledger underneath it is finished and tested.

---

## 0. Read these before writing a line

- `docs/CREDIT_LEDGER_DESIGN.md` — the money design, written 2026-09-08 before any
  code. It is the authority; this task is the piece it says comes next.
- `src/ledger.py` — the prepaid credit ledger. **It is built.** `grant`, `hold`,
  `mark_submitted`, settle/release, `expire`, `reap`, `reconcile`,
  `on_subscription_lapsed`, `credits_for_usd`, `is_billable`.
- `src/generative.py::cap_error` — the refusal shape every gate in this repo copies.
- `src/accounts.py::set_manual_lane_operator` + `db.add_manual_lane_operator_column`
  — the pattern for a per-account permission column and its CLI verb.

### Three facts that decide the whole design

1. **The ledger is not a thing to build.** `credit_lots` / `credit_entries` exist,
   are in `db.OWNED_TABLES`, carry balance triggers (`db.add_ledger_balance_trigger`),
   take a per-account advisory lock, and — the part that matters here —
   `credit_lots` is **unique on (account_id, kind, source_ref)**, so a Stripe webhook
   delivered twice grants once. `grant()` returns the existing lot instead of raising.
   Webhook idempotency is therefore *already solved*; do not invent a second guard.

2. **`ledger.hold_for_render` IS A SEAM AND NOTHING CALLS IT.** Its own docstring says
   so and names the four call sites. **Until that wiring lands, credit is sold and
   never consumed.** Phase 1 below is not optional and does not come second.

3. **The LLM half IS charged to credits — reversed 2026-09-17, Mike's call.**
   `docs/CREDIT_LEDGER_DESIGN.md` says the opposite ("the subscription's cost of goods,
   not a metered line item") and it named its own trigger for revisiting: "if a
   customer's ideation spend ever rivals their render spend." The live numbers are that
   trigger — 232 concepts written against 4 picked, 0 carrying a `media_url`. The
   ideation-only user is not hypothetical, it is the ONLY user so far, and under the
   original design that user costs the operator money, pays nothing, and is eventually
   refused by a cap rather than charged. One balance is also the only story that
   explains itself to a customer: credits buy work.

   **But not by the same mechanism — see Phase 1b.** The hold/settle machinery exists
   for an event that is rare, slow and irreversible. A Gemini call is none of those, and
   putting the per-account advisory lock in front of every one of them serializes the
   hot path. Renders hold; LLM settles after the fact.

   This supersedes the "Also out: charging for the LLM half" paragraph in
   CREDIT_LEDGER_DESIGN.md. Update that doc in the same commit as the code -- a design
   doc that still argues the other way is how a later session reverts this by accident.

---

## Phase 1 — wire the holds (BEFORE any Stripe work)

Call `ledger.hold_for_render` at the four sites its docstring names — immediately
before the single irreversible submit in each adapter (`src/runway.py`, `src/fal.py`,
`src/higgsfield.py`, `src/veo.py`), then `mark_submitted` after the submit returns,
then settle on the real cost or release on failure.

Rules that are already decided and must not drift:

- The hold is **before** the submit, never after. The `generations` row is written
  after a poll loop that can run for minutes; money cannot wait on it.
- `is_billable(key_source, source=...)` decides whether to hold at all: a BYOK render
  (`key_source == "account"`) and a manual-lane import (`params["source"]` marker) are
  **not** billable and take no hold. `hold_for_render` returns None for those.
- A refusal reads like `cap_error`'s: same route, same JSON shape, same place in the
  order of gates. "Out of credits" is not a new kind of failure to the UI.

**Done when:** approving a render with an empty balance refuses before the HTTP
submit, the ledger shows hold → settle on success and hold → release on failure, and
`ledger.reconcile()` is clean after a burst of concurrent approvals.

---

## Phase 1b — the LLM half, settled not held

Same balance, different mechanism, for the reason in fact 3.

- **No hold, no lock per call.** `spend.record_call` already computes `cost_usd` for
  every Gemini call and already never raises. The debit rides that path.
- **One entry per job or per `run_id`, not per call.** A Create fires several calls
  (ground, write, plan the timeline) and a graph run about seven. Sum them at the
  boundary `spend.bind()` already defines and write ONE `credit_entries` row, kind
  `settle`, ref carrying the run/job id. Six locks per Create is the thing this avoids.
- **The gate is at the START of the job, not at the call.** A Create or a graph run
  checks `ledger.available(account_id)` before it begins and refuses in `cap_error`'s
  shape. A run already underway finishes and overdraws; the NEXT one is blocked. That
  is the policy the design doc already chose for renders (open question 1) applied
  here, and it is what keeps a half-written scene from dying mid-sentence over
  fractions of a cent.
- **An unpriced call must never debit zero.** `record_call` writes NULL when token
  counts are missing -- deliberately, "UNPRICED, never $0.00". Decide and write down
  which: charge a documented default estimate, or charge nothing AND mark the entry so
  the gap is visible in `costs.summary`. Silence is the one unacceptable answer: "we
  could not measure it" must not become "it was free".
- **`credits_for_usd` rounds UP per entry.** Batching per run rather than per call also
  stops that rounding from being applied seven times to seven fractions of a cent,
  which would quietly overcharge by more than the calls cost.

**Done when:** a Create on an empty balance refuses before the first billed call, a
completed graph run leaves exactly one settle entry whose credits match
`spend.by_run` for that `run_id`, and an unpriced call is visible rather than free.

---

## Phase 2 — Stripe capture

### Dependencies and configuration

- `stripe` is **not** in `requirements.txt`. Add it, pinned.
- Secrets (Fly, and `.env.example` documented, never committed):
  `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_*` for each plan and
  credit pack. Test-mode keys until the whole flow passes end to end.
- `accounts` needs `stripe_customer_id TEXT` — additive ALTER in `src/db.py` following
  `add_manual_lane_operator_column` exactly (guard on `table_exists`, guard on
  `columns`, no backfill, called again from `accounts.init`). `accounts` is in
  `db.SHARED_TABLES`, so no tenancy decision is needed for the column.

### Where the routes live — this is the part that is easy to get wrong

`app/main.py:301` includes the API router as
`app.include_router(api.router, dependencies=[Depends(auth.require_user_api)])`.
**Stripe cannot sign in.** So:

- **The webhook is NOT under `/api`.** New `app/billing.py` with its own router at
  `/billing/webhook`, included in `main.py` beside `auth.router` — no session
  dependency, no `model_connections.mutation_header`. Its authentication is the
  Stripe signature and nothing else.
- **Everything customer-facing IS under `/api`**, with `Depends(auth.current_account_id)`
  like every other route (`tests/test_tenancy.py` fails the build otherwise):
  `POST /api/billing/checkout` (returns a Checkout Session URL),
  `POST /api/billing/portal` (returns a Customer Portal URL),
  `GET /api/billing/balance` (`ledger.available` + lots, for the UI).

### The webhook

- Read the **raw** body (`await request.body()`) before anything parses it, and verify
  with `stripe.Webhook.construct_event`. A failed signature is a 400 and writes nothing.
- Handle an explicit allowlist of event types and ignore the rest silently:
  - `checkout.session.completed` → `grant(kind="purchase", source_ref=<payment_intent>)`
  - `invoice.paid` → `grant(kind="subscription", source_ref=<subscription period id>)`
  - `customer.subscription.deleted` (and a lapsed/unpaid state) → `ledger.on_subscription_lapsed(account_id)`
  - `charge.refunded` → an `adjustment` lot or a documented decision not to claw back
- Map Stripe customer → account via `accounts.stripe_customer_id`. An event for an
  unknown customer is logged and **acked 200**, never retried forever and never
  guessed at.
- `grant()` RAISES by design (unlike `spend.record_call`, which swallows). Let a real
  failure return 500 so Stripe retries; only unknown-customer and unhandled-type are
  200s.

### Prices

`ledger.credits_for_usd` rounds **up**, one credit = one US cent, and the peg is
published. Margin goes on the subscription price and the pack price, not on a secret
exchange rate. The render cost inputs are the dated per-second tables in
`src/fal.py`, `src/runway.py`, `src/higgsfield.py`, `src/veo.py`.

### Tests

`tests/conftest.py` blocks all network, and that must stay true — no test may reach
Stripe. Build events as fixtures and sign them with the test webhook secret so
`construct_event` runs for real. Cover: a valid event grants once; **the same event
delivered twice grants once** (the unique index, asserted end to end); a bad signature
writes nothing; an unknown customer acks without granting; a subscription-deleted
event expires the lots `LAPSE_POLICY` says die and leaves `adjustment` alone.

---

## Phase 3 — the operator's exemption

Mike's own account spends without being charged. Build it as a **property of the
account row**, applied in **one** predicate.

- `accounts.credit_exempt BOOLEAN NOT NULL DEFAULT FALSE` — additive ALTER, no
  backfill, same shape as `manual_lane_operator`. Every account starts FALSE,
  including the bootstrap one.
- `python -m src.accounts credits <slug> --on|--off`, modelled on the `operator`
  subcommand in `accounts.main`.
- Applied **inside `hold_for_render`** (the one place that already decides whether a
  render is billable) — never as an `if account_id == …` at a call site. This is the
  same failure that left `uncanny_judge` written-but-never-called and made
  `*_SPEND_OK` an approval that was always on.
- **Still write the entry.** Exempt from the charge, not from the record: a zero-credit
  or clearly-marked lot/entry so cost-per-kept-clip keeps its heaviest user's data.
  Same choice already made for manual-lane renders (a FREE row with `cost_usd` NULL
  rather than no row).
- **The daily caps still apply to an exempt account.** Billing and runaway protection
  are different gates; `RUNWAY_DAILY_CAP` and friends are what stop a loop rendering
  forty clips at 3am, and that risk does not care who pays.
- Keep the flag two-way and **test the refusal path**, because an exempt operator never
  walks it. Same reasoning as keeping `ZEROPAGE_GATES=hard` tested: an untested way
  back is not one.

---

## Phase 4 — the Gemini key's own wall (the free tier's, now that credits meter)

`gemini_utils.api_key_for(account_id)` falls back to the operator's key, so a second
account's ideation currently bills Mike with nothing in front of it. The renderers
have `generative.cap_error`; Gemini is the one provider with no wall.

With Phase 1b in place the ledger is the wall for anyone holding credit, so this cap
shrinks to what it should always have been: the **free tier's** limit, and a backstop
on paths that hold no credit at all (the nightly walk, the scout, the CLI -- the
installation's own runs, which pass no account_id).

Add a per-account **daily dollar budget** on billed Gemini calls: read
`spend.spent_today(account_id=…)` (exists), refuse in `cap_error`'s shape when over,
skip it when `key_source == "account"` (they are paying) or the account is
`credit_exempt`. A credit balance covers it; a zero balance on a free account meets
this instead of an empty ledger, so a new signup gets a usable trial rather than a
refusal on their first Create.

Ship this one first if Stripe slips: it is small, and it is the only thing between a
stranger and the operator's Gemini balance.

---

## Decide before the first sale (Mike, not Claude Code)

From `docs/CREDIT_LEDGER_DESIGN.md`, still open:

1. **Negative balances** — settle can overdraw when actual exceeds estimate. Currently
   designed as: allow the overdraft, block the *next* hold. Confirm or change.
2. **Downgrade / cancellation** — does unused subscription allowance die immediately
   or at period end?
3. **Escheatment** — a 2-month expiry interacts with state gift-card law. The design
   doc says an accountant's half hour before selling a credit, not after.

Plus, new:

4. **The plan shape** — subscription tiers, pack sizes, the free allowance a new signup
   gets, and whether a free tier exists at all.
5. **What a thought costs.** With the LLM half now metered (fact 3), ideation needs a
   published price. The input is measured: roughly 6.8 calls and $0.043 per graph run,
   and `costs.summary`/`spend.by_stage` give the per-stage split. At the 1 credit = 1
   cent peg a graph run is ~5 credits at cost. Decide the markup, and decide whether a
   Create and a nightly walk are priced the same way — the walk is 10 runs and the
   customer is asleep for it.

## Sequencing note

Nothing has been rendered onto a concept row yet (0 concepts carry a `media_url`; 4
of 232 picked). Phase 1 and Phase 4 are worth doing now regardless — one makes credit
real, the other protects the operator's key. Phase 2 is worth doing when someone other
than the operator has taken a scene through Approve to a finished clip and said they
would pay for it.

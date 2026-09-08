# Credit ledger — design

Written 2026-09-08, before any of it is built, because the ordering decisions below
are the ones that cost real money if they are wrong and are expensive to change once
a customer has a balance.

## What this is for

Customers buy credits — by subscription allowance or by top-up — and spend them on
renders that this pipeline routes to a provider (Runway, Higgsfield, Veo, and fal
when its adapter lands). The ledger has to answer three questions truthfully, at any
moment, including mid-render and after a crash: **what does this account have, what
has it committed, and what did it actually consume.**

It is not a metering system. `src/spend.py` and `src/costs.py` already meter, and
they are deliberately never-raises: a lost row costs a number on a dashboard. A
ledger write that silently fails costs money, so **every ledger write raises**. That
is the single most important difference between this module and the two that look
like it.

## Decisions taken (Mike, 2026-09-07/08)

| Question | Decision |
|---|---|
| Unit | **Integer credits, 1 credit = 1 cent.** Never floats. |
| Acquisition | **Both** — a recurring subscription allowance *and* pay-as-you-go top-ups. |
| Failed renders | **Provider failures and QC failures are refunded**; a delivered clip the customer merely dislikes is charged. |
| Expiry | **2 months** from grant, and credit dies when the subscription lapses (2026-09-08). Per-lot-kind policy: see "Expiry and lapse" below. |
| Scope | Ledger + the three `account_id` defects (done) + a key-source flag (done). |

Two consequences worth stating plainly, because they follow from the answers rather
than from anything decided directly:

**Subscription and top-up cannot share one balance number.** An allowance granted by a
plan and a credit bought with cash are different promises even when they expire on the
same clock, so credits arrive in **lots**, each carrying its own expiry and its own
lapse policy, and are consumed **soonest-expiry-first**. That is what makes "your
monthly allowance burns before the credit you paid for" true without anyone having to
remember it, and it is what lets the two kinds be governed differently later without a
migration.

**Refunding provider failures makes your cost line real.** Every failed render is
money you paid the provider and did not bill. That is the differentiator, and it is
also a number that must be visible from day one or it will grow quietly — hence
`waste_usd` on the reconciliation view below.

## Expiry and lapse

Two rules, and they compose:

1. **A lot expires two months after it is granted.** `expires_at = granted_at + 2
   months`, enforced on read (a lot past its date contributes nothing to available
   balance) and swept by `ledger.expire_due()` which writes the `expire` entries so
   the audit trail shows where the credit went.
2. **A lot dies when the subscription lapses**, if its kind says so.
   `LAPSE_POLICY: dict[str, bool]` maps lot kind to "dies on lapse", defaulting to
   `{"subscription": True, "purchase": True, "promo": True, "refund": False}` —
   which is the rule as asked for on 2026-09-08. `ledger.on_subscription_lapsed()`
   expires every matching lot and is called by whatever owns subscription state
   (Stripe's webhook, later).

**The `purchase` entry in that map is the one to revisit.** Voiding credit a customer
paid cash for, because a separate subscription ended, is the shape that draws
chargebacks — and prepaid balances fall under gift-card and escheatment law in many
states, with minimum honor periods measured in years rather than months. It is a
constant here rather than a hardcoded rule specifically so it can be softened after an
accountant has looked at it, without touching a row of data.

Not decided, and it will come up the first time somebody resubscribes: whether credit
expired by lapse is **restored** if they come back within some window. Most products
say no. Doing it would mean expiring lots by writing an `expire` entry rather than
zeroing the lot, which the design already does — so the door is open either way.

## The unit

One credit is one US cent. Integers only, `BIGINT`, no `NUMERIC`, no floats anywhere
in the ledger path. The existing `cost_usd` columns on `generations` and `llm_calls`
stay floats — they are estimates for a dashboard and are not this. Conversion happens
at exactly one place, `ledger.credits_for_usd(usd)`, which rounds **up**, so rounding
never silently favours the customer at your expense across thousands of renders.

The peg is published. If a margin is ever wanted, it goes on the *subscription price*
or on an explicit per-model markup recorded on the hold — never by quietly moving the
peg, which is the mechanic you would be selling against.

## Tables

Two tables, both owned (`db.OWNED_TABLES`, `own_table()` in `init`), both satisfying
the static SQL audit in `tests/test_tenancy.py` — every literal touching them carries
the substring `account_id`, and uses `IS NOT DISTINCT FROM` rather than `=`.

### `credit_lots` — where credit comes from

    id, account_id, kind, credits_granted, credits_remaining,
    granted_at, expires_at, source_ref, note

`kind` is one of `subscription`, `purchase`, `refund`, `promo`, `adjustment`.
`credits_remaining` is a denormalised running figure, and the entries table below is
the truth — a reconciliation test asserts they agree. `source_ref` holds the Stripe
payment intent or the subscription period id, and is **unique per (account, kind,
source_ref)** so a webhook delivered twice cannot grant twice.

### `credit_entries` — append-only, every movement

    id, account_id, lot_id, delta, kind, ref, generation_id, created_at

`delta` is signed credits. `kind` is one of `grant`, `hold`, `settle`, `release`,
`expire`. Nothing is ever updated or deleted; a correction is another row. `ref` is
the **idempotency key** — a caller that retries with the same `ref` gets the existing
entry back rather than a second debit, which is what makes the hold safe to retry
across a network blip.

Balance is `SUM(delta)` over an account's non-expired lots. Available balance is that
minus outstanding holds.

## The lifecycle, against the moment money is actually spent

The survey established exactly where the irreversible commit is: the single HTTP
submit inside each adapter's `generate_video` (`runway.py`'s
`client.image_to_video.create(...)`, `higgsfield.py`'s `_submit_and_wait`). Everything
before it is intention; everything after it is bookkeeping the provider does not care
about. Today the `generations` row — the only record that a render happened — is
written *after* that call returns, across a poll loop that can run for minutes. A
crash in that window means the provider billed and nothing here knows.

So the ledger writes **before** the submit, not after:

1. **HOLD.** Estimate the cost (`provider.estimate_cost`), convert to credits, and in
   one transaction: take a per-account advisory lock, compute available balance, and
   either insert a negative `hold` entry or raise `InsufficientCredit`. Returns a
   `hold_id`. Nothing has been spent yet — if this raises, no HTTP call is made.
2. **SUBMIT.** The adapter does what it does today, unchanged.
3. **SETTLE** on a delivered clip that passes QC: insert the adjusting entry so the
   net debit equals the *actual* cost, and link `generation_id`. If actual exceeds
   the estimate, the difference is debited — and if that would overdraw, it is
   debited anyway and the balance goes negative, because the money is already spent
   and pretending otherwise is the lie that breaks reconciliation.
4. **RELEASE** on a provider error, a timeout, or a QC failure: reverse the hold in
   full. The customer pays nothing; the cost lands in `waste_usd`.

A render whose credential resolved to `key_source == "account"` — the BYOK case the
prerequisite work just made visible — **takes no hold at all.** The customer paid
their provider directly; debiting them again would be charging twice for one clip.

## Atomicity

`src/db.py` opens a fresh connection per `with connect()` block, there is no pool,
and nothing in the repo currently uses `FOR UPDATE` or advisory locks. The cap check
(`generative.cap_error`) is already read-then-act with no lock, which is why two
simultaneous approvals can both pass a cap of six.

The hold must not inherit that. Inside the hold's single transaction:

    SELECT pg_advisory_xact_lock(hashtext('credit:' || %s))   -- the account id

A transaction-scoped advisory lock releases on commit *or* rollback, so a crashed
worker cannot wedge an account's balance — which a `FOR UPDATE` on a balance row
would also give, but only if every future writer remembers to take it. The lock is
per account, so two customers never contend, and the critical section is one SELECT
and one INSERT.

Cost: a lock held across this repo's connection-per-call pattern. At the render rates
in question that is irrelevant; if it ever is not, the fix is a pool, not a weaker
lock.

## Orphans, and the thing that will actually go wrong

Holds outlive their renders when a worker dies between submit and settle. A hold that
is never settled or released is a customer's balance held hostage forever.

`ledger.reap(older_than)` runs on the same schedule as the nightly: for each
outstanding hold past its age, look for the `generations` row the render would have
written. Found and usable → settle. Found and failed, or absent → release, and log
it loudly, because an absent row after a successful provider submit means money was
spent that nothing recorded, and that is the one condition worth waking up for.

The reaper is the reason `hold` carries the provider and the estimate: without them
it cannot tell a dead render from a slow one.

## Reconciliation

Weekly, and on demand from `/costs`: for a window, compare credits settled against
`SUM(generations.cost_usd)` for the same accounts and the same period. They will not
match exactly — `cost_usd` is an estimate at submit time and the ledger settles on the
same estimate today — so the check is that they match *within tolerance* and that the
drift is not growing. When a provider invoice can actually be read per render (fal
publishes real per-second rates; Runway and Higgsfield do not), settle switches to the
invoice and this becomes a real check instead of a consistency one.

Three figures surface on `/costs`, per account and in total:
`outstanding_credits` (your liability), `waste_usd` (refunded failures — your cost of
the promise), and `settled_vs_metered_drift`.

## Tenancy and the audit

- `credit_lots` and `credit_entries` go in `db.OWNED_TABLES`, not `SHARED_TABLES`.
- Both get `account_id BIGINT` and `own_table()` in `init`, matching
  `add_nightly_runs_table`'s idempotent shape.
- `init` is registered in `app/main.py`'s lifespan and in
  `tests/test_tenancy.py::_init_everything`, or the schema audit never sees them.
- Every SQL literal touching either table contains `account_id` **in the same string
  literal** — the scanner cannot see a predicate assembled next door.
- One deliberately installation-wide aggregate is expected (total credits
  outstanding, for the operator's own books). It goes in `UNSCOPED_ALLOWED` with its
  reason, as an exact substring of the emitted SQL.

## Explicitly not in this build

Stripe, invoices, tax, dunning, refunds to a card, plan management, and any UI. This
is the ledger only: grant, hold, settle, release, expire, reap, reconcile. Payment
capture is a separate piece that calls `grant()` from a webhook, and it should not be
started until the ledger's own tests pass — a billing bug found through Stripe is a
billing bug found in front of a customer.

Also out: charging for the LLM half. Concepts, judges, the scout and the RAG calls
are metered in `llm_calls` and are cheap; they are the subscription's cost of goods,
not a metered line item. Revisit only if a customer's ideation spend ever rivals
their render spend.

## Open, and worth deciding before the first sale

1. **Negative balances.** Settle can overdraw when actual exceeds estimate. Cap the
   estimate's optimism, or allow the overdraft and block the *next* hold? Currently
   designed as: allow it, block the next hold.
2. **Subscription allowance on downgrade or cancellation** — does unused allowance
   die immediately or at period end?
3. **Escheatment.** Twelve-month expiry interacts with state gift-card law. Worth an
   accountant's half hour before you sell a single credit, not after.

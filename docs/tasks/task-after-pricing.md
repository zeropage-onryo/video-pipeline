# Task list — after pricing steps 1–5 (written 2026-09-19)

Where things stand: pricing steps 1–5 are on `main` (`MARKUP = "2.4"`, a billable render
needs its signed quote token — PRs #21, #32). The ledger sandwich (step 6) is on `main`
through the Stripe billing commit `390157f` (`src/charge.py`, wired into all four adapters).
`zeropage` and `antihero` are both `credit_exempt` on the live database. Read
`docs/tasks/task-pricing-and-quotes.md` ("As built" sections) and
`docs/tasks/task-pricing-and-quotes-handoff-2.md` (the rules that still bind) first.

## 0. Mike's, not Claude's — the one real billed render

- [ ] Runway key into Fly's secrets (`fly secrets set -a zeropage-studio RUNWAYML_API_SECRET=...`),
      or clear the Higgsfield `423 Locked` in their dashboard.
- [ ] Approve #361 "The Crimson Descent" in the Queue (`gen4_turbo`, 5 s, $0.25). Until task 1
      lands, antihero scenes only show at `zeropage-studio.fly.dev/ui?legacy=1&view=queue`.
- [ ] Then (Claude, read-only): the `generations` row (`cost_usd`, `key_source`, vendor tool),
      `media_url` on #361, NO credit entry (exempt), and that the approve body carried its
      token — the one part of step 5 never confirmed in production.

## 1. The React Queue hides the other brand, and its account switch is dead  (BACKLOG #19)

- [ ] Reproduce: `GET /api/queue/pending` returns every waiting scene; `web/src/app/studio/queue/page.tsx`
      draws only the active brand's. 15 of 18 were invisible on 2026-09-18.
- [ ] The account menu (`web/src/components/studio/shell.tsx`) sends no `/brand` request. Make it
      `POST /brand/{name}` THROUGH THE PROXY (own origin, so the cookie lands first-party — see
      CLAUDE.md's handoff section), then refetch `/api/me` and the Queue.
- [ ] Check the vanilla shell's behaviour (`?brand=` on the request) and match it; do not invent
      a second rule for which brand a list shows.
- [ ] Verify in a browser (recipe in handoff-2), both brands, switch both ways.

## 2. A render that fails at the provider submit leaves no `generations` row  (BACKLOG #18)

- [ ] Read `src/charge.py` and each adapter's never-raises edge: where is the row written
      relative to `charge.take()` / the submit? Does `charge.release` run on a submit failure?
- [ ] Reproduce with a stub whose submit raises (the #361 case: `HTTP 423`). Assert: a
      `generations` row exists with the error, the hold is released, nothing is settled.
- [ ] Fix in all four adapters the same way; revert-and-red on each.
- [ ] Never move a ledger write to after the provider submit.

## 3. Bind the hold to the verified quote

- [ ] Today `Charge` holds `ledger.charge_credits(estimate_usd)`; the route verified a Quote and
      then drops it. They agree only because both go through `pricing.credits_for`.
- [ ] `spend_approved(approved=..., quote=...)` — a change of shape, not location — and `Charge`
      holds `quote.credits` when a Quote is in hand; the estimate stays the fallback for
      unattended callers.
- [ ] COORDINATE FIRST: `git log origin/main -- src/charge.py src/ledger.py` — the Stripe session
      may still be in these files. Do not start this one while it is.

## Smaller, any time

- [ ] `accounts.is_credit_exempt`'s table/column pre-check is redundant (the `except` below it
      already answers False) — delete it or leave it, but know it is not a guard.
- [ ] `/api/generate/run`'s video branch calls `runway.has_key()` / `generate_from_prompt` with no
      `account_id` — it can only spend the operator's env key.
- [ ] `src.accounts` CLI never loads `.env` (documented in CLAUDE.md, PR #43). Consider a
      `load_dotenv()` in `accounts.main` so the documented command cannot hit the wrong database.
- [ ] Nightly `spent_usd` under-report — candidates listed in the pricing spec's "As built".

## Rules (short form — the handoff has the rest)

Never point the suite at Supabase; `TEST_DSN=postgresql://zeropage:zeropage@localhost:5432/zeropage`,
the MAIN checkout's venv (worktrees have none). Branch from `origin/main`, PR, no merge without
"merge". Check `git worktree list` for parallel sessions first. A test that stays green when its
line is reverted proves nothing. The API auto-deploys on a push to `main`.

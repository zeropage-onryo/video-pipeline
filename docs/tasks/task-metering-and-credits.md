# Task: close the spend holes, and show credits everywhere (plan, 2026-10-07)

Mike's ask: "wrap up a plan for 2 and 4". Item 2 was "meter the unmetered spend" and item 4 was
"credits everywhere". This is a plan only, and nothing in it is built yet. It was written from
a read of `main` at `0072b0d`. File:line references are as of that commit.

## What is already true (better than the backlog said)

- **Every still holds credits now.** That covers Nano (`nano_banana.generate_from_prompt`, hold
  at :413), fal stills (`fal.generate_image_from_prompt`, :1692), element sheets, composer image
  sends, keyframes and refgen from the MCP. The `NANO_DAILY_CAP` is gone: the balance is the
  limit.
- **Every video door holds credits** and needs a signed quote.
- **Create is free per click, by Mike's call (2026-09-29).** It is included in the plan.
  `charge.create_refusal` returns 402 only for an account with no plan and a zero balance.

So the money that leaks is **model text, not renders**.

## Part 1: the holes (item 2)

### 1a. Routes that call Gemini with no gate at all

Each of these runs a billed model call for any signed-in account, including a brand-new
open sign-up:

| Route | File:line | What it spends |
|---|---|---|
| `POST /api/creative-guide` (every composer send and every pill turn) | `app/api.py:596` | Guide turn, `find_references` (reference_needs + refcheck + Serper), `link_sheet`, `check_directions` → story_judge |
| `POST /api/projects/draft-brief` | `app/api.py:2614` | one Gemini call |
| `POST /api/assets/{kind}` vision describe, `/assets/backfill?describe=` | `app/api.py:1524/1634/1639/1648` | vision call per photo |
| `POST /api/concepts/{id}/direct`, `/shots/{n}/refine` | `app/api.py:4152/4195` | director |
| `POST /api/workflows/exec/enhance` (+ Run all's enhance node) | `app/api.py:5629` | enhance |
| `POST /api/scout/run` | `app/api.py:2759` | scout + story_judge |
| `POST /api/cut/index`, `/cut/projects/{id}/index`, `/cut/projects/{id}/agent` | `app/cut_routes.py:361/935/820` | Gemini shot log, fal Whisper, cut agent |

**Fix:** every one of them asks the same `_create_gate` that `/scenes/run` already asks. This
is one line per route plus a test. It keeps Mike's rule exactly: these stay free per click,
and you just need a plan or a balance to use them. The Guide is the one that matters most,
since it is the first thing a new account touches.

### 1b. The real exposure: a trial account can think forever

`create_refusal` passes whenever `available > 0`. A new open sign-up gets 100 trial credits,
so it may run **unlimited** Creates and Guide turns on Mike's Gemini key until those 100 credits
are spent on a still, which it never has to do. On today's numbers a Guide turn costs ~0.4¢ on
Flash and ~1.5¢ on Pro, and a Create with its timeline costs about 4¢. A script could spend
dollars an hour.

There are two ways to close it. **I recommend A.**

**A. A daily "included thinking" allowance (keeps Create free per click).**
- Every account gets a daily dollar budget of model calls. `spend.spent_today(account_id=)`
  already sums `llm_calls.cost_usd` for today, per account.
- The allowance comes from the plan: a new `Plan.included_llm_usd_day` field. Suggested values:
  no plan (trial or top-up only) $0.25, Starter ($15) $1, Creator ($35) $2.50, Studio ($95)
  $6. That's under 20% of each plan's price even if used every day. `ZEROPAGE_INCLUDED_LLM_USD`
  overrides the no-plan default.
- `charge.create_refusal` gains one check after the balance check: if `spent_today >= allowance`,
  refuse with `CREATE_DAILY_REFUSAL` ("today's included thinking is used — it resets at
  midnight UTC, or upgrade"). It answers 402 `daily_thinking_used` so the UI can word it
  differently from "top up".
- Exempt accounts and the unowned pool are untouched, and it fails open on a read error, both
  exactly as today.
- Cost: one SUM per gated request. `spend.spent_today` already filters on `account_id` and
  `created_at`, but the only index is `idx_llm_calls_run`. Add `CREATE INDEX IF NOT EXISTS
  idx_llm_calls_account_day ON llm_calls (account_id, created_at)` to `spend.SCHEMA` in the
  same PR.

**B. Charge credits for thinking.** Debit `charge_credits(cost_usd)` after each `record_call`.
This reverses Mike's 2026-09-29 call, makes every chat turn visibly cost something, and needs
a post-hoc debit path the ledger doesn't have (holds are pre-spend by design). I don't
recommend it unless he wants per-click pricing for text.

### 1c. Calls that are not even metered

These have no USD, so the allowance can't see them.

- `story_judge.judge_ad` / `judge_spark` (`src/story_judge.py:170, :198`) call raw
  `generate_content` with no `record_call`. They run on **every Guide reply that has
  directions** (`assistant_brain.check_directions`). Fix: add `spend.record_call(stage=
  "story_judge", ...)` after each call. The stage needs adding to `spend.STAGES`.
- `rag.embed_texts` (`src/rag.py:143`) runs on every ingest and query and is not metered.
  Fix: record with stage `embed` and price `gemini-embedding-001` in `DEFAULT_PRICES`. This is
  small, but it's the last blind spot on `/costs`.
- fal Whisper (`src/cut/index.py:312`) records `usage={}`, so `cost_usd` is NULL. Fix: price by
  audio seconds (fal's per-minute rate) and pass it as the explicit cost.

### 1d. Small correctness gaps

- **Nano never calls `Charge.submitted()`** (`src/nano_banana.py:413-454`). That's the line
  that tells the reaper "the provider was asked, don't release blindly". Add it as the last line
  before the image call, the same as fal.
- **Refgen from the scout crawl is charged to nobody** (`src/scout.py:1815` passes no
  `account_id`). Pass the account that ran the scout, which is the route's
  `current_account_id`. The CLI stays unowned.
- **Serper image search is unmetered** (`src/imagesearch.py:228`). It's cheap, but it's paid.
  Record a flat per-query cost under stage `image_search`.

### Order and tests

1. 1c + 1d (metering and correctness, no behaviour change). Tests: each call writes a row;
   Nano calls `submitted()` before the provider.
2. 1a (gate the ungated routes). Tests: each route answers 402 `subscribe_or_top_up` for a
   zero-balance, no-plan account, with no model call made. `conftest`'s network guard catches a
   miss.
3. 1b option A. Tests: an account over its allowance gets 402 `daily_thinking_used`; exempt
   and unowned accounts never do; a read error fails open.
4. UI: the composer and pill word the two 402s differently ("Top up" vs "Resets at midnight ·
   Upgrade").

**Decision needed from Mike:** A or B, and the four allowance numbers.

## Part 2: credits everywhere (item 4)

The rule is that the person sees **credits, never dollars**. Dollars remain only on operator dev
pages (`/costs`, the Dev Studio) and on marketing plan prices.

### What still shows dollars

| Where | File:line | Today |
|---|---|---|
| Director Generate node footer | `web/src/components/flows/flow-workspace.tsx:494-495` | `est. $X.XX` from `rw.estimate_usd` |
| Director inspector "spend" | `flow-workspace.tsx:1522` | `$X.XX per N-second clip` |
| (the source of both) | `flow-workspace.tsx:1340-1342`, `app/api.py:3105` `_render_state` | `_render_state` returns `estimate_usd` and **no credits**; `gen.credits` exists but is unused |
| Queue approve toast | `web/src/app/studio/queue/page.tsx:356` | falls back to `~$` when `quote.credits` is null |
| Queue page tally | `queue/page.tsx:497-510` | `~$` for any plan without credits |
| Queue renderer status line | `queue/page.tsx:576` | `~$X a clip` |
| Shared price text | `web/src/lib/render-choice.ts:186-190` (`priceText`), `:153` (`planFor` client USD estimate) | `~$` fallback; a client-side USD estimate when no quote |
| Vanilla `/ui` Queue | `app/static/zpf/queue.js:197, 244-245, 352-368` | dollars only, no credits path |

### Changes

1. **Server:** `_render_state` (`app/api.py:3105`) adds `credits` via
   `pricing.credits_for(pricing.usd_micros(estimate_usd))`, the same conversion `display()`
   uses. `display().credits` is already present for every billable render. Assert that in a
   test so the client can drop its fallbacks.
2. **`render-choice.ts`:** `priceText` never formats USD. With no credits it says "pricing…"
   (as `planFor(quote=null)` already does), and an exempt account says `NOT_CHARGED`. Delete
   the client-side `estimate()` USD path in `planFor`, because the server prices everything now
   (the 2026-09-18 "no JS price twin" rule).
3. **Queue page:** the toast, tally and status line read credits through `creditsText`.
4. **Director:** the Generate node footer and inspector read `rw.credits` / `gen.credits`
   ("≈ 87 cr per 6s clip"). The Nano node already uses `balance.prices.still`.
5. **Vanilla `queue.js`:** `/ui` is the legacy shell (`?legacy=1`). Either delete its approve
   price text and show "Approve in the studio" with a link, or port `creditsText`. I recommend
   deleting it: nobody should spend from the legacy shell.
6. **Balance freshness:** `announceBalanceChange()` (`studio-api.ts:688`) is fired only by the
   composer and the Queue. Add it after the Director canvas Run / Run all, an element-sheet draw
   (`elements/page.tsx` job completion and `add-element.tsx`), Draw keyframes completion, and
   any pill action. Without it the header pill shows a stale number after a spend.
7. **Prices where they're missing:** the Elements page's "draw sheet" / redraw button gets
   `· N cr` (`balance.prices.still`, as `add-element.tsx` already does). The pill's credit card
   shows on any page where the newest proposal spends, not only `/studio/queue`.
8. **A guard test** (`web/src/lib/__tests__/no-dollars.test.ts`, run in the existing node
   tests): it scans `web/src/app/studio/**` and `web/src/components/{studio,flows}/**` for
   `~$`, `$${`, `.toFixed(2)` next to `estimate_usd`, and fails with the file:line. The marketing
   folders are allow-listed.

### Order

1, 2, 3, 4 together as one PR (they share `render-choice.ts`). Then 6 and 7. Then 5 and 8.

## Verification for both parts

- `pytest tests/ -q` and `ruff check .` as CI runs them, plus `next build --webpack`, tsc and
  eslint.
- Click it against a stub API: a zero-balance trial account on the composer (402 wording), an
  over-allowance account, and a paid account through Queue, Director and Elements. No dollar
  sign on any studio page. The header pill moves after each spend.
- **No real spend.** Every test uses stubs. A live check is Mike's, with his go-ahead.

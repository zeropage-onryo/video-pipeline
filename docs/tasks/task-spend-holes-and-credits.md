# Task: close the spend holes, and show credits everywhere

Planned 2026-10-07 from a read of `main` at `0072b0d` (Mike's ask: "wrap up a plan
for 2 and 4" -- item 2 was "meter the unmetered spend", item 4 "credits
everywhere"). Built 2026-10-08, **except 1b, which Mike deferred** ("skip 1b for
now"; BACKLOG #24 keeps the two options). The "As built" section at the end says
what landed and where it differs from the plan.

## What was already true

- Every still holds credits (Nano, fal stills, element sheets, composer image
  sends, keyframes, refgen from the MCP). `NANO_DAILY_CAP` is gone: the balance
  is the limit.
- Every video door holds credits and needs a signed quote.
- Create is free per click, by Mike's call (2026-09-29): included in the plan.
  `charge.create_refusal` answers 402 only for an account with no plan and a
  zero balance.

So the money that leaked was **model text, not renders**.

## Part 1: the holes (item 2)

### 1a. Routes that called Gemini with no gate at all

| Route | What it spends |
|---|---|
| `POST /api/creative-guide` (every composer send and pill turn) | Guide turn, `find_references` (reference_needs + refcheck + Serper), `link_sheet`, `check_directions` → story_judge |
| `POST /api/projects/draft-brief` | one Gemini call |
| `POST /api/assets/{kind}`, `/assets/backfill` | vision call per photo, an embedding per save |
| `POST /api/concepts/{id}/direct`, `/shots/{n}/refine` | director |
| `POST /api/workflows/exec/enhance` (+ Run all's enhance node) | enhance |
| `POST /api/scout/run` | scout + story_judge |
| `POST /api/cut/index`, `/cut/projects/{id}/index`, `/cut/projects/{id}/agent` | Gemini shot log, fal Whisper, cut agent |

**Fix:** every one asks the same `_create_gate` that `/scenes/run` asks. Each
stays free per click; you just need a plan or a balance to use them.

### 1b. A trial account can think forever -- DEFERRED

`create_refusal` passes whenever `available > 0`, and a new sign-up gets 100
trial credits, so it may run unlimited Creates and Guide turns until it spends
those credits on a still, which it never has to do. Two ways to close it are in
BACKLOG #24 (a daily "included thinking" allowance per plan, recommended; or
charging credits per model call). Not built: Mike's call, 2026-10-08.

### 1c. Calls that were not even metered

- `story_judge.judge_ad` / `judge_spark` call raw `generate_content` with no
  `record_call`, and run on every Guide reply that has directions.
- `rag.embed_texts` runs on every ingest and query and was not metered.
- fal Whisper (`src/cut/index.py`) recorded `usage={}`, so `cost_usd` was NULL.

### 1d. Small correctness gaps

- Nano never called `Charge.submitted()`, the line that tells the reaper "the
  provider was asked, don't release blindly".
- Refgen from the scout crawl was charged to nobody (`scout.scout` passed no
  account to `refgen.render_for_finding`).
- Serper image search was unmetered.

## Part 2: credits everywhere (item 4)

The rule: the person sees **credits, never dollars**. Dollars stay only on the
operator's pages (`/costs`, the Dev Studio) and on the marketing plan prices.

What showed dollars: the Director's Generate node footer (`est. $X.XX`) and
inspector (`$X.XX per N-second clip`), the Queue's approve toast, page tally and
renderer status line (all `~$` fallbacks), the shared `priceText` /
`planFor` (a client-side USD estimate when there was no quote), and the legacy
`/ui` Queue (dollars only). `_render_state` returned `estimate_usd` and no
credits.

## As built (2026-10-08)

### 1c / 1d -- metering and correctness

- `spend.record_call` takes `cost_usd=` for a call not priced per token; such a
  row keeps NULL token counts, and `spend.reprice` now skips any row with no
  counts (it used to null an explicit price; an unmeasured row stays unpriced
  either way).
- New stages: `story_judge`, `embed`, `image_search`. `gemini-embedding-001`
  is priced at $0.15 per 1M input tokens.
- `rag.embed_texts` writes one `embed` row per batch. The Gemini API's embed
  response carries no usage block, so the token count is the per-embedding
  `statistics.token_count` when every vector has one (Vertex does), else
  characters / 4 (`rag._embed_usage`). Rounded to the micro-dollar like every
  estimate, so a one-line query embeds at $0.000001-2.
- `story_judge._meter` meters both judge calls.
- **fal Whisper is priced per audio minute at an UNVERIFIED rate.** fal bills
  it by GPU compute time and its own model page states no usable rate (it
  renders "$0 per compute second"; the pricing page lists no speech-to-text
  model). `cut/index.WHISPER_USD_PER_MIN = 0.000544` is a third-party reading
  (costbench.com, ~$0.00544 per 10-minute clip); `FAL_WHISPER_USD_PER_MIN`
  overrides it. Check it against fal's invoice before trusting it.
- Serper: `imagesearch.serper_usd`, $0.001 a credit (the smallest pack, the
  dearest per query), 2 credits when more than 10 results are asked for;
  `SERPER_USD_PER_CREDIT` overrides. A failed search is not metered.
- Nano calls `charge.submitted()` as the last line before the image call.
- `scout.scout(account_id=)`: the Studio's `/scout/run` and the MCP `research`
  tool pass the runner's account into refgen; the CLI passes none (the unowned
  pool, never charged).
- `/costs`' notes say what changed.

### 1a -- the gates

Thirteen routes in `app/api.py` and three in `app/cut_routes.py` ask the gate
(`_create_gate`; the cut router has a twin because it does not import
`app.api`). Three were NOT in the plan's table and were found by sweeping every
route that takes the Gemini key: `/concepts/{id}/approve` (write an idea's
scene), `/evals/run` (the golden set, many embeddings) and
`/workflows/exec/ground` (an embedding). Also gated: Run all
(`/workflows/{id}/run`). Not gated, on purpose: the cut's `cleanup` and
`captions` (no model call), and every MCP tool the listed server publishes
(none calls a model; `research` and `generate` already asked the gate).

An element save (`/assets/{kind}`) is refused whole -- photos are not written --
for an unfunded account, as the plan says; the alternative (save the photos,
skip the describe) was not taken.

The 402 reaches the composer and the pill as a toast with the server's message
("Create is included with a plan -- subscribe or top up credits to continue"),
and the composer marks the bubble failed and hands the words back. The second
402 wording the plan wanted was only for 1b.

### Part 2 -- credits

- `_render_state` carries `credits` (`pricing.credits_for(usd_micros(...))`).
- `render-choice.ts`: `Plan` has no dollar field; `planFor` with no quote is
  "pricing…" (the `undefined` → rate-card-dollars path is gone -- nothing in the
  app used it, the Queue fetches a quote for every card); `priceText` never
  formats USD. `estimate()` stays: `firstUsable` sorts by it, nothing shows it.
- Queue page: toast, tally and status line read credits only.
- Director: the Generate node footer, the inspector's spend line and the Run
  confirm read `rw.credits` (from `generate.credits`, else the renderer state).
- **The legacy `/ui` Queue was PORTED, not stripped.** The plan recommended
  deleting its approve price and linking to the studio; porting was smaller and
  keeps a working door: `plan()` reads the server's quote for every scene (it
  already fetched one for timed scenes), and the button says "N cr".
- Balance freshness: `studio-api.announceBalanceWhenDone(jobId)`; the Director
  announces when a still/clip node's job ends and when Run all ends however it
  ended; `AddElement` announces when its sheet job ends (it is opened from
  Elements, Assets and the composer, and only Elements watched the job); the
  Elements page announces when a sheet draw ends. Draw keyframes already did.
- Elements' Draw / Redraw sheet title says its price in credits ("a few cents"
  before).
- The pill: none of its proposals spends credits (`add_spark`, `reference`,
  `keep_references`, the project tools; a make runs through the composer), so
  its credit card stays on the Queue. Nothing to change.
- Guard: `tests/test_studio_shows_credits.py` scans every studio page and
  component, the Director, `render-choice.ts` and the legacy Queue for a dollar
  figure being built. A Python test so CI runs it (CI runs no web tests).

### Tests

`tests/test_spend_holes.py` (1c/1d), `tests/test_spend_gates.py` (1a: every
door refused with no job for an unfunded account, and the same door with
credit starting its job), `tests/test_studio_shows_credits.py`, one test in
`tests/test_scout.py`, `web/tests/render-choice.test.mjs` updated. Four Guide
test files hold the gate open in their fixtures (made-up account ids with no
balance).

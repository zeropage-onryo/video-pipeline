# Task — make cost efficiency visible (the `/costs` tracker)

**Status: SHIPPED 2026-09-04** (`claude/cost-tracker` -> `main`). Steps 1-4
built as written: `src/spend.py` (the meter: `llm_calls`, owned; prices read
off the pricing page that day; the meter never raises), `src/costs.py` (the
four numbers), `/costs` on the dev router + `GET /api/costs`, the stage label
on all 23 `generate_with_retry` callers plus the five raw sites and the
research agent. Step 5 had already landed on 2026-09-02 (`VEO_SPEND_OK`, the
caps in `.env.example`); the code defaults stay one-account-sized on purpose
-- see BACKLOG #2 for the one real night that was measured. Written
2026-09-01. This is BACKLOG #2, which had sat unbuilt since it was written,
scoped into one block against what the code looked like that day:

> "Build a tracker to make cost efficiency issues visible."

It is also the missing input to the two numbers BACKLOG #10 could not pick —
the global ceilings and the BYOK split are both bets on a spend profile nobody
has measured. This task measures it.

---

## 1. What is true today (verified 2026-09-01 against `main` @ `a7c97a3`)

### The render half is two thirds built and surfaced nowhere

`generations.cost_usd` has existed since the table was written
(`src/generative.py:64`), and every billed renderer already fills it at estimate
time: `runway.py:300,459,535`, `higgsfield.py:655,741,799,845`, `veo.py:196`,
`midjourney.py:203`.

Two aggregators already sit on top of it, both account-scoped, both correct:

- `generative.tool_scoreboard` (`src/generative.py:342`) — per tool: attempts,
  kept, hit rate, spend, **cost per keeper**.
- `generative.attempts_to_keeper` (`src/generative.py:309`) — per shot: which
  tool won, in how many attempts, and the total cost of every attempt on that
  shot including the losers.

**Nothing calls either one outside `tests/test_generative.py`.** The headline
efficiency number of the whole repo — dollars per *usable* clip — is computed
and then discarded. Surfacing those two functions is the cheapest hour in this
task and should be done first, before any new instrumentation, because it also
proves the page's plumbing against numbers that are already right.

Two honesty constraints already encoded in the code, to preserve:

- `ops/render_queue.py:135` leaves `cost_usd` NULL **on purpose** — that clip
  was paid for out of a subscription, not per call, and "nothing downstream sums
  `cost_usd` into money owed." A free render must show as free with a label, not
  as a backfilled price and not as a silent zero mixed in with metered spend.
- `cost_usd` is an *estimate written at call time*, not an invoice. Every number
  this page shows is an estimate; say so on the page.

**The live database has 20 generations, all `nano`, all with `cost_usd` NULL.**
So the board renders empty until a paid render happens. Build and test against
seeded rows; do not tune the page against his current data and conclude it works.

### The LLM half does not exist at all

`usage_metadata` appears **zero times** in `src/`, `app/` and `ops/`. Not one
Gemini call reads how many tokens it spent. Concepts, `taste_judge`,
`uncanny_judge`, `scout`, CRAG, loglines, captions, the prompt gate — all free,
as far as the system knows.

The shape of the fix is unusually good, and it is why this task is 4–5 hours and
not fifteen. There are 46 Gemini generation call sites and **42 of them go through one
function**: `gemini_utils.generate_with_retry` (`src/gemini_utils.py:67`), which
takes the response, returns `.text` as a `str`, and drops everything else.

| module | calls | | module | calls |
|---|---|---|---|---|
| `src/shootgen.py` | 8 | | `src/rework.py` | 2 |
| `src/orchestrator.py` | 4 | | `src/scheduling.py` | 2 |
| `src/imagery.py` | 3 | | `src/taste_judge.py` | 2 |
| `src/locations.py` | 3 | | `src/uncanny_judge.py` | 2 |
| `src/promptgen.py` | 3 | | `app/main.py` | 2 |
| `app/api.py` | 3 | | `src/nano_banana.py` | 1 |
| `src/crag.py` | 2 | | `app/workflow_runner.py` | 1 |
| `src/director.py` | 2 | | | |
| `src/grounded_answer.py` | 2 | | | |

Four sites bypass it and need their own meter call:

```
src/nano_banana.py:150   _generate_content()  -- the images path; its two callers
                         are nano_banana.py:267 (config=) and :271
src/scout.py:293         research
src/scout.py:697         the second scout call
src/orchestrator.py:183  _client().models.generate_content(GEMINI_MODEL)
```

**One reason the meter must live inside `generate_with_retry` rather than at its
callers:** that function falls through `FALLBACK_MODELS`
(`src/gemini_utils.py:51`) when a model stays unavailable, so *the model that
answered is not always the model that was asked for*. A caller pricing its own
call would price `gemini-3-flash-preview` for an answer that came from
`gemini-pro-latest`. Only that function knows which model actually replied.

Models in play: `gemini-3-flash-preview` (most text — shootgen, promptgen,
quality, rework, scheduling, locations, grounded_answer, director, both judges),
`gemini-3.1-flash-lite` and `gemini-pro-latest` (the fallback chain),
`gemini-2.5-flash-image` / `gemini-3-pro-image-preview` (nano banana),
`gemini-embedding-001` (rag).

### One more path, in flight

`src/research_agent.py` (new and uncommitted as of 2026-09-02, from a parallel
session) reaches Gemini through **`langchain_google_genai.ChatGoogleGenerativeAI`**
and a bare `genai.Client`, not through `generate_with_retry`. It is outside the
42 and outside the four. Whatever lands there needs its own meter call, and it is
the reason step 2 puts the pricing and the write in `src/spend.py` rather than
inside `gemini_utils` — a second SDK wrapper should be able to report a call
without importing the retry helper.

### Two bugs living in the same files

Both were named in BACKLOG #10 as bugs regardless of the BYOK decision, and both
are ten-line fixes that only became *decidable* once there is spend data:

- **Every global ceiling defaults to one account's allowance.**
  `higgsfield.py:91`, `midjourney.py:61`, `nano_banana.py:39`, `runway.py:60`,
  `veo.py:57` are all `int(os.environ.get("<X>_GLOBAL_DAILY_CAP", str(DAILY_CAP)))`.
  `generative.cap_error` implements both walls correctly (`src/generative.py:152`) —
  the defaults are what's wrong, and the first person to render each morning
  exhausts the installation for everyone including Mike.
- **Veo has no `SPEND_OK` gate.** `runway.py:62`, `higgsfield.py:85` and
  `midjourney.py:62` each define `SPEND_ENV`; `src/veo.py` defines none. The most
  expensive tool in the repo at $3.20/clip is the only one that needs nothing but
  to be under a cap.

---

## 2. The build

### Step 1 — surface what already exists (~45 min)

`/costs` page + `GET /api/costs`, rendering `tool_scoreboard` and
`attempts_to_keeper` for the current account. No new tables, no new
instrumentation. This is the skeleton, and it is shippable on its own.

### Step 2 — the meter (~1.5 h)

A new `src/spend.py` with one entry point, plus an `llm_calls` table:

```sql
CREATE TABLE IF NOT EXISTS llm_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    account_id    INTEGER REFERENCES accounts(id),
    run_id        TEXT,              -- the orchestrator's uuid; NULL for request-path calls
    stage         TEXT    NOT NULL,  -- see step 3
    model_asked   TEXT    NOT NULL,
    model_used    TEXT    NOT NULL,  -- differs when the fallback chain fired
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    cached_tokens INTEGER,
    thought_tokens INTEGER,
    cost_usd      REAL,
    ok            INTEGER NOT NULL DEFAULT 1,
    ms            INTEGER
);
```

Called from `generate_with_retry` after a successful response, and from the five
raw sites. Prices live in **one dict keyed by model**, read from env with a
literal default, in `src/spend.py` — never inline at a call site, because they
change and because the fallback models must be priced too.

Non-negotiable: **the meter never raises.** Wrap the whole thing so a metering
bug cannot fail a generation. `usage_metadata` is absent on some responses and
some fields are `None`; a `TypeError` in the accounting must not cost a render.

### Step 3 — the stage label (~1 h)

Cost without attribution answers nothing. `generate_with_retry` grows a
keyword-only `stage=` (defaulting to `"unknown"`, so all 42 callers keep working
on the first commit), and then the callers are labelled in one pass:

`concepts` · `logline` · `shot_prompt` · `prompt_gate` · `taste_judge` ·
`uncanny_judge` · `crag` · `scout` · `caption` · `director` · `enhance` ·
`location` · `schedule` · `rework` · `nano_image`

Define the list in one place and validate against it, the way `generative.LOG_TOOLS`
already constrains `record_generation` (`src/generative.py:218`). A free-text stage string turns into
fifteen spellings of "judge" within a month.

### Step 4 — the questions the page answers (~1 h)

Not a chart wall. Four numbers, each of which can change a decision:

1. **Cost per kept clip, per tool.** Already computed by `tool_scoreboard`. The
   real efficiency number: a prompt that lands in 2 tries beats one that lands in 6.
2. **Cost per stage, per night.** Which stage is the token hog. This is the one
   that has never been visible.
3. **Wasted spend.** Two sources, both already tracked:
   `autonomy.prompt_gate_agreement` (`src/autonomy.py:291`) already breaks out
   passed-but-rejected — credits burned on a clip that was never going to be
   used — from held-but-would-have-posted, which only cost a manual approval.
   Plus generated-and-never-posted from `hold_queue`.
4. **Today against the caps.** Spend so far today, per account and installation-
   wide, against the ceilings from step 5. This is what makes the caps a budget
   rather than a number in `.env`.

### Step 5 — the two bugs (~45 min)

Fix the five `GLOBAL_DAILY_CAP` defaults with numbers chosen from what steps 1–4
now show, and give veo a `SPEND_ENV` matching the other three renderers. Update
the table in `docs/PILOT.md §1`, which currently documents the broken defaults as
though they were a decision.

---

## 3. Traps, all of them verified

- **There are two different `run_id` namespaces in this repo.** `pitch_runs.id`
  is an `INTEGER` (`src/db.py:55`), joined as `ideas.run_id`. The orchestrator's
  `run_id` is a `uuid4().hex` **string** (`src/orchestrator.py:314`), and it is
  what `prompt_scores.run_id`, `corrections.run_id` and `scout_findings.run_id`
  carry. Per-night cost keys on the uuid. Typing the column `INTEGER` and joining
  the wrong one will look like it works and quietly aggregate nothing.
- **`llm_calls` must be added to `db.OWNED_TABLES`** (`src/db.py:162`), and then
  every query against it must carry an owner predicate — `tests/test_tenancy.py`
  parses every SQL literal in `src/`, `app/` and `ops/` and fails the build
  otherwise. Write it owner-scoped from the first line rather than retrofitting.
- **Never iterate on schema code inside the mounted folder.** The dev server
  watches the source tree and runs the app lifespan against `data/pipeline.db` the
  moment a file is saved — a half-finished migration has already run on live data.
  Prove it in a scratch copy of the repo against a *copy* of the database, then
  copy the finished file in.
- **Token counts are not a bill.** Cached and thinking tokens price differently
  from input tokens, and the image models are priced per image, not per token.
  Store the raw counts alongside the derived `cost_usd` so a wrong price table is
  a re-computation and not a lost measurement.
- **Do not meter the embedding path by accident.** `gemini-embedding-001` runs
  through `src/rag.py` on a different API surface; either meter it deliberately or
  leave it out and say so on the page.

---

## 4. How it gets verified

`pytest tests/` (not bare `pytest` — that collects `evals/`, which makes real
Gemini calls). New tests:

- a metered call writes exactly one `llm_calls` row with the model that *answered*,
  proven by forcing a fallback;
- a metering failure does not fail the generation;
- an account sees only its own spend (extends `tests/test_tenancy.py`);
- a free render (`cost_usd` NULL) is reported as free, not as $0.00 spend;
- the cost-per-keeper figure counts the rejected attempts on the same shot.

Then the honest check, which no test replaces: **run the nightly once, ask the
page what it cost, and compare against the Google Cloud console for the same
window.** If those two numbers disagree, the page is worse than nothing —
CLAUDE.md's standing rule is that every real bug this project has had passed
review and passed its own tests.

---

## 5. What this deliberately does not do

- **Not BYOK.** BACKLOG #10 stands: the demo in front of ten people beats BYOK,
  and BYOK gets built the week someone asks. But this task is its precondition —
  the recommended split there (Mike's keys pay for the cheap high-frequency
  steps, the user's key pays for renders) is an untested guess about the ratio
  until `llm_calls` exists. If the cheap path turns out not to be cheap, that
  recommendation changes.
- **Not a billing system.** No invoices, no per-user statements, no charging.
  Estimates, labelled as estimates, so waste is visible.
- **Not the UI readability pass** (BACKLOG #1), which is still parked. `/costs`
  matches the existing `.sk` skin; it does not introduce a second one.

# Runbook

Operational notes, newest first. Each section is dated and is about a
thing that has actually gone wrong.

## 2026-09-07 — the nightly walk (`src/nightly.py`)

Step 4 of `run_morning_prompts.sh` is `python3 -m src.nightly walk` now.
Steps 1–3 (metrics, the idea-agent bank, the research agent, the crawl)
are unchanged, as are the smoke flag, the `cd` guard and the root check.

**What it does that bash did not.** Four failures from one week of real
logs, each of which cost a whole night:

| symptom in the log | what it was | what happens now |
| --- | --- | --- |
| `trigger: run crashed: [Errno 8] nodename nor servname provided` | one DNS miss to the Supabase pooler | preflight catches it before run 1; if it appears mid-walk the breaker stops there |
| `429 RESOURCE_EXHAUSTED … prepayment credits are depleted` ×6 per call ×16 runs | an empty prepayment balance retried as if it were a rate limit | `gemini_utils.is_depleted` — no retries, no fallback models, and the breaker ends the walk |
| `held='no keyframe: daily ceiling: 20/20 …'` ×16 | the image cap was spent before the walk began | preflight sets `ZEROPAGE_KEYFRAME=0` once and says so; concepts still get written |
| LangSmith connection-error spam | tracing on with nowhere to send | the runner forces tracing off unless `NIGHTLY_TRACING=1` |

**Systemic vs content** is `nightly.classify_error(e)`, shared with
`src/trigger.py` so a hold row and the breaker cannot disagree. Systemic
(stop the walk): DNS/connection failure, a depleted-billing 429, an auth
refusal, a `psycopg.OperationalError`. Content (next spark): a Postgres
deadlock, a judge parse error, anything unrecognised — erring that way
costs one run, erring the other way costs the night.

**Budget**: `NIGHTLY_BUDGET_USD`, default $5.00, checked before each run
against `costs.spent_since(<the walk's own start>)` — LLM calls plus
renders. A timestamp, not "today", because a 22:00 walk and a 03:30 walk
are not the same calendar day.

### Morning check

```bash
python3 -m src.nightly status          # the last 7 nights' receipts
python3 -m src.nightly preflight       # the three checks, nothing spent
```

`nightly_runs` is the receipt table (`src/db.py`). Read it:

- **no row for last night** → the schedule never fired. That is launchd or
  Fly, not the code. On the Mac this is usually TCC refusing a
  LaunchAgent access to `~/Documents` (`EPERM`, not `ENOENT`, in
  `data/morning_prompts.err`) — see CLAUDE.md's launchd section; the
  durable fix is moving the project out of a protected folder.
- **`finished_at` NULL** → the walk started and died mid-flight. The row
  is written *before* the first run for exactly this.
- **`stopped_reason` set** → the breaker or the budget. There is one
  `hold_queue` row saying the same thing, on `/holds` with the night's
  other outcomes.
- **`attempted` 16, `failed` 0** → a healthy night, whatever the holds say.
  Holding is what shadow mode does.

### Running it on Fly

`ops/fly/nightly.md` + `ops/fly/run-nightly.sh`. Recipe only — not
deployed. It also lists what cannot run in that image (the frame bank,
local photo roots) and says to unload the launchd plists once Fly owns
the schedule, so the walk does not run twice against one set of caps.

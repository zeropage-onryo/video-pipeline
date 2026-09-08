# Runbook

Operational notes, newest first. Each section is dated and is about a
thing that has actually gone wrong.

## 2026-09-08 — the manual render lanes (`ops/render_queue.py`)

Two lanes spend a subscription instead of API credits, and neither can
run unattended — an MCP server and a browser both need a session, so
**this is deliberately not on the 03:30 walk and cannot be.**

```bash
python3 ops/render_queue.py --account zeropage list    # higgsfield (MCP)
python3 ops/render_queue.py --provider runway --account zeropage list
python3 ops/render_queue.py --provider runway --account zeropage import \
    --concept 131 --shot 1 --file ~/Downloads/clip.mp4 \
    --model gen4_turbo --duration 10 --anchored
```

`list` prints the prompt, the keyframe URL to drag into the start-image
slot, and the duration/ratio to set. `import` copies the mp4 into
`data/renders/runway/` (where `src/runway.py` already writes, so
`/renders` serves it unchanged) and writes the `generations` row with
`cost_usd` NULL — FREE with a count on `/costs`, never `$0`, never
backfilled — and `params.source = "manual-unlimited"`, which is what
makes `ledger.is_billable` refuse to take a hold.

**Both lanes are operator-only, and that is a security property.** Each
spends one of Mike's personal consumer plans; rendering a paying tenant's
shot on either is reselling a consumer subscription, and the penalty is
the account, which is every tenant's renders at once. `src/manual_lane.py`
holds the allowlist, checked server-side against the account id at every
surface (the CLI, `GET /api/queue/manual`). It **fails closed**: unset
means nobody, including the bootstrap account and including the unowned
pool a fresh database hands a CLI.

**The gate is a column on `accounts`, not an environment variable
(changed 2026-09-08).** `accounts.manual_lane_operator`, moved with an
idempotent `ALTER TABLE` in `src/db.py` and **no backfill** — every
account, including the bootstrap one, comes out of the migration OFF.
`ZEROPAGE_OPERATOR_ACCOUNTS` / `_EMAILS` are **removed, not deprecated**:
anything that can set an env var on the process could name itself
operator, and a gate with two doors is one door.

**RUN THIS ONCE, or both lanes — including the Higgsfield one you use
now — refuse everything:**

```bash
venv/bin/python -m src.accounts operator zeropage --on
```

It prints what changed (`OFF -> ON`, or `already ON`) and lists any other
account that is on. `--off` revokes. Do it for `antihero` too if you
render from that brand's account. The refusal names the command, so if
`list` starts refusing this is what it is telling you to run.

**The Higgsfield lane needs this too, and that is a deliberate break.**
It used to run with no configuration at all. It is the same exposure — a
consumer app subscription spent on any account's shot — and gating one
lane while leaving the other open is worse than gating neither, because
it reads as though the question had been asked and answered.

The **API-billed adapters are untouched** by any of this: `src/runway.py`,
`src/higgsfield.py`, `src/veo.py` and `src/fal.py` spend a credential a
tenant can own, metered per call, under their own `*_SPEND_OK` gates and
daily caps. This allowlist is about the subscription lanes only.

**Provenance is visible on the board.** A subscription clip and an
API-billed clip are the same mp4 in the same folder with the same URL
shape, so the scene board's status now reads `RENDERED · SUBSCRIPTION`
when the row carries a lane marker (`generative.subscription_rendered`,
derived from `params_json` — so rows imported before the field existed
are covered with no backfill). It matters when a clip is about to be used
somewhere a consumer plan's terms bite.

### Driving the Runway app (measured 2026-09-06)

Four things cost real time or a wasted round that day:

- **Two generations in flight, and extra clicks are dropped silently.**
  Unlimited queues 2 at a time; a third Generate does nothing but raise a
  "wait or switch to Credits Mode" toast. Queue two, then wait.
- **Duration resets to 5s on every page reload.** Set it and *zoom in to
  read the chip* before every Generate — one whole round went out at 5s
  because the control looked set and was not. This is why `list` prints
  the target duration on every row.
- **The gallery is stale until reload, and slow to fill.** Give it ~15s,
  reload, then "View latest". A clip that is not there yet looks exactly
  like a failed generation.
- **Uploading a 9:16 image flips the ratio chip.** Check it after the
  upload, not before.

### The four shared-box problems, and what was done about them

All four were recorded here as known-and-unfixed on 2026-09-08 and fixed
the same day. Kept as a record of what the failure actually was:

- **The environment was the whole gate.** Anyone who could set env vars
  on the process — a deploy config, a `.env` on a shared box, a wrapper
  script — could name themselves operator, with no record of who was on
  the list when a clip was rendered. Now a column, above, and the env
  vars are gone rather than left as a fallback.
- **Membership was transitive.** An operator EMAIL resolved to every
  account that person was a member of, so adding Mike to a pilot user's
  account to debug something silently gave that account the lane. Gone by
  construction: the flag is on the account row, so membership no longer
  says anything about it. A test acts as an operator who is *also* a
  member of a second, non-operator account and expects the refusal.
- **`import` believed what it was told.** `--model`, `--ratio` and
  `--duration` were unverified strings landing in a `generations` row the
  tool scoreboard reads, so a 1am typo became a measurement of a model
  that never ran. The runway lane's claims are now checked against
  `src/render_specs.py`'s per-model legal values and **refused, not
  clamped** — a value outside the set means the row and the clip have
  come apart, and rounding hides exactly that. `import` also asks
  **ffprobe** how long the file really is and writes
  `duration_measured_s` beside the claimed `duration`; with no ffprobe on
  PATH the row says so in `duration_source` rather than implying a
  measurement nobody took. The Higgsfield lane's model names are the
  MCP's own and published nowhere this repo can read, so they are
  recorded with `model_verified: false` instead of being checked against
  a list this repo invented.
- **`manual_lane.LANE_RATIO` duplicated `runway.DEFAULT_RATIO`**, with a
  drift test standing in for a shared source. Both now read
  `src/render_specs.py` — a module that imports nothing at all, so the
  script that must run under a bare `python3` can have it too. The drift
  test is deleted: a shared constant cannot drift.

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

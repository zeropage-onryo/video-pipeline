# Running the nightly walk on Fly

**Recipe only. Nothing here has been deployed** (written 2026-09-07). It
describes how to move the night off the Mac's launchd and onto the
existing `zeropage-studio` app, using the Dockerfile that already builds
this repo. Read it start to finish before running a command: the last
section is what *cannot* run there, and it is the reason this is a split
rather than a move.

The job itself is `python -m src.nightly walk` (see that module's
docstring for the breaker, the budget and the cap behaviour).
`ops/fly/run-nightly.sh` is the wrapper: it does steps 1–3 of
`run_morning_prompts.sh` (metrics, the research agent, the crawl — each
never-fatal) and then the walk, and exits non-zero when the walk stopped
early.

## Two ways to schedule it, and which to pick

### A. A scheduled Machine (preferred)

One Machine per night, booted for the job and destroyed after. Nothing
runs — and nothing bills — for the other twenty-three hours.

```bash
fly machine run . \
  --app zeropage-studio \
  --schedule daily \
  --region iad \
  --vm-memory 1024 \
  --entrypoint "" \
  /bin/bash /app/ops/fly/run-nightly.sh
```

Notes that matter:

- `--entrypoint ""` is required. The image's `CMD` is supervisord (the web
  process plus cron); a scheduled Machine that runs it would start a
  second web server and a second cron every night.
- `--schedule daily` is Fly's own scheduler and it fires on **its** clock,
  not on `TZ`. It is "once a day", not "at 03:30 America/New_York". If the
  hour matters (it does not much — the point is that it happens), use
  option B, whose cron line carries the timezone the image already sets.
- A scheduled Machine gets the app's secrets, so `ops/fly/preflight.sh`'s
  requirements apply to it exactly as to the web machine.
- `--vm-memory 1024`: the walk imports the whole generation stack. The
  web machine's 512MB in `fly.toml` is enough to serve, and thin here.

### B. The cron already in the image

`Dockerfile` writes `/etc/cron.d/zeropage` with `TZ=America/New_York`
baked in, and `ops/fly/entrypoint.sh` dumps the real environment to
`/app/.env.runtime` because cron gets a bare one. Change the morning line
to call the wrapper instead of the bash script:

```
0 22 * * *  root  cd /app && . /app/.env.runtime && /bin/bash /app/ops/fly/run-nightly.sh >> /var/log/zeropage/morning_prompts.log 2>&1
```

This keeps wall-clock scheduling and DST handling identical to launchd's,
at the cost of a machine that is always on — which `fly.toml` already
requires (`auto_stop_machines = 'off'`, `min_machines_running = 1`).

## Secrets, by name

Set with `fly secrets set NAME=...` — **names only below; read
`.env.example` for what each one is and never paste a value into a doc,
a commit, or a log line.**

Required (`ops/fly/preflight.sh` refuses to boot without them):
`DATABASE_URL`, `RAG_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SESSION_SECRET`, `ACCOUNT_KEYS_SECRET`, `SITE_URL`.

Required for the walk to generate anything: `GEMINI_API_KEY` (or
`GOOGLE_API_KEY`).

Optional, each enabling one lane and each degrading with a logged note
when absent: `ANTHROPIC_API_KEY`, `YOUTUBE_API_KEY`, `IG_GRAPH_TOKEN`,
`IG_BUSINESS_ID`, `IG_USER_ID`, `IG_ACCESS_TOKEN`, `GOOGLE_CSE_ID`,
`GOOGLE_CSE_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`,
`PINTEREST_ACCESS_TOKEN`, `ACEDATA_API_KEY`, `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`,
`R2_PUBLIC_BASE_URL`.

Knobs, not secrets, but set them here too:
`NIGHTLY_BUDGET_USD` (default 5.00), `SCOUT_PER_BRAND`,
`SCOUT_BANK_PER_BRAND`, `NANO_DAILY_CAP`, `NANO_GLOBAL_DAILY_CAP`,
`ZEROPAGE_GATES`.

**Deliberately NOT set**: every per-run spend approval —
`RUNWAY_SPEND_OK`, `VEO_SPEND_OK`, `HIGGSFIELD_SPEND_OK`,
`MIDJOURNEY_SPEND_OK`, `ZEROPAGE_POST_OK`, `ZEROPAGE_RENDER`. Those are
per-run approvals typed on a command by a person; a Fly secret is a
standing one, and a standing render approval on an unattended nightly is
how a night bills dollars nobody approved. Also not set: `DEV_TOOLS`
(preflight refuses `1` on the public deploy).

Tracing: leave `LANGSMITH_TRACING` unset. The runner forces it off for
the walk anyway (`nightly.quiet_langsmith`) unless `NIGHTLY_TRACING=1`,
because an unreachable tracer printed more lines into the owner's logs
than the runs did.

## What cannot run there

This is the "split, not a move" the Dockerfile header already names, and
the walk does not fail over it — those lanes report themselves absent and
the night carries on:

- **The frame bank / footage cutting** (`src/framebank.py`,
  `ops/build-frame-bank.py`). 149GB of ProRes is on the Mac and is
  excluded by `.dockerignore`. `FRAMES_LANE=0` is already the default in
  `.env.example`; leave it there. The lane needs ffmpeg *and* the media.
- **Local photo roots** — `characters/`, `props/`, `locations/`, the
  asset shelf, `data/refs/`. Grounding, likeness photos and any reference
  read off disk are unavailable in the image. Pre-ingest anything the
  night needs to R2 (`src/storage.py`, `ops/ingest-saved-images.py`) so a
  reference is an `https://` URL the container can actually fetch; a
  local path there is silently no reference at all.
- **Anything expecting `data/pipeline.db`**. The spine is Postgres;
  `DATABASE_URL` must be the Supabase **session pooler** string. The
  transaction pooler does not support what psycopg does here.
- **The Director canvas's renders** and every paid render tool — see the
  approvals above. The night on Fly produces concepts and (within
  `NANO_*_DAILY_CAP`) keyframes. Nothing else.

## How you know it ran

Not from the logs. A scheduled Machine is destroyed after the job and
takes its stdout with it, which is the same blindness that hid eleven
launchd nights.

The proof is a row:

```sql
SELECT started_at, finished_at, attempted, succeeded, failed,
       spent_usd, stopped_reason
FROM nightly_runs ORDER BY id DESC LIMIT 7;
```

or `python -m src.nightly status`. Read it like this:

- **no row for last night** → the schedule never fired. Fly's scheduler,
  or the plist, not the code.
- **a row with `finished_at` NULL** → the walk started and died mid-flight
  (OOM, machine killed). The row is written before the first run for
  exactly this.
- **`stopped_reason` set** → the breaker or the budget stopped it, and the
  reason says which. There is also one `hold_queue` row saying the same
  thing, so the morning review finds it where every other outcome is.
- **`attempted` 16, `failed` 0** → a healthy night.

## When Fly owns the schedule

Disable the Mac's copy, or both fire and the walk runs twice against one
database and one set of caps:

```bash
launchctl unload ~/Library/LaunchAgents/com.zeropage.morningprompts.plist
launchctl unload ~/Library/LaunchAgents/com.zeropage.shadowrun.plist
```

Remember `~/Library/LaunchAgents` holds a **copy** — editing the repo's
plist changes nothing (`ops/install-launchagents.sh --check` reports
drift). Unloading the installed copy is what actually stops it. Do this
only once a `nightly_runs` row has appeared from Fly on a night you
watched; until then, running both is a duplicate, and running neither is
the failure this whole file exists to end.

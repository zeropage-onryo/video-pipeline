# Deploying to Fly.io — backlog #14 phase 5

Written 2026-09-03 alongside the Dockerfile / fly.toml / ops/fly/*. Nothing
here has been run — no Fly account was created, no image was built, no
machine exists yet. This is the guide for when phase 4 (Postgres + RLS) is
done and it's time to leave the Mac.

## Before this phase, not during it

Do not launch this while `data/pipeline.db` is still SQLite. The Dockerfile
copies the app, not the database, and a box pointed at a file that only
exists on the Mac is "the worst of both" (backlog #14's own words). Phase 4
first.

## What's already written

- `Dockerfile` — python:3.11-slim, installs `requirements.txt`, runs
  `uvicorn app.main:app` and `cron` under supervisord. `footage/` and the
  local asset roots are excluded by `.dockerignore` (phase 5 is explicitly
  "a split, not a move" for those).
- `ops/fly/supervisord.conf` — the two processes (web, cron).
- `ops/fly/entrypoint.sh` — dumps the container's real environment (Fly
  secrets included) to a file the cron jobs source, because cron does not
  inherit environment variables the way a shell does.
- `fly.toml` — one shared-cpu-1x machine, `iad` (Virginia, same region as
  the Supabase project), `auto_stop_machines = false` because this machine
  also runs the 22:00 / 03:30 nightly jobs — letting Fly sleep it would
  silently skip them, the exact class of bug launchd_tcc.md already cost a
  night on, just moved to a new platform.

## Launch steps (when you're ready)

1. `curl -L https://fly.io/install.sh | sh`, `fly auth login`
2. From the repo root: `fly launch --copy-config --no-deploy` — it reads
   `fly.toml`, asks to confirm the app name (must be globally unique;
   `zeropage-studio` may be taken) and region. Say no to a Postgres
   database — you already have one, on Supabase.
3. `fly volumes create zeropage_data --region iad --size 3` — the mount
   `fly.toml` expects, for `data/renders` / `data/refs` / `data/thumbs`.
   Not the footage bank; size to what those three actually hold.
4. Secrets, one call per name (values from your current `.env`):
   ```
   fly secrets set \
     DATABASE_URL="postgresql://...supabase..." \
     RAG_DATABASE_URL="postgresql://...supabase..." \
     SESSION_SECRET="..." \
     ACCOUNT_KEYS_SECRET="..." \
     GEMINI_API_KEY="..." \
     RUNWAYML_API_SECRET="..." \
     HIGGSFIELD_API_KEY_ID="..." HIGGSFIELD_API_KEY_SECRET="..." \
     GOOGLE_CLIENT_ID="..." GOOGLE_CLIENT_SECRET="..." \
     SITE_URL="https://zeropage-studio.fly.dev"
   ```
   (full list: everything currently in `.env` that isn't a comment or blank)
5. `fly deploy`
6. Register `https://<app>.fly.dev/auth/google/callback` (and Discord's
   equivalent) in their consoles — this is the same step phase 2's tunnel
   needed, just against the Fly hostname instead of the tunnel's.
7. Watch the first two scheduled runs: `fly logs`, or
   `fly ssh console -C "cat /var/log/zeropage/morning_prompts.log"`

## What does NOT change

`app/main.py`, `ops/serve.sh`'s BASE/PROBE reasoning, the OAuth redirect
logic — all of it already works behind a proxy (`request.url_for` +
uvicorn's `--proxy-headers`, which `supervisord.conf` passes). Nothing in
the application code needs to know it's running on Fly instead of a Mac.

## Cost

Free tier for CPU/RAM at this size (`shared-cpu-1x`, 512MB) plus roughly
$0.15/GB-month for the volume. The real number: none of this bills anything
until step 2. Writing these files did not create an account or spend money.

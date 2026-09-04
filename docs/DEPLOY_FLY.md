# Deploying to Fly.io — backlog #14 phase 5

Written 2026-09-03 alongside the Dockerfile / fly.toml / ops/fly/* and
updated after the Supabase Postgres/Auth cutover. No Fly machine has been
launched from this repository yet.

## Before this phase, not during it

The application schema and live data are now in Supabase. The final copy
matched all 32 pipeline tables, including 17 `llm_calls` rows, and left the
353-row `rag_documents` library alone. Do not point a Fly deployment back at
the old SQLite file.

## What's already written

- `Dockerfile` — python:3.11-slim, installs `requirements.txt`, runs
  `uvicorn app.main:app` and `cron` under supervisord. `footage/` and the
  local asset roots are excluded by `.dockerignore` (phase 5 is explicitly
  "a split, not a move" for those).
- `ops/fly/supervisord.conf` — the two processes (web, cron).
- `ops/fly/entrypoint.sh` — dumps the container's real environment (Fly
  secrets included) to a file the cron jobs source, because cron does not
  inherit environment variables the way a shell does. It runs
  `ops/fly/preflight.sh` first and refuses a partial production config.
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
4. Set the required production secrets (values from the current `.env` and
   Supabase dashboard). `DATABASE_URL` and `RAG_DATABASE_URL` can use the
   same Supabase session-pooler URL. Keep the existing
   `ACCOUNT_KEYS_SECRET`; replacing it makes migrated encrypted provider
   keys unreadable.
   ```
   fly secrets set \
     DATABASE_URL="postgresql://...supabase..." \
     RAG_DATABASE_URL="postgresql://...supabase..." \
     SUPABASE_URL="https://<project-ref>.supabase.co" \
     SUPABASE_ANON_KEY="..." \
     SESSION_SECRET="..." \
     ACCOUNT_KEYS_SECRET="..." \
     SUPABASE_PROVIDERS="google,discord" \
     GEMINI_API_KEY="..." \
     RUNWAYML_API_SECRET="..." \
     HIGGSFIELD_API_KEY_ID="..." HIGGSFIELD_API_KEY_SECRET="..." \
     SITE_URL="https://zeropage-studio.fly.dev"
   ```
   `SUPABASE_JWT_SECRET` is optional on projects using asymmetric signing;
   without it the app verifies tokens against Supabase's JWKS endpoint.
   Add the active providers' keys and the global daily caps from `.env`, but
   do **not** copy `DEV_TOOLS=1`, per-run spend approvals, or local-only MCP
   settings into the public deployment.
5. `fly deploy`
6. In Supabase Authentication -> URL Configuration, set the Site URL to the
   Fly origin and allow `https://<app>.fly.dev/auth/callback`. Google and
   Discord client credentials live under Supabase Authentication ->
   Providers; each provider console uses Supabase's own callback,
   `https://<project-ref>.supabase.co/auth/v1/callback`.
7. Watch the first two scheduled runs: `fly logs`, or
   `fly ssh console -C "cat /var/log/zeropage/morning_prompts.log"`

After deploy, `fly checks list` should show the `/healthz` liveness probe
passing before traffic is considered healthy.

The first successful sign-in using the migrated email claims its placeholder
profile and preserves its existing account membership.

## What does NOT change

`app/main.py`, `ops/serve.sh`'s BASE/PROBE reasoning, the OAuth redirect
logic — all of it already works behind a proxy (`request.url_for` +
uvicorn's `--proxy-headers`, which `supervisord.conf` passes). Nothing in
the application code needs to know it's running on Fly instead of a Mac.

## Billing

The committed configuration requests one always-on shared CPU machine with
512 MB RAM and a persistent volume. Check Fly's current dashboard estimate
before launch; writing these files alone did not create infrastructure.

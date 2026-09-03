# Rollout — from one operator to other users

The ordered checklist, written 2026-09-03 the night the RAG store moved to
Supabase. Each phase is a gate on the next; nothing in a later phase is worth
starting before the earlier one is ticked. `docs/PILOT.md` has the detail
behind phases 1–3; `docs/BACKLOG.md` #10 / #14 hold the reasoning behind 4–5.

**Update, later the same night:** BYOK is off the pilot-critical path. Chasing
"how do we onboard people without five provider sign-ins" led to `src/accounts.py`'s
`invite()` (already built, already tested, commit `dfc3b4b`) — it gives each
pilot person their OWN account, so their DAILY_CAP is already personal, not
shared, and every render still uses Mike's own provider keys via the existing
env fallback. That's free credits, per person, capped, zero new sign-ins
beyond one Google/Discord click into the app itself. See Phase 3, rewritten
below. Phase 1's remaining BYOK work (4 providers + Settings page) is now
optional polish, not a pilot blocker — matches `docs/BACKLOG.md` #10's own
"BYOK gets built the week someone asks."

Tick a box with the commit or date that closed it.

## Phase 0 — done

- [x] Account tenancy on every owned table (`claude/account-tenancy`, 2026-08-31)
- [x] Dry-run leaks closed: hold_queue, workflows, job rail owned; Veo gated (`8121bee`, `e4bdbc0`)
- [x] Every `/api` route names its tenant; route-signature test guards it
- [x] RAG store on Supabase — 316 rows, session pooler, verified end to end (2026-09-03)

## Phase 1 — who pays  (Mike chose BYOK, 2026-09-03)

- [x] `src/account_keys.py` built and tested: encrypted per-account provider
      keys (Fernet, keyed by `ACCOUNT_KEYS_SECRET` in `.env`), falls back to
      the environment when an account has none — Mike's own rendering is
      unaffected. `venv/bin/python -m src.account_keys set|list|clear`.
- [x] `src/runway.py` wired as the reference pattern: `_make_client`,
      `generate_video`, `generate_candidates`, `has_key` all take/thread
      `account_id` through `account_keys.key_for()`. Verified with a scratch
      DB (10 assertions: env fallback, account override, per-account
      isolation, encryption-at-rest, wrong-key refusal, two-field providers).
- [ ] Repeat the same swap for `src/veo.py`, `src/higgsfield.py`,
      `src/midjourney.py`, `src/nano_banana.py` — same shape, each provider's
      `_make_client`/`_credentials`/`_request` takes `account_id`, resolves
      through `account_keys.key_for()` first. NOT done tonight — do one at a
      time, syntax-check, then a scratch-DB test per provider like runway's.
- [ ] A Settings page (`app/api.py` + a template) where a pilot user pastes
      their own keys — calls `account_keys.set_key`. Nothing built yet;
      `runway.has_key()` still defaults to env-only until a caller passes
      `account_id` through from the request.
- [ ] Global ceilings stay a safety net at today's per-account defaults —
      not raised, since BYOK means a pilot's spend isn't Mike's spend.
- [x] Gemini prepaid topped up 2026-09-03 — RAG query verified end to end.
- **Deprioritized 2026-09-03 (later):** the pilot does not need this. Every
      `invite()`d account already gets its own per-account DAILY_CAP against
      Mike's own keys (env fallback, no code change) — see Phase 3. Come back
      to the remaining 4 providers + Settings page only once someone actually
      asks to bill their own usage.

## Phase 2 — reachable  (a weekend; the Mac still hosts it)

- [ ] Cloudflare Tunnel (free) in front of `ops/serve.sh`; pick the hostname: ______
- [ ] `.env`: `SITE_URL=https://<host>`, `ZEROPAGE_MCP_HOSTS=<host>`; leave `ZEROPAGE_MCP` unset
- [ ] Register `https://<host>/auth/google/callback` and `/auth/discord/callback`
- [ ] Rotate the thirteen `.env` secrets (`SESSION_SECRET` first — it signs everyone out)
- [ ] Backup `data/pipeline.db` before the invite and nightly during the pilot
- [ ] `venv/bin/python -m pytest -q tests/test_tenancy.py tests/test_tenancy_routes.py` green
- [ ] Confirm the dev console (`DEV_TOOLS`) is NOT mounted on the public host

## Phase 3 — first users  (the part that actually matters; deferred, per Mike, until Phase 1/2/4/5 work lands — but this IS the answer to "onboarding without BYOK")

**This phase is the real free-credits mechanism**, already built and tested
tonight's earlier work didn't touch: `invite()` gives one person their own
isolated account (own board, own DAILY_CAP counter) with zero provider
sign-ups — every render still bills to Mike's own keys via the env fallback
that's existed all along. No Settings page, no BYOK, no per-user schema work
needed. The only real gap is Phase 2 (reachability) — an invited person still
needs a live URL and working OAuth callback to click through to.

- [ ] Name the first three people: ______ / ______ / ______
- [ ] Demo in front of them before inviting — distribution beats architecture (#10)
- [ ] Before inviting anyone, set `*_DAILY_CAP` (per person) and
      `*_GLOBAL_DAILY_CAP` (overall ceiling across everyone) in `.env` to
      pilot-safe numbers — this IS the "free credits, then capped" limit,
      already enforced on every provider call
- [ ] `venv/bin/python -m src.accounts invite <email> --brand <slug>` — their own account, never `--join-existing`
- [ ] `src.accounts members` shows them; first Google/Discord sign-in claims the row
- [ ] Watch the first week: `/api` 403s, daily-ceiling hits, what they pick vs pass
- [ ] Follow-ups that can wait for the first user: scope `corrections` (dry-run item 4),
      `active_brand` off memberships (item 5)

## Phase 4 — Supabase, the rest of it  (Postgres-only, Supabase Auth — decided 2026-09-03)

- [x] Full plan written: `docs/tasks/task-postgres-migration.md` — the verified
      dialect translation table (`?`→`%s`, `IS ?`→`IS NOT DISTINCT FROM`,
      `julianday()`→`extract(epoch from ...)`, `lastrowid`→`RETURNING id`,
      AUTOINCREMENT→IDENTITY), the module order (db.py first, auth last), and
      a worked RLS policy on the one schema fully verified tonight (`videos`).
- [ ] Execute the plan, one module at a time, tests green after each —
      NOT done tonight. This is genuinely multi-day; 15 modules, ~300
      sqlite3 call sites. See the task doc for the ordered list.
- [ ] `accounts` / `account_members` / `auth_identities` → Supabase Auth
      (decided over "keep app/auth.py" — bigger rewrite, chosen for
      `auth.uid()` inside RLS policies)
- [ ] RLS policies on every owned table using the worked `videos` pattern;
      **set the tenant claim per request** — a service-role connection
      bypasses RLS and re-creates the exact leak tenancy fixed
- [ ] Service-key paths (the nightly orchestrator, ops/) become a small, listed, audited set
- [ ] `winning_prompts` gets `account_id`; RAG domains get a per-account suffix
      (account_scoping §4 — the shelves are the one thing that does not survive a second user)
- [ ] `account_keys` (built tonight, still SQLite) gets the same RLS treatment when it moves
- [ ] `tests/test_tenancy.py` stays green as the second line, RLS is the first

## Phase 5 — off the laptop  (after phase 4; a box pointed at a laptop SQLite file is the worst of both)

- [x] Deploy files written 2026-09-03, NOT launched: `Dockerfile`, `fly.toml`,
      `ops/fly/supervisord.conf`, `ops/fly/entrypoint.sh`, `docs/DEPLOY_FLY.md`.
      Runs `uvicorn app.main:app` + cron (replacing both launchd plists,
      same commands, same 22:00/03:30 ET schedule via `TZ=America/New_York`
      so DST is handled the same way the Mac handles it).
      `.dockerignore` excludes `footage/` and the local asset roots.
- [ ] Launch: `fly launch`, `fly volumes create`, `fly secrets set ...`,
      `fly deploy` — see docs/DEPLOY_FLY.md step by step. **Blocked on phase 4**
      (`pipeline.db` still SQLite; the box has nothing to point at yet).
- [ ] launchd plists retired (`com.zeropage.morningprompts`, `ops/com.zeropage.shadowrun`)
      once the Fly cron jobs are confirmed running for a few nights
- [ ] Dev server no longer runs migrations against production seconds after a save
- [ ] `pg_dump` on a schedule — exit stays cheap

## Not on this list, on purpose

- The shared brain stays global (#11): every user's verdicts teach every generation.
- One process, in-process job registry: fine for ten people, a hard ceiling past that.
- `role` on memberships is a label, enforced nowhere.

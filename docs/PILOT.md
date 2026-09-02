# Pilot — putting the studio in front of other people

What has to be true before someone who is not Mike signs in, and what is
deliberately still true afterwards. Written 2026-08-31, when tenancy landed
(`claude/account-tenancy`); BACKLOG #8 section 6 is the checklist this replaces.
**Walked on 2026-09-02** against a copy of the live database, as Mike and as an
invited pilot — `docs/PILOT_DRY_RUN.md` is what actually broke, ranked by what
blocks the invite. The corrections below are marked *(dry run)*.

## The boundary, in one paragraph

`account_id` on every owned row is who owns it. `brand` is a label on the row,
not the thing that decides who sees it. A person reaches rows through
`account_members`: signing in grants nothing, membership does, and a fresh
signup has zero memberships on purpose. `auth.current_account_id` resolves the
**tenant** — the user's oldest membership — while `auth.current_account`
resolves the **brand** for the pill. Those two must not be confused: scope the
data by the brand and clicking ANTIHERO shows an empty board.

**So a pilot user gets their own account.** Adding them to `zeropage` does not
give them a workspace, it gives them yours. `accounts invite` refuses that by
default and counts what they would have seen.

*(dry run)* The tenant/brand split has a third resolver: `auth.dev_account_id`
(the Dev Studio) goes through the **brand**, and memberships sort by slug, so
Mike's own `/studio` acts as ANTIHERO — account 2, which owns nothing — while
an anonymous visitor to it gets the bootstrap fallback, account 1, which owns
everything. `/api` resolves Mike to 1 correctly.

## Pre-flight 0 — the two things that block the invite regardless of env

*(dry run, both verified, both fixes are a few lines — see the report)*

1. **Create saves nobody's concept.** `/api/scenes/run`, `/api/pipeline/run`
   and `/api/generate/run` all drop the account at the call boundary and write
   `account_id = NULL`. The row is invisible to whoever pressed Create, and the
   next server start (`preprod.init` → `backfill_owner`) hands it to the
   bootstrap account — i.e. a pilot's concepts appear on Mike's board.
2. **Approve cannot render.** The Queue's approve and the Director's generate
   call `runway.generate_for_shot` without the account, so every owned row
   fails with `no concept N` before any API call. Dead for Mike today too.

Plus the three `/api` routes that still take `account_id` as a query
parameter (shot media, shot reference, location create): they 404 for their
owner and accept `?account_id=1` from anyone.

## Pre-flight

### 1. Decide what a day costs

Every `*_GLOBAL_DAILY_CAP` defaults to the same number as its per-account cap:

| tool | per account | global default |
|---|---|---|
| runway | 6 | 6 |
| veo | 6 | 6 |
| higgsfield | 6 | 6 |
| midjourney | 10 | 10 |
| nano | 20 | 20 |

That default is correct for one operator and wrong the moment there are two:
**the first person to render each day exhausts the ceiling for everybody**,
you included. Raise the globals to roughly (per-account cap × people) before
inviting anyone. That number is your daily spend limit — the default exists to
force the decision rather than let the total quietly multiply.

The per-account cap is fairness. The global ceiling is the credit card. Both
are needed: ten users each inside a cap of six is sixty renders on one card.

### 2. Env

```bash
SITE_URL=https://<host>              # or every canonical tag says 127.0.0.1
ZEROPAGE_MCP_HOSTS=<host>            # or DNS-rebinding protection blocks /mcp
RUNWAY_GLOBAL_DAILY_CAP=...          # and the other four
SESSION_SECRET=<stable value>        # unset = ephemeral, sign-ins die on restart
```

Leave `ZEROPAGE_MCP` **unset**. With a tunnel in front, setting it puts the MCP
endpoint on the public internet — the thing START_SERVER.md warns about. The
Claude Desktop stdio path does not need it.

### 3. OAuth

Register `https://<host>/auth/google/callback` and `/auth/discord/callback`.

Nothing in the app needs changing for this. `auth` builds redirects with
`request.url_for(...)`, and uvicorn trusts proxy headers from 127.0.0.1 by
default — so a tunnel running on the same machine gets `https://<host>/...`
without `--proxy-headers`. Verified by sending `Host` + `X-Forwarded-Proto:
https` at the app with exactly the flags `ops/serve.sh` uses.

### 4. Rotate the secrets

Thirteen secret-shaped keys have lived in `.env` on a dev machine:
`GEMINI_API_KEY`, `YOUTUBE_API_KEY`, `LANGSMITH_API_KEY`, `IG_ACCESS_TOKEN`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `SESSION_SECRET`,
`GOOGLE_CLIENT_SECRET`, `RAG_DATABASE_URL`, `HIGGSFIELD_API_KEY_ID`,
`HIGGSFIELD_API_KEY_SECRET`, `ZEROPAGE_MCP_TOKEN`.

Rotating `SESSION_SECRET` signs everyone out. Do it before the invites, not
after. *(dry run)* The failure mode is clean: `/ui` → `/signin`, `/api` → 401,
no 500, and an unset secret generates an ephemeral one with a stderr note.

## Inviting

```bash
venv/bin/python -m src.accounts invite alex@example.com --brand alex
venv/bin/python -m src.accounts members
```

`--brand` is the slug of *their* account. Use a new one. An existing slug that
owns rows is refused; `--join-existing` overrides that when sharing a workspace
is genuinely what you mean.

No password and no secret to send. The row sits unclaimed until they sign in
with Google or Discord on that exact address, and the first sign-in claims it
(`auth._finish_oauth`). Their board starts empty.

*(dry run)* **That is the only door.** Email/password signup on the invited
address answers "already exists -- try signing in the other way", and login
has no hash to check. If the OAuth callbacks are not registered yet (they are
not on localhost), the invite is complete and unusable — register them first,
or give `invite` a password.

*(dry run)* "Their board starts empty; they cannot see anyone else's" is true
for concepts, assets, the queue and analytics. It is **not** true for
`/api/holds` (they get all 22 of Mike's held runs, and can resolve or post
them), `/api/workflows/{id}` (read/rename/delete/run by id), `/api/jobs`
(every user's jobs, cancel and clear included) and the evals endpoints — and a
signup with *no* membership sees the same, because the membership gate lives
inside `current_account_id`, not in the router-level `require_user_api`.

`role` is recorded and enforced nowhere. It is a label, not a permission.

## What is still true with people on it

- **One process, no scaling.** `app/jobs.py` keeps the job registry in an
  in-process dict on purpose. *(dry run)* Not one worker: `jobs.start` spawns
  a daemon thread per job, unbounded — two jobs ran in parallel — so ten
  people pressing Create is ten concurrent model calls on one SQLite file. A
  restart empties the registry; the Queue is derived from rows and survives.
- **Your keys pay.** Renders bill to your Gemini / Runway / Higgsfield
  accounts. The global ceiling is the only thing between a pilot and your card.
- **The dev console is not tenant-scoped the way /api is.** `auth.dev_account_id`
  falls back to the bootstrap account with no session, and resolves through
  the *brand* with one *(dry run: for Mike that is ANTIHERO, empty)*. It is
  DEV_TOOLS-only and never mounted on a public deployment (verified: every dev
  route 404s with the flag unset) — but do not mount it on one, and do not
  tunnel a dev machine to a pilot with the flag set.
- **`corrections` is cross-tenant.** *(dry run, reproduced)* A pilot's deny
  note steers Mike's next nightly run once and is consumed before their own.
  BACKLOG #11 owns the fix.
- **Veo has no spend gate.** *(dry run, confirmed)* Only the daily cap stands
  between a Veo prompt and $3.20. Don't set `ZEROPAGE_RENDER=1` or the
  autopilot live gate during the pilot.
- **`accounts` is doing double duty** as tenant table and brand table, with
  "oldest membership" picking the tenant. That holds while each person belongs
  to one operator. The day someone legitimately belongs to two, it has to split
  into `tenants` and `brands` for real. See BACKLOG #8.
- **SQLite on local disk is the store.** `data/pipeline.db` plus the renders.
  Back it up before the pilot and on a schedule during it.

## If it goes wrong

`tests/test_tenancy.py` is the safety net — 42 tests, including a static one
that parses every SQL literal in `src/`, `app/` and `ops/` and fails on any
statement that reaches an owned table without an owner predicate. If someone
adds a query that leaks, that test is what catches it. Run it before any
deploy:

```bash
venv/bin/python -m pytest -q tests/test_tenancy.py
```

Run `pytest tests/`, not bare `pytest` — the latter collects `evals/`, which
makes real Gemini calls and needs `deepeval` from `evals/requirements.txt`.

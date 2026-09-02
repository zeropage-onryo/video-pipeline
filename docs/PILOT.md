# Pilot — putting the studio in front of other people

What has to be true before someone who is not Mike signs in, and what is
deliberately still true afterwards. Written 2026-08-31, when tenancy landed
(`claude/account-tenancy`); BACKLOG #8 section 6 is the checklist this replaces.

## The boundary, in one paragraph

`account_id` on every owned row is who owns it. `brand` is a label on the row,
not the thing that decides who sees it. A person reaches rows through
`account_members`: signing in grants nothing, membership does, and a fresh
signup has zero memberships on purpose. `auth.current_account_id` resolves the
**tenant** — the user's oldest membership — while `auth.current_account`
resolves the **brand** for the pill. Those two must not be confused: scope the
data by the brand and clicking ANTIHERO shows an empty board.

The dry run of 2026-09-02 (`docs/PILOT_DRY_RUN.md`) found the paragraph above
was true of the eight tables then on `db.OWNED_TABLES` and false of
`hold_queue`, `workflows` and the job registry, which had no owner at all.
Fixed the same day: both tables are owned and backfilled, every job carries
its account, every `/api` route declares `auth.current_account_id` (a test
walks the router), and every table is either owned or named in
`db.SHARED_TABLES` with the reason it is global. Items 4 and 5 of that
report's fix order (`corrections` scoping, `active_brand` off memberships)
are still open and can follow the first user.

**So a pilot user gets their own account.** Adding them to `zeropage` does not
give them a workspace, it gives them yours. `accounts invite` refuses that by
default and counts what they would have seen.

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
inviting anyone. **Measured 2026-09-02:** six renders under a
second account produce `daily ceiling: 6/6 ... across all accounts` for Mike.
`.env.example` now carries the decision for three people (18 / 18 / 18 / 30 /
60, the arithmetic in the comment) -- copy it and change the multiplier; the
code defaults stay the one-operator numbers. Veo has `VEO_SPEND_OK` since the
same day, the per-run approval Runway and Higgsfield always had. The global
number is your daily spend limit — the default exists to
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

And on the **command**, never in `.env`, on the day something should actually
go out: `ZEROPAGE_POST_OK=1` (the per-run approval to publish, the posting
equivalent of `RUNWAY_SPEND_OK`; without it every post reports
`post-unapproved`) and `VEO_SPEND_OK=1` if Veo is to render. A serve process
started without them cannot publish or spend Veo credit however it is asked.

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
after.

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

`role` is recorded and enforced nowhere. It is a label, not a permission.

## What is still true with people on it

- **One process, no scaling.** `app/jobs.py` keeps the job registry in an
  in-process dict on purpose. One worker. Fine for ten people, hard ceiling.
- **Your keys pay.** Renders bill to your Gemini / Runway / Higgsfield
  accounts. The global ceiling is the only thing between a pilot and your card.
- **The dev console is not tenant-scoped the way /api is.** `auth.dev_account_id`
  falls back to the bootstrap account. It is DEV_TOOLS-only and never mounted
  on a public deployment — but do not mount it on one.
- **`accounts` is doing double duty** as tenant table and brand table, with
  "oldest membership" picking the tenant. That holds while each person belongs
  to one operator. The day someone legitimately belongs to two, it has to split
  into `tenants` and `brands` for real. See BACKLOG #8.
- **SQLite on local disk is the store.** `data/pipeline.db` plus the renders.
  Back it up before the pilot and on a schedule during it.

## If it goes wrong

`tests/test_tenancy.py` is the safety net — a static test that parses every SQL
literal in `src/`, `app/` and `ops/` and fails on any statement that reaches an
owned table without an owner predicate; a route test that walks `/api` and
fails on any route that does not declare `auth.current_account_id`; a schema
test that fails on any table neither owned nor named in `db.SHARED_TABLES`
with a reason; and a stranger signed in with no membership making the dry
run's requests. If someone adds a query, a route or a table that leaks, one of
those is what catches it. Run it before any deploy:

```bash
venv/bin/python -m pytest -q tests/test_tenancy.py
```

Run `pytest tests/`, not bare `pytest` — the latter collects `evals/`, which
makes real Gemini calls and needs `deepeval` from `evals/requirements.txt`.

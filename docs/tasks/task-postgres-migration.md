# pipeline.db -> Supabase Postgres, with RLS — backlog #14 phase 4

Written 2026-09-03, the night RAG moved (see [[supabase.md]] / docs/ROLLOUT.md
phase 4). Scoped tonight, NOT executed — this is the plan, not the migration.
Doing it blind across 15 modules and ~300 sqlite3 call sites without running
the suite after each step is how `concept_locations` got damaged once
(verifying.md); it deserves the same care, on a copy, with tests green at
every step, not a single unreviewed pass.

## Decisions already made (2026-09-03)

- **Postgres only** — no dual SQLite/Postgres code path. Tests run against a
  throwaway Postgres schema (the `docker-compose.yml` pgvector box already in
  this repo, or a second Supabase branch/project for CI).
- **Supabase Auth**, replacing `app/auth.py`'s hand-rolled Google/Discord
  OAuth + `accounts.py`'s `users` / `auth_identities` tables. Bigger rewrite
  than "just move the tables," chosen anyway for `auth.uid()` inside RLS
  policies instead of threading `current_account_id` through every policy by
  hand.

## The concrete dialect translations (verified against src/db.py, not guessed)

| SQLite | Postgres | where it bites |
|---|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `GENERATED ALWAYS AS IDENTITY` (or `SERIAL`) | every `CREATE TABLE` in every module's `SCHEMA` string |
| `?` placeholders | `%s` (psycopg) | every single query — this is the bulk of the ~300 sites |
| `col IS ?` (NULL-safe compare, used for `account_id IS ?`) | `col IS NOT DISTINCT FROM %s` | every tenancy-scoped read; `=` silently drops all NULL-owned rows, which is a different bug from the one tenancy fixed |
| `cur.lastrowid` | `RETURNING id` on the INSERT, read from the cursor | every `save_pitch_run`, `add_video`, `record_metrics`-shaped function |
| `ON CONFLICT (...) DO UPDATE SET x = excluded.x` | same syntax, Postgres supports it natively | `record_metrics`'s upsert — no change needed, just confirm the `excluded.` alias still resolves |
| `datetime('now')` | `now()` | `account_keys.py`'s `updated_at` default (built tonight — already needs this swap), every `_now()` helper across modules |
| `julianday(a) - julianday(b)` | `extract(epoch from (a::timestamptz - b::timestamptz)) / 86400` | `get_top_performers`'s age-in-days math — this one is easy to get subtly wrong; test it against a known pair before trusting it |
| `PRAGMA table_info(x)` | `information_schema.columns` | `add_account_column`'s column-exists check |
| `conn.executescript(SCHEMA)` | run each statement separately, or `conn.execute(SCHEMA)` with psycopg's multi-statement support off by default | every module's `init()` |
| `UNIQUE(account_id, name)` (NULLs distinct — already a documented trap, verifying.md) | Postgres NULLs are ALSO distinct in a UNIQUE constraint, so the existing `COALESCE` index trick carries over unchanged | anywhere backfilled from that lesson |

## Module-by-module order (do NOT do all 15 in one pass)

Each of these owns its own `SCHEMA` / `init()`. Port one, run its test file
alone against the throwaway Postgres, then move on:

1. `src/db.py` — smallest, four tables, already fully read for this doc.
2. `src/accounts.py` — must land before anything that FKs `accounts(id)`,
   and it's the one being replaced by Supabase Auth, so this step is really
   "design the auth.users <-> accounts bridge," not a straight port.
3. `src/preprod.py` — the big one (70 `sqlite3`-touching lines by an earlier
   count). Holds `shoot_concepts`, `shots`, most of `db.OWNED_TABLES`.
4. `src/generative.py`, `src/entities.py`, `src/scout.py`, `src/winners.py`,
   `src/evalstore.py` — mid-size, mostly independent of each other.
5. `src/autonomy.py`, `src/workflows.py`, `src/inspiration.py`,
   `src/scheduling.py`, `src/settings.py`, `src/instagram.py` — smaller
   tables, do last so the schema they FK against already exists.
6. `app/auth.py` + `app/jobs.py` — last, because they're what changes shape
   the most (Supabase Auth) and what the pilot actually signs in through.

`src/rag.py` needs NOTHING further — it already speaks Postgres (Supabase,
since tonight) and stays a separate connection, deliberately, per its own
docstring.

## RLS — the worked pattern (using the ONE schema fully verified tonight)

Every policy below assumes the request sets a session variable naming the
caller's account, the way backlog #14's own writeup describes:
`SET LOCAL request.account_id = '<n>'` per request (from the FastAPI
dependency that already resolves `current_account_id` — #12 already did the
hard part, this is "read the same value, hand it to Postgres too").

```sql
-- videos: db.py's real schema, translated
CREATE TABLE videos (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idea_id     bigint REFERENCES ideas(id) ON DELETE SET NULL,
    concept_id  bigint,
    title       text NOT NULL,
    platform    text NOT NULL,
    posted_at   text NOT NULL,
    url         text,
    timeline    text,
    topic       text,
    hook_type   text,
    duration_s  real,
    notes       text,
    brand       text,
    account_id  bigint NOT NULL REFERENCES accounts(id)
);

ALTER TABLE videos ENABLE ROW LEVEL SECURITY;

CREATE POLICY videos_isolation ON videos
    USING (account_id = current_setting('request.account_id', true)::bigint)
    WITH CHECK (account_id = current_setting('request.account_id', true)::bigint);
```

`current_setting(..., true)` returns NULL rather than erroring when the
session variable is unset — which means a connection that forgets to set it
sees **zero rows**, not every row. That is the whole point: it converts
"forgot the owner predicate" from a leak into an empty result, the way
backlog #14's writeup describes RLS as the structural fix for the exact bug
the dry run found.

**The trap, repeated because it is the one that matters:** the nightly
orchestrator, `ops/bank.py`, and any script under `ops/` connect as the
Postgres owner role for convenience today. A superuser / table-owner
connection **bypasses RLS entirely regardless of the policy above** — so
every one of those service-key paths needs either (a) its own `SET LOCAL
request.account_id` before each tenant-scoped query, done explicitly, or (b)
a deliberate, small, audited list of paths that are allowed to see
everything (the nightly walk legitimately needs to, since it writes on
behalf of the operator). Track that list in this file when it's built —
"deliberate and audited" is a decision that has to be visible, not implicit
in which role happened to be used.

`account_keys` (built tonight, see [[account-keys]]) gets the identical
treatment when it moves — same policy shape, same `account_id` column,
already there.

## Testing

`tests/test_tenancy.py`'s static SQL test (audits `db.OWNED_TABLES` for a
missing owner predicate) stops being the only line of defense once RLS
exists — it becomes the second line, per backlog #14's own framing. Keep it
green throughout the port; it will catch a query that lost its predicate
during translation before RLS would have silently returned zero rows and
made a feature look broken instead of a bug look caught.

## Exit

`pg_dump` on Supabase, same as any Postgres. No new export tooling needed —
that's the point of choosing this substrate.

## Step 1 — `src/db.py`, done 2026-09-03

Branch `claude/sqlite-postgres-migration-step1-3592b0`. The plan above left
these open; each was put to Mike and decided before any code was written.
They bind every later step, so the schemas don't drift from each other.

- **The throwaway box is Postgres.app.** There is no Docker on this machine
  (`docker-compose.yml` is not a fallback here). A `zeropage` role
  (password `zeropage`, CREATEDB) and a `zeropage` database were created on
  Postgres.app's PG 18.6 on `:5432`, so the compose URL works verbatim.
  The Homebrew PG17 on `:5433` (the local RAG copy) was left alone.
- **`videos.account_id` stays nullable and carries no FK yet.** NULL is the
  unowned pool that `tests/conftest.py`'s `account_scope` and
  `backfill_owner` are built on. `accounts` is step 2, so `REFERENCES
  accounts(id)` cannot be declared yet; `add_account_column` (now on
  `information_schema.columns`, scoped to `current_schema()`) adds a bare
  `BIGINT`, and step 2 adds the constraint with `ALTER TABLE ... ADD
  CONSTRAINT`. The `NOT NULL` in the worked example above is the RLS-era
  target, not step 1.
- **Identity is `GENERATED BY DEFAULT AS IDENTITY`, not `ALWAYS`.** The
  SQLite data copy has to preserve ids (`videos.idea_id`, `concept_id`,
  `metrics.video_id` point at them) and `ALWAYS` refuses an explicit id
  without `OVERRIDING SYSTEM VALUE`. Same form in every schema from here on.
- **The parameter is `dsn`, not `path`**, resolved as `dsn or DATABASE_URL
  or db.DEFAULT_DSN` (`DATABASE_URL` is the name docs/DEPLOY_FLY.md already
  uses). `db.DB_PATH` still names the SQLite file: the data copy reads it
  and unported modules import it. `grep -rn "path=" src/` is the list of
  what is left to port.
- **Tests get a schema each.** `tests/conftest.py`'s `pg` fixture creates a
  fresh schema, hands the test a URL carrying `options=-c
  search_path=<schema>`, and drops it after. The code under test needs no
  notion of schema: `CREATE TABLE IF NOT EXISTS`, `to_regclass()` and
  `information_schema` all resolve on `search_path`, and id sequences
  start at 1 per schema. It reads `TEST_DATABASE_URL`, falling back to the
  compose URL — **never `DATABASE_URL`**, which is live in any real `.env`.
  Reuse the fixture for every module's tests.

What the translation table above did not say, found by running it:

- `connect()` sets the session to UTC. The `julianday` translation is only
  equivalent there: a date-only `posted_at` cast to `timestamptz` takes
  the session zone, while a full ISO `captured_at` carries `+00:00`.
- `ROUND(x, 1)` is `ROUND(x::numeric, 1)::float8` — Postgres has no
  `round(double precision, int)`, and without the cast back the caller
  gets a `Decimal`.
- SQLite `REAL` is 8 bytes; Postgres `real` is 4. `duration_s` and
  `watch_time_seconds` are `DOUBLE PRECISION`. Read the worked example's
  `real` as that.
- `sqlite3.Row` was both a mapping and a sequence; psycopg's factories
  are one or the other. `db.Row` (a dict with positional indexing) keeps
  `row["id"]`, `row[0]` and `dict(row)` all working.
- `_ensure_accounts_table` is a stub that raises until step 2 —
  `preprod.py` imports it by name at import time, and a missing name takes
  `app.main`, and with it every test module, down before a test runs.
- The SQLite-era migrations in `init_db` (add `videos.brand`, add
  `videos.concept_id`) are gone: no Postgres database predates those
  columns. `own_table` stays, because step 2's FK is applied to a table
  that already exists by then.

Verified: `pytest tests/test_db.py` — 48 passed against the throwaway;
ruff clean; the static owner-predicate audit in `tests/test_tenancy.py`
passes on `IS NOT DISTINCT FROM`. Everything that calls `db.connect(path)`
is red by design until its own step. **CI has no Postgres service yet** —
`.github/workflows/ci.yml` needs the compose box as a service container
(or the Supabase branch mentioned under Decisions) before this branch can
be green there.

## Step 2 — `src/accounts.py`, done 2026-09-03

**A straight port, not the bridge** (Mike's call, same night). The line
above saying this step is "design the auth.users <-> accounts bridge" was
put to him against two facts: the module order already puts the Supabase
Auth rewrite at step 6 with `app/auth.py`, and the throwaway box has no
`auth` schema to test a bridge against. Steps 3–5 only need `accounts(id)`
to exist as an FK target. So the four tables moved as they are, and the
bridge is designed at step 6 against a real Supabase project.

- `users` / `auth_identities` / `accounts` / `account_members` carry the
  step-1 conventions: `BIGINT GENERATED BY DEFAULT AS IDENTITY`, `%s`,
  `RETURNING id`, `dsn` for `path`. `INSERT OR IGNORE` became `ON CONFLICT
  (account_id, user_id) DO NOTHING`. `sqlite_master` / `PRAGMA` reads went
  through `db.table_exists` / `db.columns`, so a per-test schema and
  `public` look alike. `create_user` raises `psycopg.errors.UniqueViolation`
  where it raised `sqlite3.IntegrityError`; nothing outside the module
  caught either by type.
- **The FK deferred from step 1 is declared now.** `db._ensure_accounts_table`
  has its real body again (run `accounts.SCHEMA`, lazily imported to avoid
  the cycle), and `db.add_account_column` grew a second idempotent half,
  `_ensure_owner_fk`: `<table>_account_id_fkey`, looked up by name on the
  table's oid, added as `ALTER TABLE ... ADD CONSTRAINT`. It has to be a
  separate step because a module's SCHEMA can carry `account_id` inline
  but never the `REFERENCES` -- `accounts.SCHEMA` lives in the module that
  imports `db`. Verified on a fresh schema: `init_db` twice around
  `accounts.init` is idempotent, and an insert with a stray `account_id`
  is refused.
- **Callers under `app/` switched to the default.** `app/auth.py`,
  `app/api.py` and `app/main.py` no longer pass `path=db.DB_PATH` to any
  `accounts.*` call: with no `dsn`, `db.connect()` resolves `DATABASE_URL`,
  and `test_auth.py`'s fixture sets that to the per-test schema. Note
  `app/main.py` imports the module as `accounts_mod` -- grep both names.
  Callers under `src/` (`slug_of`, `resolve_account`) still pass `path=`
  and stay red until their own module's step.

Verified: `pytest tests/test_auth.py tests/test_db.py` — 75 passed, 1 failed
(`test_legacy_studio_stays_open` calls `preprod.init`; step 3). Full
suite 579 passed / 41 failed / 831 errors, all the latter from unported
modules; ruff clean; the static owner-predicate audit passes.

**Tonight's uncommitted work in the main checkout** (45 paths, including
`src/account_keys.py`, `ops/migrate_rag_to_supabase.py`, the Fly files)
is not on this branch, and its diff adds ~34 more `db.connect` /
`path=db.DB_PATH` sites. Commit it to `main` and merge it in before step
3, or those sites get ported twice.

## Step 3 — `src/preprod.py`, done 2026-09-03

**The SQLite-era migration is gone, its properties stay** (Mike's call).
A third of the file was `_rebuild_locations_unique`,
`_repair_concept_locations_fk`, `_assert_no_dangling`, two `*_TARGET`
DDL strings and eight ALTER-if-missing column adds. None of it can run on
Postgres and no Postgres database will ever be in the pre-tenancy shape,
so `SCHEMA` is now the final shape: every once-ALTER'd column inline with
its comment kept, `account_id` inline on `locations` / `shoot_concepts` /
`scene_briefs` (nullable; `db.own_table` still declares the FK), and
`LOCATIONS_UNIQUE` — the `COALESCE(account_id, 0), name` expression index
— created by `init()` beside it. The doc's translation table was right
that the COALESCE trick carries over: Postgres treats NULLs as distinct
inside a UNIQUE exactly as SQLite does.

- `add_location`'s upsert names the index's expressions in its conflict
  target, `ON CONFLICT ((COALESCE(account_id, 0)), name)` — the extra
  parentheses are Postgres's syntax for an expression there, and without
  them the statement is a syntax error. `RETURNING id` is right on both
  paths of the upsert, so the "lastrowid is not trustworthy after DO
  UPDATE" re-select is gone.
- `INSERT OR IGNORE` on the join table is `ON CONFLICT (concept_id,
  location_id) DO NOTHING`. `json_array_length(shots_json)` needs a
  `::json` cast — the column is TEXT.
- The placeholder sweep has to skip `_OPENERS` and the `re.split` calls:
  a regex is the one place a `?` legitimately lives in this file.
- **`tests/test_tenancy.py` lines 38–273 were rewritten, not deleted.**
  `legacy_db` (raw sqlite3 + the a8fe240 schema) became `unowned`: the
  same rows inserted with NULL owners on a `pg` schema after
  `preprod.init`, which is the state every fresh install passes through.
  Kept as properties: rows claimed by the bootstrap account, init-before-
  seed leaves them unowned, seed claims them, the join table's FKs name
  the real tables (checked in `pg_constraint`), the cascade fires, two
  accounts can each own a Garage, one account cannot own two
  (`psycopg.errors.UniqueViolation`), ownerless rows still collide,
  `add_location` still upserts by name. Deleted: the six that pinned the
  rebuild's mechanics (`locations_old` healing, scratch tables, schema-
  text scans). Every other fixture in the file is on `pg` now, so the
  file turns green step by step; `two_accounts` still errors until
  `entities` and `generative` land (step 4).
- The static owner-predicate audit's `UNSCOPED_ALLOWED` carries **both**
  the `%s` and `?` forms of three exemptions until steps 4 and 5 port the
  modules that still say `?`; the `INSERT INTO locations_new` /
  `concept_locations_new` entries left with the rebuild.
- Callers under `app/` (`api.py` 41, `main.py` 18, `workflow_runner.py`
  1) dropped `path=db.DB_PATH`. The step-2 regex missed most of them
  because `path=` sat FIRST among the kwargs there, not last; the switch
  is now a balanced-paren scan over each `preprod.<fn>(...)` call, which
  is what the remaining modules should use.

Verified: `pytest tests/test_preprod.py` 31 passed; the three ported test
files together 106 passed, 1 failed (`test_legacy_studio_stays_open`, now
stopping at `entities.init`). `tests/test_tenancy.py`: 16 passed, 36
errors (all `two_accounts` → unported `entities`/`generative`), 4 failed
(two need every module's `init`, one is the hold_queue/workflows legacy
test for step 5, one is the pre-existing NANO cap check). Full suite 621
passed / 34 failed / 791 errors, all from unported modules; ruff clean;
the static audit passes.

## Step 4 — `generative`, `entities`, `scout`, `winners`, `evalstore`, done 2026-09-03

Five modules, one pass each, the step-3 pattern throughout: identity
columns, `%s`, `RETURNING id`, `IS NOT DISTINCT FROM` (including the
column-to-column `x.account_id IS g.account_id` in generative's
scoreboard subqueries), `account_id` inline and nullable with
`db.own_table` declaring the FK, `DOUBLE PRECISION` for every `REAL`.
The SQLite-era ALTER-if-missing migrations (winners' `verdict` /
`pair_id`, evalstore's `RUN_COLUMNS`, scout's `pass_id`) went inline,
per the step-3 decision; `tests/test_winners_migration.py` keeps the
contract the 2026-08-11 crash exposed (idempotent init, `avoid_guidance`
never raises, verdict round-trips) instead of the ALTER. Two dialect
notes: `ORDER BY name COLLATE NOCASE` is `ORDER BY lower(name)`; the
placeholder sweep has to skip regex lines in `scout.py`, and a `?` that
opens a string continuation (`"?, ?, ..."`) needs its own rule.

**The caller sweep is where the work was.** Porting a module means
every caller of it switches to `dsn=`, and callers hide the path four
ways the step-2/3 regexes could not see. Recorded here because steps 5
and 6 will meet all four again:

1. **kwargs dicts** — `kwargs = {"path": db_path} if db_path else {}`
   then `fn(**kwargs)`, in every render tool (`runway`, `veo`,
   `higgsfield`, `nano_banana`, `midjourney`), `genlog`, `promptgen`,
   `shootgen`, `director`, `rework`, `locations`, `storage`, `youtube`,
   `post_seo`, `promote_winners`, `refresh_metrics`, `autopilot`. Now
   `{"dsn": db_path}`.
2. **the positional fallback** — `db_path if db_path is not None else
   DB_PATH`, which on Postgres hands a FILE PATH to psycopg. Now plain
   `db_path`: None resolves `DATABASE_URL`.
3. **aliases** — `accounts as accounts_mod` (app/main.py), `generative
   as gen` (genlog, promptgen), `scout as scout_mod` (orchestrator),
   `db as _db` (asset_shelf). The sweep now discovers `import X as Y`
   and sweeps `Y.` too.
4. **caller-only modules with their own DB parameter named `path`** —
   `mcp_server.py` (94 uses, all the database), `research_agent.py`,
   `ops/bank.py`. Renamed to `dsn` with the `DB_PATH` fallbacks
   removed; `research_agent` passes `--db` to its MCP subprocess only
   when a DSN was given, so the child inherits `DATABASE_URL` otherwise.
   `mcp_server._full` had an `if path is not None` guard around the
   gate that its only caller could never make false; it is gone.

Callers of `preprod` and `db` under `src/` and `ops/` (which steps 1 and
3 left alone) were swept in the same pass. `format_feed.rank_formats`
still names its parameter `path`; it only forwards it.

Verified: `test_generative` 26, `test_genlog` 6, `test_winners_migration`
3, `test_crag` 10, `test_scout_api` 21, `test_bank_ingest` 12,
`test_runway` 23, `test_veo` 8, `test_higgsfield` 30,
`test_research_agent` all green; `test_scout` / `test_scout_separation` /
`test_mcp_server` green except nine tests that reach `autonomy`
(`hold_for_concept` still takes `path`; `init` still says
`executescript`), and `test_scout_instagram` errors in its fixture on
`instagram.init` / `inspiration.init` — all step 5. `test_tenancy.py`:
42 passed; the eight `two_tenants` errors and the remaining failures are
autonomy / workflows / the every-module inits (step 5) plus the
pre-existing NANO cap check. The static audit's `?`-form exemption for
`generations` is retired; the two for `hold_queue` / `workflows` stay
until step 5.

## Step 5 — the last nine `src/` modules, done 2026-09-03

`autonomy`, `workflows`, `inspiration`, `scheduling`, `settings`,
`instagram` — plus three the list above never named and Mike added to
this step: `imagesearch` (image_candidates), `framebank` (frames),
`render_assets` (generated_assets). Every module under `src/` that owns
a SCHEMA now speaks Postgres; `rag.py` always did. The step-3/4 pattern
throughout, migrations inline (autonomy's `targets` ALTER and the
personal→antihero rename, workflows' four ALTER'd columns, inspiration's
`brand` ALTER + backfill), `INSERT OR IGNORE` → `ON CONFLICT (name) DO
NOTHING`, `INSERT OR REPLACE` → `ON CONFLICT (tag) DO UPDATE`,
`sqlite3.OperationalError` → `psycopg.Error`. The legacy holds/canvases
tenancy test became a property test on `pg`, like the locations one,
and the static audit's SQLite-era and `?`-form exemptions are all
retired: no module says `PRAGMA`, `sqlite_master` or `?` any more.

**Three Postgres traps found only by running it:**

- **`SUM(<boolean>)`.** SQLite quietly summed `passed = 1 AND
  human_verdict = 'post'` as 0/1; Postgres refuses. `SUM(CASE WHEN ...
  THEN 1 ELSE 0 END)` in `autonomy.prompt_gate_agreement`.
- **A bare parameter inside `CASE WHEN`.** `CASE WHEN %s = 'posted' THEN
  %s ELSE posted_at END` fails with "could not determine data type";
  `%s::text` on both. `scheduling.mark_status`.
- **`db.Row` had to grow up twice.** `SELECT COUNT(*), SUM(a), SUM(b)`
  names its columns `count, sum, sum`, and a dict keeps one `sum` — so
  `row[2]` was an IndexError; positions are now their own tuple. And
  `dict(rows)` over fetched rows, or `a, b = fetchone()`, relied on
  sqlite3.Row being a sequence: `Row.__iter__` yields values now (the
  mapping is still `dict(row)`, `keys()`, `in`, `**row`), and
  `autonomy.evaluator_agreement` builds its counts by position.

**The fifth caller shape.** `db_path=db.DB_PATH` handed to a caller-only
wrapper (`shootgen.reference_block`, `scene_chain.*`, `director.*`,
`runway.generate_for_shot`, `taste_judge.*`, `asset_shelf.backfill` …)
which forwards it as `dsn=` — a PosixPath into psycopg. And `x or
db.DB_PATH` fallbacks in the wrappers themselves. All are `None` now
(DATABASE_URL at call time); `db.DB_PATH` has no reference left outside
`db.py`, where it stays for the data copy. Caller-only modules with
their own SQL — `taste_judge`, `ops/backfill_loglines.py`,
`ops/ingest-saved-images.py` — took the placeholder sweep.
`format_feed.rank_formats` and `ops/bank.py` renamed their DB parameter
to `dsn`; `presets.load_presets(path=)` is a FILE and stays.

`ops/render_queue.py` lost its `sqlite3.connect` monkeypatch (the
per-connection `journal_mode=MEMORY` fuse for the FUSE mount): a network
database has no journal on the mount to protect. Its "stdlib-only"
docstring is now honest about needing psycopg through `src.db`.

Tests: `pg_factory` joined `pg` in conftest for the tests that need a
second, empty schema (settings' no-table read). Every test file is on
`pg` now; `tmp_path / "x.db"` appears nowhere.

Verified: full suite **1434 passed, 7 failed, 5 errors, 9 xfailed**. Eleven
of the twelve non-passes are `tests/test_imagesearch.py` expecting `mcp_server.find_images`
/ `_reachable`, which exist on neither this branch's HEAD nor the main
checkout's uncommitted tree — they were failing before this migration
began. The twelfth is the pre-existing `NANO_GLOBAL_DAILY_CAP` check in
`.env.example`. ruff clean over the whole repo.

**Next:** step 6, `app/auth.py` + `app/jobs.py` and Supabase Auth — the
bridge design this doc always meant to happen last. Before it: merge the
main checkout's uncommitted 2026-09-03 work into this branch (it adds
`account_keys.py`, which needs the `datetime('now')` swap from the
table above, and ~34 more `db.connect`/`path=` sites for the same five
caller shapes), and give CI a Postgres service.

## Step 6 — `app/auth.py` on Supabase Auth, done 2026-09-03

`app/jobs.py` needed nothing: it is an in-memory registry with no
database behind it, and already carries the account that started each
job. Step 6 is the bridge the plan deferred, and it was DESIGNED, not
ported — three decisions put to Mike (all the recommended options):

1. **Build the GoTrue flow now, verify against the real project later.**
   Server-side, two HTTP calls, no client library (httpx + PyJWT, both
   already installed): the OAuth doors redirect to
   `{SUPABASE_URL}/auth/v1/authorize` (PKCE; the verifier lives in the
   starlette session cookie), Supabase returns to `/auth/callback?code=`,
   the code is exchanged at `/auth/v1/token?grant_type=pkce`; email +
   password is the same endpoint with `grant_type=password`, sign-up is
   `/auth/v1/signup` (a project with confirmation on returns no session,
   and the page says "check your email"). The access token is verified
   ONCE with `SUPABASE_JWT_SECRET` (HS256), or the project's JWKS when
   no secret is set (newer projects sign asymmetrically), audience
   `authenticated` so an anon or service token is never a person.
   `auth.gotrue` is the one seam every request goes through; tests
   replace it with `FakeGoTrue`, which signs real tokens with a test
   secret, so `verify_token` runs for real and the network guard still
   applies.
2. **`users` is a profile MIRROR keyed by the Supabase UUID.** id TEXT,
   no FK into `auth.users` (the schema is Supabase's; the throwaway box
   has none). `auth_identities` and `password_hash` are gone — Supabase
   owns identities and passwords. `account_members.user_id` is the
   UUID, with `ON UPDATE CASCADE`, which is what lets an invite work
   before the person has ever visited: `invite` writes the row by email
   with a placeholder uuid4 and `claimed_at` NULL, and the first
   sign-in (`accounts.claim`, the resolution ladder) rewrites the id to
   the real one; the membership follows. The seeded bootstrap user takes
   the same path. An email already claimed by a DIFFERENT uuid is refused,
   never merged — Supabase keeps one auth user per email, so that only
   happens after an auth user was deleted and re-created, and merging
   would hand the new person the old memberships.
3. **The cookie stays ours** (itsdangerous, httpOnly, 30 days), now
   carrying the Supabase user id. current_user / current_account /
   current_account_id / dev_account_id keep their contracts unchanged;
   no refresh token is stored because the app never acts as the user
   against Supabase after sign-in. RLS via `auth.uid()` over a per-user
   connection is the phase-4 bullet that would change that, and it is
   not this step.

Gone with the hand-rolled auth: Authlib, argon2 (`requirements.txt`),
`GOOGLE_*` / `DISCORD_*` env (the client ids move to the Supabase
dashboard), `accounts seed --password`. `SUPABASE_PROVIDERS` (default
`google,discord`) says which buttons the sign-in page offers, because
the app cannot read what the dashboard enabled. The old
`/auth/google/callback` and `/auth/discord/callback` URLs stay as
aliases of `/auth/callback`. `db.SHARED_TABLES` lost `auth_identities`.

Verified hermetically: `tests/test_auth.py` (rewritten, 40 tests: the
doors, the gate, the claim ladder, the token, the PKCE round trip) and
the full suite green apart from the eleven pre-existing
`test_imagesearch` failures and the NANO cap check. **Not verified: a
real sign-in through the project.** That needs the checklist below, and
Mike's hands on the dashboard.

### Supabase Auth setup checklist (the part only the dashboard can do)

- [ ] Project Settings → API: copy the project URL → `SUPABASE_URL`, the
      anon key → `SUPABASE_ANON_KEY`; JWT Settings → the JWT secret →
      `SUPABASE_JWT_SECRET` (skip if the project uses signing keys; the
      app falls back to JWKS).
- [ ] Authentication → Providers: enable Google and Discord with the
      SAME client ids and secrets that were in `.env`; in each provider's
      own console replace the redirect URI with Supabase's:
      `https://<project-ref>.supabase.co/auth/v1/callback`.
- [ ] Authentication → URL Configuration: Site URL = `SITE_URL`;
      redirect allow-list gets `<SITE_URL>/auth/callback` and
      `http://localhost:8000/auth/callback`.
- [ ] Authentication → Email: decide "confirm email" (on = a sign-up
      sees "check your email"; off = signed in at once).
- [ ] `python -m src.accounts seed <mike's email>` on the Postgres
      database, then sign in with Google using that email: the first
      sign-in claims the row and both brands appear on the picker.
- [ ] `docs/ROLLOUT.md` phase 2 (main checkout): the "register
      /auth/google/callback and /auth/discord/callback" bullet is now the
      Supabase allow-list bullet above.

**The data copy, still to write.** Every `users` row copied from
`data/pipeline.db` lands with a placeholder id and `claimed_at` NULL, so
each person's first Supabase sign-in claims their row and memberships —
no re-invite needed. `password_hash` and `auth_identities` are not
copied; Supabase has them the moment the person signs in there.

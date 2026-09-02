# Pilot dry run — what a second person actually gets

Run 2026-09-02 against a **copy** of `data/pipeline.db` (29 concepts, 38 holds,
5 workflows, all owned by account 1) in an isolated container. Nothing here
touched the live database. Method: `src.accounts invite pilot@example.com
--brand pilot` on the copy, then FastAPI `TestClient` with a forged `zp_session`
cookie for each of Mike (user 2), the pilot (user 3), a signed-in user with
**zero** memberships, and anonymous — every route requested as all four.

The suite is green at **1354 passed, 9 xfailed**. Every finding below is
something that green suite permits.

## The headline

`docs/PILOT.md` says the boundary is `account_id` on every owned row, and that
is true for the eight tables in `db.OWNED_TABLES`. Those eight hold. **The leak
is the tables that were never on the list** — `hold_queue`, `workflows`, and the
in-process job registry — plus the fact that a signed-in user with no membership
at all is not stopped by anything except the routes that happen to take
`auth.current_account_id`.

So the invite is not the risk. **Anyone who signs in with Google — invited or
not — reads Mike's publishing queue and his Director canvases, and can act on
both.**

## Status (2026-09-02, later the same day)

Findings 1-7 are fixed on `claude/pilot-dry-run` -- each has a **Fixed:**
line below. 8 and 9 are not (fix order items 4 and 5; they can follow the
first user). The migration was proved against a copy of the live database
before it touched the tree: 55 holds and 5 canvases claimed by account 1,
integrity and foreign-key checks clean, idempotent on a second init. Every
regression test below was run against the pre-fix tree first and failed
there (`tests/test_tenancy.py`, 5 failed + 7 errored on the old code).

One thing the route test found that this run did not list: three routes --
`POST /api/assets/locations`, `.../shots/{n}/media`, `.../shots/{n}/reference`
-- took `account_id` as a plain **query parameter**, so the caller chose
whose row to write. All three take the dependency now.

## Blocks the invite

### 1. The hold queue is global, and "Post now" takes no owner
`hold_queue` has no `account_id` column (38 rows). `GET /api/holds` returns all
of them to any signed-in user. Proven: as the pilot, hold 38 went `held` →
`rejected`.

`POST /api/holds/{id}/post` (`app/api.py:1998`) is worse — its signature is
`def holds_post(hold_id: int)`, no account dependency of any kind. It looks the
hold up unscoped and calls `autopilot.execute({...}, approve=True,
dry_run=False)`. The only thing between a stranger and a post on Mike's
Instagram is the process-wide autopilot gate (`ZEROPAGE_AUTOPILOT`, credentials,
and `data/autopilot.off`) — three switches about *the installation*, none about
*the caller*. Today the kill-switch file exists, which is the sole reason this
is not already live.

**Fixed:** `hold_queue.account_id` (additive ALTER, backfilled to account 1,
on `db.OWNED_TABLES`); `list_hold`/`get_hold`/`resolve_hold`/`to_hold`/
`evaluator_agreement` take the owner keyword-only with no default; every
`/api/holds*` route declares `Depends(auth.current_account_id)` and answers
404 for someone else's hold, the concept routes' shape. `holds_post` names
its gate in its docstring, and posting gained the per-run approval the render
tools have: `ZEROPAGE_POST_OK=1` (`autopilot.POST_ENV`), checked inside
`_post_dispatch` so nothing publishes around it, reported as mode
`post-unapproved` by `execute` and by the scheduling worker. It is still a
fact about the run, not the caller -- the docstring says so.

### 2. Director canvases are global, and destructible
`workflows` has no `account_id` (5 rows). As the pilot:

```
GET    /api/workflows      -> 200, Mike's canvases by name
PUT    /api/workflows/3    -> 200 {"id":3}          # overwrote it
DELETE /api/workflows/3    -> 200 {"deleted":3}     # gone from the table
```

Workflow 3 was "Midnight Evasion". It is not in the copy any more. Per
`docs/` the node tree is saved per shot *with its outputs*, so this deletes the
record of paid renders, not scratch state.

**Fixed:** `workflows.account_id`, same path; every store function takes the
owner keyword-only; `GET/PUT/DELETE /api/workflows/{id}` and `/run` are 404 for
another account's canvas, the list is the caller's, and `brand` filters inside
the tenant. `DELETE /api/concepts/{id}/graph` -- which took no account at all
-- checks the concept first. Verified on the copy: as account 2, "Midnight
Evasion" reads as missing and its delete changes nothing.

### 3. "Signed in" is not "has access" — except where it is
`auth.current_account_id` does the right thing: no membership → 403. Verified,
`/api/assets` → 403. But it only protects routes that *declare* it. A user with
zero memberships:

```
/api/assets       403   (correct)
/api/holds        200   <- Mike's queue
/api/workflows    200   <- Mike's canvases
/api/jobs         200   <- Mike's running jobs
/api/capabilities 200
```

PILOT.md's "a fresh signup has zero memberships on purpose" describes an
intention the routes do not all implement.

**Fixed:** `test_every_api_route_declares_whose_rows_it_wants` walks the
router and fails on any `/api` route without `Depends(auth.current_account_id)`
unless it is on a two-entry exempt list (`GET /api/capabilities`,
`GET /api/presets` -- installation facts, the same bytes for everyone). It
listed 35 routes on the old tree. `test_signed_in_with_no_membership_is_refused_everywhere`
makes the request the dry run made -- a user with zero memberships -- and gets
403 on every route in this table.

### 4. The job registry is global
`app/jobs.py` is a module-level dict, by design (one process, one worker). It is
also unscoped: the pilot saw a job labelled "Mike's private render" and got 200
from `POST /api/jobs/1/cancel`.

**Fixed:** every job record carries `account_id` from `create`/`start`; all
fifteen `jobs.start` calls pass the route's account (the MCP surface passes the
operator's); `/api/jobs` and the SSE stream filter by it, and the per-job routes
404 for anyone else. Still a dict, still one process.

### 5. Smaller leaks, same cause
`/api/evals/golden` and `/api/evals/runs` return Mike's eval set and run history.
`/api/director/landing` returns his brand block and sample prompt.

**Fixed:** all of them, plus `/api/analytics/accounts`, `/api/retrieve`,
`/api/scout/*`, `/api/scenes/run` and the four `/api/workflows/exec/*`
routes, declare the dependency. The eval tables stay shared (they measure the
store, `db.SHARED_TABLES`), but a user with no membership no longer reads them.

## Breaks on the second user

### 6. The global daily caps really do lock Mike out — measured
Six `runway` rows dated today under account 3, then Mike's cap check:

```
daily ceiling: 6/6 generations used across all accounts today
```

At the shipped defaults the *installation* ceiling equals *one account's*
allowance for all five tools (runway 6/6, veo 6/6, higgsfield 6/6, midjourney
10/10, nano 20/20). The first person to render each day ends the day for
everyone.

**Fixed:** `.env.example` sets all five `*_GLOBAL_DAILY_CAP`s for three people
(per-account cap x 3: 18 / 18 / 18 / 30 / 60) with the arithmetic in the
comment; a test pins each above its per-account cap. The code defaults are
unchanged on purpose -- a one-operator database still behaves as it did.

### 7. Veo still has no spend gate
`runway`, `midjourney` and `higgsfield` each define `SPEND_ENV`. `src/veo.py`
does not — `hasattr(veo, "SPEND_ENV")` is `False`. `veo.estimate_cost(6)` is
**$19.20**, and the cap is the only wall in front of it.

**Fixed:** `veo.SPEND_ENV = "VEO_SPEND_OK"`, `spend_approved()`, checked inside
`generate_video` before the client is built and again at the
`generate_candidates` edge with the priced estimate in the refusal --
runway.py's wiring exactly.

### 8. A pilot's denial steers Mike's night, once, then vanishes
Proven end to end. The pilot denied *their own* concept with the note "never put
the bike indoors". Then:

```
MIKE's run:   pending_corrections() -> ['Denied "Pilot\'s own idea": off-tone — never put the bike indoors']
PILOT's run:  pending_corrections() -> []
```

`corrections` has no account and no brand; `pending_corrections` takes every
unconsumed row and consumes it. This is BACKLOG #11's live bug, now with a
reproduction.

**Not fixed** (fix order item 4). `corrections` is listed in `db.SHARED_TABLES`
with this bug named in its reason, so the schema test passes without anyone
mistaking the listing for a decision.

### 9. The pilot is told they are ANTIHERO
`app/main.py:112` — `active_brand` reads the cookie, validates it against a
hardcoded `BRANDS`, and falls back to `DEFAULT_BRAND`. It never looks at
membership. So the pilot's first screen carries Mike's brand name and accent,
every row they create is labelled `brand="antihero"` (verified: their new
workflow saved that way), the brand pill offers them Mike's two brands, and
`POST /brand/zeropage` returns 303 → `/studio`, which is DEV_TOOLS-only and
404s on a real deployment.

**Not fixed** (fix order item 5). It is also why `rag_documents.project` is
the tenant's account slug and not the brand -- see the part-two commit.

## What holds — don't rebuild these

The concept and asset surface is genuinely tenant-safe. Every one of these,
as the pilot against Mike's concept 121, refused:

```
pick, archive, deny, approve, queue/reject, PUT shots/1/graph, POST shots/1/prompt  -> 404
GET /api/concepts/121 -> 404 ("no such concept")
/api/assets, /api/media, /api/analytics/*, /api/pipeline/concepts -> 200, empty
```

Anonymous is 401 on every `/api` route. A stale cookie (rotated
`SESSION_SECRET`) and a garbage cookie are both a clean 401, never a 500 — so
rotating the secret before invites does what PILOT.md says it does. And
`accounts invite` correctly refused to put the pilot into an account that owns
rows.

## Fix order

1. **`account_id` on `hold_queue` and `workflows`**, migrated and backfilled to
   account 1, with owner predicates on every read, write and delete — the same
   shape as the shipped tenancy work. Give `holds_post` the dependency it never
   had, and give the job registry an owner field.
2. **Make it impossible to reintroduce.** `tests/test_tenancy.py`'s static SQL
   test passes today *because these tables are not in `db.OWNED_TABLES`* — it
   only audits the list. Add them, and add a second test that walks the app's
   route table and fails on any `/api` route whose signature lacks
   `current_account_id` unless it is on an explicit exempt list.
3. **Choose the five global caps** (per-account × people) and add `VEO_SPEND_OK`.
   These are one line each and they are the credit card.
4. **Scope `corrections`.** A lesson is shared — the denial already reaches
   everyone through the `denials` RAG shelf. An instruction is addressed.
5. **`active_brand` off memberships**, so a pilot sees their own brand.

1–3 are what an invite waits on. 4–5 can follow the first user.

**1–3 done, 2026-09-02.** The tables are decided out loud in
`db.SHARED_TABLES`: `channels` stays the installation's (a channel is a
destination bound to env credentials, created only by the seed, so a tenant
with no channel row has no targets), `scheduled_posts` stays the operator's
worker queue until a route can write it, and `corrections` is listed with its
bug named. Everything else without an owner is the shared brain by Mike's
decision, or reached only through an owned row.

## Caveats on this run

Container is Python 3.11 / FastAPI 0.141.1; Mike's venv is Python 3.13 with its
own pins. Nothing above depends on framework behaviour except by inference —
each finding was reproduced by an actual request or an actual query, not read
off the source. The RAG store was unreachable (no Postgres in the container), so
`rag_documents.project` — BACKLOG #11's third point — was **not** exercised
here; it was, against the live store, in the part-two commit that followed.

## Part two — the RAG provenance gap (2026-09-02, same branch)

Tested against the live store this time (`RAG_DATABASE_URL`, 284 chunks), on a
Postgres copy made with `CREATE DATABASE ... TEMPLATE zeropage` before anything
touched the real one.

**What was true:** every one of the 284 chunks had `project = NULL`. The one
write site (the deny handler) set the brand, and no `denials` chunk had ever
been written. No retrieval site passed it.

**Decision, written in `src/rag.py`'s docstring:** `project` is the **tenant**
that taught the row — `accounts.slug_of(account_id)`, "zeropage" for both of
Mike's brands — not the brand. Brand was wrong twice: it is a label inside the
tenant everywhere else, and until finding 9 is fixed a second user's rows carry
Mike's brand name, so keyed by brand a stranger's denial would rank *first* for
Mike. Written now at every learning-shelf ingest (denials, assets, winning /
avoid prompts, proven_results, the gold-standard seed); the craft shelves
(ai_prompting, marketing, cinematography, the manifest) stay NULL on purpose —
nobody's taste, everyone's. Read at every retrieval site as `prefer_project`:
a wider pool by similarity, re-sorted with `PROJECT_BOOST` (0.02, chosen from
a sweep) off the caller's own rows. `project=` remains a hard filter for the
CLI only.

**Measured, same queries, k=5, the four learning shelves** (full output in the
part-two commit message):

- one tenant, before vs after labelling: identical top-5 sets and identical
  order up to exact-score ties on 3/3 queries — Mike's grounding did not move;
- two tenants simulated on the copy (the two `winning_prompts` sources that
  ranked highest for "gearing up ritual" relabelled as a stranger's): as Mike,
  5/5 own in the top 5 and the stranger's rows below his own band; as the
  stranger, their 4 chunks first and Mike's lessons filling the rest, and on
  the two queries they had taught nothing about, Mike's lessons 5/5 — the
  shared brain running forwards.

**Backfilled the live store:** `python -m src.rag label --project zeropage
--domain assets avoid_prompts winning_prompts denials proven_results` → 150
chunks (14 assets, 58 avoid, 78 winning; the other two shelves are empty).
Honest because every learning row was written by the only tenant that has
ever existed; a second run is a no-op, and `--project none --overwrite`
reverses it.

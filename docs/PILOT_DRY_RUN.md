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

### 4. The job registry is global
`app/jobs.py` is a module-level dict, by design (one process, one worker). It is
also unscoped: the pilot saw a job labelled "Mike's private render" and got 200
from `POST /api/jobs/1/cancel`.

### 5. Smaller leaks, same cause
`/api/evals/golden` and `/api/evals/runs` return Mike's eval set and run history.
`/api/director/landing` returns his brand block and sample prompt.

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

### 7. Veo still has no spend gate
`runway`, `midjourney` and `higgsfield` each define `SPEND_ENV`. `src/veo.py`
does not — `hasattr(veo, "SPEND_ENV")` is `False`. `veo.estimate_cost(6)` is
**$19.20**, and the cap is the only wall in front of it.

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

### 9. The pilot is told they are ANTIHERO
`app/main.py:112` — `active_brand` reads the cookie, validates it against a
hardcoded `BRANDS`, and falls back to `DEFAULT_BRAND`. It never looks at
membership. So the pilot's first screen carries Mike's brand name and accent,
every row they create is labelled `brand="antihero"` (verified: their new
workflow saved that way), the brand pill offers them Mike's two brands, and
`POST /brand/zeropage` returns 303 → `/studio`, which is DEV_TOOLS-only and
404s on a real deployment.

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

## Caveats on this run

Container is Python 3.11 / FastAPI 0.141.1; Mike's venv is Python 3.13 with its
own pins. Nothing above depends on framework behaviour except by inference —
each finding was reproduced by an actual request or an actual query, not read
off the source. The RAG store was unreachable (no Postgres in the container), so
`rag_documents.project` — BACKLOG #11's third point — was **not** exercised and
remains untested.

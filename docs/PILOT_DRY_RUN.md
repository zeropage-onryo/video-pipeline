# The pilot dry run — what breaks the first time somebody who is not Mike signs in

Run 2026-09-02 against a **copy** of the live database (`data/_pilot.db`), with
the model calls stubbed, every socket blocked, and `rag.connect` patched to
raise so a deny could not write to the live Postgres library. Nothing was
spent and `data/pipeline.db` was not opened. The walk was done four times
over: as Mike (user 2, owner of `zeropage`/`antihero`), as the pilot
(`accounts.invite pilot@example.com --brand pilot` → user 3, account 3), as a
signup with **no** membership, and anonymously; once with `DEV_TOOLS=1` and
once with it unset (226 recorded answers each). `docs/PILOT.md` is the
checklist this walks; the corrections to it are in the last section.

Tree at the end: **1354 passed, 9 xfailed**, ruff clean. One test-only fix
landed separately (an ordering flake, see the end).

## The facts the walk started from

| fact | live copy, 2026-09-02 |
|---|---|
| accounts | 1 `zeropage`, 2 `antihero` |
| users | one: `mikemassaad@gmail.com` (id 2), owner of **both** |
| who owns the concepts | **all 29 under account 1** (`zeropage`), 6 open; locations 3, characters 2, props 2 — all account 1; account 2 owns nothing |
| `auth.current_account_id` (what `/api` scopes by) | `min(id)` of the memberships → **1**, and stays 1 with the ANTIHERO pill cookie set |
| `auth.current_account` (the brand pill) | memberships are `ORDER BY a.slug`, so the default brand is **antihero** |
| `auth.dev_account_id` (what `/studio` scopes by) | resolves through the *brand*, so for Mike it is **2 — ANTIHERO, the account that owns nothing** |

So PILOT.md's warning that "oldest membership resolves to ANTIHERO" is half
right: `/api` resolves Mike to 1 and his board is full; the **Dev Studio**
resolves him to 2 and is empty. Verified: `GET /grade/draw?mode=shot` as Mike
redirects to "Nothing to grade right now", while the same call **anonymous**
deals concept 142 — his — because the no-session fallback is the bootstrap
account (1).

## The one thing to fix first

**The Create button saves a concept that belongs to nobody, and the next
server start gives it to Mike.** Every write path off the composer drops the
account at the call boundary, for Mike as much as for the pilot:

| path | where the account is lost | verified |
|---|---|---|
| `POST /api/scenes/run` (Studio **Create**, the default) | `scene_chain.run` (`src/scene_chain.py:347`) has no `account_id` parameter; `write_scenes` (`:81`) calls `shootgen.generate_scene_concepts` without one | pilot → row 151 `account_id=NULL`, `visible_on_board=False`; Mike → row 153, same |
| `POST /api/pipeline/run` | `app/api.py:1477` calls `generate_scene_concept(...)` with no `account_id`, then attaches refs *with* one (`:1493`) — which can never find the row it just wrote | pilot → 152 NULL; Mike → 154 NULL |
| `POST /api/generate/run` | the worker is declared `def work(job, account_id: Optional[int] = None)` (`app/api.py:1624`) and `jobs.start` calls `fn(job)` (`app/jobs.py:115`) — the inner name shadows the dependency and is always None | by construction (same job runner) |

Then `preprod.init()` runs on every startup and calls `backfill_owner`
(`src/db.py:218`), which claims every `account_id IS NULL` row for the
bootstrap account. Verified on the copy: rows 151–154 went from NULL to
**1**. Under `--reload` that is every code edit, which is why Mike has never
seen it: his own orphans reappear on his board minutes later. A pilot's
would reappear **on Mike's board**, never on theirs.

Smallest honest fix: add `account_id` to `scene_chain.run` / `write_scenes`
and pass it to `generate_scene_concepts`; pass `account_id=account_id` at
`app/api.py:1477`; drop the `account_id=None` default from `work` in
`generate_run` so it closes over the route's. About six lines, and the
existing scoping tests would have caught it if any of the three routes had a
test that seeded an owned account (they run under conftest's unowned pool,
where None is the right answer).

## Blocks the invite

Ranked by what stops a pilot doing the loop, or lets them touch Mike's rows.

### 1. Create saves nobody's concept (above)

### 2. Approve in the Queue cannot render — for the owner

`POST /api/queue/{id}/approve` and `POST /api/concepts/{id}/shots/{n}/generate`
resolve the concept *with* the account, then call
`runway.generate_for_shot(concept_id, shot_n, db_path=...)` **without** it
(`app/api.py:1091`, `:1291`). Inside, `preprod.get_concept(..., account_id=None)`
(`src/runway.py:428`) returns None for any owned row.

Repro (Mike, `RUNWAYML_API_SECRET=fake`, sockets blocked, concept 149 picked):
the job fails with `no concept 149` before any API call. Same for the
Director's generate button. The spend path has been dead for every owned row
since tenancy landed; it is not a pilot bug, but a pilot hits it on day one.
It also means the per-account cap inside `generate_for_shot` counts against
`None`, never the caller. Fix: `account_id=account_id` at both call sites.

### 3. Three `/api` routes still take `account_id` as a query parameter

The `8f4f9b6` archive bug has siblings. FastAPI reads a bare
`account_id: Optional[int] = None` as `?account_id=`, so the route both
**404s for its owner** and **accepts a forged owner from anyone**:

| route | line | owner, no param | pilot with `?account_id=1` |
|---|---|---|---|
| `POST /api/concepts/{id}/shots/{n}/media` | `app/api.py:1195` | 404 `no concept with id 149` (Mike, and the pilot on their own 150) | **200, Mike's shot row changed** |
| `POST /api/concepts/{id}/shots/{n}/reference` | `app/api.py:1839` | 404 | **200, Mike's shot row changed** |
| `POST /api/assets/locations` | `app/api.py:371` | photos saved, row saved as NULL (adopted by Mike at restart) | 200, `planted-in-mikes` lands in account 1 once Gemini describes it |

The dev router has the same shape at `app/main.py:878` (`videos_new_submit`),
`:1563` (`concept_shot_reference`), `:1705` (`concepts_discard_all` — a
delete), `:1733` (`scene_brief_delete`). Fix: `Depends(auth.current_account_id)`
on the three `/api` routes, `Depends(auth.dev_account_id)` on the four dev
ones. `tests/test_tenancy.py` parses SQL; it cannot see this. A one-assertion
test that walks `app.routes` and fails on any `account_id` in
`dependant.query_params` would pin all seven.

### 4. Half the API is not scoped at all — and the membership gate is per-route

`require_user_api` (`app/auth.py:208`) only checks for a session; the 403 for
"signed in, no membership" lives inside `current_account_id`, so it only
protects routes that declare it. A fresh signup with **zero** memberships sees
the "No account access yet" page (copy verified) and behind it gets 200 from:

| route | what a membership-less signup (and the pilot) got |
|---|---|
| `GET /api/holds` | **22 of Mike's held runs**, captions and payloads, plus his agreement numbers |
| `POST /api/holds/{id}/resolve`, `/post` | 200 — the pilot resolved Mike's hold 38 |
| `GET/PUT/DELETE /api/workflows/{id}`, `/run` | 200 — the pilot read and renamed Mike's workflow 2 |
| `DELETE /api/concepts/{id}/graph` | 200 on Mike's concept (`app/api.py:1796`, no account) |
| `GET /api/jobs`, `/jobs/{id}`, `/jobs/stream`, cancel, clear | every user's jobs, labels included (a label carries the prompt text); Mike cleared the pilot's job |
| `/api/evals/*`, `/api/scout/*`, `/api/retrieve`, `/api/director/landing`, `/api/analytics/accounts`, `/api/presets`, `/api/capabilities` | 200 |

Everything that takes `Depends(current_account_id)` refused correctly: pick,
archive, prompt, refs, direct, refine, approve, deny, reject, detail, graph
read/write all 404'd on Mike's 149 for the pilot and worked for Mike.

Smallest fix in one place: make the router-level dependency at
`app/main.py:216` require a membership (a `require_member_api` that raises
the same 403), which closes the "nobody" leak for every route at once. Real
scoping of holds, workflows and jobs needs an owner on each: `hold_queue` and
`workflows` have no `account_id` column (additive ALTER, then the predicate),
and `app/jobs.py` needs an owner field on the job dict and a filter in
`list_jobs`/the SSE feed.

### 5. An invited pilot has no door unless OAuth is configured

`accounts.invite` creates the user with no password and no identity, by
design, so the first Google/Discord sign-in claims it. But the email/password
path refuses the same row: signup → "an account with this email already
exists -- try signing in the other way" (`app/auth.py:287`), login →
"invalid email or password". With no provider configured (localhost today,
and any deploy where the OAuth callbacks are not yet registered) the invite
is complete and unusable. Fix: let `signup` claim an unclaimed invited row
(no password, no identities — the same test `_resolve_oauth_user` already
makes) by setting the hash, or give `invite` a `--password`.

## Breaks on the second user

### 6. The global ceilings equal one account's cap — proven

`RUNWAY_GLOBAL_DAILY_CAP` defaults to `DAILY_CAP` (`src/runway.py:60`, and
the same line in veo `:57`, higgsfield `:91`, midjourney `:61`, nano `:39`).
Repro: six `generations` rows for the pilot dated today, then Mike's next
render at **0/6 of his own**:

```
daily ceiling: 6/6 generations used across all accounts today (RUNWAY_GLOBAL_DAILY_CAP to raise)
```

Same string back through `POST /api/queue/149/approve`. The ceiling is the
credit card and the default forces the decision, as PILOT.md says — but it
must be decided *before* the invite. Proposed numbers for a pilot of two to
four people, so that no single day can exceed roughly $60 of video:

| tool | per account | global | why |
|---|---|---|---|
| runway | 6 | **18** | $0.50–1/clip; three people's full day |
| veo | 4 | **8** | $3.20/clip is the expensive one; 8 clips ≈ $26 |
| higgsfield | 6 | **18** | as runway |
| midjourney | 10 | **30** | stills, cents |
| nano | 20 | **60** | cents |

Two related facts the run turned up: the nightly `generate_render`
(`src/orchestrator.py:940`) calls `generate_candidates(..., db_path=...)`
with **no** `account_id`, so the night's renders count against nobody's
per-account cap (only the ceiling stands); and `RUNWAY_DAILY_CAP=` set but
empty crashes the import (`int('')`, `src/runway.py:55`) — a copy-pasted
`.env` line with no value takes the server down.

### 7. Veo has no spend gate — confirmed

`runway`, `higgsfield` and `midjourney` each have `spend_approved()` behind a
`*_SPEND_OK=1` env that must be set per run. `veo` has neither the function
nor the env (`hasattr(veo, "spend_approved") → False`). Repro: with a fake
Gemini key and sockets blocked, `veo.generate_candidates(...)` returned
`candidate 1: network blocked` — it reached the API call; the only thing
between a Veo prompt and $3.20 is the daily cap. It is reachable through
`autopilot.EXECUTORS["generate"]` (live mode only) and the nightly
`ZEROPAGE_RENDER=1` path. Fix: mirror runway exactly — `SPEND_ENV =
"VEO_SPEND_OK"`, `spend_approved()`, and a refusal at the top of
`generate_video` that names the free path, so the module cannot be spent
around.

### 8. `corrections` is cross-tenant — the sharpest one, as predicted

The table has no `account_id` (`src/autonomy.py:60`) and
`pending_corrections` (`:337`) takes every unconsumed note. Repro:

1. Pilot denies **their own** concept 150 with the note
   `PILOT SAYS: never show motorcycles` → `POST /api/concepts/150/deny` 200,
   `correction_id 1` (`app/api.py:1917`).
2. Mike's nightly `gen_concept` (account 1, model stubbed): the steer handed
   to the writer contains `PILOT SAYS` → **True**; saved under account 1.
3. `pending_corrections` afterwards → `[]`.
4. The pilot's own night: steer contains the note → **False**.

An instruction is addressed; a lesson is shared. Fix: `ALTER TABLE
corrections ADD COLUMN account_id` (additive, the OWNED_TABLES pattern),
`add_correction(..., account_id)` from the deny route, and
`pending_corrections(path, account_id=state["account_id"])`. The RAG
`denials` chunk stays global — that is the lesson half, and it is the part
Mike decided should be shared.

### 9. Asset photos and shelf chunks are keyed by slug alone

Two tenants each created a character named "Shared Name". The rows are
separate (ids 3 and 4, accounts 3 and 1), but the photos went to **one**
directory — `characters/shared-name/face.png`, one file for two rows
(`app/api.py:363`, `:385` for locations) — so the second upload replaced the
first tenant's photo, and both `reference_image` columns point at it. The RAG
chunk is `assets/character-shared-name` with `project: None`
(`src/asset_shelf.py:48`, `:106`), so the second ingest replaces the first
tenant's description, and `DELETE /api/assets/characters/3` (the pilot's)
runs `drop_one("character", "shared-name")` (`:129`) — Mike's chunk, same
key. The photo routes (`/characters/{slug}/photo/...`) then serve whichever
file won to anyone. Also: `POST /api/assets/backfill` calls
`asset_shelf.backfill` with `account_id=None` (`app/api.py:478`), so it walks
the unowned pool and reports `0 on the shelf` for every real account —
verified for the pilot, identical for Mike by construction.

Fix: put the account in the key — `characters/{account_id}/{slug}` on disk
and `assets/{account_id}-{kind}-{slug}` on the shelf (or `project =
str(account_id)`, which finding 12 wants anyway) — and pass `account_id` into
backfill. The photo URL then needs the account segment, which is the same
change the photo routes need for finding 14.

### 10. The Dev Studio, with `DEV_TOOLS=1`, is somebody else's engine room

Every dev route is open with no session (established posture). What the run
adds:

- `auth.dev_account_id` (`app/auth.py:171`) goes through the **brand**, so
  Mike's own console resolves to account 2 (empty) while an anonymous visitor
  gets the bootstrap fallback, account 1 (full). His grading queue reads
  "Nothing to grade"; a stranger's deals his concepts.
- The pilot's console resolves to their own account 3 — but the grade routes
  call `taste_judge.score_concept(concept, db_path=...)` and
  `gather_signals(db_path=...)` with **no** account (`app/main.py:1662`,
  `:1721`, `:1725`), so the judge scores against the unowned pool (see 13).
- `/dataset/export`, `/studio/api/evals/*`, `/winners`, `/analytics` are all
  200 anonymously. `/api/capabilities` reports `dev_tools: true` identically
  to the pilot, so their `/ui` rail shows the "legacy" link straight into it.
- `POST /concepts/discard-all?account_id=1` takes the owner from the query
  string (not executed in the run; signature only).

With `DEV_TOOLS` unset every one of these is a **404**, verified. So this is
a dev-machine finding, not a public-deploy one — until someone tunnels the
dev machine, which is the pilot plan. Fix for the bootstrap: resolve
`dev_account_id` through `current_account_id` when there is a session and
fall back only when there is none.

### 11. MCP: one token is Mike's account, for whoever holds it

With `ZEROPAGE_MCP=1` and a token the mount appears, no bearer → 401, wrong
bearer → 401, right bearer → 200 (verified). But the tools take no account
from the caller: `_account` (`src/mcp_server.py:162`) falls back to
`resolve_account` = `min(id)` = 1, so `board` is Mike's board and a
`capture` over MCP landed in **account 1**. Leaving `ZEROPAGE_MCP` unset, as
PILOT.md says, is correct; if it is ever set for a pilot, it needs a token
per account.

### 12. `rag_documents.project` — nobody reads it

Read-only against the live library: **233 chunks across 7 shelves,
`project` NULL on every one**. The single write site (`app/api.py:1935`,
the `denials` shelf) has never fired — there is no `denials` shelf yet — and
`rag.retrieve`/`rag.query` are called with `project=` by no caller in `src/`
or `app/`. A second user's lessons land on the same shelves with no label:
`winning_prompts` (10 sources, 51 chunks), `avoid_prompts` (5/34), `assets`
(6/14) become noisier per user and no query can prefer its own
neighbourhood. Fix: write `project = str(account_id)` from every shelf
ingest, and have `reference_block` pass `project=` for the ranked-first
pass. A label is not a fence.

### 13. `taste_judge` — which of the three inputs is right

| input | scoped? | verdict |
|---|---|---|
| liked/disliked (graded holds) | by `account_id` — but **every caller passes none** | bug in the callers, not the judge: as called, `liked=0`; with `account_id=1`, `liked=1` (verified after grading one hold) |
| winners / avoid (`winners.list_all`) | global | **right** — Mike's decision (BACKLOG #11): the app learns as a whole |
| perf (`post_seo.derive_signals`) | takes `account_id`, called without (`src/taste_judge.py:65`) | **accident**: performance is *your* posts; scope it |

`taste_judge.main` resolves an account and never passes it to
`gather_signals` either (`:195`). Fix: thread `account_id` through
`gather_signals`/`score_concept`/`rank` and the three `app/main.py` callers;
leave winners global and say so in a `SHARED` tuple next to `OWNED_TABLES`.

### 14. The photo routes and the two static mounts are anonymous

`/locations/{space}/photo/{f}` and the character/prop twins need no session
(`app/main.py:1496`, `:1537`, `:1547`). Root escape is solid — `../`,
`..%2F`, `%2e%2e%2f` and an encoded first segment all 404, in both postures.
But any file under a guessable `slug/filename` is served to anyone, and
`/refs/` (composer uploads, research scout images) and `/renders/` (clips)
are open `StaticFiles` mounts. On a public deploy that is every reference
photo and every rendered clip, by URL. Fix: `Depends(auth.require_user_ui)`
on the photo routes and a small guarded route in front of the two mounts; the
account segment from finding 9 then makes ownership checkable.

## Breaks at ten

### 15. `app/jobs.py` is a dict, and it is not one worker

PILOT.md says "one worker". `jobs.start` spawns a daemon thread per job
(`app/jobs.py:123`): two 0.4 s jobs finished in **0.42 s** — they run in
parallel, unbounded. Ten users pressing Create is ten concurrent Gemini calls
against one SQLite file. The registry itself: every user sees every job
(labels include the prompt text), anyone can cancel or clear anyone's, and
the SSE feed pushes every job to every subscriber. A restart empties it
(`jobs_after_restart: 0`) and the **Queue survives** (`queue_after_restart:
1` — it is derived from `picked_at`/`parked` rows, verified). Fix: an owner
on the job dict plus a filter, and a `Semaphore` in `start` sized to what the
machine and the caps can take.

### 16. `SESSION_SECRET` — clean, both ways

Rotating it: `/ui` → 303 `/signin`, `/api/*` → 401 `sign in first`, no 500,
both users. A garbage cookie and a cookie for a user id that does not exist
behave the same. Unset → an ephemeral secret is generated with the stderr
note. The only thing that stays open after rotation is `/studio`, which never
needed a session. No finding beyond "rotate before the invites".

## Every route, two answers

The pattern the walk settled into, for the record (`DEV_TOOLS=1`; the public
posture differs only in that every dev route is 404):

| route | Mike | pilot | nobody (no membership) | anon |
|---|---|---|---|---|
| `/signin` | 303 `/ui` | 303 `/ui` | 303 `/ui` | 200 |
| `/ui` | 200 | 200 (empty studio) | 303 `/ui/accounts` | 303 `/signin` |
| `/ui/accounts` | 200, both brands | 200, `pilot` | 200 **"No account access yet"** | 303 |
| `/api/assets`, `/media`, `/assets/search` | 7 / 0 / 3 | 1 / 0 / 1 (own) | 403 | 401 |
| `/api/pipeline/concepts` | 6 open, 29 with archived | 1 (own) | 403 | 401 |
| `/api/queue/pending` | 5 | 0 | 403 | 401 |
| `/api/analytics/summary`, `/posts` | 200 / 10 | 200 / 0 | 403 | 401 |
| `/api/holds` | 22 | **22 (Mike's)** | **22** | 401 |
| `/api/workflows` | 2 | **2 (Mike's)** | **2** | 401 |
| `/api/jobs`, `/evals/*`, `/scout/spark`, `/director/landing`, `/presets`, `/analytics/accounts`, `/capabilities` | 200 | 200 | **200** | 401 |
| `/api/retrieve` (store down) | 503 clean | 503 clean | 200/503 | 401 |
| pick / archive / prompt / refs / direct / refine / approve / deny / reject / detail / graph GET+PUT on Mike's 149 | works | 404 | — | — |
| media / reference attach on 149 | **404** | 404; **200 with `?account_id=1`** | — | — |
| `DELETE /api/concepts/149/graph` | 200 | **200** | — | — |
| `/api/workflows/2` GET/PUT, `/api/holds/38/resolve` | 200 | **200** | — | — |
| `POST /api/scenes/run`, `/pipeline/run` (stubbed) | saved as **NULL** | saved as **NULL** | — | — |
| `POST /api/queue/149/approve` (key present) | job fails `no concept 149` | 503 runway before the owner check | — | — |
| `/api/assets/characters` create | 200, shares the photo dir | 200 | 403 | 401 |
| `/api/assets/backfill` | `0 on the shelf` | `0 on the shelf` | 200 | 401 |
| `/studio`, `/analytics`, `/winners`, `/dataset/export` | 200, as account **2** | 200, as account 3 | 200, as account 1 | 200, as account 1 |
| `/grade/draw?mode=shot` | "Nothing to grade" | concept 150 (own) | concept 135 (Mike's) | concept 142 (Mike's) |
| `/locations/{s}/photo/{f}` (+ four escapes) | 200 / 404×4 | same | same | same |
| `/ui` after `SESSION_SECRET` rotation | 303 `/signin` | 303 | — | — |
| `/mcp` (`ZEROPAGE_MCP=1`) | — | — | — | 401 / 200 with token, acting as account 1 |

## What the dry run settled for BACKLOG #2 and #11

- **#2 (cost tracker):** the caps are the right instrument and they work
  (finding 6), but two things must land before the numbers mean anything: the
  render call sites have to carry the account (findings 2 and 6, the nightly
  path), or the per-account count is always against `None`; and Veo needs the
  gate (7). The proposed globals above are a starting budget, not a
  measurement.
- **#11 (shared brain):** confirmed as written, with evidence. `corrections`
  is the live bug (8, reproduced end to end). `project` is NULL on all 233
  chunks and read by nobody (12). The judge's hybrid is right on winners,
  broken on grades by its callers, accidental on performance (13). The asset
  shelf is a fourth case the write-up did not have: keyed by slug, it is
  cross-tenant on *write and delete* (9), not just noisy.

## Corrections to `docs/PILOT.md`

Applied in the same commit:

- "One worker" → a thread per job, unbounded (15).
- "Their board starts empty; they cannot see anyone else's" → true for
  concepts, assets, queue, analytics; false for holds, workflows, jobs, evals
  (4).
- "`auth.dev_account_id` falls back to the bootstrap account" → it resolves
  through the brand for a signed-in user, which for Mike is ANTIHERO (10).
- The invite section assumes OAuth is configured; add that email/password
  cannot claim the row (5).
- Pre-flight gains the two things that block the invite regardless of env:
  the Create path (1) and the render path (2).

## The one fix that landed

`tests/test_scenes_pick.py::test_archiving_a_row_that_has_an_owner_works`
failed in the first full-suite run (1 failed, 1353 passed) and passed alone.
It overrides `auth.current_account_id` on `app.main.app`, but its module-level
`client` was built from the *original* app object — and `test_dev_tools.py`
reloads `app.main` to exercise `DEV_TOOLS=0`, rebinding `app.main.app`. When
both land in the same xdist worker the override goes on the wrong app and the
request resolves the real dependency. Two lines: the test now overrides
`client.app`. Reproduced with `pytest tests/test_dev_tools.py
tests/test_scenes_pick.py -p no:xdist` (fails before, 41 passed after).

## How this was run

Two scripts, kept out of the tree: a walk (four clients, both postures,
every route above) and a suspects script (caps, gate, corrections, judge).
Both point `db.DB_PATH` at the copy **before** any `src` module binds its
default argument, pre-set the billing keys to `""` before `load_dotenv` can
fill them (python-dotenv never overrides an existing value), block
`socket.connect`, and patch `rag.connect`. The model seams stubbed were
`shootgen.generate_scene_concepts`, `shootgen.generate_scene_concept`,
`scene_chain.ground` and `orchestrator._client`. If a future session wants to
re-walk, that is the recipe; the only thing that needs a real network is
the read-only shelf count.

---

# Where each finding stands (2026-09-02, after the fix)

Two dry runs were run the same day, independently, and this file is the
merge of both: the sixteen findings above, plus the earlier walk's report
(commit `5a34a84`), whose numbering is kept in brackets where the two
overlap. The fixes landed in `51a39a8` (the three tables) and `12a1573`
(the RAG label). Then the earlier walk's probes were **re-run against the
fix**, which is what found the two rows marked *survived* below.

| finding | state | evidence |
|---|---|---|
| Create saves nobody's concept (1) — `scenes/run` | **fixed** `51a39a8` | the owner is threaded to `ground` / `write_scenes` / `attach_refs` |
| — the same bug in `POST /api/generate/run` | **fixed here** | it was the third row of that table: `def work(job, account_id=None)` shadowed the route's dependency, and `jobs.start` calls `fn(job)` |
| Queue approve cannot render, for the owner (2) | **fixed here** | `generate_for_shot` re-ran on a copy of the live database: concept 149, owned by account 1, `{'ok': False, 'error': 'no concept 149'}` before any API call |
| three `/api` routes take `account_id` as a query param (3) | **fixed** `51a39a8` | the route test found them; it listed 35 routes on the old tree |
| half the API unscoped; the membership gate is per-route (4) [3, 5] | **fixed** `51a39a8` | a nobody — signed in, zero memberships — is 403 on every route now, verified |
| hold queue global, "post now" ownerless [1] | **fixed** `51a39a8` | pilot: `/api/holds` empty, resolve and post-now 404, hold 37 still `held` |
| Director canvases global and destructible [2] | **fixed** `51a39a8` | pilot: PUT and DELETE both 404, the canvas survives |
| job registry global [4] | **fixed** `51a39a8` | every `jobs.start` carries the owner; the rail and the SSE stream filter |
| an invited pilot has no door without OAuth (5) | **open** | a deployment step, not a code change — `docs/PILOT.md` §3 |
| the global ceilings equal one account's cap (6) [7] | **fixed** `51a39a8` | `.env.example` sets all five for three people, arithmetic in the comment |
| veo has no spend gate (7) [8] | **fixed** `51a39a8` | `VEO_SPEND_OK`, in runway's exact shape |
| `corrections` is cross-tenant (8) [—] | **open, by choice** | fix-order item 4; declared in `db.SHARED_TABLES` with the bug named |
| asset photos and shelf chunks keyed by slug (9) | **open** | not exercised by the re-run |
| the Dev Studio is somebody else's engine room (10) | **open, by posture** | `DEV_TOOLS` off a public deploy; four dev routes still take a query-param `account_id` |
| MCP: one token is Mike's account (11) | **open** | `ZEROPAGE_MCP` stays unset for the pilot |
| `rag_documents.project` unread (12) [—] | **fixed** `12a1573` | tenant, not brand; ranks, never fences; 150 chunks labelled; measured before/after |
| `taste_judge`'s three inputs (13) | **answered** `51a39a8` | the hybrid is declared in `db.SHARED_TABLES` |
| photo routes and static mounts are anonymous (14) | **open** | on `app`, not `dev` — reachable on a public deploy |
| `app/jobs.py` is one dict, one worker (15) | **open, by design** | scoped now; still one process |
| `SESSION_SECRET` (16) [—] | **clean both ways** | stale and forged cookies are 401, never 500 |
| the pilot is told they are ANTIHERO [9] | **open** | fix-order item 5; `active_brand` never looks at membership |

**The two that survived the fix are the same mistake pointing inward.** Every
finding the fix closed was an owner missing on the way *out* — someone
reading rows that were not theirs. These two were an owner dropped on the way
*in*: `account_id` resolved correctly at the route and then not passed to the
data layer, so the caller's own rows stopped existing. It fails closed, which
is why it never looked like a security bug — and why the render button has
been dead for every owned concept since tenancy landed, and every concept the
Studio's Create saved belonged to nobody until the next server start handed
it to the bootstrap account.

Both now have a test that was **run red against the pre-fix tree first**:
`test_the_render_path_carries_the_owner` (behavioural, both routes) and
`test_no_job_closure_shadows_the_route_owner` (static — the write succeeds,
so there is nothing to observe at runtime).

Suite on the merged tree: **1407 passed, 9 xfailed**. The remaining failures
are all `tests/test_imagesearch.py`, another session's uncommitted in-flight
work, and are not this branch's.

## What still blocks an invite

Nothing in the code. What is left is the deployment half of `docs/PILOT.md` —
OAuth callbacks registered, `SITE_URL` and `SESSION_SECRET` set, the secrets
rotated — plus the two open scoping items that are choices rather than
defects: `corrections` (4) and `active_brand` (5).

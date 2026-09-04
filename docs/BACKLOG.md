# Zero Page pipeline — backlog / notes

Parked ideas and next builds. Nothing here is in progress.

## 1. UI readability pass  (parked — hold until Mike says go)
Make the app simpler and easier to read. Same density problem on both pages:
dense monospace prompt blocks, warnings, shot lists, and multiple button
sets stacked on one card.

- **/holds** — three different button groups blur together. Separate the
  three jobs clearly: (a) grade the evaluator (Would-have-posted / Glad-it-held),
  (b) prompt feedback (Worked / Didn't work → RAG), (c) Post now. Plain-language
  labels, lighter typography, skimmable prompt boxes.
- **/concepts** — same treatment: warnings, shot list, AI-prompt boxes are
  all one wall of mono text; group and lighten.
- Consider applying the lighter treatment across the whole `.sk` skin so it
  stays consistent.

## 3. Remove the location limit  (largely shipped — Mike's ask)
Right now generation is grounded ONLY in described locations, and there's
just one on file (the studio-bedroom), so every prompt is stuck in that
room. Mike wants no location limit — variety, not one room.

Why the limit exists: grounding in real, described rooms was built for
*physical* shoots (you can only film where you actually are). But for pure
AI video (Runway) that constraint doesn't apply — the model invents the
scene, so it shouldn't be capped to one real room.

STATUS (2026-08-12): shipped. The concept + shot-list prompts and
`validate_concept` now let AI shots invent or extend any location (a short
scene label + a full prompt in the shot), while camera shots stay grounded to
a real room — concepts are no longer trapped in one space. The remaining
option (seed a large real+imagined location library for even more range) is
optional, not required.

## 4. Automatic analytics pull — Facebook + Instagram  (partly shipped — Mike's ask)
Mike wants post analytics to pull **automatically** on a schedule and feed
the concept loop — no manual refresh — starting with Facebook and Instagram.

Context (verified 2026-08-12): the analytics → RAG → concepts loop already
exists. `youtube.py` / `instagram.py` fetch post metrics; `promote_winners.py`
takes the top performers (with the win/loss patterns) and ingests them into
the `proven_results` RAG shelf; the concept generator already grounds on it
(`IDEATION_DOMAINS` includes `proven_results`).

STATUS (2026-08-12): YouTube + Instagram half shipped. `src/refresh_metrics.py`
sweeps every posted video per platform (never-raises) and then runs
`promote_winners --auto`; it's wired as step 1 of `run_morning_prompts.sh`, so
the nightly job now does refresh metrics → promote winners → generate grounded
concepts, with no manual step. Still open:

- **Facebook** — no module yet. Needs a `facebook.py` wired into the same
  metrics/RAG loop (behind the `refresh_metrics` stub already in place), plus a
  Page access token from the *existing* Meta app (`FB_PAGE_ID` +
  `FB_PAGE_ACCESS_TOKEN`, scopes `pages_read_engagement` + `read_insights`).
- **Instagram token refresh** — the long-lived token expires ~60 days and
  auto-refresh isn't built, so the automation goes silently stale without it.
- **TikTok** — separate, gated follow-up (developer-app approval required).

## 5. Taste + performance judge on the concept generator  (SHIPPED — verified 2026-08-27)
An LLM judge that scores each new concept against Michael's OWN history — his
approve/reject grades on `/holds`, his hand-marked winners (`winners.py`
worked/didn't-work), and his top performers by analytics — to predict "Michael
will like this" and "this will travel," and rank / filter the slate on it.

Why it's not already there: the existing judges grade QUALITY against fixed
rubrics, not taste or performance. `score_prompts` (the prompt gate) asks "is
this prompt renderable"; `JUDGE=1` (the concept evaluator) critiques craft
against a rubric. Neither reads Michael's preferences or his numbers. Today
taste is captured (approve/reject → `evaluator_agreement`, winners shelf,
corrections) and performance is captured (metrics → `post_seo` signals →
`proven_results`), but only as *passive grounding* — nothing scores a fresh
concept for predicted fit or reach.

Build: a judge step that, per concept, pulls his recent approve/reject
patterns + `proven_results` winners + `post_seo` win/loss signals and returns a
taste-fit + predicted-performance score with reasons citing the evidence. Use
it to rank the generated slate (and optionally filter or retry the weakest), so
every slate self-filters toward what he likes and what works. All inputs exist;
this wires them into an active scorer. Arguably the highest-leverage item here.

STATUS (verified 2026-08-27): **shipped.** `src/taste_judge.py` exists and does
exactly this — `gather_signals` pulls graded concepts, `winners.list_all` and
`post_seo.derive_signals`; `score_concept` is the isolated LLM call; it's wired
at `app/main.py:1622` and the verdict is stored so `preprod` can rank on it. It
also grew a sibling the backlog never asked for: `src/uncanny_judge.py`, the
on-brand gate, which scores against a FIXED rubric precisely *because*
taste_judge needs history and therefore can't work on day one. taste_judge
degrades to a neutral 5.0; uncanny_judge fails closed.

## 6. Midjourney image → R2 → Zero Page one-tap queue  (to build — Mike's ask)
Zero Page auto-posts Midjourney image posts, semi-automatically with one-tap
approval (Mike's chosen shape: keep Midjourney, queue not fully-auto).
Midjourney has no API, so Michael generates the still in the MJ web app; the
pipeline handles both sides.

What already exists: the pipeline drafts the MJ still prompt (orchestrator
`structure_prompt._midjourney_still`) + caption; `instagram.post_image`
publishes images (JPEG only) through the autopilot gate; `storage.upload_file`
hosts to R2 (configured, R2_* set); `/post-image` already posts an image URL
live. So a manual path works today — the delta is the queue.

Build (small): (a) an upload-and-queue surface — drop the MJ image in →
ensure/convert JPEG → `storage.upload_file` to R2 → create a *held* row on the
`zeropage` channel with `image_url` + the drafted caption; (b) teach
`holds_post` to build an image post action (`image_url`) instead of only video;
(c) a "Queue for approval" button on `/post-image`. Result: generate in MJ →
upload → one-tap approve on `/holds` → posts. Channel stays `queue` (one-tap),
not `auto`. JPEG-only (Meta rejects PNG/HEIC) — convert on upload.

## 7. Brand switcher — ANTIHERO ⇄ Zero Page, full separation  (SHIPPED — verified 2026-08-27)
A brand switcher in the studio so the two brands never get confused and
Michael can flip between them. Full separation (his choice): the active brand
drives concept generation, and the holds/queue + library + analytics views
filter to that brand's channel, with a distinct label + accent per brand.

Context: the code is already separate (brand + channel params, separate
channels, sharpened brand blocks — ANTIHERO = Michael-as-star personal brand;
Zero Page = viral auto-posting engine). The confusion is UI-only: the studio
header is hardcoded "Zero Page Films" while generation defaults to `antihero`,
and there's no visible switcher.

Build: active-brand cookie + `active_brand(request)` helper + a `/brand` route
(set + redirect via `safe_next`); register Jinja globals so the switcher +
accent render on every page without editing each route's context; generation
defaults to the active brand (`/studio/assist`, `/concepts/generate`); `/holds`
filtered to the active brand's channel; add a `brand` column to `videos`
(migration + backfill) so analytics/library filter by brand; studio-header
switcher with per-brand label + accent. Note: the RAG reference library is
domain-scoped, not brand-scoped, so it does not filter by brand meaningfully.

STATUS (verified 2026-08-27): **shipped**, essentially as specced.
`active_brand(request)` is at `app/main.py:112`, registered as a Jinja global on
the next line so the switcher renders everywhere without touching each route's
context, and `POST /brand/{name}` (with `safe_next`) is at line 330. Generation
tags to the active brand. The one thing that moved past the spec: inspiration
lanes ARE now brand-scoped (`src/inspiration.py`, "so grounding never leaks
across brands") — the note above about the library being domain-only still
holds for the RAG shelves, but brand isolation exists at the inspiration layer.

---

# Open

Everything above this line is shipped or parked. Below is what's actually next.

## 8. Account tenancy — the launch blocker  (SHIPPED 2026-08-31 on `claude/account-tenancy` — see below for the one decision left)
No owned table has an `account_id`. `list_concepts` is
`SELECT * FROM shoot_concepts ORDER BY id DESC LIMIT ?` — no owner predicate —
and `get_concept` is `WHERE id = ?` with no ownership check, against sequential
integer ids. So a second signed-in user would see every concept anyone has ever
generated, and could fetch any of them by guessing.

The render caps compound it: `SELECT COUNT(*) FROM generations WHERE tool =
'runway' AND created_at >= ?` counts globally, not per account. Default is 6/day.
The first pilot user to log in each morning exhausts everyone's budget.

Why it isn't already there: sign-in was built before there was anyone to sign
in, so `accounts.py` / `auth.py` / capability gating landed as a complete
front half with no back half. Nothing broke, because there has only ever been
one user.

This is the gate on showing the product to a single other person — ahead of
anything else in this file, including item 9.

**What shipped** (`5f66f59` schema, `b7216d8` reads, `3ddf55a` writes + caps +
entry points). `account_id` on all 8 owned tables, backfilled; every read,
write, mutate and delete carries an owner; per-account render caps plus a
global ceiling; `tests/test_tenancy.py` (35 tests) including a static one that
parses every SQL literal in `src/`, `app/` and `ops/` and fails on any
statement reaching an owned table without an owner predicate.

**The boundary question, answered differently from the framing above.** The
premise that `brand` is "the only scoping dimension" was already out of date:
`accounts` IS the brand table — `seed()` creates `zeropage` and `antihero`, and
`auth.current_account()` picks between them off the brand cookie. So
`account_id` became the scoping key and `brand` stayed a label.

But that has a sting the plan did not see, and only running the migration
against a copy of the live database showed it: if the data is scoped by
`current_account`, clicking the ANTIHERO pill scopes every query to account 2,
which the backfill gave nothing — an empty board on a database with eleven
concepts. The fix is that `auth.current_account_id` resolves the **tenant** (the
user's oldest membership) while `current_account` goes on resolving the
**brand** for the pill.

**Still open, and it is the real version of the original question:** `accounts`
is now doing double duty as tenant table and brand table, with "oldest
membership" picking the tenant. That holds for one operator with two brands, and
for a pilot user with one account. It stops holding the day one person belongs
to two different operators — which is when `accounts` has to split into
`tenants` and `brands` properly. Worth deciding before the pilot grows past
people who each have exactly one.

The rest of section 6 of the task doc (deploy, rotate secrets, invite 5–10 by
manual INSERT) is untouched and still next.

## 9. LangGraph under the Studio's render path  (ANSWERED 2026-08-29 — it belonged in the graph that already exists)
The question was whether to put the Studio's *request* path on LangGraph, with a
checkpointer and an `interrupt()` for the keyframe approval. The answer turned out to be
that the request path should get SHORTER, not longer — Create writes concepts and stops on
the board — and that the full run belongs to the **automation**, where
`src/orchestrator.py`'s StateGraph already lives.

What shipped: `src/scene_chain.py` holds the stages as plain functions (`ground`,
`write_scenes`, `persist_prompt`, `keyframe_scene`, `park_scene`), and the orchestrator
gained a `keyframe` node between the prompt gate and the dry render. The nightly run now
persists the scored prompt onto the shot, renders a still, and parks the scene in the Queue
— instead of ending every night with "no usable clips (render is a dry-run stub)". That is
the first time the LangGraph in this repo has been load-bearing: its output is now
something you can look at and approve.

Why the stages are functions rather than a second graph, and why no checkpointer:

- Called from a StateGraph node and from a FastAPI job, a stage is the same function. A
  second graph for the request path would be ceremony — that path is now three stages with
  no branching at all.
- `interrupt()` spanning the human wait resumes against a concept that may have been edited
  in Director since — the staleness problem `_shot_seed_hash` already solves. The Queue is
  derived from rows and already survives a restart, so a checkpointer would be a second,
  quieter answer to the same question, free to disagree with the first.
- A `SqliteSaver` on `data/pipeline.db` runs `PRAGMA journal_mode=WAL`, and the backups
  here are plain file copies — under WAL, copying `pipeline.db` alone silently omits the
  newest committed transactions. If a checkpointer is ever added it goes in
  `data/checkpoints.db`.

Taken from the plan on the way past: the node functions came out of
`app/workflow_runner.py` into `src/imagery.py` so both executors share one implementation
(`enhance`, `fetch_image_bytes`, `image_bytes_for_gemini`, `upright`), and
`runway.generate_for_shot` now resolves a non-http keyframe instead of silently dropping
the anchor.

**Still open, and still worth doing:** the tracing. `langsmith` is already a dependency and
`.env` already sets `LANGSMITH_TRACING=true`, but the graph is only half the work now —
`@traceable` on `scene_chain`'s stages would cover the Director and request paths too, for
no new dependency. Also still true: `langgraph` is unpinned in `requirements.txt`, and that
is a library that moves.

## 10. Whose credits do pilot users spend? — BYOK, and the positioning behind it  (to decide, then maybe build — Mike's ask, 2026-09-01)
Full write-up: `docs/tasks/task-byok-and-pilot-credits.md`. Two questions asked
back to back after tenancy shipped — *"if I'm having other users wouldn't they
use their own credits / apis"* and *"how can i make it like higgsfield or
runway"* — which turn out to be the same question from both ends.

**The finding.** Tenancy scoped the data and did nothing to the spend. Every API
key is still a process-wide `os.environ.get()` made at call time, with no
per-account storage anywhere: five functions for the billed renders
(`runway._make_client`, `veo._make_client`, `midjourney._request`,
`higgsfield._credentials`, `nano_banana._client`) and ~20 more inline sites for
the cheap Gemini path. So **every render a pilot user makes bills Mike's cards**,
and the per-account cap is the only wall.

**BYOK is now small, because tenancy shipped.** `account_id` is already threaded
through every render path, so the work is an encrypted `account_keys` table, an
`accounts.key_for(account_id, provider)` resolver that falls back to the
environment when there is no row, five call-site swaps, and fixing the two
`_safe_error` redactors to scrub the key that was *used* rather than the one in
the environment. The real cost is encryption at rest (backups are plain file
copies, so a plaintext key column puts other people's credentials in them) and
onboarding friction.

**Recommended shape:** split by cost, not by principle. Mike's keys pay for the
cheap high-frequency steps (concepts, judges, scout, RAG, nano stills — cents,
and they are what builds the taste loop); the user's key pays for the expensive
renders. Veo is $3.20/clip against runway's $0.25 and midjourney's $0.27, and at
the shipped defaults one account's theoretical daily max is ~$26 with veo ~74% of
it.

**What the providers actually offer (checked 2026-09-02).** Three of the four
are bearer keys with no delegation, which shapes the whole connector story:

| provider | auth | OAuth for third-party apps? |
|---|---|---|
| Runway | API key, **organization-scoped**, displayed once | no |
| Higgsfield | key id + secret | no |
| Veo | Gemini Developer API = key; **Vertex AI = Google Cloud IAM** | **yes, via Vertex** |
| Midjourney | no official API exists | n/a |

So onboarding is "paste your API key" for two of them, not "connect your
account" -- a bigger trust ask, and users feel it. A Runway key hands over the
whole organization's API access unscoped, and Runway's own docs warn that
removing a user does not revoke their key: revocation is manual and on the
tenant's side, which makes blast-radius limiting Mike's job. The per-account
`DAILY_CAP` is already exactly that instrument.

**Midjourney breaks the model outright.** With no official API, the AceDataCloud
route means tenants are not handing over *their* credentials -- Mike is reselling
his own access and carrying the cost. "One key per tenant across all platforms"
has an exception, and it is the one where he pays. Decide it deliberately.

Veo is the only place a real "Connect your Google account" button is possible,
and only by moving off the Gemini Developer API onto Vertex AI. Not a pilot-week
change, but it is the one provider where the good version exists.

**Two things that are bugs regardless of the BYOK decision:**
- Every `*_GLOBAL_DAILY_CAP` defaults to `str(DAILY_CAP)`, so the *installation*
  ceiling equals *one account's* allowance — the second pilot user gets nothing
  once the first has used the day. Numbers still unchosen from the last session.
- ~~**Veo has no `SPEND_OK` gate.**~~ FIXED 2026-09-02 (#12): `VEO_SPEND_OK`,
  checked inside `generate_video` so nothing can spend around it. Six clips at
  $3.20 is $19.20 that used to leave on a dry run while the cheaper tools all
  stopped and asked.

**The caveat, and it is the real answer to the second question.** Higgsfield and
Runway are model companies; reselling their inference is their business, not a
position this repo can win from. What is defensible here is the pipeline with
taste in it — scout's real references, `taste_judge` scored on Mike's own graded
history, `uncanny_judge`, `winning_prompts`, pick/shoot rate, the nightly
orchestrator — a system whose tenth run beats its first because it learned the
user. The binding constraint is distribution, not architecture: none of section 3
of the task doc gets a single user. If the next session has to choose, the demo
in front of ten people beats BYOK, and BYOK gets built the week someone asks.

**STATUS UPDATE (2026-09-04) — BYOK is now half-shipped, discovered mid-session.**
`src/account_keys.py` (the encrypted `account_keys` table + `key_for()` resolver
this section specced) already existed and was already wired into
`runway._make_client()` before today — the write-up above was stale on that
point. Veo and Higgsfield were not: `veo._make_client()` took no `account_id`
at all, and `higgsfield._credentials()`/`_request()`/`_submit_and_wait()` read
`os.environ` directly. Wired both today, mirroring runway's exact shape
(`_make_client`/`_credentials` resolve via `account_keys.key_for()` first, env
fallback unchanged) — `has_key(account_id)` added to `veo.py` (was missing
entirely). Midjourney and nano_banana/Gemini deliberately left untouched: this
section's own "recommended shape" already decided Mike's keys pay for the cheap
high-frequency steps and Midjourney's no-API resale case, so wiring those would
have contradicted the decision already on record here.

Wiring it in surfaced three real, independent bugs in `account_keys.py` itself
— it had never actually been exercised end-to-end before (no
`tests/test_account_keys.py` exists):
1. `PROVIDER_ENV_FALLBACK`'s env-name fallback was a flat tuple zipped
   positionally against `PROVIDER_FIELDS`. Fine for a single-field provider,
   silently broken for higgsfield's two fields with four candidate names
   (`HIGGSFIELD_*` + legacy `HF_*`) — `key_for()` returned `None` even with
   the primary env vars set, because `len(fields) != len(env_names)`. Fixed:
   `PROVIDER_ENV_FALLBACK` now groups candidate names *per field* and
   `key_for()` resolves each field independently.
2. `account_keys.init()` took a live `sqlite3.Connection`, the only schema
   module in the repo that doesn't take `(path)` and open its own connection
   — broke `tests/test_tenancy_routes.py`'s generic schema-module discovery
   the moment `account_keys.py` (which has a `CREATE TABLE`) was picked up by
   it. Renamed the connection-level function to `_init_schema(conn)`; `init()`
   now takes `path` like every other module.
3. `account_keys` itself was never added to `db.OWNED_TABLES` — added, with
   its own comment; `tests/test_tenancy.py`'s fixture updated to init it
   alongside the other owned-table modules.

Verified: full suite (cloud copy, per [[verifying]]) — 1460 passed, 9 xfailed,
zero regressions from any of the above. Ten remaining failures are pre-existing
and unrelated (`test_imagesearch.py`, `test_scout_separation.py`, one flaky
`test_scenes_pick.py` order-dependency, and two `test_runway.py` tests whose
mocks predate runway's own earlier BYOK wiring and were never updated — not
today's changes, worth a follow-up pass).

Still open from the original write-up: the two acknowledged bugs above
(`*_GLOBAL_DAILY_CAP` defaults, both fixed now — Veo's SPEND_OK was #12; the
cap-sizing decision itself is still unmade), encryption-at-rest operational
concerns (`ACCOUNT_KEYS_SECRET` handling, backup exposure), and no UI yet for a
user to actually enter a key (`account_keys` CLI only). The distribution
argument above still holds — this was worth finishing once found half-done,
not a signal to prioritize the rest of BYOK yet.

## 2. Cost-efficiency tracker  (NEXT — scoped 2026-09-01, not started)
"Build a tracker to make cost efficiency issues visible."

Full write-up: `docs/tasks/task-cost-tracker.md` — a 4–5 hour block. The two
findings that shape it: `tool_scoreboard` and `attempts_to_keeper` already
compute cost-per-keeper and are surfaced nowhere, and `usage_metadata` appears
zero times in the repo, so no LLM call has ever been costed. 42 of the 46 Gemini
call sites funnel through `gemini_utils.generate_with_retry`, which is where the
meter goes. Also carries the two acknowledged bugs from #10 (the five
`*_GLOBAL_DAILY_CAP` defaults, and veo's missing `SPEND_OK`), because this is
what produces the numbers needed to choose them.

Goal: surface where the pipeline spends money and where it wastes it, so
inefficiency is visible instead of hidden.

Cost sources to instrument:
- **Gemini calls per run** — concept gen, Midjourney still gen, prompt-gate
  judge, CRAG grading, caption. Token cost per stage → which stage is the
  token hog.
- **Render credits** — Runway/Veo per clip (when the adapter's wired).
  `veo.estimate_cost` already exists; genlog already logs attempts.
- **Attempts-to-keeper** — from `generative.py` (attempts_to_keeper): $ per
  *usable* clip is the real efficiency number. A prompt that lands in 2 tries
  beats one that lands in 6.
- **Held vs posted ratio** — runs generated that never ship = wasted spend.

Surface as: a `/costs` page (or a Scoreboard panel) — per-run cost, cost per
kept clip, most expensive stage, and flags for prompts/stages that burn
above a threshold. Tie into the prompt-gate agreement so "credits that would
have been wasted" is a headline number (autonomy.prompt_gate_agreement already
tracks passed-but-rejected = would-have-burned).

**What the pilot dry run settled (2026-09-02, `docs/PILOT_DRY_RUN.md`):** the caps
work — six pilot renders refused Mike at 0/6 of his own, exactly as predicted —
but two things must land before any cost number is real: the Queue approve, the
Director generate and the nightly `generate_render` all call the connector
without `account_id`, so the per-account count is always against `None` (and
approve fails with `no concept N` for every owned row); and Veo has no spend
gate at all. Starting globals proposed there: runway 18, veo 8, higgsfield 18,
midjourney 30, nano 60.
## 12. The tenancy gap the dry run found  (SHIPPED 2026-09-02 -- one route left, blocked on #11)
`docs/PILOT_DRY_RUN.md`. `hold_queue` and `workflows` had no `account_id`, and
`holds_post` takes no account dependency at all -- so any signed-in user, with
or without a membership, read Mike's hold queue and Director canvases, could
reject a hold, delete a canvas, and could fire "post now" against the autopilot
gate. The concept and asset surface is clean; this was the tables tenancy never
listed. **This is the gate on the pilot, ahead of the cost tracker.** It also
measured #2's two bugs (the global caps, veo's missing SPEND_OK) and reproduced
#11's `corrections` bug end to end.

### Done (the half that does not touch app/api.py)
- **`hold_queue` and `workflows` are in `db.OWNED_TABLES`**, with the column
  added and every store function taking an owner: `autonomy.to_hold` /
  `list_hold` / `resolve_hold` (now returns False rather than raising, so a
  caller 404s on somebody else's hold) / `posts_today` / `evaluator_agreement`,
  and `workflows.create` / `update` / `delete` / `list` / `get` plus the
  concept-keyed canvas path (`save_shot_graph` / `get_shot_graph` /
  `delete_shot_graphs`).
- **The backfill is deliberately NOT run yet.** Claiming the existing rows for
  the bootstrap account while the routes still ask with no account would empty
  Mike's own queue and canvas list. The rows stay NULL -- which is what "nobody
  has said who owns them" honestly looks like -- and one word in each `init()`
  (`add_account_column` -> `own_table`) finishes it, in the same commit that
  converts the routes.
- **`app/jobs.py` carries an owner** (`_account_id`, underscore-prefixed so it
  never reaches the wire), matched in the three places that face a caller: the
  list, the per-job lookup, and the SSE fan-out.
- **`VEO_SPEND_OK`.** Veo was the one generator that spent without being asked:
  six clips at $3.20 is $19.20 leaving on a dry run while the cheaper tools all
  stopped at the gate. Same shape as runway/midjourney/higgsfield.
- **`.env.example`** documents all five `*_GLOBAL_DAILY_CAP` values and what one
  account can spend in a day at the defaults (~$25.80).
- **Two guards, in `tests/test_tenancy_routes.py`**, because the failure here
  was omission and no behavioural test can see an omission:
  - every table in a freshly built database must appear in exactly one of
    `OWNED_TABLES` / `SHARED_TABLES` / `PENDING_OWNERSHIP` / `INFRA_TABLES`;
  - every `/api` route must declare `current_account_id` or be listed with a
    reason -- and `PENDING_SCOPE` in that file is the exact remaining ledger.
  The old static SQL scan in `tests/test_tenancy.py` now builds its regex from
  `db.OWNED_TABLES` instead of repeating it, which is why it never saw these
  two tables: they were not in the list, so no query against them could offend.

### Done (the routes, second commit)
All 23. **54 of 66 routes declare an owner, up from 29.** The backfill flipped on
in the same commit, so the pairing test passes with both halves moved.

Three routes were the interesting case: `asset_create_location`,
`shot_media_attach` and `shot_reference_attach` already had an `account_id`
parameter -- as a bare `Optional[int] = None`, which FastAPI reads as a **query
parameter**, not the dependency. Every real request arrived with `None` and
`AND account_id IS ?` matched nothing. Strictly worse than no owner at all,
because it reads as done in review; it is the same shape that made
`concept_archive` 404 every card on the real board. There is now a test for that
exact shape.

Four routes touch only shared tables and take an owner anyway -- `/scout/run`,
`/evals/run`, `/workflows/exec/enhance`, the harness. They start jobs, and the
job rail is per-account.

### Left: one route, and it is not about effort
`GET /analytics/accounts` reports the autonomy channels, and `channels` is itself
in `db.PENDING_OWNERSHIP`. Its rows are installation-wide, so a dependency there
would be decoration rather than scoping. It closes when `channels` does, which
needs per-account seeding of `DEFAULT_CHANNELS` -- a design decision, and part of
#11 rather than of this item.

## 14. Off the laptop, onto Postgres — the substrate decision  (to build — Mike's ask, 2026-09-02)

**The trigger is a person, not a date.** If the REST API product (#10) does not
happen and this stays Mike's own studio, the Mac with the launchd walls now
fixed is adequate and every migration below is pure cost. The moment somebody
else's concepts depend on his laptop being open, it is not.

Two moves. They are independent and get conflated constantly — Supabase does not
run `src/orchestrator.py`, and a box does not give you row-level security.

### Move one — Supabase for the data layer
Postgres, which this repo already runs for pgvector, plus auth and row-level
security.

- **Replaces:** `src/accounts.py` + `app/auth.py` (users, `account_members`,
  `auth_identities`, the Google/Discord OAuth dance), `data/pipeline.db`, and the
  hand-maintained half of #8/#12 — every `WHERE account_id IS ?` becomes belt
  and braces behind a policy the database enforces. **RLS is the structural fix
  for the exact bug the dry run found:** a query that forgets its owner returns
  nothing, so there is no such thing as a table nobody added to a list.
- **Consolidates `rag_documents` into the same database**, which unblocks the
  provenance third of #11 — the `project` label that is written at exactly one
  site and read by nobody.
- **The trap, and it is the whole thing.** RLS only protects a request that
  carries tenant identity into the database. A FastAPI server connecting with the
  service-role key — which the nightly orchestrator must — **bypasses RLS
  entirely**, and you are back to remembering `account_id` in every query with a
  false sense of safety. Getting the benefit means setting the claim per request
  (`SET LOCAL request.jwt.claims`, or a per-request role) and treating
  service-key paths as a small, deliberate, audited set. Plenty of teams adopt
  Supabase, route everything through the service key, and ship the leak they
  thought they had bought their way out of.
- **What #12 already bought:** every route knows its account, so there is
  somewhere obvious to set that claim. The guard tests in
  `tests/test_tenancy_routes.py` keep working and become the second line rather
  than the only one.
- Exit is `pg_dump`. Cost is a flat monthly fee in the tens.
- **Done 2026-09-03 — the RAG half only.** `rag_documents` (316 rows) now lives on
  Supabase project `zeropage-studio` (Free plan, us-east-1); `RAG_DATABASE_URL` is the
  session-pooler string (direct is IPv6-only, the transaction pooler breaks psycopg's
  prepared statements). Copy tool: `ops/migrate_rag_to_supabase.py`. `pipeline.db`,
  accounts and auth are untouched — that is the rest of this item, still gated on a
  second person. Automatic RLS was switched on at project creation, so any table
  created there is closed by default; the app bypasses it today as the owner role.

### Move two — one always-on box for the app and the scheduler
Fly or Railway; a small machine running the FastAPI app and the nightly.

- **This is what kills launchd and TCC.** The 6am walk failed silently for
  eleven nights on two macOS walls plus a plist that drifted after a folder
  rename — failure modes that exist only because of *where* it runs. It is
  uptime, not throughput: nothing here is about load, and SQLite on the laptop
  would serve hundreds of readers without noticing.
- It is also where the #10 REST API answers from, since inbound requests arrive
  whenever a customer sends them.
- It also decouples the dev server from production. A save currently runs
  migrations against the live DB seconds later, which is how `concept_locations`
  got damaged once.
- **It is a split, not a move.** `framebank` cuts stills from 149GB of ProRes in
  `footage/`, and the asset shelf reads local photo roots. A cloud orchestrator
  can see neither. Those lanes stay local, or get pre-ingested to R2 first.

### Considered and rejected
- **AWS.** Better in exactly two places: Secrets Manager + KMS for #10's tenant
  credentials (per-tenant encryption context, and a CloudTrail record of every
  decrypt, which Supabase Vault has no equivalent of), and Step Functions for the
  render pipeline's submit → poll → download. Against that: Cognito is the weak
  link where auth is the piece most worth handing off, there is no "just
  connect" (IAM, VPC, RDS Proxy, CDK), the floor is roughly $30/month for a NAT
  gateway alone, and S3 bills the video egress that R2 gives away. **If one AWS
  piece is ever taken it should be KMS on its own** — an SDK call from wherever
  the app runs, committing to nothing else.
- **Neon.** Excellent Postgres with real branching, genuinely appealing given the
  live-migration scar. No auth, no storage, so more pieces to assemble.
- **Cloudflare D1 + Workers.** Coherent, and R2 is already here, but D1 is
  SQLite-flavoured and gives no pgvector — it would split the RAG layer off from
  everything else.
- **Modal / Replicate.** Solve GPU problems this repo does not have; it calls
  other people's APIs rather than running models.

### Order
1. Nothing until there is a second person, or until #10 is decided.
2. **Move secrets once.** If BYOK (#10) is happening, pick the substrate *before*
   building the connector layer — tenant credentials are the one thing not to
   migrate twice.
3. Supabase, then the box. Not the reverse: a box still pointed at a SQLite file
   on a laptop is the worst of both.

## 11. The shared brain — global learning, made deliberate  (to build — Mike's decision, 2026-09-01)
Full write-up: `docs/tasks/task-shared-brain.md`. Raised as a tenancy gap — nine
learning tables with no `account_id` — and answered by Mike as a design choice:

> "the learning loop continues for all users, the entire app learns as it goes
> and gets better, that is the loop. I see all the data in dev studio."

So the learning tables stay global. This item is the three things that decision
needs, none of which is scoping them:

- **Write it down.** `taste_judge` already scores against *your* grades and
  *everyone's* winners — the right hybrid, declared nowhere, with its third input
  (`post_seo.derive_signals` called without `account_id`) global by accident
  rather than intent. A future session reads twenty unscoped tables next to a
  42-test tenancy suite and "finishes the migration". A `SHARED` tuple beside
  `db.OWNED_TABLES` prevents that.
- **`corrections` is a live bug.** No brand, no account, `pending_corrections`
  takes every unconsumed note and consumes it. A pilot user denying a concept on
  their own board writes a standing instruction that steers Mike's next nightly
  run, once, and is gone before their own night sees it. A lesson is shared; an
  instruction is addressed. The lesson half already works — the denial reaches
  everyone through the `denials` RAG shelf.
- **Provenance on the shelves.** `rag_documents` has a `project` column *and* an
  index, `rag.retrieve` already filters on it, exactly one site writes it
  (`app/api.py:1923`, as the brand) and **no caller reads it**. Without a label,
  the shelf gets noisier per user instead of smarter — the network effect
  backwards. A label is not a fence: everyone still reaches every lesson, own
  neighbourhood ranked first.

Ahead of #2 if a second person is going on the system soon; behind it if not,
since #2 is what makes the caps a budget.

**What the pilot dry run settled (2026-09-02, `docs/PILOT_DRY_RUN.md`):** all
three confirmed by running. `corrections` reproduced end to end — a pilot's deny
note steered Mike's nightly `gen_concept` once and was gone before the pilot's
own night. `project` is NULL on all 233 live chunks and read by no caller. The
judge: winners global is right, grades are scoped but every caller passes no
account (so "your grades" is always empty), performance is unscoped by accident.
One case the write-up did not have: the **asset shelf** is keyed
`assets/<kind>-<slug>` with no owner, so a same-named character in two accounts
overwrites on ingest and deletes the other tenant's chunk on delete — and shares
one photo directory on disk. Ahead of #2, then: a second person is going on.

## 12. The tenancy gap the dry run found  (SHIPPED 2026-09-02 -- see the report)
`docs/PILOT_DRY_RUN.md` is now the merge of both dry runs plus a table of where
every finding stands. Shipped: `51a39a8` (account_id on hold_queue and
workflows, holds_post's dependency, ZEROPAGE_POST_OK, the job registry, the
route + schema tests, the five caps, VEO_SPEND_OK) and `12a1573`
(rag_documents.project as the tenant, ranking not fencing, measured).

Then re-running the first walk's probes against the fix found two the fix had
not closed, both fixed on this branch: the render path called
`generate_for_shot` without the owner -- so Queue-approve and the Director's
generate had been dead for every OWNED concept since tenancy landed -- and
`def work(job, account_id=None)` in `/api/generate/run` shadowed the route's
dependency, so every concept it saved belonged to nobody until the next
startup handed it to the bootstrap account.

Still open, both choices rather than defects: `corrections` is cross-tenant
(item 4) and `active_brand` never looks at membership (item 5). Everything
else left before an invite is deployment, not code.

## 13. Three bins, told apart  (to build — Mike's ask, 2026-09-02)

Mike, after watching a Pinterest crawl feed a keyframe end to end:

> "I want a separate bin that the idea agent crawls from specifically, the
> asset bank that I can pull from personally, and the generated content that
> goes in the asset bank."

Three stores with three different owners, three lifetimes and three trust
levels. Today there is **one**.

### What actually exists now

`data/refs/<sha>.jpg` is a single content-addressed pool, and everything
writes to it through the same `refbin.save`/`refbin.fetch` door:

| writer | what it puts there | who owns it |
|---|---|---|
| `scout.stash_images` | crawl thumbnails, feed lead images | the agent |
| `mcp_server.bank_reference` | a URL the idea agent chose | the agent |
| `ops/ingest-saved-images.py` | a folder Mike saved by hand | Mike |
| `app/api.py:1333` | a composer upload | Mike |
| `scene_chain.visual_target` | a generated still | the machine |

They come out the far end identical: `/refs/<sha>.jpg`, indistinguishable.
That sameness was a deliberate and good decision — it is why a scouted image
resolves through `_resolve_asset_photo`, attaches as an `image_ref` and rides
into a generation with no new route. It is also why there is no query that
answers "show me only what I put there", or "only what the agent crawled",
or "only what we made".

The discriminator half-exists and is unused: `scout_bin.lane` already records
`pinterest` / `agent` / `target` / the crawl lanes. But a composer upload gets
no `scout_bin` row at all — it attaches straight to a shot — so the one thing
Mike most wants to pull from personally is the one thing with no row anywhere.

The asset shelf (`locations/`, `characters/`, `props/` + the `assets` RAG
domain) is a separate, permanent, *named* store — and nothing automatic reads
it. Characters and props reach a prompt only through `{cast}`, which
`cast_for` returns `""` for on Zero Page; locations only through a manual
`picked_locations`; the RAG shelf only through an opt-in `picked_references`.
An unattended 03:30 run has never touched any of it.

### The three bins

1. **Crawl bin — the agent's.** What the idea agent found tonight, keyed by
   pass, capped at `MAX_BIN_IMAGES`, disposable. This is what `scout_bin` is
   today and it can stay exactly as it is. Attribution (`source_url`) is
   load-bearing here: these are other people's frames.
2. **Asset bank — Mike's.** Named, permanent, curated, pulled from
   deliberately: `warehouse-corridor`, not `<sha>.jpg`. Midjourney
   environments and characters land here. Described once on ingest so the
   agent can *search* it and propose picks for a spark, rather than crawling
   for something already on the shelf. No cap — a library is not a bin.
3. **Generated content → promoted into the asset bank.** A keyframe or render
   that turned out well becomes a reusable asset. This is the loop that makes
   the bank compound instead of Mike re-sourcing the same corridor forever.
   Promotion is an explicit act, not automatic: the whole value of the bank is
   that everything in it was chosen.

### What this needs (rough)

- **Provenance on every reference.** An `origin` the pool can be queried by —
  `crawl` / `mine` / `generated` — written at every `refbin` door including the
  composer upload, which currently records nothing. Cheapest correct version
  is a row per stored ref, not a new directory: the flat `/refs/<sha>.jpg`
  shape is what makes everything downstream work and must not change.
- **The asset bank as a real store**, per the folder + describe-on-ingest
  sketch (a `library/environments/<slug>/` convention, vision description on
  ingest, into the `assets` RAG domain).
- **An MCP tool that can see it.** The idea agent's whole surface is
  `bank_spark`, `bank_reference`, `spark_images`, `next_spark`,
  `list_sparks` + idea CRUD. Nothing lists or searches the shelf, so the agent
  cannot pick from it even when it is the right answer. `bank_reference` also
  takes a URL, not a file — a Midjourney PNG on Mike's disk has no URL, which
  is why `ops/ingest-saved-images.py` had to exist at all.
- **A promote step** from a rendered keyframe to a named asset.
- **A pick step in the scout node**, so chosen bank assets ride into
  `reference_photos` alongside the crawl rather than instead of it.

### Order

Provenance first — it is small, it unblocks every "show me only X" question,
and without it bins 2 and 3 have nowhere to record what they are. The bank and
the promote loop after. The MCP tool last, since the agent can't usefully
choose from a shelf that isn't described yet.

Parked deliberately: Mike wants to keep testing the current loop first
(2026-09-02).

---

## Idea-agent findings from a remote Cowork session  (2026-09-03)

Found while running spark #38 ("Sixteen Missed Calls") end to end from a phone-
linked session. Items below are proven from the source or from failed calls,
not inferred from tool signatures. Board at the time: 52 generated, 4 picked,
**0 shot**, 45 archived, 2 parked.

### A. No way to write the `shot` column  (highest priority)
Schema supports it (`stats` reports it, `board(status="shot")` filters on it);
nothing in the tool surface sets it. Only board write exposed is
`pick(idea_id, picked=bool)`.

Every piece is currently produced by hand in Mike's own studio, so the one
thing the system most needs to learn — what actually got made — is exactly what
it cannot record. Shoot rate reads 0.0% while work ships.

Fix: `shoot(idea_id, shot=True, note="")` beside `pick`. Settle the definition
first — **`shot` means made by any means**, not "a render came back," or manual
production stays invisible.

Rejected: binding `shot` to the Queue's approve button. It misses studio work
entirely (never passes through the Queue), it fires before the output exists
(approve is a spend authorisation), and it couples the column to the renderer
that is currently missing. If a counter on approve is wanted, add a separate
`approved` one.

### B. MCP `generate` stops short of judge and keyframe  (3 for 3)
Ideas 169, 170, 171, 172 all return `judge_overall: null`, empty
`judge_reason`, empty `park_reason`, status `open`. #167 — created through
another route — has `judge_overall: 7.0`, a written reason, a rendered keyframe
and a park reason.

Two consequences: nothing generated over MCP can ever park in the Queue, and no
MCP-generated row can be read as "scored badly" because it was never scored.

### C. The composer binds refs to a generation, not to a spark
`orchestrator.py:287` → `bin_for_finding`; `scene_chain.py:355` →
`bin_for_pass`. The graph reads reference photos from the **spark's bin**.
`bank_reference` writes there, keyed `agent-<finding_id>`.

The Studio composer does not. Four images uploaded before a run left the newest
`scout_bin` row at id 39 from 14:58 — hours earlier; the files landed in
`data/refs/` at 23:49 and rode into the shot's `refs` list directly.

So `spark_images(38)` reads 0 no matter how much is uploaded through Studio,
and `generate(spark, brand, goal)` — no refs parameter — cannot be handed
references by a remote agent at all. Running a concept *with* references
currently means starting it in Studio.

Fix: a refs argument on `generate`, or have the composer also write
`scout_bin` rows against the matching finding.

### D. `archive()` records no reason
`archive(idea_id, archived=True)`. Archiving is the only negative signal this
system collects, and it stores *that* a concept was killed, never *why*.
169/170/172 were all archived for **no turn** — a verdict that points straight
at a failed prompt field — and that survives nowhere but a chat log.

Fix: `archive(idea_id, reason="")`, vocabulary `weak concept · no turn ·
no stake · off-brand · unshootable · seen it`.

### E. `reference()` refuses the CDN every reference comes from
`bank_reference` → `refbin.fetch` → `public_host` guard. Tested against
`cdn.midjourney.com` at full size and at 640px webp; both refused with
*"not a readable image, too large, or a refused host"*.

**Mostly already solved:** `ops/ingest-saved-images.py` is the local-file route
and takes `--pass-id`, so a folder can be banked straight onto a spark's pass.
What is missing is only that the *agent* has no tool for it —
`reference_local(finding_id, path, source_url)` would be the same code behind
an MCP door. Worth noting in the tool docstring that the script exists, since
an agent reading `bank_reference` alone concludes there is no local route.

### F. SQLite is unwritable over the Cowork folder mount
Reads work (`file:...?mode=ro`). Writes fail
`sqlite3.OperationalError: disk I/O error` — the mount does not provide the
locking SQLite needs. The failed transaction rolled back cleanly; nothing lost.
Backup at `data/pipeline.db.bak-before-agentrefs-2153`.

Stacked with A/D/E this is the real constraint: **a remote session can put
files into `data/refs/` but cannot write the row that makes them count.**

### G. Leftovers to clear
`data/_agent_inbox/` — `mj_cavity_hand.png`, `mj_torn_wall.png`,
`mj_phone_uplight.png` (staged Midjourney stills for spark #38).
Orphans in `data/refs/` with no row: `2efac6ac92b59c014848e9cd.jpg`,
`f6a451326dafc03657b27b93.jpg`. Keep `ea48535973dc26b7d4ef616c.jpg` — a
composer upload picked it up and it is in live use on #171/#172.

### H. Also
- `#135`'s spark field holds ~1,200 chars of Runway/Wan failure notes (one
  duplicated verbatim) instead of a spark. Good notes, wrong column — they are
  being fed to the generator as creative direction.
- The Midjourney MCP connector fails every `imagine` call with
  `unexpected keyword argument 'async'`. Server-side; unrelated to this repo.
- Keyframes DO render — #167's is live on R2. Only the clip step lacks a
  renderer, so the two parked items cannot be approved. One renderer short,
  not two. Do not archive them: they were never tested, and a false archive
  poisons the only negative signal there is.

### Order
A first — it is small and it is the only thing that lets the system see the
work Mike is actually making. Then C (references are what separate #171 from
the 48 rows before it), then B. D and E are cheap. F is not fixable here.

## 15. Review-queue UI — ML-labeling / editorial-CMS pattern, not a video-tool pattern  (parked — Mike's ask, 2026-09-04)

From the UI-revamp research thread (2026-09-04, see the landing-page mood board
artifact from that session): none of the AI production comps studied — LTX
Studio, Krea, Runway, Higgsfield — have solved the actual decision layer of this
app well. They're all built to *generate and browse*, not to *decide and
record why*. Zero Page's real differentiator is the opposite half: Pipeline is
a board of concept cards awaiting a verdict, and every unpicked row is a
training label (`pick_rate`, per [[studio_shape]] — archive, never delete). The
closer analogs for *that* screen are ML data-labeling tools (Label Studio,
Scale) and editorial CMS review queues (a WordPress moderation queue, a
code-review diff-approve UI, Airtable's row-expand + status-field pattern) —
not anything in the AI-video-tool category.

**Why this is worth a dedicated pass instead of folding into the general UI
readability item (#1):** labeling/review UIs share a specific vocabulary the
current Pipeline board doesn't have —

- **Focus mode, one card at a time**, entered from the grid, with keyboard
  shortcuts for the verdict (`a` approve, `x` reject/archive, `->` next) so a
  fast reviewer never touches the mouse. The board stays the overview; focus
  mode is where the actual grading happens.
- **The verdict always asks "why," inline, at the moment of the decision** —
  not a free-text box after the fact. This is the same gap as backlog item
  13-D (`archive()` records no reason): a short reason-tag picker
  (`weak concept - no turn - no stake - off-brand - unshootable - seen it`,
  the vocabulary already proposed there) shown the instant you reject, not a
  separate flow. Item 13-D is the backend half of this; this item is the UI
  half — they should ship together.
- **Batch actions on a filtered slice** (select all "3 concepts, ungraded,
  this week" -> archive with one reason applied to all) — the thing Airtable
  and every labeling tool get right that a card grid doesn't: most of a
  review session is bulk-clearing the obvious no's, not agonizing over one
  card.
- **Progress as a visible number, not implied** — "14 of 52 graded" the way a
  labeling tool always shows queue depth, so a review session has a visible
  end instead of infinite scroll.
- **The diff/before-after habit from code review** applies directly to a
  concept that was revised (Direct/Polish per [[director_canvas]]) — show
  what changed since last seen, not just the current state, so a reviewer
  isn't re-reading a card they already passed on.

**Where this touches existing surfaces:** Pipeline (the board) stays the
overview grid it already is — per [[studio_shape]], no new surface, no tabs.
This is a *mode* on Pipeline (grid <-> focus-review), plus the reason-tag capture
on Queue's reject/archive action and the Dev Studio grading flow ([[grade_queue]]
— 7+ is a mark, not a gate; this doesn't change that rule, it changes how the
mark gets entered).

Not scoped yet — this is a direction, not a build plan. Revisit after #1 (UI
readability pass) and #13-D/B are settled, since the reason-tag vocabulary and
the `shot` column both feed the same review moment this would touch.

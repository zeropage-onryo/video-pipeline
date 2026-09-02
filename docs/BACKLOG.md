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

**Two things that are bugs regardless of the BYOK decision:**
- Every `*_GLOBAL_DAILY_CAP` defaults to `str(DAILY_CAP)`, so the *installation*
  ceiling equals *one account's* allowance — the second pilot user gets nothing
  once the first has used the day. Numbers still unchosen from the last session.
- **Veo has no `SPEND_OK` gate.** Runway, midjourney and higgsfield all need an
  explicit per-command approval Mike controls; the most expensive tool needs only
  to be under the cap.

**The caveat, and it is the real answer to the second question.** Higgsfield and
Runway are model companies; reselling their inference is their business, not a
position this repo can win from. What is defensible here is the pipeline with
taste in it — scout's real references, `taste_judge` scored on Mike's own graded
history, `uncanny_judge`, `winning_prompts`, pick/shoot rate, the nightly
orchestrator — a system whose tenth run beats its first because it learned the
user. The binding constraint is distribution, not architecture: none of section 3
of the task doc gets a single user. If the next session has to choose, the demo
in front of ten people beats BYOK, and BYOK gets built the week someone asks.

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

## 12. The tenancy gap the dry run found  (NEXT -- ahead of #2 and #11, 2026-09-02)
`docs/PILOT_DRY_RUN.md`. `hold_queue` and `workflows` have no `account_id`, and
`holds_post` takes no account dependency at all -- so any signed-in user, with
or without a membership, reads Mike's hold queue and Director canvases, can
reject a hold, delete a canvas, and can fire "post now" against the autopilot
gate. The concept and asset surface is clean; this is the tables tenancy never
listed. Fix order is in the report. **This is now the gate on the pilot, ahead
of the cost tracker.** It also measured #2's two bugs (the global caps, veo's
missing SPEND_OK) and reproduced #11's `corrections` bug end to end.

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

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

## 2. Cost-efficiency tracker  (to build — Mike's ask)
"Build a tracker to make cost efficiency issues visible."

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

## 8. Account tenancy — the launch blocker  (to build — full plan in `tasks/task-account-tenancy.md`)
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
anything else in this file, including item 9. Scope is one weekend: an
ownership column, filtered reads, ownership checks on mutate, per-account caps
(keep a global ceiling too), and the tests that would have caught it. The one
decision to make first is whether the tenancy boundary is the **account** or the
**brand** — today `brand` is the only scoping dimension and both brands belong
to one operator; an outside user needs their own brands, which makes
`account_id` the real boundary and `brand` a dimension inside it. Getting that
backwards means doing the pass twice.

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

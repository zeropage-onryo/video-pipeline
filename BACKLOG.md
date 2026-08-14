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

## 5. Taste + performance judge on the concept generator  (to build — Mike's ask)
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

## 7. Brand switcher — ANTIHERO ⇄ Zero Page, full separation  (to build — paused mid-build)
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

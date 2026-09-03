# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

An AI pre-production studio for Zero Page Films (a one-person brand), aimed at running more of
itself over time. It generates concepts and shot lists from described real rooms, writes
platform-native AI video prompts for every shot, and feeds posted-video analytics back into the
next slate. Since 2026-08-20 every shot is AI-generated: a shot's `source` says whether Michael
captures real reference material (an acting take, a room plate) that anchors the generation via
the shot's `reference_image`, not whether the shot escapes the pipeline — a reference is an
enhancement, never a gate, same as RAG grounding. Prompts are also rendered in OpenArt Director's
conversational natural-language shape (`shot.render_openart`, `shootgen.director_prompt`) for
hand-pasting into Director, which has no public API (checked 2026-08-20). The autonomy ladder: L1 assisted -> L2
grounded generation + measurement -> L3 self-improving ideation -> L4 supervised
generate-and-post (gated, default off). Editing stays manual — an explicit L1 hold.
Post-production (footage ingest -> pitches -> cut lists) was cut in Aug 2026: the product is
the pre-production loop, and the edit happens by hand in Resolve.
Experimental — the loop is structurally in place but needs weeks of real use to mean anything.

## Commands

All Python commands run through the project's venv, not system Python:

```bash
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e .

# PRE-PRODUCTION (before anything is shot)
# 0a. Describe the spaces in locations/<name>/*.jpg -> locations table
venv/bin/python -m src.locations [--locations-dir locations] [--force]

# 0b. Generate concepts grounded in those spaces -> shoot_concepts table.
#     Two stages: cheap ideas first, then ONE scene prompt for the ones you pick.
venv/bin/python -m src.shootgen [--brand antihero|zeropage] [--client ...] [--spark ...] [--count 8]
venv/bin/python -m src.shootgen --scene <concept_id>   # write THAT idea's scene prompt

# 0c. Or one run through the autonomous content graph (LangGraph). No CLI --
#     call it: grounds in cast+library (CRAG), generates, evaluates (JUDGE=1
#     adds the LLM-judge), retries with issues folded into the spark, then
#     PARKS in autonomy.hold_queue -- render/publish are stubs until the
#     credit gate clears. LANGSMITH_TRACING=true traces; `langgraph dev`
#     (venv-studio/) serves it to Studio as "zeropage".
venv/bin/python -c "from src import orchestrator; print(orchestrator.run('gearing up ritual'))"
venv/bin/python -c "from src import autonomy; print(autonomy.list_hold())"      # the dead-man log

# THE RESEARCH SCOUT — where a spark comes from when it isn't typed.
# Four best-effort lanes (grounded web search on the Gemini key, YouTube
# search.list, RSS feeds from prompts/scout_sources.txt, the inspiration
# accounts), digested by ONE call into scored one-line sparks + the
# reference images behind them. Banked in scout_findings / scout_bin;
# nothing here spends render credit.
venv/bin/python -m src.scout run  [--brand ...] [--count 4] [--lanes web,shorts,feeds,creators]
venv/bin/python -m src.scout list [--brand ...] [--unused]
venv/bin/python -m src.scout next --brand zeropage       # the servable spark, or exit 1

# THE NIGHTLY TRIGGER — one shadow run, spark rotated from prompts/sparks.txt.
# ops/com.zeropage.shadowrun.plist schedules it at 03:30 (see its header to
# install); grading happens on /holds each morning. --scout takes the
# direction from the scout's bank instead, falling back to the rotation
# when the bank is empty or under scout.SCORE_FLOOR.
venv/bin/python -m src.trigger [--spark ...] [--channel zeropage] [--scout]

# GENERATIVE CLIPS (for a shot the footage can't cover)
venv/bin/python -m src.promptgen "<loose shot description>" [--idea-id N] [--slot-index N]
venv/bin/python -m src.genlog record|keep|reject ...

# THE LOOP (L2 -> L3) — analytics into the next slate
venv/bin/python -m src.promote_winners propose|approve|reject|run     # winners -> proven_results shelf
venv/bin/python -m src.rework [--count 6] [--brand ...]               # evidence-grounded next slate

# AUTOPILOT (L4) — OFF by default; dry-run unless env+approve+no kill switch align
venv/bin/python -m src.autopilot plan|run|kill

# SCHEDULED PUBLISHING — the queue cron invokes; publishes only through the autopilot gate
venv/bin/python -m src.scheduling list
venv/bin/python -m src.scheduling run [--approve] [--live]

# REFERENCE LIBRARY (RAG) — optional grounding for ideation
venv/bin/python -m src.rag ingest <files...>        # (re-)build the pgvector library
venv/bin/python -m src.rag query "<text>" [--k 5]
venv/bin/python -m src.rag_eval <cases.json> [--k 5]   # hit@k + MRR over labeled cases

# MCP SURFACE — the board, reachable from off this machine. Mounted on the
# web app at /mcp when ZEROPAGE_MCP=1 AND ZEROPAGE_MCP_TOKEN is set (no
# token = refused, never served open). Read/decide tools are always on;
# ZEROPAGE_MCP_ENGINE=1 adds research + generate. See START_SERVER.md.
venv/bin/python -m src.mcp_server --engine   # stdio; Claude Desktop launches this itself
# Registering it: ops/connect-claude.md (paste ops/claude-desktop-mcp.json, ⌘Q, reopen)

# SIGN-IN — seed the auth tables once (idempotent); real login guards /ui + /api
venv/bin/python -m src.accounts seed you@example.com [--password '...']

# WEB APP — /ui (behind sign-in) is the product; 127.0.0.1:8000/studio is
# the Dev Studio (dev posture only): one page of Stats / Grade / RAG
# Library / Settings / Dataset tabs, no sign-in — it reads every stat in
# the project. 127.0.0.1:8000 is the public landing (the only indexed URL).
venv/bin/uvicorn app.main:app --reload
```

`src/` is an installed editable package (`pyproject.toml`) — modules use relative imports and run
via `python -m src.<module>`, not `python src/<module>.py`.

Tests run with `venv/bin/python -m pytest tests/ -q`; lint with `venv/bin/ruff check .`. Both run
in CI on every push and PR (`.github/workflows/ci.yml`).

**`tests/conftest.py` blocks all network access during tests.** This exists because the same bug
landed four times: a test monkeypatches one generator function, the route is changed to call a
different one, the patch silently misses, and a real billed API call happens while the test still
passes — the only symptom being a slower suite. If a test fails with `NetworkUseInTest`, it is
patching something the code under test no longer calls.

Requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in `.env` for shootgen/promptgen and
locations' vision step. `YOUTUBE_API_KEY` is optional — it enables auto-fetching
public view counts and importing a channel's videos; without it manual entry still works.

**Sign-in (`app/auth.py` + `src/accounts.py`).** `/ui` and every `/api/*` route
require a session; `/signin` offers Google OAuth, Discord OAuth, and
email/password (argon2). The session is one signed httpOnly cookie
(`zp_session`, itsdangerous, 30 days) — no server-side session table.
`users` / `auth_identities` / `accounts` / `account_members` are the schema:
identities keep providers decoupled from users (adding Apple/X later is a
provider registration, not a migration). **The gate:** a fresh signup gets
zero `account_members` rows and sees "no account access yet" — membership is
granted by members (manual INSERT for v1), never by signing up.
`auth.current_account` resolves the active brand from real membership; the
`brand` cookie is only a preference among accounts you belong to, and
`POST /brand/{name}` still flips it exactly as before. The legacy `/studio`
pages deliberately stay open as the dev console. OAuth email-collision rule:
same email, different method = "sign in the way you first signed up," never a
silent merge — except the seeded passwordless bootstrap user, which the first
provider sign-in claims. Env: `SESSION_SECRET`, `GOOGLE_CLIENT_ID/SECRET`,
`DISCORD_CLIENT_ID/SECRET` (see .env.example; ephemeral dev secret with a
stderr note when unset). Not built yet, deliberately: password reset (needs
email infra), email verification, invite UI, sign-out-everywhere.

## Architecture

One phase, before the shoot: everything reasons about **spaces you have**. State lives in
SQLite (`data/pipeline.db`).

**A concept is ONE scene and ONE prompt (2026-08-26, Mike's call.)** The two-stage
idea -> shot-list shape split a concept across up to six independently-rendered prompts,
which is exactly what the scene bible existed to paper over; one paste-ready whole-scene
prompt is what the video models actually take. `shootgen.generate_scene_concept` is the
path the single-concept Create uses (`/api/pipeline/run` — the Director brief; Studio's
composer moved to `/api/scenes/run` on 2026-08-28, which is the same generator asked for
N takes at once): it reuses the proven gold-standard skeleton
(`prompts/scene_brief_prompt.txt`, grounded style -> beats -> diegetic sound ->
avoid-list), saves an ordinary `shoot_concepts` row whose `shots` is a ONE-element list,
and deliberately does **not** prepend the scene bible — that anchor holds separate shots
to one look, and there are none. No schema change: `shots` was always one JSON column, so
the scene board, Director, render, and autopilot all keep working, and the older
multi-shot concepts stay readable. The two-stage `generate_concept_ideas` ->
`generate_shot_list` path still exists but nothing in the product calls it any more —
the shot-list stage itself is gone: `generate_shot_list` became
`write_scene_for_concept` (approve an idea -> write ITS one scene prompt), so an idea
from anywhere — the ideas stage, `rework`'s evidence-grounded slate — still has a path
to a real prompt instead of being a dead end. **`shortlist_rate` was deleted with it**:
it measured "was this idea worth planning a shot list for", and with one scene written
per concept there is no planning step to measure — it would have read 100% forever.
`shoot_rate` is the surviving label. The dev console's `/concepts/generate` went too
(its page was already a redirect), taking the POV toggle, the location lock, the cast
picker, and `picked_references` with it — all four had been unreachable from the product
since `/studio/assist` and `/concepts` were retired. **Inspiration grounding did NOT go
with it:** it only lived on that route, so it moved to `api.scene_grounding`, which
composes `reference_block` + the brand's inspiration accounts for every real
generation.

**You get SEVERAL scenes and pick between them** (same day, same shape).
`shootgen.generate_scene_concepts` writes N of those one-shot rows off ONE idea in a
single call, so the takes are varied against each other rather than rolled independently
(the `generate_concept_ideas` reasoning) — `POST /api/scenes/run`, which is what **the
Studio composer's Create button** posts (2026-08-28). A card is laid out as Mike
specified: the references it was written against ABOVE, the scene, then the returned
prompt BELOW.
**The label moved with the unit:** `shortlist_rate` asked "was this idea worth planning
a shot list for", derived from `shots != []` — a question with no answer left once every
concept has exactly one shot. `preprod.pick_rate` asks how many generated scenes were
worth rendering, derived from a new `picked_at` column (additive ALTER, timestamped so a
rate can be windowed) and counting **only one-shot concepts**, since a legacy six-shot
concept was never a single scene to pick. **`shortlist_rate` was then deleted**
(2026-08-26, Mike's call, same day): `pick_rate` is its whole replacement and shipping
both would have meant one tile that could only ever read 100%. `pick_rate` and
`shoot_rate` are the two surviving labels, both on the Dev Studio's Stats tab.
**A scene's references are plural and live ON its shot** (`shot["refs"]` — no schema
change, `shots_json` was always flexible), which is what carries them into the enhance,
the keyframe and the clip when it opens in Director.

**The references now actually get attached (2026-08-28).** The loop was open at its most
embarrassing point: `format_cast` tells the generator that Michael and the Ducati have
"(reference photos on file)", the scene it writes says exactly that, the photos sit in
`characters/michael` — and nothing ever handed them to a renderer. Every concept in the
live database carried `refs=None`, so Director grounded on a sentence instead of a face.
Three parts to closing it:

- `shootgen.named_assets(text, assets)` reads a finished scene back and returns the assets
  it named — the mirror of `format_cast`. Matching is on the asset's name **plus multi-word
  proper nouns from its own notes** (`asset_aliases`), because the prop is stored as
  "Motorcycle" and every scene calls it a Ducati Panigale 959. Two consecutive capitalised
  words, never one: a missed alias costs a photo, a false one attaches a reference the shot
  was never meant to resemble.
- **Order is load-bearing, not cosmetic.** Runway anchors a clip on exactly ONE frame
  (`urls[0]`), so the sort is category (character → prop → **location last**) and then
  position of first mention in the scene. A room photo in the anchor slot makes the model
  reproduce the room instead of the scene; two characters are not interchangeable either,
  and a scene that opens on Michael must not anchor on the monster he meets later.
- `api._attach_scene_refs` runs after every `/api/scenes/run`, manual picks first (an
  explicit choice outranks an inferred one, and first is what Runway anchors on).
  `ops/backfill_scene_refs.py` did the same for concepts written before the fix.

**Composer uploads persist** (`data/refs/`, content-addressed, served at `/refs`, resolved by
`_resolve_asset_photo` like any asset photo). An uploaded photo used to ground one Gemini call
and then cease to exist, so it could never reach the keyframe or the clip.

**`.heic` decodes now** (`pillow-heif`, registered in `_to_jpeg`, degrading if absent), and
`_best_photo` prefers a natively-decodable sibling regardless. `IMAGE_EXTENSIONS` has always
listed `.heic` and the gallery has always shown it, but Pillow could not read one — so a HEIC
reference was accepted, listed on the shot, and then **silently** dropped at render. Half the
asset bank comes off an iPhone.

**A concept's canvas outlives the visit (2026-08-28).** Run all called `saveWorkflow()` with
`currentId = null`, so in concept mode it POSTed a brand-new library workflow row every
session purely so the runner had a saved graph to execute — and read none of them back:
`openConceptInDirector` sets `currentId = null`, clears `shotGraphs` and rebuilds the chain
from the shot. Node positions, hand-edited text and every node's output were discarded on
exit, which made re-running a paid Gemini enhance the only way to see the enhanced prompt
again. "Save to concept" never covered this — it persists shot *prompts* only.

`workflows` gains `concept_id`, `shot_n`, `states_json`, `seed_hash` (additive ALTER, plus a
partial unique index on `(concept_id, shot_n)`), and `save_shot_graph`/`get_shot_graph` upsert
one row per shot. Three things make it work:

- **States are stored beside the drawing.** LiteGraph's `serialize()` carries a node's config
  and position but never its output, so a graph restored without them is the right shape with
  every box empty — exactly the thing that made re-running feel mandatory. The runner already
  computes them (`execute_graph` → `result["nodes"]`); Run all now saves them with the graph.
  Restoring applies them with `applyNodeStates(states, {quiet: true})` — `quiet` because a
  restored output must NOT re-post itself to the shot, which already happened on the run that
  produced it.
- **The graph that ran and the graph you return to are one row.** Run all in concept mode
  saves to the shot's row and runs *that* id, instead of saving to a throwaway and executing
  something the canvas never sees again.
- **Staleness is checked on READ, not invalidated on write.** A saved graph holds a copy of
  the prompt in its User Prompt node, so a Direct revision, a Polish or a replan turns it into
  a drawing of a shot that no longer says that. `shot_graph_get` compares `seed_hash` against
  the live shot and returns `graph: null, stale: true` so the client rebuilds. Self-healing: a
  route added later that rewrites a prompt cannot forget to invalidate anything.

Concept-scoped rows are excluded from `list_workflows`, or the Open… picker would fill with one
entry per shot anyone has ever opened. `DELETE /api/concepts/{id}/graph` is the reset hatch.

**The enhance instruction preserves rather than expands** (`prompts/enhance_system.txt`).
The original said "take the user's simple prompt and expand it with vivid, descriptive
details" — but the input is a finished director's prompt, so the model summarised it: a real
run dropped every "(reference photos on file)" lock, the entire Avoid list, the beat order,
"one continuous handheld take" and "no background music", and returned a paraphrase. It is now
a tighten-don't-summarise instruction that names those four categories as untouchable, orders
the output constraints → style → texture → blocking, and forbids "cinematic"/"masterpiece"
padding. The test asserts what it protects, not its wording.

**One idea box, one board, one spend gate (2026-08-28, Mike's call.)** Scenes and
concepts were never two things — a concept IS one scene IS one prompt, one
`shoot_concepts` row — so keeping them as two Pipeline tabs meant two places to look for
the same card. The three surfaces are now split by *what you are doing*, not by what the
row is called:

- **Studio** is where an idea is typed, and the only place. The hero composer carries the
  idea, its references (uploads or picks out of the asset bank) and a **1–4** count, and
  posts multipart to `/api/scenes/run` (`SCENE_COUNT_MAX = 4` enforces the cap
  server-side — the select is not the gate). The Pipeline composer, the legacy "Generate
  scene" bar and the Generate tab are gone; `app/static/zpf/generate.js` was deleted.
  **Create writes concepts and stops on the board** (2026-08-29, Mike's call): pressing it
  is for reading concepts, not for a minute of billed work nobody asked for. Enhancing and
  keyframing are the Director canvas's job when a person is driving — and the nightly
  graph's when nobody is.
- **Pipeline** is only the deciding: one grid of concept cards, filters Open / Picked /
  Archived, and Pick / Not this one / Open in Director. The approve-deny-holds loop went
  with the merge — denying a concept is what the Dev Studio's grade queue does, against
  every archived row, with the teach-to-RAG shelves behind it.
- **Queue** is the spend gate. Rendering is the only step that costs money, so it is the
  only one with a gate in front of it, and **approving in Queue is what calls Runway**
  (`POST /api/queue/{id}/approve`). `GET /api/queue/pending` is derived from the rows
  (**parked or picked**, not archived, no `media_url`) rather than from the jobs registry,
  which is an in-process dict a restart clears — an approval queue that quietly emptied
  itself on restart would be a queue that lies. The live job registry stays underneath it,
  and says so. Two ways in: the chain parks a scene once its keyframe is rendered, or you
  pick a text-only concept off the board.

**Leaving the board is archiving, never deleting** (`archived_at`, additive ALTER, same
shape as `picked_at`). An unpicked row is the only negative signal this system collects:
`pick_rate` is generated-vs-picked, so deleting what you passed over would make the rate
read 100% forever and unfalsifiable. Archived rows stay counted and stay in the Dev
Studio's ungraded pool (`judge_overall IS NULL`) until they are graded, which is where
they earn their keep. Two things archive a concept: **Not this one** on a card, and
**Reject** at the spend gate (which also unpicks — rejected there means generated and not
picked, which is the truth about it). Approving used to archive the unpicked siblings from
the same `spark` too; that inference was removed on 2026-08-29 when approving became the
pick. It was safe while picking was a separate bulk step done first — pick two, approve
one, both survive — but with approval *as* the pick, approving take 1 archives takes 2–4
out from under you, and racily, since it ran after Runway returned ~90s later.
`preprod.archive_batch` stays as a tested helper with no caller.

**The night does the rest (2026-08-29, Mike's call.)** Enhancing, keyframing and
rendering happen in the **Director canvas** when Michael is steering a scene, and in the
**nightly graph** when nobody is. `src/scene_chain.py` holds one implementation of each
stage — `ground`, `write_scenes`, `persist_prompt`, `keyframe_scene`, `park_scene` — so
those three callers share code instead of growing three copies of "render a keyframe"
that drift apart. The two app-layer capabilities `src/` cannot reach (which asset photos a
scene named; how to resolve a site-relative photo to a file) are **injected as callables**,
because `src/` never imports `app/`.

**This is what finally makes the LangGraph load-bearing.** `src/orchestrator.py`'s right
side was all stub: every nightly run ended `"no usable clips (render is a dry-run stub)"`
in `hold_queue` — structurally complete, and nothing anyone could judge in the morning. A
new `keyframe` node sits between the prompt gate and the (still dry) render:

- It **persists** the prompt `structure_prompt` refined onto the shot. That prompt only
  ever lived in the run's state before, so the row Runway would render from still held
  shootgen's first draft while the version that passed the gate sat in a job payload.
  `persist_prompt` keeps the model's own text as `shot["written_prompt"]` — the grade
  queue teaches on what the MODEL wrote, and the Director canvas seeds its User Prompt
  node from it, so opening a polished concept and pressing Run does not enhance an
  already-enhanced prompt (a paid call that makes it worse; the instructions compound).
- It renders a **Nano keyframe** from that prompt and attaches it as the shot's
  `reference_image` — the frame the clip will anchor on.
- It **parks** the scene (`shot["parked_at"]` / `park_reason`) so it appears in the Queue
  with its still, and the hold row says what the night produced instead of describing the
  stub.

**The prompt gate is what earns a keyframe.** Only a scene whose prompt cleared the judge
(`score_prompts`, bar `prompt_gate_min`, fails closed) gets an image — 8 sparks × 2 brands
is 16 runs a night against `NANO_DAILY_CAP` of 20, which is also shared with every
Director render. A keyframe that fails parks the scene as text-to-video with the reason on
its card. `ZEROPAGE_KEYFRAME=0` turns the step off without touching the graph.

**`gen_concept` writes ONE scene now**, through `shootgen.generate_scene_concept` rather
than the legacy multi-shot `generate_concept`. That divergence stopped being cosmetic the
moment the night's output started parking in the Queue: the Queue, `pick_rate` and the
scene board all key on `is_scene` (`len(shots) == 1`), so a six-shot concept would have
been generated, scored, keyframed and then invisible to the surface meant to approve it.
`use_pov` stopped being passed with it — the scene brief neither offers nor names a camera.

**Parked is an explicit marker**, never inferred from `reference_image`: the Director
canvas writes that field mid-work, so inferring would drag every scene anyone has ever
keyframed into the spend queue. `GET /api/queue/pending` is `parked or picked`, and
**approving a parked scene is what picks it** — nobody clicked pick on an unattended run,
so the real choice is made at the spend gate, which is also the better source for
`pick_rate` ("how many generated scenes were worth rendering"). A `template_tag` rides
into the hashed prompt template so `by_prompt` does not average two meanings of "picked".

- **`src/imagery.py`** is `enhance` plus the whole reference→bytes layer
  (`fetch_image_bytes` with its SSRF guard and 15MB cap, `image_bytes_for_gemini`,
  `render_bytes`, `upright`), lifted out of `app/workflow_runner.py` unchanged so the
  stages can reach it from `src/`. The canvas keeps exactly one alias,
  `workflow_runner.enhance`, because `execute_graph` calls it bare and the tests patch it
  there; everything else is called through `imagery.` on purpose — an alias that can be
  monkeypatched without affecting the code that runs is how a test passes while a real
  billed call escapes.
- **The keyframe now actually anchors the clip.** `runway.as_prompt_image` resolves a
  reference to something the API can read: a public URL passes through, local `/renders/`
  and asset paths become an inline data URI with the mime read off the magic number.
  Before it, `generate_for_shot` took `reference_image` only when it started with `http`,
  so on any machine without R2 the keyframe silently anchored nothing while the Queue card
  said "anchors on the attached reference" and the credit was spent on the lie.
- **The nightly job has two failure modes, and it hit both** (2026-08-31). First:
  `~/Library/LaunchAgents` holds a **copy** of the plist, so editing the repo's copy
  changes nothing — the installed one kept pointing at `/Users/iphone/Documents/Github
  Portfolio` after the folder was renamed. `ops/install-launchagents.sh` now copies and
  reloads it in one step, and `--check` reports whether the installed copy has drifted.
  Second, and the one that actually stopped it around 2026-08-20: `data/morning_prompts.err`
  reads `/bin/bash: …/run_morning_prompts.sh: Operation not permitted`. **`EPERM`, not
  `ENOENT`** — that is macOS TCC denying a LaunchAgent access to `~/Documents`, which is a
  protected location. A LaunchAgent gets no consent prompt, so it is refused in silence,
  and the same path runs fine from Terminal (which has its own grant). Fix is either Full
  Disk Access for `/bin/bash`, or moving the project out of `~/Documents` — the durable
  one, since nothing else about this project wants to live in a TCC-protected folder.
  Both failure modes look identical from inside: a night with no runs reads exactly like a
  healthy night, which is why the `cd` now logs and exits 1.

```
locations/<name>/*.jpg  --locations.py-->  locations table (vision description per space)
                                                  |
                            shootgen.py ideas <---+  (+ brand, spark, POV on/off)
                                                  |
                                    shoot_concepts rows, shots = []   <-- cheap ideas
                                                  |
                            shootgen.py --shotlist <id>   (human picks: THE LABEL)
                                                  |
                                    same row, now with <=6 shots, AI shots, edit, grade
                                                  |
                                         [ you go shoot it ]  -> shot_done (SECOND LABEL)
```

**Two-stage on purpose.** Generate cheap options, a human picks, and only the picks get
expensive detail — `generate_concept_ideas`→`generate_shot_list`. The pick is recorded
(`shoot_concepts.shots != []`), which is what makes a prompt change measurable rather than
arguable. `shootgen` can still produce one full concept in a single call (`generate_concept`)
— that's what the web app's main button does — and `src/graph.py` wraps that single-call path
in a LangGraph evaluate-and-retry loop.

Post-production (ingest -> pitch -> editgen, the manifest.json/pitches.json/concepts.json
chain) was removed in Aug 2026. The pipeline's output is a shot plan you go shoot; the edit
is yours, in Resolve, by hand.

- **`src/locations.py`** — scans `locations/<name>/`, sends each space's photos to Gemini vision,
  stores `{space, light_sources, textures, angles, constraints}` per location. Incremental: a
  space already described is skipped unless `--force`.
- **`src/shootgen.py`** — three entry points over the same described locations plus a brand block
  from `prompts/brands.txt`: `generate_concept_ideas` (N cheap ideas in **one** call, so they're
  varied against each other rather than rolled independently), `generate_shot_list` (the shot plan
  for an idea you picked, leaving its title/hook/logline untouched), and `generate_concept` (both
  at once, what the web app's main button uses). `validate_concept` advises (never blocks): shot
  `type` in `CHARACTER`/`BROLL`, per-shot `source` in `CAMERA`/`AI`, camera shots' `cam` in
  `BMPCC`/`ACTION5`, AI shots' `tool` in the `shot.PLATFORMS` registry with a non-empty prompt,
  and — the one that matters — that every shot's `location` is a described space. Everything is
  a visible warning on a saved concept; nothing is rejected, and no shot-count cap exists. No
  described locations degrades to an ungrounded run with a stderr note, same as a missing
  reference library. `apply_pov(template, use_pov)` is why the POV toggle is real: off rewrites
  the prompt so `ACTION5` is never offered *or* named as legal, and `validate_concept` flags it
  if the model reaches for it anyway. Ideation is reference-grounded:
  `reference_block` (the *edge* helper — called from `main()`, the web
  routes, and the orchestrator, never from inside the generators) queries the RAG library
  (scoped to `IDEATION_DOMAINS`, never `ai_prompting`) with the spark, client, and
  the mood of the described rooms, and the generators take the resulting `references` string as a
  plain argument defaulting to `""`. That split is what keeps the generators hermetic in tests.
- **`src/preprod.py`** — `locations`, `shoot_concepts`, `concept_locations` tables. Extends
  `db.py` in its own module (own `SCHEMA`, own `init()`), same pattern as `generative.py`.
  Two labels, not one: `shortlist_rate()` is which ideas were worth planning (derived from
  `shots != []`, never stored, so it can't drift), `shoot_rate()` is which ones actually got shot.
  Both break down per prompt hash.
- **`src/orchestrator.py`** — the autonomous content graph (LangGraph, registered as `zeropage`
  in `langgraph.json`): `planner -> ground_entities -> ground_rag ->
  gen_concept -> evaluate -> structure_prompt -> score_prompts -> generate_render ->
  qc_clip -> caption -> publish`, with the corrective `evaluate -> gen_concept` retry edge and
  a `hold` sink. `score_prompts` is the credit gate proper: a deterministic floor (thin /
  leftover template tokens, zero model calls — **no upper length bound**, removed 2026-08-14:
  a 130-word ceiling never fired across the first 17 scored prompts while six of eight judge
  failures were too *little* detail, and length is a quality judgment the judge's `coherence`
  dimension owns, not a broken-output signal this layer should reject on) under a strict LLM judge
  (subject/camera/motion/lighting/coherence, 0–2 each, bar `PROMPT_GATE_MIN`, default 7/10)
  that **fails closed** — an unreadable verdict scores 0, so a credit is never spent on a
  judgment nobody could read. One failing prompt holds the whole run, reason = the judge's own
  one-liner. Every score is a `prompt_scores` row logged before any spend; grading a hold on
  `/holds` writes the human verdict next to the gate's, and `autonomy.prompt_gate_agreement`
  splits disagreement by cost (passed-but-rejected burns a credit; held-but-posted only costs
  an approval — drive the first near zero before lowering the bar, on 20–30 graded rows, not a
  handful). The
  left third is the original evaluate-and-retry loop unchanged: the evaluator combines
  shootgen's code-enforced `warnings` with an optional LLM-judge (`JUDGE=1`, floor `JUDGE_MIN`,
  never blocks); failed critiques fold into the spark and regenerate up to `MAX_ATTEMPTS`, and
  every attempt is a saved concept row. `ground_entities` formats the picked (or all)
  characters/props into `{cast}`; `ground_rag` is CRAG-graded retrieval (weak first pass gets
  one query rewrite) that degrades to ungrounded. **The right two-thirds is deliberately
  stubbed:** `generate_render` returns no clips until the credit gate is cleared (first-try
  prompt acceptance), `publish` posts nowhere — every run ends as a row in
  `autonomy.hold_queue` with its reason. Tests drive the compiled `GRAPH` hermetically and the
  publish gates directly.
- **`src/autonomy.py`** — channels / hold_queue / corrections / settings on the shared SQLite
  DB (the preprod.py pattern). `hold_queue` and `workflows` are OWNED tables since
  2026-09-02 (`db.OWNED_TABLES`; the dry run found any signed-in user could grade Mike's
  holds and delete his canvases), and every table is either owned or named in
  `db.SHARED_TABLES` with the reason it is global -- the schema test in
  `tests/test_tenancy.py` fails on one that is neither, and the route test there fails on
  any `/api` route that does not declare `auth.current_account_id`. Posting has a per-run
  approval, `ZEROPAGE_POST_OK=1` (`autopilot.POST_ENV`), in the render tools' SPEND_OK
  shape; `holds_post`'s docstring says what that gate is and is not. Autonomy is **per-channel** (`shadow` | `queue` | `auto`), both
  channels seed as `shadow`, and promotion is a one-row `set_autonomy` change. The kill switch
  is global (a `settings` row or `ZEROPAGE_KILL=1`) and forces every run to hold. `hold_queue`
  doubles as the dead-man log — every graph run writes a row — and morning approve/reject via
  `resolve_hold` feeds `evaluator_agreement`, the credit-gate number (~0.9 is the bar for
  promoting a channel). `_post_gate` in the orchestrator is the last code-enforced check:
  clips QC'd, caption non-empty, no warnings, under the channel's `rate_cap`. `/holds` is the
  control room: grade runs, promote/demote channels, toggle the kill switch, and drop a note —
  pending `corrections` fold into the next generation's spark and are consumed (each note
  steers exactly once).
- **`src/veo.py`** — the Veo connector (same SDK + key as everything else). `generate_video`
  is the thin raising wrapper (submit → poll → download immediately; Google keeps files ~2
  days); `generate_candidates` is the never-raises edge: N candidates, every attempt a
  `generations` row (the data `attempts_to_keeper`/`tool_scoreboard` read), **nothing ever
  auto-kept** — the pick is the label. Guardrails live in the module: a DB-enforced
  `VEO_DAILY_CAP` (default 6/day), `VEO_SPEND_OK=1` per run (2026-09-02, runway's shape --
  it was the most expensive tool in the repo and the only ungated one), and `estimate_cost`
  so every dry-run preview prices the plan.
  Reached two ways, both gated: the graph's `generate_render` only when `ZEROPAGE_RENDER=1`
  (unadapted tools — KLING/RUNWAY/... — honestly stay dry), and `autopilot.EXECUTORS["generate"]`
  only in live mode through the full L4 gate. Config verified against the *installed*
  google-genai (2026-08): `duration_seconds`, not the docs snippet's `duration`.
- **`src/shot.py`** / **`src/promptgen.py`** / **`src/genlog.py`** / **`src/generative.py`** — the
  generative-clip side, for the one shot per edit the footage can't cover. `shot.py` is a `Shot`
  dataclass with a controlled camera/size vocabulary and one **pure** renderer per tool; no model
  call goes near it. `promptgen.py` is the only place an LLM turns a loose description into a
  `Shot`. That split is deliberate: a bad prompt is then either a bad `Shot` (visible in the JSON,
  the model's fault) or a bad compile (catchable in a render test, the renderer's fault). Collapse
  it and you can't tell which broke. `genlog.py` records attempts after you generate in the tool's
  own UI; `generative.py` holds `shots`/`generations` and the scoreboards. **Verification is per-map:** each camera map carries a dated comment naming the guide it was
  checked against (Veo/Seedance/LTX/Wan dated 2026-08-04 from the local video-prompting skill
  references); `RUNWAY_CAMERA` and `KLING_CAMERA` remain undated general patterns — check those
  tools' guides before trusting their wording.
- **`src/youtube.py`** — video-id parser for `watch?v=`/`youtu.be`/`shorts` URLs (the part that
  actually breaks), public stats via the Data API v3, and channel import. `refresh_metrics_for_video`
  and `import_channel_videos` never raise: a missing key or failed call returns `{"ok": False}` so
  manual entry keeps working, per BUILD_SPEC.
- **`app/main.py`** — the web app. **The dev surface is one page** (consolidated 2026-08-26):
  `/studio` is the **Dev Studio**, strictly stats + system improvement, five tabs on the legacy
  `.sk` skin: *Stats* (the five pipeline numbers — shortlist/shoot rates, evaluator/gate
  agreement, first-try pass — server-rendered, plus the whole retrieval-eval surface via
  `evals_dev.js`), *Grade* (a
  randomized grading queue: `/grade/draw?mode=shot|golden|any` deals a random ungraded
  concept (`judge_overall IS NULL`) or golden query, `POST /grade/fresh` generates one
  throwaway idea for grading that is **never saved** as a `shoot_concepts` row. **The
  prompt is the grading surface** and it takes three verdicts: *approve* teaches it as
  written (`winning_prompts`), *teach it* takes the better prompt you write and records
  the PAIR — yours on the winning shelf as the fix, the model's on `avoid_prompts` —
  and *deny* steers away. The pair is linked by `winning_prompts.pair_id` and each
  document names the other, because the lesson is the contrast and a chunk holding one
  side can't carry it; teaching with an empty box records nothing rather than quietly
  filing the model's own prompt as the winner. All three post to the existing
  `/concepts/.../verdict` routes through one `teach_verdict` helper, with `next` chaining
  into the next draw. Legacy multi-prompt concepts additionally keep an idea-level
  verdict, since there the idea is a thing apart from any one prompt), *RAG Library* (the old `/library` content;
  `/library/ingest` also takes a txt/md/pdf **file upload**, extracted server-side — pypdf for
  PDFs — before `rag.ingest_records`), *Settings* (the `src/settings.py` tunables + the channel
  autonomy/kill-switch/standing-note controls that lived on `/holds`), and *Dataset* (golden
  set + run history tables with CSV/JSON export at `/dataset/export`). The old page URLs
  survive as redirects: `/dashboard`, `/evals`→ stats tab, `/library`→ library tab,
  `/concepts`→ grade tab (forwarding `?message=`, so every legacy `next=/concepts` still lands
  its message), and `/holds`, `/assets`, `/locations`, `/characters`, `/props` → `/ui`, where
  that work lives now. The old workspace composer/assistant (`/studio/assist`, `route_intent`)
  was removed with it — `/ui`'s Studio composer is the creation surface. Inline actions still
  pass `next` (`safe_next` refuses anything not site-relative, or every button becomes an open
  redirect). Photo serving (`/locations/{space}/photo/...` and the character/prop twins)
  registers on `app`, not `dev` — `/ui`'s galleries need it on a public deployment — and still
  resolves + refuses anything escaping its root; `?thumb=1` serves a cached 480px JPEG.
  Routes that call a model wrap it and redirect with a message rather
  than 500ing. **Two deployment postures (added 2026-08-25):** `DEV_TOOLS=1` (the local `.env`)
  registers the whole dev console — the Dev Studio and the surviving standalone dev pages
  (`/analytics`, `/winners`, `/videos/*`, `/post-image`, `/references/pick`) live on
  the module's `dev = APIRouter()`, included only when the flag is set, read once at startup.
  Unset (a public deployment) those routes are never registered, so `/studio` 404s like any
  undefined path — omission, not a second session check. Only `/`, the SEO files, `/signin` +
  auth, `/ui`, `/api/*`, photo serving, and `/brand/{name}` are unconditional; the rule for a
  new legacy-style page is "register it on `dev`". The landing CTA follows the posture
  (`/studio` vs `/ui`),
  `/api/capabilities` reports `dev_tools` live, and `/ui`'s "legacy" rail link is gated on it
  via the existing `data-cap` convention. The test suite pins `DEV_TOOLS=1` in
  `tests/conftest.py`; `tests/test_dev_tools.py` reloads `app.main` under `DEV_TOOLS=0` to lock
  the public posture.
  **The console needs no login.** `/studio` and the rest of the `dev` router are open (the
  established dev-console posture), but the Stats tab's eval instruments are a client-side
  shell, and pointing them at the session-gated `/api/evals/*` left half the tab 401'ing
  ("sign in first") beside server-rendered metrics that worked — so `dev` carries its own
  `/studio/api/*` delegations to the SAME `app/api.py` functions (never a second
  implementation, so the numbers can't drift), and `evals_dev.js` prefixes its calls with
  `window.ZP_API_BASE`, which the page sets to `/studio`. `/api/*` itself stays gated;
  `DEV_TOOLS` is the only gate on the console, so with the flag unset these routes don't
  exist at all.
- **`src/settings.py`** — the Dev Studio tunables, in the same SQLite `settings` table as
  autonomy's kill switch. Three keys, resolved **per call** (stored value > env var > shipped
  default, reads never raise): `prompt_gate_min` (orchestrator's credit-gate bar, was
  `PROMPT_GATE_MIN`), `grade_threshold` (CRAG's weak-retrieval floor, was hardcoded 0.55 in
  `src/crag.py`), `eval_k` (the eval harness's k, was hardcoded 5 in `app/api.py`). Saving on
  the Settings tab takes effect on the next run with no restart; clearing a field falls back
  to env/default rather than zeroing.
- **`app/api.py` + `/ui`** — the ZPF Studio skin (added 2026-08-21): the visual system from
  `prototype/studio.html` (spec: `docs/ZPF_STUDIO_SPEC.md`) ported onto a JSON API over the
  existing modules. One rule governs it: **every control is backed by a working endpoint and
  gated by `GET /api/capabilities`**, which is derived live (key presence, a real
  `rag.connect()`), never a static dict. Views: Studio (composer with live `/api/retrieve`
  grounding + asset carousel; **the idea composer lives here and nowhere else** since
  2026-08-28), Assets (locations/characters/props unified), Pipeline (**no tabs** since
  2026-08-28 — one board of concept cards, which is all it ever was), Director (the node
  canvas as its own rail view — Mike's explicit call, 2026-08-25: the nodes must never be
  buried behind a tab), Analytics (real metric snapshots, two brands never averaged),
  Queue (the approval gate, then the live job registry). The tabbed Pipeline of
  2026-08-25 — *Concept* (approve/deny + holds) and *Generate* (Higgsfield-style single
  generation) — was merged away; `POST /api/generate/run` and the preset picker
  (`prompts/presets.json` via `src/presets.py`) survive as Director node plumbing, and
  video references still ride a Gemini call inline under ~19MB, else through the Files API
  (`api.video_part`).
  *Director* — its own rail view — is what the old Workflows view actually was: the
  LiteGraph canvas (`app/workflow_runner.py` executes, `src/workflows.py` stores, per-node
  Run + Run all, the seeded "Prompt enhancement" template still opens from the toolbar),
  scoped to holding a concept's scenes together shot to shot for continuity. **Arrival is
  the nodes, never a composer:** the view opens onto the newest planned concept's scene
  graph; the chat-first brief composer (pre-filled with `gold_standard_example()`'s opening
  blocks + quick-start chips from `ZEROPAGE_FORMATS` for Zero Page, served by
  `GET /api/director/landing`; submitting runs the same `/api/pipeline/run` engine and
  lands the result on the canvas) is the fallback when nothing is planned yet, or an
  explicit "← Brief" away. Any concept opens directly from its card's Director button —
  **no approval gate**, approval/teaching stays a dev-console background loop. The canvas
  edits ONE shot at a time (Mike's call, 2026-08-26, matching his Runway-workflows
  reference): the active shot's chain is five nodes — the shot's short prompt →
  an Instructions node seeded from `prompts/enhance_system.txt` → Gemini 2.5 Flash →
  Nano Banana keyframe → Runway clip — while every other shot waits in a dock under the
  canvas, grouped by scene, one click to pull its nodes up (edits are pocketed per shot
  when switching). **The keyframe is not a side branch** (wired 2026-08-26): the enhanced
  prompt feeds BOTH render nodes, and Nano's image feeds Generate's `image` port, so the
  clip starts from the still you just approved instead of from text alone.
  The shot's reference image and the RAG retrieval ride on the BACKEND, not as extra
  nodes: the enhance node's `auto_ground`/`image_url` properties make the server pull
  `reference_block` and attach the shot's reference itself, and an unwired `system` port
  defaults to the enhancement instruction. Edits save back through
  `POST /api/concepts/{id}/shots/{n}/prompt` (→ `update_concept_shots`, only shots whose
  text changed, title/hook/logline never touched); a shot node's finished render
  auto-attaches to its shot (clip → media_url, Nano image → `/shots/{n}/reference`). `src/nano_banana.py` is the image connector, runway.py's
  never-raises gated shape on the existing Gemini key under `NANO_DAILY_CAP`, no separate
  spend gate since an image costs cents. **Every prompt this pipeline writes describes
  video**, so `generate_from_prompt` runs it through the pure `as_still_frame()` first:
  handed camera moves and a 9:16 duration, an image model answers in prose ("Understood,
  I will apply these guidelines…") and spends a call returning no image — verified live
  2026-08-26, and verified fixed by the same prompt rendering a real keyframe. The image
  call carries its own retry on `RESOURCE_EXHAUSTED`/`UNAVAILABLE` (two of four live calls
  were 503s) — on the SAME model, deliberately not `gemini_utils.generate_with_retry`,
  whose `FALLBACK_MODELS` are text models that cannot draw.
  **Reference images must be FETCHED, never named** (fixed 2026-08-26): neither Gemini
  model can retrieve a URL, so once R2 was configured — and every stored reference and
  keyframe became an `https://…r2.dev/…` URL — grounding silently died. Nano dropped the
  reference outright; enhance degraded it to a line of text (`Reference image: <url>`),
  which is indistinguishable from no reference. `workflow_runner.fetch_image_bytes` now
  pulls it server-side (SSRF-guarded against private/loopback/link-local addresses,
  `image/*` only, 15MB cap, never raises) and both paths attach real inline bytes with the
  mime read from the magic number (`gemini_utils.sniff_mime`) rather than a blanket
  `image/jpeg`. Attaching bytes is only half of it: `REFERENCE_NOTE` tells the model what
  the reference is FOR — match subject/wardrobe/props/location, do NOT copy its framing —
  since bytes with no instruction leave it guessing between copy/continue/ignore. Verified
  live: Flash asked what it can see answered "a man in a workshop looks at a weathered
  watch", and a keyframe fed back in produced the same man in the same jacket and garage
  under a new camera setup. Evals moved OFF `/ui` (2026-08-25) into the dev console — now
  the Dev Studio's Stats tab (`/evals` redirects there) — golden set still in SQLite via
  `src/evalstore.py`, seeded once from
  `eval_cases.json`, Hit@k/MRR computed server-side by `rag_eval` and stored per run; the
  tab is a shell over the same eval endpoints, reached through the dev router's own
  delegations (see "The console needs no login" above), and it registers on
  the `dev` router so a public deployment has no eval surface at all. **Asset creation is
  always-on** (2026-08-26): `POST /api/assets/locations|characters|props` (+ DELETE for
  characters/props) are the create path `/ui`'s "+ Add asset" modal posts to — they had to
  leave the dev router or a public deploy silently loses "add a character" — and every save
  also ingests a small chunk onto the RAG **`assets` shelf** (`assets/{kind}-{slug}`,
  best-effort, dropped again on delete), so the memory bank and the vector library stop being
  two stores that sit next to each other. The five pipeline metrics left `/ui` entirely
  (the old `#pmetrics` block) for the Dev Studio Stats tab; `/api/holds/{id}/post` is the
  "post now" that used to live on the retired `/holds` page, surfaced as a Post button on
  postable channels' hold rows. Billed work runs through `app/jobs.py` — an in-process,
  deliberately non-persistent job registry whose one push channel is the
  `/api/jobs/stream` SSE feed. That feed is why uvicorn runs with
  `--timeout-graceful-shutdown 3` (`.claude/launch.json`): without it, `--reload` waits
  forever on the open SSE socket and the dev server wedges on every code change. `/ui` is
  the product surface; `/studio` beside it is stats + system improvement only (2026-08-26).
  The Pipeline view's scene board closes the render loop two ways: copy a shot's stored
  tool prompt / Director rendering, render free in the tool's own app, and paste the
  finished clip's URL back (`set_shot_media_url`) — the default path — or one click
  through `src/runway.py`'s `generate_for_shot` (added 2026-08-21 on the existing
  connector), which only fires when `RUNWAYML_API_SECRET` is set AND the per-run spend
  gate `RUNWAY_SPEND_OK=1` is on: API calls always burn API credits even on the
  Unlimited plan, so the module's own gate inside `generate_video` is the wall, the
  button shows the priced estimate, and refusal points at the free app path. Every
  attempt is a generations row under `RUNWAY_DAILY_CAP`; the shot's `reference_image`
  (public URL) anchors as `prompt_image`; the clip downloads immediately (Runway URLs
  are ephemeral) to `data/renders/`, uploaded to R2 when configured, else served via
  the app's `/renders` mount. **`src/director.py`** is the board's director mode (the
  conversational half OpenArt's Director has): one note per call revises the stored
  shot plan in place through `update_concept_shots` — never the picked title/hook/
  logline — re-validated by `validate_concept`, with attached `media_url`/
  `reference_image` carried over by shot `n` and broken revisions (unparseable, empty,
  or silently shrunken without cut-language in the note) refused so the stored scene
  survives. `refine_shot_prompt` is per-shot technique polish via `promptgen.
  refine_prompt` against the `ai_prompting` shelf; the template is
  `prompts/direct_prompt.txt`.
- **`src/mcp_server.py`** + **`app/mcp_mount.py`** — the MCP surface (2026-08-31), so the
  board can be read and decided on from a phone or an agent instead of only from this
  machine. **An adapter, never a store:** every tool is a thin call into `preprod` or
  `scout`, and `data/pipeline.db` stays the one source of truth — a synced second store is
  the mistake `asset_shelf` exists to fix. The read/decide tools (`board`, `idea`,
  `search`, `capture`, `pick`, `shoot`, `archive`, `add_spark`, `tonight`, `sparks`,
  `images`, `stats`, `job`) are always on; **nothing on them spends**. Picking still only
  puts a concept in front of the Queue, and approving there is still what calls Runway,
  still on this machine — the single spend gate is load-bearing, and a second door onto it
  from a phone is exactly how it stops being one. **`shoot` records that a concept got
  MADE, by any means** (2026-09-03): the render lane, Higgsfield, Mike's own studio, a
  camera. `preprod.mark_shot` had existed since the start and nothing reachable from a
  phone called it, so `shoot_rate` read 0.0% across 52 concepts while pieces shipped by
  hand. Deliberately NOT bound to the Queue's approve: approve authorises a spend before
  any output exists (failed and discarded renders would all count), and studio work never
  passes through the Queue at all. If a counter on approve is ever wanted it is a separate
  `approved`, never this column.
  `ZEROPAGE_MCP_ENGINE=1` adds the two that cost model credit: `research`
  (`scout.scout` — crawl, bank scored sparks, download the images behind them) and
  `generate` (`orchestrator.run` — the LangGraph, ending PARKED in the Queue). `generate`
  **refuses outright while `ZEROPAGE_RENDER=1`**: that flag turns `generate_render` from a
  dry stub into real Veo spend, and a remote caller must never be what trips it. Both run
  through `app/jobs.py` and return a job id — a five-minute graph run must not sit on an
  open HTTP request.
  **Two layers, and the split is the testable part.** The tool functions are plain Python
  against a database path (so the whole surface is testable with no `mcp` package
  installed); `build_server` wraps them lazily. `app/jobs.py` is injected as callables
  because `src/` never imports `app/` — the `scene_chain` pattern.
  Three things were found by running it, not reading it: mcp **2.x renamed FastMCP to
  MCPServer** and moved `stateless_http` onto `streamable_http_app()` (hence the `mcp>=2`
  pin); the SDK's DNS-rebinding protection **421s any unrecognised `Host`**, which behind a
  tunnel means every real call fails looking like a broken server (hence
  `ZEROPAGE_MCP_HOSTS`, `*` to disable — safe only because the bearer token is checked
  before the MCP app is entered); and the SDK relays **only a `ToolError`'s message**,
  replacing every other exception with "Error executing tool <name>" — so caller errors are
  translated, or an agent cannot tell a bad id from a broken server and retries the
  identical call.
  **Two transports, and stdio is the default.** `python -m src.mcp_server` runs it over a
  pipe: Claude Desktop launches the process itself, so there is no port, no bearer token on the
  public internet, and nothing to leave running — and because the desktop app proxies its local
  MCP servers up to cloud sessions, the board reaches a phone through the same connection. The
  tunnel was only ever buying the part the desktop already does. The HTTP mount stays for the
  caller stdio cannot serve: something that is NOT the desktop app reaching this pipeline over a
  network. `main()` is the one place `src/` imports `app/` — deliberately, to inject the single
  job registry rather than grow a second one; the rule exists so the LIBRARY layer imports
  without the web app, and a process entry point is not that. `app/jobs.py` is stdlib-only, so
  it costs nothing.
  `.claude/skills/idea-agent/` is the agent that drives these tools — and its first move is
  reading the board, not generating: a run that adds four concepts to eleven unreviewed ones
  buried the decision that was already the bottleneck.
- **The spark column is the direction, not the scaffolding** (2026-09-01). `gen_concept` used to
  do `spark = f"{spark}\n{avoid}"` and pass one string, which the generator stored — so every
  graph-written row carried ~1500 characters of `winners.avoid_guidance` in the column the board
  prints, `archive_batch` groups by, and `scout._spark_key` hashes. Novelty compared the craft
  notes along with the idea, so the same direction on a night with a different avoid-list looked
  new: **novelty detection had silently stopped working** for every graph row. Split now —
  `generate_scene_concept(spark=..., steer=...)`: the prompt sees both, the row sees the
  direction. Filmmaker corrections ride in `steer` too, still consumed so each note steers once.
- **A faceless brand is handed no cast** (2026-09-01). `ground_entities` passed every asset on
  file to the shared `{cast}` socket regardless of brand, and that socket says *"reference the
  uploaded photos as the EXACT face … name them"* — flatly against `concept_zeropage.txt`'s
  *"FACELESS — no recurring person; any human is anonymous."* The cast block won: **every Zero
  Page concept on the board named Michael, Cyclops or the Ducati**, in the brand whose whole
  identity is that nobody recurs. `shootgen.cast_for(brand, ...)` gates it on `CAST_BRANDS`,
  applied in BOTH the graph and the Create path (`scene_chain.ground`). Scoped by brand rather
  than by a column on `characters` on purpose: an asset is not owned by a brand — the same
  jacket could appear in either — what differs is whether a brand may NAME a recurring person,
  which is a property of the brand. An empty cast falls through to `NO_CAST_NOTE`, so the model
  is told to describe appearance plainly rather than left to invent someone.
- **Nothing auto-posts right now** (2026-08-31, Mike's call). `autopilot.AUTO_POST_BRANDS` is
  an empty tuple, so no brand enters an auto-post plan: everything lands in the Queue and a
  person pushes it out, including a Zero Page concept that CLEARED the on-brand gate. A hold,
  not a repeal — Zero Page was built to auto-post and the uncanny gate exists to make that safe;
  lifting it is putting `"zeropage"` back in the tuple.
  **Deliberately a constant, not `ZEROPAGE_AUTOPILOT=0`**: that env var also gates the MANUAL
  approve-and-post button (app/main.py: *"Posting is OFF — set ZEROPAGE_AUTOPILOT=1"*), so
  switching it off to stop the machine posting would also stop Mike posting by hand from the
  Queue — the exact opposite of "everything goes to the Queue". The posture belongs in code
  anyway, which is what `build_plan`'s comment block has always said.
  The check reads from a **whitelist** rather than excluding one name, so **ANTIHERO can never
  be let out by an edit that only meant to free Zero Page** — and a test objects if anyone adds
  it. The uncanny check stays in front regardless: lifting the hold must not also open the gate.
- **The feedback loop, and where it was broken** (2026-08-31). Three loops run at
  different speeds. The **craft loop** (prompt → keyframe → does it look right) has always
  worked — `winners` holds real notes because Mike looks at keyframes and reacts. The other
  two were both broken, in the same way: the cheap signal was never captured.
  **The taste loop** recorded only that a concept was passed over, never why. Thirteen of the
  first fifteen were rejected and taught nothing. Worse, the Grade tab's most reachable button
  was `/concepts/{id}/discard`, which called `delete_concept` — a **hard delete on the one page
  built for teaching the system what a miss looks like**, destroying exactly the row
  `set_archived`'s docstring says must survive ("deleting the ones you passed over would make
  the rate 100% forever and unfalsifiable"). Replaced by `/concepts/{id}/pass`: five
  one-keystroke buttons (`preprod.ARCHIVE_REASONS` — boring / off-brand / unshootable / seen it
  / other) that archive with a reason and never delete. A reason is never a gate — passing
  without one still archives, because an archive that fails on a missing word is an archive that
  does not happen. `preprod.reason_counts` tallies them on the tab, because a queue with no
  visible result is a chore and a tally that moves is a scoreboard. This is the FIRST
  idea-level signal the pipeline has ever collected: `avoid_guidance` holds craft notes about
  PROMPTS, and nothing anywhere held "you keep rejecting these for being boring."
  **The audience loop was severed, not empty.** `videos.idea_id` points at the legacy pitch
  pipeline's `ideas` table and has never been written (0 of 10 rows), so a posted video could
  not be traced to the concept that made it — everything the audience taught was structurally
  unable to reach the generator. `videos.concept_id` is the link, and `preprod.posted_outcomes`
  is the join. It reads the **latest** metrics snapshot per video, never an average: `metrics`
  is a growth curve on purpose. `concept_id` carries no `REFERENCES` on purpose either —
  `shoot_concepts` is created by `preprod.init`, which runs AFTER `db.SCHEMA`, so a declared
  foreign key there fails every insert with "no such table: main.shoot_concepts" (it did; 27
  tests said so). The writer enforces the link, not the schema.
  **And the reason nothing had ever posted** (found 2026-08-31, fixed). `uncanny_judge.py` was
  written, tested, and never called from `src/` or `app/` — only from tests. Meanwhile
  `autopilot.plan` reads the verdict it was supposed to write, and says so in as many words:
  *"the gate fails closed, so 'unjudged' == 'held'"*. With `uncanny_passed` NULL on every row,
  **every Zero Page concept was permanently ineligible to auto-post**. The gate was never wrong
  — failing closed on an unjudged concept is exactly right for a channel that posts with no
  human — it was simply never fed. `orchestrator.brand_gate` is the missing wire: it runs after
  `evaluate` passes, scores zeropage concepts, and stores the verdict.
  It **records, it never routes.** The gate belongs at the posting decision, not at generation:
  a concept that misses the brand is still worth keeping and learning from, and parking it there
  would destroy the negative signal the grade queue exists for. Antihero skips it entirely —
  review-gated forever, so judging it is spend on a number nothing reads. `ZEROPAGE_UNCANNY=0`
  skips it, and skipping means never auto-posting, which is the honest degrade.
  Still open: **0 of 15 concepts scored by the TASTE judge** — that one is a manual Dev Studio
  ranking tool, gates nothing, and costs a billed call per click, which is why the queue has
  never been worked. Deleting its columns was considered and rejected: the uncanny columns
  beside them are load-bearing, and the two are easy to confuse.
- **`app/seo.py`** — the machine-readable growth surface, all pure functions so the exact bytes a
  crawler sees are testable without a server: `robots.txt` (the AI crawlers named explicitly and
  allowed; the app disallowed), `llms.txt` (what "grounded" means plus the hard specs — the part
  worth citing), `sitemap.xml`, and the homepage JSON-LD `@graph`
  (Organization + WebSite + SoftwareApplication, **no** `Offer` — nothing is for sale yet).
  `PUBLIC_PAGES` is the single list all three read, so they can't drift apart. Everything is built
  from `SITE_URL` (default `http://127.0.0.1:8000`) — set it before the site goes public or every
  canonical tag points at localhost. `/` is the only indexed URL; every app template carries
  `noindex`.
- **`src/rag.py`** / **`src/rag_eval.py`** — the reference library. Text files are chunked at
  word boundaries, embedded with `gemini-embedding-001` (768 dims — documents as
  `RETRIEVAL_DOCUMENT`, queries as `RETRIEVAL_QUERY`; the model is asymmetric and mixing them
  quietly worsens ranking), stored in PostgreSQL + pgvector (`RAG_DATABASE_URL` or `DATABASE_URL`, default
  `postgresql://localhost/zeropage`). Every row carries a required `domain` shelf label plus
  optional `project`/`source_ref`, and queries can scope on them (`--domain`, `--project`) —
  semantic similarity and hard SQL filters in one query. Deliberately not in `data/pipeline.db`: SQLite has no
  vector type, and the library is rebuildable from its sources. Re-ingesting a source replaces
  its chunks, keyed by `source_key(path)` — the path relative to the project root, **not** the
  basename. That matters for a folder tree of references: keyed by basename,
  `references/editing/notes.txt` and `references/lighting/notes.txt` are one source that deletes
  itself on every ingest. `shootgen.py` injects into a prompt's `{references}` section, querying
  with the spark plus the mood of the described rooms.
  `retrieve_references` never raises, so no Postgres means an ungrounded run with a stderr note,
  not a dead one. **`project` is the tenant that taught the row** (2026-09-02: the account
  slug via `accounts.slug_of`, NOT the brand -- rag.py's docstring says why), written at every
  learning-shelf ingest (denials, assets, winning/avoid prompts, proven_results) and NULL on the
  craft shelves on purpose. A label is not a fence: every retrieval site passes the caller's
  slug as `prefer_project`, which fetches a wider pool by similarity and re-sorts it with a
  small `PROJECT_BOOST` for the caller's own rows, so their lessons rank first and nobody's
  are excluded. `project=` stays the hard filter for the CLI; `python -m src.rag label` is
  the backfill (150 live chunks labelled `zeropage` on 2026-09-02, measured before/after on a
  copy first). The `rag` CLI fails loudly — there
  the store is the deliverable. `rag_eval.py` scores retrieval (hit@k, MRR) against a labeled
  JSON case file, judged at document level, sources deduplicated before ranking. **Note:**
  psycopg/libpq connects below Python's socket module, so `tests/conftest.py`'s network guard
  cannot catch a stray Postgres connection in tests — anything touching the store must patch
  `rag.connect` (or above) explicitly.
- **`src/post_seo.py`** / **`src/promote_winners.py`** / **`src/rework.py`** — the L2→L3 loop.
  `post_seo` derives winning/losing traits (topics, hooks, title words) at the comparison-window
  median, equal-age, and `score_post` grades a draft with reasons that cite the evidence — pure
  against SQLite, so a hundred drafts cost nothing. (Two "seo"s on purpose: `app/seo.py` is the
  site's crawler surface; this scores *posts*.) `promote_winners` proposes/approves winners onto
  the RAG `proven_results` shelf, docs now carrying the window's patterns; `rework` proposes the
  next slate from those signals + shelf (CRAG-graded retrieval), each idea carrying an "evidence"
  sentence, saved as ordinary concept ideas so the pick stays the measured label.
- **`src/autopilot.py`** — the L4 scaffold, where the contract is the gate: nothing executes
  unless `ZEROPAGE_AUTOPILOT=1` AND a per-run `--approve` AND no `data/autopilot.off` kill switch
  all align; anything less is a dry run that describes every action. The `generate` executor is
  a deliberately unwired registration point; `post` is wired to `instagram.execute_post_action`
  but only ever runs in live mode and refuses without `IG_USER_ID`/`IG_ACCESS_TOKEN` — the gate
  above it is unchanged. `build_plan` emits a `post` action only when a concept's shot carries a
  rendered `media_url` (the plan never invents deliverables).
- **`src/instagram.py`** — the Meta Graph publish + insights module, youtube.py's shape exactly:
  thin raising wrappers (container create/status/publish, `publishing_limit`, insights) under
  never-raising edges (`post_reel` walks create → poll-until-FINISHED → publish, never publishing
  an unprocessed container; `refresh_metrics_for_video` guards platform/token, maps insights →
  `db.record_metrics`, `saved`→`saves`). `_safe_error` redacts the token from every error that
  could reach a page or a db row. `VERSION` and `REEL_METRICS` are single dated constants —
  insight metric names shift between Graph versions, so verify on bump. A `/reel/<shortcode>`
  permalink does **not** contain the numeric media id; store `ig://<media_id>` (or the raw id) in
  a video's url for refresh to work, or pass a `media_id` key. Token refresh (long-lived tokens
  expire ~60 days) is a noted follow-up, not built.
- **`src/scheduling.py`** — the publish queue, because Meta has no native future-scheduling: a
  `scheduled_posts` table (own `SCHEMA`/`init()`, the preprod.py pattern), pure `due_posts`
  windowing, and `run_due`, the worker step cron invokes. Queue management is ungated — rows are
  intentions; the publish itself always goes through `autopilot.execute`, so gate/dry-run/kill
  switch apply unchanged and there is no second posting path. Idempotency: a row is marked
  `publishing` *before* dispatch and `publishing` rows are excluded from `due_posts`, so a crash
  can't double-post — a stuck row is visible in `list` and resolved by hand. `DAILY_CAP` (20)
  sits well under Meta's 100/24h quota, which is also checked live and treated pessimistically
  (unverifiable = don't post). `build_caption` grounds captions in `post_seo.derive_signals` and
  picks the best of several candidates by `score_post` (pure, free), degrading to the fallback
  caption on any failure.
- **`src/scout.py`** — the research scout: the input side the pipeline never had. Four
  best-effort lanes (`web` = Gemini's `google_search` tool on the existing key; `shorts` =
  `youtube.search_videos`, titles against view counts; `feeds` = RSS/Atom from
  `prompts/scout_sources.txt`; `creators` = `inspiration.combined_grounding`), compressed by
  ONE call into scored one-line sparks. **The digest is not optional plumbing** — `{spark}` is
  a single line in `scene_brief_prompt.txt` sitting beside a CRAG block, so raw crawl text
  passed through would produce concepts about the internet instead of about a room. Gates in
  order: `winners.avoid_guidance` folded into the prompt, recent sparks re-checked in code by
  `_spark_key` (prompts request, code enforces), then `SCORE_FLOOR` — under it a finding is
  banked but never served, and the caller falls back to `sparks.txt`. Findings are **banked and
  claimed separately** (`next_spark` hands one over, `mark_used` stamps it) so a crash loses no
  research and the 16-run nightly batch can't fire one spark twice.
  **Deliberately NOT grounded in the described rooms** — tried, measured, backed out
  (2026-08-31). The scout's main consumer is the nightly graph, whose generator is
  `build_scene_brief_prompt`, and that template's entire placeholder set is `{brand} {cast}
  {example} {references} {spark}` — there is no `{locations}`, so a spark pinned to a room
  imposes a constraint nothing downstream can honour. (The Create path's `scenes_prompt.txt`
  DOES have `{locations}`, but `generate_scene_concepts` fetches the rooms itself at generation
  time, so pre-committing to one only removes the variety `location_variety_note` manages.) An
  ablation on identical signals settled it: without the rooms block the sparks came back
  *better* — "a dinner plate set for three", "peeling paint reveals a hidden eye" — than with it
  ("shaking hands holding one rusted key" on a balcony).
  **What actually fixed the drift** was the digest prompt's translation rule (the signals are
  where an idea comes FROM, not what the scene is ABOUT, with worked bad/good pairs) plus an
  explicit ban on screens, feeds, algorithms, monetisation, AI, creators and content-making as
  the SUBJECT of a spark — and, upstream of both, the query altitude: asking what is "trending"
  returns the content business talking about itself (monetisation updates, policy changes, gear
  launches), real signal that nobody can point a camera at. The queries now ask what imagery and
  staging is landing. Two further lane facts from live runs: YouTube's keyword index returns
  **zero** results for the sentence-shaped queries the grounded lane wants (hence separate
  `WEB_QUERIES` / `SHORTS_QUERIES`, ordered by `relevance` not `viewCount`), and Reddit answers
  403 to `.json` and 429 to `.rss` from a datacenter IP, so the shipped sources are RSS.
- **The Instagram research lane** (`scout.gather_instagram` + the reading half of
  `src/instagram.py`) — **there is no FYP API and there never has been.** Probed against the
  live `zeropagefilms` token 2026-08-31: `explore`, `reels`, `trending`, `recommended_media`
  and `discover` all return "Tried accessing nonexisting field". Meta has never exposed the
  Explore/For-You surface to any API; the only way to read it is scraping a logged-in session,
  which breaks Meta's terms and risks the account this pipeline publishes to. So the lane reads
  what is **performing** instead — `business_discovery` on the handles already in
  `inspiration.py` (curated by Mike's taste, not an algorithm) and `hashtag_top_media` (Meta's
  own "top" ranking). Both are **Facebook-Login only**: they need `IG_GRAPH_TOKEN`, a different
  credential on a different host from the publishing `IG_ACCESS_TOKEN`, which
  `graph.facebook.com` cannot even parse. The lane never falls back to the publishing token —
  that would turn "not configured" into what looks like an outage — and reports the missing
  credential once per pass rather than once per handle.
  **The hashtag id cache IS the rate-limit strategy.** Meta allows 30 unique tags per rolling
  7 days, counted on the `ig_hashtag_search` ID lookup, and a tag's id never changes — so
  `ig_hashtag_ids` caches ids forever and only a genuinely new tag spends budget. The budget is
  checked locally *before* calling, so an exhausted window logs the real reason instead of a
  generic API error. `INSTAGRAM_TAGS` is deliberately short and stable; churning it is what
  would starve the lane. Note hashtag media carries **no `username`** (Meta strips it), so the
  permalink is the only attribution and the bin stores it as `source_url`.
- **`src/refbin.py`** — one owner for `data/refs`, both directions: the content-addressed name,
  the JPEG normalisation (EXIF transpose BEFORE `convert("RGB")`, HEIC when `pillow-heif` is
  present), `save`, `fetch` (bounded download for scouted images) and `resolve`. It exists
  because `src/` cannot import `app/` and the scout writes where composer uploads live; the
  read had to move with the write, since a patched writer and an unpatched reader is a file that
  saves successfully and then resolves to nothing. `app/api.py`'s `_to_jpeg`/`_save_upload_ref`/
  `_resolve_asset_photo` now delegate. **The URL shape is the point**: a scouted image comes out
  as `/refs/<sha>.jpg`, so it rides the composer path with no new route or resolver.
- **`src/gemini_utils.py`** — shared `generate_with_retry` (retries on `RESOURCE_EXHAUSTED`/
  `UNAVAILABLE`, falls through to `FALLBACK_MODELS` if the primary model stays down for the whole
  retry budget) and `strip_fences` (strips markdown code fences from model JSON output).

### Key conventions to preserve

- **Prompts and brand brief are plain text in `prompts/`, not hardcoded strings.** They're the
  highest-frequency edit surface in this system; treat `{brief}`, `{settings}`,
  `{locations}`, `{cast}`, `{brand}`, `{client}`, `{spark}`, `{count}`, `{references}`,
  `{title}`/`{hook}`/`{logline}`, and `{pov}`/`{cam_rule}`/`{cam_values}` as the templating
  placeholders when changing prompt files.
- **Prompts request, code advises.** Model output is always independently checked against
  reality — described location names, the shot-source vocabulary, the tool registry — and
  every mismatch surfaces as a visible warning on a saved result. Nothing is rejected: the
  checks exist because models hallucinate rooms and vocabularies, and the human
  deciding needs to see that, not because output "doesn't count" until it validates.
  (The orchestrator adds one twist: it *uses* the warnings to retry, but the saved result
  still carries them.)
- **Grounded in what exists — grounding shapes, it doesn't gate.** Every stage generates *from*
  real material: the cast and props on file, the reference library, proven winners, and the
  photos attached to the run. A mismatch is a warning, and a missing grounding source degrades
  to an ungrounded run with a note.
  **Rooms are material you may pick, not the frame you must generate inside**
  (2026-08-31, Mike's call, both brands). Concepts used to be generated *from* photographed
  spaces, because a camera can only film where you actually are. Since 2026-08-20 every shot is
  AI-generated, so that stopped being true and the rooms became what cast already is: named
  material a scene MAY use. Three things carried the old rule and all three are gone.
  `orchestrator.ensure_locations` **errored a run to `hold`** when the locations table was
  empty — gating the night on rooms its own generator never reads, since
  `build_scene_brief_prompt`'s whole placeholder set is `{brand} {cast} {example}
  {references} {spark}` with no `{locations}` in it; the node is deleted and `planner` now
  edges straight to `ground_entities`. `prompts/scenes_prompt.txt` listed every described room
  under "set scenes in these real spaces where they fit", which made the photographed rooms the
  default gravity of every Create; it now says the scene may be set anywhere the idea implies
  and that no room has to appear. And `generate_scene_concepts` passed the whole catalogue into
  the prompt; it now passes `picked_locations(refs, on_file)` — **only the rooms whose photos
  are attached to THIS run**, since `/locations/<slug>/photo/<file>` is the URL the asset bank
  hands out, so the slug in a ref path IS the pick. No new form field and no client-side flag
  to go stale (the `scout_finding_id` lesson), and an accidental pick is a visible tile
  somebody can remove. Picking reads as a LOCK, not a hint — it is a deliberate act, so it gets
  `location_variety_note(lock=True)`'s treatment: lean into the space rather than manufacture
  variety away from it. `validate_concept` still checks a named room against the **whole**
  catalogue, because naming a real space you were not handed is fine and naming one that does
  not exist is the thing worth flagging. `format_locations` is untouched — `rework.py` and
  `director.py` still want the catalogue.
- **The human choice is the label, and it gets recorded.** `shootgen.py` generates ideas, a human
  plans some (`shortlist_rate`), and shoots fewer still (`shoot_done`). Stored with the prompt's
  hash, so a prompt change can be measured against the rate it produced rather than argued about.
  That selection is also the only manual gate.
- **Anything that calls a model degrades instead of breaking.** A missing API key or a failed call
  returns a result the caller can report, not an exception that takes the page or the run with it
  — `/metrics/new` still accepts typed numbers, `/concepts`
  still renders. The exceptions are deliberate: `promptgen` and `locations` fail loudly, because
  there the model call *is* the deliverable rather than bookkeeping on top of one.
- **A crawl is an enhancement, never a dependency.** Every scout lane, the digest, the image
  fetch and the bank read all degrade to contributing nothing rather than raising — the static
  `sparks.txt` rotation they replace never failed, and a research step that can fail a night is
  a downgrade. What a silent lane *does* owe is a line: `scout()` returns `errors` and the CLI
  prints them, because a crawl that quietly finds nothing looks exactly like a healthy one (the
  same failure mode that hid the dead launchd job for eleven nights).
- **A reference must be traceable to where it came from.** Bin rows keep `source_url` and the
  Create card renders it as a link on every tile. These are other people's frames held as mood
  reference; an unattributed tile in front of someone about to spend a render on it is the wrong
  affordance.
- **Verify by running it, not by reading it.** Every real bug this project has had — a `warnings`
  string shattered into 140 single-character warnings, CI dying on torch's CUDA build, two tests
  passing only because the dev machine had a populated database, a site with no navigation between
  its own pages, tests quietly making billed API calls — passed review and passed its own tests.
  Each was found by starting the server, clicking the thing, or noticing the suite got slower.

## Where the project stands

Everything below is current as of the last commit on `main`. Update it when it stops being true.

**Working and verified against real data:** the pre-production loop runs end to end, including
real Gemini calls. One location described from real photos, 50+ concepts (5+ with shot lists),
1 posted video with one metric snapshot. Reference-grounded ideation is
verified live both ways: `src.shootgen --spark "gearing up ritual"` printed "Grounding in 5
retrieved reference(s)" against the real library, and the same command with the store pointed at
a dead URL printed the ungrounded note and still produced ideas (exit 0). The evaluate-and-retry
graph is verified live too: a `src.graph`-era run produced Concept 55, grounded in 5 references,
clean on attempt 1. ~490 tests, ruff clean, CI green on every push.

Post-production (ingest/pitch/editgen, `/pitches`, the assistant's `cut` intent) was removed in
Aug 2026 — the DB keeps historical pitch-run rows, but nothing generates new ones.

**Structurally complete, statistically empty:** the L2→L3 loop is built and verified live —
`promote_winners propose` honestly reports nothing clears the bar (no videos measured at equal
age yet), and `src.rework` generates an evidence-free slate with the note. The rates
(`shortlist_rate`, `shoot_rate`, `selection_rate`) and `post_seo`'s signals are structurally
correct and currently meaningless — they need weeks of real posting before a prompt change can be
measured or a slate genuinely reworked from evidence. The most valuable next step is not code: it
is shooting one of the generated concepts, marking it shot, posting it, and recording metrics.
The de-cap is verified live: SHOOT-25 generated with 2 AI shots (WAN, RUNWAY) + 2 camera shots,
zero warnings, rendered on the studio canvas. L4 exists as `src.autopilot` — gated, dry-run,
default off, executors unwired.

**Known gaps, in rough priority:**
- `shot.py`'s `RUNWAY_CAMERA`/`VEO_CAMERA`/`KLING_CAMERA` maps and the AI-slot prompt phrasing are
  general patterns, not current documentation. Check each tool's prompt guide before relying on a
  generated prompt, and date the comment above each map.
- `YOUTUBE_API_KEY` in `.env` is a placeholder, so channel import and metric refresh can't reach
  the API. Everything else works without it.
- `import_channel_videos` can report success when the bulk stats call failed; `mark_kept` doesn't
  clear other keepers on the same shot, which skews `attempts_to_keeper`.
- The RAG store runs live on this machine via **Homebrew `postgresql@17`** (auto-starts at
  login through `~/Library/LaunchAgents/homebrew.mxcl.postgresql@17.plist`; database `zeropage`,
  data directory `/usr/local/var/postgresql@17`). No `DATABASE_URL` is set in `.env` — connections
  fall through to `rag.DEFAULT_DB_URL`, which is already `postgresql://localhost/zeropage`, so
  nothing needs setting on this machine; set `RAG_DATABASE_URL` to point elsewhere. There are no
  standalone vector files to back up: the embeddings are Postgres pages (TOASTed out of
  `rag_documents`, since 768 floats exceed the inline threshold). Use `pg_dump zeropage`, or just
  re-run `python -m src.rag ingest` — the library is rebuildable from its sources by design.
  Ingest, scoped query, and the eval harness are all verified against it with real embeddings.
  The library currently holds 14 sources / 106 chunks across `ai_prompting` (79), `marketing`
  (25), `personal_brand`, and `cinematography`. `prompts/edit_prompt.txt` was ingested early and
  has been removed: it is a prompt *template*, and retrieving `THE BRAND: {brief}` scaffolding as
  a "reference" to inject into another prompt is worse than no grounding. Don't re-add prompt
  templates; the library wants real reference material. Machines
  without a local Postgres can use the repo's `docker-compose.yml` instead. Note: Postgres.app
  is also installed but is an uninitialised PostgreSQL 18 that owns none of this data — do not
  "Initialize" it, it would contend for port 5432 with the server that actually has the library.
- `/shots` (the candidate review-and-keep screen) and the tool scoreboard surface aren't built —
  the data path is ready (`veo.generate_candidates` logs every attempt; keeping stays a human
  act through `genlog`), but the screens want real generation attempts to show, and the first
  real Veo spend is a deliberate step (`ZEROPAGE_RENDER=1`, or the autopilot live gate) nobody
  has taken yet. Same for posting: `publish` parks even on `auto` until an upload API exists —
  YouTube needs OAuth. Public clip hosting is no longer the blocker it was: R2 **is**
  configured on this machine and `storage.configured()` is live, so renders come back as
  public `*.r2.dev` URLs (verified 2026-08-26 by a real Nano render). That is also what
  lets a Nano keyframe anchor a Runway clip by URL; `workflow_runner.render_bytes` is the
  fallback for a machine where R2 is off, since a `/renders/` path is local to the app.

**The user's real data lives in `data/pipeline.db` (gitignored, ~128KB) and `locations/`
(gitignored, photos).** A fresh clone gets the tool, empty. Never overwrite either without asking.

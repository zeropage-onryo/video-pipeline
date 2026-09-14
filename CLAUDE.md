# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

An AI pre-production studio for Zero Page Films (a one-person brand), aimed at running more of
itself over time. **It is a creative studio, not a location scout.** It writes short stories
worth shooting, turns each into ONE paste-ready scene prompt, renders them, and feeds
posted-video analytics back into the next slate. Since 2026-08-20 every shot is AI-generated
and no camera is involved: a shot's `source` is a label on where its reference material came
from, never a claim that the shot escapes the pipeline. What grounds a scene is the reference
IMAGES attached to it (`shot["refs"]`) plus the RAG library — and since 2026-09-08 a scene with
no refs at all never reaches the board (see `preprod.reference_gate`). The photographed rooms in
`locations/` are optional material a scene MAY pick, not the frame it must be generated
inside. Prompts are also rendered in OpenArt Director's conversational natural-language shape
(`shot.render_openart`, `shootgen.director_prompt`) for hand-pasting into Director, which has
no public API (checked 2026-08-20). The autonomy ladder: L1 assisted -> L2
grounded generation + measurement -> L3 self-improving ideation -> L4 supervised
generate-and-post (gated, default off). Editing stays manual — an explicit L1 hold.
Post-production (footage ingest -> pitches -> cut lists) was cut in Aug 2026: the product is
the pre-production loop, and the edit happens by hand in Resolve.
Experimental — the loop is structurally in place but needs weeks of real use to mean anything.

## Backlog

Parked ideas, known bugs and next builds live in `docs/BACKLOG.md`.
Read it before proposing new work — several obvious-looking gaps are
already recorded there with the reasoning, and some already have a
script (e.g. `ops/ingest-saved-images.py` is the local-file route into
the reference bin that `bank_reference`'s URL-only signature implies is
missing).

## Commands

All Python commands run through the project's venv, not system Python:

```bash
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e .

# IDEATION -> ONE SCENE PROMPT (nothing here is shot; nothing here spends render credit)
# 0a. OPTIONAL: describe the rooms in locations/<name>/*.jpg -> locations table.
#     Material a scene may pick, never a constraint it must satisfy. The
#     nightly generator has no {locations} placeholder at all.
venv/bin/python -m src.locations [--locations-dir locations] [--force]

# 0b. Generate concepts -> shoot_concepts table. Each is ONE scene and ONE prompt.
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

# GENERATIVE CLIPS — the Shot dataclass and its per-tool prompt renderers
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

# THE MANUAL RENDER LANES — a subscription spent by hand, never by the nightly.
# The Higgsfield MCP (a Claude session) and Runway Explore Mode (a human in
# Chrome; free on Unlimited, a web-app toggle with NO API parameter). `list`
# says what is waiting, `import` files the mp4 into data/renders/<provider>/
# and writes a FREE row (cost_usd NULL, params.source = the lane marker, so
# ledger.is_billable takes no hold). BOTH lanes are OPERATOR-ONLY —
# src/manual_lane.py's gate is the accounts.manual_lane_operator COLUMN (the
# env vars are gone), checked server-side against the account id on every
# surface, fails closed (nobody, until somebody is turned on). Turn it on:
venv/bin/python -m src.accounts operator <slug> --on   # --off to revoke
# The API-billed adapters are untouched by it. See docs/RUNBOOK.md 2026-09-08.
python3 ops/render_queue.py --account <slug> [--provider runway] list
python3 ops/render_queue.py --provider runway --account <slug> import \
    --concept N --shot 1 --file clip.mp4 --model gen4_turbo --duration 10

# THE REFERENCE PHOTOS — the bytes behind every ref URL, pushed to R2 so they
# resolve on the deployed site too (characters/props/locations/data/refs are
# gitignored AND dockerignored). Re-runnable; run it after adding photos to a
# folder BY HAND -- the app's own upload routes mirror as they save.
venv/bin/python ops/backfill_reference_photos_r2.py
# ... then rewrite refs already stored on a shot to those public URLs. Reports
# first; --write to do it. A ref whose bytes are not in the bucket is left alone.
venv/bin/python -m ops.canonicalize_shot_refs [--account <slug>] [--write]

# THE DATA COPY — data/pipeline.db (SQLite) into Postgres, once, at cutover.
# Refuses a non-empty target and never guesses the DSN; --dry-run counts.
venv/bin/python -m ops.copy_sqlite_to_postgres --dsn "$DATABASE_URL" [--dry-run] [--truncate]

# SIGN-IN — seed the auth tables once (idempotent); real login guards /ui + /api
venv/bin/python -m src.accounts seed you@example.com   # identity is Supabase Auth's

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

**Sign-in (`app/auth.py` + `src/accounts.py`) is Supabase Auth's** (2026-09-03,
step 6 of `docs/tasks/task-postgres-migration.md`). `/ui` and every `/api/*` route
require a session; `/signin` offers Google, Discord and email/password, all of
which GoTrue does — the passwords, the verified-email rule, account linking.
Server-side, no client library: the OAuth doors redirect to
`{SUPABASE_URL}/auth/v1/authorize` (PKCE), Supabase sends the person back to
`/auth/callback?code=`, the code is exchanged at `/auth/v1/token`, and the access
token is verified once with PyJWT (`SUPABASE_JWT_SECRET`, or the project's JWKS).
The session is still one signed httpOnly cookie (`zp_session`, itsdangerous, 30
days) carrying the Supabase user id — no refresh token is stored, the app never
acts as the user against Supabase afterwards. `users` is a PROFILE MIRROR of
`auth.users` keyed by the same UUID (no FK: the `auth` schema is Supabase's and the
throwaway test Postgres has none); `accounts` / `account_members` are ours.
**The gate:** a fresh sign-in gets a mirror row and zero `account_members` rows and
sees "no account access yet" — membership is granted by members (`src.accounts
invite`), never by signing up. An invite creates the row by EMAIL with a placeholder
id and `claimed_at` NULL; the first sign-in with that email (`accounts.claim`)
rewrites the id to the real UUID (the membership follows through ON UPDATE CASCADE).
Same for the seeded bootstrap user. An email already claimed by a different UUID is
refused, never merged. `auth.current_account` resolves the active brand from real
membership; the `brand` cookie is only a preference among accounts you belong to,
and `POST /brand/{name}` still flips it exactly as before. The legacy `/studio`
pages deliberately stay open as the dev console. Env: `SUPABASE_URL`,
`SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`, `SUPABASE_PROVIDERS` (default
`google,discord`; enabling them, and the Google/Discord client ids, is dashboard
work — see .env.example), `SESSION_SECRET` (ephemeral dev secret with a stderr note
when unset). Tests stand in for GoTrue behind the one seam `auth.gotrue` and sign
real HS256 tokens with a test secret. Not built yet, deliberately: an invite UI,
sign-out-everywhere; password reset and email verification are Supabase's now.
**The React studio gets its session through a handoff, never cross-site (2026-09-14,
found on the live account).** `zeropage-web.fly.dev` and `zeropage-studio.fly.dev` are
different sites (fly.dev is a public suffix), so the API's cookie was a third-party cookie
to every fetch the studio made and Safari (always) and Chrome (now by default) refused to
send it: `/signin`, a top-level navigation, saw the cookie and answered "already signed
in" while every `/api` call got 401. Now the studio's fetches go through ITS OWN origin
(`NEXT_PUBLIC_API_URL` empty; the Next rewrites proxy `/api`, `/auth`, `/signin`, `/brand`
and the photo routes to `API_UPSTREAM`), sign-in and sign-out NAVIGATE to the API origin
(`NEXT_PUBLIC_AUTH_ORIGIN`, where OAuth's PKCE session and Supabase's callback live), and
a sign-in that came from a trusted `next` (FRONTEND_ORIGINS) ends in a 303 to
`{front end}/auth/handoff?t=<2-minute token, session secret under its own salt>&next=/studio`
-- the proxy forwards that GET to `auth.handoff`, whose Set-Cookie lands on the front end's
origin first-party. `/signin` does the same when already signed in here; `GET /auth/logout`
clears this origin's cookie after the studio has cleared its own through the proxy.

## Architecture

One phase, and it ends at a rendered clip: everything reasons about **an idea worth shooting
and the reference images that ground it**. State lives in **Postgres** (`DATABASE_URL`, Supabase
since 2026-09-03). `data/pipeline.db` is a 0-byte leftover of the SQLite era — `db.DB_PATH`
survives only as the name a few call sites still pass; do not write to it.

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

**A scene is written as TIMED SHOTS and rendered ONE SHOT AT A TIME (2026-09-10, Mike's
call).** The one-continuous-action rule is gone: a scene prompt's BEATS are now timed
windows — `(0-3s)` one shot, `(3-7s)` a different one, cuts and location changes between
them — filling a total length (`timeline.scene_seconds`: the composer's `cseconds` select via
`GET /api/scene-lengths`, else `ZEROPAGE_SCENE_SECONDS`, else 10; clamped 4–30, never
refused). Both writer templates get `{seconds}`, and tell the writer each window is rendered
as its own clip, so each window must be ONE shot (one camera setup, one clear action, 2–10s).
**`src/timeline.py` is the step between the scene and the renderer.** It runs on the SAME
brain that wrote the scene (the composer's Reasoning tier, or `ZEROPAGE_BRAIN` at night) and
turns the windows into `shot["timeline"]` = `{seconds, planner, source, brain, continuity,
parts: [{n, start, end, seconds, text, prompt, refs, reference_image, media_url}]}` — one
row, one shot, one scene still (`is_scene` is untouched); the parts live one level down.
The rules code enforces, not the model:

- **The windows are the scene's**, parsed off the prompt (`parse_windows`; a single window,
  or none, means no timeline — the scene renders whole, as every scene before 2026-09-10
  does). An answer that does not give one shot per window is refused and the deterministic
  split (`fallback`: the window's sentence, the rest of the scene as continuity, every ref)
  is used instead, labelled `planner: "split"`.
- **A part's refs are picked by NUMBER from the scene's own refs** (the model is shown each
  photo under its number), dropped if out of range, and re-sorted into the scene's order — a
  part can only narrow the scene's grounding, so `reference_gate` on the scene still covers
  every part, and identity stays first.
- **Continuity is prepended in code** (`render_prompt`): `CONTINUITY …` then `SHOT n OF N
  (a-bs, Ns): …`. A model asked to repeat the scene's memory in every shot drifts by shot 4.
- **Staleness is checked on read** (`source` = hash of prompt + refs; `is_current`), the
  `seed_hash` pattern: a Director edit or a new ref makes it stale and `timeline.ensure`
  re-plans, carrying over any still/clip whose window, sentence and refs did not change.

Where it runs: `scene_chain.plan_timeline` after `attach_refs` in Create (in parallel, one
copied context per thread so `spend.bind` still attributes the calls), and in the graph's
`keyframe` node after `persist_prompt` (the refined prompt is the one that renders), whether
or not the night draws. **Keyframes:** `keyframe_scene` draws ONE STILL PER SHOT
(`_keyframe_timeline`) — the part's composed prompt, its own refs, the previous shot's still
labelled `CONTINUITY_REF_LABEL` (continuity, not composition), and a beat note saying it is
the shot's FIRST frame, because that is what its clip anchors on. Shot 1's still is the
scene's `reference_image`; a strip cut short by `NANO_DAILY_CAP` is finished by picking
again (`pick_skip_reason` only says "already has a still" once every part has one).
**Rendering:** `queue_approve` renders a timed scene through `_render_timeline` — every
part, in order, through the SAME `generate_for_shot(..., part=n)` each adapter already has
(all four grew `part`; `timeline.render_target` reads the part's prompt/still, and
`timeline.attach_part` stores the clip), so the spend approval, the daily cap and the
generations row are per clip exactly as before. Each part's length is its window fitted UP
to the model (`timeline.fit_seconds`: a 3s window is a 5s Runway clip, trimmed in the edit),
priced by `providers.check_timeline_choice`; the card's duration control is hidden for such a
scene. Parts with a clip are skipped and the loop stops at the first failure, so approving
again resumes rather than re-buying shot 1. When the LAST part lands, the scene's own
`media_url` is set to shot 1's clip — the marker every existing reader means by "rendered" —
**not** a stitched cut: the edit is still Mike's, in Resolve (the L1 hold), and the parts are
listed in order on the card for exactly that. The Queue card shows the shots (`_timeline_card`;
bare windows when not yet planned). `spend.STAGES` gained `timeline`.

**The references now actually get attached (2026-08-28).** The loop was open at its most
embarrassing point: `format_cast` tells the generator that Michael and the Ducati have
"(reference photos on file)", the scene it writes says exactly that, the photos sit in
`characters/michael` — and nothing ever handed them to a renderer. Every concept in the
live database carried `refs=None`, so Director grounded on a sentence instead of a face.
Three parts to closing it:

- `shootgen.named_assets(text, assets)` reads a finished scene back and returns the assets
  it named — the mirror of `format_cast`. Matching is on the asset's name **plus multi-word
  proper nouns from its own notes** (`asset_aliases`), because a prop is stored under a
  generic name while every scene calls it by its make and model. Two consecutive capitalised
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

**A REFERENCE URL IS THE PUBLIC ONE (2026-09-08, Mike: "the reference photos aren't
appearing").** A Queue card showed four empty tiles above a scene whose shot carried four
refs. The refs were right; the URLs were `/characters/michael/photo/...` and
`/refs/<sha>.jpg`, which are true only on the machine holding the folder —
`characters/`, `props/`, `locations/` and `data/refs/` are gitignored AND dockerignored, and
`data/` on Fly is a fresh volume, so the deployed site 404s every one of them. Worse than the
tiles: a renderer running there reaches for a face it cannot fetch, and the card still says
the clip anchors on a reference.

So what goes ON a shot is `asset_shelf.canonical_url(...)` — the public R2 URL when R2 is
configured, the local route when it is not. Three parts, and the third is the one to keep in
mind when adding a fourth writer:

- **One parser, `asset_shelf.parse_ref`.** Half a dozen callers each did
  `url.strip("/").split("/")` and read `parts[0]` as the kind —
  `shootgen.reference_label`'s caption binding, `in_scope`'s picked assets,
  `picked_locations`' room lock, `resolve_photo`'s wall. An absolute URL splits with
  `parts[0] == "https:"`, so every one of them fails **quietly**: a caption not written, a
  room not locked, a face not attached. They all ask `parse_ref` now, which reads both shapes.
- **The bytes go up where they are written.** `refbin.mirror_to_r2` on every bin save (a
  composer upload, a scouted image), `api._mirror_photos_to_r2` on every asset-photo upload.
  Both best-effort: an unconfigured or unreachable R2 leaves the local file exactly as it was.
  **Photos dropped into `characters/<slug>/` BY HAND still need
  `ops/backfill_reference_photos_r2.py`** — it is re-runnable and skips nothing.
- **The old rows keep working two ways.** `ops/canonicalize_shot_refs.py` rewrote the 104
  live concepts that carried local paths (a ref is only rewritten when `storage.key_exists`
  says the bytes are really there; 12 refs on #350/#351 point at bin files that exist nowhere
  and were left alone). And `app/main.py`'s photo routes plus the `/refs` mount fall back to a
  302 into R2 when the local file is missing, so a path written before today, or typed by
  hand, still renders on the deployed site.

`resolve_photo` still resolves an R2 URL back to the local file when this machine has it, so
his Mac reads its own photos off disk rather than over the network; `_photo_bytes` in
`app/api.py` is the fetch fallback for the machine that does not.

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
  idea, its references (uploads or picks out of the asset bank) and the scene length, and
  posts multipart to `/api/scenes/run`. **One Create writes ONE scene** (2026-09-10, Mike's
  call): the old 1–4 takes picker is gone, `SCENE_COUNT_MAX = 1` enforces it server-side
  whatever `count` a client posts, and `generate_scene_concepts` never saves more takes
  than it asked for. The multi-take generator itself stays (the graph and CLI can still
  ask for N); only Studio stopped offering it. The Pipeline composer, the legacy "Generate
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
  only one with a gate in front of it, and **approving in Queue is what calls the
  renderer** (`POST /api/queue/{id}/approve`). **Which renderer is picked on the card**
  (2026-09-08, Mike's call): the route dispatches through `providers.VIDEO_PROVIDERS`, so
  every registered adapter — Runway, fal (kling / ltx / wan / seedance), Higgsfield, Veo —
  is reachable from it, with a model, a length and a frame chosen per approve. It named
  `runway` in the route body before that, which meant the one surface that spends money
  could reach one of four working adapters, and a concept shootgen planned for KLING was
  rendered on Kling by the nightly graph and on Runway by this button, silently. The
  card's default is now the shot's own `tool` through `providers.platform_default`, the
  same binding `orchestrator.generate_render`'s connectors dict holds, so the two doors
  cannot disagree about what a tool name means. `providers.render_options()` is the menu
  and is a PROJECTION of each adapter's own dated spec table, never a copy;
  `check_render_choice()` REFUSES a length or a frame outside the model's legal set rather
  than clamping it (the adapters clamp internally — that is their contract with the graph,
  which has no human to refuse to). Every gate that was there is unchanged and in the same
  order: no prompt, not queued, no reference photos, the pick recorded before the spend,
  and the spend approval still checked inside the adapter's own `generate_video` so no
  caller can spend around it. **WHAT SATISFIES THAT APPROVAL CHANGED (2026-09-09, Mike's
  call): the click is the approval.** It used to be `*_SPEND_OK=1` in the server's
  environment, which meant this button did nothing until somebody restarted the server
  with a variable set — and once set for one render it stayed set for the session, which
  is exactly the "approval that's always on" the gate was written to prevent, reached the
  long way round. `spend_approved(approved=None)` now takes the caller's own answer and
  falls back to the environment only when nobody gave one; the routes a person drives
  (Queue approve, the board's per-shot render, `/api/generate/run`'s video branch,
  `/api/workflows/exec/generate`, and the Director canvas's Generate node) pass
  `approved=True`, and `orchestrator.py` / `autopilot.py` pass nothing — so an unattended
  run still needs `*_SPEND_OK` armed for it on purpose, on top of `ZEROPAGE_RENDER=1` and
  the L4 gate. `providers.usable()` (and so `choose_provider`) deliberately still reads
  the environment, because its only caller is the nightly graph's failover. **The daily
  caps are untouched and are now the only automatic wall** — `RUNWAY_DAILY_CAP` and
  friends, default 6/vendor/day, enforced from the generations table. `GET /api/queue/pending` is derived from the rows
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
stage — `ground`, `write_scenes`, `plan_timeline`, `persist_prompt`, `keyframe_scene`,
`park_scene` — so
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

**THE NIGHT NO LONGER DRAWS ANYTHING (2026-09-08, Mike's call).** `ZEROPAGE_KEYFRAME=0`
is the standing posture, not a temporary cut: a walk that draws every scene spends the
whole Nano cap on concepts nobody has looked at, and the night of 09-07 produced 75 stills'
worth of scenes with 0 stills and nobody the wiser. **The PICK draws the still instead** —
`scene_chain.draw_on_pick`, called from the board (`POST /api/concepts/{id}/pick`, as a
background job) and from the MCP `pick`, guarded by one shared `scene_chain.pick_skip_reason`
so the two doors cannot drift into billing a scene twice. It is skipped for a scene that
already has a `reference_image` (re-picking must not re-bill, and Director's own keyframe is
the one a person chose) and `ZEROPAGE_KEYFRAME_ON_PICK=0` turns it off. `NANO_DAILY_CAP` is
60: a pick draws one still per SHOT of a timed scene (one per beat of a one-window scene),
not one per scene.
**A walk is 5 sparks × 2 brands = 10 runs** (`NIGHTLY_SPARKS`, cut from every line of
sparks.txt — 20 — on the same day, "we'll increase it once I see it gets better").
The historical note: while the night did draw, only a scene whose prompt cleared the judge
(`score_prompts`, bar `prompt_gate_min`, fails closed) earned an image, and a keyframe that
failed parked the scene as text-to-video with the reason on its card.

**THE GATES ARE INVERTED (2026-09-07, Mike's call).** Measured over the graded holds, the
prompt gate agreed with his own would-post verdict **~38% of the time** — coin-flip
territory — and **no dimension of its rubric separated** what he would post from what he
would not. Predicting from the PROMPT whether a clip will be worth posting is therefore the
wrong lever, so the graph stopped doing it and selects **after the render** instead.
`ZEROPAGE_GATES` (`orchestrator.gates_mode()`, read per call) is the one switch:

- **`advisory` (the default)** — the LLM judges still score and still store: `critique`,
  `prompt_scores`, the hold payload, the parked reason on the scene. They just never route
  to `hold`. A failing prompt still gets its bounded rework (`MAX_PROMPT_REWORKS`, cheap and
  it measurably improves the prompt) and then proceeds to `keyframe` carrying its verdict —
  `"advisory: prompt gate 4/10 — no camera direction"` — into `park_scene`'s reason, the
  hold row's reason and the payload's `advisory` list. The morning review sees what the
  judge thought *beside the still it is judging*. Same for a low concept-judge score in
  `route_after_eval`: recorded in `critique`, no corrective re-run. **Only layer 2 — the
  rubric — stops routing.** The gate's deterministic layer 1 is code and still holds; see
  "what stays hard" below.
- **`hard`** — the pre-2026-09-07 hold-on-judge behaviour, byte for byte, kept tested (the
  gate tests in `tests/test_orchestrator.py` set it) because **an untested way back is not
  one**. Anything that is not literally `hard` reads as advisory: this is the one gate in
  the repo that fails *open*, deliberately — the cost of being wrong here is re-arming a
  judge that agreed 38% of the time, and that should be a decision somebody makes, not
  something a typo does to a night.

**What stays hard in BOTH modes**, because code enforces it and none of it is taste: the
`concept["warnings"]` retry loop (`validate_concept`'s — a shot naming a room that doesn't
exist is broken output), **the prompt gate's layer 1** (`_structural_check`: empty, under
fifteen words, a leftover `{token}` or TODO — a prompt with an unfilled placeholder renders
garbage whatever a judge thinks of the writing, so a `structural` failure still holds, after
its rework pass, exactly the line `route_after_eval` draws around `warnings`; the score
entry carries `structural: True`, an explicit flag rather than "score 0 with empty dims",
because the fail-closed judge produces that same shape and those are opposite things), clip
QC, `_post_gate`, the likeness rule, the uncanny/on-brand
judge (which records and never routed anyway), the kill switch, and every credit/spend gate
(`ZEROPAGE_RENDER`, the `*_SPEND_OK` approvals, the daily caps). A camera-only concept still
holds — there is nothing to keyframe and nothing to render.

**The statistic stays honest, which is the part worth checking on any edit here.**
`log_prompt_scores` still writes `passed = 0` for a shot the gate failed, whatever the run
then did, so `autonomy.prompt_gate_agreement` keeps measuring **the judge against Mike's
grade** rather than quietly measuring whether the pipeline let the run through — which, in
advisory mode, it always does. If an advisory run recorded itself as passed, gate-vs-you
would drift to 100% and the evidence that justified this inversion would erase itself.
`held_but_posted` (the cheap disagreement) is where advisory runs Mike would have posted now
show up.

**Selection moved to where it can actually be made: `select_clip`**, a node between
`qc_clip` and `caption`. With several candidates it picks by a code-only heuristic — QC pass
first, then longest duration (`_clip_duration`, the ffprobe wrapper inlined in the
orchestrator when the frame bank was removed), then
largest file — keeps every candidate in `clip_candidates` and the hold payload (the losers
are the only evidence of what was passed over), and is a no-op on one clip, which is every
run today. `orchestrator.JUDGE` is the documented seam for the video-level judge that can
answer the question the prompt gate was guessing at: set it and it is called with the
candidates and returns one of them; a judge that raises, or answers off the menu, loses its
say and the code pick stands.

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
a spark (typed, or scouted)  +  reference IMAGES  +  RAG library  +  brand brief
                                                  |
                        shootgen.generate_scene_concept(s)   <-- Studio Create, or the
                                                  |               nightly graph's gen_concept
                          shoot_concepts row: ONE scene, ONE prompt, refs on the shot
                                                  |
             timeline.plan: timed windows -> shots, each with its own refs + the scene's memory
                                                  |
                        no refs? -> archived immediately (preprod.NO_REFERENCE, never boards)
                                                  |
              Pipeline board: Pick (draws the keyframe) / Not this one (archives + reason)
                                                  |
                          Queue: Approve -> THE ONLY PLACE MONEY IS SPENT
                                                  |
                       a rendered clip on the shot; shot_done marks one that got MADE
```

**Cheap first, expensive on the picks — the shape survived, the unit changed.** A concept is
now ONE scene and ONE prompt, so the old `generate_concept_ideas`→`generate_shot_list` pair is
not the path any more: `generate_shot_list` became `write_scene_for_concept` (approve an idea →
write ITS one scene), `generate_concept` is gone entirely, and `generate_concept_ideas` survives
with no caller outside `shootgen`'s own CLI. The two live entry points are
`generate_scene_concept` (one scene) and `generate_scene_concepts` (N takes off one idea in a
single call, so they vary against each other). **The recorded labels are `picked_at` and
`shot_done`** — `pick_rate` and `shoot_rate`, both per prompt hash, which is what makes a prompt
change measurable rather than arguable. `shortlist_rate` was deleted with the shot-list stage
and is not coming back; with one scene per concept it could only ever read 100%.

Post-production (ingest -> pitch -> editgen, the manifest.json/pitches.json/concepts.json
chain) was removed in Aug 2026. The pipeline's output is a shot plan you go shoot; the edit
is yours, in Resolve, by hand.

- **`src/locations.py`** — scans `locations/<name>/`, sends each space's photos to Gemini vision,
  stores `{space, light_sources, textures, angles, constraints}` per location. Incremental: a
  space already described is skipped unless `--force`.
- **`src/shootgen.py`** — the scene writer, over a brand block from `prompts/brands.txt` plus
  whatever grounding the edge handed it. **Two live entry points:**
  `generate_scene_concept` (ONE scene, ONE prompt — the single-concept Create and the nightly
  graph's `gen_concept`) and `generate_scene_concepts` (N takes off one idea in a single call,
  so they vary against each other rather than being rolled independently — what Studio's Create
  button posts). `write_scene_for_concept` writes THAT idea's scene once it is approved, which
  is what keeps an idea from anywhere — including `rework`'s evidence-grounded slate — from
  being a dead end. `generate_concept_ideas` survives with no caller outside this module's own
  CLI; `generate_shot_list` and `generate_concept` are gone. `validate_concept` advises (never blocks): shot
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
  Two labels, not one: `pick_rate()` is how many generated scenes were worth rendering
  (derived from `picked_at`, counting only one-shot concepts), `shoot_rate()` is how many
  actually got MADE, by any means — the render lane, Higgsfield, a hand edit. Both break down
  per prompt hash. `reason_counts()` tallies why the rest were passed over, and
  `ungrounded_count()` reports the machine-archived ungrounded rows separately, deliberately
  outside both rates. `shortlist_rate` no longer exists.
- **`src/orchestrator.py`** — the autonomous content graph (LangGraph, registered as `zeropage`
  in `langgraph.json`): `planner -> ground_entities -> ground_rag ->
  gen_concept -> evaluate -> structure_prompt -> score_prompts -> generate_render ->
  qc_clip -> select_clip -> caption -> publish`, with the corrective `evaluate -> gen_concept` retry edge and
  a `hold` sink. `score_prompts` is the credit gate proper: a deterministic floor (thin /
  leftover template tokens, zero model calls — **no upper length bound**, removed 2026-08-14:
  a 130-word ceiling never fired across the first 17 scored prompts while six of eight judge
  failures were too *little* detail, and length is a quality judgment the judge's `coherence`
  dimension owns, not a broken-output signal this layer should reject on) under a strict LLM judge
  (subject/camera/motion/lighting/coherence, 0–2 each, bar `PROMPT_GATE_MIN`, default 7/10)
  that **fails closed** — an unreadable verdict scores 0, so a credit is never spent on a
  judgment nobody could read. One failing prompt used to hold the whole run, reason = the
  judge's own one-liner; **since 2026-09-07 that happens only under `ZEROPAGE_GATES=hard`** —
  by default the verdict is recorded and the run proceeds to the keyframe carrying it on the
  card, with the selection moved after the render into `select_clip` (see "THE GATES ARE
  INVERTED" above for the 38%-agreement measurement behind it, what stays hard, and the way
  back). Every score is still a `prompt_scores` row logged before any spend — an advisory run
  logs `passed = 0` exactly as a held one did, so the number below keeps measuring the judge
  rather than the pipeline. Grading a hold on
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
- **`src/fal.py`** — the fal.ai connector, and the module that woke the four dormant
  platforms (2026-09-08). `shot.PLATFORMS` had carried prompt renderers for `kling`,
  `ltx`, `wan` and `seedance` since the registry was written with **no execution
  adapter**, so half the tool vocabulary was writable and unrenderable: a shot planned
  for KLING came back "no adapter wired for KLING" every night. fal hosts all four
  behind one queue API and one key, so **one** adapter (one entry in
  `providers.VIDEO_PROVIDERS`, a dated `VIDEO_MODELS` table, `fal.connector(platform)`
  bindings in `orchestrator.generate_render`'s connectors dict) closes all four gaps —
  not four registry entries pretending to be four vendors. higgsfield.py's shape exactly:
  thin raising `generate_video` (submit → poll → **fetch the response_url** → download)
  under never-raises edges, `FAL_SPEND_OK=1` per run, `FAL_DAILY_CAP` /
  `FAL_GLOBAL_DAILY_CAP` through `generative.cap_error`, BYOK via `account_keys`
  (`FAL_KEY`), `key_source` on every row, and `_safe_error` redacting the account's own
  stored key resolved with the account_id. **A row is logged under the PLATFORM that
  rendered it** (kling/ltx/wan/seedance), never under "fal" — the scoreboard asks which
  model makes keepable clips, and one "fal" row would average a $0.30 LTX clip with a
  $1.51 Seedance one. `generations_today` therefore sums the four. Two contract facts
  worth carrying: the result is a **second request** (fal's terminal status payload is a
  receipt, higgsfield's carries the asset), and **fal documents no FAILED status** — a
  dead job answers `COMPLETED` with `error`/`error_type`, so failure is detected by
  looking for the fields and by the deadline, never by waiting for a status string.
  FLUX rides the same queue under the image tool name `fal` (`generative.IMAGE_TOOLS`),
  deliberately outside the video cap. Every model id and per-second price is dated
  2026-09-08 with its source URL in the table; re-check before trusting one, and note
  the vendor namespaces (`alibaba/wan-3.0/*`, `bytedance/seedance-2.0/*`, not `fal-ai/`).
  Veo is available on fal and deliberately NOT registered here — veo.py owns that
  platform and two adapters sharing one daily cap is a surprise bill.
- **`src/shot.py`** / **`src/promptgen.py`** / **`src/genlog.py`** / **`src/generative.py`** — the
  generative-clip side: the typed vocabulary every tool prompt compiles from. `shot.py` is a `Shot`
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
  watch", and a keyframe fed back in produced the same man in the same jacket and room
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
  connector), which fires when `RUNWAYML_API_SECRET` is set — pressing it IS the spend
  approval since 2026-09-09, so the route passes `approved=True` and no environment
  variable stands between the button and the render. API calls always burn API credits
  even on the Unlimited plan, so the module's own gate inside `generate_video` is still
  the wall (an unapproved caller is still refused there), the button shows the priced
  estimate, and refusal points at the free app path. Every
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
- **The Director canvas is the Gen Space (2026-09-10, from the "ZPF Gen Space" design;
  the shape LTX Studio's gen space has).** `app/static/zpf/genspace.js` replaced
  `workflows.js` and the vendored LiteGraph: ONE shot's chain drawn as DOM cards on an
  infinite dot-grid canvas -- the prompt and its instructions, the scene's reference sets
  (a character's frames, a room's plates, the composer's uploads) as their own cards,
  the Gemini enhance, the Nano keyframe, the Runway model and a derived Output card --
  wired with real links; a floating prompt bar underneath edits the shot's prompt and
  an `@`-mention drops the element on the canvas already wired in; zoom/pan/fit, a cut
  tool, a minimap, a per-node inspector (camera presets fold into the prompt -- the
  runner has no camera parameter), and **Send to Queue**, which only PICKS: approving
  in Queue is still the one spend gate. A bitmap canvas could name a face but never
  show one, which is why LiteGraph went. **The JSON is still LiteGraph's serialize()
  shape** -- the runner, the saved shot graphs and the seeded template are untouched by
  the swap -- with one addition on both sides: `zpf/reference_set` (a pure node whose
  value is its url list) and a `refs` input port that takes SEVERAL wires
  (`workflow_runner.MULTI_LINK_PORTS`; the slot carries `links: [...]` beside the
  single-link `link`, and `node_reference_urls` reads the port right after the wired
  keyframe). The billed nodes' frozen `ref_urls` are rewritten from the wires before
  every save (`freezeRefs`), so the drawing and the run never disagree. The rail
  hover-expands with labels, a Queue badge (`GET /api/queue/pending` count, refreshed on
  picks, decisions and finished jobs) and the account row; the bar carries Director's
  own controls only while the canvas is up (`html[data-gs="canvas"]`). Not built from
  the same design set: the Elements page (the rail keeps Analytics until it exists).
- **The overnight branch reconciled into main (2026-09-12).** `claude/overnight-20260907`
  (13 commits: the corpus/gates/nightly/distribution/research builds, the credit ledger,
  fal.ai as one adapter for the four unwired platforms, the Runway Unlimited lane, public
  reference URLs, the studio no longer reading local video) was merged on top of the React
  studio. Where the two had built the same thing on the same day -- the subscription lane
  and the approve selectors -- **the overnight implementation won and the main-side one was
  removed**: the gate is `accounts.manual_lane_operator` read through
  `manual_lane.manual_lane_allowed` (same column, same CLI, so the flags already set on the
  live database carried over), the lane is `GET /api/queue/manual` +
  `POST /api/queue/manual/{id}/clip` (field `file`; one `ops/render_queue.import_clip`
  behind both the CLI and the browser; `render_specs` refuses a claim it cannot have
  produced; a second drop is 409; **the lane lists PICKED scenes only** -- 2026-09-14,
  Mike's call: a scene the night parked is the Queue's to approve, which picks it, and it
  joins the lane the moment it is picked, since the lane is a person's hands per clip and
  takes only what a person chose), and approve takes `{provider, model, duration, frame}`
  through `providers.check_render_choice` across every registered renderer. The React
  Queue (`web/src/app/studio/queue/page.tsx`) reads `renderers` off `/api/queue/pending`
  for its selectors, `manual_lane` off `/api/capabilities` for the lane's visibility, and
  posts the lane's mp4 to the overnight route. `_runway_state.models/ratios/durations`
  stay for the Gen Space chips, projected off `render_specs` rather than a second table.
  Not merged: the main checkout's UNCOMMITTED work on that branch (`/api/brains`,
  `/api/scene-lengths`, `/api/render-choices`, `/api/creative-guide`, `app/creative_projects.py`
  ...) -- another session's in-progress tree, which stays its own to commit.
- **`web/` is the React front end; `frontend/` is its predecessor (2026-09-11).** Both had
  only ever lived untracked in the main checkout. `web/` is the v0-bootstrapped Next.js 16
  project: the landing page at `/`, and under `/studio` the signed-in product — one shell
  (rail with Studio / Assets / Pipeline / Director / Elements / Queue, **Analytics gone in
  favour of Elements**, Mike's call), the Studio composer (`/api/scenes/run`), the
  Director on React Flow (`web/FLOWS.md` — element cards, the `refs` multi-wire port,
  @-mentions, Run all, Send to Queue) and Elements (`/api/assets/*`). It proxies to
  FastAPI (`API_UPSTREAM`), so sign-in and every gate stay here; `GET /api/me` is the
  one route added for it (identity + membership, composed from `auth.current_user` /
  `accounts.memberships` so the two shells cannot disagree). Assets (the date-grouped
  media wall off `/api/media`, with the detail rail and "Use in a shot" → `/studio?attach=`),
  Pipeline (the board: pick / archive / restore, the prompt editable in place) and Queue
  (the spend gate off `/api/queue/pending` + the job registry) are React pages too
  (2026-09-12), so nothing in the rail opens the Jinja `/ui` any more. `frontend/` is
  the Vite + React composer that preceded it, kept as received; its `/api/brains`,
  `/api/scene-lengths`, `/api/render-choices`, `/api/creative-guide` and the guide mode
  exist only as uncommitted work in the main checkout's overnight branch, and the Next
  composer shows those pills only when the routes answer. The vanilla Gen Space on `/ui`
  stays as the reference implementation the React one was ported from.
- **The overnight session's working tree landed on main (2026-09-12, second
  reconcile).** Everything that had sat uncommitted in the main checkout on
  `claude/overnight-20260907` -- the creative guide (`src/creative_guide.py`,
  `POST /api/creative-guide`, a job), creative projects, the shot timeline
  (`src/timeline.py`, `GET /api/scene-lengths`), `GET /api/brains` and
  `GET /api/render-choices` (the composer's pills, PROJECTED off
  `gemini_utils.BRAINS` and `render_specs`), personal model runtimes
  (`src/personal_models.py` + `app/model_connections.py`: a person's own
  ChatGPT/Claude CLI login, sessions under `data/model_sessions/` on the
  volume, never in the image -- hence the `model-runtime` stage in the
  Dockerfile that ships the Codex CLI), per-account renderer keys, the
  Pinterest token scripts and the vanilla studio's panels for all of it --
  was committed as found (99c9ce9) and merged. Left out on purpose: the
  media under `docs/reference-look/sprint4` and `wide_worlds_keyframes/`,
  `imports/`, `data/*.bak*`, and Codex's own `.agents/` + `AGENTS.md`.
  **Two decisions in the merge.** The deploy shape stays TWO Fly apps: that
  tree bundled the Next app into the API image behind nginx on 8080 with only
  `/studio/flows` proxied, while main already serves the whole `/studio` from
  `zeropage-web`; the API image keeps the Codex stage and drops the Next
  build, nginx and the director/proxy supervisord programs. And the vanilla
  `/ui` hands a PLANNED concept to the React Director: `DIRECTOR_FRONTEND_URL`
  (fly.toml points it at `zeropage-web.fly.dev/studio/flows`; locally it
  defaults to `:3000`) reaches the body as `data-director-url`, and
  `genspace.openConceptInDirector` redirects there unless `?legacy=1` asks for
  the vanilla canvas -- ported from the `workflows.js` edit, since that file
  no longer exists. The Generate node's gate note reads `video.generate`
  (any keyed renderer), not Runway's key alone.
- **`src/mcp_server.py`** + **`app/mcp_mount.py`** — the MCP surface (2026-08-31), so the
  board can be read and decided on from a phone or an agent instead of only from this
  machine. **An adapter, never a store:** every tool is a thin call into `preprod` or
  `scout`, and `data/pipeline.db` stays the one source of truth — a synced second store is
  the mistake `asset_shelf` exists to fix. The read/decide tools (`board`, `idea`,
  `search`, `capture`, `pick`, `shoot`, `archive`, `add_spark`, `tonight`, `sparks`,
  `images`, `stats`, `job`) are always on. **`pick` is the ONE that spends, and only
  cents** (2026-09-08, Mike's call — a deliberate amendment to "nothing on them spends",
  not an oversight): it draws the scene's keyframe through `scene_chain.draw_on_pick`,
  because the night stopped drawing and the pick is what earns a still, so a pick from a
  phone that produced nothing meant the two doors disagreed about what picking means. A
  failure comes back as `keyframe.note` on the card and NEVER as a tool error — an agent
  that sees an error retries the identical call, and the retry is what would spend twice.
  Everything else there still spends nothing. Picking still only
  puts a concept in front of the Queue, and approving there is still what calls the
  renderer, still on this machine — the single spend gate for the CLIP is load-bearing, and a second
  door onto it from a phone is exactly how it stops being one. **`shoot` records that a concept got
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
  **`generate` runs from the spark's bin (2026-09-03).** It took a spark string and nothing
  else, and `orchestrator.run` with an explicit spark never reads the bin — the scout node
  acts only when asked to CHOOSE the direction — so an agent could bank six frames behind a
  spark with `reference` and generate from it with none; #169–#172 had references only when
  started in Studio. `mcp_server.resolve_finding` now names the finding (an explicit
  `finding_id`, or the spark text matched on `_spark_key`, the composer's `claims` rule), its
  bin becomes `reference_photos`, and `orchestrator.run(scout_finding_id=)` carries the id so
  `planner` claims it and the hold card says where the idea came from. A reworded spark with
  a `finding_id` is refused rather than silently stripped of the photos the way the composer
  does it — an agent acts on a message where a person would have seen a tile vanish. The
  composer closes the same loop from its side: when a Create IS the spark, `scout.bank_urls`
  writes every uploaded `/refs/` photo into the finding's bin (lane `composer`), so
  `images(finding_id)` reads what Studio attached and a later run on that spark, from either
  door, sees it. Asset-bank picks are not banked — a room or the cast is grounding the graph
  adds for itself.
  **The card says which door wrote a row, and what the graph decided (2026-09-03).**
  Four rows (#169–#172) were read from a phone as "MCP-generated, never judged, never
  keyframed" — but they were Studio Create pairs (one prompt hash per pair, no
  `written_prompt`, no hold row), and Create stops on the board by Mike's 2026-08-29 call.
  The score that made #167 look "judged" was `judge_overall`, which is the Dev Studio's
  MANUAL taste judge (`/concepts/{id}/grade`); no automated path has ever written it, so on a
  graph row it reads null however the run scored. The graph's real verdict lives in
  `prompt_scores` (by `run_id`) and the hold row's reason, and neither reached the MCP
  surface — an agent asked why #173 held at 5/10 had nothing to say. `idea` now carries
  `origin` (`graph` / `studio` / `capture`, derived from whether a hold row exists — `_park`
  runs on every terminal edge, so a graph row always has one) with a `note` saying what a
  null judge means there, and `gate` (`autonomy.hold_for_concept` +
  `prompt_scores_for_run`: score, passed, reason, every score the run logged so a rework's
  effect is visible, and how the run ended). `generate` returns the same `gate` with the
  run. `judge_*` keeps its name and its meaning. Nothing in `run_graph` returned early; the
  diagnosis was two surfaces being read as one.
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
  Page concept on the board named a recurring character or prop off the asset shelf**, in
  the brand whose whole
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
- **`src/spend.py`** / **`src/costs.py`** — the cost tracker (BACKLOG #2, 2026-09-04).
  `spend.record_call` writes one OWNED `llm_calls` row per Gemini call -- the model that
  actually answered, raw token counts, an estimated `cost_usd` from `DEFAULT_PRICES` (read off
  the pricing page that day; `SPEND_PRICES_JSON` overrides), a `stage` from the closed
  `STAGES` list, and the account + graph run id from `spend.bind()` (jobs.start binds the
  job's account in its worker thread, the orchestrator's planner binds the run's uuid). It
  lives INSIDE `generate_with_retry` because only that function knows which model replied
  after a fallback; the five raw sites and the research agent call it themselves. **The meter
  never raises.** No usage counts = UNPRICED (NULL), never $0; a render with `cost_usd` NULL
  is FREE (subscription), never backfilled. `costs.summary` is the four numbers on `/costs`
  and `GET /api/costs`: cost per kept clip per tool, cost per stage per night, wasted spend,
  today against the caps. Every figure is an estimate and the page says so; embeddings are
  not metered.
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
  (ONE exception since 2026-09-08: the reference gate above rejects, because "was this scene
  handed photographs" is a fact about the row rather than a judgment about the writing. If you
  are adding a second exception, you are probably not — write a warning instead.)
  (The orchestrator adds one twist: it *uses* the warnings to retry, but the saved result
  still carries them.)
- **Grounded in what exists — and since 2026-09-08, NO PHOTOS MEANS NO BOARD.** Every stage
  generates *from* real material: the cast and props on file, the reference library, proven
  winners, and the photos attached to the run. A mismatch is still only a warning, and a missing
  grounding SOURCE still degrades to an ungrounded run with a note — the rule below about
  advising rather than rejecting is intact for everything except this one thing.
  **The exception, and it is deliberate (Mike's call).** A finished scene carrying no
  `shot["refs"]` at all is archived the moment it is written, with `preprod.NO_REFERENCE`, and
  can never reach the Queue. `preprod.reference_gate(concept)` is the single predicate; the two
  writers (`scene_chain.run`, `orchestrator.gen_concept`) apply it, and `app/api.py`'s `_waiting`
  + `queue_approve` and `ops/render_queue.py`'s `pending` all ask it again at the spend.
  `ops/archive_ungrounded.py` is the repair pass for rows written before it (87 archived on the
  day, of 152 live).
  What made this worth breaking the convention for: the board was showing cards reading
  "KEYFRAMED · AWAITING APPROVAL IN QUEUE" beside "NO REFERENCES". That keyframe is a still
  Nano drew **from the prompt**, so approving one spends a Runway credit anchoring the clip on
  the pipeline's own guess — and the whole point of the reference layer is that it should not.
  Hence `reference_gate` reads `refs` and NOT `reference_image`: a frame this pipeline drew is
  not evidence that anything grounded it.
  It deliberately does **not** check the prompt as well. A prompt is on `shots_json` only
  because `score_prompts` put it there, and a second bar at the spend gate would be a second
  opinion disagreeing with the first — see "THE GATES ARE INVERTED" for why re-arming that judge
  is a decision somebody makes on purpose.
  `NO_REFERENCE` is a MACHINE reason, kept out of `ARCHIVE_REASONS` and excluded from
  `pick_rate`, `shoot_rate` and `reason_counts` (`preprod.MACHINE_REASONS`). Nobody judged these
  concepts, so counting them as ones Michael passed over would read a grounding failure as a
  verdict on the writing — and `pick_rate` is the number that decision rests on.
  `preprod.ungrounded_count` reports them separately, which is the figure to watch: it climbing
  means the crawl stopped attaching photos, and that otherwise looks exactly like a quiet night.
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
- **The human choice is the label, and it gets recorded.** `shootgen.py` writes scenes, a human
  picks some (`picked_at` → `pick_rate`), and fewer still actually get made (`shot_done` →
  `shoot_rate`). Stored with the prompt's hash, so a prompt change can be measured against the
  rate it produced rather than argued about. **Passing is a label too:** `archive_reason`
  (`preprod.ARCHIVE_REASONS`) is the only idea-level negative signal this system collects, which
  is why leaving the board archives and never deletes. The pick and the Queue's Approve are the
  two manual gates; Approve is the one that spends.
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

**Working and verified against real data** (counts read off the live Postgres 2026-09-09):
the ideation loop runs end to end on real Gemini calls. **232 concepts** written, **107**
carrying reference images on the shot, **68** with a keyframe drawn, **178 archived** with a
reason, **4 picked**, **9 marked shot**, **274 recorded graph runs**, 100 generation attempts,
1610 metered LLM calls, 10 posted videos, 3 described rooms. Reference-grounded ideation is
verified live both ways: `src.shootgen --spark "gearing up ritual"` printed "Grounding in 5
retrieved reference(s)" against the real library, and the same command with the store pointed at
a dead URL printed the ungrounded note and still produced ideas (exit 0). **1956 tests pass, 8
xfail**, ruff clean, CI green on every push.

**The number that matters and is not moving: 0 concepts carry a `media_url`.** Nothing has been
rendered onto a concept row. 4 picks against 232 written is the real shape of this project —
generation is cheap and abundant, selection is the bottleneck, and the spend gate has barely
been used. Read every rate below in that light.

Post-production (ingest/pitch/editgen, `/pitches`, the assistant's `cut` intent) was removed in
Aug 2026 — the DB keeps historical pitch-run rows, but nothing generates new ones.

**Structurally complete, statistically empty:** the L2→L3 loop is built and verified live —
`promote_winners propose` honestly reports nothing clears the bar (no videos measured at equal
age yet), and `src.rework` generates an evidence-free slate with the note. `pick_rate`,
`shoot_rate` and `post_seo`'s signals are structurally correct and currently close to
meaningless — they need weeks of real posting before a prompt change can be measured or a slate
genuinely reworked from evidence. (`db.selection_rate` is a different, surviving thing: it
measures kept-vs-attempted on generative CLIPS, not concepts.) **The most valuable next step is
still not code** — it is taking one written concept all the way through Approve to a rendered
clip, posting it, and recording metrics. L4 exists as `src.autopilot` — gated, dry-run, default
off, executors unwired.

**Known gaps, in rough priority:**
- **Timed scenes (2026-09-10) are rendered shot by shot only at the Queue.** The graph's
  `generate_render` (a dry stub unless `ZEROPAGE_RENDER=1`) still renders a scene's whole
  prompt as one clip, and the Director canvas still edits the whole scene prompt rather than
  one shot of it. Both read `shot["timeline"]` for free when they are taught to. The Queue
  card's `fitSeconds` is a JS twin of `timeline.fit_seconds` (the price label); the server's
  `check_timeline_choice` on the approve response is the authoritative figure.
- `src/fal.py`'s image-to-video field name is `image_url` for every model in the table;
  that is documented for Seedance 2.0 and inferred from the playground's "Start Image
  Url" label for Wan 3.0 and LTX-2.3. Verify on the first live i2v render for those two.
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

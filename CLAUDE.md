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

## Claude Code mods

Three mods for how this repo is actually driven (`/ship`, `/merge`, `/wrap`,
`/handoff`, `/servers`, `/ci`, a spend guard, a CI watcher) live under
`.claude/skills/zp-*`; `docs/CLAUDE_MODS.md` says what each does, how to load
them, and what else the session logs suggested.

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

# THE INSTAGRAM TOKENS — two credentials, two hosts (src/instagram.py).
# check is read-only (one call each, never prints a value); refresh/publish/
# research write .env with a backup. `keep` is THE ONLY SCHEDULED JOB in the
# project (2026-09-28): daily at 10:00 ET on FLY ONLY (the image's one cron
# line, log in /app/data/ig_token_keeper.log); it makes no Meta call until
# the publishing token's last refresh is 30 days old, then refreshes it into
# the store -- never .env. The Mac runs NO LaunchAgent, by Mike's choice: its
# copy of the token (last refreshed 2026-09-26) is kept alive only by a hand
# `refresh`, and matters only for posting or metrics from the local server.
venv/bin/python -m ops.ig_tokens check [--probe]
venv/bin/python -m ops.ig_tokens refresh|publish
venv/bin/python -m ops.ig_tokens keep [--days 30]
venv/bin/python -m ops.ig_tokens research --app-id <research app id>

# THE NIGHTLY WALK IS GONE. Unscheduled 2026-09-28 (Mike's call: the Mac's
# com.zeropage.morningprompts and com.zeropage.shadowrun agents were unloaded
# and renamed .disabled.20260928 in ~/Library/LaunchAgents, and the Fly cron
# line that called run_morning_prompts.sh was replaced by the token keeper),
# then DELETED 2026-10-07 (Mike's call): src/nightly.py, run_morning_prompts.sh,
# ops/fly/run-nightly.sh + nightly.md, the db.nightly_runs receipt and its
# "Last night" line on the Dev Studio, costs.spent_since. The live Postgres
# nightly_runs table (18 rows, 2026-09-08..09-27) was dropped the same day,
# after the deploy that stopped creating it. classify_error
# (SYSTEMIC / CONTENT) moved to src/trigger.py, its one remaining caller.
# The research agent, the scout crawl and the metrics sweep run only by hand:
# `src.research_agent`, `src.scout run`, `src.refresh_metrics`. Everything
# below that says "the nightly" or "the night" is history, or means a graph
# run nobody is watching (`src.trigger`, the MCP `generate`).

# THE SHADOW RUN — one run, spark rotated from prompts/sparks.txt. MANUAL
# ONLY: nothing schedules this. The 03:30 launchd job was removed
# 2026-09-14 because it took neither the nightly lock nor the budget, so it
# ran an eleventh time beside the 22:00 walk. With the walk deleted
# (2026-10-07) this is the CLI door into the graph; exit 2 means the crash
# was systemic (trigger.classify_error), 1 that it was about the concept.
# Grading happens on /holds each morning. --scout takes the direction from
# the scout's bank instead, falling back to the rotation when the bank is
# empty or under scout.SCORE_FLOOR.
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
venv/bin/python -m src.mcp_server   # stdio; Claude Desktop launches this itself
# Since 2026-10-07 (Mike's call) the stdio default is the STUDIO surface:
# generate_image / generate_video / apply_effect (src/effects.py: image edits,
# Kling + PixVerse template effects, PixVerse camera moves, Topaz upscale/fps,
# MMAudio sound) and element_sheet, each quoted first IN CREDITS and spent only
# after a yes in chat (quote_token: signed over the exact request, used once --
# a SIGNING SECRET is needed, QUOTE_SIGNING_SECRET, or nothing can be approved),
# plus cancel_job (stops one; the money follows fal's own answer), assemble_clips
# (joins gen:<id> clips into one MP4 on this server, free, filed on the wall),
# import_file (a file from ~/Downloads, ~/Desktop or data/ -> asset:<id>; studio only),
# edit_clip (a clip changed by instruction: ONE frame as a still first, then the clip), and
# image_models / video_models / effects / elements /
# renders / images_for / prompt_craft, and PROJECTS (projects / project /
# project_chat / create_project / save_chat; project_id on a render files it there).
# NO board tools. --surface board (or
# ZEROPAGE_MCP_SURFACE=board) serves the full board; src/research_agent.py
# asks for it by name. The Guide and the HTTP mount build the board surface.
# Registering it: ops/connect-claude.md (paste ops/claude-desktop-mcp.json -- two entries,
# `zeropage` = studio and `zeropage-board` = --surface board --engine -- then ⌘Q, reopen)

# THE MANUAL RENDER LANE — a clip that reaches a concept without an API render.
# ONE lane since 2026-09-28: the generic `manual` import (a clip rendered
# anywhere, filed free -- it was the Runway Unlimited lane until 2026-09-26).
# The Higgsfield-MCP lane was REMOVED that day (Mike's call); its old
# `mcp-subscription` rows still read as FREE (src/higgsfield.py itself was
# removed 2026-09-29). Mike expects to retire this import too
# (docs/BACKLOG.md #21). `list`
# says what is waiting, `import` files the mp4 into data/renders/manual/
# and writes a FREE row (cost_usd NULL, params.source = the lane marker, so
# ledger.is_billable takes no hold). The lane is OPERATOR-ONLY —
# src/manual_lane.py's gate is the accounts.manual_lane_operator COLUMN (the
# env vars are gone), checked server-side against the account id on every
# surface, fails closed (nobody, until somebody is turned on). Turn it on:
venv/bin/python -m src.accounts operator <slug> --on   # --off to revoke
# THE ACCOUNT FLAGS WRITE TO WHATEVER `DATABASE_URL` IS EXPORTED -- and
# `src.accounts` never loads `.env`. With nothing exported, `operator`,
# `edits-teach` and `credits` fall back to db.DEFAULT_DSN (the LOCAL throwaway
# Postgres), create the auth tables there, and answer "no account '<slug>'"
# with no list of known slugs -- that empty list is the tell (found 2026-09-18,
# turning `credits` on for antihero). To move a flag on the LIVE database:
set -a && source .env && set +a && venv/bin/python -m src.accounts credits <slug> --on
# The API-billed renderer (fal) is untouched by it. See docs/RUNBOOK.md 2026-09-08.
python3 ops/render_queue.py --account <slug> [--provider manual] list
python3 ops/render_queue.py --provider manual --account <slug> import \
    --concept N --shot 1 --file clip.mp4 --model "kling 3 web app" --duration 10

# FAL RECOVERY — a fal render whose worker died (a deploy restarting the API
# mid-poll) is finished, not orphaned. The app lifespan runs this on boot
# (FAL_RECOVER=0 turns it off); by hand it is one sweep, printed:
venv/bin/python -m src.fal_requests [--account N]

# THE CUT (Assemble v0, docs/CUT_EDITOR.md) — a rendered scene's clips, in the
# order it was written, on a versioned timeline -> ONE MP4 (ffmpeg, -14 LUFS,
# optional music bed ducked under the clips' own sound). No CLI: the Queue's
# "Ready to cut" strip posts /api/cut/assemble. Nothing here spends.
# THE INDEX (phase 2) — what is IN each clip, so the editor can search it.
# One Gemini shot log per clip + fal Whisper (word level) only when the log
# heard speech. Cents per clip, metered (stages shot_log / transcribe), not
# charged in credits. Export DATABASE_URL first, like src.accounts.
venv/bin/python -m src.cut.index backfill [--account <slug>] [--dry-run]
venv/bin/python -m src.cut.index one gen:85 [--force]

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

# SUPABASE AUTH EMAIL — what is set (custom SMTP, the four templates, Site
# URL, the hourly limit) and the whole setup in one PATCH through the
# Management API (docs/SUPABASE_EMAIL_TEMPLATES.md). Needs a personal access
# token in SUPABASE_ACCESS_TOKEN; `report` is read-only, `apply` touches only
# the flags given and refuses a field the live config does not carry.
venv/bin/python -m ops.supabase_auth_email report
venv/bin/python -m ops.supabase_auth_email apply --templates [--smtp-host ...] [--dry-run]

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
sign-out-everywhere (docs/BACKLOG.md #22); email verification is Supabase's.
**Passwords and settings (2026-10-03, Mike: "Supabase didn't send a code or allow a new user
to create a password").** The sign-in page's password step now offers "Create a password"
(`/auth/signup`, with a confirm field) and "Forgot your password?" (`/auth/forgot` → GoTrue
`/recover` with a PKCE challenge → `/auth/reset`: the emailed CODE with a new password on one
screen, or the emailed LINK through `/auth/callback`, which parks the recovery session and
lands on a new-password screen instead of signing in). `/studio/settings` (the account menus)
is the person's own page: rename, set a first password or change one, change the email, see
and switch workspaces. **Every password or email write re-proves the person first** — their
current password (`/token?grant_type=password`) or a code mailed by `POST /api/me/security/code`
(`/recover`, verified as `type=recovery`) — because GoTrue takes `PUT /user` only AS the person
and this app stores no token of theirs; the one-call session is minted, used and dropped
(`auth.user_session_by_password` / `user_session_by_code` / `set_user_fields`; the `gotrue`
seam gained `token=`). `users.password_set_at` (additive column) is what the page reads for
"set" vs "change"; a password sign-up, login, reset or change stamps it, and unknown reads as
not set. An email change is only a request until the person clicks Supabase's confirmation;
`accounts.claim` moves the mirror row's email to the identity's at the next sign-in (never
onto an address another row holds). **The code not arriving is a Supabase dashboard matter,
not code:** its built-in mailer delivers only to the org's own members, and the default
templates carry no `{{ .Token }}` — `.env.example`'s Supabase block and `docs/RUNBOOK.md`
2026-10-03 say what to set. **The emailed LINK is `GET /auth/confirm?token_hash=&type=`**
(same day, read off the live auth logs: a tester's PKCE link failed in a mail app's browser
and was pre-fetched by Gmail's scanner): verified server-side with GoTrue's
`POST /verify {type, token_hash}`, no verifier cookie, any browser; a `recovery` link lands
on the new-password step. `docs/SUPABASE_EMAIL_TEMPLATES.md` is the four template bodies to
paste; `/auth/callback` stays for OAuth and for a template not yet switched.
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

**FAL IS THE ONLY VIDEO RENDERER, AND BYOK IS GONE (2026-09-26, Mike's call;
docs/tasks/task-fal-only.md).** Every video door -- Queue approve, approve-all,
the Director Generate node, the board's per-shot render, the nightly graph,
autopilot -- renders through `src/fal.py` on the operator's `FAL_KEY` and holds
credits (`src/charge.py`). `src/runway.py`, `src/veo.py` and
`src/account_keys.py` are deleted; `src/higgsfield.py` followed on 2026-09-29
(Mike's call -- the Soul stills too: refgen falls back Midjourney -> Nano, and the
unreachable `scene_chain.visual_target` went with it); Veo lives on as the fal
model `veo3.1`. `providers.VIDEO_PROVIDERS`
is `{"fal": fal}`. A shot still carrying `RUNWAY`/`HIGGSFIELD` as its tool is
read as the fal default at render time (`providers.platform_default`,
`RETIRED_PLATFORMS`) and never rewritten. `ledger.is_billable` has one
exemption left -- the manual lanes' `source` marker -- plus the operator's
`credit_exempt` column in `hold_for_render`. Pricing is v3
(`2026-09-26-fal-v3`): model x RESOLUTION x seconds off `fal.VIDEO_MODELS`
(dated, re-checked against each model's `/api` schema that day) x `MARKUP`;
bands are per resolution (`providers.BAND_BY_FRAME`: 1080p Seedance and all of
Veo are premium). `fal.fit_duration` fits a length UP to a model's enum
(LTX-2.3 takes only 6/8/10s; Veo "4s"/"6s"/"8s") and `build_body` sends it in
each model's wire shape and image field (Wan: `start_image_url`). The
`account_keys` table is dropped by `db.drop_account_keys_table` once empty (it
held 0 rows live). Much of the prose below predates this and still names
Runway as a renderer; where it does, fal is what now happens.

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
them — filling a total length (`timeline.scene_seconds`: the composer's length slider via
`GET /api/scene-lengths`, else `ZEROPAGE_SCENE_SECONDS`, else 10; clamped 4–30, never
refused). Both writer templates get `{seconds}`, and tell the writer each window is rendered
as its own clip, so each window must be ONE shot (one camera setup, one clear action, 2–10s).
**How MANY shots is the idea's (2026-10-02, Mike's calls):** "as many shots as are needed by
the prompt", never a habitual three — the writers no longer carry a three-window example.
Two or more windows by default; ONE only when the person asked for a single take ("I don't
want just one continuous shot unless asked for in the prompt or chatting with the agent");
a count the idea already sets — its own timed windows, which is how the Guide's brief arrives
after "bring it down to 2 shots", or "in 2 shots" in so many words — is kept, scene by scene.
Code advises: `timeline.shot_count_warnings` adds a concept warning when the count is not what
was asked (`requested_shots` / `one_take_requested` read the idea), checked against the
DIRECTION, never the steer. **No cap**: `MAX_PARTS = 8` silently dropped every window past the
8th off the card, the price and the render; it is gone, and the priced approve is the limit.
The React composer's length is a **slider** (`components/studio/duration-pill.tsx`), any whole
second between the route's `min` and `max`; `SCENE_SECONDS_CHOICES` is only the legacy select.
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
priced by `src/pricing.py` (`display()` on the card, `quote()` at approve — only the shots
still without a clip are priced); the card's duration control is hidden for such a
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

**MEDIA IS MULTI-TENANT NOW, AND THE STORED STRING IS A NAME AGAIN (2026-09-14).** The flat
scheme above is correct for one person and breaks on the second: `characters/michael/IMG_1.jpg`
is the same key for every account, so the second studio to upload a character called `michael`
overwrote the first one's face, and nothing in a key says who owns it, so per-account
accounting, quota and deletion are all impossible. **`src/media.py` is the one owner** of the
key scheme and of the read-time mint; `storage.py` stays the boto3 layer and
`asset_shelf.parse_ref` stays THE parser.

- **`ZEROPAGE_MEDIA` is one switch and a LADDER**, each rung a superset of the one below and
  every rung reversible by setting it back: `legacy` (default — flat keys, public URLs, today's
  behaviour byte for byte) → `tenant` (`m/<account>/<tail>`) → `signed` (the same keys,
  presigned URLs, private bucket). An unrecognised value reads as `legacy`: a typo must leave
  the system where it was, never make media private.
- **THE BIN IS SHARED, and that is a decision (2026-09-15, Mike's call).** `/refs/<sha>.jpg` is
  deliberately the same shape whether a composer uploaded it or the scout crawled it — "they
  come out the far end identical", above — and `scout_bin` has no account column at all, being a
  shared table by design. So at read time nothing can tell an owned bin image from a shared one,
  and a scheme that needed to would have to guess. `refs/` routes to `m/shared/refs/...` for
  everybody; characters, props, locations, renders and soul-training are fenced per account.
  What that costs, stated plainly: a bin image is protected by an unguessable content-hash key
  (and a signature under `signed`), not by a tenant fence. The privacy weight sits on the faces
  and the renders, and those are fenced. `media.scope_for` is the one place that decides.
- **Two top-level prefixes, `m/` for masters and `t/` for the 480px derivative, and that is not
  cosmetic.** A lifecycle rule matches on a prefix, so masters age into Infrequent Access while
  the thumbnails every card actually reads stay in Standard. Nest the thumbs under `m/` and
  that rule cannot be written without demoting them.
- **What goes ON a row is `asset_shelf.storable_ref`, not a URL.** Every reference bug this repo
  has paid for came from storing a URL — a local route true only on the machine holding the
  folder (2026-09-08), and now a signed URL true only for the next hour. From `tenant` up the
  row carries the logical name and `media.url_for` mints the fetchable string on READ. Rows
  written on either rung keep working on the other, which is what makes the ladder safe in both
  directions and why the migration does not rewrite the database at all.
- **One mirror.** `refbin.mirror_to_r2` and `api._mirror_photos_to_r2` were two implementations
  of one scheme with two key builders between them; both delegate to `media.mirror` now, which
  is also what writes the derivative. A new writer gets the tenant prefix and the thumbnail
  without having to remember either.
- **`refs` and `photo_thumbs` are deliberately NOT one list.** `refs[0]` is the single frame
  Runway anchors a clip on; a list that quietly carried 480px versions would anchor the clip on
  one. A card with no derivative falls back to `?thumb=1` — a slow tile, never a missing one.
- **The migration COPIES and never moves** (`ops/migrate_media_keys.py`, report first, `--write`
  to act, re-runnable). Old keys stay public and serving, so the flip is reversible. A flat key
  does not say who owns it, so ownership is recovered from the database; anything unattributable
  is reported and LEFT ALONE, and a slug held by two accounts is reported as ambiguous rather
  than guessed — under the flat scheme one overwrote the other and nobody can now say which
  bytes survived.
- **`signed` trades the edge cache for access control**, knowingly: a presigned URL must address
  the S3 API endpoint, because an R2 custom domain serves the public bucket path and will not
  accept a SigV4 query signature. Signatures are memoised per hour so the BROWSER cache still
  works on a card it has already drawn. The way to get both is a Worker on the custom domain
  validating a token against an R2 binding — deliberately not built until a bill says to.
- **Migrated 2026-09-15**: 303 objects copied (139 to account 1, 164 to the shared bin), 185
  derivatives built, all 364 legacy keys left in place at the time, `ZEROPAGE_MEDIA=tenant`
  locally. **The legacy keys did NOT stay:** on 2026-10-07 every flat `renders/nano/c<id>-...png`
  404'd while the same still answered under `m/1/renders/nano/`, so anything hard-coding a flat
  key (the sign-in showcase, `web/src/content/landing-media.ts`) had to move to the tenant
  prefix. Never write a new flat-key URL; ask `media.url_for`, or use the `m/<account>/` key. 61
  objects were left where they are because NOTHING in the database references them — three prop
  folders whose rows are gone, and superseded nano keyframes. Verified by fetching: a 2,258,681
  byte location photo now draws as a 33,533 byte tile.
- **`ops/media_lifecycle.py --write` needs an ADMIN token.** Lifecycle is a bucket-level
  operation and the token in `.env` is scoped to Object Read & Write (correctly, for everything
  else). It refuses with an explanation rather than a traceback and changes nothing.
- Full operational sequence, including the custom domain and the tiering pass
  (`ops/media_lifecycle.py`): **ops/r2-setup.md**.

**And the LISTING falls back to the bucket too (written 2026-09-15, reworked for the ladder
2026-09-18).** The deployed API answered `photos: []` / `poster: null` for every asset, so the
React composer and Elements page could attach none of them: `_assets_all` and
`asset_shelf.catalogue` both built the list by scanning the folder, and Fly has no folder.
`asset_shelf.r2_photo_urls(kind, slug, account_id)` lists the bucket instead, disk still first on
both listings so the Mac reads its own photos. Two rules, both learned by nearly merging the
first version after `src/media.py` landed underneath it: the prefix comes from
`media.object_key` (so on `tenant` it lists `m/<account>/characters/…`, never the flat
`characters/` every account shares -- the second studio's `michael` must not be handed the
first one's face), and what it RETURNS is `photo_url()`'s storable name, not a raw public URL,
like every other writer. `storage.keys_under(prefix)` is the cached edge behind it: ONE
`list_objects_v2` per (account, kind) prefix per process, kept for `R2_LISTING_TTL` (600s), an
upload from this process folded straight into the cache, a failed list remembered as empty for
one TTL rather than retried per asset, `[]` outright when R2 is unconfigured.
`tests/test_assets_r2_fallback.py` stands a fake listing in at `storage.list_keys`.

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

**One idea box, one board, one spend gate (2026-08-28, Mike's call.)** *(The board half is
superseded since 2026-10-07: the Pipeline and Director tabs were folded into ONE PROJECTS BOARD,
below. The Queue as the one spend gate is unchanged.)* Scenes and
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

**A hand edit of a prompt teaches — for ONE account, by a column (2026-09-18, Mike's
call: "only for my account specifically, not for other users").** Every prompt edit — the
Director prompt bar, the Pipeline card's in-place edit (both `POST /api/concepts/{id}/shots/{n}/prompt`),
a Direct note — used to write `shots_json` and nothing else, while the board's pick
snapshotted the prompt at click time: edit-then-pick filed the human's text as "worked" with
no record of the draft, pick-then-edit filed the draft and lost the edit. Now, when
`accounts.prompt_edits_teach` is TRUE for the tenant (`python -m src.accounts edits-teach
<slug> --on`; `src/edit_teach.py` is the gate, manual_lane's shape — fails closed, never
membership, FALSE for every account until turned on by hand), an edit files a PENDING pair on
the board's own `concept-{id}-shot-{n}` ref through `winners.record_pair`: the model's draft
on the avoid side, the edit on the winning side, note `edited by hand` (or `directed: <note>`
for a Direct note, where the pair is prompt-before → revision). Nothing reaches a shelf until
the Teach tab's grade-all ingests it, same as a board tap; the tab marks these `✎ EDITED`.
`shot["model_prompt"]` remembers the model's last draft across hand edits (so a re-edit still
pairs draft → latest, one pending pair per shot, latest wins; editing back to the draft
withdraws it) and every model writer drops it (`persist_prompt`, Polish, Direct). Replacement
extends `api._board_verdict`'s asymmetry: a pending board tap is replaced by the pair, a board
tap AFTER an edit leaves the pair alone, a Grade-tab verdict and anything ingested are never
touched. Accounts that are off get no new key on their rows and no winners row — byte for
byte the old behaviour. What the server cannot tell: Director's Save prompt may save the
ENHANCE node's text, which Gemini wrote; it files as the person's fix. Found on the way:
`/direct` and `/refine` never passed `account_id` into `director.*`, so on an owned row
(every live concept) the job died with "no concept N" — fixed. Deferred ingest
(`winners.ingest_pending`) now carries the tenant `project` label the immediate path always
had. Live: on for accounts 1 and 2 (both Mike's brands), column added 2026-09-18.

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

**The night does the rest (2026-08-29, Mike's call.)** *(Read as history: NOTHING IS SCHEDULED
since 2026-09-28, and the walk itself was deleted 2026-10-07 -- "the nightly graph" is now
`src.trigger` run by hand -- the
night draws no stills since 2026-09-08 and posts nothing, `autopilot.AUTO_POST_BRANDS` being
empty. The Fly image's one cron line is the Instagram token keeper; keep it that way unless Mike
asks for a walk back.)* Enhancing, keyframing and
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
worth of scenes with 0 stills and nobody the wiser. **SINCE 2026-09-29 THE PICK DRAWS NOTHING
EITHER** (Mike's call: every spend of credits sits behind a priced approve): the card carries
`keyframes` (`scene_chain.keyframe_quote` — stills missing, credits), and the Queue card's
**Draw keyframes** button posts `POST /api/concepts/{id}/keyframes`, which refuses with "top up"
(402) unless the WHOLE strip fits the balance, then runs `draw_on_pick` as a job. What follows is
the 2026-09-08 history. **The PICK draws the still instead** —
`scene_chain.draw_on_pick`, called from the board (`POST /api/concepts/{id}/pick`, as a
background job) and from the MCP `pick`, guarded by one shared `scene_chain.pick_skip_reason`
so the two doors cannot drift into billing a scene twice. It is skipped for a scene that
already has a `reference_image` (re-picking must not re-bill, and Director's own keyframe is
the one a person chose) and `ZEROPAGE_KEYFRAME_ON_PICK=0` turns it off. `NANO_DAILY_CAP` is
60: a pick draws one still per SHOT of a timed scene (one per beat of a one-window scene),
not one per scene.
**A walk was 5 sparks × 2 brands = 10 runs** (`NIGHTLY_SPARKS`, cut from every line of
sparks.txt — 20 — on the same day, "we'll increase it once I see it gets better"; the walk
was deleted 2026-10-07).
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
  Portfolio` after the folder was renamed. (`ops/install-launchagents.sh` copied and
  reloaded it in one step; it was deleted on 2026-09-28 with the last LaunchAgent.)
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
     a project's workspace (or a solo scene's canvas): Pick / Not this one (archives + reason)
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
- **`src/shootgen.py`** — the scene writer, over the active project's brief (`load_brand`;
  no brand blocks since 2026-10-04) plus whatever grounding the edge handed it. **Two live entry points:**
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
  **fal's receipt is persisted at submit (2026-09-26, `src/fal_requests.py`).** A deploy
  restarted the API while #121 and #135 were polling; `app/jobs.py`'s threads died with it,
  the holds sat `submitted` with no generations row, and fal's request_id/status_url/
  response_url had only lived in a local. Now `generate_video` writes a `fal_requests` row
  (OWNED, keyed by the hold's ref) right after the submit and before the first poll, beats
  it while polling, and the caller resolves it once its row is written. The lifespan's sweep
  claims any unresolved row whose beat is older than `FAL_RECOVER_STALE_S` (600s, longer than
  a download) and finishes it through `fal._finish_shot` -- the SAME tail the live
  `generate_for_shot` runs: COMPLETED -> download, generations row (reused if the worker got
  that far), settle, attach to the concept/part. fal's own "no" (error payload, 404/410/422,
  no output, still queued past `FAL_RECOVER_GIVE_UP_S`) -> failed row + release. No answer
  from fal (network, 5xx, 429, no key) is never a release. Nothing is written to the ledger
  after the submit except by settle/release; the new table is not the ledger.
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
  blocks; its quick-start chips were Zero Page's format skeletons and are always empty since 2026-10-04, served by
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
  `--timeout-graceful-shutdown 3` (`ops/serve.sh`, and `ops/fly/supervisord.conf` in production): without it, `--reload` waits
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
- **The vanilla Gen Space was DELETED on 2026-10-07 (Mike's call).** `genspace.js`, the
  `/ui` shell's Director view, its bar controls, its node-editor modal and their CSS are gone;
  the Director is the React studio's (`web/`, inside each project's workspace), and every "Open
  in Director" on `/ui` goes through `shared.openConceptInDirector`, which hands the scene to
  `DIRECTOR_FRONTEND_URL`. The backend it drove (`app/workflow_runner.py`, the `/api/workflows`
  routes, the LiteGraph-shaped JSON) stays: the React canvas uses it. The history follows.
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
  the same design set: the Elements page -- it exists in the React studio (`web/`), and
  the Jinja rail still shows Analytics because this shell is the reference implementation
  now, not the product. **With `STUDIO_URL` set (2026-09-14) the React studio is THE
  studio:** `/ui` (with its `?view=` translated, `auth.STUDIO_VIEWS`), the landing page's
  door, and a sign-in with no return address all hand the session to it
  (`auth.studio_handoff`, the same `/auth/handoff` the studio's own Sign in uses); a
  signed-in person with no account still sees `/ui/accounts`, the gate's page, on this
  origin. `/ui?legacy=1` keeps this shell reachable. Mike signed in on this origin's own
  page, landed here, and found the Analytics rail he had asked to retire -- that is why.
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
  (2026-09-12), so nothing in the rail opens the Jinja `/ui` any more. **It deploys on
  Vercel (2026-09-14, Mike's call):** project `zpf-web`, git-connected, root directory
  `web`, `API_UPSTREAM` + `NEXT_PUBLIC_AUTH_ORIGIN` set to the API origin and no
  `NEXT_PUBLIC_API_URL`, live at `zpf-web.vercel.app`, which the API's `STUDIO_URL`
  names; `web/README.md` has the recipe. **A push that touches nothing under `web/` no
  longer builds it** (2026-09-22, `web/vercel.json`'s `ignoreCommand`, now
  `web/scripts/vercel-ignore.sh`; the README says how it decides). Since 2026-10-08 a
  preview branch is judged against its merge base with `main`, not against `HEAD^`: the
  old rule skipped PR #182's `web/` change because its first push ended in a merge from
  `main`. Unsure means build. The studio's `/api`, `/auth` and media
  traffic still proxies through Vercel's edge ON PURPOSE -- that is what keeps the session
  cookie first-party (the 2026-09-14 note above) -- and every poll and every photo is
  therefore a Vercel edge request plus origin transfer; `docs/tasks/task-api-domain-move.md`
  is the plan to take it direct on `api.zeropage.studio`, blocked on the domain and not
  started. The Fly app `zeropage-web` is scaled to zero,
  not destroyed. The API stays on Fly. `frontend/` is
  the Vite + React composer that preceded it, kept as received; its `/api/brains`,
  `/api/scene-lengths`, `/api/render-choices`, `/api/creative-guide` and the guide mode
  exist only as uncommitted work in the main checkout's overnight branch, and the Next
  composer shows those pills only when the routes answer. The vanilla Gen Space on `/ui`
  stayed as the reference implementation the React one was ported from until it was deleted
  on 2026-10-07.
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
  `genspace.openConceptInDirector` redirected there unless `?legacy=1` asked for
  the vanilla canvas (since 2026-10-07 `shared.openConceptInDirector` always hands over; the
  vanilla canvas is deleted) -- ported from the `workflows.js` edit, since that file
  no longer exists. The Generate node's gate note reads `video.generate`
  (any keyed renderer), not Runway's key alone.
- **Assets and Elements are two things, not four chips on one wall (2026-09-18, Mike's
  call).** `_assets_all()` had always returned locations + characters + props + `generated`
  in one list, so the React Assets wall showed element photos beside renders, the Elements
  page listed a render as an element (`@runway-image`), and the `@`-mention search offered
  it. Now: **Assets** (`/studio/assets`) is GENERATED content only — `/api/media?scope=generated`,
  one row per render carrying `provider`, `model`, `concept_id`, `prompt`, `folder`, `starred` —
  and you can view, organize and delete it. **Elements** (`/studio/elements`) is the
  characters / props / places a scene is held to — `/api/assets?scope=elements` — and a card
  can be deleted (locations gained `DELETE /api/assets/locations/{id}` to match). `scope`
  defaults to `all` so every existing caller reads as before; `/assets/search` is pinned to
  `elements` because a mention is an element by definition. Organize = `folder` + `starred_at`
  on `generated_assets` (additive ALTERs in `render_assets.init`, `PATCH
  /api/assets/generated/{id}`); the wall's chips are Images / Clips / Starred / one per folder,
  plus a provider select, all derived from the response's set totals (`wall`, `folders`,
  `providers`). **A clip's tile is its poster (2026-09-28):** `fal._publish` and the manual
  import draw one frame (`media.mirror_poster`, ffmpeg, 480px) under the clip's own tail in
  `t/`, so `media.thumb_url_for(media_url)` finds it with no new column; clips from before
  that got theirs from `ops/backfill_video_posters.py` (report first, `--write`). The
  provider label is the model's catalog name (`pricing.CATALOG_MODELS`: "LTX 2.3", not
  "Ltx"). **Delete is SOFT** (`deleted_at`, `DELETE /api/assets/generated/{id}`): the
  render leaves the wall and its RAG chunk is dropped, but the row and the file stay, so a
  concept whose shot carries that clip keeps rendering it — a paid output is never thrown
  away. **"Make element"** on a still opens the add-element modal with the render attached
  by URL (`photo_urls` on the create routes, fetched through `_photo_bytes`), the Higgsfield
  "Create Element" move and the only honest way a render becomes a reference here. And the
  manual lane's `import_clip` now records a `generated_assets` row (lazily imported,
  best-effort) — until today a hand-rendered Runway/Higgsfield clip lived on the concept and
  nowhere else, so it never reached the wall. `web/` gained the `motion` package for the
  rail slide and tile enter/exit.
  **An element gets a REFERENCE SHEET, as part of adding one (same day, Mike's call).**
  Creating an element used to save the photos, describe them (vision, text) and stop; the
  frames a shot was held to were exactly the uploads. Now the create routes take `sheet`
  (on unless the modal says off) and, once the row is saved, start a job that draws ONE
  sheet from the real photos on Nano Banana Pro — `src/element_sheet.py`, prompts in
  `prompts/element_sheet_{character,prop,location}.txt` (five panels + info block for a
  person, a turnaround for a prop, plates for a place), through `nano_banana.generate_from_prompt`
  with two new flags: `literal=True` (a sheet is not a video prompt, so no `as_still_frame`)
  and `bank=False` (it lives with its element, not on the Assets wall; caps, the
  generations row, the meter and R2 still apply). It lands as `<slug>/sheet.jpg` and
  `_photo_names` sorts it LAST — a sheet is a derivative of the face, never evidence of it,
  and `refs[0]` stays a real photo. `POST /api/assets/{kind}/{id}/sheet` redraws, and is how
  elements saved before today get one (the card's button). Never a gate: no key, no photos
  or a failed draw leaves the element exactly as saved, with the reason on the job.
  **The character sheet IS the landing page's (2026-10-09, Mike: "exactly as is").**
  `prompts/element_sheet_character.txt` is now the prompt that drew
  `web/public/models/nano-banana-image-generator/sheet.jpg` on Higgsfield, word for word:
  five panels -- full-body front, three-quarter, side profile, back, head-and-shoulders
  close-up -- no labels, no text -- except the background, which is pure WHITE (2026-10-10, Mike's call; the landing image is light grey); its one slot is `{outfit}` ("wearing <notes>",
  else the photo's own clothes). **And the composer's brain draws it** (`make_element_sheet`,
  `guide_tools.SHEET_TOOL`, a third make tool, composer only -- the pill's `makes` leaves it
  out): "make an element sheet of me" with photos attached ends the turn on a step card
  (`still-step.tsx SheetStep`, Ask first / Auto like a still), and Approve posts the
  composer's references as `photo_urls` to `POST /api/assets/characters` with `sheet=1`,
  follows the sheet job and lands the sheet as the turn's tile. The create route now draws
  the sheet from the photos THAT request wrote (`_save_uploaded_photos(into=)` ->
  `_start_sheet_job(photos=)`), because a name with an older folder (`characters/michael`)
  grounded on the first six files there; and it answers `sheet_note` when a sheet was asked
  for and could not start.
- **`src/mcp_server.py`** + **`app/mcp_mount.py`** — the MCP surface (2026-08-31), so the
  board can be read and decided on from a phone or an agent instead of only from this
  machine. **An adapter, never a store:** every tool is a thin call into `preprod` or
  `scout`, and `data/pipeline.db` stays the one source of truth — a synced second store is
  the mistake `asset_shelf` exists to fix. The read/decide tools (`board`, `idea`,
  `search`, `capture`, `pick`, `shoot`, `archive`, `add_spark`, `tonight`, `sparks`,
  `images`, `stats`, `job`) are always on. **`pick` spends nothing again since
  2026-09-29** -- it returns the `keyframes` quote and a note to approve the draw in the
  studio; the history: **`pick` was the ONE that spent, and only
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
  **The board's cards carry the same verdict (2026-09-17).** `_concept_card` gained `gate`
  (`autonomy.gates_for_concepts`: `{score, passed, reason, reworks, status, outcome}`, the
  `_gate` reading batched into two queries for the whole board), on `/api/pipeline/concepts`
  and `/api/queue/pending`. `None` means no graph run ever ended on the concept — never
  scored, which the cards say as such and must never draw as a pass. `passed` is what the
  gate SAID (the `log_prompt_scores` rule), so an advisory run that parked still reads
  False; the cards show a failed gate as CHECK, never BLOCKED — BLOCKED is the reference
  gate's alone. `gateOf` in `app/static/zpf/cards.js` and
  `web/src/components/studio/concept-card.tsx` are twins.
  **And where each reference came from (same day).** `ref_sources` is parallel to `refs`
  (`refs` itself is untouched — its order anchors the render): `{url, kind, slug, filename,
  source_url, title, lane}`, `kind` from `asset_shelf.parse_ref`, the rest from
  `scout.sources_for_refs` — one query per board, joined on the bin's content-hash basename
  (the same in `/refs/<sha>.jpg` and the R2 URL), the row WITH a `source_url` winning when
  the same bytes were banked twice. "A reference must be traceable to where it came from"
  was kept at banking time and lost on the shot; the preview overlay now links the page.
  Only http(s) is ever linked, and an upload says it has no page rather than implying one.
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
  **Two starts at once used to kill one (found and fixed 2026-10-10).** Claude Desktop launches
  every local server TWICE within seconds (it drops the first, which keeps running its init),
  and `main()` runs nine module inits against the live database in each. An init holds a
  ShareLock on its table (`CREATE INDEX IF NOT EXISTS` takes one even when the index exists,
  and two ShareLocks do not conflict) and then wants `own_table`'s UPDATE or an ALTER on it, so
  two inits wait on each other and Postgres refuses the second: `DeadlockDetected`, "Server
  disconnected". The desktop log held eleven since 2026-09-05, about half of all double
  launches, on `videos`, `shoot_concepts`, then `creative_projects` -- the statement moves with
  the init order, and 16 of the 24 inits the app runs deadlock against a copy of themselves. So
  the fix is around the init, not in one: `db.run_init(steps, dsn)` holds a TRANSACTION-level
  advisory lock (`pg_try_advisory_xact_lock`, per schema, on its own connection; a session lock
  is not safe behind Supabase's transaction pooler) while `steps` runs, starts without it after
  `INIT_LOCK_WAIT_S` (20s: a line on stderr, never a dead start), and runs `steps` again (three
  attempts) on a deadlock. `mcp_server.main` and the web lifespan (`app.main.init_tables`) both
  use it; a new process entry point wraps its inits the same way, and no init() changed. Not
  covered: a CLI's own `init_db()` and a web request in flight can still be one side of a
  deadlock -- the start under `run_init` is the side that runs again. `tests/test_init_race.py`
  is the race, through the real entry point.
  **TWO DOORS SINCE 2026-09-24, and which one you came through decides whose
  board you read** (`app/mcp_auth.py`, `app/mcp_mount.guarded`). The static
  `ZEROPAGE_MCP_TOKEN` is the OPERATOR's key: compared with
  `hmac.compare_digest` before the MCP app is entered, acting as the bootstrap
  account exactly as it always did -- Claude Code, the research node and `ops/`
  are untouched. Anything else is verified as a **Supabase access token**:
  Supabase's own OAuth 2.1 server is the authorization server (it does PKCE,
  consent and the dynamic client registration the claude.ai connector requires),
  and this app is only the RESOURCE server. So what was built here is small and
  all of it is refusal: `/.well-known/oauth-protected-resource` (+ the
  `/mcp`-suffixed path RFC 9728 actually specifies), a `WWW-Authenticate` on the
  401 naming that document (a 401 without it is a dead end for a connector), and
  `account_for_token`, which resolves the caller to ONE account by the SAME rule
  `auth.current_account_id` uses -- the tenant is the user's OLDEST membership,
  `min(id)`, not the brand cookie. Two doors onto one board must not disagree
  about whose board it is. A verified token with NO membership is 403, never a
  fall-through: falling through is Mike's board.
  **The caller reaches the tool through `mcp_server.CALLER_ACCOUNT`**, a
  ContextVar set by the ASGI guard and reset in a `finally`. It lives in `src/`
  because `src/` never imports `app/` and `_account` is the one place that
  decides whose rows a tool reads. That the value survives the transport was
  measured, not assumed: in STATELESS mode the tool body runs in a task that
  inherits the request's context (a stateful session would not promise that --
  one more reason the mount is stateless). `_account`'s order is explicit
  `account_id` (the Guide) -> `CALLER_ACCOUNT` (a signed-in caller) -> bootstrap
  (the operator's key), and the end-to-end test drives the REAL streamable-HTTP
  app with two callers and asserts each resolved its own id. Deleting the
  ContextVar branch makes exactly that test fail, which is the point of it.
  **THE LISTED SERVER (2026-10-07, Mike's calls; docs/directory/).** For the
  Claude directory listing the mount builds TWO servers and `guarded` routes
  by door: the operator's static key reaches the full server exactly as
  before, a signed-in person reaches `build_server(listed=True)`, which
  registers `mcp_server.LISTED_TOOLS` only -- `board`, `idea`, `search`,
  `capture`, `pick`, `shoot`, `archive`, `stats`, `projects`, `project`,
  `project_chat`, `create_project`, `save_chat` (the project tools joined it
  2026-10-08, Mike's call: a person's own rows, nothing spent), `elements`,
  `write_scene`, `quote`, `approve`, `job` -- in `build_server`'s registration
  order, which the mount's test compares. Never the engine tools (whatever the flag says),
  never the spark bank (`scout_findings` / `scout_bin` are SHARED tables and
  one person's directions must not be listed to another -- nor their COUNT:
  `stats` drops `sparks_unused` there, found on the 2026-10-08 live walk), never
  `images_for` / `reference` / `imagine_reference`. **Claude does the ideation
  in the chat and the MCP renders**: `elements` lists the account's
  characters/props/places with photo refs; `write_scene` saves a chat-written
  prompt onto an idea as the one AI shot every reader already understands,
  accepts only refs `elements` issued (a URL, a guess, another account's photo
  are all refused), asks `preprod.reference_gate` BEFORE writing, and turns
  timed windows into the timeline through `timeline.fallback` -- the split
  with no model call, stamped `source` so `ensure` never re-plans it; `quote`
  is `pricing.display` for the clip plus `scene_chain.keyframe_quote` for the
  stills beside the balance; `approve` (`what` = keyframes | clip, the quote's
  tokens, the renderer choice; `destructiveHint: true`) runs the Queue's OWN
  approve bodies, lifted into `app.api.approve_keyframes` / `approve_render`
  (the routes wrap them; `src/approvals.ApproveRefused` is what both doors
  raise) and injected into the mount like `start_job` -- so the chat and the
  Queue card are one body and cannot drift. Every tool is published from
  constants (`TITLES` / `DESCRIPTIONS` / `HINTS`, screened for operator
  vocabulary by a test), the mount carries a per-account fixed-window rate
  limit (`ZEROPAGE_MCP_RATE` 120/min, `ZEROPAGE_MCP_RATE_OPERATOR` 1200/min,
  in-process: one Fly machine), `mcp_auth.verify` checks `iss`, and a sign-in
  with no workspace is told to sign in once at `ZEROPAGE_SIGNUP_URL` (the
  connector never creates one). **The consent page is ours** (same day,
  `app/oauth_consent.py`): Supabase's OAuth server redirects the person to
  `<Site URL>/oauth/consent?authorization_id=` (the dashboard's
  Authorization Path) and waits for the app to answer AS THE PERSON; this
  app keeps no Supabase token, so the page sends them through `/signin`
  and `auth._finish` hands back to it holding that sign-in's token for the
  one decision (`oauth_consent.resume`, a CSRF value beside it, a pending
  consent forgotten after 15 minutes). The page names the client and the
  redirect HOST, warns on a loopback one, and 303s only to an http(s)
  `redirect_url`. Signing in there creates the workspace, which is how
  "sign in once on the web" is met on the way. **The one thing the listing
  still risks:** the directory's checklist refuses connectors that
  "generate images, video, or audio through AI models", which `approve`
  does on purpose (Mike's call; `docs/directory/RENDER_DESIGN.md`). The public plugin bundle lives in its own repo beside
  the main checkout (`../zeropage-studio-plugin`, five skills, MIT).
  **The audience is checked, twice over**: a token minted for another resource
  server must not work here, so `verify` accepts only `aud` = this server's
  canonical URI (`ZEROPAGE_MCP_RESOURCE`, set in fly.toml because `SITE_URL` is
  deliberately unset there) or the ordinary session audience. The metadata
  document is built off that same resource URI rather than `SITE_URL`, or the
  deployed document would publish a localhost resource and discovery would fail
  with nothing to read.
  **THE STUDIO SURFACE (2026-10-07, Mike's calls).** What `python -m src.mcp_server`
  serves by default -- what Claude Desktop launches -- is `build_server(surface="studio")`:
  `mcp_server.STUDIO_TOOLS` only, for making things WITH Claude and never for the board
  (nothing is captured, picked, archived, banked or written to a concept). Three spending
  doors -- `generate_image` (fal.IMAGE_MODELS through `fal.generate_image_from_prompt`, the
  composer's own door), `generate_video` (`fal.generate_from_prompt`, which gained the
  caller's `duration` / `resolution` / `aspect_ratio`, a `source` label and `bank` for the
  Assets wall) and `apply_effect` (`src/effects.py`) -- each go through
  `mcp_server.approval_gate`: a call with no `quote_token` returns the quote and spends
  nothing, and only the quote's own token runs it, as a job with the usual hold / cap /
  generations row / settle / Assets wall. **Since 2026-10-08 the approval is in CREDITS and
  the token is signed and single-use** (docs/tasks/task-mcp-studio-v2.md step 1; it was
  `approve_usd`, dollars Claude repeated back, which any high enough number satisfied and the
  same yes could spend twice). The quote shows `credits` (`ledger.charge_credits`, the one
  conversion every hold uses), `charged` (false on an exempt account), `balance` and
  `balance_after`, the provider `usd` as detail, and a `quote_token` from
  `pricing.sign_studio`: the shot token's sibling, same secret / TTL / refusal codes, its body
  binding the TOOL and a hash of the normalized arguments (model, aspect / seconds / frame,
  prompt, reference ids, effect + options, the element and whether it replaces a sheet, the
  project), so any change after the yes is `stale_content`, and marked `"k": "studio"` so
  neither verify() accepts the other kind. The verified `pricing.StudioQuote` is handed down
  to the adapter (`quote=` on `fal.generate_image_from_prompt`, `fal.generate_from_prompt`,
  `effects.run`, `element_sheet.draw` -> `nano_banana.generate_from_prompt`) so the hold IS
  the signed credits. **Single use:** `start_approved` dry-runs every check, then CLAIMS the
  token in `quote_redemptions` (OWNED, src/quote_redemptions.py, an `INSERT ... ON CONFLICT DO
  NOTHING` on the token id) before the job starts; a repeat is handed the first job and
  starts and charges nothing. A short balance is a STRUCTURED refusal (`refused:
  insufficient_credits`, `needs`, `available`), never a tool error, and leaves the token
  unspent. No `QUOTE_SIGNING_SECRET` = quotes still answer, with no token and a note, and
  nothing can be approved (the Mac's `.env` had none on 2026-10-08). **`cancel_job`
  (2026-10-08, step 6)** stops one of those jobs (`_run(..., _cancellable=True)` makes them
  cancellable; `app/jobs.cancel` only FLAGS a running job). The flag reaches the adapters
  through `src/cancellation.py`, a contextvar the job runner binds in its worker thread (the
  `charge.metering` shape). Two places act on it: `Charge.submitted()` -- the last line before
  every provider call -- releases the hold and raises `Cancelled` (nothing sent, no failed row
  owed); and `fal._submit_and_wait`'s poll loop PUTs fal's `cancel_url` (the `fal.CANCEL`
  sentinel through the same `http` seam) and lets FAL'S ANSWER decide: an error payload
  (`client_cancelled`), a 404/410/499 or no output after a `CANCELLATION_REQUESTED` ->
  `Cancelled`, released; an output anyway, or `ALREADY_COMPLETED` -> kept, settled, filed, the
  job's result marked `cancel_too_late`; `NOT_FOUND` -> released; no answer (network) ->
  nothing assumed, asked again next poll. fal bills only successful outputs (its pricing page,
  2026-10-08), which is why "no output" is the release. An element sheet is one Gemini call
  and cannot be stopped once drawing. The job ends `cancelled` with the adapter's own words
  (`detail`), or `done`. Also fixed on the way: a job cancelled while still `queued` used to
  run anyway (the worker overwrote the status); it now never starts. **Every studio tool
  answers TYPED (2026-10-09, step 7):** `src/mcp_shapes.py` is the one set of pydantic models
  (`SHAPES[tool]`, open -- `extra="allow"`), and `build_server(surface="studio")` registers each
  tool through `mcp_server._structured`, a wrapper whose `__signature__` keeps the tool's own
  arguments and declares `Annotated[CallToolResult, SHAPES[tool]]` -- so the SDK publishes an
  `outputSchema` and validates every answer (a drifted payload is a crash, never a quiet wrong
  answer). The answer is `structuredContent` (the payload, enriched additively: a spend's
  `state` = quote / refused / started / already_used / done / failed, a job's `media_url`,
  `asset_id`, `ref` = `gen:<id>` and `media_kind` lifted off its result) plus text: a short
  human line FIRST and, while `mcp_shapes.MIRROR_JSON`, the same payload as JSON -- because what
  a client shows its model is the client's choice and nothing first-party says what Claude
  Desktop does (Claude Code reportedly reads structuredContent only, claude.ai forwards both);
  a client that read only the line would lose the `quote_token`. Turn the mirror off after a
  live check. The board and listed servers are NOT wrapped and return plain dicts as before.
  **`assemble_clips` (2026-10-09, step 2a)** joins 2-20 `gen:<id>` videos into ONE MP4:
  `src/cut/join.py` plans (every refusal first: not a video of this account's, soft-deleted,
  unreadable, two shapes unless `letterbox`, a crossfade over half the shortest clip, music
  that is not an `asset:<id>` audio upload), builds the cut with `assemble.build_doc` (which
  gained `transition_frames`: a crossfade INTO each later clip, added as it lands so markers
  and the music bed see the shortened cut; Assemble itself still passes 0), saves it as v1 of
  a SCRATCH cut project (`cut:<uuid>`, openable in the editor), renders it with
  `render.render` and files it on the Assets wall under the new free log tool `cut`
  (`generative.CUT_TOOLS`, `cost_usd` NULL, wall label "Joined clips"). No quote: nothing is
  spent, and the result says so (`credits: 0`). `renders(kind="audio")` lists the editor's
  audio uploads as the `asset:<id>` music takes. **`import_file(path)` (2026-10-09, step
  3+4's fallback)** reads a file on the computer running the stdio server -- only under
  `mcp_server.import_roots()` (`ZEROPAGE_IMPORT_DIRS`, else ~/Downloads, ~/Desktop and the
  checkout's data/), with every symlink resolved, images (jpg/png/webp) and mp4/mov only, under
  the editor's caps -- and files it through `src/cut/uploads.save`, the editor's upload body
  lifted out of `app/cut_routes.py` (the route now calls it too), so it lands as an
  `asset:<id>` in `cut_media`, mirrored and probed. `asset:<id>` is accepted wherever a
  reference (an image), a clip effect's source or a clip to join (a clip) is; `renders(kind=
  "upload")` lists them. STUDIO surface only -- never the board (HTTP) or the listed server --
  and refused for a signed-in caller. Also fixed on the way: the shared upload body now refuses
  a "still" or "clip" with no width/height (ffprobe calls a text file named .jpg a 0x0 mjpeg
  still, and the editor used to file it), and the stdio entry point now creates the editor's
  and the generations tables, without which import_file and assemble_clips crashed on a fresh
  database. **MCP Apps (the inline viewer + drop zone) are NOT built**: the SDK supports them
  (`mcp.server.apps`), Claude lists Desktop as a host, but open reports (anthropics/claude-ai-
  mcp#165, modelcontextprotocol/ext-apps#671) show UIs silently not rendering, a local stdio
  one in Desktop among them, and a check from inside the Desktop app cannot restart it -- the
  task's gate says stop and report. On the studio surface they
  are always on (the approval is the gate); on the board surface they sit behind the engine
  flag; the listed server never has them. References are ids, never URLs, in ONE grammar
  shared with `write_scene`: `gen:<id>` (a render; `renders` lists them), a photo `ref`
  exactly as `elements` lists it (checked by `_allowed_refs`), or `candidate:<id>` from
  `images_for`; a model's reference limit (`fal.image_max_refs`) is refused past, never
  trimmed. **`src/effects.py`** is a dated table (checked 2026-10-07 against each fal
  OpenAPI schema and model page): four image edits (Nano Banana edit, FLUX Kontext Pro,
  Seedream 4 edit, Bria background removal), Kling (98 templates) and PixVerse v5 (154)
  template effects, PixVerse 4.5 camera moves (20), Topaz upscale / frame rate and MMAudio
  sound -- each row's input field, legal options (anything off-table is REFUSED, never
  clamped) and price rule; a clip source is a `gen:` video measured by ffprobe before it is
  priced, and one that cannot be measured is refused. Effects log under the image tool name
  (`fal`), so they share the stills' cap. Left out because a price or input could not be
  verified: lip sync, relight, RIFE/FILM, PixVerse 8s. **Four clip-finishing rows were added
  2026-10-10 (task-mcp-studio-v2 step 2b), each with its OWN `checked` date** and read off its
  OpenAPI schema plus the `endpointBilling` record its fal page embeds (unit + price,
  structured): `reframe` / `reframe-hq` (Luma Ray 2 Flash / Ray 2 Reframe, $0.06 / $0.20 per
  second; a clip to a new shape by generation, `aspect_ratio` required, prompt optional; held
  to 10.5s because Luma's own guide caps a reframe at 10s and fal's page states no limit),
  `remove-video-background` (VEED, per started 30 frames: $0.0225 with edge refinement, $0.015
  without; a transparent .webm) and `remove-video-background-pro` (Bria, $0.14 per second,
  under 30s; Transparent or a flat colour; webm_vp9 / mp4_h264 / mov_proresks, with
  Transparent + H.264 refused by the row's `check`). An effect's output is published under its
  own container's mime now (`effects.VIDEO_MIMES`), not always video/mp4. Left out that day:
  BiRefNet video (billed per compute second), BEN v2 video (a per-megapixel price with no
  rule for counting a video's megapixels) and Wan VACE outpainting (priced per output second
  at a forced resolution; re-generates at 16fps, capped ~15s). **`edit_clip` (2026-10-10, step
  2c) changes something IN a clip by instruction, in TWO spends**, each a signed quote:
  `stage="frame"` pulls one frame with ffmpeg here (free) and edits it as a still
  (`clip_edit.FRAME_EFFECT` = `nano-banana-edit`, 10 credits), and its quote lists what the
  whole clip would cost on every model, or why a model cannot take this clip;
  `stage="video"` runs the whole clip and takes ONLY the `gen:<id>` of a frame stage 1 made
  from this clip with this instruction (`mcp_server._approved_frame` reads the wall row's
  `metadata.edit_clip`) -- the dear half cannot be bought without the cheap half having been
  made to look at. `src/clip_edit.py` is the dated model table: `kling-o1` (default, $0.126/s;
  3-10.05s, each side 720-2160px, 24-60fps, mp4/mov; the approved frame goes in as `@Image1`),
  `kling-o1-pro` ($0.168/s) and `flux-3` ($0.03/s; mp4 under 15s and 50MB; instruction only,
  so `frame_steers` is false and the quote says so). They are deliberately NOT `EFFECTS` rows
  (that would make them one `apply_effect` call away, no frame); `effects.run` gained `row` /
  `endpoint_body` / `extra` so they still take its hold, cap, generations row and wall record.
  The survey of all sixteen fal instruction editors, and why Kling O3, Wan 2.7, HappyHorse,
  Luma Ray 3.2, id-v2v, Gemini Omni, Grok, Bernini-R and the VACE apps are not wired, is in
  the task doc. **Projects reach it too (2026-10-08,
  Mike's ask: make projects, revisit the ones made in the studio, pull their reference images
  and chats).** `projects` lists the account's projects (`projects.list_projects`), `project`
  reopens one -- brief, look, `learned` (its memory), its scenes, every reference photo those
  scenes used (`projects.scene_refs`, each with the `ref` stored on the shot, its kind, label and
  source page), its renders and the latest chat turns -- `project_chat` pages the history
  (`projects.messages`, `before` = the oldest id held) and `create_project` makes one on the same
  projects board the studio draws. **`save_chat` writes the conversation back** (same day, Mike's
  ask): Claude passes the turns, `projects.append_turns` files them into `project_messages`
  marked `via: mcp` (shown as `via` when read back; the studio's thread ignores the key and draws
  them as ordinary turns, so the project's assistant picks the conversation up), at most 100 per
  call, refusing a role other than user/assistant. It de-duplicates by the TAIL: the longest run
  of the batch the history already ends with is skipped, so re-sending a conversation from its
  start saves only what is new -- but a studio turn written in between breaks the run and a
  re-send then repeats, a rule kept simple enough to predict. A project's scene refs join the reference grammar (`_project_refs`, read lazily, fails
  CLOSED), and `project_id` on `generate_image` / `generate_video` / `apply_effect` files the
  render under the project -- in the generations row's params and the Assets row's metadata,
  NOT as a scene (that would be adding to the board) -- so `project` lists it on the next visit
  and the Assets wall names the project (`api._project_of`, after the scene link). A project that
  is not the caller's reads as "no project N" everywhere. All five project tools are on the
  studio, board AND listed servers (the listed one since the same day, Mike's call; isolation is
  tested through the real transport in `tests/test_mcp_mount.py`), and because the listed one is a
  public door the writes and reads are bounded: `save_chat` takes at most 100 turns and 200,000
  characters a call (`projects.SAVE_CHARS_MAX`), a `project_chat` page stops at 200,000
  characters (`CHAT_PAGE_CHARS`, the rest left for the next page) and `project` shows the newest
  50 scenes and 60 references. **The cost of the choice:** the
  idea-agent skill drives BOARD tools, which Claude Desktop no longer has unless a second
  server entry runs `--surface board`. The studio surface was ported onto main from the
  stale `claude/remove-brands` branch on 2026-10-08; that branch's own `STILL_MODELS` image
  table was not carried (main's `IMAGE_MODELS` is the one table).
  **"Connect to Claude" in the account menus (2026-10-08, Mike: "access the MCP
  from the studio page at the bottom near profile").** Both menus (the rail's
  profile row and the header avatar) share one `MenuTail` in `shell.tsx`, so
  they cannot drift; the item opens `components/studio/connect-claude.tsx`.
  NOTHING ON OUR SIDE CONNECTS ANYBODY: a connector is added from claude.ai,
  which starts the OAuth flow, and the consent page is where the person says
  yes. The panel is the address to paste (`/api/me`'s `mcp_url` =
  `mcp_auth.connector_url()`, i.e. `resource_url()` when the mount is on AND
  Supabase is configured, else null and the panel says the connector is off),
  three steps, and a button to `claude.ai/customize/connectors`. claude.ai has
  no documented deep link that pre-fills a custom connector (checked
  2026-10-08), so it is copy and paste; once listed, set
  `ZEROPAGE_CLAUDE_DIRECTORY_URL` (only `https://claude.ai/...` is published)
  and the steps collapse to one button at the listing. **Connected** comes
  from `src/mcp_connections.py` (OWNED `mcp_connections`, one row per account
  × person × client, Mike's call over two columns on `accounts`): the consent
  page records `client_name` + redirect host on Allow (the GET parks them in
  the grant; a failed write never blocks the redirect), and `mcp_mount.guarded`
  stamps `last_used_at` on the LISTED door only -- at most once per account ×
  person per 10 minutes (`UseStamps`, in-process; a failed write is logged,
  never the call's error), and never for the operator's static key. A use with no
  approval on file writes a client-less row (a working token proves a
  connection). `GET /api/mcp/connection` answers for the caller's tenant and
  person only. Disconnect is claude.ai's -- Supabase's grant list needs the
  person's own token, which this app never keeps -- so the panel says where to
  remove it and nothing here deletes a row.
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
- **A faceless brand is handed no cast** (2026-09-01; REVERSED 2026-10-04 -- `CAST_BRANDS` is
  gone and every brand gets the cast, see "NO LIKENESS AND NO BRAND IDEAS"). `ground_entities` passed every asset on
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
  expire ~60 days) is built (2026-09-21, BACKLOG #4). `instagram.token_health` checks BOTH
  tokens read-only (IG_ACCESS_TOKEN by `/me`, IG_GRAPH_TOKEN by `debug_token`); its caller is
  `ops.ig_tokens check` (the nightly preflight that also logged it went with the walk,
  2026-10-07). `src.refresh_metrics`'s Instagram pass calls `refresh_token_step` first and
  prints the days left, loudly on stderr when it needs a person.
  `.env` is never written -- a NEW token Meta issues is kept in `data/ig_token.json`
  (`IG_TOKEN_STORE` overrides) beside a fingerprint of the `.env` token it replaced, and
  `access_token()`, the one reader, serves it from there exactly while `.env` still holds that
  token. The value is never printed; the message names the file and the update to make.
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
  **The hashtag half is its own opt-in (2026-09-26): `SCOUT_IG_HASHTAGS=1`**, read per call,
  off by default. Hashtag search needs Meta's *Instagram Public Content Access* feature (App
  Review, not decided) and a new tag spends budget even when Meta refuses it, so switching the
  LANE on must not switch this on. Off, `gather_instagram` runs `business_discovery` only and
  says so once per pass. A permission/feature refusal (`scout._PERMISSION_ERROR`: codes
  #10/#200/#3 or the words) is remembered in the shared `settings` table
  (`scout_ig_hashtags_paused`, `{until, reason}`) and hashtags are skipped for
  `HASHTAG_PAUSE_DAYS` (7) -- a lane that fails the same way every night is noise in `errors`.
  The budget refusal is deliberately not a pause; it has its own window.
  **The lane joins ONE account's default pass, by a column (2026-09-28, Mike's call).**
  `scout.DEFAULT_LANES` stays web/shorts/pinterest/creators; `scout.default_lanes(account_id)`
  adds `instagram` only when `accounts.scout_instagram` is TRUE for that account
  (`python -m src.accounts scout-instagram <slug> --on`; FALSE for everyone until turned on,
  fails closed, edit_teach's shape). The Studio `/api/scout/run`, the MCP `research` tool and
  a bare `scout run` (as the bootstrap account) all ask it; an explicit lane list is honoured
  either way. The MCP tool used to default to its own `LANES`, which ran Instagram for every
  caller and had drifted (named `feeds`, missed `pinterest`); it is `scout.KNOWN_LANES` now.
- **ONE PROJECTS BOARD (2026-10-07, Mike's calls; `docs/tasks/task-projects-board.md`).** A
  concept is one scene and a project holds scenes, so the board of PROJECTS replaced both the
  Pipeline tab and the standalone Director tab. `/studio/projects` is the home (first in the
  rail, the brand mark and the header's first tab): one card per project -- cover (the newest
  scene's still, else its first reference, minted through `media.url_for` in `GET /api/projects`),
  title, one line of brief, scenes / picked / rendered, last touched -- with Archive (hide, keep
  everything) and **Delete**. **There is no "New project" form**: a project is made only through
  the Guide -- `guide_tools.PROJECT_TOOLS` (`create_project`, `save_as_project`), write tools in
  the proposal sense, offered on every local turn, confirmed on a card in the pill or the
  composer and run by `/creative-guide/act` (`guide_tools.run_project_tool`), which for
  `save_as_project` takes the client's thread and the concept ids its sends made
  (`lib/assistant.asProjectConversation`) and files both under the new project. A turn inside a
  project is told so (`creative_guide.project_note`) and not to propose either.
  **The workspace** (`/studio/projects/<id>?scene=&shot=`, `components/studio/project-workspace`):
  the project's scenes on the left (the board's cards narrowed to it: Pick, Not this one, the
  drawer -- `components/studio/scene-drawer`, moved out of the old Pipeline page), the Director
  canvas for the selected scene in the centre (the SAME `FlowWorkspace`, told it is embedded
  through `CanvasNav`: its links stay in the workspace and a scene change goes through its own
  save first, `registerLeave`), and the brief / look / memory on the right. No second chat: the
  floating pill IS the Guide, and on a workspace it is scoped to the project
  (`assistant-thread.tsx`: `turns` are the project's history, each turn posts `project_id` +
  `remember=1`). **Chat history** is the OWNED `project_messages` table (`src/projects.py`:
  `append_message`, `messages` paged by id, `copy_messages`), written by the `/creative-guide`
  route as each turn happens, read by `GET /api/projects/{id}/messages`, never fed to a RAG shelf,
  kept until the project is deleted. **Delete** (`DELETE /api/projects/{id}`, guarded,
  `projects.delete`) removes the project, brief, look, memory and history in one transaction and
  DETACHES its scenes (`project_id` NULL) -- never deletes them, so a rendered clip stays on the
  Assets wall; the confirm (`components/studio/project-delete`) lists the unrendered scenes
  that will be left on no board (`GET /api/projects/{id}/scenes`). **A project is not
  required**: a video made outside one is written with `project_id NULL`, opens on its own canvas
  at `/studio/scene/<id>` (which redirects into the workspace when the scene IS filed), is picked
  with the composer's Send to Queue, and once rendered lands on the Assets wall, whose rows now
  carry `project_id` / `project_title` ("no project" on the detail rail). It never gets a board
  card. **The old doors redirect** (`web/src/lib/legacy-routes.ts`, tested): `/studio/pipeline`
  and `/studio/flows` go to the board, `?concept=` to that scene, `?draft` to
  `/studio/scene/draft`; `auth.STUDIO_VIEWS["pipeline"]` is the board. `sceneHref` /
  `workspaceHref` in `studio-api.ts` are the only scene links a page builds. The vanilla `/ui`
  still hands scenes to `/studio/flows` (`DIRECTOR_FRONTEND_URL`), i.e. through the redirect.
  **Keyboard verdicts (2026-10-08, BACKLOG #15's keys):** on the Queue and on a workspace's scene
  list, `A` approves, `X` rejects / passes, `←`/`→` move (`↑`/`↓` on the list too). The pure half
  (`lib/verdict-keys.ts`) plus ONE listener (`lib/use-verdict-keys.ts`) that answers only when
  focus is on the page itself or inside the list. It never fires while typing, inside a
  dialog/popover/menu, with a modifier key, or from the canvas, the pill or the header. On the
  Queue a keystroke NEVER spends on its own: the first `A` focuses the card's priced Approve and
  says the price, and a second `A` or Enter renders. The button and the key read one `approveOf(c)`,
  so the key cannot approve what the button would refuse. On a workspace `A` is a pick (free) and
  acts on the scene the canvas has OPEN, never one it is still saving its way to.
  `CanvasNav.registerLeave` now resolves `false` when the canvas's save failed and it stayed put.
- **The job feed and the activity tray (2026-10-08, gap list items 4, 5 and 7).** The React studio
  opens ONE `EventSource` per tab on `/api/jobs/stream` (`web/src/lib/jobs.ts`, started by the shell
  once an account is known) and nothing polls jobs any more: the Queue's list, the Elements sheet,
  the Director's node and Run all loops, the cut export and agent waits, the composer and the Guide
  all go through `studio-api.followJob` / `waitForJob` / `composer.pollJob`, which ride the stream
  through `setJobFeed` while it is live and poll exactly as before when it is not. The stream opens
  with `retry: 3000` and `event: hello {boot}` -- job ids restart at 1 with the in-memory registry,
  and a tab that sees another boot drops what it held -- then replays the live jobs and the newest
  `jobs.REPLAY_FINISHED` (50) finished ones, then `event: job` per change and `event: gone` when a job
  is cleared (`jobs.remove` / the new `DELETE /api/jobs` bulk clear never used to say so). Its
  `Cache-Control` carries `no-transform`: **Next's proxy gzips any `text/*` response that does not,
  and a gzipped stream sits in the compressor**. The store trusts the stream only after the hello; no
  hello in 6s or three errors in a row and it POLLS the list (3s busy / 15s idle, never in a hidden
  tab) and retries the stream a minute later, telling every wait riding the stream it was lost.
  Verified locally: a SIGKILLed API drops the tab to polling, a restart (new boot) brings it back live.
  A graceful stop is different: uvicorn without `--timeout-graceful-shutdown` holds the stream open
  forever, which is why that flag is set wherever the server runs. **What a job spent is exact and on
  the job**: `src/charge.metering` is a contextvar listener that every `Charge` reports its hold,
  settle and release to; `app/jobs.start`'s runner binds one and keeps `credits` (debited),
  `credits_held` (held right now, a multi-shot render's running cost) and `charged` on the job.
  An uncharged render that RAN (the exempt operator account) reports what it would have cost with
  `charged: false`, which the tray prints as "87 cr · not charged" like the Queue. The tray
  (`components/studio/activity-tray.tsx`, a bell beside search) lists running and finished jobs with
  their words, progress, credits, age, Open (`lib/job-feed.resultOf`: a concept id -> the scene, a
  cut export's uuid -> the editor, a sheet -> Elements, a Director render -> Assets) and Cancel; its
  dot counts jobs this tab SAW end since it was last opened, and an opt-in browser notification
  (permission asked only on the click that turns it on) fires for a job that ran 20s+ and ended done
  or failed while the tab was hidden. Any job ending re-reads the balance and the Queue badge (a Queue
  render finishing used to tell neither). Below 640px the header drops Library too, for the bell.
- **The ⌘K palette and global search (2026-10-08, gap list items 1 and 2).** ⌘K / Ctrl+K from
  any studio page, the rail's "Search ⌘K" and the header's search button (the phone's only door:
  the header's Timeline tab gives way below 640px) open `components/studio/command-palette.tsx`,
  a Base UI dialog mounted by the shell with props, not `useShell` (the two would import each
  other). Typed words go to ONE route, `GET /api/search` (`src/search.py`): projects (title,
  brief), scenes (title, card line, logline, spark AND shot 0's prompt -- `shots_json` is TEXT, so
  `::jsonb`), elements (characters, props/products, places by name and notes), renders (the wall,
  by prompt, removed ones excluded) and cuts, for the signed-in account only. Every word must match
  (ILIKE, `%`/`_` escaped); live before archived, then title-starts-with, all-words-in-title,
  the rest, recency within. Empty `q` is the recent projects and open scenes. The route mints one
  drawable `thumb` per hit (`_drawable`, `_element_photos`). The palette ranks its own commands by
  the same every-word rule (`lib/palette.ts`, node-tested). **Nothing in it spends**: "Draw
  keyframes" opens the Queue (the priced button), "New project" and "Find references" open Create
  with a `?spark=` for the Guide (projects are only made through it; references are its
  `find_references` tool), and a new spark is re-applied while Create is open, caret at the end.
  Results open through deep links that work on the page they target: `/studio/elements?open=<id>`
  and `?new=1`, `/studio/assets?open=<generated id>` (it clears filters that would hide it), read
  by `components/studio/url-params.tsx` (useSearchParams in its own Suspense boundary) and
  stripped from the URL once used.
- **The studio's chrome: one palette and a toast stack with Undo (2026-10-08, the front-end gap
  list vs LTX / invideo, items 6, 17, 18, 20; its item 22, credits everywhere, landed as #166).**
  **One palette**, on `:root` at
  the top of `web/src/app/studio/studio.css` -- the signal (`--signal` #e4002b, `--signal-hi` for
  red TEXT, `--signal-deep`, `--signal-soft`, `--signal-wash`), surfaces (`--void` .. `--slate`),
  opaque edges (`--edge-lo/--edge/--edge-hi`), ink (`--text`, `--bone*`, `--dim*`), `--ok`/`--warn`.
  `:root`, not `.zps`, because Base UI portals mount on `<body>` (which is why the credit pill
  and `.cx-portal` had carried copies); only COLOURS live there -- the font tokens need next/font
  variables that exist on the studio wrapper alone. `globals.css` maps the Tailwind
  `noir-*`/`bone*`/`gate-*` colours onto it (noir-red IS the signal now; the cards' #e23b2e and
  the pill's #d10024 are gone), `flows.css` and `.cx-portal` dropped their copies, and the
  composer's `--zc-*` roles name palette tokens. A new colour goes in the palette, never a hex in
  a rule. `.cx`'s `--cx-*` editor palette (track colours, Resolve-cool panels) is deliberately its
  own. **The toast stack** (`shell.tsx`): up to 4, top-centre under the header (the bottom edge
  is the pill's, the composer hint's and the job rail's), each on its own timer (held on hover),
  dismissible, and `toast(text, kind, {action, onClose})`. Undo is the server's INVERSE route
  where the change is soft -- archive (`archived:false`), Queue reject (un-archive, then re-pick
  if it was picked), mark-shot (`shot:false`), project archive, and the two restore routes added
  for it, `POST /api/assets/generated/{id}/restore` (`render_assets.restore`, back on the wall
  AND the shelf) and `POST /api/cut/projects/{id}/restore` (409 `taken` when the scene's cut was
  opened again since). An ELEMENT delete is a hard DELETE, so it is HELD instead
  (`element-sheet.useElementDelete`): off the page now, `getAssets` leaves it out of any listing
  read meanwhile, the DELETE goes when the toast closes or the page is left (`pagehide`,
  keepalive), and Undo means nothing was ever sent.
- **`src/projects.py`** + **`src/project_context.py`** — studio PROJECTS (2026-09-28, Mike's
  call, the day ANTIHERO was merged into Zero Page): one brief and one memory per piece of
  work (a client's ad, a short). `projects` is OWNED; `shoot_concepts.project_id` files a
  scene under one. The memory is what the project LEARNED -- every board pick and pass
  inside it, one entry per concept (a re-pick replaces, a pass cancels the pick, an un-pick
  withdraws) -- and `brief_block` hands the brief + the newest `PROMPT_MEMORY` lessons to
  the writer through a ContextVar that `shootgen.load_brand` appends ("" outside a project,
  so the block is byte for byte what it was). Per project on purpose: a perfume ad's lesson
  must not steer a horror short; the shared shelves still learn from everything.
  `/api/projects` (CRUD, `draft-brief`, `archive`, `forget`); `/scenes/run` and the Guide
  take `project_id` (unknown -> 404); the board takes `?project=`, narrowed INSIDE the
  window. The React Projects page opens the composer with `?project=<id>`, remembered per
  browser. `accounts.seed` now makes ONE account.
  **The LOOK belongs to the project too (2026-10-02, Mike's call: the studio has no house
  style).** `projects.look` (additive column, `''` by default; POST/PATCH `/api/projects`
  take `look`, no UI box yet) is resolved in ONE place, `looks.look_block`: a project in
  scope (passed, or `project_context.current()`) -> its look, or `""` when none is typed;
  anything else -> `""`. All readers follow the ContextVar with no argument threaded. Both
  scene writers carry a `{look}` slot (`scenes_prompt.txt` gained one -- the Studio Create
  never read the look before) and print `prompts/look_unset.txt` in its place when it is
  empty. **NO BRAND LOOK AND NO BRAND NOTES (2026-10-04, Mike: "you're building the brand
  and look from scratch" with each project).** `prompts/look_zeropage.txt`,
  `look_antihero.txt` and `brands.txt` are deleted, and so is `scout.BRAND_NOTES`. A brand
  is a label now: `shootgen.load_brand(brand)` returns the active project's brief + memory,
  or `prompts/project_unset.txt` ("the idea and the attached references are the whole
  brief") -- the scene templates' old CHANNEL DIRECTION slot reads PROJECT, keep its
  must-haves and nevers, the idea and images win on anything else. The crawl digest and the
  research brief carry no BRAND / brand note / LOOK lines and no Antihero/Zero Page casting
  rules. **NO LIKENESS AND NO BRAND IDEAS (same day, Mike: "Remove all likeness and brand
  ideas. Only keep templates related to shots and prompts to help the brain").** Gone:
  refgen's Michael identity path (his photos, the Pro model, the stubble opener, the framing
  rule) -- a hook frame naming anyone renders like any other; `shot.HOUSE_LOOK` ("noir,
  gritty, crushed shadows, desaturated", the default on every `Shot`) -- a Shot has no look
  unless given one and a renderer with no look writes no Style line, and the negative is
  only `CLEAN_NEGATIVE` ("no text overlays, no logos"); `ZEROPAGE_FORMATS` +
  `format_skeletons` + `ranked_formats` + `src/format_feed.py` and the Director chips;
  `CAST_BRANDS` (every brand gets the cast); the brand-keyed crawl queries (one neutral set,
  the dicts kept only because callers index by brand); `inspiration.DEFAULT_ACCOUNTS` (three
  Antihero noir creator profiles seeded from code -- the rows already in a database stay
  until someone deletes them); the Zero Page-only concept/ideas/shot-list templates,
  `design-system-antihero.md`, `brief.txt`, `settings.txt` and the dead edit/pitch prompts;
  the "solo filmmaker" / "Zero Page Films" persona lines in the live templates; the
  "Michael finds a cyclops" card-line examples. KEPT on purpose: the uncanny judge (Mike's
  call), the brand LABELS (their removal is scoped separately), and the dead camera-era
  `concept_prompt.txt` / `shotlist_prompt.txt` with their uncalled builders.
  `gold_standard.md` was rewritten on 2026-10-02 off the monster/portal
  dark comedy (same five-part shape, one take, daylight). `tests/test_project_look.py`
  guards all of it.
  The exemplar is NO LONGER a winner: startup used to seed it onto the `winning_prompts`
  shelf (`seed_gold_standard`); live row #2 and its 4 chunks were deleted by hand, and
  `app.main.retire_gold_standard` now runs at boot instead, removing any row with that exact
  note (and its chunks, via `winners.retire_by_note`) and seeding nothing.
- **THE COMPOSER IS DRAWN TO THE "ZPF COMPOSER DIRECTIONS" MOCK (2026-10-02, Mike:
  "create a similar look to the images shown in our mock design" -- the first port,
  Direction A, had not translated).** `web/src/app/studio/page.tsx` +
  `components/studio/composer/` (`composer.css`, `turns.tsx`, `slash-menu.tsx`) +
  `lib/composer.ts`. The page is flat #0b0b0b with the red field off, one centred box
  under "What are we making?" (Inter, not Oswald), an Image | Video segment, Guide as
  a toggle beside it, the settings as one line (frame · length · model ⌄), a round red
  send that dims when there is nothing to send, four starters, a mono keyboard hint
  pinned to the bottom; `/` opens commands (Direction A's: image / video / guide /
  animate / ref / element + the camera presets off `/api/presets`), a drop covers the
  box, Enter sends, a running send shows Stop. A send becomes a bubble on the right
  with its result as tiles underneath -- a VIDEO send's written scene as its timed
  shots (its still when one was drawn, else the number, a seconds badge, red border
  on the selected one, which is the shot Director opens on), an IMAGE send's one still
  at its aspect -- then Pick on Pipeline / Open in Director / Reuse prompt; the Guide's
  answer sits on the left in the same stream with its chips, sheet and confirm card.
  Motion (`motion/react`) draws the entrances, the slash menu and the send button.
  **What a send made is SAVED on its turn** (`Turn.made`, `lib/composer.ts Made`): the
  thread is the one `assistant-thread.tsx` keeps, so a still drawn here survives a trip
  to Pipeline, and a send left running is picked up again on return by its job id
  (page state holds only the progress ticks -- a save per tick would be a PUT a
  second). The pill leaves `made` turns out of its card and of the conversation it
  sends, and stays off `/studio` itself (the Guide is in the box there, on this same
  thread). **The header is the mock's, on every studio page** (`shell.tsx`): the red
  dot + Zero Page Studio, Create / Library / Timeline in the middle (the box, the
  Assets wall, the editor -- the rail still carries every page), the balance, **New
  session** (`lib/assistant.ts requestNewSession`, a window event the thread provider
  takes, since the shell sits above it: the open conversation is archived -- kept,
  never deleted -- and the box cleared) and the avatar, which opens the account menu.
  `EMPTY_DRAFT.mode` is `create` now. Verified in the Browser pane against a stubbed
  API (real routes, real rows, every model call replaced): send, slash, drop, Guide,
  reload, resume, Stop, New session, 390px.
- **THE BRAIN IS THE COMPOSER, AND IT MAKES (2026-10-04, Mike: "there is no guide
  button, it is all in one place where you can toggle between image and video that are
  connected to the reasoning/brain"; found when "Let's bounce ideas of what the ad should
  be" in Image mode drew a Red Bull packshot instead of answering).** The Guide toggle is
  gone from the React composer: EVERY send is a Guide turn (`POST /api/creative-guide`
  with `output=image|video`, the Image | Video switch), and the model decides between
  talking and making. Two write tools, `guide_tools.MAKE_TOOLS` (`make_image`,
  `make_video`), are published only to a maker turn (`session(maker=True)`); the turn
  ends on the call as a proposal, as every write does, and the STUDIO runs it -- the page
  posts the brain's prompt to `/api/scenes/run` (video) at once, since the send was the
  ask and writing a scene costs nothing, and to `/api/generate/run` (image, with the
  picked `image_model`) as a **step card** (2026-10-08, Mike: "similar to Runway's in
  their chat", i.e. Runway Agent's "Ask before generating media"): a still spends credits,
  so the brain's answer for a make is the prompt it wrote (never the stock "I can ...:
  {json}" line a board write carries) and the card shows it with the frame, then
  **Approve** with the model and what a still costs under it ("Nano Banana · 10 credits",
  "not charged" when exempt). The settings line's **Ask first / Auto** pill
  (`lib/composer.ts GENERATE_MODES`, per browser, Ask by default) is Runway's toggle: Auto
  draws on the send and the card is only the record. The click draws the still into that
  same turn; the card stays as the step's record (Generating / Done, or "Approve again"
  after a failure) and survives a reload with the thread. **The pill has the same card**
  (same day): `components/studio/still-step.tsx` is ONE card for both surfaces; the pill's
  turns ask as `output=still` (`creative_guide.OUTPUT_NOTES["still"]`, `MAKES_FOR` ->
  `guide_tools.session(makes=("make_image",))`: a still, never a scene), its Approve draws
  through `/generate/run` on the composer's remembered model into the shared turn (so the
  composer shows it as its own), and a still waiting on Approve turns the face amber. `/creative-guide/act` and `guide_tools.run`
  refuse the make tools. `prompts/creative_guide_make.txt` is the rule the brain follows:
  make ONLY on an ask in this turn in so many words or a confirmed offer, talk on "let's
  bounce ideas", and write the prompt as the work; `creative_guide.OUTPUT_NOTES` tells it
  which thing a "make it" means. The Fast / Reasoning pill is the brain's and shows in
  both outputs; a personal connection (ChatGPT / Claude) has no tools, so it talks and
  the brief's Make button is how it makes. Without the guide (no Gemini key) a send makes
  directly, as before. On the page: the brain's one-line answer carries `made` (the tiles
  under its words), the person's own bubble carries it when they pressed Make on the brief,
  and the conversation the brain reads says what each make produced. The draft's `mode`
  is stored and read by nothing.
  **Images come from fal too (same day, Mike's call).** `fal.IMAGE_MODELS` is six
  models (FLUX 1.1 Pro, FLUX.2 Pro, Nano Banana Pro through fal, Seedream 4.5, GPT Image 2
  under the `openai/` namespace -- three named sizes priced each, `quality` sent as medium
  since fal's default is high at four times the price, up to 16 references -- and Ideogram
  4.5; Seedream 4.0 and Ideogram 3 were replaced by their 4.5s on 2026-10-08, Mike's call,
  Seedream's frames sent doubled because 4.5 refuses under ~3.7 MP), each with its text endpoint, an `edit` endpoint when it takes references
  (`image_urls`), how it wants the frame (`size`: wh / aspect / enum), a dated price and
  a source URL. `GET /api/image-models` is the composer's picker, a PROJECTION: Nano
  Banana on the Gemini key plus fal's table when `FAL_KEY` is set, with credits per still.
  `/api/generate/run` takes `image_model`: a fal id goes through
  `fal.generate_image_from_prompt`, which now takes the SAME charge a Nano still does
  (hold at `fal.image_usd(model, aspect)` before the submit, settle on the generations
  row, release on failure), banks the still on the Assets wall under its model, uploads
  each reference public through `as_image_url`, and reports `references` so the card
  says when a text-only model drew from the prompt alone. A megapixel is 1024x1024 and
  every frame in `fal.IMAGE_SIZES` is under one. The four added models' ids and prices
  were first written from memory (fal.ai unreachable from the build session) and
  VERIFIED the same day against their fal pages via search: three matched, and FLUX.2
  Pro's was corrected to $0.03 for the first output megapixel plus $0.015 per further
  megapixel of input and output, so `image_usd` takes `references` and a FLUX.2 edit is
  priced dearer than a text draw (BACKLOG #23 has the detail).
- **THE BRAIN HAS A SKILL SHELF (2026-10-10, Mike, after the Runway / Higgsfield / invideo
  teardown: "take some out of the runway and higgsfield playbook first";
  `docs/tasks/task-studio-agent.md`).** `src/skills.py` + `prompts/skills/<name>.md`. A skill is
  a recipe for one KIND of work, where the playbooks in `prompts/stages` are one per STEP: five
  on the shelf -- `character-sheet`, `single-shot`, `multi-shot`, `product-still`, `mood-board`
  -- in the studio's own words (the pattern is Runway's slash skills and Higgsfield's skill
  files; none of their text). The header is flat `key: value` lines (`name` = the file's stem,
  `title`, `for`, optional `output` and `order`); a file without them is not on the shelf, and
  an empty shelf publishes nothing. A skill reaches a turn two ways. **The brain loads it:**
  `load_skill` is a READ tool (`guide_tools.LOCAL_READ`, published wherever the assistant's own
  tools are, its `enum` built off the shelf), and the shelf's one-line index rides in the
  instructions (`prompts/creative_guide_skills.txt`) only when that tool is offered. **The
  person picks it:** the composer's `/` menu lists the shelf (`GET /api/skills`,
  `web/src/lib/skills.ts`); a pick is a chip on the box, flips Image | Video to the skill's
  `output`, and sends `skill=<name>` on THAT send only -- the recipe rides on the turn already
  loaded (`skills.picked_note`, no tool round). Either way `reply.tool_runs` names it, so the
  thread reads "used the Mood board skill" (`lookedOf` / `lookedLine`) and the person's bubble
  carries the pick. A skill is guidance, never permission: a make still ends the turn as a
  proposal, and what the person asked for outranks the recipe. A tool result from an earlier
  turn is not sent again, so the brain loads a skill in the turn it does the work.
  `tests/test_skills.py` holds that a recipe names only tools a Guide turn can be handed and
  never an address. The character sheet is still DRAWN by the landing page's prompt
  (2026-10-09); the skill decides only when, and with what name and outfit. Not built: sheet
  layouts and styles, invented characters, per-model prompt dialects, a write tool for a
  project's look.
- **THE BRAIN PROPOSES A PLAN, AND THE STUDIO RUNS IT STEP BY STEP (2026-10-10, item 2 of
  `docs/tasks/task-studio-agent.md`; Runway's "Ask before generating", Higgsfield's plan and
  Approve).** A Guide turn ends on its FIRST write, so "make an ad from these photos" could only
  ever be one make per message. `make_plan` (`src/make_plan.py`) is still ONE write that ends
  the turn unrun -- its argument is the list: two to eight steps, each `image` / `scene` /
  `sheet` / `keep` (the existing makes, their arguments checked by `guide_tools.check_args`
  under each tool's own name, so the URL rule and every bound hold inside a plan) or
  `keyframes` / `queue`, which act on a scene step earlier in the same plan. Offered only to the
  composer (a maker turn handed every make; the dock draws a still and nothing else), with its
  own paragraph in the instructions (`prompts/creative_guide_plan.txt`) only where it is
  offered. A plan of one step comes back as that step's own tool (`collapse`). **Nothing on
  the server runs a plan**: `guide_tools.run` and `/creative-guide/act` refuse it like any make.
  The composer runs it (`web/src/lib/make-plan.ts`, pure and node-tested;
  `components/studio/make-plan-card.tsx`; the loop is `runPlan` in `app/studio/page.tsx`)
  through the doors each step always had -- `make` for a still and a scene, `runSheet`, the
  keep, `POST /concepts/{id}/keyframes`, the pick -- so a plan adds no spend door and no new
  charge, and **never renders a clip**: its last word on a scene is the Queue. The plan lives
  on its turn (`Turn.plan`, saved with the thread); a step's RESULT is an ordinary turn under
  the card. With Ask first on, the plan waits for Start and each step that costs credits stops
  for its own Approve beside its price; "Approve all" covers only the steps priced on the card
  when it was clicked -- a scene's keyframes are priced once the scene exists, so they still
  ask. With Auto it runs through, as a single make does. A step can be edited or skipped
  before it runs; editing one that ran sends THAT step back to pending and leaves every other
  finished step alone; the first failure stops the plan where it is; Stop ends the wait on a
  running make and charges nothing for it. `finishProject` (the talk is cleared once a scene is
  written) runs when the PLAN is through, and keeps the plan's card with what it made. The
  plan's state is held in a ref (`plans`) and mirrored onto its turn, because the loop awaits
  steps while the person may skip or edit a later one. The file names say `make-plan` /
  `make_plan`, never `plan`: `tests/test_plans.py` and `components/site/plan-*.tsx` are the
  BILLING plans.
- **A RENDER THAT DID NOT HAPPEN IS SAID IN A CUSTOMER'S WORDS, AND IS NEVER "DONE"
  (2026-10-10, found on the live composer).** A still whose draw failed at the provider came
  back from `/api/generate/run` as a finished job -- the scene row it rides on WAS saved -- so
  its step card read Done · Approved over a tile holding the provider's raw text ("User is
  locked. Reason: Exhausted balance. Top up your balance at fal.ai/dashboard/billing").
  `src/failures.py` `plain(raw, what)` is the one place a provider's error becomes a sentence
  for the page: four causes a person can act on differently (the studio was turned away, the
  service is busy, the model declined the prompt, no answer) and one fallback, each ending
  "Nothing was charged." -- a fact, since every adapter releases its hold on failure and a
  refusal for an empty balance or a cap comes before any hold. The studio's own refusals
  (`charge.refusal`, `generative.cap_error`) pass through as written. The raw error goes to
  stderr and stays on the generations row. On the page, `web/src/lib/made-state.ts` reads a
  record honestly: a still with status done and no image is `failed` (the card says Not drawn
  and offers Approve again), for threads saved before as well, and `failLine` keeps an old
  thread's raw text off the line. Applied to the still route only so far; keyframes, sheets
  and Queue renders still report their adapters' own text.
- **EFFECTS IN THE CHAT: A GALLERY THAT RUNS NOTHING, AND A PRICED CARD THAT DOES (2026-10-10,
  item 3 of `docs/tasks/task-studio-agent.md`).** `src/effects.py` (the dated table the studio
  MCP surface already spends through) now has the studio's own door. `GET /api/effects` is the
  gallery, a PROJECTION of that table (`api._effect_view`: label, a one-line blurb from
  `EFFECT_BLURBS`, what it takes and gives, its legal options, and a from-price in credits or
  `null` when the price hangs on a clip's length) under four tabs (`EFFECT_CATEGORY_LABELS`:
  Edit an image / Animate a still / Camera moves / Finish a clip). `POST /api/effects/quote`
  prices ONE request and spends nothing; `POST /api/effects/run` is the click that spends and
  takes `expect_credits`, the number the card showed -- absent is 400 `missing_price`, a price
  that moved is 409 `price_changed` with the new one, so an effect runs at the price shown or
  not at all. No signed token: the token's content hash is a scene's, and an effect has no
  scene. Both routes go through `api._effect_request`, which runs every check the MCP's
  `run_effect` runs (`effects.spec` / `check_options` / `check_prompt` / `check_sources`, a
  clip measured by `effects.probe_video` before it is priced) and the same `effects.run`
  (hold, generations row, settle, Assets wall), with `source="composer"`. **A source is named
  the way the composer holds it:** `gen:<id>` for a render on the wall -- the ONLY way a clip
  is named -- or a reference path (an upload, an element photo, a still on this machine's
  disk, read by `imagery.render_bytes`, which opens nothing outside `data/renders`). At most
  `EFFECT_SOURCES_MAX` (4). So that a result can be named, `/api/generate/run` now returns
  `asset: "gen:<id>"` for a still and the effect job returns the same for what it made.
  **A job's result is merged onto the job**, so the effect job answers `media` (image|video)
  and never `kind` -- `kind` is the job's own and the activity tray reads it.
  **The brain has two tools for it** (`guide_tools.EFFECT_SPECS`, published only to a composer
  maker turn, never to the dock's stills-only turn): `list_effects` (a read; the exact
  template and camera-move names) and `apply_effect {effect, options?, prompt?}` (a make: the
  turn ends on it). It never names what the effect acts on -- the studio binds it to what is
  attached to the box, else the newest result that fits, and the card shows which. A call
  `_check_effect` refuses (an unknown effect, a made-up template) is handed back to the model
  as the tool's error instead of failing the turn, bounded by `MAX_TOOL_CALLS`.
  `prompts/creative_guide_effects.txt` is the rule: only on an ask in this turn, look names up
  rather than invent them, never state a price. **On the page** (`web/src/lib/effects.ts`,
  pure, node-tested): `/effects` in the slash menu opens `effect-gallery.tsx` above the box --
  browsing is free, a row whose source is missing is disabled with the reason ("Needs a clip:
  animate a still first, then finish the clip it makes") -- and a pick, or the brain's call, puts
  `effect-step.tsx` in the thread: the source thumbs, each option as a select (a search box
  over twelve values; a required one starts on "Pick one"), the words, the live quote, and
  Approve beside the credits. The card is the still step card's look (`still-step.css`) with
  choices on it. `Turn.effect` holds the state and, once approved, `paid` (what Approve was
  pressed at -- a finished card is never re-priced); the result is the turn's `made` with
  `effect`, `asset`, and `clip` for a video (`made-state.undrawn` counts a clip as drawn).
  A failed effect says `failures.plain(err, "The effect")` and the card offers Approve again;
  an effect turn has no "Reuse prompt" / "Try again", its card is the retry. Effects are
  Ask-first ALWAYS: the Auto pill does not cover them, since the card is where the choices
  are made. Not built: effects as plan steps, effects in the dock, a preview per template, and picking a
  clip the conversation does not hold (a Queue render is on the Assets wall, and the composer
  has no way to name it yet).
- **ONE conversation, and it is saved (2026-10-02, Mike: "when I click out of the
  studio page the entire conversation, images that were generated goes away").** The
  Studio composer's Guide thread was React state in `web/src/app/studio/page.tsx`, so
  leaving the route threw away the talk and every contact sheet under it, while the
  floating pill kept its OWN thread in `assistant_projects` (`src/assistant_store.py`,
  2026-09-29). Now `web/src/components/studio/assistant-thread.tsx` holds the one thread
  for the whole studio -- mounted in `studio/layout.tsx` above both the pill and the
  pages -- and the composer and the pill are two views on it: a turn typed in the box is
  in the pill when it opens on Pipeline, and a chip tapped there is in the box on the
  way back. `lib/assistant.Turn` is the union of what either surface writes (`reply`
  carries the sheet, the proposal, the brief, the directions); each draws what it knows.
  **The box is saved with it:** `assistant_projects.draft_json` (additive ALTER,
  `_clean_draft` bounds every field) holds the idea, the guide's brief, the mode, the
  picked references, the uploads and the "scene written" card; `PUT /api/assistant/project`
  takes an optional `draft` and a body without one leaves the stored draft alone
  (COALESCE), so the pill's old save shape cannot blank the box. **An upload is saved to
  the bin the moment it is dropped** (`POST /api/refs/upload`, the Director's route) and
  the draft remembers its `/refs/<sha>.jpg` URL, sent as `asset_photos` like a pick --
  uploads first, since refs[0] anchors the clip and they were read first as `files`. A
  File object could never have survived the page. Load is the pill's rule, kept: the tab's
  sessionStorage copy paints first, the server's copy wins; `?spark=` and `?attach=` are
  applied only after that load so a saved draft cannot land on top of the visitor's
  sentence. **A conversation is WORKING MEMORY, never a record (same day, Mike's call):**
  it is saved only so the person can pick it up where they left off, on any page. Once
  Create has written the scene it goes away -- `finishProject` clears the Guide turns, the
  brief, the box and its references, leaving the "scene written" card: with the mock
  composer that card is the send's own `made` turn, so those turns are the one thing it
  keeps -- and the pill's pen and the header's New session (`clearProject`) clear
  everything by hand. Nothing is ever archived: `DELETE
  /api/assistant/project` deletes the row (`/project/new` is the older name for the same),
  and `assistant_store.init` drops the rows the 2026-09-29 archive-on-new left behind. What
  a conversation produced lives on the concept and, once rendered, on the asset with its
  prompt, which the Assets wall shows. Nothing here calls a model or spends. Verified in Chrome against a throwaway schema: idea, pick
  and upload survived a rail round-trip and a reload with sessionStorage cleared; a real
  Guide turn in the box appeared in the pill on Pipeline, and the pill's reply there was
  the fourth turn in the box.
- **`src/refbin.py`** — one owner for `data/refs`, both directions: the content-addressed name,
  the JPEG normalisation (EXIF transpose BEFORE `convert("RGB")`, HEIC when `pillow-heif` is
  present), `save`, `fetch` (bounded download for scouted images) and `resolve`. It exists
  because `src/` cannot import `app/` and the scout writes where composer uploads live; the
  read had to move with the write, since a patched writer and an unpatched reader is a file that
  saves successfully and then resolves to nothing. `app/api.py`'s `_to_jpeg`/`_save_upload_ref`/
  `_resolve_asset_photo` now delegate. **The URL shape is the point**: a scouted image comes out
  as `/refs/<sha>.jpg`, so it rides the composer path with no new route or resolver.
- **`src/linkrefs.py`** — a link the person pastes into the Guide becomes a reference frame
  (2026-10-01, Mike: "focus on image first"). The one place scraping is right: a page the PERSON
  chose, one fetch, its own preview image (`og:image` / `twitter:image` / `<link image_src>` /
  JSON-LD `Product.image`), no model, no headless browser, no crawl — a vision model browsing for
  images was refused (10-50x the cost, blocked hosts, invented URLs). **The model never handles the
  URL**: `guide_tools.check_args` refuses one in any tool argument, so the route
  (`creative_guide_reply`) reads up to 3 links off the person's own last message, `assistant_brain.
  link_sheet` registers the frames through `imagesearch.remember` (real ids, so `keep_references`
  keeps them with no new write path) and screens them with `refcheck.screen`, and the row goes
  FIRST on `reply.sheet` — a rejected frame stays on the sheet greyed with the reason, a frame
  nobody could look at is still offered (the person chose it, like an upload), and a page that
  gives nothing is a row with a note, never a silent one. The model gets ONE line
  (`assistant_brain.link_note`: "N frames from the link they pasted are on the sheet"), never the
  address. Fetches go through `refbin.public_host` on every redirect hop (followed by hand),
  `FETCH_HEADERS`, a 2 MB streamed cap. Read live: Shopify pages put the site LOGO in `og:image`
  (http AND https, one file) and the product photos in JSON-LD, so one file under two schemes is
  one frame and logo/placeholder names sort last; Ghost's energy-can page itself exposes NO
  product image in any of those (only body `<img>` tags behind a dozen nav tiles) and honestly
  yields the logo greyed plus the note; the Legend/sticks orange-cream pages and Pinterest pins
  give real frames; an Instagram POST gives nothing without a session (the note says so).
  **A prop or link frame is judged on IDENTITY, not mood (2026-10-02, Mike's call).** With
  Serper live, every clean packshot of the Ghost can was cut as "studio render on white" against
  the brand look -- the frames most worth keeping. `refcheck.IDENTITY_ROLES` (`prop`, `link`)
  swap the look block for `IDENTITY_BLOCK` (does it show the exact thing, large and sharp; a
  packshot on white is a KEEP); the clean-frame floor and the anti-references still apply, and
  place / light / mood / texture / wardrobe still sit inside the look.
- **`src/cut/`** — the editor, phase 1 of `docs/CUT_EDITOR.md` (Assemble v0, 2026-09-26).
  `doc.py` is the timeline document (OTIO-shaped, INTEGER FRAMES at the project fps, tracks
  V / A with a role voice|music|sfx / T captions, media named by `gen:<generated_assets.id>` or
  `asset:<cut_media.id>` HANDLES, never URLs); `ops.py` is ten pure doc -> doc edits (the only
  edits the future agent may emit; a clip and its `link`ed sound move as one) and
  `validate.py` the rail every doc passes before it is stored or rendered (overlaps except a
  transition's exact overlap, src_out past the media, unknown handles, duration mismatch, and
  speed/lanes REFUSED until they render). `sources.py` is the only place a handle becomes a
  file (local first, else `media.url_for` fetched through `refbin.public_host`); `store.py`
  owns `timelines` (insert-only versions with `parent_id`; the one later write is
  `export_url`, a derivative of that frozen doc), `timeline_heads` (rollback moves the
  pointer) and `cut_media` (uploads: audio, and since phase B video and stills), all three
  OWNED; a timeline key is `concept:<id>` (or, since phase B, a scratch `cut:<uuid>`).
  `assemble.py` refuses a part with no clip or a clip with no Asset Bank row rather than
  fall back to a URL; `render.py` compiles one `filter_complex` and files the MP4 under
  `data/renders/cut/`, mirrored like any render. **Homebrew's ffmpeg has no libass**, so on the
  Mac captions are NOT burned (the `.ass` lands beside the MP4 and the job says so); the Fly
  image's Debian ffmpeg burns them. CI installs ffmpeg so the render tests run rather than skip.
  **The index (phase 2, 2026-09-28)** is `index.py` + `moments.py`: per file (by sha256, stale
  on read) a proxy when the source is over 720p, shot cuts from ffmpeg's scene score (no
  OpenCV), ONE Gemini shot log for all shots (`prompts/cut/shot_log.txt`, JSON checked by
  `check_log` -- sizes/angles/quality flags off the list are dropped), and fal Whisper at word
  level with diarisation ONLY when the log heard speech (Whisper invents words over ambience,
  which is most generated clips). `media_index` / `media_moments` are OWNED; words carry
  timing, only segments and shots are embedded (the RAG library's 768-dim space, in the main
  database, the vector type schema-qualified because a test schema cannot see `public`).
  `index.find` is THE search (hybrid: vector + text, reciprocal rank) behind both
  `GET /api/cut/search` and the pill's read-only `search_footage` tool, which returns handles
  and times, never URLs. Captions on Export were considered and dropped (Mike, 2026-09-28):
  editorial features belong to the editor, not to Assemble.
  **The editor's server half (phase B, 2026-09-28)** is what `web/src/app/studio/cut/` reads.
  A project is an OWNED `cut_projects` row (Mike's D2) naming the `timeline_key` its versions
  live under: `cut:<uuid>` for a scratch project (a starter doc: V1, A1 sfx, A2 music, not
  ducked, at 9:16 / 16:9 / 1:1), `concept:<id>` for a concept's cut -- create-or-return, so it
  shares Assemble's history; with no history yet v1 is `assemble.build_doc` over the CACHED
  probe (never rendered), or the empty starter when a clip is missing. `src/cut/projects.py`
  is the one door an edit takes: `POST /api/cut/projects/{id}/ops {base_id, op, args}` ->
  409 `stale` (with `head_id`) unless base_id is still the head (checked under a row lock in
  `store.save_version(expect_head=)`), 422 `invalid` with `problems` from `ops.apply`, else a
  user version whose `op_summary` is `ops.describe` ("split c3 at 4.2s"). Undo/redo move the
  head; `timeline_heads.redo_id` holds the TOP of the undone chain (so multi-step redo works)
  and anything that makes history clears it. **Media is measured once:** `cut_media_cache`
  (OWNED) holds each handle's probe keyed to the `media_url` it was taken from (a re-pointed
  render is re-probed) plus its previews, because a `gen:` file lives in R2 on Fly and an op
  must not download the timeline to validate a trim; `sources.measure` is the reader. A handle
  already on the timeline that cannot be measured is passed to the validator as None
  (known-but-unmeasured -- one unreachable file must not freeze the cut); a handle an op would
  ADD must measure, or 422. Ops added: `lift`, `set_canvas`, `set_cue` / `delete_cue` /
  `set_caption_style` (styles are `doc.CAPTION_STYLES`, drawn by `render.CAPTION_PRESETS` --
  bold_center, lower_third, minimal_top -- and the validator refuses any other), and
  `add_caption_track(cues=[])` makes an empty T track. Uploads take video and images too; an
  image probes as a STILL (`d.STILL_SECONDS` of picture, no sound) and renders with `-loop 1`.
  `src/cut/preview.py` builds per file (by sha256, reused across handles) a 540p proxy keyed
  every second, a 90px filmstrip sprite (<=120 frames) and waveform peaks (50/s, absolute),
  as a job on upload or on the first `GET /api/cut/media/{handle}/preview` (a compare-and-set
  claim, so two polls start one build; `failed` is not retried by polling), under
  data/renders/cut/preview/ and mirrored to R2. `POST .../export {timeline_id?, aspect?}`
  renders any version in a job; another aspect first becomes a user `set_canvas` version.
  Nothing in any of it spends.
  **The Source viewer (2026-10-01)** is the first gap the invideo captures named
  (`docs/reference-look/invideo-editor/`): a clip is looked at, marked and cut BEFORE it touches
  the timeline. Double-click a bin tile to load it (the tile's `+` still appends); it has its own
  clock and In/Out marks per handle (`I`/`O`, session-only, frames at the PROJECT fps so a range
  is already the op's `src_in`/`src_out`, Out exclusive). Insert (`F9`/`,`) puts the range in AT
  the timeline playhead, splitting a clip under it first (two versions: the split, the insert);
  Overwrite (`F10`/`.`) is the new pure op `ops.overwrite(track_id, clip, at, sound_track=)` --
  composed from split, lift and insert, clearing the span as LINK GROUPS so picture is never
  overwritten out from under its own sound -- and Append (`Shift+F12`) goes to the track end.
  The transport keys follow the ACTIVE viewer (`activeViewer` in the store, a red rule on top).
  `GET /api/cut/media/{handle}/transcript` serves the index's words and shots in SECONDS (the
  index has its own fps) for the Transcript tab: click a word to go there, drag across words to
  mark them. Not indexed answers `not_indexed`; the tab says so and never runs the index.
  **Keyframes, crop and opacity (2026-10-01)** are the clip Inspector the invideo captures showed
  (06-clip-selected-inspector.jpg). `src/cut/lanes.py` (twin: `web/src/lib/cut/lanes.ts`, tests
  pin both to the same numbers) holds a picture clip's `lanes`: `zoom` (0.1-4, 1 = fitted),
  `x` / `y` (fractions of the canvas), `rotation` (degrees); each a list of keys at CLIP-RELATIVE
  frames, one key = a constant, `ease` (linear / ease / hold) on the key a segment starts at. Crop
  (`clip.crop`, fractions per side, <= 0.45) and `clip.opacity` are static. Ops: `set_key`,
  `delete_key`, `clear_lane`, `set_crop`, `set_opacity`; split and trim carry keys through
  `lanes.window` (exact for linear/hold, an eased segment cut in two is re-eased). The render
  gives a looked clip its own chain -- fit without pad, yuva, `scale ... eval=frame`, `rotate`,
  `overlay` at per-frame x/y onto a black canvas of the clip's length -- so the letterbox is the
  canvas; a clip with no look keeps the old pad path byte for byte. Verified on Fly's ffmpeg 7.1.
  The preview draws the same: the CROPPED picture fitted (`lanes.fitBoxes`, contain, not cover),
  then CSS `translate rotate scale` in the render's order. The Inspector's sliders preview through
  the store's ghost and commit ONE op on release, comparing against the SAVED clip (comparing
  against the drawn ghost read every drag as "no change").
  **Speed and reverse (2026-10-01)** finish that Inspector (its Playback row). Speed is never
  stored as a number: a retimed clip carries `dur` (timeline frames) beside its source span, and
  speed is `span / dur` (0.25x-4x; `doc.speed_of`, `source_frame`, `timeline_frame`). That keeps
  the timeline in whole frames however a sped clip is cut -- `trim` and `split` take TIMELINE
  frames and round only the source point, and a reversed clip's head is the END of its source.
  The legacy `speed` key is refused unless it is 1. Ops `set_speed(clip_id, speed, ripple=True)`
  (keys rescaled to keep their place in the clip) and `set_reverse(clip_id, on)`, both on the
  clip and its linked sound. The render: `setpts=PTS*dur/span` then hold-and-trim to the exact
  length, `atempo` (chained, pitch kept) and `areverse` for sound, and a reversed PICTURE is
  pre-rendered one second at a time (`render.reverse_source`, chunks reversed alone and joined
  last-first) because the `reverse` filter holds the whole span in memory -- ~1.8 GB for 10 s of
  1080p on a 1 GB machine. Clean up skips retimed sound with a note; auto-captions follow the
  speed and skip a reversed clip. The preview sets `playbackRate`; a browser will not play
  backwards, so a reversed clip is SEEKED per frame while playing, silently.
  **Transition styles (2026-10-01):** `transition_in.style` is how the PICTURE blends over the
  overlap -- 58 of ffmpeg's xfade transitions (`doc.TRANSITION_STYLES`, grouped Fades / Wipes /
  Slides / Shapes / Slices, every one checked present in Fly's ffmpeg 7.1); absent means `fade`, and
  the sound always crossfades. Ops `add_transition(..., style=)`, `set_transition(clip_id, style?,
  frames?)` and `remove_transition` (the exact inverse of add). The bin's Transitions tab
  (`web/src/lib/cut/transitions.ts`, pinned to the Python list by a test) plays each look on hover
  with the same CSS approximation the viewer draws -- wipes/irises as a clip-path, slides as a
  translate, the rest as the fade -- and a tile clicks onto the selected cut or drops onto a clip.
  **The mixer (2026-10-01):** an audio track carries a fader (`gain_db`, on top of every clip's
  gain) and a `pan` (-1..1, a balance: the far side drops), set by `set_track_mix` and rendered
  per track after its mix (`volume`, `pan=stereo`); a sound clip carries `fade_in` / `fade_out`
  (frames, `set_fade`, which on a picture clip goes to its linked sound) and ONE keyframe lane,
  `volume` in dB (`lanes.AUDIO_PATHS`, keyed through the same `set_key`), rendered as
  `volume=...:eval=frame`. The Inspector's Mixer tab is one strip per audio track: role, pan, a
  vertical fader, and M / S, which stay MONITORING (preview only, like the track headers). The Main
  strip says the truth about the sum: the export is loudness-normalised to -14 LUFS, so the faders
  set balance, not level. The preview multiplies gain x fader x volume key x fades, but an
  `<audio>` element can neither boost past 0 dB nor pan; the strip says so.
  **Export targets (2026-10-01):** `POST .../export {format}` makes the MP4 (`mp4`, the default
  and the only one stored as the version's `export_url`), the mix alone (`audio`, AAC .m4a --
  `compile_args(fmt="audio")` opens no picture input at all), the frame at `frame` (`still`, a PNG;
  no sound input opened), or an EDITABLE PROJECT (`project`): `src/cut/otio.py` writes the doc as
  OpenTimelineIO JSON (.otio, media by public URL and name, gaps, transitions, speed/reverse as a
  LinearTimeWarp, markers) plus captions as .srt -- no ffmpeg. Two OTIO conventions to keep: items
  ABUT, so our overlap becomes the outgoing clip ending at the incoming one's start plus a
  Transition whose `in_offset` borrows the outgoing media past the cut; and an item's
  `source_range.duration` is its TIMELINE length (the warp applies to the media), which is what
  OpenTimelineIO 0.18 reads back to exactly the cut's duration. Keyframes, crop, fades and the
  mix have no OTIO field; they ride in `metadata["zpf"]` so nothing is lost.
  **Pages (2026-10-01), Resolve's model:** one doc, three layouts -- Edit, Audio (the Program
  viewer beside a large Mixer over the SOUND tracks only) and Color (the Program viewer beside the
  grade over the PICTURE tracks only); `store.page`, the top bar's switch, and Resolve's keys
  Shift+4 / Shift+7 / Shift+6. Switching is a view, never an edit. The Color page edits a picture
  clip's basic correction, `clip.grade` = {exposure (stops), contrast, saturation, temperature
  -1..1} (`doc.GRADE_FIELDS`, `set_grade`, neutral values not stored), rendered on the source
  picture before the fit as `exposure`, `eq` and `colortemperature` (+1 warm = a 3500 K light) --
  all three present in Fly's ffmpeg 7.1 -- and previewed as a CSS filter plus a soft-light tint.
  It grades the selected picture clip, else the one at the playhead, so scrubbing walks it from
  shot to shot. Wheels, curves, qualifiers and LUTs are still a later phase.
  **More bin tabs (2026-10-01):** the left panel's Transitions tab became **Effects**
  (Transitions | Looks -- eight one-click grades, each ONE `set_grade` with `reset`, on the clip the
  Color page would grade), and an **Index** tab holds Resolve's Edit index (every clip and cue in
  record order: track, record and source in/out, and what is done to it -- speed, reverse,
  transition, grade, keys, fades, gain; a click selects and seeks) and Markers (go to, rename in
  place, remove, add at the playhead). Markers are named by their frame: `set_marker(frame, label?,
  to?)` (a move onto another marker is refused) and `delete_marker(frame)`. Seven tabs still fit the
  panel's 250px minimum, icons only.
  **The agent (phase E, 2026-09-28, Mike's D4)** never edits: every edit is a PROPOSAL
  (`{summary, ops, base_id, region, duration_delta, doc, kind}`) the person Keeps or Undoes.
  `POST /api/cut/projects/{id}/agent {message, playhead?, selection?}` is a job;
  `src/cut/agent_tools.py` shows the model the head doc as text (`read_timeline`, with names
  from `store.handle_names`), the playhead, the selection and an op catalogue DERIVED from
  `ops.OPS` signatures + `OP_NOTES` (a test fails when an op has no line), and gives it three
  tools: `read_timeline`, the pill's `search_footage`, `propose_ops`. A proposal is run through
  `projects.check_ops` (the ops in order via `ops.apply`, against the measured media, with the
  add-media rule) BEFORE it is shown; a refusal goes back with the validator's reasons ONCE,
  a second ends the turn with the reasons in `notes`. `call_model` is the one seam (tests
  script it); metered as stage `cut_agent`; no key or a dead model finishes the job with a
  reply saying so. `.../agent/keep {base_id, ops, summary}` RE-APPLIES the ops to the head
  (409 `stale`, 422 `invalid`) and saves ONE version by `agent`; Undo is client-side, nothing
  was saved. `src/cut/cleanup.py` is the two model-free jobs, both answering a proposal off
  the index's WORD timings: `.../cleanup` (silences between words over `min_silence`, 0.12 s of
  air left each side, and um/uh/erm/er/ah/hmm -- split+split+ripple_delete, or a ripple trim at
  a clip edge, applied from the END backwards; only sound that is on the timeline, a clip
  whose sound is not is skipped with a note; captions are NOT moved and it says so) and
  `.../captions` (cues of <= max_words and 2.5 s, broken at 0.4 s pauses, mapped through each
  clip's src_in/at; a new track, or `set_cue` onto an existing one without overlapping it).
  Both list `needs_index`; `.../index` indexes exactly the head's unindexed media (cents: the
  click is the approval). `POST /api/cut/projects {handles}` (phase F) starts a scratch cut
  from a selection: footage on V1 with its sound on A1, stills held 5 s, audio-only on A2.
- **`src/pricing.py`** — what a render costs, and the signed quote that says so (steps 1–4 of
  `docs/tasks/task-pricing-and-quotes.md`, on main 2026-09-18; read that doc's "As built"
  section before touching it). Pure module, three answers: `estimate()` is the provider's USD
  and always answers; `quote()` is credits and is `None` on BYOK (`ledger.is_billable` over
  `account_keys.key_source`, the one rule); `display()` is the JSON every card reads —
  `GET /api/queue/pending` carries it per card and `GET /api/queue/{id}/quote` re-prices a
  changed pick, so there is no JS price twin any more (`fitSeconds` and
  `providers.check_timeline_choice` are both deleted). `sign()`/`verify()` are an HMAC token
  (`zpfq.<body>.<mac>`, 1-hour TTL) minted per render when `QUOTE_SIGNING_SECRET` is set —
  its OWN secret, never `SESSION_SECRET`, and a different value on Fly from any dev box; unset
  means prices without tokens and approve exactly as before. Six refusals, checked in order:
  `bad_signature / retired_pricing / expired / wrong_account / wrong_render / stale_content`.
  The content hash is `pricing.content_hash` = `timeline.source_hash(prompt, refs)` computed
  on the LIVE shot, never the stored `timeline.source` — do not write a second one.
  `MARKUP = "2.4"` (2026-09-18, Mike's call: $1.00 of provider cost = 240 credits) is a string
  read through `Fraction` — a float there is a latent off-by-one; `CREDIT_FLOOR = 10`.
  **A billable render needs its token (step 5, same commit as the markup):** when the server
  can sign AND the render is not BYOK — `display()`'s `signed`, one predicate for the offer and
  the requirement — `queue_approve` and the Director's Generate node answer 400 `missing_quote`
  without one. The three doors that show no price send a billable render to the Queue instead:
  `shot_generate`, `/api/generate/run`'s video branch (refused before the job, so no Gemini call
  is made for it), and Run all's Generate node (skipped, not failed — the prompt it renders is
  the enhance node's, which did not exist when any price was shown). BYOK, and a server with no
  secret, behave exactly as before. **Step 6 — the ledger hold — is built** (`src/charge.py`,
  landed with the Stripe billing commit, 2026-09-18): every adapter's `generate_video` takes the
  hold after the spend gate and BEFORE the submit (`InsufficientCredit` there means no HTTP call
  is ever made), marks `submitted()` as the last line before the provider call, releases on any
  raise after the take, and the caller settles against the generations row. `approved=True` is
  still the spend gate's answer; the hold sits behind it, not instead of it. As decided: zero
  credits REFUSES even with a key on file, and the operator's own accounts are exempt
  (`accounts.credit_exempt`, `python -m src.accounts credits <slug> --on`; `ledger.hold_for_render`
  returns None for BYOK, a manual-lane import and an exempt account, so every `Charge` method is a
  no-op there). The daily-cap check stays in the route, not here. **Verified with real money
  2026-09-26** on fal (see "Where the project stands").
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
  today against the caps. Every figure is an estimate and the page says so. **Since
  2026-10-08 the meter also covers** embeddings (`rag.embed_texts`, stage `embed`, estimated at
  four characters a token when the API reports none), the story judge's two raw calls, fal
  Whisper (priced per AUDIO MINUTE at an unverified third-party rate, `cut/index.
  WHISPER_USD_PER_MIN`, since fal publishes none) and Serper (per query): the last two hand
  `record_call` an explicit `cost_usd`, which `reprice` leaves alone.
- **`src/gemini_utils.py`** — shared `generate_with_retry` (retries on `RESOURCE_EXHAUSTED`/
  `UNAVAILABLE`, falls through to `FALLBACK_MODELS` if the primary model stays down for the whole
  retry budget) and `strip_fences` (strips markdown code fences from model JSON output).

### Key conventions to preserve

- **Render provenance lives in `generated_assets` and `params_json`, never in new columns on
  `generations`.** `generations` is the ATTEMPT log; `generated_assets` is the record of what
  successfully rendered (`tool`, `model`, `media_kind`, `metadata_json`, with
  `render_assets._label` for the display name). On 2026-09-18 four columns — `ai_model`,
  `aspect_ratio`, `camera_motion`, `is_favorite` — were found on the live table, absent from
  `generative.SCHEMA`, unwritten by `record_generation` (the only writer) and unread by
  anything in `src app ops tests web/src`. All 113 rows therefore carried their literal
  defaults (`'Nano Banana Pro'`, `'16:9'`, the STRING `'None'`) as if they were data, and a
  fresh `init()` built a differently-shaped table than production. They were dropped. If
  structured per-attempt detail is wanted, it goes in `params_json` — which already carries
  model, ratio, duration, lane and source — or in `generated_assets`. A second provenance
  store beside the first is the mistake `asset_shelf` exists to prevent.

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
  **The Queue PAGE lists them, blocked (2026-09-17, Mike's call).** A row still gets here
  ungrounded three ways — written before the gate, un-archived, or its refs cleared later — and
  dropping it from the list made a picked scene look like a lost pick. `_waiting(...,
  include_blocked=True)` is `queue_pending`'s alone: such a card carries `blocked` (the gate's
  own reason), sorts after every spendable card, and is left out of `spendable`, which is what
  the rail's badge counts. Nothing about SPENDING moved: `_waiting`'s default is still
  spendable-only, so the manual lane never sees one, `queue_approve` still asks
  `reference_gate` itself and answers `no_reference`, and `ops/render_queue.py` is untouched.
  Listing a scene is not a way to spend on it.
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

**Working and verified against real data** (counts read off the live Postgres 2026-09-18):
the ideation loop runs end to end on real Gemini calls. **255 concepts** written, **122**
carrying reference images on the shot, **73** with a keyframe drawn, **205 archived** with a
reason, **11 picked**, **20 marked shot**, **359 recorded graph runs**, 113 generation attempts,
2403 metered LLM calls, **23 videos with 24 metrics snapshots**, 0 described rooms (rooms became
optional material on 2026-08-31 and nothing has re-run `src.locations` since). Reference-grounded
ideation is verified live both ways: `src.shootgen --spark "gearing up ritual"` printed "Grounding
in 5 retrieved reference(s)" against the real library, and the same command with the store pointed
at a dead URL printed the ungrounded note and still produced ideas (exit 0). 2425 tests pass, 8
xfail, ruff clean, CI green on every push — last full run 2026-09-22 on main's tip after the
overnight merges (`ba9e1d8`, PRs #46–#52).

**Billing is in front of the ledger (2026-09-18, docs/BILLING.md).** `MARKUP` is 2.4,
three plans live in `src/pricing.PLANS`, every adapter holds credit before its submit
(`src/charge.py`) and settles on the row, Stripe grants through `/billing/webhook`
(`app/billing.py` + `src/billing.py`), and the public site's `/pricing`, `/models` and
`/faq` are generated off `web/src/content/pricing.json` (`python -m src.pricing export`).
Yearly plans are a SCHEDULE (`credit_schedules`, released monthly by
`python -m src.billing release` and lazily on the money path), never a twelve-month lot.
**Your own account must be exempted once** -- `python -m src.accounts credits zeropage
--on`, with `DATABASE_URL` exported first (the CLI does not read `.env`; see Commands) -- or
the Queue refuses you for having no credit. Both `zeropage` and `antihero` are ON live as of
2026-09-18. Unset `STRIPE_*` = the plan
buttons say so and nothing else changes.
**Beyond renders (2026-09-28/29, Mike's calls; docs/BILLING.md):** a still costs credits
(10 Flash / 33 Pro, held in `nano_banana.generate_from_prompt`; a `refgen` reference is
charged the still that drew it, since 2026-09-29); a **Create costs 0** --
included in the subscription, priced into the plans -- but `charge.create_refusal` refuses
it (402 `subscribe_or_top_up`) for an account with no plan and no balance, and the MCP
`research` / `generate` tools ask the same predicate. **Since 2026-10-08 every route that
spends model text asks it too** (`api._create_gate`: the Guide, the brief draft, an element's
describe, Direct / Polish, the canvas's Ground / Enhance / Run all, the scout, the evals, the
cut's index and agent -- `docs/tasks/task-spend-holes-and-credits.md`). There is NO daily cap
on model text, by Mike's call (2026-10-08): its cost goes into the plan prices, so a trial
account can think without limit until its credits go (BACKLOG #24). **The studio shows
credits, never dollars** (`tests/test_studio_shows_credits.py` guards it); a new open sign-up gets a one-time
**100-credit trial** (`ZEROPAGE_SIGNUP_CREDITS`); and **`NANO_DAILY_CAP` is gone** for
everyone (`nano_banana.DAILY_CAP is None`) -- the balance is the limit.

**THE LOOP CLOSED ON 2026-09-18.** Concept #375 "Neon City Ascent" went spark -> scene ->
references -> keyframe -> pick -> render -> post -> measured, and it is the first one that ever
did. What that means concretely: **1 concept carries a `media_url`** (it was 0 for the whole life
of the project), the clip is a 10.042s 720x1280 h264 with a stereo AAC track rendered on Runway
gen4_turbo through Explore Mode — the subscription lane, `cost_usd` NULL, no ledger hold — filed
on the Fly volume, in `data/renders/runway/`, and mirrored to R2 so the deployed card resolves.
**`videos` row 11 is the first row in this project's history carrying a `concept_id`**, and it
carries a real metrics snapshot: reach 19, likes 4, comments 1, average watch 4.59s against a
10.042s clip (46%). The other 12 Instagram reels on the account were backfilled the same day with
their own snapshots, so `posted_outcomes` has 13 rows to join instead of none.
**THE FIRST API-BILLED RENDERS AND THE LEDGER HOLD WERE VERIFIED ON 2026-09-26**, on fal
(the only video renderer since that day; `FAL_KEY` and `QUOTE_SIGNING_SECRET` are Fly secrets,
`FAL_SPEND_OK` deliberately unset). Run through the deployed Queue on account 1 with
`credit_exempt` switched OFF for the test and back ON after, so the hold was real:
concept #194 on LTX 2.3 (6s 1080p, $0.36) held 87 credits and settled against generation 124;
#121 on Kling 3 turbo (101) and #135 on Seedance 2 fast (233) settled against 125/126. Every
row is `key_source = env` with `cost_usd` populated; #194's clip is on R2 and on the Assets wall
(`generated_assets` 82). **Both
halves of the hold are exercised:** the first LTX attempt 422'd at fal (LTX wants an INT
duration on the wire, fixed in #69) and its hold was RELEASED automatically four seconds later
(ledger entries 4/5). Account 1's lot went 500 -> 79 with no hold outstanding.
The same day found that a deploy restarting the machine mid-poll orphaned the render (the job
thread died with the hold `submitted` and no stored request id); holds 8/9 died that way and were
released by hand. PR #73 fixed it: `src/fal_requests.py` persists the request id so a restart
reattaches instead of orphaning the hold.

**The number that matters now: 11 picks against 255 written, and 1 of 255 rendered.** Generation
is cheap and abundant, selection is still the bottleneck, and the spend gate has barely been used.
Read every rate below in that light. The backfilled reels carry `duration_s` NULL because the IG
Graph API returns no `media_url` for REELS on this token, so their `watch_time_seconds` cannot be
turned into a completion rate — only clips this pipeline renders get a measured duration
(ffprobe at import). Cross-video watch comparison is not valid until that is solved.

Post-production (ingest/pitch/editgen, `/pitches`, the assistant's `cut` intent) was removed in
Aug 2026 — the DB keeps historical pitch-run rows, but nothing generates new ones.

**Structurally complete, statistically thin:** the L2->L3 loop is built, verified live, and now
has exactly one measured concept in it. `promote_winners propose` still honestly reports nothing
clears the bar — it compares at equal age and there is one linked video — and `src.rework` still
generates an evidence-free slate with the note. `pick_rate`, `shoot_rate` and `post_seo`'s
signals are structurally correct and now non-empty rather than meaningless; they need weeks of
real posting before a prompt change can be measured. (`db.selection_rate` is a different,
surviving thing: it measures kept-vs-attempted on generative CLIPS, not concepts — the first
`kept=1` row in the table was written 2026-09-18.) **The most valuable next step is repetition,
not code** — the path exists now, so the question is whether it can be walked weekly. L4 exists
as `src.autopilot` — gated, dry-run, default off, executors unwired.

**Known gaps, in rough priority:**
- **Timed scenes (2026-09-10): the Queue and the graph render shot by shot; the Director
  does not know them yet.** `generate_render` walks a CURRENT `shot["timeline"]` through the
  same `generate_for_shot(part=n)` door the Queue uses (2026-09-22, `_render_timed`: one clip
  entry per scene, `parts` on it, stop at the first failure, no failover, still dry unless
  `ZEROPAGE_RENDER=1`). The Director canvas still seeds and edits the WHOLE scene prompt and
  runs its keyframe/clip nodes on the whole scene; BACKLOG #20 has the design question that
  has to be answered before it can edit one shot of a timed scene.
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

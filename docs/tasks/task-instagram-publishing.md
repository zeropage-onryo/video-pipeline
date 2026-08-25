# Task — Instagram publishing, scheduling, and metrics (alongside YouTube)

Add Instagram to the pipeline the way `youtube.py` is already in it: a `platform == "instagram"`
citizen for **metrics readback**, plus the missing outbound half — **scheduled publishing** — wired
into the gate `autopilot.py` already defines. Build it test-first, degrade-don't-break, and ship it
**caged**: the live posting path stays behind `autopilot`'s existing three-condition gate and is OFF
by default.

Read `src/youtube.py`, `src/autopilot.py`, `src/post_seo.py`, `src/db.py`, and `CLAUDE.md` before
writing code. **Start in plan mode; show the plan before editing.**

## Why this fits what already exists

- `autopilot.EXECUTORS["post"]` is currently `_unwired("post")` — this task provides the **real post
  adapter** that registers there. The gate (`ZEROPAGE_AUTOPILOT` + per-run `--approve` + no
  `data/autopilot.off` kill switch, dry-run otherwise) is untouched.
- `autopilot.build_plan` already says "Posting actions enter the plan only once generated media
  exists to post" but only emits `generate` actions today. This task adds the `post` actions.
- `youtube.py` is the template for the inbound half: thin raising API wrappers + never-raises
  orchestrators returning result dicts, `_safe_error` redacting secrets, writes via
  `db.record_metrics` / `db.add_video`.
- `post_seo.derive_signals` / `score_post` already turn the channel's own numbers into a caption/
  title scorer — the autonomous caption step optimizes against it, no new analytics needed.

## Contracts to preserve (do not break)

1. **Never raises at the edges.** Every public `instagram.py` orchestrator returns
   `{"ok": bool, ...}` exactly like `refresh_metrics_for_video` — a missing token or failed call is a
   result, never an exception that takes a page or the scheduler down. The thin API wrappers may
   raise; their callers catch. Redact the access token from any error text (`_safe_error` pattern).
2. **The gate is sacred.** The live publish call runs **only** through `autopilot.execute` in `live`
   mode. Do not add a second path that publishes outside the gate. Registering the executor must not
   change `enabled()`/`killed()`/approve logic.
3. **Hermetic tests.** Patch `instagram.requests` (or the API-wrapper functions) and any db access;
   `tests/conftest.py` blocks the network. Patch what the code under test actually calls — see the
   `NetworkUseInTest` note in `CLAUDE.md`.
4. **Filenames/proxies/manifest conventions** are unaffected — this is delivery, not editing.

## 1. `src/instagram.py` — the module (mirror `youtube.py`)

Two-step publish is create-container → poll status → publish. Video is processed async; never
publish before `FINISHED`. `video_url`/`image_url` must be a **public** URL Meta can fetch.

Thin API wrappers (raise on failure):
- `create_reel_container(ig_user_id, video_url, caption, token)` → `POST {IG}/{id}/media`
  (`media_type=REELS`), returns container id
- `create_image_container(...)` → `media_type=IMAGE` (JPEG only)
- `container_status(container_id, token)` → `GET {id}?fields=status_code`
  (`IN_PROGRESS`/`FINISHED`/`ERROR`/`EXPIRED`)
- `publish_container(ig_user_id, container_id, token)` → `POST {IG}/{id}/media_publish`
- `publishing_limit(ig_user_id, token)` → `GET {id}/content_publishing_limit` (quota check)
- `fetch_media_insights(media_id, token)` → `GET {id}/insights?metric=...` (metric names shift by
  version — centralize them in one constant and date the comment)

Base host `https://graph.instagram.com/<VERSION>`; put `VERSION` in one constant.

Never-raises orchestrators (the edges):
- `post_reel(ig_user_id, video_url, caption, token, poll_tries=5, poll_delay=60)` → runs
  create→poll→publish, returns `{"ok", "media_id", "step", "error"}`. This is the function the
  autopilot post adapter calls.
- `refresh_metrics_for_video(video, token=None, db_path=None)` — **the alongside-YouTube half.**
  Same signature shape as `youtube.refresh_metrics_for_video`: guards `platform != "instagram"`,
  guards missing token, pulls the media id from the stored url (or a stored `media_id`), calls
  `fetch_media_insights`, maps insights → `{views, likes, comments}` (+ saves/shares if the schema
  grows), writes via `db.record_metrics(video["id"], ...)`, returns the result dict.

Env: read `IG_USER_ID` and `IG_ACCESS_TOKEN` (accept both, don't hardcode). Add both to
`.env.example` with a comment, next to `GEMINI_API_KEY`, and document `ZEROPAGE_AUTOPILOT`.

## 2. Wire metrics dispatch alongside YouTube

Wherever the app/CLI refreshes a video's numbers by platform (the YouTube refresh route/entry),
add the `instagram` branch so a stored Instagram post refreshes the same way a YouTube one does —
one dispatch on `video["platform"]`, both writing snapshots through `db.record_metrics`. Manual
entry must keep working if the token is absent (same guarantee YouTube has).

## 3. `src/scheduling.py` — the piece the API doesn't give you

Instagram has **no native future-scheduling**, so own the clock. New module that extends `db.py` in
its own module (own `SCHEMA`, own `init()`), the `preprod.py` / `generative.py` pattern:

- Table `scheduled_posts`: `id`, `video_ref` (media url / concept link), `caption`, `platform`,
  `publish_at` (UTC), `status` (`planned`/`publishing`/`posted`/`failed`), `media_id`, `error`,
  `created_at`.
- `due_posts(now, db_path=None)` — planned rows with `publish_at <= now`. Pure query.
- `run_due(now, approve=False, live=False, db_path=None)` — the worker step. For each due row:
  mark `publishing` **before** dispatch (idempotency — a crash mustn't double-post), build a `post`
  action, run it through **`autopilot.execute`** (so the gate + dry-run + kill switch all apply),
  mark `posted` with the returned `media_id` or `failed` with a redacted error. Respect the
  `content_publishing_limit` quota and a configurable per-day cap well under 100/24h.
- CLI `python -m src.scheduling run [--approve] [--live]` — what cron invokes. Dry-run by default,
  identical flag semantics to `autopilot`. `python -m src.scheduling list` shows the queue.

Scheduling itself (inserting/moving rows, listing the queue) is **not** gated — only the publish is,
because it goes through `autopilot.execute`.

## 4. Register the post adapter in `autopilot.py`

Replace `EXECUTORS["post"] = _unwired("post")` with an adapter that calls
`instagram.post_reel(...)` (and image/carousel as needed), reading token/id from env. Extend
`build_plan` to emit a `post` action for a concept once generated media exists to post (a shot with
a rendered file/url). Keep `generate` behavior as-is. The adapter must raise inside `live` mode only
(the executor is called only when `mode == "live"`), so dry-run still previews without touching the
API.

## 5. Autonomous caption (optional, uses existing signal)

When a `post` action needs a caption and none is supplied, generate one with the LLM **grounded in
`post_seo.derive_signals`** (winning topics/hooks/title words) and score candidates with
`post_seo.score_post`, picking the best. Pure scoring is free, so score many, bill once. Falls back
to a plain caption if there's no signal yet (`MIN_SAMPLE` guard already handles the honest-null case).

## 6. Tests (all hermetic, network blocked)

- `instagram.py`: container creation payload shape; status polling stops on `FINISHED`/`ERROR`;
  `post_reel` returns `ok:false` at each failure step; `refresh_metrics_for_video` guards non-IG /
  missing token and writes a snapshot on success (db + requests patched); `_safe_error` redacts the
  token.
- `scheduling.py`: `due_posts` windowing; `run_due` marks `publishing` before dispatch and
  `posted`/`failed` after; **a dry-run run publishes nothing** (assert the API wrapper is never
  called); per-day cap respected.
- `autopilot.py`: with the adapter registered, `disabled`/`unapproved`/`dry-run` modes still execute
  0 and never call `instagram`; `live` mode calls the adapter. Preserve existing autopilot tests.

## 7. Verify by running it

```bash
venv/bin/python -m pytest tests/ -q      # green, incl. new files
venv/bin/ruff check .                    # clean

# safe previews (no token, nothing billed, nothing posted):
venv/bin/python -m src.scheduling list
venv/bin/python -m src.scheduling run            # dry-run: prints would-publish, posts nothing
venv/bin/python -m src.autopilot plan            # post actions now appear when media exists
```

Live posting is a **separate, deliberate, later** step the user takes by hand: set `IG_USER_ID` /
`IG_ACCESS_TOKEN`, pass Meta **App Review**, then `ZEROPAGE_AUTOPILOT=1 ... run --approve --live`
against his own account first. Do not enable any of that in this task.

## Out of scope

Calling generation APIs (the `generate` executor stays unwired), image-to-video, App Review
automation, TikTok (a later adapter behind the same `post` seam), and native scheduling (there is
none — that's why `scheduling.py` exists). Token-refresh job can be a follow-up task; note it, don't
build it here.

Done when: tests pass, ruff clean, `scheduling run` and `autopilot plan` show the post path in
dry-run touching nothing, and metrics refresh handles `platform == "instagram"` beside YouTube.

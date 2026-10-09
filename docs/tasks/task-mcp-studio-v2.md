# Task: the studio MCP, v2 — credits, cancel, structured results, editing, viewer + upload

Approved by Mike 2026-10-08: **all items, in this order.** Organizing work (folders/stars) stays on
the backlog. Source of the plan: the Claude Doc "Zeropage MCP — task list review"
(https://claude.ai/code/artifact/d761f7ad-857e-4784-b2ed-79a9fb67d713).

Scope is the **studio surface** of `src/mcp_server.py` (`build_server(surface="studio")`, what
`python -m src.mcp_server` serves to Claude Desktop). Board/listed surfaces are untouched unless a
step says so. Mike's standing rules for this MCP: nothing it does adds to the idea board; every
spend is quoted first and runs only after his yes in chat.

## Ground rules for the session doing this

- Branch off `main` (HEAD is often detached in this checkout — other sessions merge here). One PR
  per numbered step; **stop after each step and report** before starting the next.
- Read `CLAUDE.md` first (spend gate, ledger, reference-by-id rule, "verify by running it").
- `tests/conftest.py` blocks network: patch the function the code really calls.
- Run `venv/bin/python -m pytest tests/ -q` and `venv/bin/ruff check .` before each PR.
- No live spend: never call fal/Gemini for real while building. A live check is Mike's call.
- Keep tool titles/descriptions in `TITLES` / `DESCRIPTIONS` / `HINTS` (the test pins them) and out
  of `INTERNAL_WORDS`.

## Progress

| step | state | PR / notes |
|---|---|---|
| 1. credits + signed single-use quote | built 2026-10-08, PR #200 | see "As built" under step 1 |
| 6. cancel a job | built 2026-10-09, PR #201 (stacked on #200) | see "As built" under step 6 |
| 7. structured results | built 2026-10-09, PR #202 (stacked on #201) | see "As built" under step 7 |
| 2a. join clips | built 2026-10-09, PR #204 (stacked on #202) | see "As built" under step 2a |
| 3 + 4. viewer + upload | `import_file` built 2026-10-09, branch `claude/task-mcp-studio-v2-import` (stacked on #204); MCP Apps NOT built -- gate not passed, see below | see "Verification" and "As built" under step 3 + 4 |
| 2b. finish a clip | not started | |
| 2c. edit by instruction | not started | |

## 1. Approve in studio credits, with a signed single-use quote

Today `approval_gate(usd, approve_usd)` compares dollars Claude repeats back.

- Quote shows **credits**, the account's **balance** (`ledger.available`) and the balance after.
  Credits come from `pricing.credits_for` over the provider micros — the same math the Queue card
  shows. USD stays in the payload as detail.
- Replace `approve_usd` with `quote_token`. `pricing.sign/verify` are shot-bound today (`shot_id`,
  `part`, `content_hash` of a shot); add a sibling for free-standing MCP renders whose body binds
  `tool` + a hash of the exact normalized arguments (model, aspect/seconds/frame, prompt, resolved
  reference ids, effect + options, element). Same secret (`QUOTE_SIGNING_SECRET`), same TTL,
  same refusal codes where they apply. Any argument changed after the yes -> refused.
- **Single use / idempotent:** record the token's id when it is redeemed (a small OWNED table or a
  column on the job); a second call with the same token returns the first job, never a second
  charge.
- Insufficient credits -> a structured refusal (`needs`, `available`), not an exception string, so
  Claude stops instead of retrying.
- Applies to `generate_image`, `generate_video`, `apply_effect`, `element_sheet`.
- No signing secret configured -> the tools refuse to spend (say why); quoting still works.

**As built (2026-10-08).**
- `approve_usd` is gone; every spending tool takes `quote_token`. `mcp_server.approval_gate`
  returns `(stop, approved, price)`: `price` = `usd` (detail), `credits`
  (`ledger.charge_credits`, the one conversion every hold uses), `charged` (false for an exempt
  account or the unowned pool), `balance` (`ledger.available`, after `billing.release_due`, as
  `Charge.take` does) and `balance_after`. Quote calls also carry `quote_token` + `expires_at`.
- `pricing.studio_quote` / `sign_studio` / `verify_studio` + `StudioQuote`: same secret, TTL,
  prefix and refusal codes as the shot token; the body has `"k": "studio"`, `tool`, `prov`,
  `ahash` (sha256 of canonical `{tool, args}`) and a `jti`. `verify()` now refuses any token
  with `k` as `wrong_render`; `verify_studio()` refuses a shot token the same way. What each
  tool binds: image `prompt, model, aspect, references, project_id`; video `prompt, model,
  seconds, frame, reference, project_id` (after `check_render_choice` resolved them); effect
  `effect, options (checked), sources, prompt (checked), project_id`; element sheet `kind,
  element, photos (basenames), replaces_sheet`. Defaults are resolved before hashing, so
  omitting `model` and naming the default are the same request. A re-priced token whose
  credits no longer match is refused `stale_content` too.
- The verified `StudioQuote` is handed to the adapter (`quote=` on
  `fal.generate_image_from_prompt`, `fal.generate_from_prompt`, `effects.run`,
  `element_sheet.draw` -> `nano_banana.generate_from_prompt`); `src/charge.py` holds its
  credits and checks its provider (`fal`, or `nano` for a sheet).
- Single use: `quote_redemptions` (OWNED, `src/quote_redemptions.py`). `start_approved` runs
  the tool with `dry_run=True` (every check, the balance included), CLAIMS the token
  (`INSERT ... ON CONFLICT DO NOTHING`), starts the job, records the response. A repeat gets
  the first response with `already_used: true`. A refusal before the claim leaves the token
  unspent (top up, same yes still works within the hour); a job that could not even start
  gives the claim back. A job that started and then failed (fal refused, no key) has used
  its token: re-quote.
- Insufficient credits is a returned dict, `{ok: false, refused: "insufficient_credits",
  needs, available, note}`, at the quote (no token issued) and at the approval.
- Verified: tests/test_mcp_studio_quotes.py (token rules; single use; the four eval
  conversations through the real server and the real ledger with only fal's HTTP call stood
  in: approve-then-retry charges once, a changed model is refused, an expired quote is
  refused, a short balance stops with the numbers) and the full suite (3373 passed). Run for
  real over stdio against a throwaway schema with no keys: quote -> bad token refused ->
  changed model refused -> approved (job 1) -> same token again returned job 1, nothing
  new started; the job ended "FAL_KEY not set", so nothing was spent.
- **The Mac's `.env` has no `QUOTE_SIGNING_SECRET`** (checked 2026-10-08), so Claude Desktop's
  studio surface quotes but cannot approve until one is set there (Fly has its own).

## 6. Cancel a job

- New tool `cancel_job(job_id)` over `app/jobs.cancel` (already exists, account-scoped).
- Release the credit hold when the provider was not yet submitted; if fal already has it, try fal's
  cancel URL (the receipt in `fal_requests` has it) and release only on fal's confirmation.
  Document honestly which states can and can't be refunded.

**fal's contract, read 2026-10-08** (fal.ai/docs/model-apis/model-endpoints/queue, /model-apis/
pricing, /model-apis/request-errors): `PUT {cancel_url}` -> 202 `CANCELLATION_REQUESTED` (a job
still IN_QUEUE "is removed immediately and is never processed"; an IN_PROGRESS one is sent a
signal and "may still complete if the app does not handle cancellation"), 400
`ALREADY_COMPLETED`, 404 `NOT_FOUND`. There is no CANCELLED status; a cancelled request's error
type is `client_cancelled` (HTTP 499). fal bills "only successful outputs" and never queue time.
Not documented anywhere: what the status endpoint answers after a cancel, so the code accepts
any of an error payload, a 404/410/499, or a finished job with no output as "cancelled".

**As built (2026-10-09).**
- `cancel_job(job_id)` on the studio surface (and the board under the engine flag; never
  listed). `mcp_server.cancel_studio_job` answers honestly: unknown id -> error; finished ->
  "nothing to cancel" plus what it cost; a job this connector did not start (not cancellable) ->
  says so; still queued -> cancelled outright, nothing held; running -> "cancel requested" with
  the outcomes below, and `job` says how it ended (`cancelled` with the adapter's own words in
  `detail`, or `done`).
- The spending tools' jobs are started cancellable (`_run(..., _cancellable=True)`), and the
  runner binds `src/cancellation.py`'s check in the worker thread, like the credit meter.
- **Before the provider call:** `charge.Charge.submitted()` -- the last line before every
  provider call in every adapter -- sees the cancel, releases the hold and raises `Cancelled`
  (no provider call, no failed generations row). Refunded.
- **While fal has it** (images, clips, effects all poll in `fal._submit_and_wait`): the cancel
  URL from fal's own submit reply is PUT through the same `http` seam (`fal.CANCEL`), on the
  job's own thread -- not from the `fal_requests` receipt, which only clips write. fal's answer
  decides: 202 then an error payload / 404 / 410 / 499 / a finish with no output -> `Cancelled`,
  hold released, and for a clip the receipt resolved and a failed attempt row written. 202
  then an output -> kept, settled at the quoted price, filed, `cancel_too_late: true` on the
  result. 400 -> the same (too late). 404 -> released. No answer (network, 5xx) -> nothing
  assumed, asked again on the next poll.
- **Cannot be refunded:** a job fal finishes before the cancel takes effect (charged, kept); a
  job already downloading / being recorded; an element sheet already being drawn (one
  synchronous Gemini call, nothing to signal); a job lost to a server restart (it is gone from
  the in-memory registry -- the recovery sweep finishes a clip). The live path's existing
  deadline rule is unchanged: a job still pending at fal's deadline is released.
- Fixed on the way: `jobs.cancel` on a still-`queued` job set its status, but the worker then
  overwrote it to `running` and ran the job anyway. The flag is set too now, and the worker
  checks it before starting.
- Verified: tests/test_mcp_cancel.py -- the pre-submit release on the real ledger; every fal
  answer above against a scripted queue; the PUT's method and empty body through the real
  `_request`; the registry (queued never runs, `Cancelled` -> `cancelled`, a non-cancellable
  job never sees a cancel); the tool's replies; and the task's eval, "cancel mid-job", end to
  end on real job threads, the real ledger and the real image door with only fal's wire stood
  in -- refunded when fal drops it, kept and charged when fal finishes first -- plus the clip
  door (receipt resolved, failed row, nothing left for the sweep).

## 7. Structured results

- Every studio tool returns typed data (MCP `outputSchema` + `structuredContent`): ids, credits,
  balance, `media_url`, `asset_id`, job state. Text content stays as a short human line.
- Same shapes feed the viewer in step 3+4, so define them once.

**As built (2026-10-09).**
- `src/mcp_shapes.py` is the one place: a pydantic model per studio tool (`SHAPES`), a
  one-line summary per tool (`SUMMARIES`), `enrich` (additive only: a spend's `state`; a job's
  `media_url` / `asset_id` / `ref` / `media_kind` lifted off its result) and `result`, which
  builds the `CallToolResult`. The models are OPEN (`extra="allow"`): they type what a caller
  and the viewer rely on -- `SpendResult` (`state`, `quote` with `credits` / `balance` /
  `balance_after` / `quote_token`, `job_id`, `refused` / `needs` / `available`, `media_url`,
  `asset_id`, `ref`), `Job` (status as a literal, credits, the lifted media), `CancelResult`,
  the project / render / element / candidate lists, the catalogues -- and let the rest through.
  The step 3+4 viewer reads these same models.
- Only the STUDIO surface is wrapped: `_reg` registers each studio tool through
  `mcp_server._structured`, which keeps the tool's own argument signature and declares
  `Annotated[CallToolResult, SHAPES[tool]]`, so the SDK (mcp 2.1.1) publishes the
  `outputSchema` and validates every answer. The board and the listed (directory) server are
  unchanged: plain dicts, no schema.
- **Text: the line first, then the JSON (a deliberate deviation from "text stays a short human
  line").** What a client puts in front of its model is the client's choice; checked
  2026-10-09, Claude Code reportedly reads `structuredContent` and drops text, claude.ai
  forwards both, and nothing first-party covers Claude Desktop. If Desktop read only the text,
  a line alone would hide the `quote_token` and the ids and break step 1. So
  `mcp_shapes.MIRROR_JSON = True` keeps the payload as a second text block (the MCP spec's own
  backwards-compatibility advice). To settle it: a live marker check in Claude Desktop (a value
  only in structuredContent, one only in text, ask Claude to repeat both); if it reads
  structuredContent, set the switch to False and the text is the line alone.
- Verified: tests/test_mcp_structured.py (every studio tool has a shape and a line; schemas
  published on the studio only; real calls for projects, the catalogues, renders, elements,
  prompt_craft, a quote, a job and cancel_job validate and read as one line; every spend state;
  a drifted payload raises) and the existing MCP tests read `structuredContent`. Run over the
  real stdio transport: 18 tools all with an outputSchema; create_project, projects, a quote,
  an approval, its job and cancel_job each came back as structuredContent plus the line.

## 2a. Join clips into one video

- New tool `assemble_clips(clips: [gen:<id>...], transition="cut"|"crossfade", crossfade_s, music)`.
- Build on `src/cut/`: a **scratch** cut project (`cut/projects.py`, key `cut:<uuid>`) with the
  clips inserted through `cut/ops.py`, validated by `cut/validate.py`, rendered by
  `cut/render.py`. Do NOT route through `assemble.assemble` (that is concept-bound).
- Output filed on the Assets wall like any render. Rendering is local ffmpeg -> no credit cost;
  say so in the result rather than quoting zero.
- Refuse non-video ids, deleted assets, mixed aspect ratios (or letterbox — decide and state it).

**As built (2026-10-09).**
- `assemble_clips(clips, transition="cut"|"crossfade", crossfade_s=0.5, music="", letterbox=false,
  title="", project_id=None)` on the studio surface (and the board under the engine flag; never
  listed). 19 studio tools now.
- `src/cut/join.py`: `plan` makes every check before anything is written -- 2-20 clips, each a
  `gen:<id>` video of this account's, not soft-deleted, readable, a moving picture (not a still);
  `crossfade_s` 0.1-2s and at most half the shortest clip (a middle clip is overlapped from both
  sides); `music` an `asset:<id>` audio upload of this account's. `join` saves the cut as v1 of
  a scratch project (`cut:<uuid>`, so it opens in the editor), renders it, records the export
  on the version, draws the wall poster, and files the MP4 on the Assets wall.
- **Aspect ratio, decided: refused by default.** Clips of different shapes (to 1%, so 720x1280
  and 1080x1920 are one) are refused with each clip's shape named. `letterbox=true` allows it:
  the canvas is the FIRST clip's frame and the others are fitted inside with black bars (the
  renderer's existing pad path), listed in `plan.letterboxed`. Refusing by default because
  "join these" rarely means "put bars on half of them".
- The cut is built by `assemble.build_doc` -- the pure builder Assemble uses (clips with their
  own sound linked on A1, a marker per clip, a music bed on A2 trimmed to the picture and
  ducked under the clips' sound) -- which gained `transition_frames`: a crossfade INTO every
  later clip, added as each clip lands so the markers and the music see the shortened cut.
  Assemble still passes 0 (a concept's windows were written as cuts). `assemble.assemble`
  (concept-bound) is not used.
- **No credits, said so:** no quote and no approval; the result carries `credits: 0` and a
  note that it ran on the studio's server. The generations row behind the wall entry is logged
  under a new free tool `cut` (`generative.CUT_TOOLS`), `cost_usd` NULL -- the manual lane's
  spelling of free -- and the wall labels it "Joined clips".
- Music discovery: `renders(kind="audio")` lists the editor's audio uploads as `asset:<id>`
  (they live in `cut_media`, not on the wall). Uploading from chat is step 3+4.
- Verified: tests/test_mcp_join.py -- every refusal; the built cut (order, linked sound,
  crossfades on every cut, markers where clips begin, duration = sum - (n-1) x fade, music
  trimmed and ducked); and with real ffmpeg, three clips + a music bed through the studio
  server -> one MP4 of the right length and frame on the wall, a scratch cut with its export,
  NOTHING in the ledger and `cost_usd` NULL; the joined clip is a `gen:<id>` the next join can
  name. Run over the real stdio server: mixed shapes refused with both shapes named; three 2s
  clips with 0.5s crossfades came back as one 5.0s 360x640 MP4 with sound, `gen:5` on the wall.

## 3 + 4. Inline viewer and upload from chat (MCP Apps)

- **First, verify** MCP Apps (UI resources rendered inline) work in the client Mike uses (Claude
  Desktop and/or claude.ai) with this SDK version (`mcp>=2`). If not supported, stop and report;
  do the `import_file` fallback only.
- Viewer: render tools attach a UI resource that polls the job and shows progress -> the image or
  video, with Approve / Join / Use-as-reference actions calling back into the tools.
- Upload: a drop-zone UI that posts the file to studio storage (R2 via `media.mirror`, bin via
  `refbin.save` for images) and returns an id usable as a reference/effect source (`gen:` for a
  file filed on the wall, or a new `upload:<id>` kind added to `resolve_references` — pick one,
  keep ids-never-URLs).
- Fallback tool `import_file(path)`: reads a file on this Mac (stdio server runs locally) under an
  allow-listed set of folders (e.g. ~/Downloads, ~/Desktop, the repo's data/), refuses anything
  else, size-capped, images and mp4/mov only.

**Verification of MCP Apps (2026-10-09) -- the gate did NOT pass, so only the fallback is built.**
- The SDK is ready: mcp 2.1.1 ships `mcp.server.apps` (`Apps` extension: declares
  `io.modelcontextprotocol/ui` at initialize, `@apps.tool(resource_uri="ui://...")` stamps
  `_meta.ui.resourceUri`, `add_html_resource` serves `text/html;profile=mcp-app` with CSP).
- The hosts say yes on paper: modelcontextprotocol.io's MCP Apps page and the 2026-01-26 launch
  post list Claude (web and desktop).
- In practice it is unreliable: anthropics/claude-ai-mcp#165 ("MCP Apps UI never renders in
  Claude Desktop", open, 16 comments, last 2026-09-18) and modelcontextprotocol/ext-apps#671
  (Desktop and claude.ai, open, 24 comments, last 2026-10-06). The capability is negotiated and
  the resource is read, and no iframe mounts. One report is a LOCAL STDIO extension in Claude
  Desktop 1.26832.0 (2026-08-07) -- our exact setup. Others got remote connectors rendering only
  after a list of undocumented server-side fixes (declare the extension at initialize, `_meta.ui`
  on the tool RESULT too, CSP on the read item, bundle the app SDK rather than load it from a
  CDN, send `ui/notifications/initialized` unconditionally, content-hash the `ui://` URI and
  keep the old one as an alias; one release broke on `serverInfo.websiteUrl`).
- Not tested in Mike's Claude Desktop: Desktop launches the stdio server from the MAIN checkout
  and only re-reads its config on restart, and this work runs inside Desktop's Code tab, so a
  restart from here would end the session. A probe is cheap to build; running it is Mike's.
- So, per this task's rule, the viewer and the drop zone wait. To resume: build a one-tool probe
  with `mcp.server.apps` following the checklist above, register it, restart Desktop, call it;
  if a panel renders, build the viewer on `mcp_shapes` (the job and spend shapes are already
  what it reads).

**As built: `import_file` (2026-10-09).**
- `import_file(path)` on the STUDIO surface only (stdio, the person's own computer); never on
  the board (served over HTTP) or the listed server, and refused for a signed-in caller. 20
  studio tools now.
- The fence: `mcp_server.import_roots()` -- `ZEROPAGE_IMPORT_DIRS` (os.pathsep-separated), else
  ~/Downloads, ~/Desktop and the checkout's data/ -- compared with the path's REAL location
  (`resolve(strict=True)`), so `../` and a symlink out of an allowed folder are both refused; a
  full path is required. Images (jpg, jpeg, png, webp) and .mp4 / .mov only; the editor's caps
  (100MB an image, 500MB a clip), checked before the file is read.
- One body files it: `src/cut/uploads.save`, lifted out of `app/cut_routes.py`'s upload route
  (which now calls it, same codes and messages): typed, capped, PROBED (and refused if it is
  not what its extension says), content-addressed under the editor's media folder, mirrored to
  the bucket under the account, recorded in `cut_media`, probe cached.
- **The id is `asset:<id>`** -- the editor's existing upload handle rather than a new
  `upload:<id>` kind: owned per account, already what music takes, already in the editor's bin.
  It is accepted by `resolve_references` (an image: generate_image references, generate_video's
  start frame, an image effect), by clip effect sources (`mcp_server._clip_row`) and by
  `assemble_clips` (a clip). `renders(kind="upload")` lists everything brought in.
- Fixed on the way: (1) the upload body now refuses a "still" or a "clip" with no width/height --
  ffprobe reads a text file named .jpg as a 0x0 mjpeg still, and the editor's route used to file
  it; (2) the stdio entry point now creates the editor's tables and the generations log, without
  which `import_file` and `assemble_clips` crashed on a fresh database (step 2a's stdio check had
  created them itself).
- Verified: tests/test_mcp_import.py (the fence: relative, outside, `../`, symlink out, wrong
  type, over the cap, a fake image, a signed-in caller; the studio-only registration; an image
  as a reference, another account's import refused, a clip as an effect source and in a join;
  the typed answer; the shared body's new refusal). Over the real stdio server against a fresh
  database: the three escapes refused; a photo, a .mov and an .mp4 imported as asset:1-3 and
  listed; the two clips joined into one 3.5s video on the wall. The photo as a reference was
  refused "not in the studio's bucket" there because that worktree has no R2 -- the right
  refusal; with R2 configured (Mike's .env) it is uploaded.
- Not taken, on purpose: audio (music still comes in through the editor's bin; adding .m4a/.mp3
  to `_import_types` is one line if wanted), HEIC, webm.

## 2b. Finish a clip — extend `src/effects.py`

- Add re-frame to a new aspect ratio (video outpaint) and video background removal **only** for fal
  endpoints with a published fixed price. Verify each against its OpenAPI schema and model page;
  date the row (`checked`) like the existing rows. Compute-second-billed endpoints stay out.

## 2c. Edit a clip by instruction — research first

- Research which fal endpoints do instruction-based video-to-video editing, their limits (length,
  resolution, fps) and pricing. Write findings to this file before building.
- Build as `edit_clip(source gen:<id>, instruction, ...)` with a two-stage flow: edit ONE frame as
  a cheap still and show it (quote 1), then the full video edit (quote 2) after Mike approves the
  frame.

## 8. Alongside every step

- Keep the studio surface at ~20 tools; prefer an `operation` argument over new tools.
- Add eval conversations as tests where possible: approve then retry (no double charge), change a
  model after approval (refused), quote expires, insufficient credits, join three clips, cancel
  mid-job.

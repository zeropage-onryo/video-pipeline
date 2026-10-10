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
| 1. credits + signed single-use quote | built 2026-10-08, branch `claude/task-mcp-studio-v2-docs-d82294` | see "As built" under step 1 |
| 6. cancel a job | not started | |
| 7. structured results | not started | |
| 2a. join clips | not started | |
| 3 + 4. viewer + upload | not started | |
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

## 7. Structured results

- Every studio tool returns typed data (MCP `outputSchema` + `structuredContent`): ids, credits,
  balance, `media_url`, `asset_id`, job state. Text content stays as a short human line.
- Same shapes feed the viewer in step 3+4, so define them once.

## 2a. Join clips into one video

- New tool `assemble_clips(clips: [gen:<id>...], transition="cut"|"crossfade", crossfade_s, music)`.
- Build on `src/cut/`: a **scratch** cut project (`cut/projects.py`, key `cut:<uuid>`) with the
  clips inserted through `cut/ops.py`, validated by `cut/validate.py`, rendered by
  `cut/render.py`. Do NOT route through `assemble.assemble` (that is concept-bound).
- Output filed on the Assets wall like any render. Rendering is local ffmpeg -> no credit cost;
  say so in the result rather than quoting zero.
- Refuse non-video ids, deleted assets, mixed aspect ratios (or letterbox — decide and state it).

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

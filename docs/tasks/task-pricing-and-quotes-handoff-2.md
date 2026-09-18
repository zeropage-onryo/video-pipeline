# Pricing & quotes — handoff for steps 5–6 (written 2026-09-18)

Paste this into a new chat. It assumes the repo at `zeropage-onryo/video-pipeline`, main at or after `7ddb947`.

## Where it stands

- **Steps 1–4 of 6 are on `main`** (PR #21, merge commit `7ddb947`, 2026-09-18). CI green, Fly Deploy of the API succeeded. The branch and worktree are deleted.
- **The spec is in the repo now**: `docs/tasks/task-pricing-and-quotes.md`. Read its last section, **"As built — steps 1–4, and where this spec was wrong about the code"**, before anything else — nine places the spec's assumptions did not match the code, and the deviations that were chosen. Do not re-derive them.
- The original handoff (`~/Downloads/task-pricing-and-quotes-handoff.md`) still holds the operating rules; the ones that keep applying are repeated below.
- Suite last run on the merged tree: **2171 passed, 8 xfailed, 0 failed**, `ruff check src app tests ops` clean, `web/` eslint clean, `tsc` clean except a pre-existing `LayoutProps` error in `web/src/app/layout.tsx` (not ours).

What exists, in one paragraph: `src/pricing.py` is the pure module — `estimate()` (provider USD, always answers), `quote()` (credits, `None` on BYOK), `display()` (the JSON every card reads; mints a signed token per render when `QUOTE_SIGNING_SECRET` is set), `sign()`/`verify()` (HMAC, `zpfq.<body>.<mac>`, 1-hour TTL, refusals in order `bad_signature / retired_pricing / expired / wrong_account / wrong_render / stale_content`), `content_hash()` = `timeline.source_hash(prompt, refs)` computed live. `MARKUP = "1.0"` (a string, read through `Fraction`), `CREDIT_FLOOR = 10`. `app/api.py`: `GET /api/queue/pending` carries `quote` per card, `GET /api/queue/{id}/quote?provider&model&duration&frame` re-prices a pick, `POST /api/queue/{id}/approve` takes `tokens: Optional[list[str]]` and verifies them through `_verify_tokens` (`app/api.py:2441`) **only when the body sends them** (`if body.tokens:` at `app/api.py:2627`). `/api/workflows/exec/generate` takes one `token`. `/api/capabilities` reports `quote.sign`. Both front ends (vanilla `app/static/zpf/queue.js`, React `web/src/app/studio/queue/page.tsx`) fetch `/quote` on a pick change and echo the tokens on approve. The four adapters are untouched: they still receive `approved=True`; `spend_approved(quote=...)` does not exist yet.

## Do these in order

### 0. Set the signing secret on Fly — DONE 2026-09-18

Set, deployed, and `pricing.configured()` reads `True` on the machine. The command is kept for rotation only (rotating invalidates every outstanding quote; cards re-quote on next load):

```bash
fly secrets set -a zeropage-studio QUOTE_SIGNING_SECRET="$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
```

A different value from any dev machine's `.env` — a dev-minted quote must not verify in production. Until it is set, the deployed API shows prices, mints no tokens, and approves exactly as before (safe posture). After it is set, cards show `signed: true` and approve carries tokens.

### 1. One real API-billed render through the Queue — ATTEMPTED 2026-09-18, BLOCKED ON PROVIDER ACCOUNTS

Still the precondition for step 6. What happened on the live site:

- **Runway and fal are `available: false` on the deployed API** (`/api/queue/pending` → `renderers`). Most likely `RUNWAYML_API_SECRET` / `FAL_KEY` exist only in the Mac's `.env`, not in Fly secrets (not checked — Mike sets keys himself: `fly secrets set -a zeropage-studio RUNWAYML_API_SECRET=...`). Only `higgsfield` and `veo` are available. So a shot whose tool is `RUNWAY` shows a Kling default on the live card (the documented preference-with-fallback of `render_default`, not a bug).
- Mike approved **#361 "The Crimson Descent"** (antihero, picked, 3 refs, keyframe drawn, one continuous take = ONE clip) on **Higgsfield `kling2.1`, 5 s, $0.40**. `POST /api/queue/361/approve` → 200 with signing on; the job failed at the provider submit: **`HTTP Error 423: Locked`** from Higgsfield. Nothing rendered, nothing charged, Higgsfield's daily count still 0, #361 still waiting. The 423 is the Higgsfield ACCOUNT (billing / API access), not our request — Mike has to look at the Higgsfield dashboard.
- Prices read off the live `/quote` for #361: Runway `gen4_turbo` 5 s $0.25 / 10 s $0.50, `gen4.5` 5 s $0.60 / 10 s $1.20; Higgsfield `kling2.1` and `kling2.5` 5 s $0.40. Unreachable models were refused with the reason (`bad_render_choice`).
- **Signing is verified in production:** cards carry `signed: true`, a token per render, `pricing_version 2026-09-17-video-v1`. NOT verified: that the approve body carried the token (the request body was not captured).

To unblock: Mike adds the Runway key to Fly (then #361 on `gen4_turbo` 5 s, $0.25) or fixes the Higgsfield lock (then retry Kling, $0.40). **Either way, confirm the exact spend with him again before clicking Approve.** Expected on success: a `generations` row with a vendor tool, `cost_usd` filled, `key_source` set, `media_url` on #361; then read what the nightly `spent_usd` says about it.

### 1b. Three findings from the attempt (none fixed, none filed)

1. **A render that fails at submit leaves NO `generations` row.** The newest rows on the live DB after the failed approve were #113 (the manual Runway lane, 16:36) and #112 (nano). CLAUDE.md says every attempt is a row; the only record of this failure was the in-process jobs registry, which a restart clears. Step 6 puts a ledger hold BEFORE the submit, so this exact path must leave a row (and release the hold). Read `src/higgsfield.py`'s never-raises edge first — find where the row is written relative to the submit.
2. **The React Queue cannot show Antihero scenes.** `GET /api/queue/pending` (no `brand` param) returned all 18 waiting scenes while `/api/me` said the active account was `zeropage`; `web/src/app/studio/queue/page.tsx` draws only the active brand's. Clicking ANTIHERO in the account menu did nothing: no `/brand` request went out and `/api/me` still said `zeropage`. 15 of 18 waiting scenes are invisible in the React studio. The approve was done through `https://zeropage-studio.fly.dev/ui?legacy=1&view=queue`, which sends `?brand=antihero` and works.
3. **"0 concepts carry a media_url" is out of date.** Concept #375 got a Runway clip on 2026-09-18 16:36 through the manual subscription lane (`cost_usd` NULL, `source: manual-unlimited`). No API-billed render has gone through yet — that is the one that matters for step 6.

### 2. Two decisions Mike has to make (ask, do not assume)

- **`MARKUP`.** The spec argues **2.4** ($1.00 of provider cost = 240 credits). It is `"1.0"` today. One-line change in `src/pricing.py`, but every credits number in the tests moves with it — that is why step 5 pairs it with the token requirement in one commit.
- **Zero credits with a key on file: refuse, or fall through to BYOK?** This decides what `ledger.hold_for_render` does. No account has ever been granted credit, so wiring `hold()` today would refuse every render, including Mike's own.

### 3. Step 5 — token required on approve + MARKUP raised, ONE commit

- `app/api.py:2627`: `if body.tokens:` becomes "when `pricing.configured()`, tokens are required" — a billable render with no token is a 400 `missing_quote`; BYOK renders (`quote()` returns `None`, `display()["signed"]` false for them) still approve without one. Keep the unconfigured posture (no secret → no tokens expected) so a dev box with no secret is not locked out.
- The other two callers that mint/accept no token yet: `shot_generate` (the board's per-shot render) and `/api/generate/run`'s video branch. Decide whether they get a token or are routed through the Queue; the spec's "five human callers" section is the list.
- Raise `MARKUP` to the number Mike gave. Re-run `tests/test_pricing.py` — the credits assertions were written against 1.0 and will say so.
- Bump `PRICING_VERSION` only if the wire body changes; a MARKUP change alone does not retire signed quotes (credits are inside the signed body, so a stale-price token already fails `wrong_render` at approve).

### 4. Step 6 — the ledger sandwich

- `spend_approved(approved=..., quote=...)` in `src/runway.py`, `src/fal.py`, `src/veo.py`, `src/higgsfield.py` — change of shape, not location (spec: "`spend_approved` changes shape, not location"). The hold is taken from the Quote **before** the provider submit; **never move a ledger write to after the submit**.
- `ledger.hold_for_render(quote)` → `settle` on the generations row → `release` on failure. `ledger.is_billable(account_keys.key_source(...))` is already the BYOK test `quote()` uses; reuse it.
- **The daily-cap check stays in the route** (`generative.cap_error`), not in pricing.py.
- The timeline loop (`_render_timeline`) holds per part, exactly as the spend approval and the generations row are per part today.
- Integration test against a stub adapter (spec's "Integration" section): approve → hold → submit → settle, and the revert-and-red check on each line.

## Rules that still bind (from the original handoff)

- **Never point the suite at Supabase.** `tests/conftest.py` creates and drops schemas; `TEST_DSN` defaults to local Postgres. On the Mac: `postgresql://zeropage:zeropage@localhost:5432/zeropage` (Postgres.app, throwaway schemas). Full suite ≈ 16–17 min.
- **The suite inherits the real `.env`.** Any new env var goes into `conftest`'s `POSTURE_ENV` the day it is added (`QUOTE_SIGNING_SECRET` is there already; `test_the_suite_does_not_inherit_a_real_secret` guards it).
- **Check for parallel sessions before any branch work** (`git worktree list` from the main checkout — three other sessions' trees were live on 09-18). Branch from `origin/main`, merge with `git push . <branch>:<target>` or a PR; never `git checkout` a branch to merge it. Do not `git stash` bare.
- **Code rules:** `account_id` keyword-only, no default, in the data layer. Do not re-implement `renderer_for`. Do not write a second content hash — `pricing.content_hash`. Do not move the cap check into pricing.py. Do not move any ledger write after the provider submit.
- **Test standard:** a test that does not fail when the fix is reverted proves nothing — revert each guarded line and confirm red before calling it done. `conftest`'s `account_scope` override returns `None`, so ownership tests must seed real accounts and set their own `dependency_overrides`.
- **Deliverable:** a branch + PR, not a merge, unless Mike says "merge". Report what the suite said (passed / xfailed / failed, pre-existing ones named), `ruff check src app tests ops`, and every place the spec was wrong about the code — that last part is the useful one.
- The API **auto-deploys on a push to `main`** (`.github/workflows/fly-deploy.yml`). Do not hand-deploy after a merge.

## Verifying in a browser (the recipe that worked)

Seed a throwaway schema with a script: `db.init_db`, `preprod.init`, `accounts.seed`, two parked concepts carrying `/refs/seed.jpg`. Run uvicorn on :8011 with `QUOTE_SIGNING_SECRET=demo-signing-secret SESSION_SECRET=demo DEV_TOOLS=1 STUDIO_URL= DATABASE_URL=<demo dsn> RAG_DATABASE_URL=postgresql://localhost:1/none`, every renderer/Gemini/R2 key blanked except a fake `RUNWAYML_API_SECRET` and `FAL_KEY`. Mint the cookie with `auth._serializer().dumps({'uid': <uuid>})`, open `http://app.localhost:8011/ui?legacy=1&view=queue` in the built-in browser. Drop the schema after. What was verified last time: default pick priced from the listing; changing the model shows "pricing…" then the new price off one `/quote` request; the Director chip reads `generate`; a stale token on approve is a 400 `stale_content` before any job starts.

## Still open, not blocking

- Nightly `spent_usd` under-report (candidate sites listed in the "As built" section).
- `web/src/app/layout.tsx` `LayoutProps` tsc error — pre-existing, not ours.
- `spend_approved(quote=...)` plumbing — that *is* step 6.

## What can be committed right now

**From the pricing session: nothing is uncommitted.** Steps 1–4, their tests and the spec doc are all on `main`; the branch is deleted. There is no code waiting.

**The main checkout (`~/Documents/PRODUCTION PIPLINE .GIT`) is dirty, and it is NOT this work** — it sits on `feat/multi-tenant-media-keys` with modified `CLAUDE.md`, `app/api.py`, `ops/render_queue.py`, `tests/test_scene_references.py`, five `web/` files, and an untracked `0001-fix-web-composer-refs-on-guide.patch`. That is another session's in-progress tree. Do not commit, stash or reset it; work in a fresh worktree off `origin/main` (main was at `0e16f80`, PR #28, when this was written).

**A docs-only commit that is ready to be written** (small, safe, no decision needed — branch `docs/pricing-as-built`, PR, not a merge):

1. `CLAUDE.md` is stale about this work on `main`:
   - line ~302: "priced by `providers.check_timeline_choice`" — that function was deleted in step 1; pricing is `src/pricing.py` (`display()` / `quote()`).
   - lines ~1556–1557 (Known gaps): "The Queue card's `fitSeconds` is a JS twin of `timeline.fit_seconds`…" — `fitSeconds` was deleted from both front ends in step 3; cards are fed by `GET /api/queue/{id}/quote`. Delete the sentence.
   - add a `src/pricing.py` bullet to the Architecture list (one paragraph: estimate/quote/display, sign/verify, the six refusals, `QUOTE_SIGNING_SECRET` its own secret and unset = prices without tokens, `MARKUP "1.0"` pending Mike's number, steps 5–6 not built) and `QUOTE_SIGNING_SECRET` to the env notes.
   - "Where the project stands": the "0 concepts carry a `media_url`" paragraph — #375 has a manual-lane clip as of 2026-09-18; say "no API-billed render yet" instead. Test count is 2171 passed / 8 xfailed.
2. `docs/BACKLOG.md`: two new entries — findings 1 and 2 above (failed submit leaves no generations row; React Queue brand scoping + dead account switch). Check the file first; #7 there is the shipped brand switcher, which finding 2 contradicts on the React side.
3. `docs/tasks/task-pricing-and-quotes.md`: append the 2026-09-18 live-attempt notes (section 1 above) under "As built".
4. Optionally copy this file into `docs/tasks/` as `task-pricing-and-quotes-handoff-2.md`.

**Not committable yet:** step 5 (needs `MARKUP` + the token-required call) and step 6 (needs the zero-credit rule + one real API-billed render).

## Context that came up and is worth keeping

- Mike asked what InVideo renders with: it owns no video model — it resells Veo 3.1, Kling 3.0, Sora 2, Seedance 2.0 and Wan behind one credit subscription (stock footage + TTS assembly underneath). Same aggregator shape as `providers.VIDEO_PROVIDERS`; the difference is they carry the provider contracts, so their user never sees a locked account or a missing key — which is what today's render attempt hit, and what credits-with-a-markup (steps 5–6) is for.
- A Chrome tab was left open on the legacy Queue (`zeropage-studio.fly.dev/ui?legacy=1&view=queue`).

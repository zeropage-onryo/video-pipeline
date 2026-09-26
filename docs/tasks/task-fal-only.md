# Task: fal is the only video renderer, BYOK is gone

**Decision (Mike, 2026-09-26):** every video render goes through fal on the
operator's key and holds credits. Remove BYOK completely. Retire the Runway,
Veo and Higgsfield video adapters. Veo stays available as a model through fal
(`fal-ai/veo3.1`).

**Why:** one key, one balance, one adapter, one billing path. BYOK users cost
the operator Gemini, Nano, storage and compute while their renders took no
hold, so they paid nothing.

**Out of scope:** image generation (`nano_banana.py`, refgen's Midjourney/nano
chain, element sheets), the Guide's `guide_provider` personal connections, and
historical rows. Past `generations` / `generated_assets` rows and R2 files are
not deleted; old clips keep their original tool labels.

## As built (branch `feat/fal-only`)

### Phase 1 -- inert
- `account_keys.key_and_source` answered from the environment only (then the
  module was deleted in phase 2).
- `ledger.is_billable` lost the BYOK branch. The one remaining exemption is
  the manual lanes' `source` marker; `hold_for_render` still skips the
  unowned pool and a `credit_exempt` account.
- `providers.VIDEO_PROVIDERS == {"fal": fal}`; `DEFAULT_ORDER`,
  `DEFAULT_PROVIDER`, `render_default`, `renderer_for`, `choose_provider` all
  resolve to fal. `RETIRED_PLATFORMS = {"runway", "higgsfield"}` read as the fal
  default at read time; stored rows are never rewritten.
- Veo 3.1 registered in `fal.VIDEO_MODELS` (`fal-ai/veo3.1`,
  `fal-ai/veo3.1/image-to-video`), $0.40/s at 720p/1080p with audio (the
  endpoint default), checked 2026-09-26.
- `shootgen.AI_TOOLS` = shot.py platforms fal renders; `ZEROPAGE_AI_TOOLS`
  = the same; `DEFAULT_SCENE_TOOL` = the fal default's platform (LTX). The
  prompt templates name only those tools.
- A render with no `FAL_KEY` refuses in `fal.generate_video` BEFORE the hold
  and before any HTTP call.

**Found re-checking fal's `/api` schemas on 2026-09-26 -- each would have
failed the first live render after a queue wait:**
- LTX-2.3 takes duration as an enum of `6/8/10` (the table said a 1-20 span
  and the default of 5 was illegal). It also has no 720p tier: 1080p is its
  floor. **The cheapest possible render is LTX 6s at 1080p = $0.36**, not the
  "LTX 5s 720p" the task describes.
- Wan 3.0's i2v image field is `start_image_url`, not `image_url`.
- Kling v3 turbo pro i2v takes neither `negative_prompt` nor `cfg_scale`;
  durations are 3-15 (the table said 5-10).
- Veo 3.1 durations are strings with a unit (`"4s"/"6s"/"8s"`).
- `fal.fit_duration` fits a request UP to the model's enum; `build_body`
  sends it in each model's wire shape (`duration_wire`) and image field
  (`image_field`).

### Phase 2 -- delete
- Deleted: `src/runway.py`, `src/veo.py`, `src/account_keys.py`,
  `app/static/zpf/renderer-keys.js`, the `/api/renderer-keys` routes, the
  Queue keys panel and its CSS, the Runway/Higgsfield prompt renderers in
  `shot.PLATFORMS`, `Shot.runway_mode`, `workflow_runner.image_for_runway`,
  `render_specs`' Runway model table and claim checks.
- `src/higgsfield.py` keeps only its Soul still path (`generate_image`,
  `generate_image_from_prompt`) -- refgen and the scene chain's visual
  targets use it. `higgsfield` joined `generative.IMAGE_TOOLS`.
- `as_image_url` moved into `fal.py`; `render_aliases` moved into
  `entities.py` (and now actually works -- the old copy ran `json.loads` over
  an already-decoded dict and silently applied no alias, ever).
- Gemini BYOK (`gemini_utils.api_key_for`) is env-only.
- The Runway Unlimited lane became the generic `manual` import
  (`ops/render_queue.py --provider manual`, tool `manual`,
  `source: manual-import`, model free text, `model_verified: false`),
  operator-gated like before. `manual-unlimited` stays in
  `SUBSCRIPTION_SOURCES` so #375-style rows still read as FREE.
- `db.drop_account_keys_table` drops the table on init once it is empty
  (live count on 2026-09-26: **0 rows**); a non-empty table is left alone with
  a stderr note.
- `ops/fly/preflight.sh` no longer requires `ACCOUNT_KEYS_SECRET`; it warns
  (never refuses) when `FAL_KEY` is unset.
- Payload rename: `runway` -> `renderer` on `/api/queue/pending` and the
  concept detail; capabilities `runway.*` / `higgsfield.*` -> `video.generate`
  / `video.spend`; `pricing.display()` lost `byok`.

### Phase 3 -- pricing on fal models
- `BANDS` keyed on the fal models; `BAND_BY_FRAME` makes 1080p Seedance 2.0
  premium; Veo 3.1 is premium (max 8s).
- Price = model x resolution x seconds from the dated table x `MARKUP` (2.4),
  integer credits, 10-credit floor. `fal.price_per_second` refuses a
  resolution the model has no rate for instead of defaulting to 720p.
  `fal.estimate_cost` rounds to 4 places (Seedance 720p 10s is $3.034, not
  $3.03). Seedance 2.0: $0.3034/s at 720p, $0.682/s at 1080p (t2v rate card;
  the i2v page says $0.3024 flat -- the higher is priced).
- Default resolution 720p where a model offers it (LTX and Kling: 1080p).
- `PRICING_VERSION = "2026-09-26-fal-v3"`; v2 tokens refuse as
  `retired_pricing`.

## Still Mike's call
- Whether the Higgsfield-MCP operator lane survives (step 10).
- Metering Create (Gemini) and Nano keyframes through the ledger (the next
  task; open sign-up should not go live before it).
- Whether the generic manual import should stay operator-only (it spends
  nothing, but files a render with no hold).
- The one live LTX render (step 6) -- needs a deploy of this branch and costs
  ~$0.36 of fal credit.

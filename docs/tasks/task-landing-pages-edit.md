# Task: edit each landing page, one by one

Started 2026-10-06 on branch `claude/landing-page-template-142b09` (unpushed).
Eleven pages, one entry each under `web/src/landing-pages/entries/`, rendered by
one template. Work them in the order below, one at a time; tick the boxes as
each lands, and keep one commit per page (`feat(web): /models/<slug> -- <what changed>`).

Run it: `preview_start web` (port 3000), or `cd web && npx next dev --port 3105`.
Gates before a commit: `npx tsc --noEmit`, `npx eslint src`, a look at 375 / 768 / 1440.

## The checklist, per page

- [ ] **Copy** -- hero (h1, subhead), the CTA label and the `spark` it opens the composer on, the wall title, nine features, three how-to steps, the FAQ, the final CTA. Every claim is something the studio does today (the entry's top comment says where it was checked).
- [ ] **Media** -- the eight wall tiles are gradient plates (`TODO(media)`); real stills go in as `src` (928x1152 JPEG under `web/public/<section>/<slug>/`). The signature's frames read the first tiles.
- [ ] **Signature** -- the page's one interaction between the hero and the wall (`signature` on the entry; registry in `components/signatures.tsx`). Keep, change, or write one.
- [ ] **Accent** -- `theme.ts`; the page's colour, contrast-checked on white.
- [ ] **Related** -- which other pages it links to under "More to make".
- [ ] **Check** -- 375 / 768 / 1440 in the browser, the Models dropdown and footer still read right, Lighthouse mobile if the page's weight changed.

## The pages

| # | Page | Route | Entry | Accent | Signature | Status |
|---|---|---|---|---|---|---|
| 1 | AI Ad Generator | `/make/ai-product-ad-generator` | `ai-product-ad-generator.ts` | RED | none | [ ] |
| 2 | LTX 2.3 | `/models/ltx-video-generator` | `ltx-video-generator.ts` | EMERALD | **none yet** | [ ] |
| 3 | Wan 3.0 | `/models/wan-video-generator` | `wan-video-generator.ts` | AMBER | **none yet** | [ ] |
| 4 | Kling 3 Turbo Pro | `/models/kling-video-generator` | `kling-video-generator.ts` | ROSE | **none yet** | [ ] |
| 5 | Seedance 2.0 / Fast | `/models/seedance-video-generator` | `seedance-video-generator.ts` | INDIGO | shot-timeline | [ ] |
| 6 | Veo 3.1 | `/models/veo-video-generator` | `veo-video-generator.ts` | BLUE | **none yet** | [ ] |
| 7 | Nano Banana Pro | `/models/nano-banana-image-generator` | `nano-banana-image-generator.ts` | AMBER | reference-stack | [ ] |
| 8 | FLUX.2 Pro | `/models/flux-image-generator` | `flux-image-generator.ts` | EMERALD | frame-picker | [ ] |
| 9 | Seedream 4.0 | `/models/seedream-image-generator` | `seedream-image-generator.ts` | ROSE | edit-loop | [ ] |
| 10 | GPT Image 2 | `/models/gpt-image-generator` | `gpt-image-generator.ts` | BLUE | type-frame | [ ] |
| 11 | Ideogram 3 | `/models/ideogram-image-generator` | `ideogram-image-generator.ts` | VIOLET | poster-type | [ ] |

## Known per page, going in

1. **AI Ad Generator** -- the one page with real media (eight ads under `web/public/make/ai-product-ad-generator/`). The only page under Solutions. No signature by design; decide whether it wants one.
2. **LTX 2.3** -- 6/8/10 s, 1080p/1440p/2160p, every plan, open weights. Lowest credits per second in the catalog (the feature card checks this at build and rewords itself if it stops being true). No signature: a frame ladder (1080p -> 2160p) was the idea.
3. **Wan 3.0** -- 2-10 s, 480p/720p/1080p, every plan; "motion" is the pitch. No signature: a length strip (2 -> 10 s) was the idea. Native audio and first/last frame exist in the model and are not in the Queue.
4. **Kling 3 Turbo Pro** -- 3-15 s, 1080p flat rate, Creator and up; "people". No signature: a horizontal scroll-snap strip of takes was the idea. Kling's multi-shot storyboard is the model's, not the Queue's.
5. **Seedance** -- covers both tiers (2.0 and 2.0 Fast). Seedance 2.5 is on fal and NOT in `src/fal.py`; naming it needs the model added and `python -m src.pricing export` first.
6. **Veo 3.1** -- 4/6/8 s, 720p/1080p, sound on (the rate the card prices), Studio plan only. No signature: an animated sound-bar frame was the idea. Reference images, extend and 4K are the model's, not the Queue's.
7. **Nano Banana Pro** -- two routes (Gemini key, 33 credits a Pro still off the catalog; fal, 1K/2K). Draws every element sheet. The reference-stack signature reads the wall's first six tiles.
8. **FLUX.2 Pro** -- up to eight references in the studio, priced per megapixel (a reference edit costs more). Frame-picker shows the ten `IMAGE_SIZES`.
9. **Seedream 4.0** -- generate and edit in one model, per-image price. The edit-loop divider reads the wall's first two tiles as before/after.
10. **GPT Image 2** -- three named sizes at medium quality, up to sixteen references, text rendering. Type-frame cycles four sample lines.
11. **Ideogram 3** -- text-only (no references), balanced speed, posters and type. Poster-type offers three settings in the site's own faces.

## Across all pages

- [ ] An image catalog export (`src/pricing.py` -> `pricing.json`) so image-model names stop being typed by hand in `shared.ts`.
- [ ] Per-page OpenGraph cards (today every page names the root's generated card).
- [ ] Lighthouse performance sits at 76-84 on mobile; the cap is the root layout preloading six font families for every page (`app/layout.tsx`, shared with `/studio`).

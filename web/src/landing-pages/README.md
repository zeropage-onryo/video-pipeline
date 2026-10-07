# Landing pages

The SEO landing pages under `/make/<slug>` live here, in one folder:

- `pages.ts` — the types and the ordered list `MAKE_PAGES`. **Adding a page is adding
  an entry under `entries/` and listing it here.** The route, the sitemap, the header's
  Solutions menu, the footer's Tools column and the FAQ JSON-LD all read this list.
- `entries/<slug>.ts` — one typed `MakePage` per page (the Ad Generator, Seedance, and
  the five image models: Nano Banana Pro, FLUX.2 Pro, Seedream 4.0, GPT Image 2,
  Ideogram 3). Every claim is checked against the code and the comment at the top of
  each file says where.
- `shared.ts` — what entries build from: the video-model readers off `@/lib/catalog`
  (`model`, `modelCards`, `PLAN_FOR`), the image-model list copied from
  `src/fal.py IMAGE_MODELS` by hand (names and notes, never prices; dated), the ten
  composer frames, the shared FAQ answers, `plateTiles`. Prices in copy are read off
  the catalog, never typed; an image still's price is only ever "shown in the picker".
- `theme.ts` — a page's **accent** (`MakeAccent`): button fill, card outline
  and hover line, the feature card's pointer light, the wall's two gradient
  plates. `accentVars()` turns it into CSS variables on the page's skin
  wrapper (`EditorialSkin style=`), so every section reads `var(--primary)`,
  `var(--card-line)`, `var(--plate-1)`… and nothing is forked per colour.
  `RED` is the light tone's original palette, byte for byte.
- `components/` — the sections, in page order: `make-hero` (bold serif H1,
  subhead, the two buttons, the spotlight), `overview-section` (optional, 2026-10-07: the model maker's own headline
  claims as alternating statement blocks, each with a media slot -- the
  Seedance page's is ByteDance's four), `signatures` (the page's ONE
  signature interaction, keyed by `signature` on the entry; nothing when
  unset: `shot-timeline`, `reference-stack`, `frame-picker`, `edit-loop`,
  `type-frame`, `poster-type`; `use-fit` sizes a frame of a given ratio
  inside a fixed stage), `ad-wall` (one heavy uppercase line, an eight-tile wall on Motion --
  tilt, lift, label slide -- and the Explore button; a tile with no `src` is
  a gradient plate off the accent), `features-section` (nine cards on Motion,
  `features-grid`), `models-section` + `how-to-section` (both `link-cards`),
  `faq-section` (one big line over centered-question rows, Base UI accordion),
  `related-section` (hidden while empty), `final-cta`. `section-title` is
  every section's headline. `make-page.tsx` assembles them inside the
  homepage's header, footer and skin.
- Motion is shared: `@/lib/motion` (pure: the easing, the springs, the
  stagger, `reveal()` / `inViewReveal()` props builders, the hover variants)
  and `@/lib/motion-hooks` (`useStill`, `useRevealGroup`; client components
  only -- a server component may import a constant from the first file but
  Next refuses a hook there). Reduced motion renders the finished state.

Each entry names its `section`: `make` renders at `/make/<slug>` (the Ad
Generator only; the header's Solutions menu and the footer's Tools column)
and `models` at `/models/<slug>` (every model's own page -- LTX, Wan, Kling,
Seedance, Veo, and the five image models; 2026-10-05, Mike's call). A model
page carries `modelIds` (catalog ids for a video page, `IMAGE_MODELS` ids for
an image page) so `/models` links each model card to its page
(`pageForModel`) and the footer's Models column names it (`pageLabel`). `makePath(page)` follows the section. The two Next routes,
`src/app/make/[slug]/page.tsx` and `src/app/models/[slug]/page.tsx`, are thin
bindings of `route.tsx`: static params for the section, metadata (title,
description, canonical, OG) and the JSON-LD; a slug under the wrong section
is a 404, so every page has exactly one URL.

## Adding a page

1. Write `entries/<slug>.ts` exporting a `MakePage` and add it to `MAKE_PAGES`
   in `pages.ts`: slug, title/description, h1,
   menu line, subhead, `cta` (label + the spark the composer opens on;
   optional `secondary` button and `startLabel`), `tone`, `accent` (`RED`, or
   a new `MakeAccent` in `theme.ts`), the wall's tiles (a tile with no `src`
   draws a plate), nine features, the model cards, three how-to cards, the
   FAQ, `related` slugs, the final CTA. Optionally `signature` and
   `overview` (statement blocks between the hero and the signature).
2. Want a signature section? Write a client component taking `{ page }`,
   register it in `components/signatures.tsx`, name its key on the entry.
3. Nothing else: the sitemap, header, footer and JSON-LD follow the list.

Every claim on a page must be something the studio does today. The CTA
carries the entry's `cta.spark` into the composer as `?spark=` through
sign-in (`goToSignIn(mode, path)`); the composer reads no template parameter
yet, so that is the extent of a "starting point" for now.

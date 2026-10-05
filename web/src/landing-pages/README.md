# Landing pages

The SEO landing pages under `/make/<slug>` live here, in one folder:

- `pages.ts` — one typed entry per page. **Adding a page is adding an entry.**
  The route, the sitemap, the header's Solutions menu, the footer's Tools column and the FAQ JSON-LD all
  read this list. Prices in copy are read off `@/lib/catalog`, never typed.
- `theme.ts` — a page's **accent** (`MakeAccent`): button fill, card outline
  and hover line, the feature card's pointer light, the wall's two gradient
  plates. `accentVars()` turns it into CSS variables on the page's skin
  wrapper (`EditorialSkin style=`), so every section reads `var(--primary)`,
  `var(--card-line)`, `var(--plate-1)`… and nothing is forked per colour.
  `RED` is the light tone's original palette, byte for byte.
- `components/` — the sections, in page order: `make-hero` (bold serif H1,
  subhead, the two buttons, the spotlight), `signatures` (the page's ONE
  signature interaction, keyed by `signature` on the entry; nothing when
  unset), `ad-wall` (one heavy uppercase line, an eight-tile wall on Motion --
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

The Next route is the thin shell at `src/app/make/[slug]/page.tsx`: static
params, metadata (title, description, canonical, OG) and the JSON-LD.

## Adding a page

1. Add an entry to `MAKE_PAGES` in `pages.ts`: slug, title/description, h1,
   menu line, subhead, `cta` (label + the spark the composer opens on;
   optional `secondary` button and `startLabel`), `tone`, `accent` (`RED`, or
   a new `MakeAccent` in `theme.ts`), the wall's tiles (a tile with no `src`
   draws a plate), nine features, the model cards, three how-to cards, the
   FAQ, `related` slugs, the final CTA. Optionally `signature`.
2. Want a signature section? Write a client component taking `{ page }`,
   register it in `components/signatures.tsx`, name its key on the entry.
3. Nothing else: the sitemap, header, footer and JSON-LD follow the list.

Every claim on a page must be something the studio does today. The CTA
carries the entry's `cta.spark` into the composer as `?spark=` through
sign-in (`goToSignIn(mode, path)`); the composer reads no template parameter
yet, so that is the extent of a "starting point" for now.

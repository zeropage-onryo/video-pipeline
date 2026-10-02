# Landing pages

The SEO landing pages under `/make/<slug>` live here, in one folder:

- `pages.ts` — one typed entry per page. **Adding a page is adding an entry.**
  The route, the sitemap, the footer's Make column and the FAQ JSON-LD all
  read this list. Prices in copy are read off `@/lib/catalog`, never typed.
- `components/` — the sections, in page order: `make-hero` (bold serif H1,
  subhead, the two buttons, the spotlight), `ad-wall` (one heavy uppercase
  line, an eight-tile wall on Motion -- tilt, lift, label slide -- and the
  Explore button; a tile with no `src` is a gradient plate), `features-section`
  (nine cards on Motion, `features-grid`), `faq-section` (Base UI accordion), `related-section` (hidden
  while empty), `final-cta`. `section-title` is the wall's headline.
  `make-page.tsx` assembles them inside the homepage's header, footer and skin.

The Next route is the thin shell at `src/app/make/[slug]/page.tsx`: static
params, metadata (title, description, canonical, OG) and the JSON-LD.

Every claim on a page must be something the studio does today. The CTA
carries the entry's `cta.spark` into the composer as `?spark=` through
sign-in (`goToSignIn(mode, path)`); the composer reads no template parameter
yet, so that is the extent of a "starting point" for now.

// The SEO landing pages under /make/<slug> (2026-10-01). ONE typed entry
// per page, ONE template (app/make/[slug]/page.tsx) -- adding a page is
// adding an entry under entries/ and listing it here, and the sitemap, the
// static params, the metadata, the header's Solutions menu, the footer's
// Tools column and the FAQ JSON-LD all read this list.
//
// Every claim in an entry is something the studio does today. Check the
// code before writing a new one (the first page's audit is in the PR):
// the composer takes `?spark=` and `?attach=` only, the Queue is the one
// spend, prices come from the catalog (shared.ts) and are never typed by hand.
//
import type { MakeAccent } from "./theme";
import type { SignatureKey } from "./components/signatures";
import { AD_GENERATOR } from "./entries/ai-product-ad-generator";
import { SEEDANCE } from "./entries/seedance-video-generator";
import { NANO_BANANA } from "./entries/nano-banana-image-generator";

// One tile in the wall under the hero (the InVideo-style wall, 2026-10-01).
// A tile with no `src` draws as a gradient plate, the way the
// reference wall leaves two slots as colour. Up to eight are laid out; the
// layout itself is the wall's (ad-wall.tsx), not the entry's.
export type MakeTile = {
  /** The bold label on the tile. Empty = no label at all. */
  title: string;
  /** The small chip under the label ("UGC Ad", "Product Film"). Empty = no chip. */
  tag: string;
  /** A third line under the chip (a price, a length). */
  meta?: string;
  /** A still: a path under public/ or an R2 URL. Absent = gradient plate. */
  src?: string;
  /** The plate's own gradient (CSS). Absent = the accent's two, alternating. */
  plate?: string;
  /** mp4/webm; when present the tile loops it muted, `src` as poster. */
  video?: string;
};

export type MakeCard = { title: string; body: string };
/** A feature card: the icon is a key features-grid.tsx maps to a glyph. */
export type MakeFeature = MakeCard & { icon: FeatureIcon };
export type FeatureIcon =
  | "references"
  | "elements"
  | "shots"
  | "keyframe"
  | "price"
  | "model"
  | "export"
  | "guide"
  | "assets"
  | "frame"
  | "sound"
  | "clock"
  | "open"
  | "type"
  | "edit";
export type MakeFaq = {
  q: string;
  /** Plain text: it is also the FAQPage JSON-LD answer. */
  a: string;
  /** An optional link rendered after the answer. */
  link?: { href: string; label: string };
};

export type MakePage = {
  slug: string;
  /** <title> without the site suffix (layout.tsx adds " — Zero Page"). */
  title: string;
  description: string;
  h1: string;
  /** The short line in the header's Solutions menu (site-header.tsx). */
  menu: string;
  subhead: string;
  cta: {
    label: string;
    /** carried into the composer as ?spark= */
    spark: string;
    /** The outline button beside it. Default: "See examples" -> #examples. */
    secondary?: { label: string; href: string };
    /** The small link at the foot of every model and how-to card. Default "Start now". */
    startLabel?: string;
  };
  /** Which starting shape the composer opens with. Only "spark" exists
   *  today; a real `?template=` the composer reads is the follow-up. */
  template: "spark";
  /** The skin's tone. "light" is white ground, black type (2026-10-01). */
  tone: "light" | "dark";
  /** The page's own colours (theme.ts), published as CSS variables on the
   *  skin wrapper. `RED` is the light tone's original palette. */
  accent: MakeAccent;
  /** The page's one signature interaction, drawn between the hero and the
   *  wall (components/signatures.tsx). Absent = none. */
  signature?: SignatureKey;
  /** The wall right under the hero (ad-wall.tsx): its own big line, up
   *  to eight tiles, and the button under them. */
  wall: { title: string; tiles: MakeTile[]; explore: { label: string; href: string } };
  /** Nine feature cards under one big line (features-grid.tsx). */
  features: { title: string; items: MakeFeature[] };
  /** Four model cards under one big line, each with a Start now. */
  models: { title: string; items: MakeCard[] };
  /** Three numbered how-to cards under one big line. */
  howTo: { title: string; items: MakeCard[] };
  /** The FAQ: one big line, then centered-question rows (faq-section.tsx). */
  faq: { title: string; items: MakeFaq[] };
  /** Slugs of other /make pages to link to. Empty hides the section. */
  related: string[];
  finalCta: { eyebrow: string; title: string; body: string };
};

// In the order the Solutions menu and the Tools column list them.
export const MAKE_PAGES: MakePage[] = [AD_GENERATOR, SEEDANCE, NANO_BANANA];

export function getMakePage(slug: string): MakePage | undefined {
  return MAKE_PAGES.find((p) => p.slug === slug);
}

export const makePath = (slug: string) => `/make/${slug}`;

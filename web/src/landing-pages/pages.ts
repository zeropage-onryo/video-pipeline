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
import { LTX } from "./entries/ltx-video-generator";
import { WAN } from "./entries/wan-video-generator";
import { KLING } from "./entries/kling-video-generator";
import { VEO } from "./entries/veo-video-generator";
import { NANO_BANANA } from "./entries/nano-banana-image-generator";
import { FLUX } from "./entries/flux-image-generator";
import { SEEDREAM } from "./entries/seedream-image-generator";
import { GPT_IMAGE } from "./entries/gpt-image-generator";
import { IDEOGRAM } from "./entries/ideogram-image-generator";

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
  /** The showcase wall only (2026-10-07): the prompt the clip was made
   *  from, shown under the tile when it is clicked. */
  prompt?: string;
  /** The showcase wall only: the generation mode chip ("I2V", "T2V"). */
  mode?: string;
  /** The showcase wall only: the tile's frame, "w:h" (default "3:4"). */
  aspect?: string;
};

export type MakeCard = {
  title: string;
  body: string;
  /** This card's own starting line for the composer (default: the page's). */
  spark?: string;
  /** A plain link instead of the sign-up door, e.g. the full model list. */
  link?: { href: string; label: string };
};
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
/** One statement block in the overview (2026-10-07, Mike: the shape of
 *  ByteDance's own Seedance 2.5 page -- a heading, one or two sentences,
 *  a demo beside it): the eyebrow, the serif line, the body, optional
 *  points, and a media slot drawn like a wall tile (plate until a still or
 *  a clip lands). */
export type MakeOverviewBlock = {
  eyebrow?: string;
  title: string;
  body: string;
  points?: string[];
  media?: MakeTile;
  /** The clip carries sound worth hearing: the slot gets an unmute toggle
   *  (autoplay is always muted). */
  sound?: boolean;
  /** A second clip under a draggable divider, e.g. a 480p draft against
   *  the 720p final: `media` is the right side, this is the left. */
  compare?: { media: MakeTile; label: string; mediaLabel: string };
};
export type MakeFaq = {
  q: string;
  /** Plain text: it is also the FAQPage JSON-LD answer. */
  a: string;
  /** An optional link rendered after the answer. */
  link?: { href: string; label: string };
};

/** Where a page lives: /make/<slug> (a thing to make) or /models/<slug>
 *  (a model's page, listed on /models under "Image models"; 2026-10-05,
 *  Mike's call). The template is the same; the route, the menu and the
 *  footer column follow the section. */
export type MakeSection = "make" | "models";

export type MakePage = {
  slug: string;
  section: MakeSection;
  /** The model ids this page is about -- catalog `model` ids for a video
   *  page, shared.ts IMAGE_MODELS ids for an image page -- so the /models
   *  listing can link each model to its page. */
  modelIds?: string[];
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
  /** The overview between the hero and the signature (overview-section.tsx):
   *  the model's own headline claims, each a block with a demo slot, in
   *  the shape of the model maker's page. Absent = none. */
  overview?: { items: MakeOverviewBlock[] };
  /** The wall right under the hero (ad-wall.tsx): its own big line, up
   *  to eight tiles, and the button under them. */
  wall: {
    title: string;
    tiles: MakeTile[];
    explore: { label: string; href: string };
    /** "bento" (default) is the four-column wall; "showcase" is three
     *  masonry columns of mixed-frame tiles, each opening its prompt
     *  underneath on click (showcase-wall.tsx, after ByteDance's own
     *  "Creativity Unleashed" grid; 2026-10-07, Mike's call). */
    layout?: "bento" | "showcase";
  };
  /** The signature's own frames, when they are not the wall's first tiles
   *  (shot-timeline.tsx reads these first). */
  signatureFrames?: MakeTile[];
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
export const MAKE_PAGES: MakePage[] = [
  AD_GENERATOR,
  LTX,
  WAN,
  KLING,
  SEEDANCE,
  VEO,
  NANO_BANANA,
  FLUX,
  SEEDREAM,
  GPT_IMAGE,
  IDEOGRAM,
];

export function getMakePage(slug: string, section?: MakeSection): MakePage | undefined {
  return MAKE_PAGES.find((p) => p.slug === slug && (!section || p.section === section));
}

/** The pages in one section, in list order. */
export const pagesIn = (section: MakeSection) => MAKE_PAGES.filter((p) => p.section === section);

/** A page's path, from its section: /make/<slug> or /models/<slug>. */
export function makePath(slugOrPage: string | MakePage): string {
  const page = typeof slugOrPage === "string" ? getMakePage(slugOrPage) : slugOrPage;
  const section = page?.section ?? "make";
  const slug = typeof slugOrPage === "string" ? slugOrPage : slugOrPage.slug;
  return `/${section}/${slug}`;
}

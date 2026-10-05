// The SEO landing pages under /make/<slug> (2026-10-01). ONE typed entry
// per page, ONE template (app/make/[slug]/page.tsx) -- adding a page is
// adding an entry here, and the sitemap, the static params, the metadata
// and the FAQ JSON-LD all read this list.
//
// Every claim in an entry is something the studio does today. Check the
// code before writing a new one (the first page's audit is in the PR):
// the composer takes `?spark=` and `?attach=` only, the Queue is the one
// spend, prices come from the catalog below and are never typed by hand.
//
import { MODELS, num } from "@/lib/catalog";
import { RED, type MakeAccent } from "./theme";
import type { SignatureKey } from "./components/signatures";

// One tile in the wall under the hero (the InVideo-style wall, 2026-10-01).
// A tile with no `src` draws as a soft gradient plate, the way the
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
  | "assets";
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

const model = (id: string) => {
  const m = MODELS.find((x) => x.model === id);
  if (!m) throw new Error(`make-pages: no model ${id} in pricing.json`);
  return m;
};

// The three models the model cards quote, read off the generated catalog so
// a re-export of src/pricing.py changes the page and nothing has to be
// remembered. The FAQ names every model and no price (2026-10-02).
const ltx = model("ltx2.3");
const kling = model("kling3-turbo-pro");
const veo = model("veo3.1");

// The model cards: three renderers off the catalog (name, blurb and price
// are the catalog's own) and a fourth for the rest of the list.
const PLAN_FOR = { standard: "every plan", creator: "Creator and up", premium: "the Studio plan" } as const;
const modelCard = (m: typeof ltx): MakeCard => ({
  title: m.name,
  body: `${m.blurb} ${num(m.credits)} credits for a ${m.seconds}-second clip, on ${PLAN_FOR[m.tier]}.`,
});
// Every model name off the catalog, "A, B and C", for the FAQ.
const MODEL_NAMES = (() => {
  const n = MODELS.map((m) => m.name);
  return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}` : n.join("");
})();

const MODEL_CARDS: MakeCard[] = [
  modelCard(ltx),
  modelCard(kling),
  modelCard(veo),
  {
    title: `${MODELS.length} Models`,
    body: `Every video model the Queue renders on, ${MODELS.filter((m) => ![ltx, kling, veo].includes(m))
      .map((m) => m.name)
      .join(", ")} included, with the price on the card before you approve.`,
  },
];

// The wall's stills are eight product ads generated in the studio (Mike,
// 2026-10-02; 928x1152 JPEGs under public/make/<slug>/, named by product
// type). Every slot carries one, so no gradient plate is drawn. The slot
// order follows the wall's bento (ad-wall.tsx): 0 is the short tile, 1 and
// 4 the tall narrow ones, 5 the wide one, 6 and 7 the pair at the end.
const ADS = "/make/ai-product-ad-generator";
const TILES: MakeTile[] = [
  { title: "Lip tint", tag: "", src: `${ADS}/lip-tint.jpg` },
  { title: "Fragrance", tag: "", src: `${ADS}/fragrance.jpg` },
  { title: "Energy drink", tag: "", src: `${ADS}/energy-drink.jpg` },
  { title: "Headphones", tag: "", src: `${ADS}/headphones.jpg` },
  { title: "Sneaker", tag: "", src: `${ADS}/sneaker.jpg` },
  { title: "Tumbler", tag: "", src: `${ADS}/tumbler.jpg` },
  { title: "Hot sauce", tag: "", src: `${ADS}/hot-sauce.jpg` },
  { title: "Matcha", tag: "", src: `${ADS}/matcha.jpg` },
];

export const MAKE_PAGES: MakePage[] = [
  {
    slug: "ai-product-ad-generator",
    title: "AI Ad Generator",
    description:
      "Upload your product, pick a look, and render a short ad on Kling, Seedance, LTX, Wan or Veo.",
    h1: "AI Ad Generator",
    menu: "AI Ad Generator",
    subhead: "Upload your product, pick a look, and render a short ad on the model you choose.",
    cta: {
      label: "Create your ad",
      spark:
        "A 10-second product ad for my [product]: a reveal, a detail, the product in use. Clean, premium look.",
    },
    template: "spark",
    tone: "light",
    accent: RED,
    wall: {
      title: "ZeroPage Ad Generator",
      tiles: TILES,
      explore: { label: "Explore more", href: "#features" },
    },
    features: {
      title: "Ad Generator Features",
      items: [
        {
          icon: "references",
          title: "Product references",
          body: "Your product photos ride into the prompt, the keyframe and the clip. Every shot anchors on a still drawn from them.",
        },
        {
          icon: "elements",
          title: "Reusable elements",
          body: "Save the product as an element once and every ad after is held to the same frames.",
        },
        {
          icon: "shots",
          title: "Timed shots",
          body: "A scene is written as timed shots, 4 to 30 seconds in all, and each shot renders as its own clip.",
        },
        {
          icon: "keyframe",
          title: "Keyframe first",
          body: "See each shot's first frame and redraw it until it is right, before a clip is rendered.",
        },
        {
          icon: "price",
          title: "Price before spend",
          body: "The Queue shows the credits for the exact model and length you picked, and that number is what is charged.",
        },
        {
          icon: "model",
          title: "Pick the model",
          body: "Kling, Seedance, LTX and Wan, plus Veo on the Studio plan, chosen per approve through one Queue.",
        },
        {
          icon: "export",
          title: "Export one MP4",
          body: "Assemble the clips in shot order into one MP4, with a music bed you upload under the clips' own sound.",
        },
        {
          icon: "guide",
          title: "Guided writing",
          body: "Describe the ad, or let the Guide work through story, look and pacing with you before anything is written.",
        },
        {
          icon: "assets",
          title: "Everything on one wall",
          body: "Every render lands on your Assets wall to view, star, sort into folders and download.",
        },
      ],
    },
    models: {
      title: `${MODELS.length} Video Generator Models`,
      items: MODEL_CARDS,
    },
    howTo: {
      title: "How to make a product ad",
      items: [
        {
          title: "Upload your product",
          body: "Sign in, drop a few product photos into the composer, and write one line about the ad. Or save the product as an element and reuse it across ads.",
        },
        {
          title: "Pick a look and approve",
          body: "Describe the look, or let the Guide work through story, look and pacing with you. In the Queue, pick the model, length and frame, with the price on the card.",
        },
        {
          title: "Render and export",
          body: "Clips render one shot at a time. Download each from Assets, or export the whole scene as one MP4 in shot order.",
        },
      ],
    },
    faq: {
      // One line at the title's full size; longer wraps (measured 2026-10-02).
      title: "FAQs about AI Ad Generator",
      // The reference's questions (what it is, how to, the prompt, people,
      // styles, references, models, length, commercial use), each answer
      // checked against the code on 2026-10-02. Cost stays out of this
      // section (Mike's call): prices live on /pricing and /models.
      items: [
        {
          q: "What is an AI product ad generator?",
          a: "A studio that writes a short ad from your product photos and one line about it. The scene is written as timed shots, each shot's first frame is drawn from your photos, and each shot renders as its own clip on the video model you pick. The clips assemble into one MP4.",
        },
        {
          q: "How do I make a product ad with it?",
          a: "Sign in, drop a few product photos into the composer, write one line about the ad, and press Create. Pick the scene on the board, which draws its keyframes, then approve each shot in the Queue. The clips land on your Assets wall, and Export joins them in shot order into one MP4.",
        },
        {
          q: "How do I write the prompt for the best ad?",
          a: "Name the product, one action per shot, and the look you want. The studio writes the full scene prompt as timed shots from that line and your photos. If you would rather talk it through, the Guide works through story, look and pacing with you first. Then check each shot's keyframe before you render: that still is what the clip anchors on, and the Director lets you edit the prompt, swap a reference and redraw it.",
        },
        {
          q: "Can I upload my own product photos as references?",
          a: "Yes. Upload photos into the composer for one ad, or save the product as an element with its photos and reuse it across ads. Every keyframe is drawn from the references attached to the scene, and a scene with no references never reaches the Queue.",
        },
        {
          q: "Can it show a real person or the same product every time?",
          a: "Save the person or product as an element with a few photos, and every scene written against it is held to those frames, keyframe and clip. Video models still vary between renders, so look at the keyframe before you approve. No pixel match is promised, and you need the consent of anyone whose likeness you upload.",
        },
        {
          q: "What looks and styles can it make?",
          a: "Whatever you can describe: the prompt carries the look, the lighting and the camera, and the keyframe shows it before a clip renders. Attach a reference image for the mood and the writing is grounded in it. The Guide can work through the look with you if you have not settled on one.",
        },
        {
          q: "Which video models does it render on?",
          a: `${MODEL_NAMES}, chosen per shot in the Queue with a length and a frame.`,
          link: { href: "/models", label: "See every model" },
        },
        {
          q: "How long can an ad be?",
          a: "A scene runs 4 to 30 seconds, written as timed shots. Each shot renders as its own clip, fitted to the lengths the model you picked supports.",
        },
        {
          q: "Can I use the ads commercially?",
          a: "What the studio generates for your account is yours to use, subject to the terms of the model that rendered it. The output is AI-made, so review it before you publish it.",
          link: { href: "/terms", label: "Read the terms" },
        },
      ],
    },
    related: [],
    finalCta: {
      eyebrow: "Your first ad",
      title: "Make your first product ad.",
      body: "Upload the product, pick a look, see the price, render.",
    },
  },
];

export function getMakePage(slug: string): MakePage | undefined {
  return MAKE_PAGES.find((p) => p.slug === slug);
}

export const makePath = (slug: string) => `/make/${slug}`;

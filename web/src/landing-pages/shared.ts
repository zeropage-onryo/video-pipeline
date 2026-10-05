// What every /make entry builds from (2026-10-05, split out of pages.ts
// when the entries moved to entries/): the catalog readers, the model
// cards, the plan names and the plate helper. Prices and model names are
// read off `@/lib/catalog`, never typed; a re-export of src/pricing.py
// changes every page.
import { CATALOG, MODELS, num, type CatalogModel } from "@/lib/catalog";
import type { MakeCard, MakeTile } from "./pages";

export const model = (id: string): CatalogModel => {
  const m = MODELS.find((x) => x.model === id);
  if (!m) throw new Error(`make-pages: no model ${id} in pricing.json`);
  return m;
};

/** The plan a tier reads as, in a sentence. */
export const PLAN_FOR = { standard: "every plan", creator: "Creator and up", premium: "the Studio plan" } as const;

export const modelCard = (m: CatalogModel): MakeCard => ({
  title: m.name,
  body: `${m.blurb} ${num(m.credits)} credits for a ${m.seconds}-second clip, on ${PLAN_FOR[m.tier]}.`,
});

/** Every model name off the catalog, "A, B and C", for a FAQ answer. */
export const MODEL_NAMES = (() => {
  const n = MODELS.map((m) => m.name);
  return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}` : n.join("");
})();

/** Three named renderers off the catalog and a fourth card for the rest. */
export const modelCards = (featured: CatalogModel[]): MakeCard[] => [
  ...featured.map(modelCard),
  {
    title: `${MODELS.length} Models`,
    body: `Every video model the Queue renders on, ${MODELS.filter((m) => !featured.includes(m))
      .map((m) => m.name)
      .join(", ")} included, with the price on the card before you approve.`,
  },
];

/** The "N Video Generator Models" line every models row carries. */
export const MODELS_TITLE = `${MODELS.length} Video Generator Models`;

/** A tile's own gradient plate. */
export const plate = (a: string, b: string, c: string) =>
  `linear-gradient(150deg, ${a} 0%, ${b} 55%, ${c} 100%)`;

/** Eight plate tiles from eight [title, tag, a, b, c] rows. */
export const plateTiles = (rows: [string, string, string, string, string][]): MakeTile[] =>
  rows.map(([title, tag, a, b, c]) => ({ title, tag, plate: plate(a, b, c) }));

/** The commercial-use answer every page shares, checked against /terms. */
export const COMMERCIAL_FAQ = {
  q: "Can I use the clips commercially?",
  a: "What the studio generates for your account is yours to use, subject to the terms of the model that rendered it. The output is AI-made, so review it before you publish it.",
  link: { href: "/terms", label: "Read the terms" },
};

/** The references answer every page shares, checked against the reference gate. */
export const REFERENCES_FAQ = {
  q: "Can I use my own photos as references?",
  a: "Yes. Upload photos into the composer for one scene, or save a person, product or place as an element and reuse it. Every keyframe is drawn from the references attached to the scene, and a scene with no references never reaches the Queue.",
};

// ---- The image models (2026-10-05, "no the image models") ------------
//
// The composer's picker is a PROJECTION of src/fal.py IMAGE_MODELS
// (GET /api/image-models) and there is no image catalog in pricing.json
// yet, so the labels and notes below are copied from fal.py's table by
// hand (names, never prices) and dated. Credits per still are shown in the
// picker at send time; the one still price the catalog DOES carry is the
// Gemini route's (`actions.still`), read below.
export type ImageModel = { id: string; label: string; note: string; references: boolean };
export const IMAGE_MODELS: ImageModel[] = [
  { id: "nano-banana-pro", label: "Nano Banana Pro", note: "Gemini's image model; strong on references and text.", references: true },
  { id: "flux2-pro", label: "FLUX.2 Pro", note: "FLUX's newest; takes reference images.", references: true },
  { id: "seedream4", label: "Seedream 4.0", note: "ByteDance; photographic, cheap, takes references.", references: true },
  { id: "gpt-image-2", label: "GPT Image 2", note: "OpenAI's image model; strong on text and instructions, takes up to 16 references.", references: true },
  { id: "ideogram3", label: "Ideogram 3", note: "Graphic, typographic, poster-like. Text-only.", references: false },
  { id: "flux-pro1.1", label: "FLUX 1.1 Pro", note: "Sharp, fast, the default. Text-only (no reference input).", references: false },
]; // src/fal.py IMAGE_MODELS, read 2026-10-05

export const imageModel = (id: string): ImageModel => {
  const m = IMAGE_MODELS.find((x) => x.id === id);
  if (!m) throw new Error(`make-pages: no image model ${id}`);
  return m;
};

export const IMAGE_MODELS_TITLE = `${IMAGE_MODELS.length} Image Models`;

/** Three named image models and a fourth card for the rest. */
export const imageModelCards = (featured: ImageModel[]): MakeCard[] => [
  ...featured.map((m) => ({
    title: m.label,
    body: `${m.note} ${m.references ? "Your reference photos reach it." : "Draws from the prompt alone."} The credits per still show in the composer's picker before you send.`,
  })),
  {
    title: IMAGE_MODELS_TITLE,
    body: `Every image model the composer draws on, ${IMAGE_MODELS.filter((m) => !featured.includes(m))
      .map((m) => m.label)
      .join(", ")} included, each priced per still in the picker.`,
  },
];

/** Credits for one still on the Gemini route (pricing.json `actions.still`). */
export const STILL_CREDITS = CATALOG.actions.still;

/** The ten frames the composer draws at (src/fal.py IMAGE_SIZES, ~1 megapixel each). */
export const IMAGE_FRAMES: { ratio: string; w: number; h: number }[] = [
  { ratio: "1:1", w: 1024, h: 1024 },
  { ratio: "4:5", w: 912, h: 1136 },
  { ratio: "5:4", w: 1136, h: 912 },
  { ratio: "3:4", w: 880, h: 1168 },
  { ratio: "4:3", w: 1168, h: 880 },
  { ratio: "2:3", w: 832, h: 1248 },
  { ratio: "3:2", w: 1248, h: 832 },
  { ratio: "9:16", w: 768, h: 1360 },
  { ratio: "16:9", w: 1360, h: 768 },
  { ratio: "21:9", w: 1536, h: 656 },
];

/** The still answers every image page shares, checked against the code. */
export const STILL_FAQS = {
  where: {
    q: "Where does the still go?",
    a: "Onto your Assets wall, under the model that drew it, with its prompt. From there you can view, star, sort into folders, download it, or press Make element to turn it into a reference a scene is held to.",
  },
  video: {
    q: "Can I turn the still into video?",
    a: "Yes. Make element saves the still with the character, prop or place it shows; attach that element to a scene and every shot's keyframe is drawn from it, then rendered as a clip on the video model you pick in the Queue.",
  },
  cost: {
    q: "What does a still cost?",
    a: "Credits, held before the draw and settled when it lands. The composer's model picker shows the credits per still for each model before you send, and a send that would overdraw your balance is refused rather than charged.",
    link: { href: "/pricing", label: "See the plans" },
  },
};

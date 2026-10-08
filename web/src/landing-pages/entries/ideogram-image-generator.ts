// The Ideogram page (2026-10-05; the 4.5 page since 2026-10-08, Mike:
// "upgrade those models in my python with fal and update the landing
// pages"). What the studio does today: the composer draws on ideogram/v4.5
// from the prompt alone (its edit endpoint edits one source image, which is
// not what a composer reference means, so references are not sent and the
// result says so), at fal's named sizes (the ten composer frames fold onto
// square_hd, portrait_4_3, landscape_4_3, portrait_16_9, landscape_16_9),
// at `quality: medium`, with Ideogram's prompt expansion left on (fal's
// default). The model's own claims -- "high-quality images, posters, and
// logos", strength "in rendering text accurately" -- are fal's page for
// ideogram/v4.5, read 2026-10-08, quoted as Ideogram's. Low and high
// quality exist in the model and are not offered here.
//
// MEDIA: every poster was drawn on Ideogram 4.5 (on Higgsfield, 1K, medium,
// prompt expansion OFF so each prompt is the literal one, 2026-10-08). The
// first condensed Lisbon poster misspelled its title ("NIIGHT") and was
// re-rolled, and a Swiss "MOTION" poster cut its top line mid-word and was
// left off the wall; that is the honest failure rate of a type model (2 of
// 17), and the FAQ
// says to read the words back. They were drawn at 2:3; the studio's
// nearest named size for a poster is portrait 3:4.
import { VIOLET } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_FAQS, imageModel, imageModelCards } from "../shared";
import type { MakePage, MakeTile } from "../pages";

const ideogram = imageModel("ideogram4.5");
const nano = imageModel("nano-banana-pro");
const flux = imageModel("flux2-pro");

const DIR = "/models/ideogram-image-generator";
const poster = (name: string, title: string, tag: string): MakeTile => ({ title, tag, src: `${DIR}/${name}.jpg`, aspect: "2:3" });

const SETTINGS: MakeTile[] = [
  { ...poster("lisbon-condensed", "Condensed", ""), prompt: "set in tall condensed bold sans-serif capitals, on four lines", meta: "the title in condensed capitals" },
  { ...poster("lisbon-serif", "Serif italic", ""), prompt: "set in an elegant high-contrast serif italic, large and centred", meta: "the title in a serif italic" },
  { ...poster("lisbon-script", "Brush script", ""), prompt: "hand-lettered in a flowing brush script, large across the top", meta: "the title in brush script" },
];

const TILES: MakeTile[] = [
  poster("logo", "Orbit Coffee", "Logo"),
  poster("lemonade", "Fizz & Fern", "Label on a bottle"),
  poster("neon", "Open late", "Neon sign"),
  poster("perfume", "Nocturne", "Packaging"),
  poster("tshirt", "Stay Weird", "Shirt graphic"),
  poster("tea", "Earl Grey", "Tin label"),
  poster("album", "Low Tide", "Album sleeve"),
  poster("ticket", "The Velvet Hours", "Ticket"),
];

export const IDEOGRAM: MakePage = {
  slug: "ideogram-image-generator",
  section: "models",
  modelIds: ["ideogram4.5"],
  title: "Ideogram 4.5 AI Image Generator",
  description:
    "Draw posters, logos, labels and signs on Ideogram 4.5 with the words spelled as you wrote them and set the way you said: condensed, serif, script. Credits per still shown before you send.",
  h1: "Ideogram 4.5",
  menu: "Ideogram Image Generator",
  subhead:
    "Put the words in quotes and say how they are set. Ideogram 4.5 draws the poster, the logo or the label around them, from one line and nothing else.",
  cta: {
    label: "Draw a poster",
    spark: "A poster on Ideogram 4.5: the title \"[your words]\" set in [condensed capitals / a serif italic / brush script] over [image], two colours.",
    secondary: { label: "See the type", href: "#type" },
    startLabel: "Start a poster",
  },
  template: "spark",
  tone: "light",
  accent: VIOLET,
  layout: {
    hero: "fan",
    order: ["signature", "wall", "features", "faq", "howTo", "models", "related", "final"],
    features: "list",
  },
  heroMedia: [
    poster("jazz", "Midnight in Violet", "Gig poster"),
    poster("book", "The Quiet Hours", "Book cover"),
    poster("magazine", "Northwind", "Magazine cover"),
    poster("plantswap", "Saturday Plant Swap", "Flyer"),
  ],
  signature: "poster-type",
  signatureFrames: SETTINGS,
  wall: {
    title: "Words Ideogram Set",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
    layout: "posters",
  },
  features: {
    title: "Ideogram in the Studio",
    items: [
      {
        icon: "type",
        title: "The words, spelled",
        body: "Ideogram describes 4.5 as strong at rendering text accurately. Put the words in quotes and they come back as letters on a poster, a label, a sign.",
      },
      {
        icon: "edit",
        title: "Say how they are set",
        body: "Condensed capitals, a serif italic, a brush script: name the setting in plain words and the layout follows it. The three Lisbon posters changed only that phrase.",
      },
      {
        icon: "model",
        title: "Graphic, not photographic",
        body: "Posters, logos, packaging, flyers, covers and neon: Ideogram's own pitch for the model, and the work it is in the picker for.",
      },
      {
        icon: "guide",
        title: "Prompt expansion on",
        body: "Ideogram's own expansion fills out a short prompt before it draws. The studio leaves it on, so one line can be enough; quote the words that must not change.",
      },
      {
        icon: "frame",
        title: "Five named shapes",
        body: "Square, portrait 3:4, landscape 4:3, portrait 9:16 and landscape 16:9. The composer's ten frames fold onto the nearest one.",
      },
      {
        icon: "price",
        title: "One price a still",
        body: "Drawn at Ideogram's medium quality and priced per image, whatever the shape. The picker shows the credits per still before you send.",
      },
      {
        icon: "open",
        title: "From the line alone",
        body: "Ideogram draws from text only here: no reference photos are sent, and the result says so. For a product's own label, use a model that takes references.",
      },
      {
        icon: "assets",
        title: "On the wall, under its model",
        body: "Every poster lands on your Assets wall with its prompt, to view, star, sort into folders and download.",
      },
      {
        icon: "export",
        title: "Make it an element, then shoot it",
        body: "Make element turns a poster into a prop a scene is held to: the flyer on the wall, the label on the bottle, the sign over the door.",
      },
    ],
  },
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([ideogram, nano, flux]) },
  howTo: {
    title: "How to set type on Ideogram",
    items: [
      {
        title: "Quote the words",
        body: "Sign in, switch the composer to Image and write one line with the exact words in quotes: the title, the tagline, the small print.",
      },
      {
        title: "Say how they are set",
        body: "Condensed, serif, script, bold or thin, where they sit. Choose Ideogram 4.5 in the picker, with its credits per still beside it, and a shape. Send.",
      },
      {
        title: "Read it back",
        body: "Check every letter before it goes out. Keep it on your Assets wall, download it, or press Make element and put it in a scene.",
      },
    ],
  },
  faq: {
    title: "FAQs about Ideogram",
    items: [
      {
        q: "What is the Ideogram image generator?",
        a: "Ideogram 4.5 is Ideogram's text-to-image model for posters, logos and type. In this studio you write one line with the words in quotes, pick a shape, and the composer draws it through fal. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Does it always spell the words right?",
        a: "Usually, not always. Of the seventeen designs drawn for this page, one came back with a misspelled title and was drawn again, and one cut its top line off mid-word and was left out. Read every letter back before you use a poster.",
      },
      {
        q: "Does it take my reference photos?",
        a: "No. Ideogram draws from the prompt alone in the studio, and a send with photos attached says they were not used. For a product's own packaging, pick Nano Banana Pro, Seedream or FLUX.2 Pro, which take references.",
      },
      {
        q: "What shapes can it draw?",
        a: "Five named shapes: square, portrait 3:4, landscape 4:3, portrait 9:16 and landscape 16:9. The composer's ten frames fold onto the nearest, so a 2:3 poster draws at 3:4.",
      },
      {
        q: "What happened to Ideogram 3?",
        a: "The picker draws on Ideogram 4.5 now, at the same medium quality and price per still. Posters drawn on 3 stay on your wall as they were.",
      },
      {
        q: "Were the posters on this page made on Ideogram 4.5?",
        a: "Yes, every one, from the prompt alone with Ideogram's prompt expansion switched off, so the words you see are the words that were asked for.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["nano-banana-image-generator", "flux-image-generator", "seedream-image-generator"],
  finalCta: {
    eyebrow: "Your first poster",
    title: "Quote the words. Say how they are set.",
    body: "One line, a shape, the credits on the picker. Read it back before it goes out.",
  },
};

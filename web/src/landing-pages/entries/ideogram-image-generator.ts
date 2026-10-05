// The Ideogram 3 page (2026-10-05). What the studio does today: the
// composer draws on fal-ai/ideogram/v3 from the prompt alone (no edit
// endpoint, so reference photos are not sent and the result says so), at
// fal's named sizes (the ten composer frames fold onto square_hd,
// portrait_4_3, landscape_4_3, portrait_16_9, landscape_16_9), at the
// BALANCED rendering speed. The model's own claims -- "high-quality
// images, posters, and logos", "exceptional typography handling" -- are
// fal's page for fal-ai/ideogram/v3, read 2026-10-05, quoted as
// Ideogram's. TURBO and QUALITY speeds exist in the model and are not
// offered here. TODO(media): the wall's eight tiles are plates until
// Ideogram stills from the studio replace them.
import { VIOLET } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_FAQS, imageModel, imageModelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const ideogram = imageModel("ideogram3");
const gpt = imageModel("gpt-image-2");
const flux = imageModel("flux2-pro");

const TILES = plateTiles([
  ["Gig poster", "Poster", "#f5f3ff", "#c4b5fd", "#6d28d9"],
  ["Wordmark", "Logo", "#faf5ff", "#d8b4fe", "#5b21b6"],
  ["Event flyer", "Poster", "#fdf4ff", "#e879f9", "#7e22ce"],
  ["Book cover", "Type", "#eef2ff", "#a5b4fc", "#4c1d95"],
  ["Album art", "Type", "#ede9fe", "#a78bfa", "#3b0764"],
  ["Shop sign", "Logo", "#fae8ff", "#d946ef", "#581c87"],
  ["Night marquee", "Poster", "#2e1065", "#4c1d95", "#c4b5fd"],
  ["Label, foil", "Type", "#3b0764", "#6d28d9", "#ddd6fe"],
]);

export const IDEOGRAM: MakePage = {
  slug: "ideogram-image-generator",
  title: "Ideogram 3 AI Image Generator",
  description:
    "Draw posters, logos and typographic stills on Ideogram 3 from one line, in any of the composer's frames, then make the still an element and shoot it.",
  h1: "Ideogram Image Generator",
  menu: "Ideogram Image Generator",
  subhead:
    "Draw posters, logos and typographic stills on Ideogram 3 from one line, in any of the composer's frames, then make the still an element and shoot it.",
  cta: {
    label: "Draw a poster",
    spark: "A poster on Ideogram: the title \"[your words]\" set in heavy condensed type over [subject], 2:3, two colours.",
    secondary: { label: "See the type", href: "#type" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: VIOLET,
  signature: "poster-type",
  wall: {
    title: "Posters Ideogram Draws",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "Ideogram in the Studio",
    items: [
      {
        icon: "type",
        title: "Typography first",
        body: "Ideogram's claim for version 3 is exceptional typography handling: posters, logos and lettered images. Put the words in quotes and say how they should be set.",
      },
      {
        icon: "model",
        title: "Graphic, not photographic",
        body: "The picker's note is graphic, typographic, poster-like. Reach for it when the still is a design, and for a photograph pick Seedream or FLUX.",
      },
      {
        icon: "frame",
        title: "Named frames",
        body: "Pick any of the composer's ten frames and it folds onto Ideogram's named sizes: square, portrait or landscape at 4:3 or 16:9.",
      },
      {
        icon: "price",
        title: "Balanced speed, priced per still",
        body: "The studio renders at Ideogram's balanced speed and the credits per still show in the picker before you send. Turbo and quality speeds exist in the model and are not offered.",
      },
      {
        icon: "references",
        title: "From the prompt alone",
        body: "Ideogram 3 takes no reference photos in the studio. If you attach some, the result says they were not used rather than dropping them silently.",
      },
      {
        icon: "guide",
        title: "Talk it through or just ask",
        body: "The composer's brain answers when you are bouncing ideas and draws when you ask for the poster, writing the prompt as the work.",
      },
      {
        icon: "assets",
        title: "On the wall, under its model",
        body: "Every still lands on your Assets wall with its prompt, to view, star, sort into folders and download.",
      },
      {
        icon: "elements",
        title: "Make it an element",
        body: "Make element turns a poster into a reference a scene is held to: the sign on the wall, the cover on the table.",
      },
      {
        icon: "export",
        title: "Then shoot it",
        body: "Attach the element to a scene and every shot's keyframe is drawn from it before a clip renders on the video model you pick.",
      },
    ],
  },
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([ideogram, gpt, flux]) },
  howTo: {
    title: "How to draw on Ideogram",
    items: [
      {
        title: "Write the poster, words in quotes",
        body: "Sign in, switch the composer to Image, and write one line: the words, how they are set, what sits behind them.",
      },
      {
        title: "Pick the model and the frame",
        body: "Choose Ideogram 3 in the picker, with its credits per still beside it, and a frame. Send.",
      },
      {
        title: "Read it back, then make it an element",
        body: "The still lands on your Assets wall. Check the lettering, star it, download it, or press Make element and put it in a scene.",
      },
    ],
  },
  faq: {
    title: "FAQs about Ideogram",
    items: [
      {
        q: "What is the Ideogram image generator?",
        a: "Ideogram 3 is Ideogram's image model, known for typography. In this studio you write one line with the words in quotes, pick a frame, and the composer draws the still on it through fal at the balanced speed. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Does it take my reference photos?",
        a: "No. Ideogram 3 draws from the prompt alone in the studio. Attach photos and the result says they were not used. For a still that must match your photos, pick Nano Banana Pro, FLUX.2 Pro, Seedream or GPT Image 2.",
        link: { href: "/models", label: "See every model" },
      },
      {
        q: "What is it good at?",
        a: "Posters, logos and lettered images. Ideogram describes exceptional typography handling and realistic outputs optimised for commercial and creative use. For a photograph, another model in the picker will serve better.",
      },
      {
        q: "What frames can it draw?",
        a: "Any of the composer's ten, folded onto Ideogram's named sizes: square, and portrait or landscape at 4:3 or 16:9.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["gpt-image-generator", "nano-banana-image-generator", "seedream-image-generator"],
  finalCta: {
    eyebrow: "Your first poster",
    title: "Draw your first poster on Ideogram.",
    body: "One line, the words in quotes, a frame, the credits on the picker.",
  },
};

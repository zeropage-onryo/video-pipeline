// The FLUX.2 Pro page (2026-10-05). What the studio does today: the
// composer draws on fal-ai/flux-2-pro at any of the ten ~1-megapixel
// frames (src/fal.py IMAGE_SIZES, `size: "wh"`), and sends reference
// photos to fal-ai/flux-2-pro/edit as image_urls (the studio sends up to
// 8). Priced per megapixel: the first output megapixel at the base rate,
// every further megapixel of input and output at the extra rate, so a
// reference edit costs more than a text draw (fal.image_usd). The model's
// own claims -- "studio-grade images", "zero-configuration quality",
// "style transfer, and sequential editing workflows" -- are fal's page for
// fal-ai/flux-2-pro, read 2026-10-05, quoted as Black Forest Labs'.
// TODO(media): the wall's eight tiles are plates until FLUX stills from
// the studio replace them.
import { EMERALD } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_FAQS, imageModel, imageModelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const flux = imageModel("flux2-pro");
const flux11 = imageModel("flux-pro1.1");
const seedream = imageModel("seedream4");

const TILES = plateTiles([
  ["Editorial portrait", "Still", "#ecfdf5", "#6ee7b7", "#047857"],
  ["Product on stone", "Reference", "#f0fdfa", "#5eead4", "#115e59"],
  ["Style transfer", "Edit", "#ecfeff", "#67e8f9", "#0e7490"],
  ["Interior, morning", "Still", "#f7fee7", "#bef264", "#3f6212"],
  ["Same jacket, new set", "Reference", "#d1fae5", "#34d399", "#064e3b"],
  ["Wide 21:9", "Frame", "#ccfbf1", "#2dd4bf", "#134e4a"],
  ["Night exterior", "Still", "#022c22", "#064e3b", "#6ee7b7"],
  ["Macro texture", "Still", "#064e3b", "#047857", "#a7f3d0"],
]);

export const FLUX: MakePage = {
  slug: "flux-image-generator",
  title: "FLUX.2 Pro AI Image Generator",
  description:
    "Draw a still on FLUX.2 Pro from one line and your reference photos, in any of ten frames from 1:1 to 21:9, then make it an element and shoot it. Credits per still shown before you send.",
  h1: "FLUX Image Generator",
  menu: "FLUX Image Generator",
  subhead:
    "Draw a still on FLUX.2 Pro from one line and your reference photos, in any of ten frames from 1:1 to 21:9, then make it an element and shoot it.",
  cta: {
    label: "Draw a still",
    spark: "An editorial still on FLUX.2 Pro: [subject], window light, 4:5, shallow depth of field.",
    secondary: { label: "See the frames", href: "#frames" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: EMERALD,
  signature: "frame-picker",
  wall: {
    title: "Stills FLUX Draws",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "FLUX in the Studio",
    items: [
      {
        icon: "frame",
        title: "Ten frames, one megapixel each",
        body: "1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9 or 21:9, picked in the composer and sent as exact pixel sizes. Every frame is under one megapixel, so every frame prices the same from text.",
      },
      {
        icon: "references",
        title: "Up to eight reference photos",
        body: "Drop photos into the composer and they go to FLUX.2 Pro's edit endpoint with the prompt. fal describes the model's style transfer and sequential editing; the studio sends up to eight references.",
      },
      {
        icon: "model",
        title: "Zero-configuration quality",
        body: "fal's words for FLUX.2 Pro: studio-grade images with no tuning steps or guidance parameters. The composer sends the prompt and the frame, nothing else to set.",
      },
      {
        icon: "price",
        title: "Priced per megapixel",
        body: "The first output megapixel at the base rate, every further megapixel of input and output at the extra rate, so a reference edit costs more than a text draw. The picker shows the credits before you send.",
      },
      {
        icon: "edit",
        title: "Generate, then edit",
        body: "Send the still again with itself as a reference and a new line, and FLUX edits rather than redraws. Each pass lands on the wall as its own still.",
      },
      {
        icon: "guide",
        title: "Talk it through or just ask",
        body: "The composer's brain answers when you are bouncing ideas and draws when you ask for the still, writing the prompt as the work.",
      },
      {
        icon: "assets",
        title: "On the wall, under its model",
        body: "Every still lands on your Assets wall with its prompt, to view, star, sort into folders and download.",
      },
      {
        icon: "elements",
        title: "Make it an element",
        body: "Make element turns a still into a reference a scene is held to, the one way a render becomes a reference here.",
      },
      {
        icon: "export",
        title: "Then shoot it",
        body: "Attach the element to a scene and every shot's keyframe is drawn from it before a clip renders on the video model you pick.",
      },
    ],
  },
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([flux, flux11, seedream]) },
  howTo: {
    title: "How to draw on FLUX",
    items: [
      {
        title: "Write the still",
        body: "Sign in, switch the composer to Image, drop your reference photos in if the still should match them, and write one line.",
      },
      {
        title: "Pick the model and the frame",
        body: "Choose FLUX.2 Pro in the picker, with its credits per still beside it, and one of the ten frames. Send.",
      },
      {
        title: "Keep it, edit it, or make it an element",
        body: "The still lands on your Assets wall. Send it back with a new line to edit it, star it, download it, or press Make element.",
      },
    ],
  },
  faq: {
    title: "FAQs about FLUX",
    items: [
      {
        q: "What is the FLUX image generator?",
        a: "FLUX.2 Pro is Black Forest Labs' production image model. In this studio you write one line, attach reference photos if you want, pick a frame, and the composer draws the still on it through fal. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Do my reference photos reach the model?",
        a: "Yes. They go to FLUX.2 Pro's edit endpoint with your prompt, up to eight of them. A reference edit is priced higher than a text draw because the model bills input megapixels too.",
      },
      {
        q: "What frames can it draw?",
        a: "Ten frames from 1:1 to 21:9, each sent as an exact pixel size of about one megapixel.",
      },
      {
        q: "What is the difference from FLUX 1.1 Pro?",
        a: "FLUX 1.1 Pro is the older, text-only model in the picker: it takes no reference photos and draws from the prompt alone. FLUX.2 Pro takes references and edits.",
        link: { href: "/models", label: "See every model" },
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["seedream-image-generator", "nano-banana-image-generator", "gpt-image-generator"],
  finalCta: {
    eyebrow: "Your first still",
    title: "Draw your first still on FLUX.",
    body: "One line, your photos, a frame, the credits on the picker.",
  },
};

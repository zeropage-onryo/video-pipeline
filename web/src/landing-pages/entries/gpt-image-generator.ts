// The GPT Image 2 page (2026-10-05). What the studio does today: the
// composer draws on openai/gpt-image-2 at one of three named sizes
// (square 1024x1024, portrait 1024x1536, landscape 1536x1024; the ten
// composer frames fold onto them), at `quality: medium` sent explicitly
// (fal's default is high at four times the price), and sends reference
// photos to openai/gpt-image-2/edit as image_urls, up to 16. The model's
// own claims -- "Near-Perfect Text Rendering", "Strong Prompt Adherence"
// -- are fal's page for openai/gpt-image-2, read 2026-10-05, quoted as
// OpenAI's. Mask inpainting, 4K and the high tier exist in the model and
// are not offered here. TODO(media): the wall's eight tiles are plates
// until GPT Image stills from the studio replace them.
import { BLUE } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_FAQS, imageModel, imageModelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const gpt = imageModel("gpt-image-2");
const nano = imageModel("nano-banana-pro");
const ideogram = imageModel("ideogram3");

const TILES = plateTiles([
  ["Headline in frame", "Text", "#eff6ff", "#93c5fd", "#1d4ed8"],
  ["Packaging mockup", "Text", "#f0f9ff", "#7dd3fc", "#1e40af"],
  ["Sixteen references", "Reference", "#eef2ff", "#a5b4fc", "#1e3a8a"],
  ["Exact instructions", "Prompt", "#ecfeff", "#67e8f9", "#1d4ed8"],
  ["Menu, legible", "Text", "#dbeafe", "#60a5fa", "#172554"],
  ["Landscape 3:2", "Frame", "#e0f2fe", "#38bdf8", "#1e3a8a"],
  ["Night sign", "Text", "#172554", "#1e3a8a", "#93c5fd"],
  ["Portrait 2:3", "Frame", "#1e3a8a", "#1d4ed8", "#bfdbfe"],
]);

export const GPT_IMAGE: MakePage = {
  slug: "gpt-image-generator",
  title: "GPT Image 2 AI Image Generator",
  description:
    "Draw a still on OpenAI's GPT Image 2 from one line and up to sixteen reference photos, with the words in the picture spelled right, then make it an element and shoot it.",
  h1: "GPT Image Generator",
  menu: "GPT Image Generator",
  subhead:
    "Draw a still on OpenAI's GPT Image 2 from one line and up to sixteen reference photos, with the words in the picture spelled right, then make it an element and shoot it.",
  cta: {
    label: "Draw a still",
    spark: "A still on GPT Image 2: a poster for [product] with the headline \"[your words]\" set large and legible, square.",
    secondary: { label: "See the words", href: "#words" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: BLUE,
  signature: "type-frame",
  wall: {
    title: "Stills GPT Image Draws",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "GPT Image in the Studio",
    items: [
      {
        icon: "type",
        title: "Words spelled right",
        body: "OpenAI's claim for GPT Image 2 is near-perfect text rendering, correct spelling and consistent spacing, in Latin and CJK scripts. Put the exact words in the prompt and read them back.",
      },
      {
        icon: "references",
        title: "Up to sixteen reference photos",
        body: "Drop photos into the composer and they go to GPT Image 2's edit endpoint with the prompt, up to sixteen of them, the most of any model in the picker.",
      },
      {
        icon: "guide",
        title: "Follows instructions",
        body: "OpenAI describes strong prompt adherence that preserves composition, lighting and fine detail. Write the still as a brief: what, where, which light, which words.",
      },
      {
        icon: "frame",
        title: "Three sizes",
        body: "Square, portrait or landscape. Pick any of the composer's ten frames and it folds onto the nearest of the three, 1024 by 1024, 1024 by 1536 or 1536 by 1024.",
      },
      {
        icon: "price",
        title: "Medium quality, priced per size",
        body: "The studio sends the medium tier, which fal prices at a quarter of high, and the credits per still show in the picker before you send.",
      },
      {
        icon: "edit",
        title: "Edit by reference",
        body: "Send a still back with a new line and it edits rather than redraws. Mask inpainting exists in the model and is not offered in the studio.",
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
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([gpt, nano, ideogram]) },
  howTo: {
    title: "How to draw on GPT Image",
    items: [
      {
        title: "Write the still, words included",
        body: "Sign in, switch the composer to Image, drop your reference photos in, and write one line with the exact words you want in the picture in quotes.",
      },
      {
        title: "Pick the model and the frame",
        body: "Choose GPT Image 2 in the picker, with its credits per still beside it, and a square, portrait or landscape frame. Send.",
      },
      {
        title: "Read it back, then make it an element",
        body: "The still lands on your Assets wall. Check the words, send it back to edit, or press Make element and shoot it.",
      },
    ],
  },
  faq: {
    title: "FAQs about GPT Image",
    items: [
      {
        q: "What is the GPT Image generator?",
        a: "GPT Image 2 is OpenAI's image model. In this studio you write one line, attach up to sixteen reference photos, pick a frame, and the composer draws the still on it through fal at the medium quality tier. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Can it put exact text in the image?",
        a: "OpenAI describes GPT Image 2's text rendering as near-perfect, with correct spelling and consistent spacing in Latin and CJK scripts. Put the words in quotes in the prompt and read them back in the still before you use it.",
      },
      {
        q: "What sizes does it draw?",
        a: "Three: 1024 by 1024, 1024 by 1536 and 1536 by 1024. The composer's ten frames fold onto the nearest one. 4K and the high quality tier exist in the model and are not offered in the studio.",
      },
      {
        q: "How many reference photos can I attach?",
        a: "Up to sixteen, sent to the model's edit endpoint with your prompt.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["ideogram-image-generator", "nano-banana-image-generator", "flux-image-generator"],
  finalCta: {
    eyebrow: "Your first still",
    title: "Draw your first still on GPT Image.",
    body: "One line, your photos, the words in quotes, the credits on the picker.",
  },
};

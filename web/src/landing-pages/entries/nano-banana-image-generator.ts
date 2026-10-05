// The Nano Banana Pro page (2026-10-05, Mike: "the image models"). What
// the studio does today: the composer's Image mode draws a still on Nano
// Banana through the Gemini key (a Pro still is pricing.json's
// actions.still.pro credits) or on "Nano Banana Pro (fal)" (src/fal.py
// IMAGE_MODELS: 1K/2K, aspect ratio strings, references through the edit
// endpoint); every element's reference sheet is drawn on Nano Banana Pro
// (src/element_sheet.py); a scene's keyframes are drawn on Nano Banana
// (src/nano_banana.py, Flash by default). The model's own claims --
// "industry-leading text generation", consistency "for up to 5 people" --
// are fal's page for fal-ai/nano-banana-pro, read 2026-10-05, quoted as
// Google's. 4K exists in the model and is not offered here. TODO(media):
// the wall's eight tiles are plates until Nano stills from the studio
// replace them.
import { AMBER } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_CREDITS, STILL_FAQS, imageModel, imageModelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const nano = imageModel("nano-banana-pro");
const gpt = imageModel("gpt-image-2");
const flux = imageModel("flux2-pro");

const TILES = plateTiles([
  ["Packshot on white", "Still", "#fffbeb", "#fde68a", "#a16207"],
  ["Same face, new room", "Reference", "#fef3c7", "#fbbf24", "#92400e"],
  ["Lettered label", "Text", "#fff7ed", "#fdba74", "#9a3412"],
  ["Element sheet", "Sheet", "#fefce8", "#fde047", "#854d0e"],
  ["Two people, one scene", "Reference", "#ffedd5", "#fb923c", "#7c2d12"],
  ["Menu board", "Text", "#fef9c3", "#facc15", "#713f12"],
  ["Night market", "Still", "#451a03", "#92400e", "#fcd34d"],
  ["Studio portrait", "Still", "#78350f", "#b45309", "#fef3c7"],
]);

export const NANO_BANANA: MakePage = {
  slug: "nano-banana-image-generator",
  section: "models",
  modelIds: ["nano-banana-pro"],
  title: "Nano Banana Pro AI Image Generator",
  description:
    "Draw a still on Google's Nano Banana Pro from one line and your reference photos, in any of ten frames, then make it an element and shoot it. Credits per still shown before you send.",
  h1: "Nano Banana Image Generator",
  menu: "Nano Banana Image Generator",
  subhead:
    "Draw a still on Google's Nano Banana Pro from one line and your reference photos, in any of ten frames, then make it an element and shoot it.",
  cta: {
    label: "Draw a still",
    spark: "A product still on Nano Banana Pro: [product] on a clean white sweep, soft studio light, the label legible.",
    secondary: { label: "See the references", href: "#references" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: AMBER,
  signature: "reference-stack",
  wall: {
    title: "Stills Nano Banana Draws",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "Nano Banana in the Studio",
    items: [
      {
        icon: "references",
        title: "Your photos reach the model",
        body: "Drop reference photos into the composer and they go to Nano Banana Pro's edit endpoint with the prompt, so the still is of your product, person or place.",
      },
      {
        icon: "type",
        title: "Legible text",
        body: "Google describes Nano Banana Pro's text generation as industry-leading, in multiple languages. Name the words you want on the label and check them in the still.",
      },
      {
        icon: "elements",
        title: "It draws every element sheet",
        body: "Save a character, prop or place as an element and the studio draws its reference sheet on Nano Banana Pro from the real photos, five panels for a person, a turnaround for a prop.",
      },
      {
        icon: "frame",
        title: "Ten frames",
        body: "1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9 or 21:9, picked in the composer. On the fal route the still comes back at 1K or 2K.",
      },
      {
        icon: "price",
        title: "Credits before you send",
        body: `The picker shows each model's credits per still. On the Gemini route a Nano Banana Pro still is ${STILL_CREDITS.pro} credits, a Nano Banana still ${STILL_CREDITS.standard}.`,
      },
      {
        icon: "keyframe",
        title: "The same family draws your keyframes",
        body: "Every shot's first frame in a scene is drawn on Nano Banana from the scene's references, so what you learn writing stills carries into video.",
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
        icon: "export",
        title: "Make it an element, then shoot it",
        body: "Make element turns a still into a reference. Attach it to a scene and every shot's keyframe is drawn from it before a clip renders.",
      },
    ],
  },
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([nano, gpt, flux]) },
  howTo: {
    title: "How to draw on Nano Banana",
    items: [
      {
        title: "Write the still",
        body: "Sign in, switch the composer to Image, drop your reference photos in, and write one line about the still you want.",
      },
      {
        title: "Pick the model and the frame",
        body: "Choose Nano Banana Pro in the picker, with its credits per still beside it, and the frame from the ten on offer. Send.",
      },
      {
        title: "Keep it, or make it an element",
        body: "The still lands on your Assets wall. Star it, download it, or press Make element to hold a scene to it and shoot it.",
      },
    ],
  },
  faq: {
    title: "FAQs about Nano Banana",
    items: [
      {
        q: "What is the Nano Banana image generator?",
        a: "Nano Banana Pro is Google's image generation and editing model, the Gemini image model. In this studio you write one line, attach reference photos, pick a frame, and the composer draws the still on it, through the Gemini key or through fal. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Do my reference photos reach the model?",
        a: "Yes. On the fal route the photos go to Nano Banana Pro's edit endpoint with your prompt. Google describes the model as holding a consistent look for up to five people across generations; check the still rather than assume it.",
      },
      {
        q: "Can it write text in the image?",
        a: "Google describes Nano Banana Pro's text generation as industry-leading and legible in multiple languages. Put the exact words in the prompt and read them back in the still before you use it.",
      },
      {
        q: "What frames and sizes can it draw?",
        a: "Ten frames from 1:1 to 21:9, at about one megapixel. On the fal route the still comes back at 1K or 2K; 4K exists in the model and is not offered in the studio.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["gpt-image-generator", "flux-image-generator", "seedream-image-generator"],
  finalCta: {
    eyebrow: "Your first still",
    title: "Draw your first still on Nano Banana.",
    body: "One line, your photos, a frame, the credits on the picker.",
  },
};

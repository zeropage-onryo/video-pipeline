// The Seedream 4.0 page (2026-10-05). What the studio does today: the
// composer draws on fal-ai/bytedance/seedream/v4/text-to-image at any of
// the ten ~1-megapixel frames (src/fal.py IMAGE_SIZES, all at or above
// the model's 960x960 floor) and sends reference photos to .../v4/edit as
// image_urls (up to 8). Priced per image. The model's own claim --
// "integrates image generation and image editing capabilities into a
// single, unified architecture" -- is fal's page, read 2026-10-05, quoted
// as ByteDance's; fal.py's note bands it "photographic, cheap, takes
// references". TODO(media): the wall's eight tiles are plates until
// Seedream stills from the studio replace them.
import { ROSE } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_FAQS, imageModel, imageModelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const seedream = imageModel("seedream4");
const flux = imageModel("flux2-pro");
const nano = imageModel("nano-banana-pro");

const TILES = plateTiles([
  ["Street portrait", "Still", "#fdf2f8", "#f9a8d4", "#be185d"],
  ["Swap the background", "Edit", "#fff1f2", "#fda4af", "#9f1239"],
  ["Same dress, new light", "Reference", "#fdf4ff", "#e879f9", "#86198f"],
  ["Food, overhead", "Still", "#fce7f3", "#f472b6", "#831843"],
  ["Add the prop", "Edit", "#ffe4e6", "#fb7185", "#881337"],
  ["Golden hour", "Still", "#fae8ff", "#d946ef", "#701a75"],
  ["Night rain", "Still", "#500724", "#831843", "#f9a8d4"],
  ["Twenty takes", "Cheap", "#4a044e", "#86198f", "#f0abfc"],
]);

export const SEEDREAM: MakePage = {
  slug: "seedream-image-generator",
  title: "Seedream 4.0 AI Image Generator",
  description:
    "Draw a photographic still on ByteDance's Seedream 4.0 from one line and your reference photos, edit it in the same model, then make it an element and shoot it.",
  h1: "Seedream Image Generator",
  menu: "Seedream Image Generator",
  subhead:
    "Draw a photographic still on Seedream 4.0 from one line and your reference photos, edit it in the same model, then make it an element and shoot it.",
  cta: {
    label: "Draw a still",
    spark: "A photographic still on Seedream: [subject] at golden hour, 3:2, natural light, no text.",
    secondary: { label: "See the edit", href: "#edit" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: ROSE,
  signature: "edit-loop",
  wall: {
    title: "Stills Seedream Draws",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "Seedream in the Studio",
    items: [
      {
        icon: "edit",
        title: "Generate and edit in one model",
        body: "ByteDance built Seedream 4.0 as one architecture for drawing and editing. Send a still back with a new line and your photos and it edits rather than redraws.",
      },
      {
        icon: "references",
        title: "Your photos reach the model",
        body: "Drop reference photos into the composer and they go to Seedream's edit endpoint with the prompt, up to eight of them.",
      },
      {
        icon: "price",
        title: "Priced per still, and cheap",
        body: "Seedream is priced per image, not per megapixel, and sits at the cheap end of the picker. The credits per still show before you send, so twenty takes is a number you can read first.",
      },
      {
        icon: "frame",
        title: "Ten frames",
        body: "1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9 or 21:9, every one at or above the size the model accepts.",
      },
      {
        icon: "model",
        title: "Photographic",
        body: "The picker's note for Seedream is photographic, cheap, takes references. Write light and lens the way you would brief a photographer.",
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
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([seedream, flux, nano]) },
  howTo: {
    title: "How to draw on Seedream",
    items: [
      {
        title: "Write the still",
        body: "Sign in, switch the composer to Image, drop your reference photos in if the still should match them, and write one line.",
      },
      {
        title: "Pick the model and the frame",
        body: "Choose Seedream 4.0 in the picker, with its credits per still beside it, and one of the ten frames. Send.",
      },
      {
        title: "Edit it, or make it an element",
        body: "The still lands on your Assets wall. Send it back with a new line to edit it in the same model, or press Make element and shoot it.",
      },
    ],
  },
  faq: {
    title: "FAQs about Seedream",
    items: [
      {
        q: "What is the Seedream image generator?",
        a: "Seedream 4.0 is ByteDance's image model, one architecture for both drawing and editing. In this studio you write one line, attach reference photos if you want, pick a frame, and the composer draws the still on it through fal. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Can it edit a still I already have?",
        a: "Yes. Send the still back as a reference with a line saying what to change and Seedream's edit endpoint takes it, up to eight references at once. Each pass lands on the wall as its own still.",
      },
      {
        q: "What frames can it draw?",
        a: "Ten frames from 1:1 to 21:9, each about one megapixel and at or above the 960 by 960 size the model accepts.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["flux-image-generator", "nano-banana-image-generator", "ideogram-image-generator"],
  finalCta: {
    eyebrow: "Your first still",
    title: "Draw your first still on Seedream.",
    body: "One line, your photos, a frame, the credits on the picker.",
  },
};

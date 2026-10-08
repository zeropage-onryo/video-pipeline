// The Seedream page (2026-10-05; the 4.5 page since 2026-10-08, Mike:
// "upgrade those models in my python with fal and update the landing
// pages"). What the studio does today: the composer draws on
// fal-ai/bytedance/seedream/v4.5/text-to-image at any of the ten frames,
// sent DOUBLED to about 4 megapixels because 4.5 refuses under ~3.7
// (src/fal.py IMAGE_MODELS["seedream4.5"], `scale: 2`), and sends reference
// photos to .../v4.5/edit as image_urls (up to 10). Priced per image,
// whatever the size. The model's own claims -- up to "4MP (2048x2048)",
// "architectural refinements for prompt interpretation", "up to 10 images
// per edit" for multi-source composition -- are fal's pages for the two
// endpoints, read 2026-10-08, quoted as ByteDance's.
//
// MEDIA: every still was drawn on Seedream 4.5 (on Higgsfield, 2026-10-08).
// The signature's three edits were each made by sending the draw back as
// the one reference with the line shown; the sneaker was fused from two
// references, the plain sneaker and the jacquard swatch.
import { ROSE } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_FAQS, imageModel, imageModelCards } from "../shared";
import type { MakePage, MakeTile } from "../pages";

const seedream = imageModel("seedream4.5");
const flux = imageModel("flux2-pro");
const nano = imageModel("nano-banana-pro");

const DIR = "/models/seedream-image-generator";

const EDITS: MakeTile[] = [
  { title: "The draw", tag: "", src: `${DIR}/draw.jpg`, aspect: "3:4" },
  {
    title: "Make it blue hour",
    tag: "",
    src: `${DIR}/edit-bluehour.jpg`,
    aspect: "3:4",
    prompt: "Keep the same woman, pose, plaza and framing; change the time to blue hour, the street lamps lit and the cobblestones wet.",
  },
  {
    title: "Red leather coat",
    tag: "",
    src: `${DIR}/edit-leather.jpg`,
    aspect: "3:4",
    prompt: "Keep the same woman, pose, plaza, light and framing; change the pale pink trench to deep red leather.",
  },
  {
    title: "Snow and an umbrella",
    tag: "",
    src: `${DIR}/edit-snow.jpg`,
    aspect: "3:4",
    prompt: "Keep the same woman, pose, plaza and framing; add a light snowfall and an open red umbrella in her hand.",
  },
];

const TILES: MakeTile[] = [
  { title: "A diner at night, every chrome stool", tag: "16:9", src: `${DIR}/diner.jpg`, aspect: "16:9", meta: "Rain on the glass, neon on the counter, the booths in their own light." },
  { title: "Glaze and sugar, overhead", tag: "4:3", src: `${DIR}/tart.jpg`, aspect: "4:3" },
  { title: "A scooter, an alley, a long shadow", tag: "3:4", src: `${DIR}/scooter.jpg`, aspect: "3:4" },
  { title: "Droplets on a petal", tag: "4:3", src: `${DIR}/petals.jpg`, aspect: "4:3" },
  { title: "Satin, worn", tag: "3:4", src: `${DIR}/pointe.jpg`, aspect: "3:4" },
];

export const SEEDREAM: MakePage = {
  slug: "seedream-image-generator",
  section: "models",
  modelIds: ["seedream4.5"],
  title: "Seedream 4.5 AI Image Generator",
  description:
    "Draw photographic stills on ByteDance's Seedream 4.5 at about 4 megapixels, then edit them in the same model: change the hour, the coat, the weather, and keep the person and the frame. Up to ten references fused into one still.",
  h1: "Seedream 4.5",
  menu: "Seedream Image Generator",
  subhead:
    "Draw a still at about 4 megapixels, then send it back with one line: blue hour, a red coat, snow. Seedream 4.5 changes that and keeps everything else where it was.",
  cta: {
    label: "Draw a still",
    spark: "A photographic still on Seedream 4.5: [subject] in [place], natural light, 3:4, then one edit: [what to change].",
    secondary: { label: "See the edits", href: "#edit" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: ROSE,
  layout: {
    hero: "stack",
    order: ["signature", "wall", "overview", "features", "models", "howTo", "faq", "related", "final"],
    features: "grid",
  },
  heroMedia: [
    { title: "Skin, gloss, a pearl", tag: "About 4 megapixels", src: `${DIR}/beauty.jpg`, aspect: "3:4" },
    { title: "A flamingo and its reflection", tag: "Seedream 4.5", src: `${DIR}/flamingo.jpg`, aspect: "3:4" },
    { title: "Pink stucco, one lemon tree", tag: "Seedream 4.5", src: `${DIR}/building.jpg`, aspect: "3:4" },
  ],
  signature: "edit-loop",
  signatureFrames: EDITS,
  overview: {
    items: [
      {
        eyebrow: "Two references, one still",
        title: "Hand it a shoe and a fabric. Get the shoe in the fabric.",
        body: "Seedream 4.5's edit takes up to ten reference images and composes them into one still. Here it was handed a plain white sneaker and a rose jacquard swatch, and asked for the first made of the second: the sole, the laces and the shape kept, the weave on the upper.",
        points: ["Drag the divider: the reference on the left, the fused still on the right.", "References go in the composer; the studio sends up to ten to Seedream 4.5."],
        media: { title: "The sneaker in the jacquard", tag: "", src: `${DIR}/fusion.jpg`, aspect: "1:1" },
        compare: {
          media: { title: "The plain sneaker, reference 1", tag: "", src: `${DIR}/ref-sneaker.jpg` },
          label: "Reference",
          mediaLabel: "Fused",
        },
      },
    ],
  },
  wall: {
    title: "Stills Seedream Draws",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
    layout: "editorial",
  },
  features: {
    title: "Seedream in the Studio",
    items: [
      {
        icon: "edit",
        title: "Generate and edit in one model",
        body: "Send a still back as a reference with one line and Seedream 4.5 edits it rather than drawing again: the light, the coat or the weather change, the person and the frame stay.",
      },
      {
        icon: "references",
        title: "Up to ten references",
        body: "Drop reference photos into the composer and they go to Seedream 4.5's edit endpoint with the prompt, up to ten, composed into one still.",
      },
      {
        icon: "frame",
        title: "About 4 megapixels, any of ten frames",
        body: "1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9 or 21:9, sent at about four megapixels: 2048 by 2048 for a square, 1824 by 2272 at 4:5.",
      },
      {
        icon: "price",
        title: "One price a still",
        body: "Seedream is priced per image, not per megapixel, so four megapixels cost what one would. The credits per still show in the picker before you send.",
      },
      {
        icon: "model",
        title: "Brief it like a photographer",
        body: "ByteDance describes 4.5 as refined for prompt interpretation. Write the light, the lens and the place the way you would brief a shoot.",
      },
      {
        icon: "guide",
        title: "Talk it through or just ask",
        body: "The composer's brain answers when you are bouncing ideas and draws when you ask for the still, writing the prompt as the work.",
      },
      {
        icon: "assets",
        title: "Every pass on the wall",
        body: "The draw and each edit land on your Assets wall as their own stills, with their prompts, to compare, star, sort and download.",
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
    title: "How to draw and edit on Seedream",
    items: [
      {
        title: "Draw the still",
        body: "Sign in, switch the composer to Image, pick Seedream 4.5 with its credits per still beside it, choose a frame and write one line. Add reference photos if it should match them.",
      },
      {
        title: "Send it back with one change",
        body: "Attach the still as a reference and write only what changes: the hour, the coat, the weather. Seedream edits it and keeps the rest.",
      },
      {
        title: "Keep the take you want",
        body: "Every pass lands on your Assets wall. Star the one you want, download it, or press Make element and shoot it.",
      },
    ],
  },
  faq: {
    title: "FAQs about Seedream",
    items: [
      {
        q: "What is the Seedream image generator?",
        a: "Seedream 4.5 is ByteDance's image model for drawing and editing in one. In this studio you write one line, attach reference photos if you want, pick a frame, and the composer draws the still on it through fal at about four megapixels. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Can it edit a still I already have?",
        a: "Yes. Send the still back as a reference with a line saying what to change and Seedream 4.5's edit endpoint takes it, with up to ten references at once. Each pass lands on the wall as its own still, so the draw is never overwritten.",
      },
      {
        q: "What size are the stills?",
        a: "About four megapixels in every frame: 2048 by 2048 square, 1824 by 2272 at 4:5, 3072 by 1312 at 21:9. Seedream 4.5 does not draw below roughly 3.7 megapixels, so the studio sends each frame at that size.",
      },
      {
        q: "What happened to Seedream 4.0?",
        a: "The picker draws on 4.5 now, at four times the pixels for one price a still. Stills drawn on 4.0 stay on your wall as they were.",
      },
      {
        q: "Were the stills on this page made on Seedream 4.5?",
        a: "Yes, every one. The three edits were made by sending the first draw back with the line shown beside each, and the fabric sneaker from two references.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["nano-banana-image-generator", "flux-image-generator", "ideogram-image-generator"],
  finalCta: {
    eyebrow: "Your first edit",
    title: "Draw it once. Change one thing.",
    body: "One line, a frame, then one line more. The credits on the picker each time.",
  },
};

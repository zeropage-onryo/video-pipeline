// The Kling page (2026-10-05). What renders today is Kling 3 Turbo Pro
// through fal (src/fal.py VIDEO_MODELS): 3 to 15 s a clip, 1080p only (the
// endpoint takes no resolution field, one flat rate), image-to-video off
// the shot's keyframe, on Creator and up. fal's page for the model
// (fal-ai/kling-video/v3/turbo/pro, read 2026-10-05) describes "high
// quality 1080p videos ... with improved lipsync and multishot generation";
// the catalog bands it "Cinematic motion, strong on people." Kling's own
// multi-shot storyboarding is the model's, not the Queue's -- here one shot
// is one clip -- so the page says "people" and "motion", not storyboards.
// TODO(media): the wall's eight tiles are plates until Kling renders
// from the studio replace them.
import { ROSE } from "../theme";
import { COMMERCIAL_FAQ, MODELS_TITLE, PLAN_FOR, REFERENCES_FAQ, model, modelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const kling = model("kling3-turbo-pro");
const seedance = model("seedance2");
const veo = model("veo3.1");

const TILES = plateTiles([
  ["A turn to camera", "People", "#fdf2f8", "#f9a8d4", "#be185d"],
  ["A laugh", "People", "#fff1f2", "#fda4af", "#9f1239"],
  ["Walking through", "People", "#fdf4ff", "#e879f9", "#86198f"],
  ["Hands at work", "People", "#fce7f3", "#f472b6", "#831843"],
  ["Two in frame", "People", "#ffe4e6", "#fb7185", "#881337"],
  ["A look back", "People", "#fae8ff", "#d946ef", "#701a75"],
  ["Night street", "Cinematic", "#500724", "#831843", "#f9a8d4"],
  ["Slow tracking", "Cinematic", "#4a044e", "#86198f", "#f0abfc"],
]);

export const KLING: MakePage = {
  slug: "kling-video-generator",
  section: "models",
  modelIds: ["kling3-turbo-pro"],
  title: "Kling 3 AI Video Generator",
  description:
    "Write a scene, anchor every shot on your reference photos, and render it on Kling 3 Turbo Pro at 1080p, 3 to 15 seconds a clip. Cinematic motion, strong on people.",
  h1: "Kling Video Generator",
  menu: "Kling Video Generator",
  subhead:
    "Write a scene, anchor every shot on your reference photos, and render it on Kling 3 Turbo Pro at 1080p, 3 to 15 seconds a clip.",
  cta: {
    label: "Make a scene",
    spark: "A 15-second scene in three timed shots on one person: a turn to camera, hands at work, a look back. Render on Kling.",
    secondary: { label: "See the takes", href: "#takes" },
    startLabel: "Start a scene",
  },
  template: "spark",
  tone: "light",
  accent: ROSE,
  wall: {
    title: "Takes Kling Renders",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "Kling in the Studio",
    items: [
      {
        icon: "model",
        title: "Strong on people",
        body: "The catalog bands Kling 3 Turbo Pro as cinematic motion, strong on people. Save a person as an element and every shot written against them is held to the same frames.",
      },
      {
        icon: "frame",
        title: "1080p, one flat rate",
        body: "Every Kling clip renders at 1080p. The model takes no resolution choice, so the price on the card depends only on the length you pick.",
      },
      {
        icon: "clock",
        title: "3 to 15 seconds a shot",
        body: "Any whole number of seconds from 3 to 15. A shot's window renders at its own length, so a 4-second cut is a 4-second clip.",
      },
      {
        icon: "price",
        title: `On ${PLAN_FOR[kling.tier]}`,
        body: "The Queue shows the credits for the exact length before anything renders, and that number is what is charged.",
      },
      {
        icon: "references",
        title: "Image to video, from your photos",
        body: "Each shot renders image-to-video from a keyframe drawn from the references you attached, so the clip starts on your person, product or place.",
      },
      {
        icon: "keyframe",
        title: "Keyframe first",
        body: "Draw every shot's first frame before a clip is rendered, and redraw it in the Director until the face and the framing are right.",
      },
      {
        icon: "shots",
        title: "Timed shots",
        body: "A scene is written as timed shots, 4 to 30 seconds in all, and each shot renders as its own Kling clip.",
      },
      {
        icon: "export",
        title: "Export one MP4",
        body: "Assemble the clips in shot order into one MP4, loudness-normalised, with an optional music bed under them.",
      },
      {
        icon: "assets",
        title: "Everything on one wall",
        body: "Every render lands on your Assets wall with its model and prompt, to view, star, sort and download.",
      },
    ],
  },
  models: { title: MODELS_TITLE, items: modelCards([kling, seedance, veo]) },
  howTo: {
    title: "How to render on Kling",
    items: [
      {
        title: "Write the scene",
        body: "Sign in, drop photos of the person into the composer or pick a saved element, and write one line about the scene. It comes back as timed shots, each with its own prompt.",
      },
      {
        title: "Check each keyframe",
        body: "Pick the scene on the board and draw its keyframes. Open any shot in the Director to edit the prompt, swap a reference and redraw.",
      },
      {
        title: "Approve on Kling",
        body: "In the Queue, choose Kling 3 Turbo Pro and the length for each shot, with the price on the card, and approve. Export joins the clips into one MP4.",
      },
    ],
  },
  faq: {
    title: "FAQs about Kling",
    items: [
      {
        q: "What is the Kling video generator?",
        a: "Kling 3 Turbo Pro is Kuaishou's video model. In this studio you write a scene as timed shots, each shot's first frame is drawn from your reference photos, and each shot renders as its own Kling clip at 1080p, image-to-video, at the length you pick in the Queue. The clips assemble into one MP4.",
      },
      {
        q: "How long can a Kling clip be?",
        a: "Any whole number of seconds from 3 to 15 a shot. A scene runs 4 to 30 seconds in all, written as timed shots.",
      },
      {
        q: "What resolution does it render at?",
        a: "1080p, always. Kling 3 Turbo Pro takes no resolution choice, so the price on the card depends only on the length.",
      },
      {
        q: "Does it keep the same person across shots?",
        a: "Each shot's keyframe is drawn from the same references and from the previous shot's still, so the scene holds together. Video models still vary between renders, so look at each keyframe before you approve. No pixel match is promised, and you need the consent of anyone whose likeness you upload.",
      },
      REFERENCES_FAQ,
      {
        q: "Which plan do I need?",
        a: `Kling 3 Turbo Pro is on ${PLAN_FOR[kling.tier]}, with the credits for a clip shown in the Queue before you approve it.`,
        link: { href: "/pricing", label: "Compare plans" },
      },
      COMMERCIAL_FAQ,
    ],
  },
  related: ["seedance-video-generator", "veo-video-generator", "ltx-video-generator"],
  finalCta: {
    eyebrow: "Your first scene",
    title: "Render your first scene on Kling.",
    body: "Write it, see every keyframe, see the price, approve.",
  },
};

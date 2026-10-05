// The LTX page (2026-10-05, "do up to 5 with what I'm using"). What
// renders today is LTX 2.3 through fal (src/fal.py VIDEO_MODELS): 6, 8 or
// 10 s a clip (an enum, fitted UP), 1080p / 1440p / 2160p, image-to-video
// off the shot's keyframe, on every plan. Model facts beyond the studio
// (open weights under Apache 2.0, a 22B diffusion transformer, native
// audio in the model) come from fal.ai/models/fal-ai/ltx-2.3 and
// Lightricks' release notes, read 2026-10-05, and are stated as the
// model's, never as something the Queue exposes. TODO(media): the wall's
// eight tiles are plates until LTX renders from the studio replace them.
import { MODELS } from "@/lib/catalog";
import { EMERALD } from "../theme";
import { COMMERCIAL_FAQ, MODELS_TITLE, PLAN_FOR, REFERENCES_FAQ, model, modelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const ltx = model("ltx2.3");
const wan = model("wan3");
const kling = model("kling3-turbo-pro");

// true only while the catalog says so: the lowest credits per second of
// any model in the Queue
const cheapestPerSecond = MODELS.every((m) => m.credits / m.seconds >= ltx.credits / ltx.seconds);

const TILES = plateTiles([
  ["Wide, 1080p", "Shot 1", "#ecfdf5", "#6ee7b7", "#047857"],
  ["Detail, 2160p", "Shot 2", "#f0fdfa", "#5eead4", "#115e59"],
  ["Slow dolly", "Shot 3", "#ecfeff", "#67e8f9", "#0e7490"],
  ["Handheld", "Shot 4", "#f7fee7", "#bef264", "#3f6212"],
  ["Overhead", "Shot 5", "#d1fae5", "#34d399", "#064e3b"],
  ["Rack focus", "Shot 6", "#ccfbf1", "#2dd4bf", "#134e4a"],
  ["Dusk", "Shot 7", "#fef3c7", "#fcd34d", "#047857"],
  ["Night", "Shot 8", "#064e3b", "#065f46", "#34d399"],
]);

export const LTX: MakePage = {
  slug: "ltx-video-generator",
  section: "models",
  modelIds: ["ltx2.3"],
  title: "LTX 2.3 AI Video Generator",
  description:
    "Write a scene, anchor every shot on your reference photos, and render it on LTX 2.3 at 1080p, 1440p or 2160p, 6 to 10 seconds a clip, on every plan.",
  h1: "LTX Video Generator",
  menu: "LTX Video Generator",
  subhead:
    "Write a scene, anchor every shot on your reference photos, and render it on LTX 2.3 at up to 2160p, 6 to 10 seconds a clip, on every plan.",
  cta: {
    label: "Make a scene",
    spark: "A 10-second scene in two timed shots: a wide reveal, then a close detail. Render on LTX at 1080p.",
    secondary: { label: "See the frames", href: "#frames" },
    startLabel: "Start a scene",
  },
  template: "spark",
  tone: "light",
  accent: EMERALD,
  wall: {
    title: "Shots LTX Renders",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "LTX in the Studio",
    items: [
      {
        icon: "frame",
        title: "1080p to 2160p",
        body: "Pick the frame per shot in the Queue: 1080p, 1440p or 2160p. The price on the card follows the frame you picked.",
      },
      {
        icon: "clock",
        title: "6, 8 or 10 seconds",
        body: "LTX renders three lengths. A shot's window is fitted up to the nearest one, so a 7-second window renders as 8 and is trimmed in the edit.",
      },
      {
        icon: "price",
        title: cheapestPerSecond ? "The lowest price per second" : "Priced before you approve",
        body: cheapestPerSecond
          ? `The lowest credits per second of any model in the Queue, on ${PLAN_FOR[ltx.tier]}. Start scenes here and move a shot to a dearer model only when it earns it.`
          : `On ${PLAN_FOR[ltx.tier]}. The Queue shows the credits for the exact frame and length before anything renders.`,
      },
      {
        icon: "open",
        title: "Open weights",
        body: "LTX 2.3 is Lightricks' open model, released under the Apache 2.0 licence. The studio renders it through fal, so there is nothing to install or host.",
      },
      {
        icon: "references",
        title: "Image to video, from your photos",
        body: "Each shot renders image-to-video from a keyframe drawn from the references you attached, so the clip starts on your product, person or place.",
      },
      {
        icon: "keyframe",
        title: "Keyframe first",
        body: "Draw every shot's first frame before a clip is rendered, and redraw it in the Director until it is right.",
      },
      {
        icon: "shots",
        title: "Timed shots",
        body: "A scene is written as timed shots, 4 to 30 seconds in all, and each shot renders as its own LTX clip.",
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
  models: { title: MODELS_TITLE, items: modelCards([ltx, wan, kling]) },
  howTo: {
    title: "How to render on LTX",
    items: [
      {
        title: "Write the scene",
        body: "Sign in, drop your reference photos into the composer, and write one line about the scene. It comes back as timed shots, each with its own prompt.",
      },
      {
        title: "Check each keyframe",
        body: "Pick the scene on the board and draw its keyframes. Open any shot in the Director to edit the prompt, swap a reference and redraw.",
      },
      {
        title: "Approve on LTX",
        body: "In the Queue, choose LTX 2.3, the frame and the length for each shot, with the price on the card, and approve. Export joins the clips into one MP4.",
      },
    ],
  },
  faq: {
    title: "FAQs about LTX",
    items: [
      {
        q: "What is the LTX video generator?",
        a: "LTX 2.3 is Lightricks' open-weight video model. In this studio you write a scene as timed shots, each shot's first frame is drawn from your reference photos, and each shot renders as its own LTX clip, image-to-video, at the frame and length you pick in the Queue. The clips assemble into one MP4.",
      },
      {
        q: "What resolutions does it render at?",
        a: "1080p, 1440p or 2160p, chosen per shot in the Queue. The price on the card follows the frame.",
      },
      {
        q: "How long can an LTX clip be?",
        a: "6, 8 or 10 seconds a shot. A scene runs 4 to 30 seconds in all, written as timed shots, and each window is fitted up to the nearest length LTX renders.",
      },
      REFERENCES_FAQ,
      {
        q: "Which plan do I need?",
        a: `LTX 2.3 is on ${PLAN_FOR[ltx.tier]}, with the credits for a clip shown in the Queue before you approve it.`,
        link: { href: "/pricing", label: "Compare plans" },
      },
      {
        q: "Is LTX open source?",
        a: "Lightricks publishes LTX 2.3's weights under the Apache 2.0 licence. The studio renders it through fal rather than hosting the weights, so you get the model with nothing to install.",
        link: { href: "/models", label: "See every model" },
      },
      COMMERCIAL_FAQ,
    ],
  },
  related: ["wan-video-generator", "kling-video-generator", "seedance-video-generator"],
  finalCta: {
    eyebrow: "Your first scene",
    title: "Render your first scene on LTX.",
    body: "Write it, see every keyframe, see the price, approve.",
  },
};

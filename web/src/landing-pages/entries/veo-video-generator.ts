// The Veo page (2026-10-05). What renders today is Veo 3.1 through fal
// (src/fal.py VIDEO_MODELS): 4, 6 or 8 s a clip (an enum, fitted UP),
// 720p or 1080p, WITH audio (the endpoint's default, and the rate the
// studio prices), a negative prompt on the wire, on the Studio plan only.
// Google's own page (deepmind.google/models/veo, read 2026-10-05) claims
// native audio with dialogue, real-world physics and improved prompt
// adherence; those are quoted as Google's. Veo's reference images, first/
// last frame, extend and 4K are the model's and NOT in the Queue, so
// nothing here names them. TODO(media): the wall's eight tiles are
// plates until Veo renders from the studio replace them.
import { BLUE } from "../theme";
import { COMMERCIAL_FAQ, MODELS_TITLE, PLAN_FOR, REFERENCES_FAQ, model, modelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const veo = model("veo3.1");
const kling = model("kling3-turbo-pro");
const seedance = model("seedance2");

const TILES = plateTiles([
  ["A line of dialogue", "Sound", "#eff6ff", "#93c5fd", "#1d4ed8"],
  ["Rain", "Sound", "#f0f9ff", "#7dd3fc", "#1e40af"],
  ["Footsteps", "Sound", "#eef2ff", "#a5b4fc", "#1e3a8a"],
  ["A door", "Sound", "#ecfeff", "#67e8f9", "#1d4ed8"],
  ["Glass set down", "Sound", "#dbeafe", "#60a5fa", "#172554"],
  ["Wind", "Sound", "#e0f2fe", "#38bdf8", "#1e3a8a"],
  ["Night traffic", "Sound", "#172554", "#1e3a8a", "#93c5fd"],
  ["A crowd", "Sound", "#1e3a8a", "#1d4ed8", "#bfdbfe"],
]);

export const VEO: MakePage = {
  slug: "veo-video-generator",
  section: "models",
  modelIds: ["veo3.1"],
  title: "Veo 3.1 AI Video Generator",
  description:
    "Write a scene, anchor every shot on your reference photos, and render it on Google's Veo 3.1 with sound, 4 to 8 seconds a clip, at 720p or 1080p, on the Studio plan.",
  h1: "Veo Video Generator",
  menu: "Veo Video Generator",
  subhead:
    "Write a scene, anchor every shot on your reference photos, and render it on Veo 3.1 with sound, 4 to 8 seconds a clip, at 720p or 1080p.",
  cta: {
    label: "Make a scene",
    spark: "An 8-second single take with sound: rain on a window, a kettle, one line of dialogue. Render on Veo.",
    secondary: { label: "Hear the shot", href: "#sound" },
    startLabel: "Start a scene",
  },
  template: "spark",
  tone: "light",
  accent: BLUE,
  wall: {
    title: "Shots Veo Renders",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "Veo in the Studio",
    items: [
      {
        icon: "sound",
        title: "Sound in the clip",
        body: "Every Veo clip the Queue renders comes back with its audio, which is the rate the card prices. Google describes Veo 3.1 as generating sound effects, ambience and dialogue natively.",
      },
      {
        icon: "clock",
        title: "4, 6 or 8 seconds",
        body: "Veo renders three lengths. A shot's window is fitted up to the nearest one, so a 5-second window renders as 6 and is trimmed in the edit.",
      },
      {
        icon: "frame",
        title: "720p or 1080p",
        body: "Pick the frame per shot in the Queue. Both frames price the same on Veo, so the card's number follows the length.",
      },
      {
        icon: "price",
        title: `On ${PLAN_FOR[veo.tier]}`,
        body: "The most expensive clip in the studio, and the Queue shows its credits before anything renders. Start the scene on a cheaper model and move the one shot that needs Veo.",
      },
      {
        icon: "model",
        title: "Google DeepMind's model",
        body: "Google claims real-world physics and improved prompt adherence for Veo 3.1. The studio renders it through fal, so there is no second account and no second bill.",
      },
      {
        icon: "references",
        title: "Image to video, from your photos",
        body: "Each shot renders image-to-video from a keyframe drawn from the references you attached, so the clip starts on your product, person or place.",
      },
      {
        icon: "keyframe",
        title: "Keyframe first",
        body: "Draw every shot's first frame before a clip is rendered, and redraw it in the Director until it is right. On the dearest model, this is where the credits are saved.",
      },
      {
        icon: "export",
        title: "Export one MP4",
        body: "Assemble the clips in shot order into one MP4, loudness-normalised to -14 LUFS, Veo's own sound under an optional music bed.",
      },
      {
        icon: "assets",
        title: "Everything on one wall",
        body: "Every render lands on your Assets wall with its model and prompt, to view, star, sort and download.",
      },
    ],
  },
  models: { title: MODELS_TITLE, items: modelCards([veo, kling, seedance]) },
  howTo: {
    title: "How to render on Veo",
    items: [
      {
        title: "Write the scene",
        body: "Sign in, drop your reference photos into the composer, and write one line about the scene, sound included. It comes back as timed shots, each with its own prompt.",
      },
      {
        title: "Check each keyframe",
        body: "Pick the scene on the board and draw its keyframes. Open any shot in the Director to edit the prompt, swap a reference and redraw.",
      },
      {
        title: "Approve on Veo",
        body: "In the Queue, choose Veo 3.1, the frame and the length for each shot, with the price on the card, and approve. Export joins the clips into one MP4 with their sound.",
      },
    ],
  },
  faq: {
    title: "FAQs about Veo",
    items: [
      {
        q: "What is the Veo video generator?",
        a: "Veo 3.1 is Google DeepMind's video model. In this studio you write a scene as timed shots, each shot's first frame is drawn from your reference photos, and each shot renders as its own Veo clip with sound, image-to-video, at the frame and length you pick in the Queue. The clips assemble into one MP4.",
      },
      {
        q: "Does the clip have sound?",
        a: "Yes. The Queue renders Veo with audio on, which is the rate it prices. Google describes Veo 3.1 as generating sound effects, ambience and dialogue natively. Export keeps that sound and normalises the whole cut to -14 LUFS.",
      },
      {
        q: "How long can a Veo clip be?",
        a: "4, 6 or 8 seconds a shot. A scene runs 4 to 30 seconds in all, written as timed shots, and each window is fitted up to the nearest length Veo renders.",
      },
      {
        q: "What resolutions does it render at?",
        a: "720p or 1080p, chosen per shot in the Queue.",
      },
      REFERENCES_FAQ,
      {
        q: "Which plan do I need?",
        a: `Veo 3.1 is on ${PLAN_FOR[veo.tier]} only, the premium band, with the credits for a clip shown in the Queue before you approve it.`,
        link: { href: "/pricing", label: "Compare plans" },
      },
      COMMERCIAL_FAQ,
    ],
  },
  related: ["kling-video-generator", "seedance-video-generator", "ltx-video-generator"],
  finalCta: {
    eyebrow: "Your first scene",
    title: "Render your first scene on Veo.",
    body: "Write it, see every keyframe, see the price, approve.",
  },
};

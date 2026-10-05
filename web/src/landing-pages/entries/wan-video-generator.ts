// The Wan page (2026-10-05). What renders today is Wan 3.0 through fal
// (src/fal.py VIDEO_MODELS, the `alibaba/` namespace): 2 to 10 s a clip,
// 480p / 720p / 1080p, image-to-video off the shot's keyframe
// (start_image_url), on every plan. The model's own claims -- "enhanced
// motion smoothness, superior scene fidelity, and greater visual
// coherence" -- are fal's page for alibaba/wan-3.0, read 2026-10-05, and
// are quoted as the model's. Wan's native audio, first-and-last-frame
// control and its 30-second ceiling exist in the model and are NOT in the
// Queue, so nothing here names them. TODO(media): the wall's eight tiles
// are plates until Wan renders from the studio replace them.
import { AMBER } from "../theme";
import { COMMERCIAL_FAQ, MODELS_TITLE, PLAN_FOR, REFERENCES_FAQ, model, modelCards, plateTiles } from "../shared";
import type { MakePage } from "../pages";

const wan = model("wan3");
const ltx = model("ltx2.3");
const seedance = model("seedance2");

const TILES = plateTiles([
  ["Fabric in wind", "Motion", "#fffbeb", "#fcd34d", "#b45309"],
  ["Water", "Motion", "#fff7ed", "#fdba74", "#9a3412"],
  ["A walk", "Motion", "#fef3c7", "#f59e0b", "#78350f"],
  ["Smoke", "Motion", "#fefce8", "#fde047", "#a16207"],
  ["Pouring", "Motion", "#ffedd5", "#fb923c", "#7c2d12"],
  ["Hair", "Motion", "#fef2f2", "#fca5a5", "#b45309"],
  ["Traffic at dusk", "Motion", "#431407", "#9a3412", "#fdba74"],
  ["Rain on glass", "Motion", "#78350f", "#b45309", "#fde68a"],
]);

export const WAN: MakePage = {
  slug: "wan-video-generator",
  section: "models",
  modelIds: ["wan3"],
  title: "Wan 3.0 AI Video Generator",
  description:
    "Write a scene, anchor every shot on your reference photos, and render it on Alibaba's Wan 3.0, 2 to 10 seconds a clip, up to 1080p, on every plan.",
  h1: "Wan Video Generator",
  menu: "Wan Video Generator",
  subhead:
    "Write a scene, anchor every shot on your reference photos, and render it on Wan 3.0, 2 to 10 seconds a clip, up to 1080p, on every plan.",
  cta: {
    label: "Make a scene",
    spark: "An 8-second scene in two timed shots with real motion: fabric in wind, then water poured into glass. Render on Wan.",
    secondary: { label: "See the lengths", href: "#lengths" },
    startLabel: "Start a scene",
  },
  template: "spark",
  tone: "light",
  accent: AMBER,
  wall: {
    title: "Motion Wan Renders",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "Wan in the Studio",
    items: [
      {
        icon: "model",
        title: "Open-weight realism",
        body: "Wan 3.0 is Alibaba's open video model. fal describes it as delivering enhanced motion smoothness, superior scene fidelity and greater visual coherence; the studio renders it through fal.",
      },
      {
        icon: "clock",
        title: "2 to 10 seconds a shot",
        body: "Any whole number of seconds from 2 to 10. A shot's window renders at its own length, so a 3-second cut is a 3-second clip.",
      },
      {
        icon: "frame",
        title: "480p, 720p or 1080p",
        body: "Pick the frame per shot in the Queue. 720p is the default; 1080p when the shot is worth it. The price on the card follows the frame.",
      },
      {
        icon: "price",
        title: "On every plan",
        body: `Wan 3.0 is on ${PLAN_FOR[wan.tier]}. The Queue shows the credits for the exact frame and length before anything renders.`,
      },
      {
        icon: "references",
        title: "Image to video, from your photos",
        body: "Each shot renders image-to-video from a keyframe drawn from the references you attached, so the motion starts on your product, person or place.",
      },
      {
        icon: "keyframe",
        title: "Keyframe first",
        body: "Draw every shot's first frame before a clip is rendered, and redraw it in the Director until it is right.",
      },
      {
        icon: "shots",
        title: "Timed shots",
        body: "A scene is written as timed shots, 4 to 30 seconds in all, and each shot renders as its own Wan clip.",
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
  models: { title: MODELS_TITLE, items: modelCards([wan, ltx, seedance]) },
  howTo: {
    title: "How to render on Wan",
    items: [
      {
        title: "Write the scene",
        body: "Sign in, drop your reference photos into the composer, and write one line about the motion you want. It comes back as timed shots, each with its own prompt.",
      },
      {
        title: "Check each keyframe",
        body: "Pick the scene on the board and draw its keyframes. Open any shot in the Director to edit the prompt, swap a reference and redraw.",
      },
      {
        title: "Approve on Wan",
        body: "In the Queue, choose Wan 3.0, the frame and the length for each shot, with the price on the card, and approve. Export joins the clips into one MP4.",
      },
    ],
  },
  faq: {
    title: "FAQs about Wan",
    items: [
      {
        q: "What is the Wan video generator?",
        a: "Wan 3.0 is Alibaba's open-weight video model. In this studio you write a scene as timed shots, each shot's first frame is drawn from your reference photos, and each shot renders as its own Wan clip, image-to-video, at the frame and length you pick in the Queue. The clips assemble into one MP4.",
      },
      {
        q: "How long can a Wan clip be?",
        a: "Any whole number of seconds from 2 to 10 a shot. A scene runs 4 to 30 seconds in all, written as timed shots.",
      },
      {
        q: "What resolutions does it render at?",
        a: "480p, 720p or 1080p, chosen per shot in the Queue. The price on the card follows the frame.",
      },
      REFERENCES_FAQ,
      {
        q: "Which plan do I need?",
        a: `Wan 3.0 is on ${PLAN_FOR[wan.tier]}, with the credits for a clip shown in the Queue before you approve it.`,
        link: { href: "/pricing", label: "Compare plans" },
      },
      {
        q: "What is Wan good at?",
        a: "Motion. fal's page for the model describes enhanced motion smoothness, superior scene fidelity and greater visual coherence, and the catalog bands it as open-weight realism up to 1080p. Write the shot's action plainly and check the keyframe before you approve.",
        link: { href: "/models", label: "See every model" },
      },
      COMMERCIAL_FAQ,
    ],
  },
  related: ["ltx-video-generator", "seedance-video-generator", "kling-video-generator"],
  finalCta: {
    eyebrow: "Your first scene",
    title: "Render your first scene on Wan.",
    body: "Write it, see every keyframe, see the price, approve.",
  },
};

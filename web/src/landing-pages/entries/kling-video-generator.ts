// The Kling page (2026-10-05; media, copy and layout 2026-10-08). What
// renders today is Kling 3 Turbo Pro through fal (src/fal.py VIDEO_MODELS):
// any whole number of seconds from 3 to 15 a clip, 1080p only (the endpoint
// takes no resolution field, one flat rate), image-to-video off the shot's
// keyframe, on Creator and up. fal's page for the model
// (fal-ai/kling-video/v3/turbo/pro, read 2026-10-05) describes "high
// quality 1080p videos ... with improved lipsync and multishot generation";
// the catalog bands it "Cinematic motion, strong on people." Kling's own
// multi-shot storyboarding is the model's, not the Queue's -- here one shot
// is one clip -- so the page says "people" and "motion", not storyboards.
//
// MEDIA: four clips rendered on Kling 3.0 Turbo at 1080p (on Higgsfield,
// 5 s, 9:16, 2026-10-08) -- the studio's Kling 3 Turbo Pro is that model at
// its 1080p tier. They came back with sound and the page plays it (Mike:
// "use the sound on the page. We will support audio in the future"); the
// copy states sound as the model's, never as a Queue setting.
import { COMMERCIAL_FAQ, MODELS_TITLE, PLAN_FOR, REFERENCES_FAQ, model, modelCards } from "../shared";
import { FUCHSIA } from "../theme";
import type { MakePage, MakeTile } from "../pages";

const kling = model("kling3-turbo-pro");
const seedance = model("seedance2.5");
const wan = model("wan3");

const DIR = "/models/kling-video-generator";
const clip = (name: string, title: string, meta: string): MakeTile => ({
  title,
  tag: "",
  meta,
  video: `${DIR}/${name}.mp4`,
  src: `${DIR}/${name}.jpg`,
  aspect: "9:16",
});

export const KLING: MakePage = {
  slug: "kling-video-generator",
  section: "models",
  modelIds: ["kling3-turbo-pro"],
  title: "Kling 3 Turbo Pro AI Video Generator",
  description:
    "Render people on Kling 3 Turbo Pro at 1080p: a laugh that turns to camera, a dancer's hits, two hands on one fishing rod. Any length from 3 to 15 seconds a shot, vertical or wide, every shot drawn from your own reference photos.",
  h1: "Kling 3 Turbo Pro",
  menu: "Kling Video Generator",
  subhead:
    "People who move like people, at 1080p: faces that turn and laugh, hands that work, bodies that dance. Any length from 3 to 15 seconds a shot, vertical for the feed.",
  cta: {
    label: "Make a scene",
    spark: "A vertical 10-second scene of one person in two timed shots: a wide of them moving, then a close-up as they turn to camera. Render on Kling 3 Turbo Pro.",
    secondary: { label: "Watch the takes", href: "#examples" },
    startLabel: "Start a scene",
  },
  template: "spark",
  tone: "light",
  accent: FUCHSIA,
  layout: {
    hero: "phone",
    order: ["wall", "features", "howTo", "models", "faq", "related", "final"],
    features: "split",
  },
  heroMedia: [
    clip("rooftop", "A laugh that turns to camera, on a windy rooftop", "Kling 3 Turbo Pro · 1080p · 9:16"),
  ],
  wall: {
    title: "People Kling Renders",
    tiles: [
      clip("dancer", "Popping and locking under a bridge", "Sharp hits and a body wave in one 5-second take, low and handheld."),
      clip("dock", "Two hands on one fishing rod", "An old man guides a girl's cast at dawn; her grin, his nod."),
      clip("boxer", "Shadowboxing in one shaft of light", "Jab, jab, hook, a slip; the sweat catches the beam."),
    ],
    explore: { label: "See the features", href: "#features" },
    layout: "reels",
  },
  features: {
    title: "Kling in the Studio",
    items: [
      {
        icon: "model",
        title: "Strong on people",
        body: "The catalog bands Kling 3 Turbo Pro as cinematic motion, strong on people: faces that turn, hands that hold things, bodies that move with weight.",
      },
      {
        icon: "frame",
        title: "1080p, always",
        body: "Kling 3 Turbo Pro renders every clip at 1080p at one flat rate, so the price on the card depends only on the length.",
      },
      {
        icon: "clock",
        title: "Any length from 3 to 15 seconds",
        body: "Any whole number of seconds from 3 to 15 a shot, rendered at exactly that length, so a timed window gets the clip it asked for.",
      },
      {
        icon: "sound",
        title: "Its own sound",
        body: "Kling renders sound with the picture, and every clip on this page plays the sound it came back with; press Sound on.",
      },
      {
        icon: "price",
        title: "Priced before you approve",
        body: `${kling.credits} credits for a ${kling.seconds}-second ${kling.frame} clip, on ${PLAN_FOR[kling.tier]}, shown on the card before anything renders.`,
      },
      {
        icon: "references",
        title: "The person you uploaded",
        body: "Each shot's keyframe is drawn from the references attached to the scene and from the previous shot's still, and Kling animates that frame.",
      },
      {
        icon: "keyframe",
        title: "Keyframe first",
        body: "Draw every shot's first frame in the Queue and look at the face before a clip is made.",
      },
      {
        icon: "shots",
        title: "Timed shots",
        body: "A scene is written as timed shots, 4 to 30 seconds in all, and each shot renders as its own Kling clip, in order.",
      },
      {
        icon: "export",
        title: "Export one MP4",
        body: "The editor assembles the clips in shot order into one MP4, loudness-normalised, ready to post vertical.",
      },
    ],
  },
  models: {
    title: MODELS_TITLE,
    items: modelCards([kling, seedance, wan], (m) => `A vertical 10-second scene of one person in two timed shots. Render on ${m.name}.`),
  },
  howTo: {
    title: "How to render on Kling",
    items: [
      {
        title: "Upload the person",
        body: "Sign in, save the person as an element or drop their photos into Create, and write what they do. It comes back as timed shots.",
      },
      {
        title: "Check every face",
        body: "Send the scene to the Queue and draw each shot's keyframe there, so you see the face in every first frame before a clip is made.",
      },
      {
        title: "Approve on Kling",
        body: "Choose Kling 3 Turbo Pro, see the credits on the card, and approve. The editor joins the clips into one MP4.",
      },
    ],
  },
  faq: {
    title: "FAQs about Kling",
    items: [
      {
        q: "What is the Kling video generator?",
        a: "Kling 3 Turbo Pro is Kuaishou's video model, strong on people. In this studio you write a scene as timed shots, each shot's first frame is drawn from your reference photos, and each shot renders as its own Kling clip at 1080p, image-to-video. The clips assemble into one MP4.",
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
      {
        q: "Were the clips on this page made on Kling?",
        a: "Yes, all four, on Kling 3.0 Turbo at 1080p, 5 seconds, vertical, with the sound Kling rendered for each.",
      },
      {
        q: "Which plan do I need?",
        a: `Kling 3 Turbo Pro is on ${PLAN_FOR[kling.tier]}, with the credits for a clip shown in the Queue before you approve it.`,
        link: { href: "/pricing", label: "Compare plans" },
      },
      REFERENCES_FAQ,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["seedance-video-generator", "veo-video-generator", "wan-video-generator", "ltx-video-generator"],
  finalCta: {
    eyebrow: "Your first scene",
    title: "Put your person in motion on Kling.",
    body: "Upload them, see every face, see the price, approve.",
  },
};

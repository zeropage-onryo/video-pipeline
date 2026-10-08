// The Wan page (2026-10-05; media, copy and layout 2026-10-08). What
// renders today is Wan 3.0 through fal (src/fal.py VIDEO_MODELS, the
// `alibaba/` namespace): any whole number of seconds from 2 to 10 a clip
// (no enum, so a 3-second window is a 3-second clip), 480p / 720p / 1080p,
// image-to-video off the shot's keyframe (start_image_url), on every plan.
// The model's own claims -- "enhanced motion smoothness, superior scene
// fidelity, and greater visual coherence" -- are fal's page for
// alibaba/wan-3.0, read 2026-10-05, quoted as the model's. Wan 3.0 renders
// native sound with the picture; the page plays it (Mike, 2026-10-08: "use
// the sound on the page. We will support audio in the future") and states
// it as the model's, never as a Queue setting.
//
// MEDIA: four clips rendered on Wan 3.0 itself (on Higgsfield, 720p, native
// audio on, 2026-10-08): the flamenco (5 s, 16:9), the retriever (10 s,
// 16:9, the length dial), the leaves and the balloons (5 s, 9:16). The
// length dial's beats were read off the retriever clip's frames: the leap
// at about 4.5 s, the splash at 6, the swim back from 8.
import { COMMERCIAL_FAQ, MODELS_TITLE, PLAN_FOR, REFERENCES_FAQ, model, modelCards } from "../shared";
import { ORANGE } from "../theme";
import type { MakePage, MakeTile } from "../pages";

const wan = model("wan3");
const ltx = model("ltx2.5-fast");
const kling = model("kling3-turbo-pro");

const DIR = "/models/wan-video-generator";
const clip = (name: string, title: string, aspect: string, tag = ""): MakeTile => ({
  title,
  tag,
  video: `${DIR}/${name}.mp4`,
  src: `${DIR}/${name}.jpg`,
  aspect,
});

export const WAN: MakePage = {
  slug: "wan-video-generator",
  section: "models",
  modelIds: ["wan3"],
  title: "Wan 3.0 AI Video Generator",
  description:
    "Render motion on Alibaba's Wan 3.0: a skirt in a full spin, a dog's leap and splash, leaves in a gust. Any length from 2 to 10 seconds a shot, 480p to 1080p, every shot anchored on your reference photos, on every plan.",
  h1: "Wan 3.0",
  menu: "Wan Video Generator",
  subhead:
    "Motion that holds together: cloth that spins, water that splashes, people who move like people. Any length from 2 to 10 seconds a shot, from your own reference photos.",
  cta: {
    label: "Make a scene",
    spark: "A 10-second scene of fast motion in two timed shots, with its sound: [the action], then a close detail. Render on Wan 3.0.",
    secondary: { label: "Pick a length", href: "#length" },
    startLabel: "Start a scene",
  },
  template: "spark",
  tone: "light",
  accent: ORANGE,
  layout: {
    hero: "split",
    order: ["signature", "overview", "features", "models", "howTo", "faq", "related", "final"],
    features: "list",
  },
  heroMedia: [clip("flamenco", "A flamenco spin, rendered on Wan 3.0", "16:9", "Wan 3.0 · 720p · sound")],
  signature: "length-dial",
  signatureFrames: [
    {
      ...clip("retriever", "A retriever off the end of a jetty, 10 s on Wan 3.0", "16:9"),
      meta: "2|the run along the jetty;5|the run and the leap;7|the leap and the splash;10|the whole take: the run, the leap, the splash and the swim back",
    },
  ],
  overview: {
    items: [
      {
        eyebrow: "Motion first",
        title: "A gust, a hat, a hundred leaves.",
        body: "fal's page for Wan 3.0 describes enhanced motion smoothness and greater visual coherence. Here a single line asked for a gust across a square and an old man catching his cap; every leaf moves on its own path and the hand finds the hat.",
        points: ["Vertical 9:16, 5 seconds, 720p.", "Write the action plainly: what moves, which way, what it hits."],
        media: clip("leaves", "Autumn leaves in a gust, an old man catches his cap", "9:16", "Wan 3.0 · with sound"),
        sound: true,
      },
      {
        eyebrow: "Scale and light",
        title: "Lift-off, with the burner roaring.",
        body: "The same model at the other end of the scale: a hot-air balloon lifting off a canyon floor at sunrise, the burner flaring inside the envelope, two more rising behind. Wan renders its own sound with the picture, so the burner roars when it flares.",
        media: clip("balloons", "Hot-air balloons lifting off a canyon at sunrise", "9:16", "Wan 3.0 · with sound"),
        sound: true,
      },
    ],
  },
  wall: {
    title: "Motion Wan Renders",
    tiles: [],
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "Wan in the Studio",
    items: [
      {
        icon: "clock",
        title: "Any length from 2 to 10 seconds",
        body: "Any whole number of seconds from 2 to 10. A shot's window renders at its own length, so a 3-second cut is a 3-second clip, not a longer one trimmed.",
      },
      {
        icon: "model",
        title: "Built for motion",
        body: "fal describes Wan 3.0 as delivering enhanced motion smoothness, superior scene fidelity and greater visual coherence: cloth, water, crowds, animals.",
      },
      {
        icon: "sound",
        title: "Its own sound",
        body: "Wan 3.0 renders native sound with the picture: the heel strikes, the splash, the burner. Every clip on this page plays the sound Wan made with it.",
      },
      {
        icon: "frame",
        title: "480p, 720p or 1080p",
        body: "720p is where the Queue starts; drop to 480p to draft a take, or go to 1080p when the shot is worth it. The price on the card follows the frame.",
      },
      {
        icon: "price",
        title: "On every plan",
        body: `Wan 3.0 is on ${PLAN_FOR[wan.tier]}: ${wan.credits} credits for a ${wan.seconds}-second ${wan.frame} clip, shown on the card before anything renders.`,
      },
      {
        icon: "references",
        title: "Image to video, from your photos",
        body: "Each shot renders image-to-video from a keyframe drawn from the references you attached, so the motion starts on your product, person or place.",
      },
      {
        icon: "keyframe",
        title: "Keyframe first",
        body: "Draw every shot's first frame in the Queue, priced on the button, before a clip is rendered.",
      },
      {
        icon: "shots",
        title: "Timed shots",
        body: "A scene is written as timed shots, 4 to 30 seconds in all, and each shot renders as its own Wan clip at exactly its length.",
      },
      {
        icon: "export",
        title: "Export one MP4",
        body: "The editor assembles the clips in shot order into one MP4, loudness-normalised, with an optional music bed under them.",
      },
    ],
  },
  models: { title: MODELS_TITLE, items: modelCards([wan, ltx, kling], (m) => `A 10-second scene of fast motion in two timed shots. Render on ${m.name}.`) },
  howTo: {
    title: "How to render on Wan",
    items: [
      {
        title: "Write the motion",
        body: "Sign in, drop your reference photos into Create, and write what moves and how. It comes back as timed shots, each with its own prompt and length.",
      },
      {
        title: "Send it to the Queue",
        body: "Send the scene to the Queue and draw each shot's keyframe there, so you see every first frame before a clip is made.",
      },
      {
        title: "Approve on Wan 3.0",
        body: "Choose Wan 3.0 and the frame, see the credits on the card, and approve. The editor joins the clips into one MP4.",
      },
    ],
  },
  faq: {
    title: "FAQs about Wan",
    items: [
      {
        q: "What is the Wan video generator?",
        a: "Wan 3.0 is Alibaba's video model, strong on motion. In this studio you write a scene as timed shots, each shot's first frame is drawn from your reference photos, and each shot renders as its own Wan clip, image-to-video, at the frame you pick in the Queue. The clips assemble into one MP4.",
      },
      {
        q: "How long can a Wan clip be?",
        a: "Any whole number of seconds from 2 to 10 a shot, rendered at exactly that length. A scene runs 4 to 30 seconds in all, written as timed shots.",
      },
      {
        q: "Does Wan make sound?",
        a: "Wan 3.0 renders native sound with the picture, and every clip on this page plays the sound it was rendered with; press Sound on.",
      },
      {
        q: "What resolutions does it render at?",
        a: "480p, 720p or 1080p, chosen in the Queue. The price on the card follows the frame.",
      },
      {
        q: "Which plan do I need?",
        a: `Wan 3.0 is on ${PLAN_FOR[wan.tier]}, with the credits for a clip shown in the Queue before you approve it.`,
        link: { href: "/pricing", label: "Compare plans" },
      },
      {
        q: "Were the clips on this page made on Wan 3.0?",
        a: "Yes, all four, at 720p with Wan's own sound: the flamenco and the leaves and the balloons at 5 seconds, the retriever at 10.",
      },
      REFERENCES_FAQ,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["ltx-video-generator", "kling-video-generator", "veo-video-generator", "seedance-video-generator"],
  finalCta: {
    eyebrow: "Your first scene",
    title: "Put your scene in motion on Wan.",
    body: "Write what moves, see every keyframe, pick the length, approve.",
  },
};

// The LTX page (2026-10-05; the LTX 2.5 page since 2026-10-08, Mike: "use
// ltx 2.5 on runway, switch to that"). What renders today: LTX 2.5 Fast and
// LTX 2.5 Pro through fal (src/fal.py VIDEO_MODELS "ltx2.5-fast" / "ltx2.5",
// the `lightricks/` namespace, read off fal's queue OpenAPI schema and model
// pages 2026-10-08) -- Fast 6 to 20 s in even steps at 720p, 1080p, 1440p or
// 2160p, Pro 6, 8 or 10 s at 720p or 1080p, sound generated with the
// picture and included in the rate, image-to-video off the shot's keyframe,
// on every plan. LTX 2.3 stays in the Queue as the cheapest LTX (the
// platform default). camera_motion, fps and the end frame exist in the
// model and are not wired, so nothing here names them.
//
// MEDIA: four clips rendered on LTX 2.5 itself, on Runway (which hosts the
// same Lightricks models), 2026-10-08: 6 s, 720p, 16:9, sound on -- the
// diver and the ramen counter on Pro, the forge prompt on BOTH tiers for
// the side-by-side. Each clip keeps the sound LTX rendered with it.
import { COMMERCIAL_FAQ, MODELS_TITLE, PLAN_FOR, REFERENCES_FAQ, model, modelCards } from "../shared";
import { CYAN } from "../theme";
import type { MakePage, MakeTile } from "../pages";

const pro = model("ltx2.5");
const fast = model("ltx2.5-fast");
const ltx23 = model("ltx2.3");

const DIR = "/models/ltx-video-generator";
const clip = (name: string, title: string, tag = ""): MakeTile => ({
  title,
  tag,
  video: `${DIR}/${name}.mp4`,
  src: `${DIR}/${name}.jpg`,
  aspect: "16:9",
});

const FORGE =
  "One continuous 6-second take, locked-off medium shot at anvil height. In a dark stone forge, a blacksmith in a leather apron is already mid-swing, hammering a glowing orange blade on an anvil; each strike throws a burst of sparks, he turns the blade with tongs and strikes again, the forge fire roaring behind him. Photorealistic, firelight against deep shadow, shot on film, fine grain. AUDIO: three ringing hammer strikes, each on the frame it lands, the hiss and roar of the forge, sparks crackling. No text, no logos, no music.";

const per = (m: typeof pro) => `${m.credits} credits for ${m.seconds} s at ${m.frame}`;

export const LTX: MakePage = {
  slug: "ltx-video-generator",
  section: "models",
  modelIds: ["ltx2.5", "ltx2.5-fast", "ltx2.3"],
  title: "LTX 2.5 AI Video Generator",
  description:
    "Render scenes on Lightricks' LTX 2.5 with the sound in the same pass: Fast for drafts up to 20 seconds and 4K, Pro for the final at 1080p. Every shot anchored on your reference photos, priced before you approve.",
  h1: "LTX 2.5",
  menu: "LTX Video Generator",
  subhead:
    "Picture and sound in one pass. Draft on LTX 2.5 Fast, up to 20 seconds and 4K, then finish on Pro, with every shot held to your reference photos.",
  cta: {
    label: "Make a scene",
    spark: "A 12-second scene in two timed shots with its sound: a wide reveal, then a close detail. Render on LTX 2.5.",
    secondary: { label: "Compare the tiers", href: "#tiers" },
    startLabel: "Start a scene",
  },
  template: "spark",
  tone: "light",
  accent: CYAN,
  layout: {
    hero: "reel",
    order: ["signature", "overview", "features", "howTo", "models", "faq", "related", "final"],
    features: "grid",
  },
  heroMedia: [
    {
      ...clip("diver", "A free diver in a kelp forest, rendered on LTX 2.5 Pro with its sound"),
      meta: "LTX 2.5 Pro · 720p · 6 s · sound",
    },
  ],
  signature: "tier-pair",
  signatureFrames: [
    { ...clip("forge-fast", "LTX 2.5 Fast", "Fast"), meta: per(fast), prompt: FORGE },
    { ...clip("forge-pro", "LTX 2.5 Pro", "Pro"), meta: per(pro), prompt: FORGE },
  ],
  overview: {
    items: [
      {
        eyebrow: "Sound in the same pass",
        title: "The pot bubbles on the frame it bubbles.",
        body: "LTX 2.5 generates the audio with the picture, not after it, and the sound is in the clip's price. Write the sound into the scene the way you write the light: the ladle on the bowl, the rain on the glass, the room behind.",
        points: [
          "Every scene the studio writes ends in its diegetic sound; LTX 2.5 renders it.",
          "This clip's push-in through the steam was asked for in the prompt; no camera control was set.",
        ],
        media: { ...clip("ramen", "A ramen counter at night, dolly-in through the steam", "LTX 2.5 Pro · with sound") },
        sound: true,
      },
    ],
  },
  wall: {
    title: "Shots LTX Renders",
    tiles: [],
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "LTX in the Studio",
    items: [
      {
        icon: "sound",
        title: "Sound with the picture",
        body: "LTX 2.5 renders the audio in the same pass as the frames, on both tiers, and it is included in the rate the card prices.",
      },
      {
        icon: "clock",
        title: "Up to 20 seconds on Fast",
        body: "LTX 2.5 Fast takes 6 to 20 seconds in two-second steps; Pro takes 6, 8 or 10. A shorter window is fitted up and trimmed in the edit.",
      },
      {
        icon: "frame",
        title: "720p to 4K",
        body: "Fast renders at 720p, 1080p, 1440p or 2160p. Pro renders at 720p or 1080p. The Queue starts on 720p and you pick the frame when you approve.",
      },
      {
        icon: "price",
        title: "Draft cheap, then approve",
        body: `${fast.name} is ${fast.credits} credits for ${fast.seconds} s at ${fast.frame}, ${pro.name} ${pro.credits}. The card prices every shot before you approve, on the tier you pick.`,
      },
      {
        icon: "model",
        title: "Three LTX models in the Queue",
        body: `LTX 2.5 Pro, LTX 2.5 Fast and LTX 2.3, the cheapest of the three at ${ltx23.credits} credits for ${ltx23.seconds} s at ${ltx23.frame}. On ${PLAN_FOR[pro.tier]}.`,
      },
      {
        icon: "references",
        title: "Image to video, from your photos",
        body: "Every shot's first frame is drawn from the references attached to the scene, and LTX animates that frame, so the person, product or place is the one you uploaded.",
      },
      {
        icon: "keyframe",
        title: "Keyframe first",
        body: "Draw each shot's keyframe in the Queue, look at it, and only then approve the clip. The keyframe is what the clip starts on.",
      },
      {
        icon: "shots",
        title: "Timed shots",
        body: "Write a scene as timed windows and each window renders as its own LTX clip, in order, with the scene's continuity carried into every shot.",
      },
      {
        icon: "export",
        title: "One MP4 at the end",
        body: "The editor assembles a scene's clips in shot order into one MP4, sound normalised, with an optional music bed under them.",
      },
    ],
  },
  models: { title: MODELS_TITLE, items: modelCards([pro, fast, ltx23], (m) => `A 10-second scene in two timed shots with its sound. Render on ${m.name}.`) },
  howTo: {
    title: "How to render on LTX 2.5",
    items: [
      {
        title: "Write the scene",
        body: "Sign in, describe the scene in Create, attach the photos it must keep, and write its sound. It comes back as timed shots.",
      },
      {
        title: "Send it to the Queue",
        body: "Send the scene to the Queue and draw each shot's keyframe there, priced on the button, so you see every first frame before a clip is made.",
      },
      {
        title: "Approve on LTX 2.5",
        body: "Pick Fast for a quick or long take, Pro for the finer picture, see the credits on the card, and approve. The editor exports the scene as one MP4.",
      },
    ],
  },
  faq: {
    title: "FAQs about LTX",
    items: [
      {
        q: "What is the LTX video generator?",
        a: "LTX 2.5 is Lightricks' video model, in two tiers: Fast for quick, long and high-resolution takes, Pro for the best picture at up to 1080p. In this studio you write a scene, its shots are drawn from your reference photos, and you approve each shot on the LTX model you pick.",
      },
      {
        q: "Does LTX 2.5 make sound?",
        a: "Yes. It generates the audio with the picture on both tiers, and the sound is included in the clip's price. Every clip on this page plays the sound LTX rendered; press Sound on.",
      },
      {
        q: "What is the difference between Fast and Pro?",
        a: `Fast renders 6 to 20 seconds at up to 2160p and costs less (${per(fast)}); Pro renders 6, 8 or 10 seconds at up to 1080p with more detail (${per(pro)}). The forge clips above are the same prompt on each.`,
      },
      {
        q: "How long can an LTX clip be?",
        a: "Up to 20 seconds on LTX 2.5 Fast and 10 on Pro. A scene longer than that is written as timed shots, each its own clip, assembled in order.",
      },
      {
        q: "Which plan do I need?",
        a: `LTX renders on ${PLAN_FOR[pro.tier]}. Each shot is priced in credits on the card before you approve it.`,
        link: { href: "/pricing", label: "See the plans" },
      },
      {
        q: "Were the clips on this page made on LTX 2.5?",
        a: "Yes, all four, at 720p and 6 seconds with their sound: the diver and the ramen counter on Pro, the forge on both Fast and Pro from the one prompt printed under them.",
      },
      REFERENCES_FAQ,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["wan-video-generator", "kling-video-generator", "veo-video-generator", "seedance-video-generator"],
  finalCta: {
    eyebrow: "Your first scene",
    title: "Hear your first scene on LTX 2.5.",
    body: "Write it with its sound, draft it on Fast, finish it on Pro.",
  },
};

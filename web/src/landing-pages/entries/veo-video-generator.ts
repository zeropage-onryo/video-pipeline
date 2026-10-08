// The Veo page (2026-10-05; media, copy and layout 2026-10-08). What
// renders today is Veo 3.1 through fal (src/fal.py VIDEO_MODELS): 4, 6 or
// 8 s a clip (an enum, fitted UP), 720p or 1080p, WITH audio (the
// endpoint's default, and the rate the studio prices), a negative prompt
// on the wire, on the Studio plan only. Google's own page
// (deepmind.google/models/veo, read 2026-10-05) claims native audio with
// dialogue, real-world physics and improved prompt adherence; those are
// quoted as Google's. Veo's reference images, first/last frame, extend and
// 4K are the model's and NOT in the Queue, so nothing here names them.
//
// MEDIA: four clips rendered on Veo 3.1 itself -- the standard model, not
// Veo 3.1 Fast (on Higgsfield, variant veo-3-1-preview, 4 s, 720p, 16:9,
// 2026-10-08), each with the sound Veo rendered. The barista's line was
// checked by transcribing the clip's audio: "Flat white for Sam."
import { COMMERCIAL_FAQ, MODELS_TITLE, PLAN_FOR, REFERENCES_FAQ, model, modelCards } from "../shared";
import { BLUE } from "../theme";
import type { MakePage, MakeTile } from "../pages";

const veo = model("veo3.1");
const seedance = model("seedance2.5");
const ltx = model("ltx2.5");

const DIR = "/models/veo-video-generator";
const clip = (name: string, title: string, meta: string): MakeTile => ({
  title,
  tag: "",
  meta,
  video: `${DIR}/${name}.mp4`,
  src: `${DIR}/${name}.jpg`,
  aspect: "16:9",
});

export const VEO: MakePage = {
  slug: "veo-video-generator",
  section: "models",
  modelIds: ["veo3.1"],
  title: "Veo 3.1 AI Video Generator",
  description:
    "Render scenes on Google's Veo 3.1 with the sound made in the same pass: a line of dialogue in sync, rain on a tin roof, a trumpet echoing off tile. 4, 6 or 8 seconds a shot, 720p or 1080p, from your own reference photos.",
  h1: "Veo 3.1",
  menu: "Veo Video Generator",
  subhead:
    "Google's model for scenes you hear as well as see: a spoken line on the right frame, the rain, the room. Turn the sound on.",
  cta: {
    label: "Make a scene",
    spark: "An 8-second scene with one spoken line and its room sound, in two timed shots. Render on Veo 3.1.",
    secondary: { label: "Hear the clips", href: "#sound" },
    startLabel: "Start a scene",
  },
  template: "spark",
  tone: "light",
  accent: BLUE,
  layout: {
    hero: "theater",
    order: ["signature", "features", "faq", "models", "howTo", "related", "final"],
    features: "grid",
  },
  heroMedia: [clip("barista", "“Flat white for Sam!”, spoken in sync, rendered on Veo 3.1", "Veo 3.1 · 720p · 4 s · dialogue")],
  signature: "sound-board",
  signatureFrames: [
    clip("porch", "Rain on a tin roof", "The downpour, the screen door's bang, a wet dog's shake, thunder far off."),
    clip("trumpet", "A trumpet in a tiled station", "The phrase echoing off the tiles as a train rushes in under it."),
    clip("surf", "Surf on black sand", "The crash, the hiss of foam, pebbles rattling as the water pulls back."),
  ],
  wall: {
    title: "Scenes Veo Renders",
    tiles: [],
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "Veo in the Studio",
    items: [
      {
        icon: "sound",
        title: "Sound, rendered with the frame",
        body: "The Queue renders Veo with audio on. Google describes Veo 3.1 as generating sound effects, ambience and dialogue natively, in the same pass as the picture.",
      },
      {
        icon: "guide",
        title: "A line of dialogue",
        body: "Write the line in quotes and who says it. The barista's line above was asked for in the prompt and came back spoken, on her lips.",
      },
      {
        icon: "model",
        title: "Physics and prompt adherence",
        body: "Google pitches Veo 3.1 on real-world physics and improved prompt adherence: rain that sheets, foam that drains, a train that pushes air.",
      },
      {
        icon: "clock",
        title: "4, 6 or 8 seconds",
        body: "A shot's window is fitted up to the nearest length Veo renders, and trimmed in the edit.",
      },
      {
        icon: "frame",
        title: "720p or 1080p",
        body: "Chosen when you approve, at one rate for both, so the frame never changes the price.",
      },
      {
        icon: "price",
        title: "Studio plan, priced first",
        body: `${veo.credits} credits for a ${veo.seconds}-second ${veo.frame} clip, on ${PLAN_FOR[veo.tier]}, shown on the card before anything renders.`,
      },
      {
        icon: "references",
        title: "Image to video, from your photos",
        body: "Each shot's keyframe is drawn from the references attached to the scene, and Veo animates that frame with its sound.",
      },
      {
        icon: "shots",
        title: "Timed shots",
        body: "A scene is written as timed shots, 4 to 30 seconds in all, and each shot renders as its own Veo clip, in order.",
      },
      {
        icon: "export",
        title: "Export keeps the sound",
        body: "The editor assembles the clips in shot order into one MP4 with Veo's own sound, the whole cut normalised to -14 LUFS.",
      },
    ],
  },
  models: { title: MODELS_TITLE, items: modelCards([veo, seedance, ltx], (m) => `An 8-second scene with one spoken line and its room sound. Render on ${m.name}.`) },
  howTo: {
    title: "How to render on Veo",
    items: [
      {
        title: "Write the scene and its sound",
        body: "Sign in, attach the photos the scene must keep, and write the action, the line in quotes and the room you should hear. It comes back as timed shots.",
      },
      {
        title: "Send it to the Queue",
        body: "Send the scene to the Queue and draw each shot's keyframe there, so you see every first frame before a clip is made.",
      },
      {
        title: "Approve on Veo 3.1",
        body: "Choose Veo 3.1 and the frame, see the credits on the card, and approve. The editor exports the scene as one MP4 with its sound.",
      },
    ],
  },
  faq: {
    title: "FAQs about Veo",
    items: [
      {
        q: "What is the Veo video generator?",
        a: "Veo 3.1 is Google DeepMind's video model. In this studio you write a scene as timed shots, each shot's first frame is drawn from your reference photos, and each shot renders as its own Veo clip with sound, image-to-video, at the frame you pick in the Queue. The clips assemble into one MP4.",
      },
      {
        q: "Does the clip have sound?",
        a: "Yes. The Queue renders Veo with audio on, which is the rate it prices. Google describes Veo 3.1 as generating sound effects, ambience and dialogue natively. Export keeps that sound and normalises the whole cut to -14 LUFS.",
      },
      {
        q: "Can it say a line of dialogue?",
        a: "Yes: put the line in quotes in the scene and say who speaks it. The barista clip on this page was asked for “Flat white for Sam!” and says it. Check the words in every clip before you use it.",
      },
      {
        q: "How long can a Veo clip be?",
        a: "4, 6 or 8 seconds a shot. A scene runs 4 to 30 seconds in all, written as timed shots, and each window is fitted up to the nearest length Veo renders.",
      },
      {
        q: "What resolutions does it render at?",
        a: "720p or 1080p, chosen when you approve, at one rate for both.",
      },
      {
        q: "Which plan do I need?",
        a: `Veo 3.1 is on ${PLAN_FOR[veo.tier]} only, the premium band, with the credits for a clip shown in the Queue before you approve it.`,
        link: { href: "/pricing", label: "Compare plans" },
      },
      {
        q: "Were the clips on this page made on Veo 3.1?",
        a: "Yes, all four, on the standard Veo 3.1 model, not the Fast one, at 720p and 4 seconds, each with the sound Veo rendered.",
      },
      REFERENCES_FAQ,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["seedance-video-generator", "ltx-video-generator", "kling-video-generator", "wan-video-generator"],
  finalCta: {
    eyebrow: "Your first scene",
    title: "Write a scene you can hear.",
    body: "The action, the line, the room. See every keyframe, see the price, approve on Veo.",
  },
};

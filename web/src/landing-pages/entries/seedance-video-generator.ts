// The Seedance page (2026-10-05, Mike's call).
import { INDIGO } from "../theme";
import { MODELS_TITLE, PLAN_FOR, model, modelCards, plate } from "../shared";
import type { MakePage, MakeTile } from "../pages";

// The Seedance page's two renderers, off the catalog like the three above.
const sd = model("seedance2");
const sdFast = model("seedance2-fast");
const kling = model("kling3-turbo-pro");

// TODO(media): eight Seedance stills from the studio go here as `src`
// (public/make/seedance-video-generator/<name>.jpg, 928x1152, the Ad
// Generator wall's shape). Until then each slot is its own plate: a shot
// type the scene writer actually produces, drawn as a cool gradient.
const SEEDANCE_TILES: MakeTile[] = [
  { title: "Wide establishing", tag: "Shot 1", plate: plate("#e0e7ff", "#a5b4fc", "#4f46e5") },
  { title: "Macro detail", tag: "Shot 2", plate: plate("#ecfeff", "#67e8f9", "#3730a3") },
  { title: "Slow push-in", tag: "Shot 3", plate: plate("#f5f3ff", "#c4b5fd", "#4338ca") },
  { title: "Handheld follow", tag: "Shot 4", plate: plate("#e0f2fe", "#7dd3fc", "#312e81") },
  { title: "Top-down reveal", tag: "Shot 5", plate: plate("#eef2ff", "#818cf8", "#1e1b4b") },
  { title: "Rack focus", tag: "Shot 6", plate: plate("#fdf4ff", "#d8b4fe", "#4c1d95") },
  { title: "Golden hour", tag: "Shot 7", plate: plate("#fff7ed", "#fdba74", "#4338ca") },
  { title: "Night exterior", tag: "Shot 8", plate: plate("#1e1b4b", "#312e81", "#6366f1") },
];

// Seedance (2026-10-05, Mike's call). What renders today is Seedance 2.0
// and Seedance 2.0 Fast through fal (src/fal.py VIDEO_MODELS; 4-15 s a
// clip, 480p/720p, 1080p on the full model as the premium band). Seedance
// 2.5 is on fal and NOT in the catalog, so no line here names it: the copy
// names the models the Queue offers, and `sd`/`sdFast` read the catalog
// so a re-export changes the page. TODO(media): the wall's eight tiles are
// gradient plates until Seedance renders from the studio replace them
// (`src: "/make/seedance-video-generator/<name>.jpg"`, 928x1152).
export const SEEDANCE: MakePage = {
    slug: "seedance-video-generator",
    section: "models",
    modelIds: ["seedance2", "seedance2-fast"],
    title: "Seedance AI Video Generator",
    description:
      "Write a scene, anchor every shot on your reference photos, and render it on Seedance 2.0 or Seedance 2.0 Fast, 4 to 15 seconds a clip, up to 1080p.",
    h1: "Seedance Video Generator",
    menu: "Seedance Video Generator",
    subhead:
      "Write a scene, anchor every shot on your reference photos, and render it on Seedance, 4 to 15 seconds a clip, up to 1080p.",
    cta: {
      label: "Make a scene",
      spark:
        "A 15-second scene in three timed shots: a wide establishing shot, a close detail, the action. Render on Seedance.",
      secondary: { label: "See the shots", href: "#shots" },
      startLabel: "Start a scene",
    },
    template: "spark",
    tone: "light",
    accent: INDIGO,
    signature: "shot-timeline",
    wall: {
      title: "Shots Seedance Renders",
      tiles: SEEDANCE_TILES,
      explore: { label: "See the features", href: "#features" },
    },
    features: {
      title: "Seedance in the Studio",
      items: [
        {
          icon: "model",
          title: "Two Seedance tiers",
          body: `${sdFast.name} for quick 720p takes, ${sd.name} for the full-quality render up to 1080p. Pick either per shot in the Queue.`,
        },
        {
          icon: "shots",
          title: "4 to 15 seconds a shot",
          body: "A scene is written as timed shots, and each shot's window is fitted to a Seedance clip length between 4 and 15 seconds.",
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
          icon: "price",
          title: "Price before spend",
          body: "The Queue prices the exact Seedance tier, length and frame you picked, and that number is what is charged.",
        },
        {
          icon: "elements",
          title: "Reusable elements",
          body: "Save a character, prop or place as an element and every scene written against it is held to the same frames.",
        },
        {
          icon: "guide",
          title: "Guided writing",
          body: "Type the idea, or let the Guide work through story, look and pacing with you before the scene is written.",
        },
        {
          icon: "export",
          title: "Export one MP4",
          body: "Assemble the Seedance clips in shot order into one MP4, loudness-normalised, with an optional music bed under them.",
        },
        {
          icon: "assets",
          title: "Everything on one wall",
          body: "Every render lands on your Assets wall with its model and prompt, to view, star, sort and download.",
        },
      ],
    },
    models: {
      title: MODELS_TITLE,
      items: modelCards([sd, sdFast, kling]),
    },
    howTo: {
      title: "How to render on Seedance",
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
          title: "Approve on Seedance",
          body: "In the Queue, choose Seedance 2.0 or 2.0 Fast, the length and the frame for each shot, with the price on the card, and approve. Export joins the clips into one MP4.",
        },
      ],
    },
    faq: {
      title: "FAQs about Seedance",
      items: [
        {
          q: "What is the Seedance video generator?",
          a: "Seedance is ByteDance's video model. In this studio you write a scene as timed shots, each shot's first frame is drawn from your reference photos, and each shot renders as its own Seedance clip, image-to-video, on the tier you pick in the Queue. The clips assemble into one MP4.",
        },
        {
          q: "Which Seedance models can I render on?",
          a: `${sdFast.name} and ${sd.name}, both chosen per shot in the Queue with a length and a frame. The Fast tier renders at 480p or 720p; the full model adds 1080p.`,
          link: { href: "/models", label: "See every model" },
        },
        {
          q: "How long can a Seedance clip be?",
          a: "Between 4 and 15 seconds a shot. A scene runs 4 to 30 seconds in all, written as timed shots, and each shot's window is fitted up to a length Seedance supports.",
        },
        {
          q: "Can I use my own photos as references?",
          a: "Yes. Upload photos into the composer for one scene, or save a person, product or place as an element and reuse it. Every keyframe is drawn from the references attached to the scene, and a scene with no references never reaches the Queue.",
        },
        {
          q: "Does it keep the same character or product across shots?",
          a: "Each shot's keyframe is drawn from the same references and from the previous shot's still, so the scene holds together. Video models still vary between renders, so look at each keyframe before you approve. No pixel match is promised, and you need the consent of anyone whose likeness you upload.",
        },
        {
          q: "Does the Queue render text-to-video or image-to-video?",
          a: "Image-to-video, anchored on the shot's keyframe. A scene whose keyframes have not been drawn yet is drawn on the Draw keyframes button before the render, so a Seedance clip always starts from a frame you have seen.",
        },
        {
          q: "Which plan do I need?",
          a: `Both Seedance tiers are on ${PLAN_FOR[sd.tier]}. A 1080p render on ${sd.name} is the premium band, on ${PLAN_FOR.premium}.`,
          link: { href: "/pricing", label: "Compare plans" },
        },
        {
          q: "Can I use the clips commercially?",
          a: "What the studio generates for your account is yours to use, subject to the terms of the model that rendered it. The output is AI-made, so review it before you publish it.",
          link: { href: "/terms", label: "Read the terms" },
        },
      ],
    },
    related: ["ai-product-ad-generator"],
    finalCta: {
      eyebrow: "Your first scene",
      title: "Render your first scene on Seedance.",
      body: "Write it, see every keyframe, see the price, approve.",
    },
  };

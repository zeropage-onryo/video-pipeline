// The Seedance page (2026-10-05, Mike's call).
import { INDIGO } from "../theme";
import { MODELS_TITLE, PLAN_FOR, model, modelCards, plate } from "../shared";
import type { MakePage, MakeTile } from "../pages";

// The Seedance page's renderers, off the catalog like the three above:
// 2.5 is the page's model (2026-10-06, Mike's call), the two 2.0 tiers
// stay on the page as the family it belongs to.
const sd25 = model("seedance2.5");
const sd = model("seedance2");
const sdFast = model("seedance2-fast");

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

// Seedance (2026-10-05, Mike's call; 2.5 since 2026-10-06). What renders
// is Seedance 2.5 (src/fal.py VIDEO_MODELS: 4-30 s a clip with sound,
// 480p/720p/1080p, 1080p the premium band) beside Seedance 2.0 and 2.0
// Fast (4-15 s). The copy names the models the Queue offers, and `sd25`/
// `sd`/`sdFast` read the catalog so a re-export changes the page. TODO(media): the wall's eight tiles are
// gradient plates until Seedance renders from the studio replace them
// (`src: "/make/seedance-video-generator/<name>.jpg"`, 928x1152).
export const SEEDANCE: MakePage = {
    slug: "seedance-video-generator",
    section: "models",
    modelIds: ["seedance2.5", "seedance2", "seedance2-fast"],
    title: "Seedance 2.5 AI Video Generator",
    description:
      "Write a scene, anchor every shot on your reference photos, and render it on Seedance 2.5: 4 to 30 seconds a clip with synchronized sound, 480p to 1080p, priced before you approve.",
    h1: "Seedance 2.5",
    menu: "Seedance 2.5",
    subhead:
      "Write a scene, anchor every shot on your reference photos, and render it on Seedance 2.5, 4 to 30 seconds a clip with sound, up to 1080p.",
    cta: {
      label: "Make a scene",
      spark:
        "A 30-second scene in three timed shots: a wide establishing shot, a close detail, the action. Render on Seedance 2.5.",
      secondary: { label: "See the shots", href: "#shots" },
      startLabel: "Start a scene",
    },
    template: "spark",
    tone: "light",
    accent: INDIGO,
    signature: "shot-timeline",
    // ByteDance's four headline claims for 2.5 (seed.bytedance.com/en/seedance2_5,
    // read 2026-10-07), each restated as what THIS studio does with them.
    // Media: TODO -- a Seedance clip per block (`media: { video, src }`).
    overview: {
      items: [
        {
          eyebrow: "Longer narratives. Better control.",
          title: "Up to 30 seconds a shot, written as timed beats.",
          body: "Seedance 2.5 renders 4 to 30 seconds in one generation, and reads a prompt the way this studio writes one: 0 to 3 seconds does one thing, 3 to 7 the next, and the beats come back in order. Cut the scene into shots, or ask for one take.",
          points: [
            "Each shot's window is fitted to a clip length Seedance renders, 4 to 30 seconds.",
            "Six frames from 21:9 to 9:16; image-to-video keeps the keyframe's framing.",
          ],
          media: { title: "", tag: "0–30s", plate: plate("#e0e7ff", "#a5b4fc", "#4f46e5") },
        },
        {
          eyebrow: "Smarter reference",
          title: "Held to your photos from the first second to the last.",
          body: "Every shot's first frame is drawn from the references you attach, and a scene with none never reaches the Queue. Seedance 2.5 keeps a product or a face the same at second one and second twenty-eight, and each shot's keyframe carries the previous shot's still for continuity.",
          points: [
            "Upload photos for one scene, or save a person, product or place as an element and reuse it.",
            "The keyframe you approved is what the clip starts on, image-to-video.",
          ],
          media: { title: "", tag: "Reference", plate: plate("#ecfeff", "#67e8f9", "#3730a3") },
        },
        {
          eyebrow: "Audio and picture together",
          title: "Sound is generated with the frame, not laid over it.",
          body: "Every scene this studio writes ends in its diegetic sound: the footstep, the room tone, no music bed. Seedance 2.5 decides picture and sound in the same pass, so the footstep lands on the frame the foot does, and the audio is included in the clip's price.",
          media: { title: "", tag: "Sound on", plate: plate("#f5f3ff", "#c4b5fd", "#4338ca") },
        },
        {
          eyebrow: "Aiming for production",
          title: "Priced before you spend, assembled when you approve.",
          body: "Draft a scene at 480p for under half the 720p rate, look at every keyframe, then approve the tier, length and frame per shot with the credits on the card. The clips assemble in shot order into one MP4, loudness-normalised, with an optional music bed under them.",
          points: [
            `${sdFast.name} and ${sd.name} stay on the same card for a quicker or a 1080p take.`,
          ],
          media: { title: "", tag: "Queue", plate: plate("#eef2ff", "#818cf8", "#1e1b4b") },
        },
      ],
    },
    wall: {
      title: "Shots Seedance Renders",
      tiles: SEEDANCE_TILES,
      explore: { label: "See the features", href: "#features" },
    },
    features: {
      title: "Seedance 2.5 in the Studio",
      items: [
        {
          icon: "sound",
          title: "Sound with the picture",
          body: "Every scene is written with its diegetic sound, and Seedance 2.5 generates the audio in the same pass as the frames. It is in the clip and in the price.",
        },
        {
          icon: "clock",
          title: "Up to 30 seconds a shot",
          body: "Each shot's window is fitted to a Seedance 2.5 clip length between 4 and 30 seconds, twice what 2.0 renders, in one generation.",
        },
        {
          icon: "shots",
          title: "Timed beats, in order",
          body: "A scene is written as timed windows, which is the prompt shape Seedance 2.5 reads best: 0 to 3 seconds one thing, 3 to 7 the next, returned in order.",
        },
        {
          icon: "edit",
          title: "One take, or a cut",
          body: "The writer cuts a scene into shots by default and writes one continuous take when you ask for it. On Seedance 2.5 either renders.",
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
          title: "Draft cheap, then approve",
          body: `A 480p draft costs under half the 720p rate. The Queue prices the exact tier, length and frame you picked, and that number is what is charged.`,
        },
        {
          icon: "elements",
          title: "Reusable elements",
          body: "Save a character, prop or place as an element and every scene written against it is held to the same frames.",
        },
        {
          icon: "export",
          title: "Export one MP4",
          body: "Assemble the Seedance clips in shot order into one MP4, loudness-normalised, with an optional music bed under them.",
        },
      ],
    },
    models: {
      title: MODELS_TITLE,
      items: modelCards([sd25, sd, sdFast]),
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
          body: "In the Queue, choose Seedance 2.5 (or 2.0, or 2.0 Fast), the length and the frame for each shot, with the price on the card, and approve. Export joins the clips into one MP4.",
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
          a: `${sd25.name}, and beside it ${sd.name} and ${sdFast.name}, each chosen per shot in the Queue with a length and a frame. 2.5 renders 4 to 30 seconds with sound at 480p, 720p or 1080p; the 2.0 tiers render 4 to 15 seconds, the Fast one up to 720p.`,
          link: { href: "/models", label: "See every model" },
        },
        {
          q: "How long can a Seedance clip be?",
          a: "Between 4 and 30 seconds a shot on Seedance 2.5 (4 to 15 on the 2.0 tiers). A scene runs 4 to 30 seconds in all, written as timed shots, and each shot's window is fitted up to a length Seedance supports.",
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
          a: `Every Seedance model is on ${PLAN_FOR[sd25.tier]}. A 1080p render on ${sd25.name} or ${sd.name} is the premium band, on ${PLAN_FOR.premium}.`,
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

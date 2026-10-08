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

// RENDERED 2026-10-07 on Seedance 2.5 through Mike's Runway account
// (session "Seedance 2.5 landing page", text-to-video, 720p, sound on,
// 1,930 credits for all thirteen clips), so the chips read T2V.
// The wall (2026-10-07, Mike's call): the showcase layout -- three masonry
// columns, each tile its own Seedance 2.5 snippet in its own frame, the
// feature it shows along the bottom, its prompt underneath on click. The
// prompts are the drafts in docs/tasks/seedance-media-brief.md (v3); every
// tile is a plate until its clip lands (`video` + a poster `src` under
// public/models/seedance-video-generator/). Frames are Seedance's own
// (3:4, 4:3, 16:9, 9:16; it takes no 4:5), and the ORDER is what deals
// them into three even columns (showcase-wall.tsx's `deal`).
const SNIPPET = "Seedance 2.5 · text-to-video · 5 s · 720p";
const SEEDANCE_TILES: MakeTile[] = [
  {
    title: "Spray and momentum",
    video: "/models/seedance-video-generator/skate.mp4", src: "/models/seedance-video-generator/skate.jpg",
    tag: "Handheld follow",
    mode: "T2V",
    aspect: "3:4",
    meta: SNIPPET,
    plate: plate("#e0f2fe", "#7dd3fc", "#312e81"),
    prompt:
      "One continuous 5-second take. A skateboarder in a dark rain jacket carves through a rain-slick concrete underpass at blue hour, face turned away; the camera follows low and close behind as the board cuts left then right, throwing a fine spray, sodium lights doubled in the puddles. Sound: wheels on wet concrete, the hiss of spray, the underpass echo. No music.",
  },
  {
    title: "Push-in",
    video: "/models/seedance-video-generator/dancer.mp4", src: "/models/seedance-video-generator/dancer.jpg",
    tag: "Slow push-in",
    mode: "T2V",
    aspect: "4:3",
    meta: SNIPPET,
    plate: plate("#f5f3ff", "#c4b5fd", "#4338ca"),
    prompt:
      "One continuous 5-second take. An empty theatre: a dancer in a pale slip dress mid-turn on a bare stage under one spotlight, seen from the stalls, face in shadow. The camera pushes slowly in as she completes the turn and sweeps into an arabesque, the dress trailing. Sound: her feet on the boards, the hush of the hall. No music.",
  },
  {
    title: "Micro detail",
    video: "/models/seedance-video-generator/honey.mp4", src: "/models/seedance-video-generator/honey.jpg",
    tag: "Macro detail",
    mode: "T2V",
    aspect: "9:16",
    meta: SNIPPET,
    plate: plate("#fff7ed", "#fdba74", "#4338ca"),
    prompt:
      "One continuous 5-second take, extreme macro. A ribbon of honey falls from a wooden dipper onto a honeycomb, light glowing through it; it folds over itself and pools into the cells, a last drip stretching and snapping. Sound: the faint tick of the drip. No music.",
  },
  {
    title: "Multi-beat action",
    video: "/models/seedance-video-generator/table.mp4", src: "/models/seedance-video-generator/table.jpg",
    tag: "Top-down reveal",
    mode: "T2V",
    aspect: "9:16",
    meta: SNIPPET,
    plate: plate("#eef2ff", "#818cf8", "#1e1b4b"),
    prompt:
      "One continuous 5-second take, directly overhead. A long oak table at dusk, half set for dinner. In order: a stoneware plate set down, a glass, a linen napkin folded, a match struck and a candle lit, as the camera rises slowly. Each sound lands on its action: the plate on wood, the glass, the match. No music.",
  },
  {
    title: "Scale and atmosphere",
    video: "/models/seedance-video-generator/saltflat.mp4", src: "/models/seedance-video-generator/saltflat.jpg",
    tag: "Wide establishing",
    mode: "T2V",
    aspect: "16:9",
    meta: SNIPPET,
    plate: plate("#e0e7ff", "#a5b4fc", "#4f46e5"),
    prompt:
      "One continuous 5-second take, static wide shot. A lone figure in a long dark coat crosses a white salt flat at blue hour, tiny in the lower third, a low ridge of mountains behind; wind lifts the coat and drives a thin haze of salt across the ground. Sound: wind, crunching footsteps. No music.",
  },
  {
    title: "Rain and steam",
    video: "/models/seedance-video-generator/noodles.mp4", src: "/models/seedance-video-generator/noodles.jpg",
    tag: "Night exterior",
    mode: "T2V",
    aspect: "3:4",
    meta: SNIPPET,
    plate: plate("#1e1b4b", "#312e81", "#6366f1"),
    prompt:
      "One continuous 5-second take. A street noodle stall at night in the rain, one bare bulb, no signage; a cook's arm lifts noodles high with long chopsticks and drops them back into the pot as steam rolls up through the falling rain. Sound: the boil, rain drumming on a tarp, the clack of chopsticks. No music.",
  },
  {
    title: "Backlight and water",
    video: "/models/seedance-video-generator/surfer.mp4", src: "/models/seedance-video-generator/surfer.jpg",
    tag: "Golden hour",
    mode: "T2V",
    aspect: "3:4",
    meta: SNIPPET,
    plate: plate("#fff7ed", "#fdba74", "#312e81"),
    prompt:
      "One continuous 5-second take. A surfer walks out of the sea at golden hour, board under one arm, seen from behind at three-quarters; backlit, water sheeting off the wetsuit, the low sun flaring through the spray as she walks up the wet sand toward frame right. Sound: surf, wind, footsteps in wet sand. No music.",
  },
  {
    title: "Rack focus",
    video: "/models/seedance-video-generator/perfume.mp4", src: "/models/seedance-video-generator/perfume.jpg",
    tag: "Camera control",
    mode: "T2V",
    aspect: "16:9",
    meta: SNIPPET,
    plate: plate("#fdf4ff", "#d8b4fe", "#4c1d95"),
    prompt:
      "One continuous 5-second take. A clear, unlabelled glass perfume bottle on wet black slate, droplets sharp on the glass; behind it a figure in a cream coat passes a rain-streaked window, soft and out of focus. Focus pulls from the droplets to the figure as she passes, then back to the bottle. Sound: rain on glass, one distant car. No music.",
  },
];

// The signature's own three frames (one scene, three shots), since the
// wall's tiles are eight different subjects. Drawn on Nano Banana Pro
// through Mike's Runway account (2026-10-07, 20 credits each, 3:4).
const D = "/models/seedance-video-generator/";
const SIGNATURE_FRAMES: MakeTile[] = [
  { title: "A ceramics studio at dawn, a potter at the wheel by the window", tag: "", src: `${D}sig-wide.jpg` },
  { title: "Wet hands opening the clay on the spinning wheel", tag: "", src: `${D}sig-macro.jpg` },
  { title: "Clay-dusted hands lifting the indigo cup to the window", tag: "", src: `${D}sig-cup.jpg` },
];

// Seedance (2026-10-05, Mike's call; 2.5 since 2026-10-06). What renders
// is Seedance 2.5 (src/fal.py VIDEO_MODELS: 4-30 s a clip with sound,
// 480p/720p/1080p, 1080p the premium band) beside Seedance 2.0 and 2.0
// Fast (4-15 s). The copy names the models the Queue offers, and `sd25`/
// `sd`/`sdFast` read the catalog so a re-export changes the page.
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
    signatureFrames: SIGNATURE_FRAMES,
    // ByteDance's four headline claims for 2.5 (seed.bytedance.com/en/seedance2_5,
    // read 2026-10-07), each restated as what THIS studio does with them.
    // Media: Seedance 2.5 renders (Runway, 2026-10-07) under public/models/seedance-video-generator/.
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
          media: { title: "A kitchen in three timed shots", tag: "Timed beats · three cuts in 6 s", video: "/models/seedance-video-generator/kitchen.mp4", src: "/models/seedance-video-generator/kitchen.jpg" },
        },
        {
          eyebrow: "Smarter reference",
          title: "Held to your photos from the first second to the last.",
          body: "Every shot's first frame is drawn from the references you attach, and a scene with none never reaches the Queue. Seedance 2.5 keeps a product or a face the same at second one and second twenty-eight, and each shot's keyframe carries the previous shot's still for continuity.",
          points: [
            "Upload photos for one scene, or save a person, product or place as an element and reuse it.",
            "The keyframe you approved is what the clip starts on, image-to-video.",
          ],
          media: { title: "A sneaker turned through a full rotation", tag: "Product held steady", video: "/models/seedance-video-generator/sneaker.mp4", src: "/models/seedance-video-generator/sneaker.jpg" },
        },
        {
          eyebrow: "Audio and picture together",
          title: "Sound is generated with the frame, not laid over it.",
          body: "Every scene this studio writes ends in its diegetic sound: the footstep, the room tone, no music bed. Seedance 2.5 decides picture and sound in the same pass, so the footstep lands on the frame the foot does, and the audio is included in the clip's price.",
          media: { title: "Ice and soda poured into a glass", tag: "Native audio sync", video: "/models/seedance-video-generator/soda.mp4", src: "/models/seedance-video-generator/soda.jpg" },
          sound: true,
        },
        {
          eyebrow: "Aiming for production",
          title: "Priced before you spend, assembled when you approve.",
          body: "Draft a scene at 480p for under half the 720p rate, look at every keyframe, then approve the tier, length and frame per shot with the credits on the card. The clips assemble in shot order into one MP4, loudness-normalised, with an optional music bed under them.",
          points: [
            `${sdFast.name} and ${sd.name} stay on the same card for a quicker or a 1080p take.`,
          ],
          media: { title: "A motorcycle at dusk, 720p", tag: "", video: "/models/seedance-video-generator/moto-720p.mp4", src: "/models/seedance-video-generator/moto-720p.jpg" },
          compare: {
            media: { title: "The same shot as a 480p draft", tag: "", video: "/models/seedance-video-generator/moto-480p.mp4", src: "/models/seedance-video-generator/moto-480p.jpg" },
            label: "480p draft",
            mediaLabel: "720p final",
          },
        },
      ],
    },
    wall: {
      title: "Shots Seedance Renders",
      tiles: SEEDANCE_TILES,
      explore: { label: "See the features", href: "#features" },
      layout: "showcase",
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
          body: "Draw every shot's first frame in the Queue before a clip is rendered, with the credits on the button before you press it.",
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
      items: modelCards([sd25, sd, sdFast], (m) => `A 15-second scene in three timed shots: a wide establishing shot, a close detail, the action. Render on ${m.name}.`),
    },
    howTo: {
      // The studio's flow as main has it (2026-10-07): Create writes the
      // scene, Send to Queue is the pick, the Queue draws the keyframes
      // (priced on the button) and approves the render, and Ready to cut
      // opens the scene in the editor for the one MP4.
      title: "How to render on Seedance 2.5",
      items: [
        {
          title: "Write the scene",
          body: "Sign in, attach your reference photos in Create, and describe the scene in a line. It comes back as timed shots, each with its own prompt and its sound.",
        },
        {
          title: "Send it to the Queue",
          body: "Press Send to Queue on the scene. In the Queue, draw every shot's first frame, with the credits shown on the button before you press it.",
        },
        {
          title: "Approve on Seedance 2.5",
          body: "Choose Seedance 2.5 for each shot, or 2.0 or 2.0 Fast, with its length and frame, check the price on the card and approve. Then open the scene in the editor and export one MP4.",
        },
      ],
    },
    faq: {
      // Checked against main 2026-10-08: the Queue approves a scene with no
      // keyframe as text-to-video (the card says so), the reference gate
      // still refuses a scene with no photos, scenes clamp to 4-30 s, the
      // plans are Starter / Creator / Studio, /terms exists.
      title: "FAQs about Seedance 2.5",
      items: [
        {
          q: "What is the Seedance 2.5 video generator?",
          a: "Seedance 2.5 is ByteDance's newest video model: up to 30 seconds a shot, with sound generated in the same pass as the picture. In this studio you write a scene as timed shots from your reference photos, each shot renders as its own Seedance clip on the model you pick in the Queue, and the editor joins them into one MP4.",
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
          a: "Yes. Attach photos in Create for one scene, or save a person, product or place as an element and reuse it. Every keyframe is drawn from the references attached to the scene, and a scene with no references cannot be rendered.",
        },
        {
          q: "Does it keep the same character or product across shots?",
          a: "Each shot's keyframe is drawn from the same references and from the previous shot's still, so the scene holds together. Video models still vary between renders, so look at each keyframe before you approve. No pixel match is promised, and you need the consent of anyone whose likeness you upload.",
        },
        {
          q: "Does it render text-to-video or image-to-video?",
          a: "Both. Draw a shot's keyframe in the Queue and the clip renders image-to-video, starting from that frame. Approve without one and it renders text-to-video from the prompt. The card says which before you approve.",
        },
        {
          q: "Does Seedance 2.5 make sound?",
          a: "Yes. Every scene is written with its diegetic sound, the footsteps and the room, not a music bed, and Seedance 2.5 generates that audio in the same pass as the picture. It is included in the clip's price.",
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

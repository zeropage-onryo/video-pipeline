// The FLUX.2 Pro page (2026-10-05; media, copy and layout 2026-10-08).
// What the studio does today: the composer draws on fal-ai/flux-2-pro at
// any of the ten ~1-megapixel frames (src/fal.py IMAGE_SIZES, `size: "wh"`),
// and sends reference photos to fal-ai/flux-2-pro/edit as image_urls (the
// studio sends up to 8). Priced per megapixel: the first output megapixel
// at the base rate, every further megapixel of input and output at the
// extra rate, so a reference edit costs more than a text draw
// (fal.image_usd). The model's own claims -- "studio-grade images",
// "zero-configuration quality", "style transfer, and sequential editing
// workflows" -- are fal's page for fal-ai/flux-2-pro, read 2026-10-05,
// quoted as Black Forest Labs'.
//
// MEDIA: every still was drawn on FLUX.2 Pro (on Higgsfield, variant pro,
// 2026-10-08). The wall is the prompt-adherence test: each tile carries the
// prompt it was drawn from, word for word, and only the clauses the still
// visibly honours are [[marked]] -- the first lemons draw came back with
// two lemons and was re-rolled; the suit's "to his left" is unmarked
// because the plant stands on his right. The frame picker's five stills
// are one prompt drawn at 1:1, 3:4, 4:3, 9:16 and 16:9; the other five
// frames show the nearest, cropped, and say so.
import { EMERALD } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_FAQS, imageModel, imageModelCards } from "../shared";
import type { MakePage, MakeTile } from "../pages";

const flux = imageModel("flux2-pro");
const flux11 = imageModel("flux-pro1.1");
const seedream = imageModel("seedream4.5");

const DIR = "/models/flux-image-generator";

const TILES: MakeTile[] = [
  {
    title: "Count it, place it",
    tag: "3:4",
    src: `${DIR}/lemons.jpg`,
    aspect: "3:4",
    prompt:
      "Still life on a [[mint-green linen tablecloth]]: [[three whole lemons grouped together on the left]], [[a clear glass carafe of water in the centre]], [[a folded navy-blue napkin on the right]], and [[a single sprig of rosemary lying in front of the carafe]]. Soft window light from the right, gentle shadows, photorealistic, shot from a slightly high angle.",
  },
  {
    title: "Find the red can",
    tag: "3:4",
    src: `${DIR}/glasshouse.jpg`,
    aspect: "3:4",
    prompt:
      "Inside a [[Victorian glasshouse]]: [[rows of ferns on tiered wooden shelves]], a [[red metal watering can]] on the second shelf from the bottom, condensation beading on the glass roof, a [[three-legged wooden stool in the foreground]], soft overcast daylight, photorealistic.",
  },
  {
    title: "Scale and geometry",
    tag: "3:4",
    src: `${DIR}/stairwell.jpg`,
    aspect: "3:4",
    prompt:
      "Looking [[straight down a spiral brutalist concrete stairwell]] from the top floor, [[a single person in a bright yellow coat]] standing on the third landing down, [[moss growing in the corners of the steps]], cool daylight falling from a round skylight, strong geometric composition, photorealistic.",
  },
  {
    title: "Macro, every droplet",
    tag: "3:4",
    src: `${DIR}/beetle.jpg`,
    aspect: "3:4",
    prompt:
      "Macro photograph of an [[iridescent green jewel beetle]] resting on a [[dew-covered leaf]], [[water droplets on its shell]] catching the light, [[the leaf veins sharp]], background dissolving into soft green bokeh, photorealistic.",
  },
  {
    title: "Colour by name",
    tag: "3:4",
    src: `${DIR}/convertible.jpg`,
    aspect: "3:4",
    prompt:
      "A [[vintage emerald-green convertible]] parked on a coastal road beside [[white chalk cliffs]], a folded [[red-and-white striped beach umbrella in the back seat]], the sea behind, late afternoon sun, [[no badges, no text]], 35mm film photograph.",
  },
  {
    title: "A portrait, composed",
    tag: "3:4",
    src: `${DIR}/suit.jpg`,
    aspect: "3:4",
    prompt:
      "Editorial portrait of a man in a [[sage-green linen suit]] sitting on a [[simple wooden chair]] in an [[empty white gallery room]], one large [[monstera plant in a terracotta pot]] to his left, soft north light, [[centred symmetrical composition]], photorealistic.",
  },
];

const FRAMES: MakeTile[] = [
  { title: "The ridge road at 1:1", tag: "", src: `${DIR}/frame-1x1.jpg`, aspect: "1:1" },
  { title: "The ridge road at 3:4", tag: "", src: `${DIR}/frame-3x4.jpg`, aspect: "3:4" },
  { title: "The ridge road at 4:3", tag: "", src: `${DIR}/frame-4x3.jpg`, aspect: "4:3" },
  { title: "The ridge road at 9:16", tag: "", src: `${DIR}/frame-9x16.jpg`, aspect: "9:16" },
  { title: "The ridge road at 16:9", tag: "", src: `${DIR}/frame-16x9.jpg`, aspect: "16:9" },
];

export const FLUX: MakePage = {
  slug: "flux-image-generator",
  section: "models",
  modelIds: ["flux2-pro"],
  title: "FLUX.2 Pro AI Image Generator",
  description:
    "Draw stills on Black Forest Labs' FLUX.2 Pro that follow the prompt to the object: counts, colours, positions. Any of ten frames from 1:1 to 21:9, up to eight reference photos, credits per still shown before you send.",
  h1: "FLUX.2 Pro",
  menu: "FLUX Image Generator",
  subhead:
    "Write what is in the frame and where it sits, and FLUX.2 Pro draws exactly that: three lemons on the left, the red can on the shelf, the frame you picked to the pixel.",
  cta: {
    label: "Draw a still",
    spark: "An editorial still on FLUX.2 Pro: [subject] in [place], [what sits where], window light, 4:5.",
    secondary: { label: "See the prompts", href: "#examples" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: EMERALD,
  layout: {
    hero: "cover",
    order: ["wall", "signature", "features", "howTo", "models", "faq", "related", "final"],
    features: "list",
  },
  heroMedia: [{ title: "Drawn on FLUX.2 Pro", tag: "2K · 16:9, one prompt, no retouching", src: `${DIR}/cover.jpg`, aspect: "16:9" }],
  signature: "frame-picker",
  signatureFrames: FRAMES,
  wall: {
    title: "Prompt In, Picture Out",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
    layout: "prompts",
  },
  features: {
    title: "FLUX in the Studio",
    items: [
      {
        icon: "frame",
        title: "Ten frames, exact pixels",
        body: "1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9 or 21:9, picked in the composer and sent as exact pixel sizes. Every frame is under one megapixel, so every frame prices the same from text.",
      },
      {
        icon: "references",
        title: "Up to eight reference photos",
        body: "Drop photos into the composer and they go to FLUX.2 Pro's edit endpoint with the prompt. fal describes the model's style transfer and sequential editing; the studio sends up to eight references.",
      },
      {
        icon: "model",
        title: "It follows the prompt",
        body: "Black Forest Labs pitches FLUX.2 Pro on studio-grade images with zero configuration: no steps, no guidance scale. Write counts, colours and positions in plain words; the stills on this page mark what each prompt asked for.",
      },
      {
        icon: "price",
        title: "Priced per megapixel",
        body: "The first output megapixel at the base rate, every further megapixel of input and output at the extra rate, so a reference edit costs more than a text draw. The picker shows the credits before you send.",
      },
      {
        icon: "edit",
        title: "Generate, then edit",
        body: "Send the still again with itself as a reference and a new line, and FLUX edits rather than redraws. Each pass lands on the wall as its own still.",
      },
      {
        icon: "guide",
        title: "Talk it through or just ask",
        body: "The composer's brain answers when you are bouncing ideas and draws when you ask for the still, writing the prompt as the work.",
      },
      {
        icon: "assets",
        title: "On the wall, under its model",
        body: "Every still lands on your Assets wall with its prompt, to view, star, sort into folders and download.",
      },
      {
        icon: "elements",
        title: "Make it an element",
        body: "Make element turns a still into a reference a scene is held to, the one way a render becomes a reference here.",
      },
      {
        icon: "export",
        title: "Then shoot it",
        body: "Attach the element to a scene and every shot's keyframe is drawn from it before a clip renders on the video model you pick.",
      },
    ],
  },
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([flux, flux11, seedream]) },
  howTo: {
    title: "How to draw on FLUX",
    items: [
      {
        title: "Write the still",
        body: "Sign in, switch the composer to Image, drop your reference photos in if the still should match them, and write one line.",
      },
      {
        title: "Pick the model and the frame",
        body: "Choose FLUX.2 Pro in the picker, with its credits per still beside it, and one of the ten frames. Send.",
      },
      {
        title: "Keep it, edit it, or make it an element",
        body: "The still lands on your Assets wall. Send it back with a new line to edit it, star it, download it, or press Make element.",
      },
    ],
  },
  faq: {
    title: "FAQs about FLUX",
    items: [
      {
        q: "What is the FLUX image generator?",
        a: "FLUX.2 Pro is Black Forest Labs' production image model, built to follow the prompt closely. In this studio you write one line, attach reference photos if you want, pick a frame, and the composer draws the still on it through fal. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Do my reference photos reach the model?",
        a: "Yes. They go to FLUX.2 Pro's edit endpoint with your prompt, up to eight of them. A reference edit is priced higher than a text draw because the model bills input megapixels too.",
      },
      {
        q: "What frames can it draw?",
        a: "Ten frames from 1:1 to 21:9, each sent as an exact pixel size of about one megapixel.",
      },
      {
        q: "What is the difference from FLUX 1.1 Pro?",
        a: "FLUX 1.1 Pro is the older, text-only model in the picker: it takes no reference photos and draws from the prompt alone. FLUX.2 Pro takes references and edits.",
        link: { href: "/models", label: "See every model" },
      },
      {
        q: "Were the stills on this page made on FLUX.2 Pro?",
        a: "Yes, every one, each from the prompt printed under it. The highlighted words are the ones the still visibly honours; where it did not (the suit's plant stands on his right, not his left), the words are left unmarked.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["nano-banana-image-generator", "seedream-image-generator", "ideogram-image-generator"],
  finalCta: {
    eyebrow: "Your first still",
    title: "Say what is in the frame. Get that.",
    body: "One line, a frame, your photos if it should match them, the credits on the picker.",
  },
};

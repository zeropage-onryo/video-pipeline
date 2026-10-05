// The AI Ad Generator page (2026-10-01), the first /make page and the
// template every later one was cut from. Its wall is eight real ads.
import { RED } from "../theme";
import { MODEL_NAMES, MODELS_TITLE, model, modelCards } from "../shared";
import type { MakePage, MakeTile } from "../pages";

// The three models the model cards quote, read off the generated catalog so
// a re-export of src/pricing.py changes the page and nothing has to be
// remembered. The FAQ names every model and no price (2026-10-02).
const ltx = model("ltx2.3");
const kling = model("kling3-turbo-pro");
const veo = model("veo3.1");

// The wall's stills are eight product ads generated in the studio (Mike,
// 2026-10-02; 928x1152 JPEGs under public/make/<slug>/, named by product
// type). Every slot carries one, so no gradient plate is drawn. The slot
// order follows the wall's bento (ad-wall.tsx): 0 is the short tile, 1 and
// 4 the tall narrow ones, 5 the wide one, 6 and 7 the pair at the end.
const ADS = "/make/ai-product-ad-generator";
const TILES: MakeTile[] = [
  { title: "Lip tint", tag: "", src: `${ADS}/lip-tint.jpg` },
  { title: "Fragrance", tag: "", src: `${ADS}/fragrance.jpg` },
  { title: "Energy drink", tag: "", src: `${ADS}/energy-drink.jpg` },
  { title: "Headphones", tag: "", src: `${ADS}/headphones.jpg` },
  { title: "Sneaker", tag: "", src: `${ADS}/sneaker.jpg` },
  { title: "Tumbler", tag: "", src: `${ADS}/tumbler.jpg` },
  { title: "Hot sauce", tag: "", src: `${ADS}/hot-sauce.jpg` },
  { title: "Matcha", tag: "", src: `${ADS}/matcha.jpg` },
];

export const AD_GENERATOR: MakePage = {
    slug: "ai-product-ad-generator",
    title: "AI Ad Generator",
    description:
      "Upload your product, pick a look, and render a short ad on Kling, Seedance, LTX, Wan or Veo.",
    h1: "AI Ad Generator",
    menu: "AI Ad Generator",
    subhead: "Upload your product, pick a look, and render a short ad on the model you choose.",
    cta: {
      label: "Create your ad",
      spark:
        "A 10-second product ad for my [product]: a reveal, a detail, the product in use. Clean, premium look.",
    },
    template: "spark",
    tone: "light",
    accent: RED,
    wall: {
      title: "ZeroPage Ad Generator",
      tiles: TILES,
      explore: { label: "Explore more", href: "#features" },
    },
    features: {
      title: "Ad Generator Features",
      items: [
        {
          icon: "references",
          title: "Product references",
          body: "Your product photos ride into the prompt, the keyframe and the clip. Every shot anchors on a still drawn from them.",
        },
        {
          icon: "elements",
          title: "Reusable elements",
          body: "Save the product as an element once and every ad after is held to the same frames.",
        },
        {
          icon: "shots",
          title: "Timed shots",
          body: "A scene is written as timed shots, 4 to 30 seconds in all, and each shot renders as its own clip.",
        },
        {
          icon: "keyframe",
          title: "Keyframe first",
          body: "See each shot's first frame and redraw it until it is right, before a clip is rendered.",
        },
        {
          icon: "price",
          title: "Price before spend",
          body: "The Queue shows the credits for the exact model and length you picked, and that number is what is charged.",
        },
        {
          icon: "model",
          title: "Pick the model",
          body: "Kling, Seedance, LTX and Wan, plus Veo on the Studio plan, chosen per approve through one Queue.",
        },
        {
          icon: "export",
          title: "Export one MP4",
          body: "Assemble the clips in shot order into one MP4, with a music bed you upload under the clips' own sound.",
        },
        {
          icon: "guide",
          title: "Guided writing",
          body: "Describe the ad, or let the Guide work through story, look and pacing with you before anything is written.",
        },
        {
          icon: "assets",
          title: "Everything on one wall",
          body: "Every render lands on your Assets wall to view, star, sort into folders and download.",
        },
      ],
    },
    models: {
      title: MODELS_TITLE,
      items: modelCards([ltx, kling, veo]),
    },
    howTo: {
      title: "How to make a product ad",
      items: [
        {
          title: "Upload your product",
          body: "Sign in, drop a few product photos into the composer, and write one line about the ad. Or save the product as an element and reuse it across ads.",
        },
        {
          title: "Pick a look and approve",
          body: "Describe the look, or let the Guide work through story, look and pacing with you. In the Queue, pick the model, length and frame, with the price on the card.",
        },
        {
          title: "Render and export",
          body: "Clips render one shot at a time. Download each from Assets, or export the whole scene as one MP4 in shot order.",
        },
      ],
    },
    faq: {
      // One line at the title's full size; longer wraps (measured 2026-10-02).
      title: "FAQs about AI Ad Generator",
      // The reference's questions (what it is, how to, the prompt, people,
      // styles, references, models, length, commercial use), each answer
      // checked against the code on 2026-10-02. Cost stays out of this
      // section (Mike's call): prices live on /pricing and /models.
      items: [
        {
          q: "What is an AI product ad generator?",
          a: "A studio that writes a short ad from your product photos and one line about it. The scene is written as timed shots, each shot's first frame is drawn from your photos, and each shot renders as its own clip on the video model you pick. The clips assemble into one MP4.",
        },
        {
          q: "How do I make a product ad with it?",
          a: "Sign in, drop a few product photos into the composer, write one line about the ad, and press Create. Pick the scene on the board, which draws its keyframes, then approve each shot in the Queue. The clips land on your Assets wall, and Export joins them in shot order into one MP4.",
        },
        {
          q: "How do I write the prompt for the best ad?",
          a: "Name the product, one action per shot, and the look you want. The studio writes the full scene prompt as timed shots from that line and your photos. If you would rather talk it through, the Guide works through story, look and pacing with you first. Then check each shot's keyframe before you render: that still is what the clip anchors on, and the Director lets you edit the prompt, swap a reference and redraw it.",
        },
        {
          q: "Can I upload my own product photos as references?",
          a: "Yes. Upload photos into the composer for one ad, or save the product as an element with its photos and reuse it across ads. Every keyframe is drawn from the references attached to the scene, and a scene with no references never reaches the Queue.",
        },
        {
          q: "Can it show a real person or the same product every time?",
          a: "Save the person or product as an element with a few photos, and every scene written against it is held to those frames, keyframe and clip. Video models still vary between renders, so look at the keyframe before you approve. No pixel match is promised, and you need the consent of anyone whose likeness you upload.",
        },
        {
          q: "What looks and styles can it make?",
          a: "Whatever you can describe: the prompt carries the look, the lighting and the camera, and the keyframe shows it before a clip renders. Attach a reference image for the mood and the writing is grounded in it. The Guide can work through the look with you if you have not settled on one.",
        },
        {
          q: "Which video models does it render on?",
          a: `${MODEL_NAMES}, chosen per shot in the Queue with a length and a frame.`,
          link: { href: "/models", label: "See every model" },
        },
        {
          q: "How long can an ad be?",
          a: "A scene runs 4 to 30 seconds, written as timed shots. Each shot renders as its own clip, fitted to the lengths the model you picked supports.",
        },
        {
          q: "Can I use the ads commercially?",
          a: "What the studio generates for your account is yours to use, subject to the terms of the model that rendered it. The output is AI-made, so review it before you publish it.",
          link: { href: "/terms", label: "Read the terms" },
        },
      ],
    },
    related: ["seedance-video-generator"],
    finalCta: {
      eyebrow: "Your first ad",
      title: "Make your first product ad.",
      body: "Upload the product, pick a look, see the price, render.",
    },
  };

// The Nano Banana Pro page (2026-10-05, Mike: "the image models"; media,
// copy and layout 2026-10-08). What the studio does today: the composer's
// Image mode draws a still on Nano Banana through the Gemini key (a Pro
// still is pricing.json's actions.still.pro credits) or on "Nano Banana Pro
// (fal)" (src/fal.py IMAGE_MODELS: 1K/2K, aspect ratio strings, up to eight
// references through the edit endpoint); every element's reference sheet
// is drawn on Nano Banana Pro (src/element_sheet.py); a scene's keyframes
// are drawn on Nano Banana (src/nano_banana.py, Flash by default). The
// model's own claims -- "industry-leading text generation", consistency
// "for up to 5 people" -- are fal's page for fal-ai/nano-banana-pro, read
// 2026-10-05, quoted as Google's. 4K exists in the model and is not offered
// here.
//
// MEDIA: every still on the page was drawn on Nano Banana Pro itself (on
// Higgsfield, 2K, 2026-10-08; Higgsfield's own asset panel names the model)
// -- the three references from text, the three results FROM those
// references, the element sheet from the person's reference. The prompts
// on the signature are the ones sent, word for word.
import { AMBER } from "../theme";
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_CREDITS, STILL_FAQS, imageModel, imageModelCards } from "../shared";
import type { MakePage, MakeTile } from "../pages";

const nano = imageModel("nano-banana-pro");
const seedream = imageModel("seedream4.5");
const flux = imageModel("flux2-pro");

const DIR = "/models/nano-banana-image-generator";
const ref = (name: string, title: string): MakeTile => ({ title, tag: "", src: `${DIR}/ref-${name}.jpg`, aspect: "4:5" });

const REFS = [ref("mug", "The mug"), ref("person", "The person"), ref("cafe", "The cafe")];

const STEPS: MakeTile[] = [
  {
    title: "One reference: the same mug, a new scene.",
    tag: "",
    src: `${DIR}/step-1.jpg`,
    aspect: "4:5",
    prompt:
      "The exact mug from the reference photo, same speckled cream glaze and the same honey-amber drip from the rim, now filled with a flat white with simple latte art, standing on a folded linen napkin beside a croissant on a wooden table, soft morning side light, close-up, photorealistic.",
  },
  {
    title: "Two references: the same mug, in the same person's hands.",
    tag: "",
    src: `${DIR}/step-2.jpg`,
    aspect: "4:5",
    prompt:
      "The woman from the portrait reference, same face, same short curly auburn hair, same freckles, same mustard-yellow chunky knit sweater, holding the exact mug from the product reference (speckled cream glaze, honey-amber drip) in both hands near her chin, a slight smile, plain warm-grey backdrop, soft window light from the left, waist-up, photorealistic.",
  },
  {
    title: "Three references: the mug, the person and the cafe, held at once.",
    tag: "",
    src: `${DIR}/step-3.jpg`,
    aspect: "4:5",
    prompt:
      "Medium close-up: the woman from the portrait reference (same face, curly auburn hair, freckles, mustard knit sweater) fills the right half of the frame, leaning on the pale oak counter of the cafe from the interior reference, the brass espresso machine and hanging plants softly out of focus behind her, holding the exact mug from the product reference (speckled cream glaze, honey-amber drip) up near her shoulder, low morning sun through the tall windows, photorealistic.",
  },
];

const TILES: MakeTile[] = [
  { title: "A chalk menu that reads", tag: "3:4", src: `${DIR}/menu.jpg`, aspect: "3:4", meta: "Every price on the board was in the prompt, in quotes." },
  { title: "A diagram, labelled", tag: "4:5", src: `${DIR}/infographic.jpg`, aspect: "4:5", meta: "Four numbered stages, each bean darker than the last." },
  { title: "Five faces in one frame", tag: "4:3", src: `${DIR}/friends.jpg`, aspect: "4:3", meta: "Matching jackets, five distinct people, one candid moment." },
  { title: "Fire, steam, night", tag: "16:9", src: `${DIR}/market.jpg`, aspect: "16:9", meta: "A wok in flames under a string of bulbs." },
  { title: "A packshot on white", tag: "1:1", src: `${DIR}/honey.jpg`, aspect: "1:1", meta: "One drip caught falling, a clean shadow." },
  { title: "Golden hour, backlit", tag: "4:5", src: `${DIR}/sunflower.jpg`, aspect: "4:5", meta: "Skin and straw held sharp against the sun." },
];

export const NANO_BANANA: MakePage = {
  slug: "nano-banana-image-generator",
  section: "models",
  modelIds: ["nano-banana-pro"],
  title: "Nano Banana Pro AI Image Generator",
  description:
    "Draw stills on Google's Nano Banana Pro from one line and up to eight reference photos: the same product, the same face, the same room, held from still to still, with text that reads. Credits per still shown before you send.",
  h1: "Nano Banana Pro",
  menu: "Nano Banana Image Generator",
  subhead:
    "Attach the product, the person and the place, write one line, and Nano Banana Pro draws a still that keeps all three. Labels and menus come back legible.",
  cta: {
    label: "Draw a still",
    spark: "A product still on Nano Banana Pro: [product] held by [person] in [place], morning light, the label legible.",
    secondary: { label: "See the references", href: "#references" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: AMBER,
  layout: {
    hero: "split",
    order: ["signature", "overview", "wall", "howTo", "features", "models", "faq", "related", "final"],
    features: "split",
  },
  heroMedia: [
    { title: "Three references, one still", tag: "Nano Banana Pro", src: `${DIR}/step-3.jpg`, aspect: "4:5" },
    { title: "Product", tag: "", src: `${DIR}/ref-mug.jpg` },
    { title: "Person", tag: "", src: `${DIR}/ref-person.jpg` },
    { title: "Place", tag: "", src: `${DIR}/ref-cafe.jpg` },
  ],
  signature: "reference-stack",
  signatureFrames: [...REFS, ...STEPS],
  overview: {
    items: [
      {
        eyebrow: "Text that reads",
        title: "Put the words in quotes. They come back spelled.",
        body: "Google describes Nano Banana Pro's text generation as industry-leading, in multiple languages. This label was asked for in three quoted lines, roaster, origin and tasting notes, and every letter landed where the prompt put it.",
        points: [
          "Labels, menus, signs and diagrams: name the exact words in the prompt.",
          "Read them back in the still before it goes anywhere; a model can still slip.",
        ],
        media: { title: "A kraft-paper coffee bag with a three-line printed label", tag: "Text in the prompt, in quotes", src: `${DIR}/label.jpg`, aspect: "4:5" },
      },
      {
        eyebrow: "It draws your element sheets",
        title: "One photo in, a sheet of the same person out.",
        body: "Save a character as an element and the studio draws its reference sheet on Nano Banana Pro from the real photos: front, three-quarter, profile, back and a close-up, the face and the sweater kept in every panel. Scenes are then held to the sheet.",
        media: { title: "A five-panel character sheet drawn from one portrait", tag: "Element sheet", src: `${DIR}/sheet.jpg`, aspect: "16:9" },
      },
    ],
  },
  wall: {
    title: "Stills Nano Banana Draws",
    tiles: TILES,
    explore: { label: "See the features", href: "#features" },
    layout: "filmstrip",
  },
  features: {
    title: "Nano Banana in the Studio",
    items: [
      {
        icon: "references",
        title: "Up to eight reference photos",
        body: "Drop reference photos into the composer and they go to Nano Banana Pro's edit endpoint with the prompt, so the still is of your product, person or place, not a guess at it.",
      },
      {
        icon: "type",
        title: "Legible text",
        body: "Google calls Nano Banana Pro's text generation industry-leading, in multiple languages. Quote the words you want on the label, the sign or the menu, and check them in the still.",
      },
      {
        icon: "elements",
        title: "It draws every element sheet",
        body: "Save a character, prop or place as an element and the studio draws its reference sheet on Nano Banana Pro from the real photos: five panels for a person, a turnaround for a prop.",
      },
      {
        icon: "frame",
        title: "Ten frames, 1K or 2K",
        body: "1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9 or 21:9, picked in the composer. On the fal route the still comes back at 1K or 2K.",
      },
      {
        icon: "price",
        title: "Credits before you send",
        body: `The picker shows each model's credits per still. On the Gemini route a Nano Banana Pro still is ${STILL_CREDITS.pro} credits, a Nano Banana still ${STILL_CREDITS.standard}.`,
      },
      {
        icon: "keyframe",
        title: "The same family draws your keyframes",
        body: "Every shot's first frame in a scene is drawn on Nano Banana from the scene's references, so what holds a still together holds a clip together too.",
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
        icon: "export",
        title: "Make it an element, then shoot it",
        body: "Make element turns a still into a reference. Attach it to a scene and every shot's keyframe is drawn from it before a clip renders.",
      },
    ],
  },
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([nano, seedream, flux]) },
  howTo: {
    title: "How to draw on Nano Banana",
    items: [
      {
        title: "Attach what must stay the same",
        body: "Sign in, switch the composer to Image and drop in the photos the still has to keep: the product, the person, the place. Up to eight.",
      },
      {
        title: "Write one line, pick Nano Banana Pro",
        body: "Say what happens and name any words in quotes. Choose Nano Banana Pro in the picker, with its credits per still beside it, and a frame. Send.",
      },
      {
        title: "Keep it, or make it an element",
        body: "The still lands on your Assets wall. Star it, download it, or press Make element to hold a scene to it and shoot it.",
      },
    ],
  },
  faq: {
    title: "FAQs about Nano Banana",
    items: [
      {
        q: "What is the Nano Banana image generator?",
        a: "Nano Banana Pro is Google's image generation and editing model, the Gemini image model. In this studio you write one line, attach reference photos, pick a frame, and the composer draws the still on it, through the Gemini key or through fal. The still lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "Do my reference photos reach the model?",
        a: "Yes. On the fal route up to eight photos go to Nano Banana Pro's edit endpoint with your prompt. Google describes the model as holding a consistent look for up to five people across generations; the stills on this page were drawn from three references at once. Check the still rather than assume it.",
      },
      {
        q: "Can it write text in the image?",
        a: "Google describes Nano Banana Pro's text generation as industry-leading and legible in multiple languages. Put the exact words in the prompt, in quotes, and read them back in the still before you use it.",
      },
      {
        q: "What frames and sizes can it draw?",
        a: "Ten frames from 1:1 to 21:9. On the fal route the still comes back at 1K or 2K; 4K exists in the model and is not offered in the studio.",
      },
      {
        q: "Were the stills on this page made on Nano Banana Pro?",
        a: "Yes, every one, at 2K. The three references were drawn from text first, then each result was drawn from them with the prompt shown under it.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["seedream-image-generator", "flux-image-generator", "ideogram-image-generator"],
  finalCta: {
    eyebrow: "Your first still",
    title: "Hold a still to your own photos.",
    body: "Attach the product, the person, the place. One line. The credits on the picker.",
  },
};

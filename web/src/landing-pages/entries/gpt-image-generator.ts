// The GPT Image page (2026-10-05 as GPT Image 2; the GPT Image 2.5 page
// since 2026-10-08, Mike: "swap out the gpt 2 page with the gpt image 2.5
// page"). What the studio does today: the composer draws on GPT Image 2.5
// in two variants through fal (src/fal.py IMAGE_MODELS "gpt-image-2.5-flare"
// and "-sunburst", read off fal's queue OpenAPI schemas and pages that
// day): exact {width, height} at any of the ten composer frames, `quality`
// sent at high (xhigh and max exist and are not offered), reference photos
// to the variant's `/edit` as image_urls, up to 16. fal's own words: Flare
// is "OpenAI's default image model for most applications. Fast,
// high-quality generation with natural lighting, rich textures, and support
// for complex layouts including transparent backgrounds"; Sunburst is
// "OpenAI's precision-focused image model ... extra fidelity on intricate
// detail". The model can return a transparent background (`background`);
// the studio does not ask for one yet, and the page says so. GPT Image 2
// stays in the picker as the older sibling.
//
// MEDIA: the "Brightly" set made on GPT Image 2.5 through fal on 2026-10-05
// for the GPT Image 2.5 showcase (test_stills/brightly in the main
// checkout): one bottle drawn, then six ad formats edited from one
// reference each. The variant, quality and instruction on each format are
// the showcase slides' own labels; the instructions are abridged where the
// slides abridged them (marked "…"). The VOLT ad is a Sunburst text-to-image
// at high, 1024x1280, its prompt in test_stills/.gen_tmp.py. The finished
// showcase slides are NOT used: they print fal list prices into the art.
import { COMMERCIAL_FAQ, IMAGE_MODELS_TITLE, STILL_FAQS, imageModel, imageModelCards } from "../shared";
import { LIME } from "../theme";
import type { MakePage, MakeTile } from "../pages";

const flare = imageModel("gpt-image-2.5-flare");
const sunburst = imageModel("gpt-image-2.5-sunburst");
const gpt2 = imageModel("gpt-image-2");

const DIR = "/models/gpt-image-generator";

const FORMATS: MakeTile[] = [
  {
    title: "In a scene",
    tag: "GPT Image 2.5 Flare, edit, high",
    src: `${DIR}/scene.jpg`,
    aspect: "4:5",
    meta: "The bottle from the reference, set on a bathroom sill at the size of a real 500 ml spray, its shadow matching the window.",
    prompt:
      "Place the bottle from image 1 on a sunlit bathroom windowsill … scaled realistically as a standard 500 ml spray bottle, soft window light with a matching soft shadow.",
  },
  {
    title: "Colourways",
    tag: "GPT Image 2.5 Flare, edit, high",
    src: `${DIR}/colorways.jpg`,
    aspect: "4:5",
    meta: "Three variants from one bottle, each label reading exactly what the instruction said, each coloured to its trigger.",
    prompt:
      "Left: label text reads BRIGHTLY LEMON. Middle: BRIGHTLY MINT. Right: BRIGHTLY GRAPEFRUIT. Each label colored to match its trigger.",
  },
  {
    title: "Before / after",
    tag: "GPT Image 2.5 Sunburst, edit, high",
    src: `${DIR}/after.jpg`,
    from: `${DIR}/before.jpg`,
    aspect: "4:5",
    meta: "Drag the divider. The camera, the light and every object stay where they were; only the grime on the counter and the hob is gone.",
    prompt:
      "Keep the identical camera angle, composition, window light and every object in place. Change only the condition: spotless, streak-free.",
  },
  {
    title: "Cutout",
    tag: "GPT Image 2.5 Flare, edit, high, PNG with alpha",
    src: `${DIR}/cutout.webp`,
    alpha: true,
    aspect: "4:5",
    meta: "A real transparent background, ready for any layout. The model can return one; the studio does not ask for it yet.",
    prompt:
      "Isolate the spray bottle on a fully transparent background. Keep the bottle exactly as is; remove the mist, backdrop and floor shadow.",
  },
  {
    title: "Macro",
    tag: "GPT Image 2.5 Sunburst, edit, xhigh",
    src: `${DIR}/macro.jpg`,
    aspect: "4:5",
    meta: "Sunburst's fine detail: the beaded droplets on the trigger and the label, each one sharp. Drawn at xhigh, one tier above the high the studio sends.",
    prompt:
      "Extreme macro of the trigger, nozzle and label letters, beaded condensation, every droplet and the plastic grain razor sharp.",
  },
  {
    title: "Poster with copy",
    tag: "GPT Image 2.5 Flare, edit, high",
    src: `${DIR}/poster.jpg`,
    aspect: "4:5",
    meta: "Three lines of copy, each set once, where the instruction put it.",
    prompt:
      "Text exactly as written, each appearing once: headline 'SPRAY. WIPE. DONE.' … in lime: '2 FOR $10' … small cream line: 'BRIGHTLY MULTI-SURFACE CLEANER'.",
  },
];

export const GPT_IMAGE: MakePage = {
  slug: "gpt-image-generator",
  section: "models",
  modelIds: ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2"],
  navLabel: "GPT Image 2.5",
  title: "GPT Image 2.5 AI Image Generator",
  description:
    "Turn one product photo into a set of ads on OpenAI's GPT Image 2.5: the product in a scene, colourways with their labels spelled, before and after, a macro and a poster with your copy. Flare for speed, Sunburst for detail, up to 16 references.",
  h1: "GPT Image 2.5",
  menu: "GPT Image Generator",
  subhead:
    "One product photo in, a set of ads out: in a room, in three colourways, before and after, up close, and on a poster with your words spelled exactly.",
  cta: {
    label: "Draw a still",
    spark: "A product ad on GPT Image 2.5: the [product] from my photo on [surface], and a headline that reads exactly '[your words]'.",
    secondary: { label: "See the six formats", href: "#formats" },
    startLabel: "Start a still",
  },
  template: "spark",
  tone: "light",
  accent: LIME,
  layout: {
    hero: "theater",
    order: ["signature", "overview", "features", "faq", "models", "howTo", "related", "final"],
    features: "split",
  },
  heroMedia: [{ title: "A spray bottle in mist, drawn on GPT Image 2.5", tag: "", src: `${DIR}/hero.jpg`, aspect: "4:5", meta: "GPT Image 2.5 · 4:5" }],
  signature: "ad-types",
  signatureFrames: FORMATS,
  overview: {
    items: [
      {
        eyebrow: "Text in the frame",
        title: "Three pieces of type, spelled from one prompt.",
        body: "One text-to-image prompt on Sunburst, at high quality, asked for a can labelled 'VOLT' in a burst of ice, a skier mid-flip behind it, the headline 'CHARGE THE DROP' in heavy condensed type and 'VOLT ENERGY' at the foot, and no other text. All three came back as written, and nothing else was lettered.",
        points: ["Quote the words and say where they sit.", "Read them back before the still goes anywhere; a model can still slip."],
        media: { title: "VOLT energy drink poster, headline and tagline rendered", tag: "", src: `${DIR}/volt.jpg`, aspect: "4:5" },
      },
    ],
  },
  wall: {
    title: "Ads GPT Image Draws",
    tiles: [],
    explore: { label: "See the features", href: "#features" },
  },
  features: {
    title: "GPT Image 2.5 in the Studio",
    items: [
      {
        icon: "references",
        title: "Up to 16 reference photos",
        body: "Drop the product, the room, the person into the composer; they go to GPT Image 2.5's edit endpoint with the prompt, up to sixteen at once.",
      },
      {
        icon: "type",
        title: "Words spelled as written",
        body: "Quote the label, the headline, the small print. The colourway labels and the poster's three lines on this page came back exactly as asked.",
      },
      {
        icon: "edit",
        title: "Edits that keep the frame",
        body: "Send a still back with one change and the camera, the light and every object stay put; only what you named moves.",
      },
      {
        icon: "model",
        title: "Flare or Sunburst",
        body: "Flare is OpenAI's fast default; Sunburst is the precision tier for fine detail and a face or product kept across edits. Both are in the picker.",
      },
      {
        icon: "frame",
        title: "Ten frames, exact pixels",
        body: "1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9 or 21:9, sent to GPT Image 2.5 as an exact width and height.",
      },
      {
        icon: "price",
        title: "Credits before you send",
        body: "Drawn at high quality and priced per still; the picker shows the credits for each variant before you send.",
      },
      {
        icon: "open",
        title: "Cutouts, from the model",
        body: "GPT Image 2.5 can return a PNG with a transparent background, as the cutout above shows. The studio does not ask for one yet.",
      },
      {
        icon: "assets",
        title: "Every format on the wall",
        body: "Each still lands on your Assets wall with its prompt, to compare, star, sort into folders and download.",
      },
      {
        icon: "export",
        title: "Make it an element, then shoot it",
        body: "Make element turns the ad's product into a reference a scene is held to, so the bottle in the poster is the bottle in the clip.",
      },
    ],
  },
  models: { title: IMAGE_MODELS_TITLE, items: imageModelCards([flare, sunburst, gpt2]) },
  howTo: {
    title: "How to make a set of ads",
    items: [
      {
        title: "Attach the product",
        body: "Sign in, switch the composer to Image and drop in the product photo. Add a room, a model or a texture if the ad needs them.",
      },
      {
        title: "One line per format",
        body: "Pick GPT Image 2.5 Flare or Sunburst and a frame, then ask for one format at a time: the scene, the colourways, the poster with its words in quotes.",
      },
      {
        title: "Keep the set",
        body: "Every still lands on your Assets wall. Star the keepers, download them, or press Make element and put the product in a scene.",
      },
    ],
  },
  faq: {
    title: "FAQs about GPT Image 2.5",
    items: [
      {
        q: "What is the GPT Image generator?",
        a: "GPT Image 2.5 is OpenAI's image model, in two variants: Flare, the fast default, and Sunburst, the precision tier. In this studio you attach reference photos, write one line, pick a frame, and the composer draws the still through fal. It lands on your Assets wall and can become an element a scene is held to.",
      },
      {
        q: "What is the difference between Flare and Sunburst?",
        a: "Flare is OpenAI's default for most work: fast, with natural light and complex layouts. Sunburst is built for intricate detail and for keeping a product or a face the same across edits. On this page the before/after and the macro are Sunburst; the rest are Flare.",
      },
      {
        q: "Do my reference photos reach the model?",
        a: "Yes, up to sixteen at once, to the variant's edit endpoint with your prompt. Every format on this page was edited from one reference photo of the bottle.",
      },
      {
        q: "Can it write the words on the ad?",
        a: "Put the exact words in quotes and say where they go. The labels and the poster's copy on this page came back as written; read every letter back before you publish.",
      },
      {
        q: "Can it make a cutout with a transparent background?",
        a: "The model can: the cutout on this page is a PNG with a real alpha channel. The studio does not request a transparent background yet, so a still from the composer comes back on a background.",
      },
      {
        q: "Were the stills on this page made on GPT Image 2.5?",
        a: "Yes, every one, through fal: the six formats as edits of one bottle photo, the VOLT poster from text. Each format shows the variant and quality that drew it and its instruction, abridged where marked. The macro was drawn at xhigh, one tier above the high the studio sends.",
      },
      STILL_FAQS.cost,
      STILL_FAQS.where,
      STILL_FAQS.video,
      COMMERCIAL_FAQ,
    ],
  },
  related: ["ai-product-ad-generator", "nano-banana-image-generator", "flux-image-generator", "ideogram-image-generator"],
  finalCta: {
    eyebrow: "Your first set",
    title: "One photo in. A set of ads out.",
    body: "Attach the product, ask for one format at a time, read the words back.",
  },
};

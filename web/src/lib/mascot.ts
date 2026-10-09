/* The assistant's mascot (2026-10-08, Mike's calls; docs/ASSISTANT_AVATARS.md).

   Five plush creatures -- Nimbus (the default), Mote, Sprout, Glim, Pip --
   whose names never change. A person picks the creature, one of its three
   LOOKS (material and accessory are baked into the render), a colour (the
   look's own, or one of four shared ones) and how it talks (the persona's
   tone). Every option is an image rendered ONCE and served from R2: picking
   one costs nothing and nothing is generated per person. 15 looks x their
   colours x 7 moods = 483 images, each at 128px and 320px.

   The choice is stored in the persona's `avatar` column as a short code,
   "m:<look>.<colour>" (e.g. "m:nf.own"), because the server cuts that
   column to 16 characters (assistant_store.clean_avatar). Anything else in
   it -- the emoji and film glyphs the pill offered before -- reads as the
   default, Nimbus in lavender felt. */

export const MOODS = ["awake", "listen", "think", "talk", "made", "oops", "sleep"] as const;
export type Mood = (typeof MOODS)[number];

export type CreatureId = "nimbus" | "mote" | "sprout" | "glim" | "pip";
export type ColourId = "own" | "lightred" | "lavender" | "mint" | "sky";

export type Look = {
  id: string; // the file stem, e.g. "nimbus-felt"
  code: string; // two letters, what the avatar code stores
  creature: CreatureId;
  label: string; // material, then the accessory
  own: { name: string; hex: string };
};

export const CREATURES: { id: CreatureId; name: string; note: string }[] = [
  { id: "nimbus", name: "Nimbus", note: "A soft little cloud" },
  { id: "mote", name: "Mote", note: "A round pom-pom" },
  { id: "sprout", name: "Sprout", note: "A bean with a sprout" },
  { id: "glim", name: "Glim", note: "A gumdrop with a light bulb" },
  { id: "pip", name: "Pip", note: "An egg with round ears" },
];

/* the order a creature's looks are offered in; the first is its own default */
export const LOOKS: Look[] = [
  { id: "nimbus-felt", code: "nf", creature: "nimbus", label: "Felt", own: { name: "Lavender", hex: "#b49ac4" } },
  { id: "nimbus-knit", code: "nk", creature: "nimbus", label: "Knit, beanie", own: { name: "Mint", hex: "#9cc2b4" } },
  { id: "nimbus-clay", code: "nc", creature: "nimbus", label: "Clay, glasses", own: { name: "Peach", hex: "#e3a184" } },
  { id: "mote-orig", code: "mo", creature: "mote", label: "Mohair", own: { name: "Oatmeal", hex: "#d8c3a8" } },
  { id: "mote-rose", code: "mr", creature: "mote", label: "Mohair, beret", own: { name: "Rose", hex: "#d4908a" } },
  { id: "mote-velvet", code: "mv", creature: "mote", label: "Velvet, headphones", own: { name: "Charcoal", hex: "#5c555c" } },
  { id: "sprout-orig", code: "so", creature: "sprout", label: "Clay", own: { name: "Sage", hex: "#8fa58d" } },
  { id: "sprout-velvet", code: "sv", creature: "sprout", label: "Velvet, scarf", own: { name: "Butter", hex: "#e5c27e" } },
  { id: "sprout-felt", code: "sf", creature: "sprout", label: "Felt, clapperboard", own: { name: "Sky", hex: "#8fb6d6" } },
  { id: "glim-orig", code: "go", creature: "glim", label: "Velvet", own: { name: "Butter", hex: "#e8c26e" } },
  { id: "glim-felt", code: "gf", creature: "glim", label: "Felt, glasses", own: { name: "Lavender", hex: "#b49ac4" } },
  { id: "glim-clay", code: "gc", creature: "glim", label: "Clay, beret", own: { name: "Mint", hex: "#9cc7b2" } },
  { id: "pip-orig", code: "po", creature: "pip", label: "Knit, scarf", own: { name: "Sky", hex: "#8fb6d6" } },
  { id: "pip-clay", code: "pc", creature: "pip", label: "Clay, beret", own: { name: "Sage", hex: "#9aab92" } },
  { id: "pip-mohair", code: "pm", creature: "pip", label: "Mohair, headphones", own: { name: "Cream", hex: "#eadccb" } },
];

/* the four colours every look can take; a look whose own colour is one of
   them is not offered it twice */
export const SHARED: { id: Exclude<ColourId, "own">; code: string; name: string; hex: string }[] = [
  { id: "lightred", code: "red", name: "Light red", hex: "#e8857c" },
  { id: "lavender", code: "lav", name: "Lavender", hex: "#b49ac4" },
  { id: "mint", code: "mnt", name: "Mint", hex: "#9cc7b2" },
  { id: "sky", code: "sky", name: "Sky", hex: "#8fb6d6" },
];

export type Mascot = { look: string; colour: ColourId };
export const DEFAULT_MASCOT: Mascot = { look: "nimbus-felt", colour: "own" };

const lookById = new Map(LOOKS.map((l) => [l.id, l]));
const lookByCode = new Map(LOOKS.map((l) => [l.code, l]));

export const looksOf = (creature: CreatureId) => LOOKS.filter((l) => l.creature === creature);
export const lookOf = (id: string): Look => lookById.get(id) ?? lookById.get(DEFAULT_MASCOT.look)!;
export const creatureOf = (m: Mascot): CreatureId => lookOf(m.look).creature;
export const nameOf = (m: Mascot): string => CREATURES.find((c) => c.id === creatureOf(m))!.name;

/* the colours a look is rendered in: its own first, then the shared ones it
   does not already own */
export function coloursOf(lookId: string): { id: ColourId; name: string; hex: string }[] {
  const look = lookOf(lookId);
  const own = look.own.name.toLowerCase();
  return [
    { id: "own" as ColourId, name: look.own.name, hex: look.own.hex },
    ...SHARED.filter((s) => s.name.toLowerCase() !== own).map((s) => ({ id: s.id as ColourId, name: s.name, hex: s.hex })),
  ];
}

const PREFIX = "m:";
export function encodeMascot(m: Mascot): string {
  const look = lookOf(m.look);
  const colour = coloursOf(look.id).some((c) => c.id === m.colour) ? m.colour : "own";
  const code = colour === "own" ? "own" : SHARED.find((s) => s.id === colour)!.code;
  return `${PREFIX}${look.code}.${code}`;
}

/* the avatar column -> a mascot; anything that is not a mascot code (an
   emoji, a film glyph, a typo, nothing) is the default */
export function decodeMascot(avatar: string | null | undefined): Mascot {
  const m = /^m:([a-z]{2})\.([a-z]{3})$/.exec(avatar ?? "");
  const look = m ? lookByCode.get(m[1]) : undefined;
  if (!m || !look) return { ...DEFAULT_MASCOT };
  const colour = m[2] === "own" ? "own" : SHARED.find((s) => s.code === m[2])?.id;
  if (!colour || !coloursOf(look.id).some((c) => c.id === colour)) return { look: look.id, colour: "own" };
  return { look: look.id, colour };
}
export const isMascotCode = (avatar: string | null | undefined) => /^m:[a-z]{2}\.[a-z]{3}$/.test(avatar ?? "");
export const DEFAULT_AVATAR = encodeMascot(DEFAULT_MASCOT);

/* The renders live on R2 under site/mascot/<version>/<size>/. The version is
   part of the path so a redone image is a new URL, never a stale cache. A
   build can point elsewhere (a local copy while checking) with
   NEXT_PUBLIC_MASCOT_BASE. */
export const MASCOT_BASE =
  process.env.NEXT_PUBLIC_MASCOT_BASE || "https://pub-62d6d70ed50d44449d464cd43245b69d.r2.dev/site/mascot/v1";

/* 640 (2026-10-09) is the floating creature's: drawn at 320 CSS px it needs
   twice that on a sharp screen. Same frames as 128 and 320, so the three
   sizes swap in place. */
export type MascotSize = 128 | 320 | 640;
export const sizeFor = (px: number): MascotSize => (px <= 64 ? 128 : px <= 160 ? 320 : 640);
export function mascotSrc(m: Mascot, mood: Mood, size: MascotSize = 128): string {
  const look = lookOf(m.look);
  const colour = coloursOf(look.id).some((c) => c.id === m.colour) ? m.colour : "own";
  return `${MASCOT_BASE}/${size}/${look.id}-${colour}-${mood}.webp`;
}
/* a 640 image that did not load (a bucket the larger set has not reached)
   is drawn from the 320 one: softer, never broken */
export const smallerSrc = (src: string): string | null => (src.includes("/640/") ? src.replace("/640/", "/320/") : null);

/* every image the asset set holds, for the upload check */
export function allImages(): string[] {
  const out: string[] = [];
  for (const look of LOOKS)
    for (const c of coloursOf(look.id)) for (const mood of MOODS) out.push(`${look.id}-${c.id}-${mood}`);
  return out;
}

/* The face's states (assistant-avatar.tsx) as moods. "working" thinks with
   the ring filling, "needs" holds still awake beside its amber light, and
   "talking" flaps: the open-mouthed frame and the awake one in turn while a
   reply is being written. */
export type FaceState =
  | "idle"
  | "listening"
  | "thinking"
  | "working"
  | "talking"
  | "needs"
  | "success"
  | "error"
  | "sleeping";
export function moodFor(state: FaceState, flap = true): Mood {
  switch (state) {
    case "listening":
      return "listen";
    case "thinking":
    case "working":
      return "think";
    case "talking":
      return flap ? "talk" : "awake";
    case "success":
      return "made";
    case "error":
      return "oops";
    case "sleeping":
      return "sleep";
    default:
      return "awake";
  }
}

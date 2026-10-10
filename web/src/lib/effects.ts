/* Effects in the composer (src/effects.py through GET /api/effects; item 3
   of docs/tasks/task-studio-agent.md).

   An effect changes something that already exists: edit a still, animate
   one with a template or a camera move, upscale or add sound to a clip.
   Two ways one starts, and both end on the same priced card: the person
   picks it from the `/effects` gallery, or the brain proposes apply_effect.
   Neither names what it acts on -- the studio binds the source here
   (`sourcesFor`): what is attached to the box, else the newest result in
   the thread that fits. A clip can only be a result the studio made (it is
   named by its `gen:<id>`); an image can be anything the composer holds.

   Pure and import-free on purpose: tests/effects.test.mjs runs this file
   as it is. */

export const EFFECT_TOOL = "apply_effect";

export type OptionValue = string | number | boolean;
export type EffectOption = { values: OptionValue[]; default: OptionValue | null; required: boolean };
export type Effect = {
  id: string;
  label: string;
  category: string;
  /** one line for a person: what it does */
  blurb: string;
  takes: "image" | "video";
  output: "image" | "video";
  sources: { min: number; max: number };
  prompt: "required" | "optional" | "none";
  options: Record<string, EffectOption>;
  /** what it costs at its defaults; null when the clip's length decides */
  credits: number | null;
};

/** Something an effect could act on. */
export type Candidate = {
  /** what the server is sent: `gen:<id>` for a render, else the reference
   *  exactly as the composer holds it */
  ref: string;
  kind: "image" | "clip";
  /** a drawable address for the card's thumbnail (images only) */
  thumb?: string;
  /** "attached", "the last still", "the last clip" */
  from: string;
};

/** One effect, on its way to a result: saved on its turn (`Turn.effect`). */
export type EffectState = {
  id: string;
  effect: string;
  label: string;
  takes: "image" | "video";
  output: "image" | "video";
  sources: Candidate[];
  options: Record<string, OptionValue>;
  prompt: string;
  /** what Approve was pressed at: the card's line once it has run, so a
   *  finished card never has to be priced again */
  paid?: { credits: number; charged: boolean };
};

export type ResultLike = { image?: string | null; clip?: string | null; asset?: string | null };

/** What is there to act on, most deliberate first: every image attached
    to the box, then the thread's results from the newest back. A result
    is named by its render id when it has one. */
export function candidates(attached: string[], results: ResultLike[]): Candidate[] {
  const out: Candidate[] = attached.filter(Boolean).map((ref) => ({ ref, kind: "image", thumb: ref, from: "attached" }));
  let stills = 0;
  let clips = 0;
  for (const r of [...results].reverse()) {
    if (r.clip) {
      // a clip is only ever named by id: one with no id cannot be a source
      if (r.asset) out.push({ ref: r.asset, kind: "clip", from: clips++ ? "an earlier clip" : "the last clip" });
    } else if (r.image) {
      out.push({ ref: r.asset || r.image, kind: "image", thumb: r.image, from: stills++ ? "an earlier still" : "the last still" });
    }
  }
  return out;
}

const wants = (e: Pick<Effect, "takes">) => (e.takes === "video" ? "clip" : "image");

/** The sources an effect is bound to: everything attached that fits, up to
    what it takes; with nothing attached, the newest result that fits. */
export function sourcesFor(effect: Pick<Effect, "takes" | "sources">, all: Candidate[]): Candidate[] {
  const fits = all.filter((c) => c.kind === wants(effect));
  const attached = fits.filter((c) => c.from === "attached");
  if (attached.length) return attached.slice(0, effect.sources.max);
  return fits.slice(0, Math.max(1, effect.sources.min));
}

/** Can this effect start at all, given what is there? "" or the reason. */
export function unavailable(effect: Pick<Effect, "takes" | "sources">, all: Candidate[]): string {
  const have = sourcesFor(effect, all).length;
  if (have >= effect.sources.min) return "";
  if (effect.takes === "video") return "Needs a clip: animate a still first, then finish the clip it makes";
  return effect.sources.min > 1 ? `Needs ${effect.sources.min} images attached` : "Needs an image: attach one, or make a still first";
}

/** The options an effect starts with: its defaults. A required option
    with no default is left for the person to pick. */
export function defaults(effect: Pick<Effect, "options">): Record<string, OptionValue> {
  const out: Record<string, OptionValue> = {};
  for (const [name, o] of Object.entries(effect.options)) {
    if (o.default !== null && o.default !== undefined) out[name] = o.default;
  }
  return out;
}

/** A proposal's options, held to the table: an unknown name or a value
    that is not legal is dropped (the server would refuse it), and the
    defaults fill what is left. */
export function settle(effect: Pick<Effect, "options">, given: Record<string, unknown> | null | undefined): Record<string, OptionValue> {
  const out = defaults(effect);
  for (const [name, value] of Object.entries(given ?? {})) {
    const legal = effect.options[name]?.values.find((v) => String(v) === String(value));
    if (legal !== undefined) out[name] = legal;
  }
  return out;
}

const OPTION_LABELS: Record<string, string> = {
  effect_scene: "Template",
  effect: "Template",
  camera_movement: "Camera move",
  resolution: "Resolution",
  duration: "Length",
  aspect_ratio: "Shape",
  style: "Style",
  upscale_factor: "Upscale",
  target_fps: "Frame rate",
  subject_is_person: "Subject is a person",
  refine_foreground_edges: "Refine edges",
  background_color: "Background",
  output_container_and_codec: "File type",
};

/** "camera_movement" -> "Camera move" */
export const optionLabel = (name: string) => OPTION_LABELS[name] ?? sentence(name);

function sentence(raw: string): string {
  const words = raw.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "";
}

/** A value as a person reads it: "bloom_bloom" -> "Bloom bloom", a length
    in seconds, a multiple, yes / no. */
export function valueLabel(name: string, value: OptionValue): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (name === "duration") return `${value}s`;
  if (name === "upscale_factor") return value === 1 || value === "1" ? "Keep the size" : `${value}x`;
  if (name === "target_fps") return `${value} fps`;
  if (name === "resolution" || name === "aspect_ratio") return String(value);
  return sentence(String(value));
}

/** What still stops this effect from being approved: "" when nothing does.
    The server checks all of it again; this is only said sooner. */
export function missing(effect: Pick<Effect, "sources" | "prompt" | "options" | "takes">, state: Pick<EffectState, "sources" | "options" | "prompt">): string {
  if (state.sources.length < effect.sources.min) {
    return effect.takes === "video" ? "Needs a clip to work on" : "Needs an image to work on";
  }
  for (const [name, o] of Object.entries(effect.options)) {
    if (o.required && (state.options[name] === undefined || state.options[name] === "")) {
      return `Pick a ${optionLabel(name).toLowerCase()}`;
    }
  }
  if (effect.prompt === "required" && !state.prompt.trim()) {
    return effect.takes === "video" ? "Say what it should sound like" : "Say what to change";
  }
  return "";
}

/** "A still in, a clip out" */
export function takesLine(effect: Pick<Effect, "takes" | "output" | "sources">): string {
  const input = effect.takes === "video" ? "A clip" : effect.sources.max > 1 ? `Up to ${effect.sources.max} images` : "A still";
  return `${input} in, ${effect.output === "video" ? "a clip" : "an image"} out`;
}

/** What the gallery says an effect costs before anything is picked. */
export function fromPrice(effect: Pick<Effect, "credits">, exempt: boolean): string {
  if (effect.credits === null) return "Priced by the clip's length";
  return exempt ? `${effect.credits.toLocaleString()} credits · not charged` : `From ${effect.credits.toLocaleString()} credits`;
}

/** The body both effect routes take. */
export function requestOf(state: EffectState) {
  return {
    effect: state.effect,
    sources: state.sources.map((s) => s.ref),
    prompt: state.prompt.trim(),
    options: state.options,
  };
}

/** A new effect, bound to its sources and its starting options. */
export function begin(
  effect: Effect,
  all: Candidate[],
  id: string,
  given: { options?: Record<string, unknown> | null; prompt?: string | null } = {},
): EffectState {
  return {
    id,
    effect: effect.id,
    label: effect.label,
    takes: effect.takes,
    output: effect.output,
    sources: sourcesFor(effect, all),
    options: settle(effect, given.options),
    prompt: effect.prompt === "none" ? "" : (given.prompt ?? "").trim(),
  };
}

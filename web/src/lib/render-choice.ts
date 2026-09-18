/* The Queue card's renderer pick, as pure functions (2026-09-17).

   Ported from app/static/zpf/queue.js so the React Queue and the vanilla
   one cannot disagree about what a card opens on or what its button says:

   - `usable` needs BOTH a vendor key and a reachable model. Runway's models
     always report available (render_specs has no per-account probe), so
     reading only the model let a keyless vendor win the default.
   - `firstUsable` is the CHEAPEST usable model at its own default length,
     not the first in registry order -- the registry lists Veo second, and a
     card quietly defaulting to a $3 preview render because Runway had no
     key is a silent spend. Unpriced models sort last.
   - `defaultPick`: the plan leads when this account can render it, else
     the cheapest it can; a plan nobody can render is not a default (the
     2026-09-11 dead-Runway-button fix).
   - `held` keeps a pick by concept id for the life of the tab, so it
     survives repaints AND leaving the page and coming back. Dropped once
     the card is approved or rejected.
   - `estimate` is a LABEL, not an invoice: the server's
     check_render_choice / check_timeline_choice is authoritative and
     answers on the approve. tests/test_providers.py pins this shape
     (flat, or a per-second rate optionally keyed by frame) to the adapters.
   - A TIMED scene is priced by the SERVER (src/pricing.py): each shot
     renders at its window's length fitted UP to what the model can make,
     and that fitting is done once, on the server, never here -- the
     listing serves `quote` for the card's default pick and /quote answers
     any other. `planFor` takes that quote; without one it says "pricing…"
     rather than make a number up. There is no fitSeconds twin any more.

   No "@/..." imports: tests/render-choice.test.mjs loads this with node. */

export type AxisLike = {
  kind: "choices" | "range" | "fixed";
  values?: (string | number)[];
  min?: number;
  max?: number;
  default?: string | number | null;
  note?: string;
};
export type PriceLike = { kind: string; usd?: number | null; usd_by_frame?: Record<string, number> };
export type ModelLike = { id: string; label: string; available?: boolean; duration: AxisLike; frame: AxisLike; price?: PriceLike };
export type RendererLike = { label: string; available: boolean; frame_axis?: string; models: ModelLike[] };
export type Renderers = Record<string, RendererLike>;
export type Pick = { provider: string; model: string; duration: number | null; frame: string | null };
export type PartLike = { seconds?: number | null; media_url?: string | null };

export const held = new Map<number, Pick>();

export const specOf = (renderers: Renderers, provider?: string, model?: string): ModelLike | null =>
  (provider && renderers[provider]?.models?.find((m) => m.id === model)) || null;

export const usable = (renderers: Renderers, provider?: string, model?: string): boolean => {
  const r = provider ? renderers[provider] : undefined;
  const spec = specOf(renderers, provider, model);
  return !!(r && r.available && spec && spec.available !== false);
};

export const axisDefault = (axis?: AxisLike): string | number | null =>
  !axis ? null : axis.kind === "range" ? (axis.default ?? axis.min ?? null) : (axis.default ?? axis.values?.[0] ?? null);

const asPick = (provider: string, spec: ModelLike): Pick => {
  const duration = axisDefault(spec.duration);
  const frame = axisDefault(spec.frame);
  return { provider, model: spec.id, duration: duration === null ? null : Number(duration), frame: frame === null ? null : String(frame) };
};

export function estimate(spec: ModelLike | null, frame: string | null, seconds: number | null): number | null {
  const price = spec?.price;
  if (!price) return null;
  if (price.kind === "flat") return price.usd ?? null;
  const per = price.usd_by_frame && frame !== null ? price.usd_by_frame[frame] : price.usd;
  return per === undefined || per === null || seconds === null ? null : per * seconds;
}

export function firstUsable(renderers: Renderers): Pick | null {
  let best: { pick: Pick; cost: number } | null = null;
  for (const [name, r] of Object.entries(renderers)) {
    // a vendor with no key is not usable, however many models it lists
    if (!r.available) continue;
    for (const m of r.models || []) {
      if (m.available === false) continue;
      const pick = asPick(name, m);
      const usd = estimate(m, pick.frame, pick.duration);
      const cost = usd === null ? Infinity : usd;
      if (!best || cost < best.cost) best = { pick, cost };
    }
  }
  return best && best.pick;
}

export function defaultPick(renderers: Renderers, want?: { provider?: string; model?: string } | null): Pick | null {
  const planned = specOf(renderers, want?.provider, want?.model);
  if (planned && usable(renderers, want?.provider, want?.model)) return asPick(want!.provider!, planned);
  return firstUsable(renderers) || (planned ? asPick(want!.provider!, planned) : null);
}

/** The pick a card shows: the held one while it is still usable, else the default. */
export function pickFor(renderers: Renderers, id: number, want?: { provider?: string; model?: string } | null): Pick | null {
  const kept = held.get(id);
  if (kept && usable(renderers, kept.provider, kept.model)) return kept;
  return defaultPick(renderers, want);
}

/** Changing the model takes the NEW model's defaults, never the old values:
 *  20s is legal on LTX and refused by Runway. */
export function withModel(renderers: Renderers, provider: string, model: string): Pick | null {
  const spec = specOf(renderers, provider, model);
  return spec ? asPick(provider, spec) : null;
}

export function legalDuration(axis: AxisLike, seconds: number): boolean {
  if (!Number.isFinite(seconds)) return false;
  if (axis.kind === "range") return seconds >= (axis.min ?? -Infinity) && seconds <= (axis.max ?? Infinity);
  return (axis.values || []).map(Number).includes(seconds);
}

export type Plan = { timed: boolean; n: number; lengths: number[]; usd: number | null; pending?: boolean; refused?: string };
/** the server's price for a pick (pricing.display), or its refusal */
export type QuoteLike = { error?: string; timed?: boolean; durations?: number[]; estimate_usd?: number } | null | undefined;

/** What an approve would make and cost. `parts` is the scene's timeline
 *  (null for a scene that renders whole). A timed scene's lengths and
 *  price are the server's `quote` for THIS pick: shots that already have
 *  a clip are not in it, as the server's resume skips them. */
export function planFor(spec: ModelLike, pick: Pick, parts: PartLike[] | null | undefined, quote?: QuoteLike): Plan {
  if (!parts || !parts.length) {
    return { timed: false, n: 1, lengths: [pick.duration ?? 0], usd: estimate(spec, pick.frame, pick.duration) };
  }
  const todo = parts.filter((p) => !p.media_url);
  if (!quote || quote.error || !quote.timed || !quote.durations) {
    return { timed: true, n: todo.length, lengths: [], usd: null, pending: !quote, refused: quote?.error ?? "" };
  }
  return { timed: true, n: quote.durations.length, lengths: quote.durations, usd: quote.estimate_usd ?? null };
}

export const approveText = (plan: Plan): string =>
  `Approve · ${plan.n} shot${plan.n === 1 ? "" : "s"} · ${plan.refused ? "refused" : plan.pending ? "pricing…" : plan.usd === null ? "unpriced" : "~$" + plan.usd.toFixed(2)}`;

export const chipText = (spec: ModelLike, pick: Pick, plan: Plan): string =>
  `${spec.label} · ${plan.timed ? `${plan.n} shot${plan.n === 1 ? "" : "s"}` : `${pick.duration}s`} · ${pick.frame ?? "—"}`.toUpperCase();

/* The Queue card's renderer pick, as pure functions (2026-09-17).

   Ported from app/static/zpf/queue.js so the React Queue and the vanilla
   one cannot disagree about what a card opens on or what its button says:

   - `usable` needs BOTH a configured renderer and a reachable model. A
     model always reports available (render_specs has no per-account
     probe), so reading only the model let an unconfigured renderer win the
     default. Since 2026-09-26 the only renderer is fal.ai, on the
     operator's key; the catalogue stays keyed by provider regardless.
   - `firstUsable` is the CHEAPEST usable model at its own default length,
     not the first in registry order -- a card quietly defaulting to a $3
     Veo render is a silent spend. Unpriced models sort last.
   - `defaultPick`: the plan leads when this account can render it, else
     the cheapest it can; a plan nobody can render is not a default (the
     2026-09-11 dead-button fix).
   - `held` keeps a pick by concept id for the life of the tab, so it
     survives repaints AND leaving the page and coming back. Dropped once
     the card is approved or rejected.
   - `estimate` ORDERS models, it is never shown: `firstUsable` sorts by
     it to find the cheapest. tests/test_providers.py pins this shape
     (flat, or a per-second rate optionally keyed by frame) to the adapters.
     The studio shows CREDITS, never dollars (2026-10-08): every number a
     person reads is the server's (pricing.display), and a pick it has not
     priced yet says "pricing…".
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
export type ModelLike = {
  id: string;
  label: string;
  available?: boolean;
  duration: AxisLike;
  frame: AxisLike;
  price?: PriceLike;
  /** the frame a DRAFT renders at -- the catalogue says (src/drafts.py) --
   *  or null when this model has no cheaper tier than its default */
  draft?: string | null;
};
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
    // an unconfigured renderer is not usable, however many models it lists
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
 *  10s is legal on LTX and refused by Veo. */
export function withModel(renderers: Renderers, provider: string, model: string): Pick | null {
  const spec = specOf(renderers, provider, model);
  return spec ? asPick(provider, spec) : null;
}

export function legalDuration(axis: AxisLike, seconds: number): boolean {
  if (!Number.isFinite(seconds)) return false;
  if (axis.kind === "range") return seconds >= (axis.min ?? -Infinity) && seconds <= (axis.max ?? Infinity);
  return (axis.values || []).map(Number).includes(seconds);
}

export type Plan = {
  timed: boolean;
  n: number;
  lengths: number[];
  /** what it costs THIS account in credits (the server's quote, markup
   *  included); null only when not priced yet. There is no dollar field:
   *  the studio never shows the provider's cost (2026-10-08). */
  credits: number | null;
  pending?: boolean;
  refused?: string;
};
/** the server's price for a pick (pricing.display), or its refusal */
export type QuoteLike = {
  error?: string;
  timed?: boolean;
  durations?: number[];
  credits?: number | null;
} | null | undefined;

/** What an approve would make and cost. `parts` is the scene's timeline
 *  (null for a scene that renders whole). A timed scene's lengths and
 *  price are the server's `quote` for THIS pick: shots that already have
 *  a clip are not in it, as the server's resume skips them.
 *
 *  CREDITS COME ONLY FROM THE SERVER (2026-09-25). The credit price is
 *  pricing.credits_for -- markup, rounding up, a floor per render -- and
 *  this file does not keep a second copy of that rule. `quote`:
 *    - a quote: its credits are the button's number
 *    - null or undefined: not answered yet -- "pricing…", never a guess.
 *      (Until 2026-10-08 an undefined quote fell back to the rate card's
 *      dollar label; the studio shows no dollars now.) */
export function planFor(spec: ModelLike, pick: Pick, parts: PartLike[] | null | undefined, quote?: QuoteLike): Plan {
  if (!parts || !parts.length) {
    const base = { timed: false, n: 1, lengths: [pick.duration ?? 0] };
    if (!quote) return { ...base, credits: null, pending: true };
    if (quote.error) return { ...base, credits: null, refused: quote.error };
    return { ...base, credits: quote.credits ?? null };
  }
  const todo = parts.filter((p) => !p.media_url);
  if (!quote || quote.error || !quote.timed || !quote.durations) {
    return { timed: true, n: todo.length, lengths: [], credits: null, pending: !quote, refused: quote?.error ?? "" };
  }
  return { timed: true, n: quote.durations.length, lengths: quote.durations, credits: quote.credits ?? null };
}

/** Beside a credit price on an exempt (operator) account. */
export const NOT_CHARGED = " · not charged";

export const creditsText = (credits: number, exempt = false): string =>
  `${credits.toLocaleString("en-US")} credit${credits === 1 ? "" : "s"}${exempt ? NOT_CHARGED : ""}`;

/** The price half of the button: the server's credits, or "pricing…"
 *  until it answers -- never a dollar figure (2026-10-08). "cr" rather than
 *  "credits" because the button is 22px Bebas in a card a third of the
 *  page wide -- the /models page abbreviates the same way. An exempt
 *  account still sees the price (it is still what the render costs) with
 *  "not charged" beside it, so the button agrees with the shell's pill. */
export const priceText = (plan: Plan, exempt = false): string =>
  plan.refused
    ? "refused"
    : plan.credits !== null && !plan.pending
      ? `${plan.credits.toLocaleString("en-US")} cr${exempt ? NOT_CHARGED : ""}`
      : "pricing…";

export const approveText = (plan: Plan, exempt = false, draft = false): string =>
  `${draft ? "Draft" : "Approve"} · ${plan.n} shot${plan.n === 1 ? "" : "s"} · ${priceText(plan, exempt)}`;

/* ── draft, then finish (2026-10-11; src/drafts.py) ──
   A draft is this same approve at the model's cheapest frame. The catalogue
   says which frame that is; nothing here knows a price. */

/** The frame a draft of this model renders at, or null: no draft offered. */
export const draftFrame = (spec: ModelLike | null | undefined): string | null => {
  const d = spec?.draft;
  return d && (spec.frame.values || []).map(String).includes(d) ? d : null;
};
/** Is this pick the model's draft? */
export const isDraft = (spec: ModelLike | null | undefined, pick: Pick | null | undefined): boolean =>
  !!pick?.frame && draftFrame(spec) === pick.frame;
/** Draft on: the draft frame. Off: back to the frame the model renders at
 *  by default. A model with no draft is left as it is. */
export const withDraft = (spec: ModelLike, pick: Pick, on: boolean): Pick => {
  const d = draftFrame(spec);
  if (!d) return pick;
  return { ...pick, frame: on ? d : spec.frame.default != null ? String(spec.frame.default) : pick.frame };
};

export const chipText = (spec: ModelLike, pick: Pick, plan: Plan): string =>
  `${spec.label} · ${plan.timed ? `${plan.n} shot${plan.n === 1 ? "" : "s"}` : `${pick.duration}s`} · ${pick.frame ?? "—"}`.toUpperCase();

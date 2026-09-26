// The public pricing data, GENERATED: web/src/content/pricing.json is what
// `python -m src.pricing export` writes off src/pricing.py, and
// tests/test_plans.py fails the build when the two disagree. Nothing on
// the site types a number by hand -- a plan, a markup, a rate card or a
// band changes in Python and is re-exported here.
import catalog from "@/content/pricing.json";

export type Tier = "standard" | "creator" | "premium";

export type Plan = {
  key: string;
  name: string;
  tier: Tier;
  monthly_usd: number;
  yearly_usd: number;
  yearly_monthly_usd: number;
  credits: number;
  blurb: string;
  popular: boolean;
};

export type Interval = "month" | "year";

export type CatalogModel = {
  provider: string;
  model: string;
  name: string;
  blurb: string;
  tier: Tier;
  max_seconds: number | null;
  seconds: number;
  credits: number;
  frame: string;
};

export type Catalog = {
  pricing_version: string;
  credit_cents: number;
  markup: string;
  credit_floor: number;
  expiry_months: number;
  clip_seconds: number;
  yearly_discount: string;
  tiers: Tier[];
  plans: Plan[];
  topup: { key: string; name: string; usd: number; credits: number };
  models: CatalogModel[];
};

export const CATALOG = catalog as Catalog;
export const PLANS = CATALOG.plans;
export const MODELS = CATALOG.models;
export const TOPUP = CATALOG.topup;

export const TIER_LABEL: Record<Tier, string> = {
  standard: "Standard",
  creator: "Creator",
  premium: "Premium",
};

/** May a plan on `tier` render a model banded `model`? Ascending order. */
export function tierAllows(tier: Tier, model: Tier): boolean {
  return CATALOG.tiers.indexOf(model) <= CATALOG.tiers.indexOf(tier);
}

/** The models a plan unlocks beyond the tier below it. */
export function modelsAddedBy(tier: Tier): CatalogModel[] {
  return MODELS.filter((m) => m.tier === tier);
}

export function modelsFor(tier: Tier): CatalogModel[] {
  return MODELS.filter((m) => tierAllows(tier, m.tier));
}

/** How many clips of `model` a month's allowance buys. */
export function clipsPerMonth(plan: Plan, model: CatalogModel): number {
  return Math.floor(plan.credits / model.credits);
}

/** A "720:1280" ratio form and a "720p" resolution read the same. */
export function frameLabel(frame: string): string {
  if (/^\d+p$/.test(frame)) return frame;
  const m = frame.match(/^(\d+):(\d+)$/);
  if (m) return `${Math.min(Number(m[1]), Number(m[2]))}p`;
  if (/^\d+$/.test(frame)) return `${frame}p`;
  return frame;
}

/** The per-month figure a card prints at an interval. */
export function monthlyAt(plan: Plan, interval: Interval): number {
  return interval === "year" ? plan.yearly_monthly_usd : plan.monthly_usd;
}

export function discountPercent(): number {
  return Math.round(Number(CATALOG.yearly_discount) * 100);
}

export function usd(n: number): string {
  return `$${n.toLocaleString("en-US")}`;
}

export function num(n: number): string {
  return n.toLocaleString("en-US");
}

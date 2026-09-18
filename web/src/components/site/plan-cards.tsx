"use client";

import { Suspense, useState } from "react";
import { Check } from "lucide-react";
import { PlanButton } from "@/components/site/plan-button";
import {
  CATALOG,
  MODELS,
  PLANS,
  TOPUP,
  TIER_LABEL,
  clipsPerMonth,
  discountPercent,
  modelsAddedBy,
  monthlyAt,
  num,
  tierAllows,
  usd,
  type Interval,
  type Plan,
} from "@/lib/catalog";

// The monthly / yearly switch and the three cards under it. A client
// component only because the toggle is state; every number still comes
// from the generated catalog. Yearly is twelve months at the discount,
// billed once, with the allowance landing month by month (docs/BILLING.md).

function illustrate(plan: Plan) {
  const allowed = MODELS.filter((m) => tierAllows(plan.tier, m.tier));
  const cheapest = allowed.reduce((a, b) => (a.credits <= b.credits ? a : b));
  const dearest = allowed.reduce((a, b) => (a.credits >= b.credits ? a : b));
  return { cheapest, dearest };
}

function planFeatures(plan: Plan): string[] {
  const idx = CATALOG.tiers.indexOf(plan.tier);
  const below = idx > 0 ? PLANS[idx - 1] : null;
  const added = modelsAddedBy(plan.tier).map((m) => m.name);
  const features: string[] = [];
  if (below) features.push(`Everything in ${below.name}`);
  if (added.length) features.push(added.join(", "));
  if (!below) {
    features.push("Keyframes drawn on every pick");
    features.push("The Director canvas and the Queue");
    features.push("Bring your own renderer key — those renders cost no credits");
  }
  features.push(`Top up ${num(TOPUP.credits)} credits for ${usd(TOPUP.usd)} any time`);
  return features;
}

export function IntervalToggle({
  value,
  onChange,
}: {
  value: Interval;
  onChange: (v: Interval) => void;
}) {
  const pct = discountPercent();
  return (
    <div
      role="radiogroup"
      aria-label="Billing interval"
      className="inline-flex items-center gap-1 rounded-lg border border-border bg-card p-1"
    >
      {(["month", "year"] as Interval[]).map((v) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={value === v}
          onClick={() => onChange(v)}
          className={`rounded-md px-3.5 py-1.5 text-[13.5px] font-medium tracking-[-0.005em] transition-colors ${
            value === v ? "bg-foreground text-background" : "text-[#c6c4c0] hover:text-foreground"
          }`}
        >
          {v === "month" ? "Monthly" : "Yearly"}
          {v === "year" && (
            <span className={`ml-1.5 text-[11px] ${value === v ? "text-background/70" : "text-[#1f9d64]"}`}>
              −{pct}%
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function PlanCards() {
  const [interval, setInterval] = useState<Interval>("month");
  return (
    <>
      <div className="mb-8 flex justify-center">
        <IntervalToggle value={interval} onChange={setInterval} />
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {PLANS.map((plan) => {
          const { cheapest, dearest } = illustrate(plan);
          const perMonth = monthlyAt(plan, interval);
          return (
            <article
              key={plan.key}
              className={`relative flex flex-col rounded-[14px] border bg-card p-7 ${
                plan.popular ? "border-foreground/40" : "border-border"
              }`}
            >
              {plan.popular && (
                <span className="absolute -top-3 left-7 rounded-md bg-foreground px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-background">
                  Popular
                </span>
              )}
              <h2 className="serif text-[28px]">{plan.name}</h2>
              <p className="mt-2 min-h-[2.75rem] text-[15px] leading-relaxed text-[#afafaf]">{plan.blurb}</p>
              <div className="mt-6 flex items-baseline gap-2">
                {interval === "year" && (
                  <span className="serif text-[26px] leading-none text-[#565553] line-through">
                    {usd(plan.monthly_usd)}
                  </span>
                )}
                <span className="serif text-[44px] leading-none">{usd(perMonth)}</span>
                <span className="text-sm text-[#82807d]">/month</span>
              </div>
              <p className="mt-2 min-h-[1.25rem] text-[13px] text-[#82807d]">
                {interval === "year"
                  ? `Billed yearly, ${usd(plan.yearly_usd)}. Save ${usd(plan.monthly_usd * 12 - plan.yearly_usd)}/year.`
                  : "Billed monthly. Cancel any time."}
              </p>
              <p className="mt-3 text-sm font-medium text-foreground">
                {num(plan.credits)} credits <span className="text-[#82807d]">/ month</span>
              </p>
              <p className="mt-1 text-[13px] leading-relaxed text-[#82807d]">
                ≈ {clipsPerMonth(plan, cheapest)} × {CATALOG.clip_seconds}s on {cheapest.name}, or{" "}
                {clipsPerMonth(plan, dearest)} on {dearest.name}.
              </p>
              <div className="mt-7">
                <Suspense fallback={null}>
                  <PlanButton
                    item={plan.key}
                    interval={interval}
                    label={`Get ${plan.name}`}
                    variant={plan.popular ? "default" : "outline"}
                  />
                </Suspense>
              </div>
              <ul className="mt-7 flex flex-col gap-2.5 border-t border-border pt-6 text-[14px] leading-snug text-[#c6c4c0]">
                {planFeatures(plan).map((f) => (
                  <li key={f} className="flex items-start gap-2.5">
                    <Check className="mt-0.5 size-3.5 shrink-0 text-foreground" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-6 text-[12px] text-[#82807d]">
                {TIER_LABEL[plan.tier]} tier · credits expire {CATALOG.expiry_months} months after they land
                {interval === "year" ? " · a year's allowance lands month by month" : ""}
              </p>
            </article>
          );
        })}
      </div>
    </>
  );
}

import type { Metadata } from "next";
import { Suspense } from "react";
import { Check } from "lucide-react";
import { EditorialSkin } from "@/components/editorial-skin";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { PageIntro } from "@/components/site/page-intro";
import { PlanButton } from "@/components/site/plan-button";
import { CheckoutNotice } from "@/components/site/checkout-notice";
import { FaqList } from "@/components/site/faq-list";
import {
  CATALOG,
  MODELS,
  PLANS,
  TOPUP,
  TIER_LABEL,
  clipsPerMonth,
  modelsAddedBy,
  num,
  tierAllows,
  usd,
  type Plan,
} from "@/lib/catalog";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Three plans, one peg: a credit is a cent, and a render costs what the model you pick costs. Every price on this page is the number the Queue charges.",
};

// The two models a plan's allowance is illustrated with: the cheapest
// standard one and the most expensive the plan can reach.
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
  if (added.length) features.push(`${added.join(", ")}`);
  if (!below) {
    features.push("Keyframes drawn on every pick");
    features.push("The Director canvas and the Queue");
    features.push("Bring your own renderer key — those renders cost no credits");
  }
  features.push(`Top up ${num(TOPUP.credits)} credits for ${usd(TOPUP.usd)} any time`);
  return features;
}

export default function PricingPage() {
  return (
    <EditorialSkin>
      <SiteHeader />
      <main className="flex-1">
        <PageIntro
          eyebrow="Pricing"
          title="Pick your plan."
          dek="One credit is one cent. A render costs what the model you pick costs, and the number on the Queue card is the number you're charged — never more."
        >
          <Suspense fallback={null}>
            <CheckoutNotice />
          </Suspense>
        </PageIntro>

        {/* the cards */}
        <section className="mx-auto max-w-[1200px] px-6 pb-20">
          <div className="grid gap-3 md:grid-cols-3">
            {PLANS.map((plan) => {
              const { cheapest, dearest } = illustrate(plan);
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
                  <div className="mt-6 flex items-baseline gap-1.5">
                    <span className="serif text-[44px] leading-none">{usd(plan.monthly_usd)}</span>
                    <span className="text-sm text-[#82807d]">/month</span>
                  </div>
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
                  </p>
                </article>
              );
            })}
          </div>

          <div className="mt-3 flex flex-col gap-4 rounded-[14px] border border-border bg-card p-6 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="serif text-2xl">Top up</h2>
              <p className="mt-1 text-[15px] text-[#afafaf]">
                {num(TOPUP.credits)} credits for {usd(TOPUP.usd)}, one time, on any plan. Purchased credit is spent
                after your monthly allowance.
              </p>
            </div>
            <div className="w-full md:w-56">
              <Suspense fallback={null}>
                <PlanButton item={TOPUP.key} label={`Buy ${num(TOPUP.credits)} credits`} variant="outline" />
              </Suspense>
            </div>
          </div>
        </section>

        {/* compare */}
        <section className="border-t border-border">
          <div className="mx-auto max-w-[1200px] px-6 py-20">
            <div className="max-w-[640px]">
              <span className="eyebrow">Compare models across plans</span>
              <h2 className="serif mt-5 text-[clamp(2rem,4.2vw,3.25rem)]">What a month buys.</h2>
              <p className="mt-5 text-[17px] leading-relaxed text-[#afafaf]">
                Clips per month, at {CATALOG.clip_seconds} seconds each, priced by the same tables the Queue prices
                with. A dash means the plan doesn&apos;t reach that model.
              </p>
            </div>
            <div className="mt-10 overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-[12px] uppercase tracking-[0.06em] text-[#82807d]">
                    <th className="py-3 pr-4 font-medium">Model</th>
                    <th className="py-3 pr-4 font-medium">Credits / clip</th>
                    {PLANS.map((p) => (
                      <th key={p.key} className="py-3 pr-4 font-medium text-foreground">
                        {p.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MODELS.map((m) => (
                    <tr key={m.model} className="border-b border-border">
                      <td className="py-3.5 pr-4">
                        <span className="font-medium text-foreground">{m.name}</span>
                        <span className="ml-2 text-[12px] text-[#82807d]">{TIER_LABEL[m.tier]}</span>
                      </td>
                      <td className="py-3.5 pr-4 text-[#c6c4c0]">
                        {num(m.credits)} / {m.seconds}s
                      </td>
                      {PLANS.map((p) => (
                        <td key={p.key} className="py-3.5 pr-4 text-[#c6c4c0]">
                          {tierAllows(p.tier, m.tier) ? `${num(clipsPerMonth(p, m))} clips` : "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* billing faq */}
        <section className="border-t border-border">
          <div className="mx-auto max-w-[760px] px-6 py-20">
            <span className="eyebrow">Billing</span>
            <h2 className="serif mt-5 text-[clamp(2rem,4.2vw,3.25rem)]">Questions about credits.</h2>
            <div className="mt-10">
              <FaqList items={BILLING_FAQ} />
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </EditorialSkin>
  );
}

const BILLING_FAQ = [
  {
    q: "How do credits work?",
    a: (
      <p>
        One credit is one US cent. When you approve a render in the Queue, the card shows its price in credits;
        that exact amount is held from your balance, the clip renders, and the hold settles. The price is the
        model&apos;s own rate for the length you picked, so a {CATALOG.clip_seconds}-second LTX clip and a
        {CATALOG.clip_seconds}-second Veo clip cost very different amounts — the table above is the honest map.
      </p>
    ),
  },
  {
    q: "What happens when a render fails?",
    a: (
      <p>
        The hold is released back to your balance automatically. You are only charged for a clip that came
        back.
      </p>
    ),
  },
  {
    q: "Do credits roll over or expire?",
    a: (
      <p>
        Every grant is its own lot with its own clock: credit expires {CATALOG.expiry_months} months after it
        lands, and your monthly allowance is spent before any credit you bought as a top-up. If a subscription
        ends, its remaining allowance ends with it.
      </p>
    ),
  },
  {
    q: "Can I use my own renderer keys?",
    a: (
      <p>
        Yes. Add a Runway, fal, Higgsfield or Google key in the Queue&apos;s renderer keys panel and renders on
        that key cost no credits at all — the provider bills you directly. Plans still decide which models the
        studio quotes for you.
      </p>
    ),
  },
  {
    q: "Is writing scenes metered?",
    a: (
      <p>
        No. Writing scenes, drawing keyframes on a pick, the research scout and the reference library are part
        of the subscription. Credits are spent on one thing: the clip you approve.
      </p>
    ),
  },
  {
    q: "How do I change or cancel a plan?",
    a: (
      <p>
        From the billing portal in your account, any time. Changes take effect on the next invoice; a cancelled
        plan stays active until the end of the period you paid for.
      </p>
    ),
  },
];

import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { EditorialSkin } from "@/components/editorial-skin";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { PageIntro } from "@/components/site/page-intro";
import { Button } from "@/components/ui/button";
import { CATALOG, MODELS, PLANS, TIER_LABEL, frameLabel, num, type Tier } from "@/lib/catalog";

export const metadata: Metadata = {
  title: "Models",
  description:
    "Every video model the Queue can dispatch to — Runway, Kling, LTX, Wan, Seedance, Veo — with the tier that unlocks it and what a clip costs.",
};

const TIER_BLURB: Record<Tier, string> = {
  standard: "On every plan. Fast, cheap, and where most scenes should start.",
  creator: "Creator and up. Stronger motion and people, audio on Seedance.",
  premium: "Studio only. The most expensive clip in the studio, and the best.",
};

export default function ModelsPage() {
  return (
    <EditorialSkin>
      <SiteHeader />
      <main className="flex-1">
        <PageIntro
          eyebrow="Models"
          title="One Queue, every model."
          dek="Pick the renderer per approve. The studio writes the scene once, draws the keyframe once, and sends it to whichever model you chose — with the price on the card before you press it."
        />

        <section className="mx-auto max-w-[1200px] px-6 pb-20">
          {CATALOG.tiers.map((tier) => {
            const rows = MODELS.filter((m) => m.tier === tier);
            const plan = PLANS.find((p) => p.tier === tier);
            if (!rows.length) return null;
            return (
              <div key={tier} className="border-t border-border py-12 first:border-t-0 first:pt-0">
                <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                  <div className="max-w-[560px]">
                    <span className="eyebrow">{TIER_LABEL[tier]} tier</span>
                    <p className="mt-3 text-[17px] leading-relaxed text-[#afafaf]">{TIER_BLURB[tier]}</p>
                  </div>
                  {plan && (
                    <p className="text-sm text-[#82807d]">
                      Unlocked by <span className="text-foreground">{plan.name}</span>
                    </p>
                  )}
                </div>
                <div className="mt-6 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                  {rows.map((m) => (
                    <article
                      key={m.model}
                      className="flex flex-col justify-between rounded-[14px] border border-border bg-card p-6 transition-colors hover:border-[#343331]"
                    >
                      <div>
                        <h2 className="serif text-2xl">{m.name}</h2>
                        <p className="mt-2 text-[15px] leading-relaxed text-[#afafaf]">{m.blurb}</p>
                      </div>
                      <dl className="mt-6 grid grid-cols-3 gap-3 border-t border-border pt-4 text-[13px]">
                        <div>
                          <dt className="text-[#82807d]">Per clip</dt>
                          <dd className="mt-1 font-medium text-foreground">
                            {num(m.credits)} cr <span className="text-[#82807d]">/ {m.seconds}s</span>
                          </dd>
                        </div>
                        <div>
                          <dt className="text-[#82807d]">Frame</dt>
                          <dd className="mt-1 font-medium text-foreground">{frameLabel(m.frame)}</dd>
                        </div>
                        <div>
                          <dt className="text-[#82807d]">Max length</dt>
                          <dd className="mt-1 font-medium text-foreground">
                            {m.max_seconds ? `${m.max_seconds}s` : "model's own"}
                          </dd>
                        </div>
                      </dl>
                    </article>
                  ))}
                </div>
              </div>
            );
          })}
        </section>

        <section className="border-t border-border">
          <div className="mx-auto grid max-w-[1200px] gap-10 px-6 py-20 md:grid-cols-2 md:gap-16">
            <div>
              <span className="eyebrow">Keyframes</span>
              <h2 className="serif mt-5 text-[clamp(1.75rem,3.5vw,2.5rem)]">Every clip anchors on a still you approved.</h2>
              <p className="mt-5 text-[17px] leading-relaxed text-[#afafaf]">
                Picking a scene draws its first frame from the references you attached. That still is what the
                clip renders from, on every model — so the face, the room and the wardrobe are decided before a
                credit is spent, not guessed by the video model.
              </p>
            </div>
            <div>
              <span className="eyebrow">Your own keys</span>
              <h2 className="serif mt-5 text-[clamp(1.75rem,3.5vw,2.5rem)]">Bring a key, skip the credits.</h2>
              <p className="mt-5 text-[17px] leading-relaxed text-[#afafaf]">
                Add a Runway, fal, Higgsfield or Google key to your account and renders on it cost nothing
                here — the provider bills you at its own rate, and the Queue still shows you the estimate first.
              </p>
              <Button size="lg" variant="outline" className="mt-7" render={<Link href="/pricing" />}>
                See the plans
                <ArrowRight data-icon="inline-end" className="size-4" />
              </Button>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </EditorialSkin>
  );
}

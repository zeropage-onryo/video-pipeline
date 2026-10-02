import Link from "next/link";
import { Spotlight } from "@/components/ui/spotlight-new";
import { Button } from "@/components/ui/button";
import { CreateCtaButton } from "./create-cta-button";
import type { MakePage } from "../pages";

// The homepage hero's bones -- serif H1 at the same scale (bold here),
// centered column -- with the spotlight as this page's one effect. The
// beam is a tint of the page's own ink, not the component's default blue:
// warm white on the dark tone, a soft black on the light one.
const beam = (tone: MakePage["tone"]) => {
  const ink = tone === "light" ? "0, 0, 0" : "250, 248, 244";
  const k = tone === "light" ? 0.7 : 1; // black reads stronger than white
  return {
    first: `radial-gradient(68.54% 68.72% at 55.02% 31.46%, rgba(${ink}, ${0.09 * k}) 0, rgba(${ink}, ${0.025 * k}) 50%, rgba(${ink}, 0) 80%)`,
    second: `radial-gradient(50% 50% at 50% 50%, rgba(${ink}, ${0.07 * k}) 0, rgba(${ink}, ${0.02 * k}) 80%, transparent 100%)`,
    third: `radial-gradient(50% 50% at 50% 50%, rgba(${ink}, ${0.045 * k}) 0, rgba(${ink}, ${0.02 * k}) 80%, transparent 100%)`,
  };
};

const REVEAL =
  "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-4 motion-safe:fill-mode-both";

export function MakeHero({ page }: { page: MakePage }) {
  const BEAM = beam(page.tone);
  return (
    <section className="relative overflow-hidden pt-[60px]">
      <div aria-hidden className="absolute inset-0 z-0 overflow-hidden">
        <Spotlight
          gradientFirst={BEAM.first}
          gradientSecond={BEAM.second}
          gradientThird={BEAM.third}
          translateY={-300}
          duration={9}
          xOffset={60}
        />
      </div>

      <div className="relative z-10 mx-auto flex min-h-[460px] max-w-[1200px] flex-col items-center justify-center px-4 pb-16 pt-16 text-center md:min-h-[560px] md:px-6 md:pb-20 md:pt-20">
        <h1
          className={`serif serif-bold max-w-[14ch] text-[clamp(3rem,10.5vw,7.25rem)] ${REVEAL} motion-safe:duration-700`}
        >
          {page.h1}
        </h1>
        <p
          className={`mt-7 max-w-[52ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal tracking-[-0.005em] text-[var(--ink-2)] md:mt-9 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}
        >
          {page.subhead}
        </p>
        <div
          className={`mt-9 flex w-full max-w-[420px] flex-col items-stretch gap-3 sm:w-auto sm:max-w-none sm:flex-row sm:items-center ${REVEAL} motion-safe:duration-700 motion-safe:delay-200`}
        >
          <CreateCtaButton label={page.cta.label} spark={page.cta.spark} />
          <Button size="lg" variant="outline" render={<Link href="#examples" />}>
            See examples
          </Button>
        </div>
      </div>
    </section>
  );
}

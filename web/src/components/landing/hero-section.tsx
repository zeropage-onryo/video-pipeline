import Link from "next/link";
import { HeroCursors } from "@/components/landing/hero-cursors";
import { HeroMedia } from "@/components/landing/hero-media";
import { HeroPrompt } from "@/components/landing/hero-prompt";
import { HeroSpotlight } from "@/components/landing/hero-spotlight";

// The hero (2026-09-18 restyle, made interactive 2026-09-24): a centered
// column over a hairline grid that brightens under the pointer, four
// floating cursors, the headline Mike chose in the serif face, and a box
// you can actually type an idea into. Every reveal is motion-safe -- with
// reduced motion set the content simply renders.
const REVEAL =
  "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-4 motion-safe:fill-mode-both";

export function HeroSection() {
  return (
    <section id="studio" className="relative overflow-hidden pt-[60px]">
      <div aria-hidden className="hero-grid pointer-events-none absolute inset-0 z-0" />
      <HeroSpotlight />

      <div className="relative z-10 mx-auto flex min-h-[440px] max-w-[1200px] flex-col items-center justify-center px-6 pb-10 pt-12 text-center md:min-h-[520px]">
        <HeroCursors />
        <h1
          className={`serif max-w-[20ch] text-[clamp(2.5rem,8vw,5rem)] ${REVEAL} motion-safe:duration-700`}
        >
          The AI content studio that creates for you.
        </h1>
        <p
          className={`mt-8 max-w-[52ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal tracking-[-0.005em] text-[#afafaf] md:mt-10 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}
        >
          An AI content studio for filmmakers, brands, and creators. Bring the spark, shape the
          story, and make something only you could imagine.
        </p>
        <div
          className={`flex w-full flex-col items-center ${REVEAL} motion-safe:duration-700 motion-safe:delay-200`}
        >
          <HeroPrompt />
          <Link
            href="/#how"
            className="mt-5 text-sm text-[#82807d] transition-colors hover:text-foreground"
          >
            See how it works
          </Link>
        </div>
      </div>

      <HeroMedia />
    </section>
  );
}

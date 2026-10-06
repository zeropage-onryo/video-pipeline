import Link from "next/link";
import { HeroCursors } from "@/components/landing/hero-cursors";
import { HeroLetterbox } from "@/components/landing/hero-letterbox";
import { HeroMedia } from "@/components/landing/hero-media";
import { HeroPrompt } from "@/components/landing/hero-prompt";
import { HeroCopy, HeroPlate } from "@/components/landing/hero-scroll";
import { HeroSpotlight } from "@/components/landing/hero-spotlight";
import { KineticText } from "@/components/motion/kinetic-text";

// The hero (2026-09-18 restyle, made interactive 2026-09-24, cinematic
// motion 2026-10-06): letterbox bars open the page, the headline rises in
// word by word, the copy drifts away under the scroll and the product
// frame tilts up to face you. Every move is motion-safe -- with reduced
// motion set the content simply renders.
const REVEAL =
  "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-4 motion-safe:fill-mode-both";

export function HeroSection() {
  return (
    <section id="studio" className="relative overflow-hidden pt-[60px]">
      <HeroLetterbox />
      <div aria-hidden className="hero-grid pointer-events-none absolute inset-0 z-0" />
      <HeroSpotlight />

      <HeroCopy className="relative z-10 mx-auto flex min-h-[440px] max-w-[1200px] flex-col items-center justify-center px-6 pb-10 pt-12 text-center md:min-h-[520px]">
        <HeroCursors />
        <KineticText
          as="h1"
          trigger="mount"
          delay={0.55}
          stagger={0.07}
          text="The AI content studio that creates for you."
          className="serif max-w-[20ch] text-[clamp(2.5rem,8vw,5rem)]"
        />
        <p
          className={`mt-8 max-w-[52ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal tracking-[-0.005em] text-[#afafaf] md:mt-10 ${REVEAL} motion-safe:duration-700 motion-safe:delay-[1100ms]`}
        >
          An AI content studio for filmmakers, brands, and creators. Bring the spark, shape the
          story, and make something only you could imagine.
        </p>
        <div
          className={`flex w-full flex-col items-center ${REVEAL} motion-safe:duration-700 motion-safe:delay-[1250ms]`}
        >
          <HeroPrompt />
          <Link
            href="/#pipeline"
            className="mt-5 text-sm text-[#82807d] transition-colors hover:text-foreground"
          >
            See how it works
          </Link>
        </div>
      </HeroCopy>

      <HeroPlate>
        <HeroMedia />
      </HeroPlate>
    </section>
  );
}

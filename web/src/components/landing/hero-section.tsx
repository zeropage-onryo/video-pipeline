import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeroCursors } from "@/components/landing/hero-cursors";
import { HeroMedia } from "@/components/landing/hero-media";

// The hero (2026-09-18 restyle): a centered 640px column over a hairline
// grid that fades out before the media frame, four floating cursors, the
// headline Mike chose in the serif face, one white button. Every reveal
// is motion-safe -- with reduced motion set the content simply renders.
const REVEAL =
  "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-4 motion-safe:fill-mode-both";

export function HeroSection() {
  return (
    <section id="studio" className="relative overflow-hidden pt-[60px]">
      <div aria-hidden className="hero-grid pointer-events-none absolute inset-0 z-0" />

      <div className="relative z-10 mx-auto flex min-h-[560px] max-w-[1200px] flex-col items-center justify-center px-6 py-12 text-center md:min-h-[640px]">
        <HeroCursors />
        <h1
          className={`serif max-w-[20ch] text-[clamp(2.5rem,8vw,5rem)] ${REVEAL} motion-safe:duration-700`}
        >
          The AI content studio that creates for you.
        </h1>
        <p
          className={`mt-8 max-w-[52ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal tracking-[-0.005em] text-[#afafaf] md:mt-11 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}
        >
          An AI content studio for filmmakers, brands, and creators. Bring the spark, shape the
          story, and make something only you could imagine.
        </p>
        <div
          className={`mt-10 flex flex-wrap items-center justify-center gap-2.5 md:mt-14 ${REVEAL} motion-safe:duration-700 motion-safe:delay-200`}
        >
          <Button size="lg" render={<Link href="/studio" />}>
            Start creating
            <ArrowRight data-icon="inline-end" className="size-4" />
          </Button>
          <Button size="lg" variant="outline" render={<Link href="/#how" />}>
            See how it works
          </Button>
        </div>
      </div>

      <HeroMedia />
    </section>
  );
}

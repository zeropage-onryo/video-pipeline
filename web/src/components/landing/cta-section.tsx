import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ApertureMark } from "@/components/aperture-mark";

export function CtaSection() {
  return (
    <section className="relative z-10 overflow-hidden border-t border-border/60">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background: "radial-gradient(60% 80% at 50% 120%, rgba(228,0,43,0.16), transparent 70%)",
        }}
      />
      <div className="relative mx-auto flex max-w-4xl flex-col items-center gap-7 px-6 py-32 text-center">
        <ApertureMark className="h-10 w-10 text-primary animate-aperture" />
        <span className="kicker">Your next creation starts here</span>
        <h2 className="display text-balance text-5xl sm:text-7xl xl:text-8xl">
          Make what&apos;s
          <br />
          <span className="text-primary">on your mind.</span>
        </h2>
        <p className="max-w-lg text-balance text-sm font-light leading-relaxed text-muted-foreground">
          Start with whatever you have. ZeroPage helps you develop the direction, build the scene,
          and turn the idea into an image or video.
        </p>
        <Button className="h-12 px-8" render={<Link href="/studio" />}>
          Open your studio
        </Button>
      </div>
    </section>
  );
}

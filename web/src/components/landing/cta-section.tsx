import { Reveal } from "@/components/reveal";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function CtaSection() {
  return (
    <section className="border-t border-border">
      <Reveal className="mx-auto flex max-w-[760px] flex-col items-center gap-7 px-6 py-28 text-center md:py-36">
        <span className="eyebrow">Your next creation starts here</span>
        <h2 className="serif text-[clamp(2.25rem,5.5vw,4rem)]">Make what&apos;s on your mind.</h2>
        <p className="max-w-[46ch] text-[17px] leading-relaxed text-[#afafaf]">
          Start with whatever you have. Zero Page helps you develop the direction, build the scene,
          and turn the idea into an image or video.
        </p>
        <Button size="lg" render={<Link href="/studio" />}>
          Open your studio
          <ArrowRight data-icon="inline-end" className="size-4" />
        </Button>
      </Reveal>
    </section>
  );
}

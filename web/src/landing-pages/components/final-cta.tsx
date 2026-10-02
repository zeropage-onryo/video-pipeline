import { BlurFade } from "@/components/ui/blur-fade";
import { CreateCtaButton } from "./create-cta-button";
import type { MakePage } from "../pages";

export function FinalCta({ page }: { page: MakePage }) {
  return (
    <section className="border-t border-border">
      <BlurFade
        inView
        className="mx-auto flex max-w-[760px] flex-col items-center gap-7 px-4 py-24 text-center md:px-6 md:py-36"
      >
        <span className="eyebrow">{page.finalCta.eyebrow}</span>
        <h2 className="serif text-[clamp(2.25rem,5.5vw,4rem)]">{page.finalCta.title}</h2>
        <p className="max-w-[46ch] text-[17px] leading-relaxed text-[var(--ink-2)]">{page.finalCta.body}</p>
        <CreateCtaButton label={page.cta.label} spark={page.cta.spark} />
      </BlurFade>
    </section>
  );
}

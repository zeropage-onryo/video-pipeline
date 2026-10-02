"use client";

import Link from "next/link";
import { Accordion as AccordionPrimitive } from "@base-ui/react/accordion";
import { Plus } from "lucide-react";
import { BlurFade } from "@/components/ui/blur-fade";
import { Accordion, AccordionContent, AccordionItem } from "@/components/ui/accordion";
import { SectionTitle } from "./section-title";
import type { MakeFaq } from "../pages";

// The reference's FAQ (Mike's screenshot, 2026-10-02): one big line, then
// full-width hairline rows, the question bold and CENTERED in each, a thin
// plus at the right edge that turns into a cross when the row opens. Every
// row starts closed, as in the reference. The trigger is Base UI's own
// rather than the kit's, which hard-wires a chevron pair. Answers are plain
// strings because the same strings are the FAQPage JSON-LD on the route.
export function FaqSection({ title, items }: { title: string; items: MakeFaq[] }) {
  return (
    <section id="faq" className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-4 py-20 md:px-6 md:py-24">
        <SectionTitle>{title}</SectionTitle>
        <BlurFade inView delay={0.08}>
          <Accordion className="mt-10 border-y border-border md:mt-14">
            {items.map((item) => (
              <AccordionItem key={item.q} value={item.q} className="border-border">
                <AccordionPrimitive.Header className="flex">
                  <AccordionPrimitive.Trigger className="group/faq relative flex w-full items-center justify-center px-12 py-6 text-center text-[clamp(1.125rem,2.1vw,1.75rem)] font-bold leading-snug tracking-[-0.015em] text-foreground outline-none transition-colors hover:text-[var(--line-hover)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--line-hover)] md:px-16 md:py-8">
                    {item.q}
                    <Plus
                      aria-hidden
                      strokeWidth={1.25}
                      className="pointer-events-none absolute top-1/2 right-0 size-7 -translate-y-1/2 text-foreground transition-transform duration-300 group-aria-expanded/faq:rotate-45 md:right-2 md:size-9"
                    />
                  </AccordionPrimitive.Trigger>
                </AccordionPrimitive.Header>
                <AccordionContent className="pb-8">
                  <div className="mx-auto max-w-[64ch]">
                    <p className="text-[16px] leading-relaxed text-[var(--ink-2)]">{item.a}</p>
                    {item.link && (
                      <p className="mt-3 text-[16px]">
                        <Link
                          href={item.link.href}
                          className="text-foreground underline underline-offset-4 transition-opacity hover:opacity-80"
                        >
                          {item.link.label}
                        </Link>
                      </p>
                    )}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </BlurFade>
      </div>
    </section>
  );
}

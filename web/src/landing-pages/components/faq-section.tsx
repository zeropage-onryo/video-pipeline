"use client";

import Link from "next/link";
import { BlurFade } from "@/components/ui/blur-fade";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import type { MakeFaq } from "../pages";

// The Base UI accordion, restyled to the FAQ page's hairline rows: 17px
// question, muted answer, the first item open so the section never reads
// as a list of closed doors. Answers are plain strings because the same
// strings are the FAQPage JSON-LD on the route.
export function FaqSection({ items }: { items: MakeFaq[] }) {
  return (
    <section id="faq" className="border-t border-border">
      <div className="mx-auto max-w-[760px] px-4 py-20 md:px-6 md:py-24">
        <BlurFade inView>
          <span className="eyebrow">FAQ</span>
          <h2 className="serif mt-5 text-[clamp(2rem,4.2vw,3.25rem)]">Questions, answered plainly.</h2>
        </BlurFade>
        <BlurFade inView delay={0.08}>
          <Accordion defaultValue={[items[0]?.q]} className="mt-10 border-y border-border md:mt-12">
            {items.map((item) => (
              <AccordionItem key={item.q} value={item.q} className="border-border">
                <AccordionTrigger className="rounded-none border-0 py-5 text-[17px] font-medium tracking-[-0.005em] hover:no-underline focus-visible:ring-0 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--signal)]">
                  {item.q}
                </AccordionTrigger>
                <AccordionContent className="pb-5">
                  <p className="max-w-[64ch] text-[15px] leading-relaxed text-[var(--ink-2)]">{item.a}</p>
                  {item.link && (
                    <p className="mt-3 text-[15px]">
                      <Link
                        href={item.link.href}
                        className="text-foreground underline underline-offset-4 transition-opacity hover:opacity-80"
                      >
                        {item.link.label}
                      </Link>
                    </p>
                  )}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </BlurFade>
      </div>
    </section>
  );
}

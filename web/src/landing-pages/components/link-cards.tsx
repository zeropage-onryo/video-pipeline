import { BlurFade } from "@/components/ui/blur-fade";
import { CreateCtaButton } from "./create-cta-button";
import { SectionTitle } from "./section-title";
import { stagger } from "@/lib/motion";
import type { MakeCard } from "../pages";

// The reference's row of cards (Mike's screenshots, 2026-10-01): one big
// line, then white cards on a hairline with a bold title, a line of body
// and "Start now ›" at the foot. `numbered` prefixes "1." "2." "3." for
// the how-to row. Every Start now is the sign-up door with this page's
// starting line, the same as "Create your ad".
export function LinkCards({
  id,
  title,
  items,
  spark,
  startLabel = "Start now",
  numbered = false,
}: {
  id: string;
  title: string;
  items: MakeCard[];
  spark: string;
  startLabel?: string;
  numbered?: boolean;
}) {
  const cols = items.length >= 4 ? "lg:grid-cols-4" : "lg:grid-cols-3";
  return (
    <section id={id} className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-4 py-20 md:px-6 md:py-24">
        <SectionTitle>{title}</SectionTitle>
        <ul className={`mt-10 grid gap-3 sm:grid-cols-2 md:mt-14 ${cols} lg:gap-4`}>
          {items.map((card, i) => (
            <li key={card.title} className="h-full">
              <BlurFade inView delay={stagger(i, 0)} className="h-full">
                <article className="flex h-full flex-col rounded-2xl border border-[var(--card-line)] bg-background p-6 transition-[border-color,transform,box-shadow] duration-300 hover:-translate-y-1 hover:border-[var(--line-hover)] hover:shadow-[var(--card-shadow)] motion-reduce:hover:translate-y-0">
                  <h3 className="text-[21px] font-bold leading-tight tracking-[-0.02em]">
                    {numbered ? `${i + 1}. ` : ""}
                    {card.title}
                  </h3>
                  <p className="mt-3 flex-1 text-[15px] leading-relaxed text-[var(--ink-2)]">{card.body}</p>
                  <CreateCtaButton variant="link" label={startLabel} spark={spark} className="mt-7" />
                </article>
              </BlurFade>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

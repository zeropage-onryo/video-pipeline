import { SectionTitle } from "./section-title";
import { FeaturesGrid, FeaturesList, FeaturesRows } from "./features-grid";
import type { MakePage } from "../pages";

// Nine features under one big line in the wall's heavy condensed
// uppercase (2026-10-01, Mike), drawn as the entry's `layout.features`
// says (2026-10-08): cards (the default), a numbered hairline list, or rows
// beside a title pinned on the left. The interactive parts live in
// features-grid.tsx, a client component on Motion.
export function FeaturesSection({ page }: { page: MakePage }) {
  const shape = page.layout?.features ?? "grid";
  if (shape === "split") {
    return (
      <section id="features" className="border-t border-border">
        <div className="mx-auto grid max-w-[1200px] gap-10 px-4 py-20 md:px-6 md:py-24 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-16">
          <div className="lg:sticky lg:top-28 lg:self-start">
            <SectionTitle className="lg:text-left">{page.features.title}</SectionTitle>
          </div>
          <FeaturesRows items={page.features.items} />
        </div>
      </section>
    );
  }
  return (
    <section id="features" className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-4 py-20 md:px-6 md:py-24">
        <SectionTitle>{page.features.title}</SectionTitle>
        {shape === "list" ? <FeaturesList items={page.features.items} /> : <FeaturesGrid items={page.features.items} />}
      </div>
    </section>
  );
}

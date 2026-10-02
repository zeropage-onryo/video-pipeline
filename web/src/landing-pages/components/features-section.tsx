import { SectionTitle } from "./section-title";
import { FeaturesGrid } from "./features-grid";
import type { MakePage } from "../pages";

// Nine feature cards under one big line in the wall's heavy condensed
// uppercase (2026-10-01, Mike). The cards are the interactive part and
// live in features-grid.tsx, a client component on Motion.
export function FeaturesSection({ page }: { page: MakePage }) {
  return (
    <section id="features" className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-4 py-20 md:px-6 md:py-24">
        <SectionTitle>{page.features.title}</SectionTitle>
        <FeaturesGrid items={page.features.items} />
      </div>
    </section>
  );
}

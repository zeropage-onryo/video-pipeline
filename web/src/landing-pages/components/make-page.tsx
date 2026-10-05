import { EditorialSkin } from "@/components/editorial-skin";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { MakeHero } from "./make-hero";
import { Signature } from "./signatures";
import { AdWall } from "./ad-wall";
import { FeaturesSection } from "./features-section";
import { ModelsSection } from "./models-section";
import { HowToSection } from "./how-to-section";
import { FaqSection } from "./faq-section";
import { RelatedSection } from "./related-section";
import { FinalCta } from "./final-cta";
import { accentVars } from "../theme";
import type { MakePage as MakePageEntry } from "../pages";

// The whole /make page from one entry, in the order the brief fixed:
// hero, the page's signature section when it names one, the wall (its own
// headline + Explore), features, models, how-to, FAQ, related, final CTA.
// Same header, footer and skin as the homepage; the entry's accent rides
// on the skin wrapper as CSS variables (theme.ts).
export function MakePage({ page }: { page: MakePageEntry }) {
  return (
    <EditorialSkin tone={page.tone} style={accentVars(page.accent)}>
      <SiteHeader />
      <main className="flex-1">
        <MakeHero page={page} />
        <Signature page={page} />
        <AdWall page={page} />
        <FeaturesSection page={page} />
        <ModelsSection page={page} />
        <HowToSection page={page} />
        <FaqSection title={page.faq.title} items={page.faq.items} />
        <RelatedSection page={page} />
        <FinalCta page={page} />
      </main>
      <SiteFooter />
    </EditorialSkin>
  );
}

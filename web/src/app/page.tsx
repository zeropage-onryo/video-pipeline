import { EditorialSkin } from "@/components/editorial-skin";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { HeroSection } from "@/components/landing/hero-section";
import { FeatureSection } from "@/components/landing/feature-section";
import { FramesSection } from "@/components/landing/frames-section";
import { WorkSection } from "@/components/landing/work-section";
import { StartingPointsSection } from "@/components/landing/starting-points-section";
import { CtaSection } from "@/components/landing/cta-section";

export default function Home() {
  return (
    <EditorialSkin>
      <SiteHeader />
      <main className="flex-1">
        <HeroSection />
        <FeatureSection />
        <FramesSection />
        <WorkSection />
        <StartingPointsSection />
        <CtaSection />
      </main>
      <SiteFooter />
    </EditorialSkin>
  );
}

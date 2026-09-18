import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { HeroSection } from "@/components/landing/hero-section";
import { PipelineSection, StartingPointsSection } from "@/components/landing/pipeline-section";
import { WorkSection } from "@/components/landing/work-section";
import { FramesSection } from "@/components/landing/frames-section";
import { CtaSection } from "@/components/landing/cta-section";

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        <HeroSection />
        <WorkSection />
        <FramesSection />
        <PipelineSection />
        <StartingPointsSection />
        <CtaSection />
      </main>
      <SiteFooter />
    </>
  );
}

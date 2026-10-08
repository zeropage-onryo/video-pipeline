import type { Metadata } from "next";
import { LandingRoute, metadataFor, staticParams } from "@/landing-pages/route";

// /make/<slug>: the "make a thing" landing pages. Everything it renders
// comes from src/landing-pages (pages.ts, entries/); this file only binds
// the section. The image-model pages live at /models/<slug>.

export const dynamicParams = false;

export function generateStaticParams() {
  return staticParams("make");
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  return metadataFor("make", slug);
}

export default async function Page({ params }: Props) {
  const { slug } = await params;
  return <LandingRoute section="make" slug={slug} />;
}

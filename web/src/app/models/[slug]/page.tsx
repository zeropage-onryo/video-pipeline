import type { Metadata } from "next";
import { LandingRoute, metadataFor, staticParams } from "@/landing-pages/route";

// /models/<slug>: one page per image model, listed on /models under
// "Image models" (2026-10-05, Mike's call). Same template as /make; this
// file only binds the section.

export const dynamicParams = false;

export function generateStaticParams() {
  return staticParams("models");
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  return metadataFor("models", slug);
}

export default async function Page({ params }: Props) {
  const { slug } = await params;
  return <LandingRoute section="models" slug={slug} />;
}

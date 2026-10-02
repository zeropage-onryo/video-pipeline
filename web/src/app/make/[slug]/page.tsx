import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MakePage } from "@/landing-pages/components/make-page";
import { MAKE_PAGES, getMakePage, makePath } from "@/landing-pages/pages";

// The one template behind every /make/<slug> page. Everything it renders
// comes from src/landing-pages/pages.ts; this file only maps a slug to
// an entry, writes the <head>, and emits the FAQPage JSON-LD.

export const dynamicParams = false;

export function generateStaticParams() {
  return MAKE_PAGES.map((p) => ({ slug: p.slug }));
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const page = getMakePage(slug);
  if (!page) return {};
  const path = makePath(page.slug);
  return {
    title: page.title,
    description: page.description,
    alternates: { canonical: path },
    openGraph: {
      type: "website",
      siteName: "Zero Page",
      title: `${page.title} — Zero Page`,
      description: page.description,
      url: path,
      locale: "en_US",
    },
    twitter: {
      card: "summary_large_image",
      title: `${page.title} — Zero Page`,
      description: page.description,
    },
    robots: { index: true, follow: true },
  };
}

export default async function Page({ params }: Props) {
  const { slug } = await params;
  const page = getMakePage(slug);
  if (!page) notFound();

  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: page.faq.items.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
    })),
  };

  return (
    <>
      <script
        type="application/ld+json"
        // JSON.stringify output with "<" escaped: the one way a string in
        // this attribute could close the tag.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd).replace(/</g, "\\u003c") }}
      />
      <MakePage page={page} />
    </>
  );
}

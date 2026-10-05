import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MakePage } from "./components/make-page";
import { getMakePage, makePath, pagesIn, type MakeSection } from "./pages";

// The one template behind every landing page, shared by the two thin
// routes (app/make/[slug] and app/models/[slug], 2026-10-05): static
// params for a section, the <head>, and the FAQPage JSON-LD. A slug asked
// for under the wrong section is a 404, so a page has exactly one URL.

export function staticParams(section: MakeSection) {
  return pagesIn(section).map((p) => ({ slug: p.slug }));
}

export function metadataFor(section: MakeSection, slug: string): Metadata {
  const page = getMakePage(slug, section);
  if (!page) return {};
  const path = makePath(page);
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
      // Next replaces the whole openGraph object per route rather than
      // merging it, and the root's file-based card (app/opengraph-image.tsx)
      // applies to `/` only, so until 2026-10-05 these pages shared with no
      // image at all. The root's generated card is named here explicitly;
      // layout.tsx's `/og.jpg` is a file that does not exist (404).
      // TODO(media): a per-page card, app/<section>/[slug]/opengraph-image.tsx.
      images: [{ url: "/opengraph-image", width: 1200, height: 630, type: "image/png" }],
    },
    twitter: {
      card: "summary_large_image",
      title: `${page.title} — Zero Page`,
      description: page.description,
      images: ["/opengraph-image"],
    },
    robots: { index: true, follow: true },
  };
}

export function LandingRoute({ section, slug }: { section: MakeSection; slug: string }) {
  const page = getMakePage(slug, section);
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

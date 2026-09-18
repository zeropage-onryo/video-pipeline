import type { ReactNode } from "react";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { EditorialSkin } from "@/components/editorial-skin";

// The one layout /terms and /privacy share: the landing page's header and
// footer around a numbered, single-column document. Server-rendered and
// static -- these are the URLs OAuth app registrations keep on file.

export const LEGAL_CONTACT = "mikemassaad@gmail.com";

export type LegalSection = { title: string; body: ReactNode };

export function LegalPage({
  title,
  dek,
  effective,
  sections,
}: {
  title: string;
  dek: string;
  effective: string;
  sections: LegalSection[];
}) {
  return (
    <EditorialSkin>
      <SiteHeader />
      <main className="flex-1">
        <article className="mx-auto max-w-2xl px-6 pb-28 pt-36">
          <span className="eyebrow block">Legal</span>
          <h1 className="serif mt-5 text-[clamp(2.25rem,5vw,3.5rem)]">{title}</h1>
          <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-[#afafaf]">{dek}</p>
          <p className="eyebrow mt-6 border-b border-border pb-9 leading-relaxed">
            Effective {effective} · Zero Page, operated by Michael Massaad
          </p>

          {sections.map((section, i) => (
            <section
              key={section.title}
              className="mt-10 space-y-3 leading-relaxed text-[#c6c4c0] [&_a]:text-foreground [&_a]:underline [&_a]:underline-offset-4 [&_a:hover]:opacity-80 [&_li]:marker:text-[#82807d] [&_strong]:font-medium [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:space-y-1.5 [&_ul]:pl-5"
            >
              <div className="flex items-baseline gap-4">
                <span className="eyebrow">{String(i + 1).padStart(2, "0")}</span>
                <h2 className="serif text-2xl">{section.title}</h2>
              </div>
              {section.body}
            </section>
          ))}
        </article>
      </main>
      <SiteFooter />
    </EditorialSkin>
  );
}

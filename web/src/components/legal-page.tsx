import type { ReactNode } from "react";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";

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
    <>
      <SiteHeader />
      <main className="flex-1">
        <article className="mx-auto max-w-2xl px-6 pb-28 pt-20">
          <span className="kicker block">Legal</span>
          <h1 className="display mt-5 text-5xl sm:text-6xl">{title}</h1>
          <p className="mt-6 max-w-xl leading-relaxed text-muted-foreground">{dek}</p>
          <p className="film-slate mt-6 border-b border-border/60 pb-9 leading-relaxed text-muted-foreground/70">
            Effective {effective} · Zero Page, operated by Michael Massaad
          </p>

          {sections.map((section, i) => (
            <section
              key={section.title}
              className="mt-10 space-y-3 leading-relaxed text-foreground/90 [&_a]:text-primary [&_a:hover]:underline [&_li]:marker:text-primary [&_strong]:font-medium [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:space-y-1.5 [&_ul]:pl-5"
            >
              <div className="flex items-baseline gap-4">
                <span className="font-mono text-xs text-primary">{String(i + 1).padStart(2, "0")}</span>
                <h2 className="display text-2xl">{section.title}</h2>
              </div>
              {section.body}
            </section>
          ))}
        </article>
      </main>
      <SiteFooter />
    </>
  );
}

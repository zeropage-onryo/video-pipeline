import Link from "next/link";
import type { ReactNode } from "react";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { SITE, LEGAL_IS_DRAFT, isPlaceholder } from "@/lib/site";

// The shell both legal pages share: header, a draft banner while any
// SITE fact is still a placeholder, numbered sections, footer. Prose
// width is capped so the text reads rather than spans.

export function Fact({ value }: { value: string }) {
  return isPlaceholder(value) ? (
    <mark className="bg-primary/20 px-1 text-foreground">{value}</mark>
  ) : (
    <>{value}</>
  );
}

export function LegalSection({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="display mt-6 text-2xl sm:text-3xl">
        <span className="mr-3 font-mono text-base font-medium text-primary/80">
          {String(n).padStart(2, "0")}
        </span>
        {title}
      </h2>
      <div className="flex flex-col gap-3 text-sm font-light leading-relaxed text-muted-foreground [&_li]:ml-5 [&_li]:list-disc [&_a]:underline [&_a]:text-foreground">
        {children}
      </div>
    </section>
  );
}

export function LegalPage({ title, sibling, children }: {
  title: string;
  sibling: { href: string; label: string };
  children: ReactNode;
}) {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        <div className="mx-auto max-w-3xl px-6 pb-28 pt-24">
          <Link href="/" className="film-slate text-muted-foreground hover:text-foreground">
            ← Back
          </Link>
          <h1 className="display mt-8 text-5xl sm:text-7xl">{title}</h1>
          <p className="film-slate mt-5 text-muted-foreground/70">
            Effective {SITE.effectiveDate}
          </p>
          {LEGAL_IS_DRAFT && (
            <div className="mt-8 border border-primary bg-primary/5 p-4 text-sm leading-relaxed">
              <span className="font-medium text-primary">Draft.</span> Written in plain language
              to be honest and short. Have a lawyer read it before real pilot users sign up
              under it. Highlighted items are placeholders — fill them in{" "}
              <code className="font-mono text-xs">src/lib/site.ts</code>.
            </div>
          )}
          <div className="mt-6 flex flex-col gap-4">{children}</div>
          <Link
            href={sibling.href}
            className="film-slate mt-14 inline-block text-primary hover:text-foreground"
          >
            {sibling.label} →
          </Link>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}

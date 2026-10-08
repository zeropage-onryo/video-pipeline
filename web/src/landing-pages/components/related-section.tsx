import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { getMakePage, makePath, type MakePage } from "../pages";
import { pageLabel } from "../shared";

// Links to the other landing pages. Renders nothing while an entry's
// `related` list is empty or names slugs that do not exist yet. A model
// page's heading says "More models"; each link is named by `pageLabel`,
// the catalog's name, so it reads the same as the Models menu and the
// footer (2026-10-08: the LTX link said "LTX 2.5", the footer "LTX 2.5 Pro").
export function RelatedSection({ page }: { page: MakePage }) {
  const related = page.related.map((s) => getMakePage(s)).filter((p): p is MakePage => Boolean(p));
  if (!related.length) return null;
  return (
    <section id="related" className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-4 py-16 md:px-6 md:py-20">
        <span className="eyebrow">{page.section === "models" ? "More models" : "More to make"}</span>
        <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {related.map((p) => (
            <li key={p.slug}>
              <Link
                href={makePath(p)}
                className="flex h-full items-center justify-between gap-4 rounded-[14px] border border-border bg-card p-5 transition-colors hover:border-[var(--line-hover)]"
              >
                <span className="serif text-xl">{pageLabel(p)}</span>
                <ArrowRight className="size-4 shrink-0 text-[var(--ink-3)]" />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

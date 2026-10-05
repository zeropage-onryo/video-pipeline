import Link from "next/link";
import { Wordmark } from "@/components/wordmark";
import { makePath, pagesIn } from "@/landing-pages/pages";
import { IMAGE_MODELS } from "@/landing-pages/shared";

const COLUMNS: { title: string; links: [string, string][] }[] = [
  {
    title: "Studio",
    links: [
      ["How it works", "/#how"],
      ["Models", "/models"],
      ["Frames", "/#frames"],
      ["Who it's for", "/#work"],
    ],
  },
  {
    // "Tools" (Mike, 2026-10-02): the word the generator sites use and the
    // phrase people search; "Make" is the URL segment, not a label.
    title: "Tools",
    // every /make landing page, off its own entry, so the site links to
    // each one from every page (crawlers find it; the person does too)
    links: pagesIn("make").map((page) => [page.h1, makePath(page)]),
  },
  {
    // the image-model pages, under /models (2026-10-05, Mike's call)
    title: "Image models",
    links: pagesIn("models").map((page) => [
      IMAGE_MODELS.find((m) => m.id === page.model)?.label ?? page.h1,
      makePath(page),
    ]),
  },
  {
    title: "Plans",
    links: [
      ["Pricing", "/pricing"],
      ["FAQ", "/faq"],
      ["Sign in", "/studio"],
      ["Start creating", "/studio"],
    ],
  },
  {
    title: "Legal",
    links: [
      ["Terms", "/terms"],
      ["Privacy", "/privacy"],
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-6 py-14">
        <div className="grid gap-10 sm:grid-cols-2 md:grid-cols-[1.4fr_repeat(5,1fr)]">
          <div className="max-w-xs">
            <Wordmark />
            <p className="mt-4 text-sm leading-relaxed text-[var(--ink-2)]">
              The AI content studio that creates for you — for filmmakers, brands, and creators.
            </p>
          </div>
          {COLUMNS.map((column) => (
            <div key={column.title} className="flex flex-col gap-3">
              <span className="eyebrow">{column.title}</span>
              {column.links.map(([label, href]) => (
                <Link
                  key={label + href}
                  href={href}
                  className="text-sm text-[var(--nav-fg)] transition-colors hover:text-foreground"
                >
                  {label}
                </Link>
              ))}
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col gap-2 border-t border-border pt-6 text-[13px] text-[var(--ink-3)] sm:flex-row sm:items-center sm:justify-between">
          <span>© {new Date().getFullYear()} Zero Page Films</span>
          <span>From idea to creation</span>
        </div>
      </div>
    </footer>
  );
}

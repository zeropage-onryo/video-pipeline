import Link from "next/link";
import { Wordmark } from "@/components/wordmark";

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
        <div className="grid gap-10 md:grid-cols-[1.4fr_repeat(3,1fr)]">
          <div className="max-w-xs">
            <Wordmark />
            <p className="mt-4 text-sm leading-relaxed text-[#afafaf]">
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
                  className="text-sm text-[#c6c4c0] transition-colors hover:text-foreground"
                >
                  {label}
                </Link>
              ))}
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col gap-2 border-t border-border pt-6 text-[13px] text-[#82807d] sm:flex-row sm:items-center sm:justify-between">
          <span>© {new Date().getFullYear()} Zero Page Films</span>
          <span>From idea to creation</span>
        </div>
      </div>
    </footer>
  );
}

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ApertureMark } from "@/components/aperture-mark";

const NAV = [
  ["/#pipeline", "The studio"],
  ["/#work", "Who it's for"],
  ["/#faq", "FAQ"],
] as const;

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-6">
        <Link href="/" className="group flex shrink-0 items-center gap-2.5" aria-label="ZeroPage home">
          <ApertureMark className="h-5 w-5 text-primary transition-transform duration-500 group-hover:rotate-45" />
          <span className="display text-lg tracking-normal">
            ZERO<span className="text-primary">PAGE</span>
          </span>
        </Link>

        <nav aria-label="Primary" className="hidden items-center gap-9 md:flex">
          {NAV.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className="film-slate text-muted-foreground transition-colors hover:text-foreground"
            >
              {label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          {/* Below sm the logo and the red button are the whole header:
              a third control jams against the wordmark at 390px. */}
          <Button variant="ghost" size="sm" className="hidden sm:inline-flex" render={<Link href="/studio" />}>
            Sign in
          </Button>
          <Button size="sm" render={<Link href="/studio" />}>
            Start creating
          </Button>
        </div>
      </div>
    </header>
  );
}

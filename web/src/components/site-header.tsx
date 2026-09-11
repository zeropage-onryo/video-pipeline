import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ApertureMark } from "@/components/aperture-mark";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link href="/" className="group flex items-center gap-2.5">
          <ApertureMark className="h-5 w-5 text-primary transition-transform duration-500 group-hover:rotate-45" />
          <span className="display text-lg tracking-normal">
            ZERO<span className="text-primary">PAGE</span>
          </span>
        </Link>

        <nav className="hidden items-center gap-9 md:flex">
          <Link
            href="/#pipeline"
            className="film-slate text-muted-foreground transition-colors hover:text-foreground"
          >
            The studio
          </Link>
          <Link
            href="/#work"
            className="film-slate text-muted-foreground transition-colors hover:text-foreground"
          >
            Who it&apos;s for
          </Link>
        </nav>

        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" render={<Link href="/studio" />}>
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

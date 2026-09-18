import Link from "next/link";
import { ApertureMark } from "@/components/aperture-mark";

export function SiteFooter() {
  return (
    <footer className="relative z-10 border-t border-border/60">
      <div className="mx-auto max-w-6xl px-6 py-14">
        <div className="flex flex-col gap-10 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-xs">
            <div className="flex items-center gap-2.5">
              <ApertureMark className="h-5 w-5 text-primary" />
              <span className="display text-lg tracking-normal">
                ZERO<span className="text-primary">PAGE</span>
              </span>
            </div>
            <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
              The AI content studio that creates for you — for filmmakers, brands, and creators.
            </p>
          </div>

          <div className="flex gap-16">
            <div className="flex flex-col gap-3">
              <span className="film-slate text-muted-foreground/70">Studio</span>
              <Link href="/#pipeline" className="text-sm text-muted-foreground hover:text-foreground">
                The studio
              </Link>
              <Link href="/#work" className="text-sm text-muted-foreground hover:text-foreground">
                Who it&apos;s for
              </Link>
            </div>
            <div className="flex flex-col gap-3">
              <span className="film-slate text-muted-foreground/70">Access</span>
              <Link href="/studio" className="text-sm text-muted-foreground hover:text-foreground">
                Sign in
              </Link>
              <Link href="/studio" className="text-sm text-muted-foreground hover:text-foreground">
                Get started
              </Link>
            </div>
          </div>
        </div>

        <div className="mt-12 flex flex-col gap-2 border-t border-border/60 pt-6 sm:flex-row sm:items-center sm:justify-between">
          <span className="film-slate text-muted-foreground/60">
            © {new Date().getFullYear()} Zero Page Films
          </span>
          <nav aria-label="Legal" className="flex gap-6">
            <Link href="/terms" className="film-slate text-muted-foreground/60 hover:text-foreground">
              Terms
            </Link>
            <Link href="/privacy" className="film-slate text-muted-foreground/60 hover:text-foreground">
              Privacy
            </Link>
          </nav>
        </div>
      </div>
    </footer>
  );
}

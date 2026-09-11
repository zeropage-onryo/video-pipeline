import Link from "next/link";
import { Button } from "@/components/ui/button";

export function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_70%_40%,rgba(228,0,43,.18),transparent_36%)]" />
      <div className="relative mx-auto grid min-h-[82vh] max-w-6xl items-end gap-12 px-6 pb-20 pt-36 md:grid-cols-[1.25fr_.75fr] md:pb-24">
        <div>
          <span className="kicker">Your vision. Your studio.</span>
          <h1 className="display mt-8 text-balance text-6xl sm:text-8xl xl:text-[7.5rem]">
            From idea
            <br />to <span className="text-primary">creation.</span>
          </h1>
          <p className="mt-8 max-w-xl text-lg font-light leading-relaxed text-muted-foreground sm:text-xl">
            An AI creative studio for filmmakers, brands, and creators. Bring the spark, shape
            the story, and make something only you could imagine.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-6">
          <Button
            className="h-12 px-8"
            render={<Link href="/studio" />}
          >
            Start creating
          </Button>
          <Link href="#starting-points" className="film-slate text-muted-foreground hover:text-foreground">
            Choose your starting point ↓
          </Link>
        </div>
        </div>
        <div className="relative hidden min-h-[430px] border border-border/70 bg-[linear-gradient(145deg,#242424,#0c0c0c_65%)] md:block">
          <div className="absolute inset-5 border border-white/10" />
          <span className="film-slate absolute left-8 top-8 text-muted-foreground">A world starts with a spark</span>
          <div className="absolute bottom-8 left-8 right-8 border-l-2 border-primary bg-black/70 p-5 backdrop-blur">
            <span className="kicker">Creative direction</span>
            <p className="mt-3 text-xl leading-snug">The world you see.<br />The story you haven&apos;t told.</p>
          </div>
        </div>
      </div>
      <div className="border-y border-border/60 py-4">
        <p className="film-slate mx-auto max-w-6xl px-6 text-muted-foreground">
          Script &nbsp;·&nbsp; Idea &nbsp;·&nbsp; Concept &nbsp;·&nbsp; Image &nbsp;·&nbsp; Video
        </p>
      </div>
    </section>
  );
}

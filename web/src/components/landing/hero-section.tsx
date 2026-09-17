import Link from "next/link";
import { Button } from "@/components/ui/button";
import { NoirScene } from "@/components/noir-scene";

// The five ways in, as the hero's slate strip. A flex list rather than a
// single &nbsp;-spaced string so it wraps cleanly at phone widths.
const WAYS_IN = ["Script", "Idea", "Concept", "Image", "Video"];

// Every reveal is motion-safe: with reduced motion set, content simply
// renders in place (tw-animate-css's animate-in is only applied under
// motion-safe:).
const REVEAL = "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-4 motion-safe:fill-mode-both";

export function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_70%_40%,rgba(228,0,43,.18),transparent_36%)]" />
      {/* Fills the first viewport (minus the 4rem header) and centres the
          copy in it -- the old items-end + 82vh left a third of the screen
          empty above the headline. */}
      <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-6 pb-16 pt-20 md:min-h-[calc(100svh-4rem)] md:grid-cols-[1.25fr_.75fr] md:py-20">
        <div>
          <span className={`kicker block ${REVEAL} motion-safe:duration-700`}>Your vision. Your studio.</span>
          <h1 className={`display mt-6 text-balance text-6xl sm:text-8xl xl:text-[7.5rem] ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}>
            The AI content studio that{" "}
            <span className="text-primary">creates for you.</span>
          </h1>
          <p className={`mt-8 max-w-xl text-lg font-light leading-relaxed text-muted-foreground sm:text-xl ${REVEAL} motion-safe:duration-700 motion-safe:delay-200`}>
            An AI creative studio for filmmakers, brands, and creators. Bring the spark, shape
            the story, and make something only you could imagine.
          </p>
          <div className={`mt-10 flex flex-wrap items-center gap-6 ${REVEAL} motion-safe:duration-700 motion-safe:delay-300`}>
            <Button className="h-12 px-8" render={<Link href="/studio" />}>
              Start creating
            </Button>
            <Link
              href="#starting-points"
              className="film-slate text-muted-foreground transition-colors hover:text-foreground"
            >
              Choose your starting point ↓
            </Link>
          </div>
        </div>

        {/* The viewfinder: the aperture-ring WebGL scene (noir-scene.tsx was
            built for this hero and never mounted) inside a slate frame. It
            renders null without WebGL or under reduced motion, leaving the
            gradient plate and the caption. */}
        <div
          className={`relative hidden aspect-[4/5] max-h-[520px] border border-border/70 bg-[linear-gradient(145deg,#242424,#0c0c0c_65%)] md:block ${REVEAL} motion-safe:duration-1000 motion-safe:delay-200`}
        >
          {/* Stops above the caption card so the ring centres in the open plate. */}
          <NoirScene className="absolute inset-x-0 top-0 bottom-28" />
          <div aria-hidden className="pointer-events-none absolute inset-5 border border-white/10" />
          <ViewfinderCorners />
          <span className="film-slate absolute left-8 top-8 text-muted-foreground">
            A world starts with a spark
          </span>
          <span className="film-slate absolute right-8 top-8 flex items-center gap-2 text-primary">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary animate-aperture" />
            Rec
          </span>
          <div className="absolute bottom-8 left-8 right-8 border-l-2 border-primary bg-black/70 p-5 backdrop-blur">
            <span className="kicker">Creative direction</span>
            <p className="mt-3 text-xl leading-snug">
              The world you see.
              <br />
              The story you haven&apos;t told.
            </p>
          </div>
        </div>
      </div>

      <div className="border-y border-border/60 py-4">
        <ul className="film-slate mx-auto flex max-w-6xl flex-wrap gap-x-3 gap-y-2 px-6 text-muted-foreground">
          {WAYS_IN.map((way, i) => (
            <li key={way} className="flex items-center gap-3">
              {i > 0 && <span aria-hidden className="text-muted-foreground/50">·</span>}
              {way}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// Four L-shaped ticks at the frame's corners -- the viewfinder overlay.
function ViewfinderCorners() {
  const corners = [
    "left-5 top-5 border-l border-t",
    "right-5 top-5 border-r border-t",
    "left-5 bottom-5 border-l border-b",
    "right-5 bottom-5 border-r border-b",
  ];
  return (
    <>
      {corners.map((c) => (
        <span key={c} aria-hidden className={`pointer-events-none absolute h-4 w-4 border-primary/70 ${c}`} />
      ))}
    </>
  );
}

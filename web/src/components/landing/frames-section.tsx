import { MediaTile } from "@/components/landing/media-tile";
import { LANDING_MEDIA } from "@/content/landing-media";

// The filmstrip: every frame in landing-media.ts as a horizontal, snap-
// scrolling strip of 9:16 tiles. Each is a keyframe the studio drew for a
// concept on the board, captioned with the concept's own title, so the
// strip is a live sample of what comes out rather than a mood board.

export function FramesSection() {
  return (
    <section id="frames" className="relative z-10 border-y border-border/60 py-24">
      <div className="mx-auto max-w-6xl px-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <span className="kicker">Off the board</span>
            <h2 className="display mt-5 text-4xl sm:text-6xl">Frames the studio drew.</h2>
          </div>
          <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
            Keyframes from recent concepts, each the first frame its clip will anchor on. Nothing
            here is stock.
          </p>
        </div>
      </div>

      <ul className="mt-12 flex snap-x snap-mandatory gap-px overflow-x-auto border-y border-border bg-border px-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {LANDING_MEDIA.map((media, i) => (
          <li
            key={media.concept}
            className="group relative aspect-[9/16] w-[220px] shrink-0 snap-start overflow-hidden bg-black sm:w-[260px]"
          >
            <MediaTile media={media} sizes="260px" />
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/85 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100"
            />
            <div className="absolute inset-x-4 bottom-4 translate-y-2 opacity-0 transition-all duration-500 group-hover:translate-y-0 group-hover:opacity-100">
              <span className="film-slate text-foreground/70">
                {String(i + 1).padStart(2, "0")} / #{media.concept}
              </span>
              <p className="display mt-2 text-xl">{media.title}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

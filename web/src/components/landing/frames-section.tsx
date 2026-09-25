import { Reveal } from "@/components/reveal";
import { MediaTile } from "@/components/landing/media-tile";
import { LANDING_MEDIA } from "@/content/landing-media";

// The filmstrip: every frame in landing-media.ts as a horizontal, snap-
// scrolling strip of 9:16 tiles. Each is a keyframe the studio drew for a
// concept on the board, captioned with the concept's own title, so the
// strip is a live sample of what comes out rather than a mood board.

export function FramesSection() {
  return (
    <section id="frames" className="border-b border-border py-24">
      <div className="mx-auto max-w-[1200px] px-6">
        <Reveal className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <span className="eyebrow">Off the board</span>
            <h2 className="serif mt-5 text-[clamp(2rem,4.2vw,3.25rem)]">Frames the studio drew.</h2>
          </div>
          <p className="max-w-sm text-[15px] leading-relaxed text-[#afafaf]">
            Keyframes from recent concepts, each the first frame its clip will anchor on. Nothing
            here is stock.
          </p>
        </Reveal>
      </div>

      <ul className="mt-12 flex snap-x snap-mandatory gap-3 overflow-x-auto px-6 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {LANDING_MEDIA.map((media, i) => (
          <li
            key={media.concept}
            className="group relative aspect-[9/16] w-[220px] shrink-0 snap-start overflow-hidden rounded-[14px] border border-border bg-black sm:w-[260px]"
          >
            <MediaTile media={media} sizes="260px" />
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/85 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100"
            />
            <div className="absolute inset-x-4 bottom-4 translate-y-2 opacity-0 transition-all duration-500 group-hover:translate-y-0 group-hover:opacity-100">
              <span className="eyebrow text-white/70">
                {String(i + 1).padStart(2, "0")} / #{media.concept}
              </span>
              <p className="serif mt-2 text-xl">{media.title}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

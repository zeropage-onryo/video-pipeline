import Image from "next/image";
import { HERO_MEDIA, HERO_STEPS } from "@/content/hero-media";
import { LANDING_MEDIA } from "@/content/landing-media";

// The frame under the headline: a 16:9 plate in a 24px-radius border -- the
// recording of the studio when there is one, its poster (a real screenshot)
// when there is not, three real keyframes off the board with neither
// (see content/hero-media.ts). Under it, the four
// beats of the recording as a strip whose underlines fill in turn.
export function HeroMedia() {
  const stills = LANDING_MEDIA.slice(0, 3);
  return (
    <div className="relative z-10 mx-auto w-full max-w-[1190px] px-6 pb-16">
      <div className="rounded-3xl border border-white/[0.16] bg-card p-[3px]">
        <div className="relative aspect-video overflow-hidden rounded-[20px] bg-[#0f0e0c]">
          {HERO_MEDIA.video ? (
            <video
              className="h-full w-full object-cover"
              src={HERO_MEDIA.video}
              poster={HERO_MEDIA.poster}
              autoPlay
              muted
              loop
              playsInline
              preload="metadata"
              aria-label={HERO_MEDIA.alt}
            />
          ) : HERO_MEDIA.poster ? (
            <Image
              src={HERO_MEDIA.poster}
              alt={HERO_MEDIA.alt}
              fill
              sizes="(min-width: 1190px) 1142px, 100vw"
              priority
              className="object-cover object-top"
            />
          ) : (
            <div className="grid h-full grid-cols-3 gap-[3px]" aria-label="Recent frames off the board">
              {stills.map((media, i) => (
                <div key={media.concept} className="relative overflow-hidden">
                  <Image
                    src={media.src}
                    alt={media.title}
                    fill
                    sizes="(min-width: 1190px) 380px, 33vw"
                    priority={i === 0}
                    quality={70}
                    className="object-cover"
                  />
                  <span className="eyebrow absolute bottom-4 left-4 text-white/70">#{media.concept}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <ol className="mt-6 grid grid-cols-2 gap-x-2 gap-y-4 sm:grid-cols-4">
        {HERO_STEPS.map((step, i) => (
          <li key={step} className="flex flex-col gap-3">
            <span className="text-sm font-medium tracking-[-0.005em] text-foreground">{step}</span>
            <span className="relative block h-px w-full bg-border">
              <span
                className="step-fill absolute inset-0 bg-foreground"
                style={{ animationDelay: `${i * 3}s` }}
              />
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

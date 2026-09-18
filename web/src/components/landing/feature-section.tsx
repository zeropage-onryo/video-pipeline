import Image from "next/image";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { LANDING_MEDIA } from "@/content/landing-media";

// The pipeline as four alternating two-column features -- the sequence is
// real (ground, write, pick, render) so the order is load-bearing. Each
// feature's media column holds real keyframes off the board; `screenshot`
// is the slot for a product screenshot when Mike hands one over, and it
// replaces the stills for that feature only.
type Feature = {
  title: string;
  body: string;
  cta: string;
  stills: [number, number];
  screenshot?: { src: string; alt: string };
};

const FEATURES: Feature[] = [
  {
    title: "Develop the direction",
    body: "Turn a spark, a brief, or a passage from your script into several scene concepts worth exploring. The studio writes the scene; you decide which one is worth the frame.",
    cta: "Start with a spark",
    stills: [0, 1],
  },
  {
    title: "Build the visual world",
    body: "Attach characters, objects, locations, and visual references so every scene begins from your material. A scene with no references never reaches the board.",
    cta: "Bring your references",
    stills: [2, 3],
  },
  {
    title: "Direct every frame",
    body: "Shape the prompt, connect the references, and draw the keyframe in a canvas built for creative decisions. The still you approve is the frame the clip anchors on.",
    cta: "Open the Director",
    stills: [4, 5],
  },
  {
    title: "Put it in motion",
    body: "Choose a model, a frame, and a duration, then render the clip you decided was worth making. The Queue is the only place money is spent, and you are the one who presses it.",
    cta: "See the Queue",
    stills: [1, 4],
  },
];

export function FeatureSection() {
  return (
    <div id="how" className="border-t border-border">
      {FEATURES.map((feature, i) => (
        <section
          key={feature.title}
          className="overflow-x-clip border-b border-border"
          aria-labelledby={`feature-${i}`}
        >
          <div
            className={`mx-auto grid max-w-[1200px] items-center gap-12 px-6 py-20 md:min-h-[640px] md:grid-cols-2 md:gap-16 md:py-16 ${
              i % 2 === 1 ? "md:[&>*:first-child]:order-2" : ""
            }`}
          >
            <div className="max-w-[440px]">
              <span className="eyebrow">Step {String(i + 1).padStart(2, "0")}</span>
              <h2 id={`feature-${i}`} className="serif mt-5 text-[clamp(2rem,4.2vw,3.25rem)]">
                {feature.title}
              </h2>
              <p className="mt-6 text-[17px] leading-relaxed text-[#afafaf]">{feature.body}</p>
              <Link
                href="/studio"
                className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-foreground transition-opacity hover:opacity-80"
              >
                {feature.cta}
                <ArrowRight className="size-4" />
              </Link>
            </div>

            <FeatureMedia feature={feature} priority={i === 0} />
          </div>
        </section>
      ))}
    </div>
  );
}

function FeatureMedia({ feature, priority }: { feature: Feature; priority: boolean }) {
  return (
    <div className="relative">
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-10 rounded-[40px] bg-[radial-gradient(60%_60%_at_50%_50%,rgba(255,255,255,0.05),transparent_70%)]"
      />
      <div className="relative overflow-hidden rounded-[14px] border border-border bg-card p-3">
        {feature.screenshot ? (
          <div className="relative aspect-[4/3] overflow-hidden rounded-lg">
            <Image
              src={feature.screenshot.src}
              alt={feature.screenshot.alt}
              fill
              sizes="(min-width: 768px) 560px, 100vw"
              className="object-cover"
              priority={priority}
            />
          </div>
        ) : (
          <div className="grid aspect-[4/3] grid-cols-2 gap-3">
            {feature.stills.map((n) => {
              const media = LANDING_MEDIA[n % LANDING_MEDIA.length];
              return (
                <div key={media.concept} className="relative overflow-hidden rounded-lg bg-black">
                  <Image
                    src={media.src}
                    alt={media.title}
                    fill
                    sizes="(min-width: 768px) 280px, 50vw"
                    quality={70}
                    className="object-cover"
                    priority={priority}
                  />
                  <span className="eyebrow absolute bottom-3 left-3 text-white/70">#{media.concept}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

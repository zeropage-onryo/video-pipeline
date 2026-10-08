import type { CSSProperties } from "react";
import Image from "next/image";
import Link from "next/link";
import { Spotlight } from "@/components/ui/spotlight-new";
import { Button } from "@/components/ui/button";
import { CreateCtaButton } from "./create-cta-button";
import { ClipPlayer } from "./clips";
import { REVEAL_CLASS as REVEAL } from "@/lib/motion";
import type { MakePage, MakeTile } from "../pages";

const SECONDARY = { label: "See examples", href: "#examples" };

// The homepage hero's bones -- serif H1 at the same scale (bold here),
// centered column -- with the spotlight as this page's one effect. The
// beam is a tint of the page's own ink, not the component's default blue:
// warm white on the dark tone, a soft black on the light one.
const beam = (tone: MakePage["tone"]) => {
  const ink = tone === "light" ? "0, 0, 0" : "250, 248, 244";
  const k = tone === "light" ? 0.7 : 1; // black reads stronger than white
  return {
    first: `radial-gradient(68.54% 68.72% at 55.02% 31.46%, rgba(${ink}, ${0.09 * k}) 0, rgba(${ink}, ${0.025 * k}) 50%, rgba(${ink}, 0) 80%)`,
    second: `radial-gradient(50% 50% at 50% 50%, rgba(${ink}, ${0.07 * k}) 0, rgba(${ink}, ${0.02 * k}) 80%, transparent 100%)`,
    third: `radial-gradient(50% 50% at 50% 50%, rgba(${ink}, ${0.045 * k}) 0, rgba(${ink}, ${0.02 * k}) 80%, transparent 100%)`,
  };
};

// Five shapes (2026-10-08, Mike: "make sure every layout varies"), picked
// by `layout.hero`. All of them stay server-rendered with CSS entrances, so
// the H1 still paints from the HTML (the LCP rule in section-title.tsx);
// the media is the entry's `heroMedia`, a still or a looping clip.
export function MakeHero({ page }: { page: MakePage }) {
  switch (page.layout?.hero) {
    case "split":
      return <SplitHero page={page} />;
    case "cover":
      return <CoverHero page={page} />;
    case "stack":
      return <StackHero page={page} />;
    case "fan":
      return <FanHero page={page} />;
    case "reel":
      return <ReelHero page={page} />;
    case "phone":
      return <PhoneHero page={page} />;
    case "theater":
      return <TheaterHero page={page} />;
    default:
      return <CenterHero page={page} />;
  }
}

function Buttons({ page, align = "center", onDark = false }: { page: MakePage; align?: "center" | "start"; onDark?: boolean }) {
  const secondary = page.cta.secondary ?? SECONDARY;
  return (
    <div
      className={`mt-9 flex w-full max-w-[420px] flex-col items-stretch gap-3 sm:w-auto sm:max-w-none sm:flex-row ${align === "center" ? "sm:items-center" : "sm:items-start"} ${REVEAL} motion-safe:duration-700 motion-safe:delay-200`}
    >
      <CreateCtaButton label={page.cta.label} spark={page.cta.spark} />
      <Button
        size="lg"
        variant="outline"
        className={onDark ? "border-white/40 bg-white/5 text-white backdrop-blur-sm hover:bg-white/15 hover:text-white" : undefined}
        render={<Link href={secondary.href} />}
      >
        {secondary.label}
      </Button>
    </div>
  );
}

/** One hero still or clip, filling its box. */
function Media({ tile, sizes, priority = false, className = "" }: { tile: MakeTile; sizes: string; priority?: boolean; className?: string }) {
  if (tile.video) return <ClipPlayer tile={tile} className={className} />;
  if (!tile.src) return <div aria-hidden className="absolute inset-0" style={{ background: tile.plate ?? "var(--plate-1)" }} />;
  return <Image src={tile.src} alt={tile.title} fill sizes={sizes} priority={priority} quality={78} className={`object-cover ${className}`} />;
}

function CenterHero({ page }: { page: MakePage }) {
  const BEAM = beam(page.tone);
  return (
    <section className="relative overflow-hidden pt-[60px]">
      <div aria-hidden className="absolute inset-0 z-0 overflow-hidden">
        <Spotlight
          gradientFirst={BEAM.first}
          gradientSecond={BEAM.second}
          gradientThird={BEAM.third}
          translateY={-300}
          duration={9}
          xOffset={60}
        />
      </div>

      <div className="relative z-10 mx-auto flex min-h-[460px] max-w-[1200px] flex-col items-center justify-center px-4 pb-16 pt-16 text-center md:min-h-[560px] md:px-6 md:pb-20 md:pt-20">
        <h1
          className={`serif serif-bold max-w-[14ch] text-[clamp(3rem,10.5vw,7.25rem)] ${REVEAL} motion-safe:duration-700`}
        >
          {page.h1}
        </h1>
        <p
          className={`mt-7 max-w-[52ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal tracking-[-0.005em] text-[var(--ink-2)] md:mt-9 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}
        >
          {page.subhead}
        </p>
        <Buttons page={page} />
      </div>
    </section>
  );
}

// The copy on the left, the result large on the right with the inputs that
// made it pinned to its edge as chips -- the Nano Banana page's "these
// references, this still" in one glance.
function SplitHero({ page }: { page: MakePage }) {
  const [main, ...chips] = page.heroMedia ?? [];
  return (
    <section className="relative overflow-hidden pt-[60px]">
      <div className="mx-auto grid max-w-[1200px] items-center gap-12 px-4 pb-16 pt-10 md:px-6 md:pb-24 md:pt-16 lg:grid-cols-[1.05fr_1fr] lg:gap-16">
        <div className="flex flex-col items-start text-left">
          <h1 className={`serif serif-bold max-w-[11ch] text-[clamp(2.9rem,7.4vw,6rem)] ${REVEAL} motion-safe:duration-700`}>
            {page.h1}
          </h1>
          <p
            className={`mt-7 max-w-[46ch] text-[clamp(1rem,1.5vw,1.125rem)] leading-normal text-[var(--ink-2)] ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}
          >
            {page.subhead}
          </p>
          <Buttons page={page} align="start" />
        </div>

        {main && (
          <figure className={`relative mx-auto w-full max-w-[480px] pl-10 sm:pl-16 ${REVEAL} motion-safe:duration-1000 motion-safe:delay-150`}>
            <div className="relative aspect-[4/5] overflow-hidden rounded-[28px] bg-card shadow-[0_30px_80px_-30px_rgba(0,0,0,0.35)]">
              <Media tile={main} sizes="(min-width: 1024px) 480px, 90vw" priority />
              {main.title && (
                <figcaption
                  className={`absolute inset-x-4 flex flex-wrap items-center justify-end gap-2 text-white ${main.video ? "top-4" : "bottom-4"}`}
                >
                  <span className="rounded-full bg-black/55 px-3 py-1.5 text-[12px] font-medium backdrop-blur-md">{main.title}</span>
                  {main.tag && <span className="rounded-full bg-[var(--primary)] px-3 py-1.5 text-[12px] font-semibold text-[var(--primary-foreground)]">{main.tag}</span>}
                </figcaption>
              )}
            </div>
            {chips.length > 0 && (
              <ul className="absolute left-0 top-1/2 flex -translate-y-1/2 flex-col gap-3">
                {chips.map((chip, i) => (
                  <li
                    key={chip.title}
                    style={{ rotate: `${(i - (chips.length - 1) / 2) * -4}deg` }}
                    className="group relative w-[76px] transition-transform duration-300 hover:-translate-y-1 hover:rotate-0 sm:w-[104px]"
                  >
                    <div className="relative aspect-[4/5] overflow-hidden rounded-xl bg-card ring-4 ring-background shadow-lg">
                      <Media tile={chip} sizes="104px" />
                    </div>
                    <span className="absolute -bottom-2 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-foreground px-2 py-0.5 text-[10px] font-semibold text-background">
                      {chip.title}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </figure>
        )}
      </div>
    </section>
  );
}

// The first still full-bleed behind the copy, the way a film poster sells
// the frame before the words -- the FLUX page's "studio-grade" in one image.
function CoverHero({ page }: { page: MakePage }) {
  const main = page.heroMedia?.[0];
  return (
    <section className="relative isolate flex min-h-[620px] items-end overflow-hidden pt-[60px] md:min-h-[760px]">
      {/* the frame starts under the header, which is transparent at the top
          of the page and would set its dark links on the dark picture */}
      <div className="absolute inset-x-0 bottom-0 top-[60px] -z-10">
        {main && <Media tile={main} sizes="100vw" priority />}
        <div aria-hidden className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/35 to-black/5" />
      </div>
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-14 pt-24 text-left text-white md:px-6 md:pb-20">
        <h1 className={`serif serif-bold max-w-[13ch] text-[clamp(3rem,9vw,7rem)] text-white ${REVEAL} motion-safe:duration-700`}>
          {page.h1}
        </h1>
        <div className="mt-6 flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
          <div>
            <p className={`max-w-[48ch] text-[clamp(1rem,1.5vw,1.125rem)] leading-normal text-white/80 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}>
              {page.subhead}
            </p>
            <Buttons page={page} align="start" onDark />
          </div>
          {main?.title && (
            <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-white/60 md:max-w-[30ch] md:text-right">
              {main.title}
              {main.tag ? ` · ${main.tag}` : ""}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

// Centered copy over a row of the media, the middle one raised: three
// results side by side, captioned, before a word of the page is read.
function StackHero({ page }: { page: MakePage }) {
  const media = page.heroMedia ?? [];
  return (
    <section className="relative overflow-hidden pt-[60px]">
      <div className="mx-auto flex max-w-[1200px] flex-col items-center px-4 pt-14 text-center md:px-6 md:pt-20">
        <h1 className={`serif serif-bold max-w-[15ch] text-[clamp(2.9rem,8.6vw,6.5rem)] ${REVEAL} motion-safe:duration-700`}>
          {page.h1}
        </h1>
        <p
          className={`mt-6 max-w-[54ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal text-[var(--ink-2)] md:mt-8 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}
        >
          {page.subhead}
        </p>
        <Buttons page={page} />
      </div>
      {media.length > 0 && (
        <ul
          className={`mx-auto mt-14 grid max-w-[1200px] grid-cols-3 items-end gap-2 px-4 pb-16 sm:gap-4 md:mt-20 md:px-6 md:pb-24 ${REVEAL} motion-safe:duration-1000 motion-safe:delay-200`}
        >
          {media.slice(0, 3).map((tile, i) => (
            <li key={tile.title} className={i === 1 ? "md:-translate-y-10" : ""}>
              <figure>
                <div className="relative aspect-[3/4] overflow-hidden rounded-2xl bg-card md:rounded-3xl">
                  <Media tile={tile} sizes="(min-width: 1200px) 390px, 33vw" priority={i === 1} />
                </div>
                <figcaption className="mt-3 text-left">
                  <span className="block text-[12px] font-semibold leading-tight sm:text-[14px]">{tile.title}</span>
                  {tile.tag && <span className="eyebrow mt-1 block">{tile.tag}</span>}
                </figcaption>
              </figure>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Centered copy over the media fanned like a hand of cards, spreading on
// hover -- posters, for the type page.
const FAN = [
  { rotate: -14, x: -78, y: 26 },
  { rotate: -5, x: -26, y: 4 },
  { rotate: 5, x: 26, y: 4 },
  { rotate: 14, x: 78, y: 26 },
];
function FanHero({ page }: { page: MakePage }) {
  const media = (page.heroMedia ?? []).slice(0, 4);
  return (
    <section className="relative overflow-hidden pt-[60px]">
      <div className="mx-auto flex max-w-[1200px] flex-col items-center px-4 pt-14 text-center md:px-6 md:pt-20">
        <h1 className={`serif serif-bold max-w-[14ch] text-[clamp(2.9rem,9vw,6.75rem)] ${REVEAL} motion-safe:duration-700`}>
          {page.h1}
        </h1>
        <p
          className={`mt-6 max-w-[52ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal text-[var(--ink-2)] md:mt-8 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}
        >
          {page.subhead}
        </p>
        <Buttons page={page} />
      </div>
      {media.length > 0 && (
        <div
          className={`group relative mx-auto mt-12 h-[300px] max-w-[900px] sm:h-[380px] md:mt-16 md:h-[460px] ${REVEAL} motion-safe:duration-1000 motion-safe:delay-200`}
        >
          {media.map((tile, i) => {
            const f = FAN[i + Math.floor((FAN.length - media.length) / 2)] ?? FAN[i];
            return (
              <div
                key={tile.title}
                style={
                  {
                    "--t": `translateX(calc(-50% + ${f.x}%)) translateY(${f.y}px) rotate(${f.rotate}deg)`,
                    "--t-open": `translateX(calc(-50% + ${f.x * 1.45}%)) translateY(${f.y - 14}px) rotate(${f.rotate}deg)`,
                  } as CSSProperties
                }
                className="absolute left-1/2 top-0 w-[33%] max-w-[260px] transition-transform sm:w-[38%] duration-500 ease-out [transform:var(--t)] group-hover:[transform:var(--t-open)] motion-reduce:transition-none"
              >
                <div className="relative aspect-[2/3] overflow-hidden rounded-xl bg-card shadow-[0_24px_60px_-24px_rgba(0,0,0,0.45)]">
                  <Media tile={tile} sizes="260px" priority={i === 1} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// Centered copy over one wide letterboxed clip, its specs pinned to the
// frame -- the LTX page's "this is what it renders" before a word of copy.
function ReelHero({ page }: { page: MakePage }) {
  const main = page.heroMedia?.[0];
  const specs = (main?.meta ?? "").split("·").map((x) => x.trim()).filter(Boolean);
  return (
    <section className="relative overflow-hidden pt-[60px]">
      <div className="mx-auto flex max-w-[1100px] flex-col items-center px-4 pt-14 text-center md:px-6 md:pt-20">
        <h1 className={`serif serif-bold max-w-[14ch] text-[clamp(2.9rem,9vw,6.75rem)] ${REVEAL} motion-safe:duration-700`}>
          {page.h1}
        </h1>
        <p
          className={`mt-6 max-w-[54ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal text-[var(--ink-2)] md:mt-8 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}
        >
          {page.subhead}
        </p>
        <Buttons page={page} />
      </div>
      {main && (
        <figure className={`mx-auto mt-12 max-w-[1320px] px-4 pb-16 md:mt-16 md:px-6 md:pb-24 ${REVEAL} motion-safe:duration-1000 motion-safe:delay-200`}>
          <div className="relative aspect-video overflow-hidden rounded-3xl bg-black md:aspect-[21/9]">
            <Media tile={main} sizes="100vw" priority />
            {specs.length > 0 && (
              <ul className="absolute left-4 top-4 flex flex-wrap gap-2">
                {specs.map((sp) => (
                  <li key={sp} className="rounded-full bg-black/55 px-3 py-1 font-mono text-[11px] uppercase tracking-[0.08em] text-white backdrop-blur-md">
                    {sp}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {main.title && <figcaption className="mt-3 text-[13px] text-[var(--ink-2)]">{main.title}</figcaption>}
        </figure>
      )}
    </section>
  );
}

// The copy on the left, the clip in a phone frame on the right with a
// second phone tilted behind it -- vertical takes of people, the way they
// are watched.
function PhoneHero({ page }: { page: MakePage }) {
  const [main, back] = page.heroMedia ?? [];
  return (
    <section className="relative overflow-hidden pt-[60px]">
      <div className="mx-auto grid max-w-[1200px] items-center gap-12 px-4 pb-16 pt-10 md:px-6 md:pb-24 md:pt-16 lg:grid-cols-[1.1fr_1fr] lg:gap-10">
        <div className="flex flex-col items-start text-left">
          <h1 className={`serif serif-bold max-w-[12ch] text-[clamp(2.9rem,7.4vw,6rem)] ${REVEAL} motion-safe:duration-700`}>{page.h1}</h1>
          <p className={`mt-7 max-w-[46ch] text-[clamp(1rem,1.5vw,1.125rem)] leading-normal text-[var(--ink-2)] ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}>
            {page.subhead}
          </p>
          <Buttons page={page} align="start" />
        </div>
        {main && (
          <div className={`relative mx-auto aspect-[3/4] w-full max-w-[420px] ${REVEAL} motion-safe:duration-1000 motion-safe:delay-150`}>
            {back && (
              <div className="absolute right-0 top-10 aspect-[9/16] w-[58%] rotate-[8deg] overflow-hidden rounded-[30px] border-[6px] border-foreground/80 bg-black opacity-80 shadow-xl">
                <Media tile={{ ...back, video: undefined }} sizes="240px" />
              </div>
            )}
            <div className="absolute left-[4%] top-[2%] aspect-[9/16] w-[64%] -rotate-[3deg] overflow-hidden rounded-[34px] border-[7px] border-foreground bg-black shadow-[0_30px_80px_-30px_rgba(0,0,0,0.6)]">
              <Media tile={main} sizes="280px" priority />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// A dark panel inset under the header, the clip large under the copy and
// its sound toggle the first thing to press -- Veo is bought for its sound.
function TheaterHero({ page }: { page: MakePage }) {
  const main = page.heroMedia?.[0];
  return (
    <section className="relative pt-[60px]">
      <div className="mx-2 overflow-hidden rounded-[28px] bg-[#0a0b10] text-white sm:mx-4 md:rounded-[40px]">
        <div className="mx-auto flex max-w-[1100px] flex-col items-center px-4 pt-14 text-center md:px-6 md:pt-20">
          <h1 className={`serif serif-bold max-w-[13ch] text-[clamp(2.9rem,9vw,6.75rem)] text-white ${REVEAL} motion-safe:duration-700`}>
            {page.h1}
          </h1>
          <p className={`mt-6 max-w-[52ch] text-[clamp(1rem,1.6vw,1.125rem)] leading-normal text-white/70 md:mt-8 ${REVEAL} motion-safe:duration-700 motion-safe:delay-100`}>
            {page.subhead}
          </p>
          <Buttons page={page} onDark />
        </div>
        {main && (
          <figure className={`mx-auto mt-12 max-w-[1040px] px-4 pb-10 md:mt-16 md:px-6 md:pb-16 ${REVEAL} motion-safe:duration-1000 motion-safe:delay-200`}>
            <div className="relative aspect-video overflow-hidden rounded-2xl bg-black ring-1 ring-white/10">
              {main.video ? (
                <ClipPlayer tile={main} label={{ on: "Sound on", off: "Turn the sound on" }} />
              ) : (
                <Media tile={main} sizes="(min-width: 1040px) 1040px, 100vw" priority />
              )}
            </div>
            {main.title && (
              <figcaption className="mt-4 flex flex-wrap items-baseline justify-between gap-2 text-[13px] text-white/60">
                <span>{main.title}</span>
                {main.meta && <span className="font-mono text-[11px] uppercase tracking-[0.12em]">{main.meta}</span>}
              </figcaption>
            )}
          </figure>
        )}
      </div>
    </section>
  );
}

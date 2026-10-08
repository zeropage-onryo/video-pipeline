"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { motion } from "motion/react";
import { SectionTitle } from "./section-title";
import { reveal } from "@/lib/motion";
import { useNearView, useRevealGroup, useStill } from "@/lib/motion-hooks";
import type { MakePage, MakeTile } from "../pages";
import { clipSrc } from "../media";

// The video pages' clips (2026-10-08). Every clip on these pages was
// rendered with its sound (Mike: "use the sound on the page"), and a
// browser only autoplays muted, so each clip carries its own sound toggle.
// One clip speaks at a time: turning one on turns the others off (a window
// event), so a page of four clips never plays four soundtracks at once.
// A clip plays only while it is on screen (the landing page's rule), and
// reduced motion leaves every clip on its poster until it is pressed.
// A clip's poster and video load only once it is within a screen of view
// (`useNearView`); a clip at the top of the page passes `eager`.

const SOUND_EVENT = "zp-clip-sound";

function useOnScreen(ref: React.RefObject<HTMLVideoElement | null>, still: boolean, near: boolean) {
  useEffect(() => {
    const v = ref.current;
    if (!v || still || !near) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) v.play().catch(() => {});
        else v.pause();
      },
      { threshold: 0.25 },
    );
    io.observe(v);
    return () => io.disconnect();
  }, [ref, still, near]);
}

/** One clip filling its box, with a sound toggle. */
export function ClipPlayer({
  tile,
  className = "",
  sound = true,
  label,
  onTime,
  videoRef,
  eager = false,
}: {
  tile: MakeTile;
  className?: string;
  /** Draw the sound toggle (a clip with no track turns it off). */
  sound?: boolean;
  /** The toggle's words; default "Sound on" / "Sound off". */
  label?: { on: string; off: string };
  onTime?: (t: number, v: HTMLVideoElement) => void;
  videoRef?: React.RefObject<HTMLVideoElement | null>;
  /** Load at once (a hero clip); otherwise it waits until it is near view. */
  eager?: boolean;
}) {
  const still = useStill();
  const own = useRef<HTMLVideoElement>(null);
  const ref = videoRef ?? own;
  const box = useRef<HTMLDivElement>(null);
  const near = useNearView(box, { eager });
  const id = useId();
  const [muted, setMuted] = useState(true);
  useOnScreen(ref, still, near);

  useEffect(() => {
    const off = (e: Event) => {
      if ((e as CustomEvent<string>).detail === id) return;
      const v = ref.current;
      if (v && !v.muted) {
        v.muted = true;
        setMuted(true);
      }
    };
    window.addEventListener(SOUND_EVENT, off);
    return () => window.removeEventListener(SOUND_EVENT, off);
  }, [id, ref]);

  const toggle = () => {
    const v = ref.current;
    if (!v) return;
    v.muted = !v.muted;
    if (!v.muted) {
      window.dispatchEvent(new CustomEvent(SOUND_EVENT, { detail: id }));
      v.play().catch(() => {});
    }
    setMuted(v.muted);
  };

  return (
    <div ref={box} className={`absolute inset-0 ${className}`}>
      <video
        ref={ref}
        className="absolute inset-0 h-full w-full object-cover"
        src={near ? clipSrc(tile.video) : undefined}
        poster={near ? tile.src : undefined}
        muted
        loop
        playsInline
        preload={near ? "metadata" : "none"}
        aria-label={tile.title}
        onTimeUpdate={onTime ? (e) => onTime(e.currentTarget.currentTime, e.currentTarget) : undefined}
      />
      {sound && tile.video && (
        <button
          type="button"
          onClick={toggle}
          aria-pressed={!muted}
          className="absolute bottom-3 right-3 z-10 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-3 py-1.5 text-[12px] font-medium text-white backdrop-blur-sm outline-none transition-colors hover:bg-black/75 focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {muted ? <VolumeX className="size-3.5" /> : <Volume2 className="size-3.5" />}
          {muted ? (label?.off ?? "Sound off") : (label?.on ?? "Sound on")}
        </button>
      )}
    </div>
  );
}

const ratio = (tile: MakeTile, fallback: string) => (tile.aspect ?? fallback).replace(":", " / ");

// ---- LTX: the same prompt on both tiers -----------------------------------
// `signatureFrames` = [fast, pro]; each tile's `meta` is its price line,
// read off the catalog by the entry.
export function TierPair({ page }: { page: MakePage }) {
  const [a, b] = page.signatureFrames ?? [];
  if (!a || !b) return null;
  return (
    <section id="tiers" className="border-t border-border bg-[color-mix(in_oklab,var(--primary)_5%,var(--background))]">
      <div className="mx-auto max-w-[1200px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">One prompt, two tiers</span>
          <h2 className="serif max-w-[22ch] text-[clamp(1.75rem,4.2vw,3rem)]">Draft it on Fast. Finish it on Pro.</h2>
        </div>
        <div className="mt-10 grid gap-5 md:mt-14 md:grid-cols-2">
          {[a, b].map((tile) => (
            <figure key={tile.title}>
              <div className="relative overflow-hidden rounded-2xl bg-card" style={{ aspectRatio: ratio(tile, "16:9") }}>
                <ClipPlayer tile={tile} />
                <span className="absolute left-3 top-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-semibold text-white backdrop-blur-sm">
                  {tile.tag}
                </span>
              </div>
              <figcaption className="mt-3 flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-[16px] font-semibold tracking-[-0.01em]">{tile.title}</span>
                {tile.meta && <span className="text-[13px] text-[var(--ink-2)]">{tile.meta}</span>}
              </figcaption>
            </figure>
          ))}
        </div>
        {a.prompt && (
          <p className="mx-auto mt-8 max-w-[70ch] text-center font-mono text-[12px] leading-relaxed text-[var(--ink-2)]">
            &ldquo;{a.prompt}&rdquo;
          </p>
        )}
      </div>
    </section>
  );
}

// ---- Wan: pick the length -------------------------------------------------
// `signatureFrames[0]` is one long clip; its `meta` lists "s|what happens"
// beats ("2|the run up the jetty"). The slider sets the clip's length and
// the clip loops at that second, so the page shows what a shorter take of
// the same scene would hold.
export function LengthDial({ page }: { page: MakePage }) {
  const tile = page.signatureFrames?.[0];
  const beats = (tile?.meta ?? "")
    .split(";")
    .map((b) => b.split("|"))
    .filter((b) => b.length === 2)
    .map(([s, what]) => ({ s: Number(s), what }));
  const [len, setLen] = useState(beats.at(-1)?.s ?? 10);
  const video = useRef<HTMLVideoElement>(null);
  if (!tile) return null;
  const beat = [...beats].reverse().find((b) => b.s <= len) ?? beats[0];
  const loop = (t: number, v: HTMLVideoElement) => {
    if (t >= len) v.currentTime = 0;
  };
  return (
    <section id="length" className="border-t border-border">
      <div className="mx-auto max-w-[1000px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Two to ten seconds a clip</span>
          <h2 className="serif max-w-[22ch] text-[clamp(1.75rem,4.2vw,3rem)]">Pick the length. The take holds that much.</h2>
        </div>
        <div className="mt-10 overflow-hidden rounded-2xl bg-card md:mt-14" style={{ aspectRatio: ratio(tile, "16:9") }}>
          <div className="relative h-full w-full">
            <ClipPlayer tile={tile} videoRef={video} onTime={loop} />
            <span className="absolute left-3 top-3 rounded-md bg-black/55 px-2 py-1 font-mono text-[12px] text-white backdrop-blur-sm">
              {len}s
            </span>
          </div>
        </div>
        <div className="mx-auto mt-6 max-w-[640px]">
          <label htmlFor="wan-length" className="sr-only">
            Clip length in seconds
          </label>
          <input
            id="wan-length"
            type="range"
            min={2}
            max={beats.at(-1)?.s ?? 10}
            step={1}
            value={len}
            onChange={(e) => {
              const n = Number(e.target.value);
              setLen(n);
              const v = video.current;
              if (v && v.currentTime >= n) v.currentTime = 0;
            }}
            className="w-full accent-[var(--primary)]"
          />
          <div className="mt-1 flex justify-between font-mono text-[11px] text-[var(--ink-2)]">
            <span>2s</span>
            <span>{beats.at(-1)?.s ?? 10}s</span>
          </div>
          <p aria-live="polite" className="mt-4 text-center text-[15px] text-[var(--ink-2)]">
            At <span className="font-semibold text-foreground">{len} seconds</span> the clip holds {beat?.what}.
          </p>
        </div>
      </div>
    </section>
  );
}

// ---- Veo: the sound board --------------------------------------------------
// `signatureFrames` are clips whose sound is the point; `meta` names what
// you hear. Pressing one plays it with sound and quiets the rest.
export function SoundBoard({ page }: { page: MakePage }) {
  const clips = page.signatureFrames ?? [];
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLDivElement>(0.15);
  if (!clips.length) return null;
  return (
    <section id="sound" className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Picture and sound, one pass</span>
          <h2 className="serif max-w-[24ch] text-[clamp(1.75rem,4.2vw,3rem)]">Turn the sound on. It was rendered with the frame.</h2>
        </div>
        <div ref={ref} className="mt-10 grid gap-5 md:mt-14 md:grid-cols-3">
          {clips.map((tile, i) => (
            <motion.figure key={tile.title} {...reveal(i, { still, show })}>
              <div className="relative overflow-hidden rounded-2xl bg-card" style={{ aspectRatio: ratio(tile, "16:9") }}>
                <ClipPlayer tile={tile} label={{ on: "Listening", off: "Hear it" }} />
              </div>
              <figcaption className="mt-3">
                <span className="block text-[16px] font-semibold tracking-[-0.01em]">{tile.title}</span>
                {tile.meta && <span className="mt-1 block text-[13.5px] leading-snug text-[var(--ink-2)]">{tile.meta}</span>}
              </figcaption>
            </motion.figure>
          ))}
        </div>
      </div>
    </section>
  );
}

// ---- Kling: a row of vertical takes ---------------------------------------
export function ReelsWall({ page }: { page: MakePage }) {
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLUListElement>(0.12);
  return (
    <section id="examples" className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-4 pb-16 pt-16 md:px-6 md:pb-24 md:pt-24">
        <SectionTitle>{page.wall.title}</SectionTitle>
        <ul ref={ref} className="mx-auto mt-10 grid max-w-[1000px] grid-cols-1 gap-6 sm:grid-cols-3 md:mt-14">
          {page.wall.tiles.map((tile, i) => (
            <motion.li key={tile.title} {...reveal(i, { still, show, y: 32 })} className={i === 1 ? "sm:mt-12" : ""}>
              <figure>
                <div className="relative mx-auto aspect-[9/16] max-w-[260px] overflow-hidden sm:max-w-[320px] rounded-[28px] border-[6px] border-foreground bg-black shadow-[0_24px_60px_-28px_rgba(0,0,0,0.55)]">
                  <ClipPlayer tile={tile} />
                </div>
                <figcaption className="mx-auto mt-4 max-w-[260px] sm:max-w-[320px]">
                  <span className="block text-[16px] font-semibold tracking-[-0.01em]">{tile.title}</span>
                  {tile.meta && <span className="mt-1 block text-[13.5px] leading-snug text-[var(--ink-2)]">{tile.meta}</span>}
                </figcaption>
              </figure>
            </motion.li>
          ))}
        </ul>
      </div>
    </section>
  );
}

"use client";

import Image from "next/image";
import { useEffect, useRef, type PointerEvent } from "react";
import { ClipPlayer } from "./clips";
import { motion, useMotionTemplate, useMotionValue, useSpring, useTransform } from "motion/react";
import { EASE_OUT, RISE, SPRINGS } from "@/lib/motion";
import { useNearView, useRevealBelowFold, useStill } from "@/lib/motion-hooks";
import type { MakeOverviewBlock, MakePage, MakeTile } from "../pages";
import { clipSrc } from "../media";

// The overview (2026-10-07, Mike's call): the shape of ByteDance's own
// Seedance 2.5 page -- a run of headline claims, each one line of serif,
// a sentence or two, and a demo beside it -- carried on the entry as
// `overview.items` so any model page can have one. The text and the media
// alternate sides; the media slot is a wall tile (a plate until a real
// still or clip lands). Two extras a block can ask for: `sound` (an
// unmute toggle, since autoplay is always muted) and `compare` (a second
// clip under a draggable divider, a draft against its final). Clips play
// only while on screen. A block is VISIBLE in the server HTML and only one
// that mounts below the fold rises in (useRevealBelowFold, the section
// titles' rule): on a phone the first block sits just under the hero and
// its paragraph was the page's LCP, held invisible until hydration ran
// the entrance (2026-10-08, Lighthouse mobile LCP 6.4 s). Nothing moves
// under reduced motion. A page with no `overview` draws nothing.

const PLATES = ["var(--plate-1)", "var(--plate-2)"];

export function OverviewSection({ page }: { page: MakePage }) {
  const items = page.overview?.items ?? [];
  const still = useStill();
  if (!items.length) return null;
  return (
    <section id="overview" className="border-t border-border">
      <div className="mx-auto flex max-w-[1100px] flex-col gap-16 px-4 py-20 md:gap-24 md:px-6 md:py-24">
        {items.map((block, i) => (
          <Block key={block.title} block={block} index={i} flip={i % 2 === 1} still={still} />
        ))}
      </div>
    </section>
  );
}

function Block({
  block,
  index,
  flip,
  still,
}: {
  block: MakeOverviewBlock;
  index: number;
  flip: boolean;
  still: boolean;
}) {
  const plate = block.media?.plate ?? PLATES[index % PLATES.length];
  const { ref, shown, instant } = useRevealBelowFold<HTMLDivElement>(still, 0.15);
  return (
    <motion.div
      ref={ref}
      initial={false}
      animate={shown ? RISE.shown : RISE.hidden}
      transition={instant ? { duration: 0 } : { duration: 0.55, ease: EASE_OUT }}
      className={`grid items-center gap-8 md:grid-cols-2 md:gap-14 ${flip ? "md:[&>*:first-child]:order-2" : ""}`}
    >
      <div className="flex flex-col gap-4">
        {block.eyebrow && <span className="eyebrow">{block.eyebrow}</span>}
        <h2 className="serif text-[clamp(1.75rem,4vw,2.75rem)] leading-[1.08]">{block.title}</h2>
        <p className="text-[15.5px] leading-relaxed text-[var(--ink-2)] md:text-[17px]">{block.body}</p>
        {block.points && block.points.length > 0 && (
          <ul className="mt-1 flex flex-col gap-2">
            {block.points.map((p) => (
              <li key={p} className="flex gap-3 text-[14.5px] leading-relaxed text-[var(--ink-2)]">
                <span aria-hidden className="mt-[0.6em] size-1.5 shrink-0 rounded-full bg-primary" />
                <span>{p}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {block.compare ? (
        <Compare left={block.compare.media} right={block.media} leftLabel={block.compare.label} rightLabel={block.compare.mediaLabel} plate={plate} still={still} />
      ) : (
        <Media tile={block.media} title={block.title} plate={plate} still={still} sound={Boolean(block.sound)} />
      )}
    </motion.div>
  );
}

/** Play a clip only while its frame is on screen (the landing page's rule). */
function useOnScreenPlay(ref: React.RefObject<HTMLElement | null>, still: boolean, near: boolean) {
  useEffect(() => {
    const el = ref.current;
    const videos = el ? Array.from(el.querySelectorAll("video")) : [];
    if (!el || !videos.length || still || !near) return;
    const io = new IntersectionObserver(
      ([entry]) => videos.forEach((v) => (entry.isIntersecting ? v.play().catch(() => {}) : v.pause())),
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref, still, near]);
}

/** A slot's picture. A clip's poster and video load only once `near`. */
function Fill({ tile, alt, plate, near }: { tile?: MakeTile; alt: string; plate: string; near: boolean }) {
  if (tile?.video)
    return (
      <video
        className="absolute inset-0 size-full object-cover"
        src={near ? clipSrc(tile.video) : undefined}
        poster={near ? tile.src : undefined}
        muted
        loop
        playsInline
        preload="none"
      />
    );
  if (tile?.src)
    return <Image src={tile.src} alt={alt} fill sizes="(min-width: 768px) 50vw, 100vw" quality={70} className="object-cover" />;
  return <div aria-hidden className="absolute inset-0" style={{ background: plate }} />;
}

/** A vertical frame (9:16, 2:3): drawn narrower so the block stays a block. */
const tall = (aspect: string) => {
  const [w, h] = aspect.split(":").map(Number);
  return h / w > 1.3;
};

/** A landscape frame (16:9, 21:9): drawn at the column's full width. */
const wide = (aspect: string) => {
  const [w, h] = aspect.split(":").map(Number);
  return w / h > 1.4;
};

const CHIP = "rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm";

function Media({ tile, title, plate, still, sound }: { tile?: MakeTile; title: string; plate: string; still: boolean; sound: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useNearView(ref);
  useOnScreenPlay(ref, still, near);
  // a clip with sound goes through the shared player (clips.tsx), so it
  // obeys the page's one-soundtrack-at-a-time rule like every other clip
  const speaks = Boolean(sound && tile?.video);
  const frame = tile?.aspect
    ? tall(tile.aspect)
      ? "mx-auto max-w-[300px]"
      : wide(tile.aspect)
        ? ""
        : "mx-auto max-w-[460px]"
    : "aspect-[4/3]";
  return (
    <div
      ref={ref}
      // a tile's own frame when it names one (a 4:5 label still must not be
      // cropped to 4:3 and lose its words); 4:3 otherwise, as before
      style={tile?.aspect ? { aspectRatio: tile.aspect.replace(":", " / ") } : undefined}
      className={`relative w-full overflow-hidden rounded-2xl bg-card ${frame}`}
    >
      {speaks && tile ? <ClipPlayer tile={tile} /> : <Fill tile={tile} alt={tile?.title || title} plate={plate} near={near} />}
      {tile?.tag && <span className={`absolute bottom-3 left-3 z-10 ${CHIP}`}>{tile.tag}</span>}
    </div>
  );
}

/** Two clips under one divider: the left one revealed up to the handle. */
function Compare({
  left,
  right,
  leftLabel,
  rightLabel,
  plate,
  still,
}: {
  left: MakeTile;
  right?: MakeTile;
  leftLabel: string;
  rightLabel: string;
  plate: string;
  still: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useNearView(ref);
  useOnScreenPlay(ref, still, near);
  const raw = useMotionValue(0.5);
  const x = useSpring(raw, still ? { stiffness: 1000, damping: 100 } : SPRINGS.glow);
  const clip = useMotionTemplate`inset(0 ${useTransform(x, (v) => (1 - v) * 100)}% 0 0)`;
  const handle = useMotionTemplate`${useTransform(x, (v) => v * 100)}%`;
  const set = (clientX: number) => {
    const r = ref.current?.getBoundingClientRect();
    if (r) raw.set(Math.min(1, Math.max(0, (clientX - r.left) / r.width)));
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === "touch" && e.buttons === 0) return;
    set(e.clientX);
  };
  return (
    <div
      ref={ref}
      onPointerMove={onMove}
      onPointerDown={(e) => set(e.clientX)}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") raw.set(Math.max(0, raw.get() - 0.1));
        if (e.key === "ArrowRight") raw.set(Math.min(1, raw.get() + 0.1));
      }}
      tabIndex={0}
      role="slider"
      aria-label={`${leftLabel} against ${rightLabel}`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={50}
      className="relative aspect-[4/3] w-full touch-pan-y overflow-hidden rounded-2xl bg-card outline-none select-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <Fill tile={right} alt={rightLabel} plate={plate} near={near} />
      <motion.div aria-hidden style={{ clipPath: clip }} className="absolute inset-0">
        <Fill tile={left} alt={leftLabel} plate={left.plate ?? "var(--plate-2)"} near={near} />
      </motion.div>
      <span className={`absolute top-3 left-3 ${CHIP}`}>{leftLabel}</span>
      <span className={`absolute top-3 right-3 ${CHIP}`}>{rightLabel}</span>
      <motion.div aria-hidden style={{ left: handle }} className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-white/90">
        <span className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary px-2.5 py-1 text-[11px] font-semibold text-primary-foreground">
          drag
        </span>
      </motion.div>
    </div>
  );
}

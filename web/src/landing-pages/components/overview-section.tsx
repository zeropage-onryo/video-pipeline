"use client";

import Image from "next/image";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { motion, useMotionTemplate, useMotionValue, useSpring, useTransform } from "motion/react";
import { SPRINGS, reveal } from "@/lib/motion";
import { useRevealGroup, useStill } from "@/lib/motion-hooks";
import type { MakeOverviewBlock, MakePage, MakeTile } from "../pages";

// The overview (2026-10-07, Mike's call): the shape of ByteDance's own
// Seedance 2.5 page -- a run of headline claims, each one line of serif,
// a sentence or two, and a demo beside it -- carried on the entry as
// `overview.items` so any model page can have one. The text and the media
// alternate sides; the media slot is a wall tile (a plate until a real
// still or clip lands). Two extras a block can ask for: `sound` (an
// unmute toggle, since autoplay is always muted) and `compare` (a second
// clip under a draggable divider, a draft against its final). Clips play
// only while on screen. Blocks rise in off ONE observer; nothing moves
// under reduced motion. A page with no `overview` draws nothing.

const PLATES = ["var(--plate-1)", "var(--plate-2)"];

export function OverviewSection({ page }: { page: MakePage }) {
  const items = page.overview?.items ?? [];
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLDivElement>(0.1);
  if (!items.length) return null;
  return (
    <section id="overview" className="border-t border-border">
      <div ref={ref} className="mx-auto flex max-w-[1100px] flex-col gap-16 px-4 py-20 md:gap-24 md:px-6 md:py-24">
        {items.map((block, i) => (
          <Block key={block.title} block={block} index={i} flip={i % 2 === 1} still={still} show={show} />
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
  show,
}: {
  block: MakeOverviewBlock;
  index: number;
  flip: boolean;
  still: boolean;
  show: boolean;
}) {
  const plate = block.media?.plate ?? PLATES[index % PLATES.length];
  return (
    <motion.div
      {...reveal(index, { still, show })}
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
function useOnScreenPlay(ref: React.RefObject<HTMLElement | null>, still: boolean) {
  useEffect(() => {
    const el = ref.current;
    const videos = el ? Array.from(el.querySelectorAll("video")) : [];
    if (!el || !videos.length || still) return;
    const io = new IntersectionObserver(
      ([entry]) => videos.forEach((v) => (entry.isIntersecting ? v.play().catch(() => {}) : v.pause())),
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref, still]);
}

function Fill({ tile, alt, plate }: { tile?: MakeTile; alt: string; plate: string }) {
  if (tile?.video)
    return <video className="absolute inset-0 size-full object-cover" src={tile.video} poster={tile.src} muted loop playsInline preload="none" />;
  if (tile?.src)
    return <Image src={tile.src} alt={alt} fill sizes="(min-width: 768px) 50vw, 100vw" quality={70} className="object-cover" />;
  return <div aria-hidden className="absolute inset-0" style={{ background: plate }} />;
}

const CHIP = "rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm";

function Media({ tile, title, plate, still, sound }: { tile?: MakeTile; title: string; plate: string; still: boolean; sound: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [muted, setMuted] = useState(true);
  useOnScreenPlay(ref, still);
  const toggle = () => {
    const v = ref.current?.querySelector("video");
    if (!v) return;
    v.muted = !v.muted;
    if (!v.muted) v.play().catch(() => {});
    setMuted(v.muted);
  };
  return (
    <div
      ref={ref}
      // a tile's own frame when it names one (a 4:5 label still must not be
      // cropped to 4:3 and lose its words); 4:3 otherwise, as before
      style={tile?.aspect ? { aspectRatio: tile.aspect.replace(":", " / ") } : undefined}
      className={`relative w-full overflow-hidden rounded-2xl bg-card ${tile?.aspect ? "mx-auto max-w-[460px]" : "aspect-[4/3]"}`}
    >
      <Fill tile={tile} alt={tile?.title || title} plate={plate} />
      {tile?.tag && <span className={`absolute bottom-3 left-3 ${CHIP}`}>{tile.tag}</span>}
      {sound && tile?.video && (
        <button
          type="button"
          onClick={toggle}
          aria-pressed={!muted}
          className="absolute right-3 bottom-3 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-3 py-1.5 text-[12px] font-medium text-white backdrop-blur-sm outline-none transition-colors hover:bg-black/75 focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {muted ? <VolumeX className="size-3.5" /> : <Volume2 className="size-3.5" />}
          {muted ? "Sound off" : "Sound on"}
        </button>
      )}
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
  useOnScreenPlay(ref, still);
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
      <Fill tile={right} alt={rightLabel} plate={plate} />
      <motion.div aria-hidden style={{ clipPath: clip }} className="absolute inset-0">
        <Fill tile={left} alt={leftLabel} plate={left.plate ?? "var(--plate-2)"} />
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

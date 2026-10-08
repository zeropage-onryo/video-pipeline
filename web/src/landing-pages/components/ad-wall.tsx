"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { ArrowRight } from "lucide-react";
import { motion, useMotionValue, useSpring, useTransform } from "motion/react";
import { SectionTitle } from "./section-title";
import { ShowcaseWall } from "./showcase-wall";
import { EditorialWall, FilmstripWall, PostersWall, PromptsWall } from "./walls";
import { Button } from "@/components/ui/button";
import { SPRINGS, reveal } from "@/lib/motion";
import { useRevealGroup, useStill } from "@/lib/motion-hooks";
import type { MakePage, MakeTile } from "../pages";

// The wall right under the hero, in the shape of InVideo's model wall
// (2026-10-01, Mike's reference): one line of heavy condensed uppercase, a
// four-column bento of tiles with a bold label and a chip, and one button
// under it. Nothing else -- no eyebrow, no dek.
//
// The tiles are interactive on Motion: they rise in with a stagger, lift
// and tilt toward the pointer on hover (a spring, so they settle rather
// than snap), the still inside pushes in, and the label slides up. Every
// bit of it is off under reduced motion.

// The gradient plates are the page's accent (theme.ts): `--plate-1` and
// `--plate-2` on the skin wrapper, the reference's two colour slots.
const PLATES = ["var(--plate-1)", "var(--plate-2)"];

// Below lg every wrapper is `contents`, so the eight tiles fall into one
// two-column grid; at lg the wrappers become the reference's four columns
// (14 / 30 / 20 / 36) and the last column ends in a row of two.
const COL = "contents lg:flex lg:flex-col lg:gap-4";

export function AdWall({ page }: { page: MakePage }) {
  switch (page.wall.layout) {
    case "showcase":
      return <ShowcaseWall page={page} />;
    case "filmstrip":
      return <FilmstripWall page={page} />;
    case "prompts":
      return <PromptsWall page={page} />;
    case "editorial":
      return <EditorialWall page={page} />;
    case "posters":
      return <PostersWall page={page} />;
    default:
      return <BentoWall page={page} />;
  }
}

function BentoWall({ page }: { page: MakePage }) {
  const still = useStill();
  // ONE observer on the wall drives every tile's entrance (lib/motion's
  // rule, learned here 2026-10-01): once a fifth of the wall is on screen
  // the eight rise in with a stagger, and a tile never waits on its own
  // intersection.
  const { ref: wall, show } = useRevealGroup<HTMLDivElement>(0.15);
  const t = page.wall.tiles;
  const tile = (i: number, h: number, extra = "") =>
    t[i] ? (
      <Tile key={i} tile={t[i]} index={i} still={still} show={show} plate={PLATES[i % PLATES.length]} height={h} className={extra} />
    ) : null;

  return (
    <section id="examples" className="relative overflow-hidden border-t border-border">
      <div className="mx-auto max-w-[1440px] px-4 pb-16 pt-16 md:px-6 md:pb-20 md:pt-24">
        <SectionTitle className="lg:whitespace-nowrap">{page.wall.title}</SectionTitle>

        <div ref={wall} className="mt-10 grid grid-cols-2 gap-3 md:mt-14 lg:flex lg:h-[560px] lg:gap-4">
          <div className={`${COL} lg:w-[14%]`}>
            {tile(0, 0.26)}
            {tile(1, 0.74)}
          </div>
          <div className={`${COL} lg:w-[30%]`}>
            {tile(2, 0.5)}
            {tile(3, 0.5)}
          </div>
          <div className={`${COL} lg:w-[20%]`}>{tile(4, 1)}</div>
          <div className={`${COL} lg:w-[36%]`}>
            {tile(5, 0.56)}
            <div className="contents lg:flex lg:min-h-0 lg:basis-[44%] lg:gap-4">
              {tile(6, 1, "lg:flex-1")}
              {tile(7, 1, "lg:flex-1")}
            </div>
          </div>
        </div>

        <div className="mt-10 flex justify-center md:mt-12">
          <Button size="lg" render={<Link href={page.wall.explore.href} />}>
            {page.wall.explore.label}
            <ArrowRight data-icon="inline-end" className="size-4" />
          </Button>
        </div>
      </div>
    </section>
  );
}

const TILT = 7; // degrees at a tile's edge

export function Tile({
  tile,
  index,
  still,
  show,
  plate,
  className,
  height,
}: {
  tile: MakeTile;
  index: number;
  still: boolean;
  show: boolean;
  plate: string;
  className?: string;
  /** The tile's share of its column's height; absent in a grid. */
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState(false);
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const rotateY = useSpring(useTransform(px, [-0.5, 0.5], [-TILT, TILT]), SPRINGS.settle);
  const rotateX = useSpring(useTransform(py, [-0.5, 0.5], [TILT, -TILT]), SPRINGS.settle);

  // a looping tile plays only while on screen (the landing page's rule)
  useEffect(() => {
    const el = ref.current;
    const video = el?.querySelector("video");
    if (!el || !video || still) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) video.play().catch(() => {});
        else video.pause();
      },
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [still]);

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el || still || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width - 0.5);
    py.set((e.clientY - r.top) / r.height - 0.5);
  };
  const onLeave = () => {
    px.set(0);
    py.set(0);
    setHover(false);
  };

  const labelled = Boolean(tile.title);
  const inRow = (className ?? "").includes("flex-1");

  return (
    <motion.div
      ref={ref}
      {...reveal(index, { still, show, y: 28, scale: 0.97, duration: 0.6, base: 0.08 })}
      whileHover={still ? undefined : { scale: 1.03, zIndex: 2 }}
      onPointerMove={onMove}
      onPointerEnter={() => setHover(true)}
      onPointerLeave={onLeave}
      // in a column the tile's share of the height is its flex-basis; in
      // the last column's row the two share the width equally instead
      style={{
        rotateX: still ? 0 : rotateX,
        rotateY: still ? 0 : rotateY,
        transformPerspective: 1100,
        ...(inRow
          ? { flex: "1 1 0%" }
          : height !== undefined
            ? { flexBasis: `${height * 100}%`, flexGrow: 0, flexShrink: 1 }
            : {}),
      }}
      className={`group relative aspect-[4/5] overflow-hidden rounded-2xl bg-card ${height !== undefined || inRow ? "lg:aspect-auto lg:min-h-0" : ""} ${className ?? ""}`}
    >
      {tile.src ? (
        tile.video ? (
          <video
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-700 ease-out group-hover:scale-105"
            src={tile.video}
            poster={tile.src}
            muted
            loop
            playsInline
            preload="none"
            aria-label={tile.title}
          />
        ) : (
          <Image
            src={tile.src}
            alt={tile.title}
            fill
            sizes="(min-width: 1024px) 30vw, 50vw"
            quality={70}
            className="object-cover transition-transform duration-700 ease-out group-hover:scale-105"
            priority={index < 4}
          />
        )
      ) : (
        <div aria-hidden className="absolute inset-0" style={{ background: tile.plate ?? plate }} />
      )}

      {labelled && (
        <>
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/70 to-transparent"
          />
          <motion.div
            animate={still ? undefined : { y: hover ? 0 : 6 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
            className="absolute inset-x-4 bottom-4 flex flex-col items-start gap-2 text-white"
          >
            <span className="text-[15px] font-semibold leading-tight tracking-[-0.01em] md:text-[17px]">
              {tile.title}
            </span>
            {tile.tag && (
              <span className="rounded-md bg-white/15 px-2 py-1 text-[11px] font-medium backdrop-blur-sm">
                {tile.tag}
              </span>
            )}
            {tile.meta && <span className="text-[12px] text-white/75">{tile.meta}</span>}
          </motion.div>
        </>
      )}
    </motion.div>
  );
}

"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { SectionTitle } from "./section-title";
import { CreateCtaButton } from "./create-cta-button";
import { Button } from "@/components/ui/button";
import { EASE_OUT, reveal } from "@/lib/motion";
import { useNearView, useRevealGroup, useStill } from "@/lib/motion-hooks";
import type { MakePage, MakeTile } from "../pages";
import { clipSrc } from "../media";

// The showcase wall (2026-10-07, Mike's reference: ByteDance's "Creativity
// Unleashed" grid on the Seedance 2.5 page). Three masonry columns of
// tiles in their own frames, a mode chip on each ("I2V"), the feature it
// shows along the bottom; clicking a tile opens the prompt it was made
// from right underneath it, with "Use this prompt" into the composer. One
// tile open at a time.
//
// The columns are FIXED, not CSS `columns`: an opened prompt only pushes
// its own column down, where CSS columns would reflow every tile across
// the grid. Tiles are dealt to the shortest column by frame (a pure
// function of the entry, so the server and the browser agree). Below md
// the three columns stack into one. Under reduced motion nothing animates
// and clips do not autoplay.

const PLATES = ["var(--plate-1)", "var(--plate-2)"];
const COLUMNS = 3;

const ratio = (aspect?: string) => {
  const [w, h] = (aspect ?? "3:4").split(":").map(Number);
  return w > 0 && h > 0 ? { w, h } : { w: 3, h: 4 };
};

/** Deal tiles to the shortest column, by height-for-width, in entry order. */
function deal(tiles: MakeTile[]): { tile: MakeTile; index: number }[][] {
  const cols: { tile: MakeTile; index: number }[][] = Array.from({ length: COLUMNS }, () => []);
  const heights = new Array(COLUMNS).fill(0);
  tiles.forEach((tile, index) => {
    const { w, h } = ratio(tile.aspect);
    const c = heights.indexOf(Math.min(...heights));
    cols[c].push({ tile, index });
    heights[c] += h / w;
  });
  return cols;
}

export function ShowcaseWall({ page }: { page: MakePage }) {
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLDivElement>(0.1);
  const [open, setOpen] = useState<number | null>(null);
  const columns = deal(page.wall.tiles);

  return (
    <section id="examples" className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-4 py-16 md:px-6 md:py-24">
        <SectionTitle>{page.wall.title}</SectionTitle>

        <div ref={ref} className="mt-10 flex flex-col gap-3 md:mt-14 md:flex-row md:items-start md:gap-4">
          {columns.map((col, c) => (
            <div key={c} className="flex flex-1 flex-col gap-3 md:gap-4">
              {col.map(({ tile, index }) => (
                <ShowcaseTile
                  key={index}
                  tile={tile}
                  index={index}
                  still={still}
                  show={show}
                  open={open === index}
                  onToggle={() => setOpen((o) => (o === index ? null : index))}
                />
              ))}
            </div>
          ))}
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

function ShowcaseTile({
  tile,
  index,
  still,
  show,
  open,
  onToggle,
}: {
  tile: MakeTile;
  index: number;
  still: boolean;
  show: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const media = useRef<HTMLButtonElement>(null);
  const { w, h } = ratio(tile.aspect);
  const panelId = `showcase-prompt-${index}`;
  // the poster and the clip load only once the tile is within a screen of view
  const near = useNearView(media);

  // a clip plays only while on screen (the landing page's rule)
  useEffect(() => {
    const el = media.current;
    const video = el?.querySelector("video");
    if (!el || !video || still || !near) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) video.play().catch(() => {});
        else video.pause();
      },
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [still, near]);

  return (
    <motion.div {...reveal(index, { still, show, y: 24, duration: 0.55, base: 0.06 })} className="flex flex-col">
      <button
        ref={media}
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={tile.prompt ? panelId : undefined}
        aria-label={`${tile.title}${tile.prompt ? (open ? ", hide the prompt" : ", show the prompt") : ""}`}
        style={{ aspectRatio: `${w} / ${h}` }}
        className={`group relative w-full overflow-hidden rounded-2xl bg-card text-left outline-none transition-shadow duration-300 focus-visible:ring-3 focus-visible:ring-ring/50 ${open ? "ring-2 ring-primary" : ""}`}
      >
        {tile.video ? (
          <video
            className="absolute inset-0 size-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.03]"
            src={near ? clipSrc(tile.video) : undefined}
            poster={near ? tile.src : undefined}
            muted
            loop
            playsInline
            preload="none"
          />
        ) : tile.src ? (
          <Image
            src={tile.src}
            alt=""
            fill
            sizes="(min-width: 768px) 33vw, 100vw"
            quality={70}
            className="object-cover transition-transform duration-700 ease-out group-hover:scale-[1.03]"
          />
        ) : (
          <div aria-hidden className="absolute inset-0" style={{ background: tile.plate ?? PLATES[index % PLATES.length] }} />
        )}

        {tile.mode && (
          <span className="absolute top-3 left-3 rounded-md bg-black/60 px-2 py-1 text-[12px] font-medium tracking-[0.01em] text-white backdrop-blur-sm">
            {tile.mode}
          </span>
        )}
        {tile.title && (
          <>
            <span aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-2/5 bg-gradient-to-t from-black/60 to-transparent" />
            <span className="absolute inset-x-3 bottom-3 flex items-end justify-between gap-3 text-white">
              <span className="text-[14px] font-semibold leading-tight tracking-[-0.01em] md:text-[15px]">{tile.title}</span>
              {tile.prompt && (
                <span className="shrink-0 rounded-full bg-white/20 px-2.5 py-1 text-[11px] font-medium backdrop-blur-sm transition-colors group-hover:bg-white/30">
                  {open ? "Hide prompt" : "Prompt"}
                </span>
              )}
            </span>
          </>
        )}
      </button>

      <AnimatePresence initial={false}>
        {open && tile.prompt && (
          <motion.div
            id={panelId}
            key="panel"
            initial={still ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={still ? undefined : { height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: EASE_OUT }}
            className="overflow-hidden"
          >
            <div className="mt-2 rounded-xl border border-[var(--card-line)] bg-background p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] font-medium text-[var(--ink-3)]">
                  {tile.tag && <span className="text-foreground">{tile.tag}</span>}
                  {tile.meta && <span>{tile.meta}</span>}
                </div>
                <button
                  type="button"
                  onClick={onToggle}
                  aria-label="Close the prompt"
                  className="-m-1 rounded-md p-1 text-[var(--ink-3)] transition-colors hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              </div>
              <p className="mt-2 text-[14px] leading-relaxed text-[var(--ink-2)]">{tile.prompt}</p>
              <CreateCtaButton variant="link" label="Use this prompt" spark={tile.prompt} className="mt-3" />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

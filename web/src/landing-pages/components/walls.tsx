"use client";

import Image from "next/image";
import Link from "next/link";
import { useRef } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { motion } from "motion/react";
import { SectionTitle } from "./section-title";
import { CreateCtaButton } from "./create-cta-button";
import { Button } from "@/components/ui/button";
import { reveal } from "@/lib/motion";
import { useRevealGroup, useStill } from "@/lib/motion-hooks";
import type { MakePage, MakeTile } from "../pages";

// The walls a page can have besides the bento and the showcase (2026-10-08,
// Mike: "make sure every layout varies so neither one is identical"). Each
// is the same eight-or-so tiles off the entry, drawn a different way:
//
// - filmstrip: one row at a fixed height, each still at its own frame,
//   scrolled sideways (or by the two arrows), a caption under each;
// - prompts: every still above the prompt that drew it, the words the
//   model had to get right marked [[like this]] in the entry;
// - editorial: one large plate beside numbered figures, a magazine spread;
// - posters: 2:3 posters in a staggered row on a tint of the page's colour.
//
// The tiles rise in on one observer (lib/motion's rule); reduced motion
// shows them in place.

const ratio = (tile: MakeTile, fallback = "4:5") => (tile.aspect ?? fallback).replace(":", " / ");

function Still({ tile, sizes, className = "" }: { tile: MakeTile; sizes: string; className?: string }) {
  if (tile.video) {
    return (
      <video
        className={`absolute inset-0 h-full w-full object-cover ${className}`}
        src={tile.video}
        poster={tile.src}
        autoPlay
        muted
        loop
        playsInline
        preload="none"
        aria-label={tile.title}
      />
    );
  }
  if (!tile.src) return <div aria-hidden className="absolute inset-0" style={{ background: tile.plate ?? "var(--plate-1)" }} />;
  return <Image src={tile.src} alt={tile.title} fill sizes={sizes} quality={72} className={`object-cover ${className}`} />;
}

function Explore({ page }: { page: MakePage }) {
  return (
    <div className="mt-10 flex justify-center md:mt-12">
      <Button size="lg" render={<Link href={page.wall.explore.href} />}>
        {page.wall.explore.label}
        <ArrowRight data-icon="inline-end" className="size-4" />
      </Button>
    </div>
  );
}

export function FilmstripWall({ page }: { page: MakePage }) {
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLUListElement>(0.1);
  const strip = useRef<HTMLUListElement | null>(null);
  const nudge = (dir: 1 | -1) => {
    const el = strip.current;
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: still ? "auto" : "smooth" });
  };
  return (
    <section id="examples" className="border-t border-border">
      <div className="mx-auto max-w-[1440px] pb-16 pt-16 md:pb-20 md:pt-24">
        <div className="flex flex-col gap-6 px-4 md:flex-row md:items-end md:justify-between md:px-6">
          <SectionTitle className="md:text-left">{page.wall.title}</SectionTitle>
          <div className="hidden shrink-0 gap-2 md:flex">
            <Button size="icon-lg" variant="outline" aria-label="Scroll back" onClick={() => nudge(-1)}>
              <ArrowLeft className="size-4" />
            </Button>
            <Button size="icon-lg" variant="outline" aria-label="Scroll on" onClick={() => nudge(1)}>
              <ArrowRight className="size-4" />
            </Button>
          </div>
        </div>
        <ul
          ref={(el) => {
            strip.current = el;
            ref.current = el;
          }}
          className="mt-10 flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-px-4 px-4 pb-4 [scrollbar-width:thin] md:mt-14 md:scroll-px-6 md:gap-5 md:px-6"
        >
          {page.wall.tiles.map((tile, i) => (
            <motion.li key={tile.title} {...reveal(i, { still, show, y: 24, duration: 0.55, base: 0.06 })} className="shrink-0 snap-start">
              <figure>
                <div
                  className="group relative h-[340px] overflow-hidden rounded-2xl bg-card md:h-[440px]"
                  style={{ aspectRatio: ratio(tile) }}
                >
                  <Still tile={tile} sizes="(min-width: 768px) 560px, 80vw" className="transition-transform duration-700 ease-out group-hover:scale-[1.04]" />
                </div>
                <figcaption className="mt-3 flex items-baseline justify-between gap-3">
                  <span className="text-[15px] font-semibold tracking-[-0.01em]">{tile.title}</span>
                  {tile.tag && <span className="eyebrow shrink-0">{tile.tag}</span>}
                </figcaption>
                {tile.meta && <p className="mt-1 max-w-[42ch] text-[13px] leading-snug text-[var(--ink-2)]">{tile.meta}</p>}
              </figure>
            </motion.li>
          ))}
        </ul>
        <div className="px-4 md:px-6">
          <Explore page={page} />
        </div>
      </div>
    </section>
  );
}

/** A prompt with its [[must-get-right]] words marked, as React nodes. */
function Marked({ text }: { text: string }) {
  const parts = text.split(/(\[\[[^\]]+\]\])/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("[[") ? (
          <mark key={i} className="rounded-[4px] bg-[color-mix(in_oklab,var(--primary)_14%,transparent)] px-0.5 text-[var(--primary)]">
            {part.slice(2, -2)}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}
const plain = (text: string) => text.replace(/\[\[|\]\]/g, "");

export function PromptsWall({ page }: { page: MakePage }) {
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLUListElement>(0.12);
  return (
    <section id="examples" className="border-t border-border">
      <div className="mx-auto max-w-[1240px] px-4 pb-16 pt-16 md:px-6 md:pb-20 md:pt-24">
        <SectionTitle>{page.wall.title}</SectionTitle>
        <ul ref={ref} className="mt-10 grid gap-x-5 gap-y-10 sm:grid-cols-2 md:mt-14 lg:grid-cols-3">
          {page.wall.tiles.map((tile, i) => (
            <motion.li key={tile.title} {...reveal(i, { still, show, y: 24, duration: 0.55 })}>
              <article className="flex h-full flex-col">
                <div className="relative overflow-hidden rounded-2xl bg-card" style={{ aspectRatio: ratio(tile, "3:4") }}>
                  <Still tile={tile} sizes="(min-width: 1024px) 400px, (min-width: 640px) 50vw, 100vw" />
                  {tile.tag && (
                    <span className="absolute left-3 top-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
                      {tile.tag}
                    </span>
                  )}
                </div>
                <h3 className="mt-4 text-[17px] font-semibold tracking-[-0.01em]">{tile.title}</h3>
                {tile.prompt && (
                  <>
                    <p className="mt-2 flex-1 font-mono text-[12.5px] leading-relaxed text-[var(--ink-2)]">
                      <Marked text={tile.prompt} />
                    </p>
                    <CreateCtaButton variant="link" label="Use this prompt" spark={plain(tile.prompt)} className="mt-4 self-start" />
                  </>
                )}
              </article>
            </motion.li>
          ))}
        </ul>
        <Explore page={page} />
      </div>
    </section>
  );
}

export function EditorialWall({ page }: { page: MakePage }) {
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLDivElement>(0.12);
  const [lead, ...figures] = page.wall.tiles;
  // every third figure runs the full width; a last figure that would sit
  // alone in its row does too, so the column never ends on a hole
  const wide = figures.map((_, i) => i % 3 === 2 || (i === figures.length - 1 && i % 3 === 0));
  if (!lead) return null;
  return (
    <section id="examples" className="border-t border-border">
      <div className="mx-auto max-w-[1240px] px-4 pb-16 pt-16 md:px-6 md:pb-20 md:pt-24">
        <SectionTitle>{page.wall.title}</SectionTitle>
        <div ref={ref} className="mt-10 grid gap-5 md:mt-14 lg:grid-cols-[1.25fr_1fr] lg:gap-8">
          <motion.figure {...reveal(0, { still, show, y: 24, duration: 0.6 })} className="lg:sticky lg:top-24 lg:self-start">
            <div className="relative overflow-hidden rounded-3xl bg-card" style={{ aspectRatio: ratio(lead, "3:4") }}>
              <Still tile={lead} sizes="(min-width: 1024px) 680px, 100vw" />
            </div>
            <figcaption className="mt-4 flex gap-4 border-t border-border pt-4">
              <span className="eyebrow shrink-0 whitespace-nowrap pt-1">Fig. 1</span>
              <span>
                <span className="block text-[17px] font-semibold tracking-[-0.01em]">{lead.title}</span>
                {lead.meta && <span className="mt-1 block text-[14px] leading-relaxed text-[var(--ink-2)]">{lead.meta}</span>}
              </span>
            </figcaption>
          </motion.figure>
          <div className="grid grid-cols-2 gap-x-4 gap-y-8 self-start">
            {figures.map((tile, i) => (
              <motion.figure key={tile.title} {...reveal(i + 1, { still, show, y: 24, duration: 0.55 })} className={wide[i] ? "col-span-2" : ""}>
                <div
                  className="relative overflow-hidden rounded-2xl bg-card"
                  style={{ aspectRatio: wide[i] ? "16 / 9" : ratio(tile, "3:4") }}
                >
                  <Still tile={tile} sizes="(min-width: 1024px) 520px, 50vw" />
                </div>
                <figcaption className="mt-3 flex gap-3">
                  <span className="eyebrow shrink-0 whitespace-nowrap pt-0.5">Fig. {i + 2}</span>
                  <span className="text-[14px] font-semibold leading-snug tracking-[-0.01em]">{tile.title}</span>
                </figcaption>
              </motion.figure>
            ))}
          </div>
        </div>
        <Explore page={page} />
      </div>
    </section>
  );
}

export function PostersWall({ page }: { page: MakePage }) {
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLUListElement>(0.1);
  return (
    <section id="examples" className="border-t border-border bg-[color-mix(in_oklab,var(--primary)_7%,var(--background))]">
      <div className="mx-auto max-w-[1300px] px-4 pb-16 pt-16 md:px-6 md:pb-24 md:pt-24">
        <SectionTitle>{page.wall.title}</SectionTitle>
        <ul ref={ref} className="mt-10 grid grid-cols-2 gap-x-4 gap-y-8 md:mt-16 md:grid-cols-4 md:gap-x-6">
          {page.wall.tiles.map((tile, i) => (
            <motion.li
              key={tile.title}
              {...reveal(i, { still, show, y: 32, duration: 0.6, base: 0.07 })}
              className={i % 2 === 1 ? "md:translate-y-12" : ""}
            >
              <figure className="group">
                <div className="relative aspect-[2/3] overflow-hidden rounded-lg bg-card shadow-[0_18px_40px_-22px_rgba(0,0,0,0.45)] transition-[transform,box-shadow] duration-500 ease-out group-hover:-translate-y-2 group-hover:shadow-[0_30px_60px_-24px_rgba(0,0,0,0.5)] motion-reduce:transition-none motion-reduce:group-hover:translate-y-0">
                  <Still tile={tile} sizes="(min-width: 768px) 300px, 50vw" />
                </div>
                <figcaption className="mt-3">
                  <span className="block text-[14px] font-semibold tracking-[-0.01em]">{tile.title}</span>
                  {tile.tag && <span className="eyebrow mt-1 block">{tile.tag}</span>}
                </figcaption>
              </figure>
            </motion.li>
          ))}
        </ul>
        {/* the odd columns sit 3rem lower, which the grid does not count */}
        <div className="md:mt-24">
          <Explore page={page} />
        </div>
      </div>
    </section>
  );
}

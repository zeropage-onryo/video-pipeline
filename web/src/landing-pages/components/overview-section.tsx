"use client";

import Image from "next/image";
import { motion } from "motion/react";
import { reveal } from "@/lib/motion";
import { useRevealGroup, useStill } from "@/lib/motion-hooks";
import type { MakeOverviewBlock, MakePage } from "../pages";

// The overview (2026-10-07, Mike's call): the shape of ByteDance's own
// Seedance 2.5 page -- a run of headline claims, each one line of serif,
// a sentence or two, and a demo beside it -- carried on the entry as
// `overview.items` so any model page can have one. The text and the media
// alternate sides; the media slot is a wall tile (a plate until a real
// still or clip lands, `src`/`video` when one does). Blocks rise in with a
// stagger off ONE observer on the section (lib/motion's rule); nothing
// moves under reduced motion. A page with no `overview` draws nothing.

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
  const media = block.media;
  const plate = media?.plate ?? PLATES[index % PLATES.length];
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
      <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl bg-card md:aspect-[5/4]">
        {media?.video ? (
          <video
            className="absolute inset-0 size-full object-cover"
            src={media.video}
            poster={media.src}
            autoPlay={!still}
            muted
            loop
            playsInline
          />
        ) : media?.src ? (
          <Image src={media.src} alt={media.title || block.title} fill sizes="(min-width: 768px) 50vw, 100vw" quality={70} className="object-cover" />
        ) : (
          <div aria-hidden className="absolute inset-0" style={{ background: plate }} />
        )}
        {media?.tag && (
          <span className="absolute bottom-3 left-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
            {media.tag}
          </span>
        )}
      </div>
    </motion.div>
  );
}

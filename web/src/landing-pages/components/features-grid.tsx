"use client";

import { type PointerEvent } from "react";
import { motion, useMotionTemplate, useMotionValue, useSpring } from "motion/react";
import {
  Clapperboard,
  Download,
  Frame,
  Images,
  LayoutGrid,
  Layers,
  MessageSquareText,
  Monitor,
  Package,
  Receipt,
  Timer,
  Type,
  Unlock,
  Volume2,
  Wand2,
  type LucideIcon,
} from "lucide-react";
import { HOVER, SPRINGS, reveal } from "@/lib/motion";
import { useRevealGroup, useStill } from "@/lib/motion-hooks";
import type { FeatureIcon, MakeFeature } from "../pages";

// Nine cards in a 3x3 (one column on a phone, two on a tablet). The
// interaction, all on Motion and all off under reduced motion:
//
// - they rise in with a stagger once the grid is a fifth on screen (one
//   observer for the nine, the wall's rule);
// - a card lifts on hover and a soft light follows the pointer across its
//   face (two motion values driving a radial gradient, no re-render; the
//   light's colour is the page's accent, `--card-light`);
// - the glyph nudges up and the number fades, so the eye lands on the title.
const ICONS: Record<FeatureIcon, LucideIcon> = {
  references: Images,
  elements: Package,
  shots: Clapperboard,
  keyframe: Frame,
  price: Receipt,
  model: Layers,
  export: Download,
  guide: MessageSquareText,
  assets: LayoutGrid,
  frame: Monitor,
  sound: Volume2,
  clock: Timer,
  open: Unlock,
  type: Type,
  edit: Wand2,
};

export function FeaturesGrid({ items }: { items: MakeFeature[] }) {
  const still = useStill();
  const { ref: grid, show } = useRevealGroup<HTMLUListElement>(0.15);
  return (
    <ul ref={grid} className="mt-10 grid gap-3 sm:grid-cols-2 md:mt-14 lg:grid-cols-3 lg:gap-4">
      {items.map((item, i) => (
        <Card key={item.title} item={item} index={i} show={show} still={still} />
      ))}
    </ul>
  );
}

function Card({ item, index, show, still }: { item: MakeFeature; index: number; show: boolean; still: boolean }) {
  const Icon = ICONS[item.icon];
  const mx = useMotionValue(50);
  const my = useMotionValue(50);
  const sx = useSpring(mx, SPRINGS.glow);
  const sy = useSpring(my, SPRINGS.glow);
  const light = useMotionTemplate`radial-gradient(260px circle at ${sx}% ${sy}%, var(--card-light), transparent 65%)`;

  const onMove = (e: PointerEvent<HTMLElement>) => {
    if (still || e.pointerType === "touch") return;
    const r = e.currentTarget.getBoundingClientRect();
    mx.set(((e.clientX - r.left) / r.width) * 100);
    my.set(((e.clientY - r.top) / r.height) * 100);
  };

  return (
    <motion.li {...reveal(index, { still, show })} className="h-full">
      <motion.article
        onPointerMove={onMove}
        whileHover={still ? undefined : "hover"}
        initial="rest"
        animate="rest"
        variants={HOVER.card}
        transition={SPRINGS.lift}
        className="group relative flex h-full min-h-[220px] flex-col overflow-hidden rounded-2xl border border-[var(--card-line)] bg-background p-6 transition-colors duration-300 hover:border-[var(--line-hover)]"
      >
        <motion.div aria-hidden style={{ background: light }} className="pointer-events-none absolute inset-0" />
        <div className="relative flex items-start justify-between">
          <motion.span
            variants={HOVER.glyph}
            transition={SPRINGS.nudge}
            className="inline-flex size-11 items-center justify-center rounded-xl bg-foreground text-background"
          >
            <Icon className="size-5" strokeWidth={1.75} />
          </motion.span>
          <motion.span variants={HOVER.dim} className="eyebrow pt-1">
            {String(index + 1).padStart(2, "0")}
          </motion.span>
        </div>
        <h3 className="relative mt-8 text-[20px] font-bold leading-tight tracking-[-0.015em]">{item.title}</h3>
        <p className="relative mt-3 text-[14.5px] leading-relaxed text-[var(--ink-2)]">{item.body}</p>
      </motion.article>
    </motion.li>
  );
}

// Two more shapes (2026-10-08, so the nine are not drawn the same way on
// every page): a hairline list in two columns, numbered, the glyph inline;
// and rows under a title pinned to the left (features-section.tsx).
export function FeaturesList({ items }: { items: MakeFeature[] }) {
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLOListElement>(0.12);
  return (
    <ol ref={ref} className="mt-10 grid gap-x-12 border-t border-[var(--card-line)] md:mt-14 md:grid-cols-2">
      {items.map((item, i) => {
        const Icon = ICONS[item.icon];
        return (
          <motion.li
            key={item.title}
            {...reveal(i, { still, show, y: 16, duration: 0.5 })}
            className="group grid grid-cols-[auto_1fr] gap-x-5 border-b border-[var(--card-line)] py-7"
          >
            <span className="flex flex-col items-center gap-3">
              <span className="eyebrow">{String(i + 1).padStart(2, "0")}</span>
              <Icon className="size-5 text-[var(--primary)] transition-transform duration-300 group-hover:-translate-y-0.5" strokeWidth={1.75} />
            </span>
            <span>
              <h3 className="text-[19px] font-bold leading-tight tracking-[-0.015em]">{item.title}</h3>
              <p className="mt-2 text-[14.5px] leading-relaxed text-[var(--ink-2)]">{item.body}</p>
            </span>
          </motion.li>
        );
      })}
    </ol>
  );
}

export function FeaturesRows({ items }: { items: MakeFeature[] }) {
  const still = useStill();
  const { ref, show } = useRevealGroup<HTMLUListElement>(0.1);
  return (
    <ul ref={ref} className="flex flex-col">
      {items.map((item, i) => {
        const Icon = ICONS[item.icon];
        return (
          <motion.li
            key={item.title}
            {...reveal(i, { still, show, y: 14, duration: 0.5, base: 0.03 })}
            className="group flex gap-5 border-t border-border py-6 first:border-t-0 first:pt-0"
          >
            <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-[var(--card-line)] transition-colors duration-300 group-hover:border-[var(--line-hover)] group-hover:bg-[var(--primary)] group-hover:text-[var(--primary-foreground)]">
              <Icon className="size-[18px]" strokeWidth={1.75} />
            </span>
            <span>
              <h3 className="text-[18px] font-bold leading-tight tracking-[-0.015em]">{item.title}</h3>
              <p className="mt-1.5 max-w-[60ch] text-[14.5px] leading-relaxed text-[var(--ink-2)]">{item.body}</p>
            </span>
          </motion.li>
        );
      })}
    </ul>
  );
}

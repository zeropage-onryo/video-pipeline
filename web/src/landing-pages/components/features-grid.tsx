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

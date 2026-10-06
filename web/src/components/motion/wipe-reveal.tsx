"use client";

import { motion, type Variants } from "motion/react";
import { useStill } from "@/components/motion/use-still";
import type { ReactNode } from "react";

// The masked wipe: the block is uncovered from one edge like a shutter
// opening, while the content inside settles from a slight over-scale. It
// is what the feature screenshots arrive with -- a hard-edged cinematic
// reveal next to Reveal's soft rise.
//
// clip-path, not a sliding cover element: nothing extra is painted and the
// layout box never changes. The in-view trigger is the unclipped OUTER
// box; the clipped inner one only listens (see kinetic-text.tsx for why a
// clipped element must not watch for itself).
const FROM = {
  up: "inset(100% 0% 0% 0%)",
  down: "inset(0% 0% 100% 0%)",
  left: "inset(0% 0% 0% 100%)",
  right: "inset(0% 100% 0% 0%)",
} as const;

export function WipeReveal({
  children,
  className,
  direction = "up",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  direction?: keyof typeof FROM;
  delay?: number;
}) {
  const still = useStill();
  if (still) return <div className={className}>{children}</div>;

  const shutter: Variants = {
    hidden: { clipPath: FROM[direction] },
    show: { clipPath: "inset(0% 0% 0% 0%)", transition: { duration: 1.1, ease: [0.77, 0, 0.18, 1], delay } },
  };
  const settle: Variants = {
    hidden: { scale: 1.12 },
    show: { scale: 1, transition: { duration: 1.6, ease: [0.16, 1, 0.3, 1], delay } },
  };

  return (
    <motion.div className={className} initial="hidden" whileInView="show" viewport={{ once: true, amount: 0.3 }}>
      <motion.div variants={shutter}>
        <motion.div variants={settle}>{children}</motion.div>
      </motion.div>
    </motion.div>
  );
}

"use client";

import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

// A section that arrives as you reach it. `once` is deliberate: content
// that re-animates every time it scrolls back into view reads as a page
// that will not settle, which is worse than no motion at all.
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ duration: 0.6, ease: [0.22, 0.61, 0.36, 1], delay }}
    >
      {children}
    </motion.div>
  );
}

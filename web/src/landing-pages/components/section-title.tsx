"use client";

import { motion, useReducedMotion } from "motion/react";

// Every section's headline on a /make page: the reference's one line of
// heavy condensed uppercase, centered, rising in as it reaches the view.
export function SectionTitle({
  children,
  as: Tag = "h2",
  className = "",
  light = false,
}: {
  children: string;
  as?: "h2" | "h3";
  className?: string;
  /** White, for a dark plate. */
  light?: boolean;
}) {
  const still = useReducedMotion();
  const M = Tag === "h2" ? motion.h2 : motion.h3;
  return (
    <M
      initial={still ? false : { opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.5 }}
      transition={{ duration: 0.6, ease: [0.22, 0.61, 0.36, 1] }}
      className={`display text-center text-[clamp(2.25rem,6.4vw,5rem)] ${light ? "text-white" : "text-foreground"} ${className}`}
    >
      {children}
    </M>
  );
}

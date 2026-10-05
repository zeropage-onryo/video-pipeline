"use client";

import { motion } from "motion/react";
import { inViewReveal } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";

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
  const still = useStill();
  const M = Tag === "h2" ? motion.h2 : motion.h3;
  return (
    <M
      {...inViewReveal(still)}
      className={`display text-center text-[clamp(2.25rem,6.4vw,5rem)] ${light ? "text-white" : "text-foreground"} ${className}`}
    >
      {children}
    </M>
  );
}

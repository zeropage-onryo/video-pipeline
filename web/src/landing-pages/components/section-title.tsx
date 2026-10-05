"use client";

import { motion } from "motion/react";
import { EASE_OUT, RISE } from "@/lib/motion";
import { useRevealBelowFold, useStill } from "@/lib/motion-hooks";

// Every section's headline on a /make page: the reference's one line of
// heavy condensed uppercase, centered, rising in as it reaches the view.
// It is in the server HTML visible, and only a title below the fold at
// load gets the entrance (useRevealBelowFold): the first title on screen
// was the page's LCP, and it waited on hydration to fade in.
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
  const { ref, shown, instant } = useRevealBelowFold<HTMLHeadingElement>(still);
  const M = Tag === "h2" ? motion.h2 : motion.h3;
  return (
    <M
      ref={ref}
      initial={false}
      animate={shown ? RISE.shown : RISE.hidden}
      transition={instant ? { duration: 0 } : { duration: 0.6, ease: EASE_OUT }}
      className={`display text-center text-[clamp(2.25rem,6.4vw,5rem)] ${light ? "text-white" : "text-foreground"} ${className}`}
    >
      {children}
    </M>
  );
}

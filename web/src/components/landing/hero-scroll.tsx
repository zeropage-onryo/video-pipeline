"use client";

import { motion, useScroll, useSpring, useTransform } from "motion/react";
import { useStill } from "@/components/motion/use-still";
import { useRef, type ReactNode } from "react";

// Two scroll-linked layers for the hero, both driven by the scroll
// position itself (not a timer), so they run backwards when you scroll
// back up and never get ahead of the reader.
//
// HeroCopy: the headline block drifts up and dims as the page leaves it --
// a slower layer than the scroll, which is what reads as depth.
// HeroPlate: the product frame starts tipped back in perspective and
// slightly small, and lands flat and full-size as it reaches the middle
// of the screen, like a screen being raised to face you.
export function HeroCopy({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const still = useStill();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const y = useTransform(scrollYProgress, [0, 1], [0, -140]);
  const opacity = useTransform(scrollYProgress, [0, 0.8], [1, 0]);
  const blur = useTransform(scrollYProgress, [0.2, 0.9], ["blur(0px)", "blur(6px)"]);

  return (
    <motion.div ref={ref} className={className} style={still ? undefined : { y, opacity, filter: blur }}>
      {children}
    </motion.div>
  );
}

export function HeroPlate({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const still = useStill();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "center center"] });
  const smooth = useSpring(scrollYProgress, { stiffness: 140, damping: 28, mass: 0.4 });
  const rotateX = useTransform(smooth, [0, 1], [28, 0]);
  const scale = useTransform(smooth, [0, 1], [0.86, 1]);
  const y = useTransform(smooth, [0, 1], [60, 0]);

  return (
    <div ref={ref} className="relative [perspective:1600px]">
      <motion.div
        className="origin-top will-change-transform"
        style={still ? undefined : { rotateX, scale, y }}
        initial={still ? undefined : { opacity: 0 }}
        animate={still ? undefined : { opacity: 1 }}
        transition={{ duration: 1, delay: 1.1 }}
      >
        {children}
      </motion.div>
    </div>
  );
}

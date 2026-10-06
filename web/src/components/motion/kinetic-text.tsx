"use client";

import { motion, type Variants } from "motion/react";
import { useStill } from "@/components/motion/use-still";

// Kinetic type, the cinematic title-card move (2026-10-06, Mike's call:
// "bold cinematic"). Every word sits in its own overflow-hidden slot and
// rises out of it from below with a slight roll, one after the other, so a
// headline arrives the way an opening title does rather than fading in.
//
// The text stays ONE string in the accessible name: the words are
// aria-hidden spans and the full sentence rides on aria-label, so a screen
// reader hears the heading once, not word by word.
//
// The in-view trigger sits on the HEADING, never on the words: a word
// parked below its mask is fully clipped, and an IntersectionObserver
// counts ancestor clipping, so a word watching for itself never fires.
// The heading owns the trigger and hands it down through variants.
//
// `trigger="mount"` plays on load (the hero); "view" plays the first time
// the heading scrolls into view, once -- a title that re-runs every time
// you scroll back past it reads as a page that will not settle.
type Props = {
  text: string;
  as?: "h1" | "h2" | "h3" | "p";
  className?: string;
  delay?: number;
  stagger?: number;
  trigger?: "mount" | "view";
};

const EASE = [0.16, 1, 0.3, 1] as const;

const WORD: Variants = {
  hidden: { y: "110%", rotate: 6, opacity: 0 },
  show: { y: "0%", rotate: 0, opacity: 1, transition: { duration: 0.9, ease: EASE } },
};

export function KineticText({
  text,
  as = "h2",
  className,
  delay = 0,
  stagger = 0.06,
  trigger = "view",
}: Props) {
  const still = useStill();
  if (still) {
    const Tag = as;
    return <Tag className={className}>{text}</Tag>;
  }

  const Tag = motion[as];
  const words = text.split(" ");
  const play =
    trigger === "mount"
      ? { animate: "show" }
      : { whileInView: "show", viewport: { once: true, amount: 0.5 } };

  return (
    <Tag
      className={className}
      aria-label={text}
      initial="hidden"
      {...play}
      variants={{ hidden: {}, show: { transition: { delayChildren: delay, staggerChildren: stagger } } }}
    >
      {words.map((word, i) => (
        <span
          key={`${word}-${i}`}
          aria-hidden
          // pb/-mb keep descenders (g, y, p) inside the mask
          className="inline-block overflow-hidden pb-[0.12em] -mb-[0.12em] align-bottom"
        >
          <motion.span className="inline-block origin-bottom-left will-change-transform" variants={WORD}>
            {word}
          </motion.span>
          {i < words.length - 1 ? " " : null}
        </span>
      ))}
    </Tag>
  );
}

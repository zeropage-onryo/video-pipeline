// The public site's motion, in one place (2026-10-05): the easing every
// reveal shares, the three springs the landing pages use, the stagger and
// the in-view hooks. The /make sections and the homepage's Reveal read
// from here; nothing under /studio does (its own motion lives beside it).
//
// Two rules the helpers enforce so a new section cannot forget them:
//
// - Reduced motion renders the finished state and animates nothing.
//   `useStill()` is the one switch; `reveal()` takes it and returns
//   `initial: false` (no entrance) when it is on.
// - A GROUP reveals on ONE observer (`useRevealGroup`), never a per-child
//   whileInView: a per-tile observer left three wall tiles stuck invisible
//   in a short viewport (2026-10-01).
//
// Only `transform` and `opacity` are animated by what is here. BlurFade
// (components/ui) animates `filter` as well, and is used knowingly.
//
// This file is PURE (no React, type imports only) so a server component
// can read a constant from it; the two hooks (`useStill`,
// `useRevealGroup`) live in motion-hooks.ts, which only client components
// import. Next refuses a hook import in a server module.
import type { Transition, Variants } from "motion/react";

/** The site's one ease-out: fast start, long settle. */
export const EASE_OUT = [0.22, 0.61, 0.36, 1] as const;

/** Springs, named by what they do rather than where they are. */
export const SPRINGS = {
  /** A tilt that settles instead of snapping (the wall tiles). */
  settle: { stiffness: 220, damping: 20, mass: 0.6 },
  /** A card lifting on hover. */
  lift: { type: "spring", stiffness: 320, damping: 26 } as const,
  /** A glyph nudging on hover. */
  nudge: { type: "spring", stiffness: 300, damping: 18 } as const,
  /** A light following the pointer (two motion values, no re-render). */
  glow: { stiffness: 300, damping: 30 },
} as const;

/** Seconds between one staggered child and the next. */
export const STAGGER = 0.06;

/** Delay for the i-th child of a staggered group. */
export const stagger = (i: number, base = 0.05, step = STAGGER) => base + i * step;

/** The CSS entrance the hero's own lines use (tw-animate-css, motion-safe). */
export const REVEAL_CLASS =
  "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-4 motion-safe:fill-mode-both";

export type RevealOptions = {
  /** `useStill()` (motion-hooks.ts): no entrance at all. */
  still: boolean;
  /** The group's `show`. */
  show: boolean;
  /** Rise distance in px. */
  y?: number;
  /** Starting scale, when the entrance also grows. */
  scale?: number;
  duration?: number;
  /** The first child's delay. */
  base?: number;
  step?: number;
};

/**
 * The `initial` / `animate` / `transition` for the i-th child of a group:
 * fade + rise (+ grow), staggered, off entirely under reduced motion.
 */
export function reveal(i: number, opts: RevealOptions) {
  const { still, show, y = 24, scale, duration = 0.55, base = 0.05, step = STAGGER } = opts;
  const hidden = { opacity: 0, y, ...(scale !== undefined ? { scale } : {}) };
  const shown = { opacity: 1, y: 0, ...(scale !== undefined ? { scale: 1 } : {}) };
  const transition: Transition = { duration, ease: EASE_OUT, delay: stagger(i, base, step) };
  return {
    initial: still ? (false as const) : hidden,
    animate: still || show ? shown : undefined,
    transition,
  };
}

/** The in-view entrance's hidden and shown states (section titles). */
export const RISE = { hidden: { opacity: 0, y: 20 }, shown: { opacity: 1, y: 0 } } as const;

/** Rest / hover variants for a card and the pieces inside it. */
export const HOVER: Record<"card" | "glyph" | "dim", Variants> = {
  card: { rest: { y: 0 }, hover: { y: -6 } },
  glyph: { rest: { y: 0, rotate: 0 }, hover: { y: -3, rotate: -4 } },
  dim: { rest: { opacity: 1 }, hover: { opacity: 0.35 } },
};

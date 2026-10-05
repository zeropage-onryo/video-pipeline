// The hooks half of lib/motion.ts (see the note there): client components
// only. `useStill` is the one reduced-motion switch; `useRevealGroup` is
// the one observer a staggered group shares.
import { useRef, type RefObject } from "react";
import { useInView, useReducedMotion } from "motion/react";

/** Is the person asking for reduced motion? Boolean, never null. */
export function useStill(): boolean {
  return !!useReducedMotion();
}

/**
 * One observer for a whole group: `ref` goes on the container, `show`
 * flips once when `amount` of it is on screen, and every child's entrance
 * keys off it.
 */
export function useRevealGroup<T extends Element = HTMLElement>(
  amount = 0.15,
): { ref: RefObject<T | null>; show: boolean } {
  const ref = useRef<T>(null);
  const show = useInView(ref, { once: true, amount });
  return { ref, show };
}

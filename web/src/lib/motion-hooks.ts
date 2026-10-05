// The hooks half of lib/motion.ts (see the note there): client components
// only. `useStill` is the one reduced-motion switch; `useRevealGroup` is
// the one observer a staggered group shares.
import { useEffect, useRef, useState, type RefObject } from "react";
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

/**
 * An entrance that never delays the first paint (2026-10-05, Lighthouse):
 * the element renders VISIBLE in the server HTML, and only when it mounts
 * below the fold is it hidden (instantly, off screen) and revealed on
 * reaching the view. A title already on screen at load simply shows,
 * because a title that waits on hydration to fade in is the page's LCP
 * waiting on every script.
 */
export function useRevealBelowFold<T extends Element = HTMLElement>(
  still: boolean,
  amount = 0.5,
): { ref: RefObject<T | null>; shown: boolean; instant: boolean } {
  const ref = useRef<T>(null);
  const [below, setBelow] = useState(false);
  const inView = useInView(ref, { once: true, amount });
  useEffect(() => {
    const el = ref.current;
    if (!el || still) return;
    if (el.getBoundingClientRect().top > window.innerHeight) setBelow(true);
  }, [still]);
  const shown = still || !below || inView;
  // the one move to the hidden state (below the fold, unseen) is instant
  return { ref, shown, instant: !shown };
}

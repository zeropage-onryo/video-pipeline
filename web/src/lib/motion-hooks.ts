// The hooks half of lib/motion.ts (see the note there): client components
// only. `useStill` is the one reduced-motion switch; `useRevealGroup` is
// the one observer a staggered group shares.
import { useEffect, useRef, useState, type RefObject } from "react";
import { useInView } from "motion/react";

/** Is the person asking for reduced motion? Boolean, never null. The
 *  landing page's hydration-safe reading (components/motion/use-still.ts,
 *  2026-10-06): false on the first client render, like the server, then the
 *  real setting -- answering "reduce" straight away draws a different tree
 *  from the server's and React throws a hydration mismatch. */
export { useStill } from "@/components/motion/use-still";

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

/**
 * Has the element come within `margin` of the viewport yet (once, then it
 * stays true)? For media that should not load until it is about to be
 * seen (2026-10-08, Lighthouse): a <video poster> is fetched the moment it
 * is in the DOM, and thirteen of them on one page were all requested
 * before the first paint, which is what slow-4G LCP is computed from.
 * `eager` starts true, for a clip at the top of the page.
 */
export function useNearView<T extends Element = HTMLElement>(
  ref: RefObject<T | null>,
  { margin = "100% 0px", eager = false }: { margin?: string; eager?: boolean } = {},
): boolean {
  const [near, setNear] = useState(eager);
  useEffect(() => {
    if (near) return;
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setNear(true);
          io.disconnect();
        }
      },
      { rootMargin: margin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref, margin, near]);
  return near;
}

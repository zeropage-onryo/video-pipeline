"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

// The opening: two letterbox bars cover the top and bottom of the screen
// on load and pull away, a hairline of signal red riding each inner edge,
// so the page opens like a frame rather than appearing. Then they unmount
// -- nothing is left sitting over the page or intercepting a click.
//
// Once per tab session (sessionStorage), because a curtain that drops
// every time someone comes back from /pricing is a delay, not a moment.
// Reduced motion never sees it.
const KEY = "zp-letterbox-seen";

export function HeroLetterbox() {
  const still = useReducedMotion();
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (still) return;
    let seen = false;
    try {
      seen = sessionStorage.getItem(KEY) === "1";
      sessionStorage.setItem(KEY, "1");
    } catch {
      // storage blocked (private mode): play it, it is only once per load
    }
    if (seen) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot on mount, decided by storage the server cannot read
    setShow(true);
    const id = setTimeout(() => setShow(false), 1500);
    return () => clearTimeout(id);
  }, [still]);

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          key="letterbox"
          aria-hidden
          className="pointer-events-none fixed inset-0 z-[60]"
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {(["top", "bottom"] as const).map((edge) => (
            <motion.div
              key={edge}
              className={`letterbox-bar absolute inset-x-0 h-[50vh] ${edge === "top" ? "top-0 origin-top" : "bottom-0 origin-bottom"}`}
              initial={{ scaleY: 1 }}
              animate={{ scaleY: 0 }}
              transition={{ duration: 1.15, ease: [0.83, 0, 0.17, 1], delay: 0.15 }}
            >
              <span
                className={`absolute inset-x-0 h-px bg-[var(--signal)] shadow-[0_0_18px_2px_var(--signal)] ${edge === "top" ? "bottom-0" : "top-0"}`}
              />
            </motion.div>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

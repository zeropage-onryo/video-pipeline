"use client";

import { useReducedMotion } from "motion/react";
import { useSyncExternalStore } from "react";

// Reduced motion, read only once the page has hydrated. The server cannot
// know the viewer's setting, so it renders the animated tree; if the
// first client render answered "reduce" straight away it would draw a
// DIFFERENT tree (plain text instead of masked words, cards instead of the
// pinned sequence) and React would throw a hydration mismatch. So the
// first client render agrees with the server and the switch to the still
// version happens right after.
const noop = () => () => {};

export function useStill(): boolean {
  const reduce = useReducedMotion();
  const hydrated = useSyncExternalStore(noop, () => true, () => false);
  return hydrated && Boolean(reduce);
}

"use client";

import { useEffect, useState, type RefObject } from "react";

// The largest w x h of a given ratio that fits inside `ref`'s box
// (2026-10-05). A frame sized by `aspect-ratio` alone has no intrinsic
// size inside a fixed-height flex container and collapses to nothing, so
// the frame pickers measure the container and set explicit pixels, which
// also gives the layout animation two real numbers to tween between.
export function useFit(ref: RefObject<HTMLElement | null>, ratio: number): { width: number; height: number } {
  const [box, setBox] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const W = el.clientWidth;
      const H = el.clientHeight;
      if (!W || !H) return;
      const width = Math.min(W, H * ratio);
      setBox({ width: Math.round(width), height: Math.round(width / ratio) });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, ratio]);
  return box;
}

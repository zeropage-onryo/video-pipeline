"use client";

import { useEffect, useRef } from "react";

// The hairline grid brightens under the pointer. invideo runs the same
// layer as a timed diagonal sweep; pointer-driven is the honest version of
// it here -- the page answers the person rather than performing at them.
//
// Positions are written as CSS custom properties on the element rather
// than through state: a pointermove that re-renders React at 120Hz is a
// stutter, and nothing else on the page needs to know where the mouse is.
export function HeroSpotlight() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const layer = ref.current;
    const section = layer?.parentElement;
    if (!layer || !section) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const move = (event: PointerEvent) => {
      const box = section.getBoundingClientRect();
      layer.style.setProperty("--x", `${event.clientX - box.left}px`);
      layer.style.setProperty("--y", `${event.clientY - box.top}px`);
      layer.style.opacity = "1";
    };
    const leave = () => {
      layer.style.opacity = "0";
    };

    section.addEventListener("pointermove", move);
    section.addEventListener("pointerleave", leave);
    return () => {
      section.removeEventListener("pointermove", move);
      section.removeEventListener("pointerleave", leave);
    };
  }, []);

  return (
    <div
      ref={ref}
      aria-hidden
      className="hero-spot pointer-events-none absolute inset-0 z-0 opacity-0 transition-opacity duration-500"
    />
  );
}

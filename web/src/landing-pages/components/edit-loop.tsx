"use client";

import { useRef, type PointerEvent } from "react";
import { motion, useMotionTemplate, useMotionValue, useSpring, useTransform } from "motion/react";
import { SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import type { MakePage } from "../pages";

// The Seedream page's signature (2026-10-05): generate, then edit in the
// same model. One frame, two plates -- the draw and the edit -- and a
// divider that follows the pointer (or a drag on a phone). The reveal is
// transform-only: the "after" layer slides in a clipped wrapper and its
// picture slides back by the same amount, so nothing repaints but the
// compositor. Two buttons jump the divider for the keyboard. Reduced
// motion: the divider still follows, without the spring.
//
// TODO(media): the two plates are the wall's first two tiles; a real
// before/after pair from the studio goes in as their `src`.

export function EditLoop({ page }: { page: MakePage }) {
  const still = useStill();
  const ref = useRef<HTMLDivElement>(null);
  const raw = useMotionValue(0.5);
  const x = useSpring(raw, still ? { stiffness: 1000, damping: 100 } : SPRINGS.glow);
  // the wrapper reveals from the right: it moves right by (1 - x) of the
  // width and its content moves left by the same, so the picture stays put
  const wrap = useMotionTemplate`translateX(${useTransformPct(x, 1)})`;
  const inner = useMotionTemplate`translateX(${useTransformPct(x, -1)})`;
  const handle = useMotionTemplate`translateX(${useTransformPct(x, 1)})`;

  const set = (clientX: number) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    raw.set(Math.min(1, Math.max(0, (clientX - r.left) / r.width)));
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === "touch" && e.buttons === 0) return;
    set(e.clientX);
  };
  const [before, after] = page.wall.tiles;

  return (
    <section id="edit" className="border-t border-border">
      <div className="mx-auto max-w-[1100px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Generate, then edit</span>
          <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">The draw and the edit, one model.</h2>
        </div>

        <div
          ref={ref}
          onPointerMove={onMove}
          onPointerDown={(e) => set(e.clientX)}
          className="relative mx-auto mt-10 aspect-[3/2] w-full max-w-[860px] touch-pan-y overflow-hidden rounded-2xl bg-card select-none"
        >
          {/* before */}
          <div aria-hidden className="absolute inset-0" style={{ background: before?.plate ?? "var(--plate-1)" }} />
          <span className="absolute top-3 left-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
            The draw · TODO still
          </span>
          {/* after, revealed from the right */}
          <motion.div aria-hidden style={{ transform: wrap }} className="absolute inset-0 overflow-hidden will-change-transform">
            <motion.div style={{ transform: inner, background: after?.plate ?? "var(--plate-2)" }} className="absolute inset-0 will-change-transform" />
            <motion.span style={{ transform: inner }} className="absolute top-3 right-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
              The edit · TODO still
            </motion.span>
          </motion.div>
          {/* the divider */}
          <motion.div aria-hidden style={{ transform: handle }} className="pointer-events-none absolute inset-y-0 left-0 w-full will-change-transform">
            <div className="absolute inset-y-0 left-0 w-0.5 bg-white/90" />
            <div className="absolute top-1/2 left-0 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary px-2.5 py-1 text-[11px] font-semibold text-primary-foreground shadow-[var(--card-shadow)]">
              drag
            </div>
          </motion.div>
        </div>

        <div className="mt-5 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => raw.set(0.08)}
            className="rounded-full border border-[var(--card-line)] px-3 py-1.5 text-[13px] font-medium text-foreground outline-none transition-colors hover:border-[var(--line-hover)] focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Show the edit
          </button>
          <button
            type="button"
            onClick={() => raw.set(0.92)}
            className="rounded-full border border-[var(--card-line)] px-3 py-1.5 text-[13px] font-medium text-foreground outline-none transition-colors hover:border-[var(--line-hover)] focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Show the draw
          </button>
        </div>
        <p className="mx-auto mt-4 max-w-[52ch] text-center text-[15px] text-[var(--ink-2)]">
          Send a still back with a new line and your photos, and Seedream edits it rather than drawing again. Each pass
          lands on the wall as its own still.
        </p>
      </div>
    </section>
  );
}

// x in [0,1] -> "NN%" of the wrapper's travel, in one direction
function useTransformPct(x: ReturnType<typeof useSpring>, sign: 1 | -1) {
  const n = useTransform(x, (v) => sign * (v * 100));
  return useMotionTemplate`${n}%`;
}

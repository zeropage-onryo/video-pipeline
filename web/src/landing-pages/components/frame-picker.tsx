"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE_OUT, SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import { IMAGE_FRAMES } from "../shared";
import { useFit } from "./use-fit";
import type { MakePage } from "../pages";

// The FLUX page's signature (2026-10-05): the ten frames the composer
// draws at. Pick one and the frame morphs to it (a layout animation on its
// aspect ratio), the pixel size swaps underneath, and the pill slides
// along the row. The sizes are src/fal.py IMAGE_SIZES, sent to the model
// as exact width and height. Reduced motion: the morph is instant.

export function FramePicker({ page }: { page: MakePage }) {
  const still = useStill();
  const [i, setI] = useState(1);
  const f = IMAGE_FRAMES[i];
  const stage = useRef<HTMLDivElement>(null);
  const box = useFit(stage, f.w / f.h);
  const t = still ? { duration: 0 } : SPRINGS.lift;
  const plate = page.wall.tiles[i % page.wall.tiles.length]?.plate ?? "var(--plate-1)";

  return (
    <section id="frames" className="border-t border-border">
      <div className="mx-auto max-w-[1100px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Ten frames, exact pixels</span>
          <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">Pick the frame. The model gets the size.</h2>
        </div>

        <div role="radiogroup" aria-label="Frame" className="mx-auto mt-8 flex max-w-[720px] flex-wrap justify-center gap-1.5">
          {IMAGE_FRAMES.map((fr, k) => (
            <button
              key={fr.ratio}
              type="button"
              role="radio"
              aria-checked={k === i}
              onClick={() => setI(k)}
              className="relative rounded-full px-3 py-1.5 text-[13px] font-medium text-foreground outline-none transition-colors hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {k === i && (
                <motion.span
                  layoutId={still ? undefined : "frame-pill"}
                  transition={t}
                  aria-hidden
                  className="absolute inset-0 rounded-full bg-primary"
                />
              )}
              <span className={`relative ${k === i ? "text-primary-foreground" : ""}`}>{fr.ratio}</span>
            </button>
          ))}
        </div>

        <div ref={stage} className="mx-auto mt-8 flex h-[clamp(240px,46svh,460px)] items-center justify-center">
          <motion.div
            layout={!still}
            transition={still ? { duration: 0 } : { type: "spring", stiffness: 260, damping: 28 }}
            style={{ width: box.width || undefined, height: box.height || undefined }}
            className="relative overflow-hidden rounded-2xl bg-card shadow-[var(--card-shadow)]"
          >
            <div aria-hidden className="absolute inset-0" style={{ background: plate }} />
            <span className="absolute top-3 left-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
              TODO still
            </span>
            {/* a square inside the frame as a constant yardstick, so the ratio change reads */}
            <div aria-hidden className="absolute bottom-3 right-3 size-8 rounded-md border border-white/70" />
          </motion.div>
        </div>

        <div aria-live="polite" className="mt-5 text-center">
          <AnimatePresence mode="wait" initial={false}>
            <motion.p
              key={f.ratio}
              initial={still ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={still ? undefined : { opacity: 0, y: -6 }}
              transition={{ duration: 0.22, ease: EASE_OUT }}
              className="text-[15px] text-[var(--ink-2)]"
            >
              <span className="font-semibold text-foreground">{f.ratio}</span> is sent as {f.w} by {f.h} pixels,{" "}
              {((f.w * f.h) / 1_000_000).toFixed(2)} megapixels.
            </motion.p>
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

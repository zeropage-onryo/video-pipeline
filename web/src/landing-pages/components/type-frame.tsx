"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE_OUT, SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import { useFit } from "./use-fit";
import type { MakePage } from "../pages";

// The GPT Image page's signature (2026-10-05): the words in the picture.
// A frame at one of the model's three named sizes (square, portrait,
// landscape -- a pill that slides, and the frame that morphs) with a
// headline that sets itself letter by letter, each letter a staggered
// entrance on transform and opacity, then the next line. Tap the frame
// to set it again. Reduced motion: the line is just there.

const SIZES = [
  { key: "square", label: "Square", w: 1024, h: 1024 },
  { key: "portrait", label: "Portrait", w: 1024, h: 1536 },
  { key: "landscape", label: "Landscape", w: 1536, h: 1024 },
] as const;
const LINES = ["OPEN LATE", "FRESH DAILY", "SOLD OUT", "ONE NIGHT ONLY"];

export function TypeFrame({ page }: { page: MakePage }) {
  const still = useStill();
  const [size, setSize] = useState(0);
  const [line, setLine] = useState(0);
  const [take, setTake] = useState(0);
  const s = SIZES[size];
  const stage = useRef<HTMLDivElement>(null);
  const box = useFit(stage, s.w / s.h);
  const t = still ? { duration: 0 } : SPRINGS.lift;
  const plate = page.wall.tiles[line % page.wall.tiles.length]?.plate ?? "var(--plate-1)";

  // the next line every few seconds, unless the person asked for stillness
  useEffect(() => {
    if (still) return;
    const id = setInterval(() => setLine((l) => (l + 1) % LINES.length), 3600);
    return () => clearInterval(id);
  }, [still]);

  const word = LINES[line];
  return (
    <section id="words" className="border-t border-border">
      <div className="mx-auto max-w-[1100px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">The words, in quotes</span>
          <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">Say the words. Read them back.</h2>
        </div>

        <div role="radiogroup" aria-label="Size" className="mx-auto mt-8 flex justify-center gap-1.5">
          {SIZES.map((sz, k) => (
            <button
              key={sz.key}
              type="button"
              role="radio"
              aria-checked={k === size}
              onClick={() => setSize(k)}
              className="relative rounded-full px-3.5 py-1.5 text-[13px] font-medium text-foreground outline-none transition-colors hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {k === size && (
                <motion.span layoutId={still ? undefined : "size-pill"} transition={t} aria-hidden className="absolute inset-0 rounded-full bg-primary" />
              )}
              <span className={`relative ${k === size ? "text-primary-foreground" : ""}`}>
                {sz.label} <span className="opacity-70">{sz.w}×{sz.h}</span>
              </span>
            </button>
          ))}
        </div>

        <div ref={stage} className="mx-auto mt-8 flex h-[clamp(260px,48svh,480px)] items-center justify-center">
          <motion.button
            type="button"
            onClick={() => setTake((n) => n + 1)}
            aria-label="Set the line again"
            layout={!still}
            transition={still ? { duration: 0 } : { type: "spring", stiffness: 260, damping: 28 }}
            style={{ width: box.width || undefined, height: box.height || undefined }}
            className="relative overflow-hidden rounded-2xl bg-card text-left shadow-[var(--card-shadow)] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <div aria-hidden className="absolute inset-0" style={{ background: plate }} />
            <span className="absolute top-3 left-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
              TODO still
            </span>
            <div className="absolute inset-0 flex items-center justify-center p-6">
              <AnimatePresence mode="wait" initial={false}>
                <motion.span
                  key={`${word}-${take}`}
                  aria-label={word}
                  exit={still ? undefined : { opacity: 0, transition: { duration: 0.18 } }}
                  className="display text-center text-[clamp(2rem,7vw,4.5rem)] text-white drop-shadow-[0_2px_12px_rgba(0,0,0,0.35)]"
                >
                  {word.split("").map((ch, i) => (
                    <motion.span
                      key={i}
                      aria-hidden
                      initial={still ? false : { opacity: 0, y: 14 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, ease: EASE_OUT, delay: still ? 0 : 0.05 + i * 0.045 }}
                      className="inline-block"
                    >
                      {ch === " " ? " " : ch}
                    </motion.span>
                  ))}
                </motion.span>
              </AnimatePresence>
            </div>
          </motion.button>
        </div>

        <p className="mx-auto mt-5 max-w-[52ch] text-center text-[15px] text-[var(--ink-2)]">
          The prompt said <span className="font-semibold text-foreground">&ldquo;{word}&rdquo;</span>. GPT Image 2 is sent
          the {s.label.toLowerCase()} size, {s.w} by {s.h}, at the medium quality tier.
        </p>
      </div>
    </section>
  );
}

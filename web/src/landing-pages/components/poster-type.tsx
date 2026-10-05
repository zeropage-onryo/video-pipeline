"use client";

import { useRef, useState, type PointerEvent } from "react";
import { AnimatePresence, motion, useMotionValue, useSpring, useTransform } from "motion/react";
import { EASE_OUT, SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import type { MakePage } from "../pages";

// The Ideogram page's signature (2026-10-05): a poster, and the type on it.
// One 2:3 poster plate that tilts toward the pointer (the wall's spring),
// a title that swaps when a setting is picked -- the serif, the condensed
// display face and the mono, the site's own three -- and a pill that
// slides between them. What it says is the brief Ideogram takes: the
// words, and how they are set. Reduced motion: no tilt, instant swaps.

const SETTINGS = [
  { key: "display", label: "Condensed", cls: "display text-[clamp(2.4rem,9vw,5.5rem)]", words: "LAST\nNIGHT" },
  { key: "serif", label: "Serif", cls: "serif serif-bold text-[clamp(2rem,7.5vw,4.5rem)]", words: "Last\nNight" },
  { key: "mono", label: "Mono", cls: "font-mono uppercase tracking-[0.2em] text-[clamp(1.1rem,3.6vw,2rem)]", words: "LAST\nNIGHT" },
] as const;
const TILT = 6;

export function PosterType({ page }: { page: MakePage }) {
  const still = useStill();
  const [i, setI] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const rotateY = useSpring(useTransform(px, [-0.5, 0.5], [-TILT, TILT]), SPRINGS.settle);
  const rotateX = useSpring(useTransform(py, [-0.5, 0.5], [TILT, -TILT]), SPRINGS.settle);
  const t = still ? { duration: 0 } : SPRINGS.lift;
  const s = SETTINGS[i];
  const plate = page.wall.tiles[i]?.plate ?? "var(--plate-1)";

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el || still || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width - 0.5);
    py.set((e.clientY - r.top) / r.height - 0.5);
  };
  const onLeave = () => {
    px.set(0);
    py.set(0);
  };

  return (
    <section id="type" className="border-t border-border">
      <div className="mx-auto max-w-[1100px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Posters, logos, lettering</span>
          <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">Say how the words are set.</h2>
        </div>

        <div className="mx-auto mt-10 grid max-w-[860px] items-center gap-8 md:grid-cols-[1fr_300px]">
          <div className="flex justify-center" style={{ perspective: 1100 }}>
            <motion.div
              ref={ref}
              onPointerMove={onMove}
              onPointerLeave={onLeave}
              style={{ rotateX: still ? 0 : rotateX, rotateY: still ? 0 : rotateY }}
              className="relative aspect-[2/3] w-full max-w-[340px] overflow-hidden rounded-2xl bg-card shadow-[var(--card-shadow)] will-change-transform"
            >
              <div aria-hidden className="absolute inset-0" style={{ background: plate }} />
              <span className="absolute top-3 left-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
                TODO still
              </span>
              <div className="absolute inset-0 flex items-end p-6">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.h3
                    key={s.key}
                    initial={still ? false : { opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={still ? undefined : { opacity: 0, y: -12 }}
                    transition={{ duration: 0.28, ease: EASE_OUT }}
                    className={`whitespace-pre-line text-white drop-shadow-[0_2px_12px_rgba(0,0,0,0.35)] ${s.cls}`}
                  >
                    {s.words}
                  </motion.h3>
                </AnimatePresence>
              </div>
            </motion.div>
          </div>

          <div>
            <span className="eyebrow">The setting</span>
            <div role="radiogroup" aria-label="Type setting" className="mt-3 flex flex-col gap-1.5">
              {SETTINGS.map((st, k) => (
                <button
                  key={st.key}
                  type="button"
                  role="radio"
                  aria-checked={k === i}
                  onClick={() => setI(k)}
                  className="relative rounded-xl px-4 py-3 text-left text-[14px] font-medium text-foreground outline-none transition-colors hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {k === i && (
                    <motion.span layoutId={still ? undefined : "type-pill"} transition={t} aria-hidden className="absolute inset-0 rounded-xl bg-primary" />
                  )}
                  <span className={`relative ${k === i ? "text-primary-foreground" : ""}`}>{st.label}</span>
                </button>
              ))}
            </div>
            <p className="mt-5 text-[15px] leading-relaxed text-[var(--ink-2)]">
              The prompt names the words in quotes and the setting in plain words. Ideogram draws the poster from
              that line alone, no reference photos.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

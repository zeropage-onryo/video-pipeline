"use client";

import Image from "next/image";
import { useRef, useState, type PointerEvent } from "react";
import { AnimatePresence, motion, useMotionValue, useSpring, useTransform } from "motion/react";
import { EASE_OUT, SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import type { MakePage } from "../pages";

// The Ideogram page's signature (2026-10-05; real posters 2026-10-08): one
// poster, three settings of the same words. Each setting is a poster
// Ideogram actually drew from a prompt that changed ONE phrase -- how the
// title is set -- and nothing else, so what changes on screen is what the
// words asked for. The poster tilts toward the pointer (the wall's spring),
// the pill slides between settings. Reduced motion: no tilt, instant swaps.
//
// `signatureFrames` carries the posters: `title` is the setting's name,
// `prompt` the phrase that set it.
const TILT = 6;

export function PosterType({ page }: { page: MakePage }) {
  const still = useStill();
  const posters = page.signatureFrames ?? [];
  const [i, setI] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const rotateY = useSpring(useTransform(px, [-0.5, 0.5], [-TILT, TILT]), SPRINGS.settle);
  const rotateX = useSpring(useTransform(py, [-0.5, 0.5], [TILT, -TILT]), SPRINGS.settle);
  const t = still ? { duration: 0 } : SPRINGS.lift;

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
  if (posters.length === 0) return null;
  const poster = posters[i];

  return (
    <section id="type" className="border-t border-border">
      <div className="mx-auto max-w-[1100px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Same words, three settings</span>
          <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">Say how the words are set.</h2>
        </div>

        <div className="mx-auto mt-10 grid max-w-[880px] items-center gap-10 md:grid-cols-[1fr_320px]">
          <div className="flex justify-center" style={{ perspective: 1100 }}>
            <motion.div
              ref={ref}
              onPointerMove={onMove}
              onPointerLeave={onLeave}
              style={{ rotateX: still ? 0 : rotateX, rotateY: still ? 0 : rotateY }}
              className="relative aspect-[2/3] w-full max-w-[360px] overflow-hidden rounded-lg bg-card shadow-[0_30px_70px_-30px_rgba(0,0,0,0.5)] will-change-transform"
            >
              <AnimatePresence initial={false}>
                <motion.div
                  key={i}
                  initial={still ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={still ? undefined : { opacity: 0 }}
                  transition={{ duration: 0.35, ease: EASE_OUT }}
                  className="absolute inset-0"
                >
                  {poster.src ? (
                    <Image src={poster.src} alt={`${poster.title}: ${poster.meta ?? ""}`} fill sizes="360px" quality={75} className="object-cover" />
                  ) : (
                    <div aria-hidden className="absolute inset-0" style={{ background: poster.plate ?? "var(--plate-1)" }} />
                  )}
                </motion.div>
              </AnimatePresence>
            </motion.div>
          </div>

          <div>
            <span className="eyebrow">The setting</span>
            <div role="radiogroup" aria-label="Type setting" className="mt-3 flex flex-col gap-1.5">
              {posters.map((st, k) => (
                <button
                  key={st.title}
                  type="button"
                  role="radio"
                  aria-checked={k === i}
                  onClick={() => setI(k)}
                  className="relative rounded-xl px-4 py-3 text-left outline-none transition-colors hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {k === i && (
                    <motion.span layoutId={still ? undefined : "type-pill"} transition={t} aria-hidden className="absolute inset-0 rounded-xl bg-primary" />
                  )}
                  <span className={`relative block text-[14px] font-semibold ${k === i ? "text-primary-foreground" : "text-foreground"}`}>{st.title}</span>
                  {st.prompt && (
                    <span className={`relative mt-0.5 block font-mono text-[11.5px] ${k === i ? "text-primary-foreground/80" : "text-[var(--ink-2)]"}`}>
                      &ldquo;{st.prompt}&rdquo;
                    </span>
                  )}
                </button>
              ))}
            </div>
            <p className="mt-5 text-[15px] leading-relaxed text-[var(--ink-2)]">
              The prompt names the words in quotes and the setting in plain words; only that phrase changed between the
              three. Ideogram drew each poster from the line alone, no reference photos.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

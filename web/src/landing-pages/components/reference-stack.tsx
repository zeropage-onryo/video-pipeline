"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE_OUT, SPRINGS } from "@/lib/motion";
import { useRevealGroup, useStill } from "@/lib/motion-hooks";
import type { MakePage, MakeTile } from "../pages";

// The Nano Banana page's signature (2026-10-05; real stills 2026-10-08):
// the references reach the model. Three reference photos sit beside one
// frame; step through them -- one reference, two, three -- and the frame
// shows the still Nano Banana Pro actually drew with that many attached,
// the prompt that asked for it underneath. The page's own claim, shown
// rather than told: the same mug, then the same mug in the same person's
// hands, then both in the same cafe.
//
// `signatureFrames` is the references then the results, the same count of
// each (three and three). The steps cycle on their own while the section
// is in view until someone picks one; reduced motion never cycles.

export function ReferenceStack({ page }: { page: MakePage }) {
  const still = useStill();
  const frames = page.signatureFrames ?? [];
  const half = Math.floor(frames.length / 2);
  const refs = frames.slice(0, half);
  const results = frames.slice(half, half * 2);
  const [step, setStep] = useState(0);
  const [touched, setTouched] = useState(false);
  const { ref, show } = useRevealGroup<HTMLDivElement>(0.4);

  useEffect(() => {
    if (still || touched || !show || results.length < 2) return;
    const id = window.setInterval(() => setStep((s) => (s + 1) % results.length), 3800);
    return () => window.clearInterval(id);
  }, [still, touched, show, results.length]);

  if (results.length === 0) return null;
  const pick = (i: number) => {
    setTouched(true);
    setStep(i);
  };
  const result = results[step];
  const fade = still ? { duration: 0 } : { duration: 0.45, ease: EASE_OUT };

  return (
    <section id="references" className="border-t border-border bg-[color-mix(in_oklab,var(--primary)_5%,var(--background))]">
      <div ref={ref} className="mx-auto max-w-[1100px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Your photos go to the model</span>
          <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">Add a reference. The still is held to it.</h2>
        </div>

        <div className="mx-auto mt-10 grid max-w-[920px] items-start gap-8 md:mt-14 md:grid-cols-[260px_1fr] md:gap-10">
          {/* the references, attached in order */}
          <div>
            <div role="radiogroup" aria-label="References attached" className="flex flex-col gap-3">
              {refs.map((tile, i) => {
                const attached = i <= step;
                return (
                  <button
                    key={tile.title}
                    type="button"
                    role="radio"
                    aria-checked={i === step}
                    onClick={() => pick(i)}
                    className="group flex items-center gap-4 rounded-2xl border border-[var(--card-line)] bg-background p-2.5 pr-4 text-left outline-none transition-colors duration-300 hover:border-[var(--line-hover)] focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    <motion.span
                      animate={{ opacity: attached ? 1 : 0.35, scale: attached ? 1 : 0.92 }}
                      transition={still ? { duration: 0 } : SPRINGS.lift}
                      className="relative size-16 shrink-0 overflow-hidden rounded-xl bg-card"
                    >
                      <RefImage tile={tile} />
                    </motion.span>
                    <span className="min-w-0">
                      <span className="eyebrow block">{attached ? `Reference ${i + 1}` : "Not attached"}</span>
                      <span className="mt-1 block text-[15px] font-semibold leading-tight">{tile.title}</span>
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="mt-5 text-[13px] leading-relaxed text-[var(--ink-2)]">
              Each reference is a photo dropped into the composer. All three were drawn on Nano Banana Pro too, from text.
            </p>
          </div>

          {/* the still they produced */}
          <figure>
            <div className="relative aspect-[4/5] w-full overflow-hidden rounded-3xl bg-card shadow-[0_30px_70px_-35px_rgba(0,0,0,0.45)]">
              <AnimatePresence initial={false}>
                <motion.div
                  key={step}
                  initial={still ? false : { opacity: 0, scale: 1.03 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={still ? undefined : { opacity: 0 }}
                  transition={fade}
                  className="absolute inset-0"
                >
                  <RefImage tile={result} sizes="(min-width: 768px) 620px, 100vw" />
                </motion.div>
              </AnimatePresence>
              <span className="absolute left-4 top-4 rounded-full bg-black/55 px-3 py-1.5 text-[12px] font-medium text-white backdrop-blur-md">
                {step + 1} reference{step === 0 ? "" : "s"} attached
              </span>
            </div>
            <figcaption aria-live="polite" className="mt-4 min-h-[5.5rem]">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={step}
                  initial={still ? false : { opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={still ? undefined : { opacity: 0, y: -6 }}
                  transition={{ duration: 0.25, ease: EASE_OUT }}
                >
                  <span className="block text-[16px] font-semibold leading-tight">{result.title}</span>
                  {result.prompt && (
                    <span className="mt-2 block font-mono text-[12px] leading-relaxed text-[var(--ink-2)]">{result.prompt}</span>
                  )}
                </motion.div>
              </AnimatePresence>
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}

function RefImage({ tile, sizes = "64px" }: { tile: MakeTile; sizes?: string }) {
  if (!tile.src) return <span aria-hidden className="absolute inset-0" style={{ background: tile.plate ?? "var(--plate-1)" }} />;
  return <Image src={tile.src} alt={tile.title} fill sizes={sizes} quality={75} className="object-cover" />;
}

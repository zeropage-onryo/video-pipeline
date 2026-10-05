"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE_OUT, SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import type { MakePage } from "../pages";

// The Nano Banana page's signature (2026-10-05): the references reach the
// model. Six photo slots sit under one frame; tap a slot and it slides up
// into the row of attached references (a layout animation), the frame
// takes on more of their colour, and the line under it says how many are
// going to the model. What it draws is the studio's rule for a still:
// reference photos in the composer go to the model's edit endpoint.
// Reduced motion: the moves are instant.
//
// TODO(media): the six slots are plates; real photos go in as `src`
// on the page's wall tiles, which this reads.

const SLOTS = ["Face", "Jacket", "Room", "Product", "Light", "Palette"];

export function ReferenceStack({ page }: { page: MakePage }) {
  const still = useStill();
  const [on, setOn] = useState<number[]>([0, 3]);
  const toggle = (i: number) => setOn((s) => (s.includes(i) ? s.filter((x) => x !== i) : [...s, i]));
  const tiles = page.wall.tiles;
  const t = still ? { duration: 0 } : SPRINGS.lift;
  const strength = Math.min(on.length, 6) / 6;

  return (
    <section id="references" className="border-t border-border">
      <div className="mx-auto max-w-[1100px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Your photos go to the model</span>
          <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">Attach a reference. The still is held to it.</h2>
        </div>

        <div className="mx-auto mt-10 grid max-w-[860px] gap-6 md:grid-cols-[1fr_280px] md:gap-8">
          {/* the frame, with the attached row above it */}
          <div className="flex flex-col gap-3">
            <div className="flex min-h-[52px] flex-wrap items-center gap-2" aria-label="Attached references">
              <AnimatePresence initial={false}>
                {on.map((i) => (
                  <motion.button
                    key={i}
                    type="button"
                    layoutId={still ? undefined : `ref-${i}`}
                    onClick={() => toggle(i)}
                    initial={still ? false : { opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={still ? undefined : { opacity: 0 }}
                    transition={t}
                    aria-label={`Detach ${SLOTS[i]}`}
                    className="group relative size-12 overflow-hidden rounded-lg ring-2 ring-primary outline-none focus-visible:ring-4"
                  >
                    <span aria-hidden className="absolute inset-0" style={{ background: tiles[i]?.plate ?? "var(--plate-1)" }} />
                    <span className="absolute inset-x-0 bottom-0 bg-black/55 px-1 text-[9px] font-medium text-white">{SLOTS[i]}</span>
                  </motion.button>
                ))}
              </AnimatePresence>
              <span className="text-[13px] text-[var(--ink-3)]">{on.length === 0 ? "none attached, draws from the prompt alone" : ""}</span>
            </div>

            <div className="relative aspect-[4/5] w-full overflow-hidden rounded-2xl bg-card">
              <div aria-hidden className="absolute inset-0" style={{ background: "var(--plate-2)" }} />
              {/* the references' colour, laid over the frame as they attach (opacity only) */}
              <motion.div
                aria-hidden
                animate={{ opacity: strength }}
                transition={still ? { duration: 0 } : { duration: 0.5, ease: EASE_OUT }}
                className="absolute inset-0"
                style={{ background: "linear-gradient(160deg, var(--primary) 0%, transparent 70%)" }}
              />
              <span className="absolute top-3 left-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
                TODO still
              </span>
              <div aria-live="polite" className="absolute inset-x-4 bottom-4 text-white">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.p
                    key={on.length}
                    initial={still ? false : { opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={still ? undefined : { opacity: 0, y: -6 }}
                    transition={{ duration: 0.25, ease: EASE_OUT }}
                    className="text-[15px] font-semibold leading-tight"
                  >
                    {on.length === 0
                      ? "Drawn from the prompt alone."
                      : `${on.length} reference${on.length === 1 ? "" : "s"} reach the model with the prompt.`}
                  </motion.p>
                </AnimatePresence>
              </div>
            </div>
          </div>

          {/* the slots */}
          <div>
            <span className="eyebrow">Tap to attach</span>
            <ul className="mt-3 grid grid-cols-3 gap-2 md:grid-cols-2">
              {SLOTS.map((label, i) => {
                const attached = on.includes(i);
                return (
                  <li key={label} className="relative aspect-square">
                    {!attached && (
                      <motion.button
                        type="button"
                        layoutId={still ? undefined : `ref-${i}`}
                        onClick={() => toggle(i)}
                        whileHover={still ? undefined : { y: -3 }}
                        whileTap={still ? undefined : { scale: 0.97 }}
                        transition={t}
                        aria-pressed={false}
                        aria-label={`Attach ${label}`}
                        className="absolute inset-0 overflow-hidden rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                      >
                        <span aria-hidden className="absolute inset-0" style={{ background: tiles[i]?.plate ?? "var(--plate-1)" }} />
                        <span className="absolute inset-x-0 bottom-0 bg-black/50 px-2 py-1 text-left text-[11px] font-medium text-white">{label}</span>
                      </motion.button>
                    )}
                    {attached && (
                      <button
                        type="button"
                        onClick={() => toggle(i)}
                        aria-pressed
                        aria-label={`Detach ${label}`}
                        className="absolute inset-0 rounded-xl border border-dashed border-[var(--card-line)] text-[11px] text-[var(--ink-3)] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                      >
                        attached
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

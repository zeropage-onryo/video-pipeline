"use client";

import Image from "next/image";
import { useRef, useState, type PointerEvent } from "react";
import { motion, useMotionTemplate, useMotionValue, useSpring, useTransform } from "motion/react";
import { SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import type { MakePage, MakeTile } from "../pages";

// The Seedream page's signature (2026-10-05): generate, then edit in the
// same model. One frame, two plates -- the draw and the edit -- and a
// divider that follows the pointer (or a drag on a phone). The reveal is
// transform-only: the "after" layer slides in a clipped wrapper and its
// picture slides back by the same amount, so nothing repaints but the
// compositor. Two buttons jump the divider for the keyboard. Reduced
// motion: the divider still follows, without the spring.
//
// The frames are `signatureFrames` (2026-10-08): the draw first, then
// each edit of it, picked from the list beside the frame.

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
  // the signature's own stills (2026-10-08): the draw, then edits of it,
  // each made by sending the draw back with one line. Older entries fall
  // back to the wall's first two tiles.
  const frames = page.signatureFrames?.length ? page.signatureFrames : page.wall.tiles.slice(0, 2);
  const [before, ...edits] = frames;
  const [k, setK] = useState(0);
  const after = edits[k];
  const portrait = (before?.aspect ?? "3:2").split(":").map(Number);
  const aspect = `${portrait[0]} / ${portrait[1]}`;
  const tall = portrait[1] > portrait[0];

  return (
    <section id="edit" className="border-t border-border">
      <div className="mx-auto max-w-[1100px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">Generate, then edit</span>
          <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">The draw and the edit, one model.</h2>
        </div>

        <div className={`mx-auto mt-10 grid items-center gap-8 md:mt-14 ${tall ? "max-w-[900px] md:grid-cols-[minmax(0,1fr)_300px]" : "max-w-[860px]"}`}>
          <div
            ref={ref}
            onPointerMove={onMove}
            onPointerDown={(e) => set(e.clientX)}
            style={{ aspectRatio: aspect }}
            className={`relative w-full touch-pan-y overflow-hidden rounded-2xl bg-card select-none ${tall ? "mx-auto max-w-[480px]" : ""}`}
          >
            {/* before */}
            <Layer tile={before} fallback="var(--plate-1)" />
            <span className="absolute top-3 left-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
              The draw
            </span>
            {/* after, revealed from the right */}
            <motion.div aria-hidden style={{ transform: wrap }} className="absolute inset-0 overflow-hidden will-change-transform">
              <motion.div style={{ transform: inner }} className="absolute inset-0 will-change-transform">
                <Layer tile={after} fallback="var(--plate-2)" />
              </motion.div>
              <motion.span style={{ transform: inner }} className="absolute top-3 right-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
                The edit
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

          {edits.length > 1 && (
            <div>
              <span className="eyebrow">Pick an edit</span>
              <ul role="radiogroup" aria-label="Edit" className="mt-3 flex flex-col gap-2">
                {edits.map((edit, i) => (
                  <li key={edit.title}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={i === k}
                      onClick={() => {
                        setK(i);
                        raw.set(0.35);
                      }}
                      className={`w-full rounded-xl border px-4 py-3 text-left outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 ${i === k ? "border-[var(--line-hover)] bg-[color-mix(in_oklab,var(--primary)_7%,transparent)]" : "border-[var(--card-line)] hover:border-[var(--line-hover)]"}`}
                    >
                      <span className="block text-[15px] font-semibold leading-tight">{edit.title}</span>
                      {edit.prompt && <span className="mt-1 block text-[12.5px] leading-snug text-[var(--ink-2)]">{edit.prompt}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="mt-6 flex items-center justify-center gap-2">
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
        <p className="mx-auto mt-4 max-w-[56ch] text-center text-[15px] text-[var(--ink-2)]">
          Attach a still you drew as a reference, write the one line that changes it, and Seedream edits it rather than
          drawing again: same person, same pose, same frame. Each pass lands on the wall as its own still.
        </p>
      </div>
    </section>
  );
}

function Layer({ tile, fallback }: { tile?: MakeTile; fallback: string }) {
  if (!tile?.src) return <div aria-hidden className="absolute inset-0" style={{ background: tile?.plate ?? fallback }} />;
  return <Image src={tile.src} alt={tile.title} fill sizes="(min-width: 768px) 560px, 100vw" quality={78} draggable={false} className="object-cover" />;
}

// x in [0,1] -> "NN%" of the wrapper's travel, in one direction
function useTransformPct(x: ReturnType<typeof useSpring>, sign: 1 | -1) {
  const n = useTransform(x, (v) => sign * (v * 100));
  return useMotionTemplate`${n}%`;
}

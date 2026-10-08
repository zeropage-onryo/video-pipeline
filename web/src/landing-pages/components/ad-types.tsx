"use client";

import Image from "next/image";
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE_OUT, SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import type { MakePage, MakeTile } from "../pages";

// The GPT Image 2.5 page's signature (2026-10-08): one product photo, six
// ad formats. Pick a format and the frame shows the still GPT Image 2.5 drew
// for it, the variant and quality that drew it, and the instruction it was
// given. A before/after (`from` on the tile) draws under a draggable
// divider; a cutout (`alpha`) sits on a checkerboard so the transparency
// reads. Reduced motion: the swaps are instant.
//
// `signatureFrames` are the six formats: `title` the format, `tag` the
// variant and quality, `prompt` the instruction (abridged where the source
// was), `src` the still.

const CHECKER =
  "repeating-conic-gradient(#e7e5e4 0% 25%, #fafaf9 0% 50%) 50% / 22px 22px";

export function AdTypes({ page }: { page: MakePage }) {
  const still = useStill();
  const types = page.signatureFrames ?? [];
  const [i, setI] = useState(0);
  const [split, setSplit] = useState(50);
  if (!types.length) return null;
  const t = types[i];
  const fade = still ? { duration: 0 } : { duration: 0.35, ease: EASE_OUT };

  return (
    <section id="formats" className="border-t border-border">
      <div className="mx-auto max-w-[1180px] px-4 py-16 md:px-6 md:py-24">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="eyebrow">One photo in, six formats out</span>
          <h2 className="serif max-w-[24ch] text-[clamp(1.75rem,4.2vw,3rem)]">One bottle. Six ads. The label spelled every time.</h2>
        </div>

        <div className="mt-10 grid gap-8 md:mt-14 md:grid-cols-[240px_minmax(0,1fr)_280px] md:items-start md:gap-10">
          {/* the formats */}
          <div role="tablist" aria-label="Ad format" className="flex gap-2 overflow-x-auto pb-1 md:flex-col md:overflow-visible">
            {types.map((ty, k) => (
              <button
                key={ty.title}
                type="button"
                role="tab"
                aria-selected={k === i}
                onClick={() => {
                  setI(k);
                  setSplit(50);
                }}
                className="relative flex shrink-0 items-baseline gap-3 rounded-xl px-4 py-3 text-left outline-none transition-colors hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {k === i && (
                  <motion.span
                    layoutId={still ? undefined : "adtype-pill"}
                    transition={still ? { duration: 0 } : SPRINGS.lift}
                    aria-hidden
                    className="absolute inset-0 rounded-xl bg-primary"
                  />
                )}
                <span className={`relative font-mono text-[11px] ${k === i ? "text-primary-foreground/80" : "text-[var(--ink-2)]"}`}>
                  {String(k + 1).padStart(2, "0")}
                </span>
                <span className={`relative whitespace-nowrap text-[15px] font-semibold ${k === i ? "text-primary-foreground" : "text-foreground"}`}>{ty.title}</span>
              </button>
            ))}
          </div>

          {/* the still */}
          <div className="relative mx-auto aspect-[4/5] w-full max-w-[480px] overflow-hidden rounded-2xl shadow-[0_30px_70px_-35px_rgba(0,0,0,0.45)]" style={{ background: t.alpha ? CHECKER : "var(--card)" }}>
            <AnimatePresence initial={false}>
              <motion.div key={i} initial={still ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={still ? undefined : { opacity: 0 }} transition={fade} className="absolute inset-0">
                {t.from ? <Divided tile={t} split={split} /> : <Still tile={t} />}
              </motion.div>
            </AnimatePresence>
            {t.from && (
              <>
                <label htmlFor="adtype-split" className="sr-only">
                  Before and after divider
                </label>
                <input
                  id="adtype-split"
                  type="range"
                  min={0}
                  max={100}
                  value={split}
                  onChange={(e) => setSplit(Number(e.target.value))}
                  className="absolute inset-x-4 bottom-4 z-10 accent-[var(--primary)]"
                />
              </>
            )}
          </div>

          {/* how it was made */}
          <aside aria-live="polite" className="min-h-[220px]">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={i} initial={still ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={still ? undefined : { opacity: 0, y: -6 }} transition={{ duration: 0.25, ease: EASE_OUT }}>
                <span className="eyebrow">Drawn on</span>
                <p className="mt-1 text-[18px] font-bold tracking-[-0.01em]">{t.tag}</p>
                {t.meta && <p className="mt-3 text-[14px] leading-relaxed text-[var(--ink-2)]">{t.meta}</p>}
                {t.prompt && (
                  <>
                    <span className="eyebrow mt-5 block">The instruction</span>
                    <p className="mt-1 rounded-xl border border-[var(--card-line)] p-3 font-mono text-[12px] leading-relaxed text-[var(--ink-2)]">{t.prompt}</p>
                  </>
                )}
              </motion.div>
            </AnimatePresence>
          </aside>
        </div>
      </div>
    </section>
  );
}

function Still({ tile }: { tile: MakeTile }) {
  if (!tile.src) return <div aria-hidden className="absolute inset-0" style={{ background: tile.plate ?? "var(--plate-1)" }} />;
  return (
    <Image
      src={tile.src}
      alt={tile.title}
      fill
      sizes="(min-width: 768px) 480px, 100vw"
      quality={75}
      className={tile.alpha ? "object-contain" : "object-cover"}
    />
  );
}

// before on the left of the divider, the edit on the right
function Divided({ tile, split }: { tile: MakeTile; split: number }) {
  return (
    <>
      <Image src={tile.from!} alt={`${tile.title}: before`} fill sizes="(min-width: 768px) 480px, 100vw" quality={75} className="object-cover" />
      <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
        <Image src={tile.src!} alt={`${tile.title}: after`} fill sizes="(min-width: 768px) 480px, 100vw" quality={75} className="object-cover" />
      </div>
      <div aria-hidden className="absolute inset-y-0 w-0.5 bg-white/90" style={{ left: `${split}%` }} />
      <span className="absolute left-3 top-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">Before</span>
      <span className="absolute right-3 top-3 rounded-md bg-[var(--primary)] px-2 py-1 text-[11px] font-semibold text-[var(--primary-foreground)]">After</span>
    </>
  );
}

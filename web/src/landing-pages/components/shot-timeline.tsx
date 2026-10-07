"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll, useSpring, useTransform } from "motion/react";
import { EASE_OUT, SPRINGS } from "@/lib/motion";
import { useStill } from "@/lib/motion-hooks";
import type { MakePage, MakeTile } from "../pages";

// The Seedance page's signature (2026-10-05): ONE scene scrubbed by the
// scroll. The section pins for two and a half screens; as the page moves,
// a 15-second rail fills, the clock runs, and the three timed shots light
// up one after the other, each a clip Seedance would render on its own --
// which is exactly how the studio writes and renders a scene
// (src/timeline.py: timed windows, one shot per window, one clip per shot).
//
// Scroll-linked on Motion: useScroll on the pinned block, useTransform for
// the rail's scaleX, the clock and each frame's opacity (transform and
// opacity only), useMotionValueEvent to pick the active shot, a layoutId
// ring that slides between the cards, and AnimatePresence on the caption.
// Under reduced motion nothing pins and nothing is scroll-linked: the three
// shots sit still, the first is active, and a tap moves the ring.
//
// TODO(media): the three frames are the entry's `signatureFrames` (else
// the wall's first three tiles); a still dropped there (`src`) shows here.

const SCENE_SECONDS = 15;
const SHOTS = [
  { label: "Wide establishing", start: 0, end: 5, prompt: "Wide, static. A ceramics studio at dawn; dust hangs in one shaft of light over the wheel." },
  { label: "Macro detail", start: 5, end: 10, prompt: "Macro, slow push-in. Wet thumbs open the clay on the spinning wheel; slip runs over the knuckles." },
  { label: "The action", start: 10, end: 15, prompt: "Medium, handheld. She lifts the glazed cup to the window and turns it once; the indigo catches the light." },
] as const;

export function ShotTimeline({ page }: { page: MakePage }) {
  const still = useStill();
  const outer = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);

  const { scrollYProgress } = useScroll({ target: outer, offset: ["start start", "end end"] });
  // a touch of spring so the rail and the clock lag the wheel by a frame
  const progress = useSpring(scrollYProgress, { stiffness: 180, damping: 28, mass: 0.4 });
  const clock = useTransform(progress, (v) => `${(v * SCENE_SECONDS).toFixed(1)}s`);

  useMotionValueEvent(scrollYProgress, "change", (v) => {
    if (still) return;
    setActive(Math.min(SHOTS.length - 1, Math.max(0, Math.floor(v * SHOTS.length))));
  });

  const jump = (i: number) => {
    setActive(i);
    const el = outer.current;
    if (still || !el) return;
    const span = el.offsetHeight - window.innerHeight;
    const frac = (SHOTS[i].start + 0.5) / SCENE_SECONDS; // the shot's first beat
    window.scrollTo({ top: el.offsetTop + span * frac, behavior: "smooth" });
  };

  const tiles = page.signatureFrames ?? page.wall.tiles;

  return (
    <section id="shots" className="border-t border-border">
      {/* the pinned block: two and a half screens of scroll under reduced-motion-free pointers, one plain section otherwise */}
      <div ref={outer} className={still ? "" : "h-[260svh]"}>
        <div className={still ? "" : "sticky top-[60px] flex h-[calc(100svh-60px)] flex-col justify-center"}>
          <div className="mx-auto w-full max-w-[1100px] px-4 py-14 md:px-6 md:py-16">
            <div className="flex flex-col items-center gap-3 text-center">
              <span className="eyebrow">One scene, three timed shots</span>
              <h2 className="serif text-[clamp(1.75rem,4.2vw,3rem)]">
                Each shot is its own Seedance clip.
              </h2>
            </div>

            {/* the rail: 0 to 15 s, one mark per shot, filled by the scroll */}
            <div className="mt-8 md:mt-10">
              <div className="flex items-center justify-between text-[12px] font-medium text-[var(--ink-3)]">
                <span>0s</span>
                <span className="inline-flex items-center gap-2 tabular-nums text-foreground">
                  <span className="eyebrow">clock</span>
                  <motion.span className="text-[14px] font-semibold">{still ? `${SCENE_SECONDS}s` : clock}</motion.span>
                </span>
                <span>{SCENE_SECONDS}s</span>
              </div>
              <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-secondary">
                <motion.div
                  aria-hidden
                  style={{ scaleX: still ? 1 : progress, transformOrigin: "0% 50%" }}
                  className="absolute inset-0 rounded-full bg-primary"
                />
              </div>
              <div className="relative mt-1 h-3">
                {SHOTS.slice(1).map((s) => (
                  <span
                    key={s.start}
                    aria-hidden
                    style={{ left: `${(s.start / SCENE_SECONDS) * 100}%` }}
                    className="absolute top-0 h-3 w-px bg-[var(--ink-3)]"
                  />
                ))}
              </div>
            </div>

            {/* the three shots */}
            <div className="mt-6 grid grid-cols-3 gap-3 md:mt-8 md:gap-4">
              {SHOTS.map((shot, i) => (
                <ShotCard
                  key={shot.label}
                  index={i}
                  shot={shot}
                  tile={tiles[i]}
                  active={active === i}
                  still={still}
                  progress={progress}
                  onPick={() => jump(i)}
                />
              ))}
            </div>

            {/* the active shot's line, swapped as the ring moves */}
            <div aria-live="polite" className="mx-auto mt-6 min-h-[4.5rem] max-w-[56ch] text-center md:mt-8">
              <AnimatePresence mode="wait" initial={false}>
                <motion.p
                  key={active}
                  initial={still ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={still ? undefined : { opacity: 0, y: -8 }}
                  transition={{ duration: 0.28, ease: EASE_OUT }}
                  className="text-[15px] leading-relaxed text-[var(--ink-2)] md:text-[16px]"
                >
                  <span className="font-semibold text-foreground">
                    Shot {active + 1} of {SHOTS.length} ({SHOTS[active].start}–{SHOTS[active].end}s):
                  </span>{" "}
                  {SHOTS[active].prompt}
                </motion.p>
              </AnimatePresence>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ShotCard({
  index,
  shot,
  tile,
  active,
  still,
  progress,
  onPick,
}: {
  index: number;
  shot: (typeof SHOTS)[number];
  tile: MakeTile | undefined;
  active: boolean;
  still: boolean;
  progress: ReturnType<typeof useSpring>;
  onPick: () => void;
}) {
  // the frame lights as the clock reaches its window (over the last two
  // seconds before it) and stays lit; shot 1 is lit from the start
  const lit = useTransform(progress, [(shot.start - 2) / SCENE_SECONDS, shot.start / SCENE_SECONDS], [0.4, 1]);
  const plate = tile?.plate ?? `var(--plate-${(index % 2) + 1})`;
  return (
    <motion.button
      type="button"
      onClick={onPick}
      aria-pressed={active}
      whileHover={still ? undefined : { y: -4 }}
      whileTap={still ? undefined : { scale: 0.98 }}
      transition={SPRINGS.lift}
      className="group relative flex flex-col gap-2 rounded-2xl p-1.5 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 md:p-2"
    >
      {active && (
        <motion.span
          layoutId="shot-ring"
          aria-hidden
          transition={still ? { duration: 0 } : SPRINGS.lift}
          className="pointer-events-none absolute inset-0 rounded-2xl border-2 border-primary"
        />
      )}
      <motion.div
        style={{ opacity: still ? 1 : lit }}
        className="relative h-[clamp(150px,34svh,400px)] w-full overflow-hidden rounded-xl bg-card"
      >
        {tile?.src ? (
          <Image src={tile.src} alt={tile.title} fill sizes="(min-width: 1024px) 30vw, 33vw" quality={70} className="object-cover" />
        ) : (
          <div aria-hidden className="absolute inset-0" style={{ background: plate }} />
        )}
        <span className="absolute top-2 left-2 rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white backdrop-blur-sm">
          {shot.start}–{shot.end}s
        </span>
      </motion.div>
      <span className="px-1 text-[12px] font-semibold leading-tight tracking-[-0.01em] text-foreground md:text-[14px]">
        <span className="text-[var(--ink-3)]">{index + 1}.</span> {shot.label}
      </span>
    </motion.button>
  );
}

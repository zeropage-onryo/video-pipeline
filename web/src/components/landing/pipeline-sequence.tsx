"use client";

import Image from "next/image";
import {
  AnimatePresence,
  motion,
  useMotionValueEvent,
  
  useScroll,
  useSpring,
  useTransform,
  type MotionValue,
} from "motion/react";
import { useStill } from "@/components/motion/use-still";
import { useRef, useState } from "react";
import { LANDING_MEDIA } from "@/content/landing-media";

// The pipeline explainer (2026-10-06): a pinned, scroll-driven sequence
// that plays the studio's four beats on one screen -- the spark is typed,
// the scene writes itself as timed shots with its references flying in,
// the keyframe is drawn top to bottom, and the clip runs on a timeline.
// The scroll IS the playhead: scrolling back rewinds it, and nothing moves
// while the reader is not scrolling.
//
// It is a DIAGRAM of the pipeline, not a recording of it. The frames are
// real keyframes the studio drew (landing-media.ts); the spark and the
// shot lines are written to describe that frame, not lifted off a row.
//
// Reduced motion gets the four beats as a static row of cards.

const KEYFRAME = LANDING_MEDIA.find((m) => m.concept === 353) ?? LANDING_MEDIA[0];
const REFS = [LANDING_MEDIA.find((m) => m.concept === 361), LANDING_MEDIA.find((m) => m.concept === 348)]
  .filter((m): m is (typeof LANDING_MEDIA)[number] => Boolean(m));

const SPARK = "a man searches a red forest at night and finds his son's bike";
const SHOTS = [
  ["0–3s", "Flashlight cuts through red fog between the trees."],
  ["3–6s", "The beam stops on a child's bike in the leaves."],
  ["6–9s", "Close on his face. Something moves behind him."],
];

const STAGES = [
  {
    title: "Bring a spark",
    body: "A sentence, a feeling, a what-if. That is the whole brief.",
  },
  {
    title: "Write the scene",
    body: "The studio writes one scene as timed shots, held to the references you gave it.",
  },
  {
    title: "Draw the keyframe",
    body: "Pick the scene and it draws the first frame from your references: the still the clip anchors on.",
  },
  {
    title: "Render the clip",
    body: "Approve it in the Queue, choose the model and length, and the shots render one by one.",
  },
];

export function PipelineSequence() {
  const still = useStill();
  return still ? <StaticPipeline /> : <PinnedPipeline />;
}

function PinnedPipeline() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const p = useSpring(scrollYProgress, { stiffness: 120, damping: 30, mass: 0.35 });
  const [stage, setStage] = useState(0);

  // State only changes when the stage does (4 renders over the whole
  // scroll); every per-frame value below is a MotionValue.
  useMotionValueEvent(p, "change", (v) => {
    const next = Math.min(STAGES.length - 1, Math.max(0, Math.floor(v * STAGES.length)));
    setStage((s) => (s === next ? s : next));
  });

  return (
    <section ref={ref} id="pipeline" aria-label="How a spark becomes a clip" className="relative h-[460vh] border-t border-border">
      <div className="sticky top-0 flex h-svh items-center overflow-hidden">
        <BigNumber stage={stage} />
        <div className="relative mx-auto grid w-full max-w-[1200px] items-center gap-8 px-6 pt-[60px] md:grid-cols-[0.85fr_1.15fr] md:gap-14">
          <div className="relative">
            <span className="eyebrow">From spark to clip</span>
            <div className="mt-6 flex items-baseline gap-4">
              <span className="eyebrow tabular-nums text-[var(--signal)]">
                {String(stage + 1).padStart(2, "0")} / {String(STAGES.length).padStart(2, "0")}
              </span>
            </div>
            <div className="relative mt-3 min-h-[8.5rem] md:min-h-[12rem]">
              <AnimatePresence mode="popLayout" initial={false}>
                <motion.div
                  key={stage}
                  initial={{ y: 40, opacity: 0, filter: "blur(8px)" }}
                  animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
                  exit={{ y: -40, opacity: 0, filter: "blur(8px)" }}
                  transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
                >
                  <h2 className="serif text-[clamp(2rem,4.6vw,3.5rem)]">{STAGES[stage].title}</h2>
                  <p className="mt-4 max-w-[38ch] text-[16px] leading-relaxed text-[#afafaf] md:text-[17px]">
                    {STAGES[stage].body}
                  </p>
                </motion.div>
              </AnimatePresence>
            </div>
            <Rail p={p} />
          </div>

          <Monitor p={p} />
        </div>
      </div>
    </section>
  );
}

// The stage number, huge and faint behind everything, swapped with a
// vertical roll -- the title-card counter.
function BigNumber({ stage }: { stage: number }) {
  return (
    <div aria-hidden className="pointer-events-none absolute -left-4 bottom-[-6vh] select-none overflow-hidden md:left-[2vw]">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={stage}
          className="block font-[family-name:var(--font-oswald)] font-bold text-[42vh] leading-none text-white/[0.035]"
          initial={{ y: "60%" }}
          animate={{ y: "0%" }}
          exit={{ y: "-60%" }}
          transition={{ duration: 0.8, ease: [0.77, 0, 0.18, 1] }}
        >
          {String(stage + 1).padStart(2, "0")}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}

function Rail({ p }: { p: MotionValue<number> }) {
  const fill = useTransform(p, [0, 1], [0, 1]);
  return (
    <div className="mt-6 hidden md:block">
      <div className="relative h-px w-full max-w-[360px] bg-border">
        <motion.span className="absolute inset-0 origin-left bg-[var(--signal)]" style={{ scaleX: fill }} />
      </div>
      <ol className="mt-4 grid max-w-[360px] grid-cols-4 gap-2">
        {STAGES.map((s, i) => (
          <RailLabel key={s.title} p={p} i={i} label={s.title} />
        ))}
      </ol>
    </div>
  );
}

function RailLabel({ p, i, label }: { p: MotionValue<number>; i: number; label: string }) {
  const n = STAGES.length;
  const opacity = useTransform(p, [i / n - 0.02, i / n + 0.02, (i + 1) / n - 0.02, (i + 1) / n + 0.02], [0.35, 1, 1, 0.35]);
  return (
    <motion.li style={{ opacity }} className="text-[11px] leading-snug text-[#c6c4c0]">
      {label}
    </motion.li>
  );
}

// The screen the four beats play on.
function Monitor({ p }: { p: MotionValue<number> }) {
  const rotateY = useTransform(p, [0, 1], [-10, 6]);
  const rotateX = useTransform(p, [0, 1], [6, -2]);
  return (
    <div className="[perspective:1400px]">
      <motion.div
        style={{ rotateY, rotateX }}
        className="relative aspect-[4/3] w-full overflow-hidden rounded-[22px] border border-white/[0.14] bg-[#0b0a09] shadow-[0_40px_120px_-30px_rgba(0,0,0,0.9)] max-md:aspect-[4/5] md:aspect-[16/11]"
      >
        <div aria-hidden className="hero-grid absolute inset-0 opacity-60" />
        <TopBar p={p} />
        <SparkLayer p={p} />
        <SceneLayer p={p} />
        <FrameLayer p={p} />
      </motion.div>
    </div>
  );
}

function TopBar({ p }: { p: MotionValue<number> }) {
  const time = useTransform(p, (v) => {
    const t = Math.max(0, (v - 0.75) / 0.25) * 9;
    return `00:00:${String(Math.floor(t)).padStart(2, "0")}:${String(Math.floor((t % 1) * 24)).padStart(2, "0")}`;
  });
  const rec = useTransform(p, [0.74, 0.76], [0, 1]);
  return (
    <div className="absolute inset-x-0 top-0 z-20 flex items-center justify-between border-b border-white/[0.08] px-4 py-2.5">
      <span className="flex gap-1.5">
        {[0, 1, 2].map((i) => (
          <span key={i} className="size-2 rounded-full bg-white/15" />
        ))}
      </span>
      <span className="eyebrow flex items-center gap-2 tabular-nums text-white/60">
        <motion.span style={{ opacity: rec }} className="flex">
          <span className="size-1.5 animate-pulse rounded-full bg-[var(--signal)]" />
        </motion.span>
        <motion.span>{time}</motion.span>
      </span>
    </div>
  );
}

// 01 -- the spark is typed, one character per sliver of scroll.
function SparkLayer({ p }: { p: MotionValue<number> }) {
  const typed = useTransform(p, (v) => SPARK.slice(0, Math.round(Math.min(1, Math.max(0, (v - 0.02) / 0.17)) * SPARK.length)));
  const opacity = useTransform(p, [0, 0.03, 0.24, 0.3], [0, 1, 1, 0]);
  const y = useTransform(p, [0.22, 0.3], [0, -60]);
  const scale = useTransform(p, [0.22, 0.3], [1, 0.9]);
  return (
    <motion.div style={{ opacity, y, scale }} className="absolute inset-0 z-10 flex items-center justify-center px-6">
      <div className="w-full max-w-[460px] rounded-2xl border border-white/15 bg-card/90 p-2 pl-4 shadow-2xl backdrop-blur">
        <span className="eyebrow text-white/45">What do you want to create?</span>
        <div className="flex items-center gap-3 py-2">
          <p className="min-h-[3em] flex-1 text-[15px] leading-normal text-foreground">
            <motion.span>{typed}</motion.span>
            <span className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[3px] animate-pulse bg-[var(--signal)]" />
          </p>
          <span className="shrink-0 self-end rounded-lg bg-foreground px-3 py-2 text-xs font-medium text-background">Create</span>
        </div>
      </div>
    </motion.div>
  );
}

// 02 -- the scene arrives as timed shots, and its references fly in.
function SceneLayer({ p }: { p: MotionValue<number> }) {
  const opacity = useTransform(p, [0.25, 0.3, 0.49, 0.55], [0, 1, 1, 0]);
  return (
    <motion.div style={{ opacity }} className="absolute inset-0 z-10 grid grid-cols-[1fr_auto] gap-4 px-5 pb-5 pt-14 md:px-7 md:pt-16">
      <div className="flex flex-col gap-2.5">
        <span className="eyebrow text-white/45">Scene · 3 shots · 9s</span>
        {SHOTS.map(([window, line], i) => (
          <ShotLine key={window} p={p} i={i} window={window} line={line} />
        ))}
      </div>
      <div className="flex flex-col gap-2.5">
        <span className="eyebrow text-white/45">Refs</span>
        {REFS.map((m, i) => (
          <RefCard key={m.concept} p={p} i={i} src={m.src} title={m.title} />
        ))}
      </div>
    </motion.div>
  );
}

function ShotLine({ p, i, window, line }: { p: MotionValue<number>; i: number; window: string; line: string }) {
  const a = 0.29 + i * 0.045;
  const clip = useTransform(p, [a, a + 0.05], ["inset(0% 100% 0% 0%)", "inset(0% 0% 0% 0%)"]);
  const x = useTransform(p, [a, a + 0.05], [-16, 0]);
  return (
    <motion.div style={{ clipPath: clip, x }} className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
      <span className="eyebrow text-[var(--signal)]">({window})</span>
      <p className="mt-1 text-[13px] leading-snug text-[#d9d7d3] md:text-[14px]">{line}</p>
    </motion.div>
  );
}

function RefCard({ p, i, src, title }: { p: MotionValue<number>; i: number; src: string; title: string }) {
  const a = 0.31 + i * 0.05;
  const x = useTransform(p, [a, a + 0.06], [140, 0]);
  const rotate = useTransform(p, [a, a + 0.06], [14, i % 2 ? -3 : 3]);
  const o = useTransform(p, [a, a + 0.03], [0, 1]);
  return (
    <motion.div
      style={{ x, rotate, opacity: o }}
      className="relative aspect-[9/16] w-[64px] overflow-hidden rounded-lg border border-white/20 shadow-xl md:w-[84px]"
    >
      <Image src={src} alt={title} fill sizes="84px" quality={75} className="object-cover" />
    </motion.div>
  );
}

// 03 + 04 -- the keyframe is drawn top to bottom under a scanline, then
// it plays: a slow push-in and a playhead walking three shot segments.
function FrameLayer({ p }: { p: MotionValue<number> }) {
  const opacity = useTransform(p, [0.5, 0.54], [0, 1]);
  const draw = useTransform(p, [0.54, 0.72], ["inset(0% 0% 100% 0%)", "inset(0% 0% 0% 0%)"]);
  const scan = useTransform(p, [0.54, 0.72], ["0%", "100%"]);
  const scanOpacity = useTransform(p, [0.53, 0.55, 0.71, 0.73], [0, 1, 1, 0]);
  const push = useTransform(p, [0.75, 1], [1, 1.18]);
  const grade = useTransform(p, [0.54, 0.72], ["grayscale(1) contrast(1.4) brightness(0.7)", "grayscale(0) contrast(1) brightness(1)"]);
  const tlOpacity = useTransform(p, [0.74, 0.78], [0, 1]);
  const tlY = useTransform(p, [0.74, 0.78], [20, 0]);
  const head = useTransform(p, [0.78, 0.99], ["0%", "100%"]);
  const label = useTransform<number, string>(p, (v) => (v < 0.74 ? "Keyframe · shot 1 of 3" : "Rendering · shot by shot"));

  return (
    <motion.div style={{ opacity }} className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 px-5 pb-5 pt-14">
      <div className="relative aspect-[9/16] h-[70%] overflow-hidden rounded-xl border border-white/15 bg-black md:h-[66%]">
        <div aria-hidden className="absolute inset-0 bg-[repeating-linear-gradient(0deg,rgba(255,255,255,0.04)_0_1px,transparent_1px_6px)]" />
        <motion.div style={{ clipPath: draw }} className="absolute inset-0">
          <motion.div style={{ scale: push, filter: grade }} className="absolute inset-0">
            <Image src={KEYFRAME.src} alt={KEYFRAME.title} fill sizes="260px" quality={75} className="object-cover" />
          </motion.div>
        </motion.div>
        <motion.span
          aria-hidden
          style={{ top: scan, opacity: scanOpacity }}
          className="absolute inset-x-0 h-[2px] -translate-y-1/2 bg-[var(--signal)] shadow-[0_0_24px_6px_var(--signal)]"
        />
        <motion.span className="eyebrow absolute bottom-2.5 left-2.5 right-2.5 truncate text-[10px] text-white/75 md:text-xs">{label}</motion.span>
      </div>

      <motion.div style={{ opacity: tlOpacity, y: tlY }} className="w-full max-w-[420px]">
        <div className="relative flex h-7 gap-1">
          {SHOTS.map(([w]) => (
            <span key={w} className="flex flex-1 items-center rounded-md border border-white/10 bg-white/[0.06] px-2">
              <span className="eyebrow text-[10px] text-white/50">{w}</span>
            </span>
          ))}
          <motion.span
            aria-hidden
            style={{ left: head }}
            className="absolute -bottom-1 -top-1 w-[2px] -translate-x-1/2 rounded bg-[var(--signal)] shadow-[0_0_12px_2px_var(--signal)]"
          />
        </div>
      </motion.div>
    </motion.div>
  );
}

function StaticPipeline() {
  return (
    <section id="pipeline" aria-label="How a spark becomes a clip" className="border-t border-border">
      <div className="mx-auto max-w-[1200px] px-6 py-24">
        <span className="eyebrow">From spark to clip</span>
        <div className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {STAGES.map((s, i) => (
            <article key={s.title} className="rounded-[14px] border border-border bg-card p-6">
              <span className="eyebrow">{String(i + 1).padStart(2, "0")}</span>
              <h3 className="serif mt-6 text-2xl">{s.title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-[#afafaf]">{s.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

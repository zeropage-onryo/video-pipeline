"use client";

/* The assistant's face: the mascot (2026-10-08, docs/ASSISTANT_AVATARS.md;
   the data is lib/mascot.ts).

   One component draws the chosen creature in every state the assistant
   can be in. A state is a MOOD -- one of seven pre-rendered images -- plus
   a small body move:

     idle       awake, floating                   (nothing is happening)
     listening  listen, leaning in                (the box has text)
     thinking   think, floating faster            (a turn is out)
     working    think, with a ring that fills     (a tool / job is running)
     talking    talk and awake in turn: lip-flap  (a reply is being written)
     needs      awake, still, a steady amber light (something waits on a click)
     success    made, one hop                     (a turn or job just landed)
     error      oops, one shake                   (a turn failed)
     sleeping   sleep, breathing slowly, a z      (nobody has touched it in a while)

   Beside the state, a count (`badge`): answers that landed while the card
   was shut, until it is opened again.

   All seven moods are stacked and cross-faded, so a change of state never
   waits on a download (the browser fetches the seven ~8 KB images with the
   first one). The tiny size draws only the awake image. Every move is CSS
   (assistant-avatar.css) and stops under prefers-reduced-motion, where a
   talking face simply shows its open mouth. */
/* eslint-disable @next/next/no-img-element -- fixed-size transparent WebPs off R2, already sized per use */
import { useEffect, useState, type CSSProperties } from "react";
import { useReducedMotion } from "motion/react";
import { MOODS, decodeMascot, mascotSrc, moodFor, sizeFor, type FaceState } from "@/lib/mascot";
import "@/components/studio/assistant-avatar.css";

export { DEFAULT_AVATAR } from "@/lib/mascot";

export type AvatarState = FaceState;

/* the order the setup screen's preview walks through them */
export const AVATAR_STATES: AvatarState[] = [
  "idle",
  "listening",
  "thinking",
  "talking",
  "working",
  "needs",
  "success",
  "error",
  "sleeping",
];

export const STATE_LABEL: Record<AvatarState, string> = {
  idle: "Ready",
  listening: "Listening",
  thinking: "Thinking",
  working: "Working",
  talking: "Answering",
  needs: "Needs you",
  success: "Done",
  error: "Didn't go through",
  sleeping: "Resting",
};

/* how fast the mouth flaps while a reply is written: open, shut, open */
const FLAP_MS = 160;

type Size = "xs" | "sm" | "md" | "lg" | "xl";
const PX: Record<Size, number> = { xs: 18, sm: 32, md: 56, lg: 60, xl: 96 };

export function AssistantAvatar({
  avatar,
  state = "idle",
  progress,
  badge = 0,
  size = "md",
  title,
  className = "",
}: {
  avatar: string | null | undefined;
  state?: AvatarState;
  /* 0..1 fills the working ring; absent = an indeterminate sweep */
  progress?: number;
  /* unread answers; 0 draws nothing, past 9 reads "9+" */
  badge?: number;
  size?: Size;
  title?: string;
  className?: string;
}) {
  const mascot = decodeMascot(avatar);
  const px = PX[size];
  const reduce = useReducedMotion();
  const flapping = state === "talking" && !reduce && size !== "xs";
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (!flapping) return;
    const t = setInterval(() => setOpen((o) => !o), FLAP_MS);
    return () => clearInterval(t);
  }, [flapping]);
  const mood = moodFor(state, flapping ? open : true);
  const res = sizeFor(px);
  const moods = size === "xs" ? (["awake"] as const) : MOODS;
  const p = progress == null ? null : Math.max(0, Math.min(1, progress));
  const style = { "--zav": `${px}px`, "--zav-p": p ?? 0.28 } as CSSProperties;
  return (
    <span
      className={`zav ${className}`}
      data-state={state}
      data-size={size}
      data-mood={mood}
      data-progress={p == null ? "sweep" : "known"}
      style={style}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      {size !== "xs" && state === "working" ? <Ring /> : null}
      <span className="zav-fig">
        {moods.map((m) => (
          <img
            key={m}
            src={mascotSrc(mascot, m, res)}
            alt=""
            draggable={false}
            decoding="async"
            data-on={m === mood || size === "xs" ? "" : undefined}
          />
        ))}
      </span>
      {size !== "xs" ? (
        <>
          <span className="zav-tally" />
          <span className="zav-z">z</span>
          {badge > 0 ? (
            <span className="zav-badge" key={badge} aria-hidden>
              {badge > 9 ? "9+" : badge}
            </span>
          ) : null}
        </>
      ) : null}
    </span>
  );
}

/* A picker's still: one creature, one look, one colour, awake. Used where
   many are shown at once, so it loads one image, not seven. */
export function MascotStill({ avatar, px, className = "" }: { avatar: string; px: number; className?: string }) {
  return (
    <img
      className={`zav-still ${className}`}
      src={mascotSrc(decodeMascot(avatar), "awake", sizeFor(px))}
      alt=""
      width={px}
      height={px}
      draggable={false}
      decoding="async"
      loading="lazy"
    />
  );
}

/* the progress ring, drawn only while a tool or job is working */
function Ring() {
  return (
    <svg className="zav-ring" viewBox="0 0 100 100" aria-hidden>
      <circle className="zav-track" cx="50" cy="50" r="46" />
      <circle className="zav-arc" cx="50" cy="50" r="46" pathLength="100" />
    </svg>
  );
}

"use client";

/* The assistant's face (2026-10-07 mock, docs/ASSISTANT_AVATARS.md).

   One component draws every look the person can pick in "Meet your
   assistant", and every state the assistant can be in:

     idle       slow breathing                    (nothing is happening)
     listening  leans in, ring follows the typing (the box has text)
     thinking   the glyph's own "pondering" move  (a turn is out)
     working    sprocket ring fills with progress (a tool / job is running)
     needs      steady amber tally, no loop       (something waits on a click)
     success    one flash + a check, ~1.2s        (a turn or job just landed)
     error      one shake, red notch              (a turn failed)
     sleeping   dimmed, slowed, a small z         (nobody has touched it in a while)

   "Needs you" is the loudest state and it does NOT animate: a steady
   light reads louder than another loop on a page full of motion. States
   differ in shape as well as colour, so they read without the colour.

   A look is either an emoji ("🦊") or a built-in glyph ("glyph:aperture").
   The glyph ids fit the server's avatar column (assistant_store.clean_avatar:
   16 chars, no brackets or quotes), so nothing on the server changes.
   Every animation is CSS (assistant-avatar.css) and stops under
   prefers-reduced-motion. */
import type { CSSProperties } from "react";
import "@/components/studio/assistant-avatar.css";

export type AvatarState =
  | "idle"
  | "listening"
  | "thinking"
  | "working"
  | "needs"
  | "success"
  | "error"
  | "sleeping";

export const AVATAR_STATES: AvatarState[] = [
  "idle",
  "listening",
  "thinking",
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
  needs: "Needs you",
  success: "Done",
  error: "Didn't go through",
  sleeping: "Resting",
};

export type GlyphId =
  | "aperture"
  | "clapper"
  | "reel"
  | "lens"
  | "tally"
  | "megaphone"
  | "spot"
  | "finder";

/* the order the setup screen shows them in; aperture is the house look */
export const GLYPHS: { id: GlyphId; label: string; note: string }[] = [
  { id: "aperture", label: "Iris", note: "Closes to think, opens when it lands" },
  { id: "clapper", label: "Slate", note: "Claps on every take that lands" },
  { id: "reel", label: "Reel", note: "Spins while a job runs" },
  { id: "lens", label: "Lens", note: "A flare drifts across while it thinks" },
  { id: "tally", label: "Tally", note: "A camera's tally light, nothing more" },
  { id: "megaphone", label: "Director", note: "Calls it out" },
  { id: "spot", label: "Spot", note: "A beam that sweeps while it looks" },
  { id: "finder", label: "Finder", note: "A viewfinder that frames up" },
];

/* film-flavoured emoji for the "Look" row, after the glyphs */
export const EMOJI_SKINS = ["🎬", "🎥", "📽️", "🎞️", "📣", "🦊", "🤖", "👾", "🐺"];

export const GLYPH_PREFIX = "glyph:";
export const glyphAvatar = (id: GlyphId) => `${GLYPH_PREFIX}${id}`;
export const DEFAULT_AVATAR = glyphAvatar("aperture");

export function glyphOf(avatar: string | null | undefined): GlyphId | null {
  if (!avatar?.startsWith(GLYPH_PREFIX)) return null;
  const id = avatar.slice(GLYPH_PREFIX.length);
  return GLYPHS.some((g) => g.id === id) ? (id as GlyphId) : null;
}

/* what to put in a line of TEXT (e.g. "🎬 Filled by Nova"): an emoji is
   itself, a glyph has no text form */
export function avatarText(avatar: string | null | undefined): string {
  return avatar && !avatar.startsWith(GLYPH_PREFIX) ? avatar : "";
}

type Size = "xs" | "sm" | "md" | "lg" | "xl";
const PX: Record<Size, number> = { xs: 18, sm: 32, md: 56, lg: 60, xl: 96 };

export function AssistantAvatar({
  avatar,
  state = "idle",
  progress,
  size = "md",
  title,
  className = "",
}: {
  avatar: string | null | undefined;
  state?: AvatarState;
  /* 0..1 fills the working ring; absent = an indeterminate sweep */
  progress?: number;
  size?: Size;
  title?: string;
  className?: string;
}) {
  const glyph = glyphOf(avatar);
  const px = PX[size];
  const p = progress == null ? null : Math.max(0, Math.min(1, progress));
  const style = { "--zav": `${px}px`, "--zav-p": p ?? 0.28 } as CSSProperties;
  return (
    <span
      className={`zav ${className}`}
      data-state={state}
      data-size={size}
      data-glyph={glyph ?? "emoji"}
      data-progress={p == null ? "sweep" : "known"}
      style={style}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      {size !== "xs" ? <Ring /> : null}
      <span className="zav-face">
        {glyph ? <Glyph id={glyph} /> : <span className="zav-emoji">{avatar || "✦"}</span>}
      </span>
      {size !== "xs" ? (
        <>
          <span className="zav-tally" />
          <svg className="zav-check" viewBox="0 0 24 24" aria-hidden>
            <path d="M6 12.5l4 4 8-9" />
          </svg>
          <span className="zav-z">z</span>
        </>
      ) : null}
    </span>
  );
}

/* the outer ring: sprocket holes at rest, a progress arc while working,
   amber while it needs you, a red notch on error */
function Ring() {
  return (
    <svg className="zav-ring" viewBox="0 0 100 100" aria-hidden>
      <circle className="zav-track" cx="50" cy="50" r="46" />
      <circle className="zav-holes" cx="50" cy="50" r="46" pathLength="100" />
      <circle className="zav-arc" cx="50" cy="50" r="46" pathLength="100" />
      <path className="zav-notch" d="M50 2 v9" />
    </svg>
  );
}

function Glyph({ id }: { id: GlyphId }) {
  switch (id) {
    case "aperture":
      return (
        <svg className="zg zg-aperture" viewBox="0 0 48 48" aria-hidden>
          <circle className="zg-rim" cx="24" cy="24" r="20" />
          <g className="zg-blades">
            {[0, 60, 120, 180, 240, 300].map((r) => (
              <path key={r} transform={`rotate(${r} 24 24)`} d="M24 4 L33 19 L24 24 Z" />
            ))}
          </g>
          <circle className="zg-pupil" cx="24" cy="24" r="5" />
        </svg>
      );
    case "clapper":
      return (
        <svg className="zg zg-clapper" viewBox="0 0 48 48" aria-hidden>
          <rect className="zg-board" x="8" y="20" width="32" height="20" rx="3" />
          <g className="zg-stick">
            <rect x="8" y="12" width="32" height="7" rx="2" />
            <path className="zg-stripes" d="M13 12 l-4 7 M21 12 l-4 7 M29 12 l-4 7 M37 12 l-4 7" />
          </g>
          <path className="zg-lines" d="M13 27 h16 M13 33 h10" />
        </svg>
      );
    case "reel":
      return (
        <svg className="zg zg-reel" viewBox="0 0 48 48" aria-hidden>
          <g className="zg-spin">
            <circle className="zg-rim" cx="24" cy="24" r="19" />
            {[0, 72, 144, 216, 288].map((r) => (
              <circle key={r} className="zg-hole" cx="24" cy="12" r="4.2" transform={`rotate(${r} 24 24)`} />
            ))}
            <circle className="zg-hub" cx="24" cy="24" r="3" />
          </g>
        </svg>
      );
    case "lens":
      return (
        <svg className="zg zg-lens" viewBox="0 0 48 48" aria-hidden>
          <defs>
            <radialGradient id="zg-lens-glass" cx="38%" cy="34%" r="70%">
              <stop offset="0" stopColor="#5b6170" />
              <stop offset=".55" stopColor="#14161b" />
              <stop offset="1" stopColor="#050506" />
            </radialGradient>
          </defs>
          <circle cx="24" cy="24" r="19" fill="url(#zg-lens-glass)" className="zg-glass" />
          <circle className="zg-rim" cx="24" cy="24" r="19" />
          <circle className="zg-rim thin" cx="24" cy="24" r="12" />
          <g className="zg-flare">
            <circle cx="17" cy="17" r="3.4" />
            <circle cx="29" cy="29" r="1.6" />
          </g>
        </svg>
      );
    case "tally":
      return (
        <svg className="zg zg-tally" viewBox="0 0 48 48" aria-hidden>
          <rect className="zg-body" x="11" y="11" width="26" height="26" rx="8" />
          <circle className="zg-light" cx="24" cy="24" r="7" />
        </svg>
      );
    case "megaphone":
      return (
        <svg className="zg zg-megaphone" viewBox="0 0 48 48" aria-hidden>
          <path className="zg-horn" d="M9 21 v6 h6 l14 8 V13 l-14 8 Z" />
          <path className="zg-grip" d="M15 27 l2 8 h4 l-2-8" />
          <g className="zg-waves">
            <path d="M34 19 q4 5 0 10" />
            <path d="M38 15 q7 9 0 18" />
          </g>
        </svg>
      );
    case "spot":
      return (
        <svg className="zg zg-spot" viewBox="0 0 48 48" aria-hidden>
          <g className="zg-beamwrap">
            <path className="zg-beam" d="M18 14 L4 44 H32 Z" />
          </g>
          <rect className="zg-can" x="14" y="6" width="12" height="10" rx="2" transform="rotate(-18 20 11)" />
          <circle className="zg-pin" cx="34" cy="10" r="2" />
        </svg>
      );
    case "finder":
      return (
        <svg className="zg zg-finder" viewBox="0 0 48 48" aria-hidden>
          <g className="zg-corners">
            <path d="M8 16 V8 h8" />
            <path d="M32 8 h8 v8" />
            <path d="M40 32 v8 h-8" />
            <path d="M16 40 H8 v-8" />
          </g>
          <circle className="zg-rec" cx="24" cy="24" r="4" />
        </svg>
      );
  }
}

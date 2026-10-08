// A /make page's accent (2026-10-05): the handful of colours a page owns,
// published as CSS variables on the page's skin wrapper so every section
// reads them through the same `var(--…)` the light tone declares. A page
// changes its accent by changing an entry, never by forking a component.
//
// `RED` is byte for byte what `.editorial-light` in globals.css declared
// before the accent existed, so the Ad Generator page is unchanged by it.
import type { CSSProperties } from "react";

export type MakeAccent = {
  /** The button fill, the focus ring, text selection. */
  primary: string;
  /** Type on the button. */
  primaryForeground: string;
  /** A card's resting outline. */
  cardLine: string;
  /** A card's hover outline, the FAQ question's hover colour. */
  lineHover: string;
  /** The soft light that follows the pointer across a feature card. */
  cardLight: string;
  /** The two gradient plates a wall tile draws when it has no still. */
  plates: [string, string];
};

export const RED: MakeAccent = {
  primary: "#e4002b",
  primaryForeground: "#ffffff",
  cardLine: "#f2b9c3",
  lineHover: "#e4002b",
  cardLight: "rgba(0,0,0,0.06)",
  plates: [
    "linear-gradient(135deg, #f6d7a6 0%, #e9a67f 55%, #d78a8a 100%)",
    "linear-gradient(135deg, #cfe3f2 0%, #e8c9a8 50%, #b9d9a3 100%)",
  ],
};

// The Seedance page's accent (2026-10-05): an electric indigo on the same
// white ground. #4338ca on white is 8.1:1; the pale outline is the same hue
// at a tint. The plates are the cool, cinematic half of the wall.
export const INDIGO: MakeAccent = {
  primary: "#4338ca",
  primaryForeground: "#ffffff",
  cardLine: "#c9c5f3",
  lineHover: "#4338ca",
  cardLight: "rgba(67,56,202,0.08)",
  plates: [
    "linear-gradient(135deg, #e0e7ff 0%, #a5b4fc 55%, #6366f1 100%)",
    "linear-gradient(135deg, #cffafe 0%, #a5f3fc 50%, #818cf8 100%)",
  ],
};

// The four model pages' accents (2026-10-05), each checked against white:
// emerald 5.5:1, amber 4.6:1, rose 5.9:1, blue 6.3:1.
export const EMERALD: MakeAccent = {
  primary: "#047857",
  primaryForeground: "#ffffff",
  cardLine: "#b7e4cf",
  lineHover: "#047857",
  cardLight: "rgba(4,120,87,0.08)",
  plates: [
    "linear-gradient(135deg, #ecfdf5 0%, #6ee7b7 55%, #047857 100%)",
    "linear-gradient(135deg, #f0fdfa 0%, #5eead4 50%, #115e59 100%)",
  ],
};

export const AMBER: MakeAccent = {
  primary: "#b45309",
  primaryForeground: "#ffffff",
  cardLine: "#f5d3a8",
  lineHover: "#b45309",
  cardLight: "rgba(180,83,9,0.08)",
  plates: [
    "linear-gradient(135deg, #fffbeb 0%, #fcd34d 55%, #b45309 100%)",
    "linear-gradient(135deg, #fff7ed 0%, #fdba74 50%, #9a3412 100%)",
  ],
};

export const ROSE: MakeAccent = {
  primary: "#be185d",
  primaryForeground: "#ffffff",
  cardLine: "#f6bdd3",
  lineHover: "#be185d",
  cardLight: "rgba(190,24,93,0.08)",
  plates: [
    "linear-gradient(135deg, #fdf2f8 0%, #f9a8d4 55%, #be185d 100%)",
    "linear-gradient(135deg, #fff1f2 0%, #fda4af 50%, #9f1239 100%)",
  ],
};

export const BLUE: MakeAccent = {
  primary: "#1d4ed8",
  primaryForeground: "#ffffff",
  cardLine: "#bcd0fb",
  lineHover: "#1d4ed8",
  cardLight: "rgba(29,78,216,0.08)",
  plates: [
    "linear-gradient(135deg, #eff6ff 0%, #93c5fd 55%, #1d4ed8 100%)",
    "linear-gradient(135deg, #f0f9ff 0%, #7dd3fc 50%, #1e40af 100%)",
  ],
};

export const VIOLET: MakeAccent = {
  primary: "#6d28d9",
  primaryForeground: "#ffffff",
  cardLine: "#d6c6fa",
  lineHover: "#6d28d9",
  cardLight: "rgba(109,40,217,0.08)",
  plates: [
    "linear-gradient(135deg, #f5f3ff 0%, #c4b5fd 55%, #6d28d9 100%)",
    "linear-gradient(135deg, #faf5ff 0%, #d8b4fe 50%, #5b21b6 100%)",
  ],
};

// Three more (2026-10-08) so no two model pages share a colour: the video
// pages had borrowed the image pages' emerald, amber and rose. Checked
// against white: cyan 5.4:1, orange 5.2:1, fuchsia 6.3:1.
export const CYAN: MakeAccent = {
  primary: "#0e7490",
  primaryForeground: "#ffffff",
  cardLine: "#b3e3ee",
  lineHover: "#0e7490",
  cardLight: "rgba(14,116,144,0.08)",
  plates: [
    "linear-gradient(135deg, #ecfeff 0%, #67e8f9 55%, #0e7490 100%)",
    "linear-gradient(135deg, #f0f9ff 0%, #7dd3fc 50%, #155e75 100%)",
  ],
};

export const ORANGE: MakeAccent = {
  primary: "#c2410c",
  primaryForeground: "#ffffff",
  cardLine: "#f8cdb4",
  lineHover: "#c2410c",
  cardLight: "rgba(194,65,12,0.08)",
  plates: [
    "linear-gradient(135deg, #fff7ed 0%, #fdba74 55%, #c2410c 100%)",
    "linear-gradient(135deg, #fffbeb 0%, #fca5a5 50%, #9a3412 100%)",
  ],
};

export const FUCHSIA: MakeAccent = {
  primary: "#a21caf",
  primaryForeground: "#ffffff",
  cardLine: "#efc2f3",
  lineHover: "#a21caf",
  cardLight: "rgba(162,28,175,0.08)",
  plates: [
    "linear-gradient(135deg, #fdf4ff 0%, #f0abfc 55%, #a21caf 100%)",
    "linear-gradient(135deg, #faf5ff 0%, #e879f9 50%, #86198f 100%)",
  ],
};

/** The inline variables the skin wrapper carries for `accent`. */
export function accentVars(accent: MakeAccent): CSSProperties {
  return {
    "--primary": accent.primary,
    "--primary-foreground": accent.primaryForeground,
    "--ring": accent.primary,
    "--card-line": accent.cardLine,
    "--line-hover": accent.lineHover,
    "--card-light": accent.cardLight,
    "--plate-1": accent.plates[0],
    "--plate-2": accent.plates[1],
  } as CSSProperties;
}

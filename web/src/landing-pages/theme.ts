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

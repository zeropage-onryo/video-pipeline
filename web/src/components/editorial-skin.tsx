"use client";

import { createContext, useContext, type CSSProperties, type ReactNode } from "react";

// The public site's skin, applied as a wrapper rather than on <html>:
// the root layout is shared with /studio, which keeps the noir tokens.
// `.editorial` (globals.css) re-declares every shadcn token underneath
// it -- warm black, white primary, Inter, 8px radius -- so every
// component below reads the new palette through the same class names.
// `tone="light"` adds `.editorial-light`, the same tokens inverted (white
// ground, black type) -- the /make landing pages wear it; the homepage
// and the legal pages stay dark.
//
// The tone is also published through a context, because anything that
// PORTALS to <body> (the header's Solutions panel) leaves this wrapper and
// would otherwise draw with the root's noir tokens on a white page. Such a
// portal stamps `skinClass(useTone())` onto its root.
export type Tone = "dark" | "light";

const ToneContext = createContext<Tone>("dark");

export function useTone(): Tone {
  return useContext(ToneContext);
}

/** The classes that make an element read the skin's tokens. */
export function skinClass(tone: Tone): string {
  return `editorial ${tone === "light" ? "editorial-light" : ""}`;
}

export function EditorialSkin({
  children,
  tone = "dark",
  style,
}: {
  children: ReactNode;
  tone?: Tone;
  /** A page's own CSS variables (a /make page's accent, theme.ts), laid
   *  over the tone's. Inline, so they win the cascade on this subtree only. */
  style?: CSSProperties;
}) {
  return (
    <ToneContext.Provider value={tone}>
      <div
        className={`${skinClass(tone)} flex min-h-svh flex-1 flex-col bg-background text-foreground`}
        style={style}
      >
        {children}
      </div>
    </ToneContext.Provider>
  );
}

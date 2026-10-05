import type { ComponentType } from "react";
import { ShotTimeline } from "./shot-timeline";
import type { MakePage } from "../pages";

// A page's ONE signature interaction (2026-10-05): the section that gives
// it an identity beyond copy and colour, drawn between the hero and the
// wall when the entry names it. Each is its own client component, keyed
// here; the sections every page shares stay in make-page.tsx untouched.
//
// Adding one: write the component, add it to SIGNATURES, and name the key
// on the entry. Nothing else changes.
export const SIGNATURES = {
  /** One 15-second scene scrubbed by the scroll, shot by shot (Seedance). */
  "shot-timeline": ShotTimeline,
} satisfies Record<string, ComponentType<{ page: MakePage }>>;

export type SignatureKey = keyof typeof SIGNATURES;

export function Signature({ page }: { page: MakePage }) {
  const key = page.signature;
  const Section = key ? SIGNATURES[key] : undefined;
  return Section ? <Section page={page} /> : null;
}

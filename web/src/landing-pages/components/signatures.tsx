import type { ComponentType } from "react";
import { ShotTimeline } from "./shot-timeline";
import { ReferenceStack } from "./reference-stack";
import { FramePicker } from "./frame-picker";
import { EditLoop } from "./edit-loop";
import { TypeFrame } from "./type-frame";
import { PosterType } from "./poster-type";
import { LengthDial, SoundBoard, TierPair } from "./clips";
import { AdTypes } from "./ad-types";
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
  /** Tap references into the frame; the still is held to them (Nano Banana). */
  "reference-stack": ReferenceStack,
  /** The ten frames, morphing to exact pixel sizes (FLUX). */
  "frame-picker": FramePicker,
  /** The draw and the edit under one divider (Seedream). */
  "edit-loop": EditLoop,
  /** The words set letter by letter at the model's three sizes (GPT Image). */
  "type-frame": TypeFrame,
  /** A poster whose type setting you pick (Ideogram). */
  "poster-type": PosterType,
  /** One prompt on two tiers, side by side, with sound (LTX). */
  "tier-pair": TierPair,
  /** One long clip, looped at the length a slider picks (Wan). */
  "length-dial": LengthDial,
  /** Clips whose sound is the point, one heard at a time (Veo). */
  "sound-board": SoundBoard,
  /** One product photo, six ad formats, each with how it was drawn (GPT Image 2.5). */
  "ad-types": AdTypes,
} satisfies Record<string, ComponentType<{ page: MakePage }>>;

export type SignatureKey = keyof typeof SIGNATURES;

export function Signature({ page }: { page: MakePage }) {
  const key = page.signature;
  const Section = key ? SIGNATURES[key] : undefined;
  return Section ? <Section page={page} /> : null;
}

// The frames the landing page shows. Every entry is REAL studio output --
// a keyframe Nano drew for a concept on the board, served from R2 -- never
// stock or a fabricated still. Newest first, one per concept, read off the
// bucket on 2026-09-14 (`renders/nano/c<id>-<stamp>.png`).
//
// A `video` URL, when a concept has a rendered clip, turns the tile into a
// muted loop with the still as its poster; nothing else changes. The bucket
// held zero clips on 2026-09-14, so every entry is a still for now.

const R2 = "https://pub-62d6d70ed50d44449d464cd43245b69d.r2.dev/renders/nano";

export type LandingMedia = {
  concept: number;
  title: string;
  src: string;
  video?: string;
  width: number;
  height: number;
};

// Nano's stills are 768x1344 (9:16).
const STILL = { width: 768, height: 1344 };

export const LANDING_MEDIA: LandingMedia[] = [
  { concept: 361, title: "The Crimson Descent", src: `${R2}/c361-20260911-161358.png`, ...STILL },
  { concept: 351, title: "The Last Breath", src: `${R2}/c351-20260910-135712.png`, ...STILL },
  { concept: 353, title: "The Crimson Path", src: `${R2}/c353-20260909-181442.png`, ...STILL },
  { concept: 348, title: "The Final Check", src: `${R2}/c348-20260908-073120.png`, ...STILL },
  { concept: 265, title: "The Infinite Loop", src: `${R2}/c265-20260907-024101.png`, ...STILL },
  { concept: 264, title: "Frozen Checkpoint", src: `${R2}/c264-20260907-023841.png`, ...STILL },
  { concept: 262, title: "Silent Sector Plea", src: `${R2}/c262-20260907-020957.png`, ...STILL },
  { concept: 261, title: "Bio-Digital Erasure", src: `${R2}/c261-20260907-020707.png`, ...STILL },
];

// The recording under the hero headline: the studio being driven, in a
// rounded frame. Mike supplies it (2026-09-18: "Real Studio recording --
// I'll provide it"); until `video` is set the frame shows `poster` -- a
// real screenshot of the product -- or, with neither, three real keyframes
// off the board (landing-media.ts). Never a mock-up. Put the mp4 on R2 and point `video` at it; `poster` is the
// still shown before playback and under reduced motion.
export type HeroMedia = {
  video?: string;
  poster?: string;
  alt: string;
};

export const HERO_MEDIA: HeroMedia = {
  // The Pipeline board (Mike's screenshot, 2026-09-18) stands in as the
  // poster until the recording lands; the frame plays `video` over it.
  poster: "/site/studio-pipeline.webp",
  alt: "The Zero Page studio turning a spark into a rendered scene.",
};

// The four beats the recording walks through, in order. The strip under
// the frame fills each one in turn on a 12s loop.
export const HERO_STEPS = ["Bring a spark", "Write the scene", "Pick the frame", "Render the clip"];

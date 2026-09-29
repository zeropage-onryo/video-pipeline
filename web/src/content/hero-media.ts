// The four beats under the hero headline. Each one is a real recording of
// the studio being driven (Mike's screen captures, 2026-09-24), cropped
// free of browser chrome and cut to 3 seconds -- never a mock-up. The
// strip under the frame is the control: clicking a beat plays it, and the
// underline fills with that clip's own playback.
//
// Two encodes per beat, VP9 first and H.264 behind it: a browser takes the
// first source it can decode, and a Chromium without the proprietary codec
// (every headless build this project screenshots with) shows a broken
// frame on an mp4 alone.
//
// `poster` is the clip's first frame. It is what shows before the video
// can play, while it loads, and under reduced motion, where the frame
// stays a still.
export type HeroStep = {
  label: string;
  webm: string;
  mp4: string;
  poster: string;
  alt: string;
};

export const HERO_STEPS: HeroStep[] = [
  {
    label: "Bring a spark",
    webm: "/site/hero/spark.webm",
    mp4: "/site/hero/spark.mp4",
    poster: "/site/hero/spark.webp",
    alt: "An idea typed into the studio composer.",
  },
  {
    label: "Write the scene",
    webm: "/site/hero/scene.webm",
    mp4: "/site/hero/scene.mp4",
    poster: "/site/hero/scene.webp",
    alt: "The scene's prompt, references and renderer on the Director canvas.",
  },
  {
    label: "Pick the frame",
    webm: "/site/hero/frame.webm",
    mp4: "/site/hero/frame.mp4",
    poster: "/site/hero/frame.webp",
    alt: "Concepts on the Pipeline board, each with the frames behind it.",
  },
  {
    label: "Render the clip",
    webm: "/site/hero/clip.webm",
    mp4: "/site/hero/clip.mp4",
    poster: "/site/hero/clip.webp",
    alt: "Rendered frames filling the studio's asset wall, newest first.",
  },
];

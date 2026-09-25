"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { HERO_STEPS } from "@/content/hero-media";

// The frame under the headline: a 16:9 plate in a 24px-radius border
// playing one beat of the studio at a time, and under it the four beats as
// a strip that both REPORTS and DRIVES it -- the underline fills with the
// clip's own playback, clicking a beat plays that one, and the end of a
// clip moves to the next. Pointing at the frame pauses it, so a viewer
// reading a card is not dragged onward.
//
// Progress is read off the video rather than run as a CSS loop: a timer
// beside a video drifts the moment one stalls, buffers or is paused, and
// the strip would then describe a beat the frame is not showing.
export function HeroMedia() {
  const [active, setActive] = useState(0);
  const [progress, setProgress] = useState(0);
  const [still, setStill] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Reduced motion keeps the poster and the strip, and drops the playback.
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setStill(query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);

  // A new beat is a new element (key), so it starts from the top on its
  // own. play() rejects when the browser blocks autoplay -- the poster is
  // the fallback, so the rejection is not an error.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || still) return;
    setProgress(0);
    video.play().catch(() => {});
  }, [active, still]);

  const step = HERO_STEPS[active];

  return (
    <div className="relative z-10 mx-auto w-full max-w-[1560px] px-4 pb-16 md:px-8">
      <div className="rounded-3xl border border-white/[0.16] bg-card p-[3px]">
        <div
          className="relative aspect-video overflow-hidden rounded-[20px] bg-[#0f0e0c]"
          onPointerEnter={() => videoRef.current?.pause()}
          onPointerLeave={() => videoRef.current?.play().catch(() => {})}
        >
          {still ? (
            <Image
              src={step.poster}
              alt={step.alt}
              fill
              sizes="(min-width: 1560px) 1496px, 100vw"
              priority
              className="object-cover"
            />
          ) : (
            <video
              key={step.mp4}
              ref={videoRef}
              className="h-full w-full object-cover"
              poster={step.poster}
              autoPlay
              muted
              playsInline
              preload="auto"
              aria-label={step.alt}
              onTimeUpdate={(event) => {
                const video = event.currentTarget;
                if (video.duration) setProgress(video.currentTime / video.duration);
              }}
              onEnded={() => setActive((i) => (i + 1) % HERO_STEPS.length)}
            >
              <source src={step.webm} type="video/webm" />
              <source src={step.mp4} type="video/mp4" />
            </video>
          )}
        </div>
      </div>

      <ol className="mt-6 grid grid-cols-2 gap-x-2 gap-y-4 sm:grid-cols-4">
        {HERO_STEPS.map((heroStep, i) => {
          const isActive = i === active;
          const fill = still ? (isActive ? 1 : 0) : isActive ? progress : i < active ? 1 : 0;
          return (
            <li key={heroStep.label}>
              <button
                type="button"
                onClick={() => setActive(i)}
                aria-current={isActive ? "step" : undefined}
                className="flex w-full cursor-pointer flex-col gap-3 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--signal)]"
              >
                <span
                  className={`text-sm font-medium tracking-[-0.005em] transition-colors ${
                    isActive ? "text-foreground" : "text-[#82807d] hover:text-foreground"
                  }`}
                >
                  {heroStep.label}
                </span>
                <span className="relative block h-px w-full bg-border">
                  <span
                    className="absolute inset-0 origin-left bg-foreground"
                    style={{
                      transform: `scaleX(${fill})`,
                      opacity: isActive ? 1 : fill ? 0.25 : 0,
                    }}
                  />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

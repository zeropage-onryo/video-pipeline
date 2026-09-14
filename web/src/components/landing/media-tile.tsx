"use client";

// One frame on the landing page, the LTX treatment: a still that drifts
// (a slow push-in) while it is on screen and tilts toward the pointer on
// hover, or -- when the entry carries a `video` -- a muted loop that plays
// only while in view, with the still as its poster. Everything motion is
// gated on motion-safe:, so reduced-motion viewers get a static frame.
//
// In-view is tracked on the element (data-inview) rather than in state:
// React's set-state-in-effect rule is on, and the CSS reads the attribute
// directly, so state would only add a render.

import Image from "next/image";
import { useEffect, useRef, type PointerEvent } from "react";
import type { LandingMedia } from "@/content/landing-media";

type Props = {
  media: LandingMedia;
  sizes: string;
  priority?: boolean;
  className?: string;
};

export function MediaTile({ media, sizes, priority, className = "" }: Props) {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const video = el.querySelector("video");
    const io = new IntersectionObserver(
      ([entry]) => {
        const seen = entry.isIntersecting;
        el.dataset.inview = seen ? "true" : "false";
        if (!video) return;
        // play() returns a promise that rejects when autoplay is blocked;
        // the poster is the fallback, so the rejection is not an error.
        if (seen) video.play().catch(() => {});
        else video.pause();
      },
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  function onMove(e: PointerEvent<HTMLDivElement>) {
    const el = root.current;
    if (!el || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--px", String(((e.clientX - r.left) / r.width - 0.5) * 2));
    el.style.setProperty("--py", String(((e.clientY - r.top) / r.height - 0.5) * 2));
  }

  function onLeave() {
    const el = root.current;
    if (!el) return;
    el.style.setProperty("--px", "0");
    el.style.setProperty("--py", "0");
  }

  return (
    <div
      ref={root}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
      className={`media-tile absolute inset-0 overflow-hidden ${className}`}
    >
      {media.video ? (
        <video
          className="media-tile__frame h-full w-full object-cover"
          src={media.video}
          poster={media.src}
          muted
          loop
          playsInline
          preload="none"
          aria-label={media.title}
        />
      ) : (
        <Image
          className="media-tile__frame object-cover"
          src={media.src}
          alt={media.title}
          fill
          sizes={sizes}
          priority={priority}
          quality={70}
        />
      )}
    </div>
  );
}

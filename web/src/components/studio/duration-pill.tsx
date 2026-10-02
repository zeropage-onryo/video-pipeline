"use client";

/* How long the scene is, as a SLIDER (2026-10-02, Mike: "you can toggle it
   like a slider and choose any amount of time"). It replaced a menu of five
   lengths (5 / 10 / 15 / 20 / 30s): the scene is cut into as many shots as
   its idea needs, and a fixed menu of totals was the wrong control for
   that. Any whole second from the route's `min` to `max` (GET
   /api/scene-lengths, timeline.MIN/MAX_SCENE_SECONDS), which is exactly
   what timeline.scene_seconds will take -- it clamps, so the slider and the
   server cannot disagree about a legal length.

   Its own component so each composer draws its own trigger (the page's
   `.pill`, Direction A's `.zc-tool`) around the same popover. The value
   moves while dragging; nothing is sent until Create. */
import { useEffect, useId, useRef, useState } from "react";

export type SceneLengths = { min: number; max: number; default: number };

export function DurationPill({
  seconds,
  span,
  onChange,
  trigger,
  end,
}: {
  seconds: number;
  span: SceneLengths;
  onChange: (seconds: number) => void;
  trigger: (open: boolean) => React.ReactNode;
  end?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", off);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", off);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const value = Math.min(span.max, Math.max(span.min, seconds || span.default));
  // the filled share of the track, for the CSS gradient
  const filled = span.max > span.min ? ((value - span.min) / (span.max - span.min)) * 100 : 100;
  return (
    <span className="pillwrap" ref={box}>
      <span onClick={() => setOpen((v) => !v)}>{trigger(open)}</span>
      {open ? (
        <span className={`pillmenu durationmenu${end ? " end" : ""}`} role="dialog" aria-labelledby={id}>
          <span className="m" id={id}>
            Choose duration
          </span>
          <span className="durationrow">
            <input
              type="range"
              min={span.min}
              max={span.max}
              step={1}
              value={value}
              aria-labelledby={id}
              aria-valuetext={`${value} seconds`}
              style={{ "--filled": `${filled}%` } as React.CSSProperties}
              onChange={(e) => onChange(Number(e.target.value))}
              autoFocus
            />
            <output aria-live="polite">{value}s</output>
          </span>
          <span className="durationends" aria-hidden="true">
            <span>{span.min}s</span>
            <span>{span.max}s</span>
          </span>
        </span>
      ) : null}
    </span>
  );
}

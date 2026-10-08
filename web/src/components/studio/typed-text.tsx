"use client";

/* An answer as it is written (2026-10-08): catches up with what the job
   has said so far a few characters a frame (lib/assistant-text.ts
   typeAhead), so a poll's worth of words reads as typing rather than as a
   jump, and ends in a caret. Shown whole under reduced motion. Shared by
   the assistant pill's card and the Studio composer's stream; each passes
   its own caret class, since their stylesheets are prefixed apart. */
import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { typeAhead } from "@/lib/assistant-text";

export function TypedText({ text, caret }: { text: string; caret: string }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState("");
  // what is on screen, read by the frame loop (a state updater runs when
  // React renders, too late to decide whether to ask for another frame)
  const at = useRef("");
  useEffect(() => {
    if (reduce) return;
    let raf = 0;
    const tick = () => {
      const next = typeAhead(at.current, text);
      if (next !== at.current) {
        at.current = next;
        setShown(next);
      }
      if (next.length < text.length) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [text, reduce]);
  return (
    <>
      {reduce ? text : shown}
      <span className={caret} />
    </>
  );
}

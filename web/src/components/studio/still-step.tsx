"use client";

/* A still's step card (2026-10-08, after Runway Agent's "Ask before
   generating media"): what the brain will draw, at what frame, and Approve
   -- the one click that spends -- with the model and what a still costs
   under it. It stays as the step's record once drawn ("Approved"), and a
   still that failed can be approved again.

   ONE card for both places the brain talks: the Studio composer's stream
   (composer/turns.tsx, the still drawn below it as the send's tiles) and
   the assistant pill (assistant-pill.tsx, which has no tiles, so the still
   shows inside the card). The turn it reads is the shared thread's: a
   brain answer whose proposal is make_image, its `made` once approved. */
import { useState } from "react";
import { Check, ImagePlus } from "lucide-react";
import type { Turn } from "@/lib/assistant";
import { mediaSrc } from "@/lib/composer";
import "@/components/studio/still-step.css";

export type StepState = "waiting" | "running" | "done" | "failed";

/** a brain answer that proposes a still: a step card, wherever it is drawn */
export const isStillStep = (t: Turn) => t.role === "assistant" && t.reply?.proposal?.tool === "make_image";

export function stepOf(t: Turn) {
  const args = (t.reply?.proposal?.args ?? {}) as { prompt?: unknown; aspect?: unknown };
  const prompt = typeof args.prompt === "string" && args.prompt.trim() ? args.prompt.trim() : t.content;
  const aspect = typeof args.aspect === "string" ? args.aspect : undefined;
  const status = t.made?.status;
  const state: StepState = !t.made
    ? "waiting"
    : status === "running"
      ? "running"
      : status === "done"
        ? "done"
        : "failed";
  return { prompt, aspect, frame: t.made?.frame ?? aspect ?? "", state };
}

/** the turn's own line says the same words as the card: leave it out */
export const lineIsPrompt = (t: Turn) => isStillStep(t) && t.content.trim() === stepOf(t).prompt;

const LABEL: Record<StepState, string> = {
  waiting: "Waiting for approval",
  running: "Generating",
  done: "Done",
  failed: "Not drawn",
};

export function StillStep({
  turn,
  line,
  busy,
  onApprove,
  showImage = false,
}: {
  turn: Turn;
  /** under Approve: "Nano Banana · 10 credits" */
  line: string;
  busy: boolean;
  onApprove: () => void;
  /** the pill draws the still inside the card; the composer draws it below */
  showImage?: boolean;
}) {
  const [more, setMore] = useState(false);
  const { prompt, frame, state } = stepOf(turn);
  const image = showImage && state === "done" ? turn.made?.image : null;
  return (
    <div className="ss" data-state={state}>
      <div className="ss-head">
        <ImagePlus strokeWidth={1.6} />
        <b>Image</b>
        {frame ? <span>{frame}</span> : null}
        <em>{LABEL[state]}</em>
      </div>
      <p className={more ? "open" : undefined}>{prompt}</p>
      {prompt.length > 240 ? (
        <button type="button" className="ss-more" onClick={() => setMore((v) => !v)}>
          {more ? "Less" : "Full prompt"}
        </button>
      ) : null}
      {image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="ss-image" src={mediaSrc(image)} alt="" />
      ) : null}
      <div className="ss-go">
        {state === "waiting" || state === "failed" ? (
          <button type="button" disabled={busy} onClick={onApprove}>
            {state === "failed" ? "Approve again" : "Approve"}
          </button>
        ) : (
          <span className="ss-ok">
            {state === "done" ? <Check strokeWidth={2.2} /> : <span className="ss-live" aria-hidden />}
            {state === "done" ? "Approved" : "Generating…"}
          </span>
        )}
        {line ? <small>{line}</small> : null}
      </div>
    </div>
  );
}

"use client";

/* The stream above the composer, drawn to the "ZPF Composer Directions"
   mock: what was asked as a bubble on the right, what came back under it.

   A SEND (a turn carrying `made`) shows its result as tiles -- an IMAGE
   turn the still, a VIDEO turn the written scene as its timed shots. A
   scene is text until the Queue renders it, so a shot tile is its still
   when one has been drawn and its number otherwise, never fake footage;
   a tile with a clip (rendered later, read back here) gets the play mark.
   The Guide's turns are the same stream: the person's words on the
   right, the answer on the left with its chips, sheet and confirm card.
   Since 2026-10-04 every send IS a Guide turn, and when the brain makes
   (make_image / make_video) its one-line answer carries `made`: the line
   on the left, the tiles under it. A make proposal is never a confirm card;
   a STILL is a step card instead (2026-10-08, after Runway Agent's chat):
   its prompt, its frame, and Approve with the model and price under it --
   then the same card as the step's record, the still drawn below it. */
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Clapperboard, Film, ImagePlus, ListVideo, Play, RotateCcw } from "lucide-react";
import { sceneHref } from "@/lib/studio-api";
import { cssAspect, isMake, isSheetTool, madeMeta, mediaSrc, type Made } from "@/lib/composer";
import type { ContactSheet, Turn } from "@/lib/assistant";
import { lookedLine } from "@/lib/skills";
import { failLine, madeStatus } from "@/lib/made-state";
import { PlanCard, type PlanHandlers } from "@/components/studio/make-plan-card";
import { EffectStep } from "@/components/studio/effect-step";
import type { Effect, EffectState } from "@/lib/effects";
import { ContactSheetView } from "@/components/studio/contact-sheet";
import { TypedText } from "@/components/studio/typed-text";
import { SheetStep, StillStep, isSheetStep, isStillStep, lineIsPrompt } from "@/components/studio/still-step";

const pad = (n: number) => String(n).padStart(2, "0");

export type Live = { progress: number; detail: string };

type Handlers = {
  busy: boolean;
  /** an /image-models id -> its label, for the meta line */
  modelLabel: (id?: string) => string | undefined;
  onAnimate: (m: Made) => void;
  onUseAsRef: (m: Made) => void;
  onReuse: (t: Turn) => void;
  onSelect: (madeId: string, n: number) => void;
  onChip: (text: string) => void;
  onDecide: (i: number, yes: boolean) => void;
  /** a written scene's Send to Queue: the pick, never a render */
  onPick: (m: Made) => void;
  onToggleFrame: (i: number, id: string) => void;
  onKeep: (i: number, sheet: ContactSheet) => void;
  /** a make_image step's Approve: the only click that spends here */
  onApprove: (i: number) => void;
  /** under Approve: the model that draws the still (this one, else the
   *  picker's) and what one costs -- "Nano Banana · 10 credits" */
  stillLine: (modelId?: string) => string;
  /** an element sheet step's Approve: saves the character, draws the sheet */
  onApproveSheet: (i: number) => void;
  /** under the sheet's Approve: "Nano Banana Pro · 36 credits" */
  sheetLine: string;
  /** a plan's card (lib/make-plan.ts), by the plan's id */
  plan: (planId: string) => PlanHandlers;
  /** an effect's card (lib/effects.ts): the table's row for it, whether
   *  this account is charged, a changed choice, and the click that spends */
  effectItem: (effectId: string) => Effect | undefined;
  effectExempt: boolean;
  onEffectChange: (next: EffectState) => void;
  onEffectApprove: (id: string, credits: number, charged: boolean) => void;
};

function Meta({ m, live, h }: { m: Made; live?: Live; h: Handlers }) {
  if (m.status === "running") {
    return (
      <div className="zc-meta">
        <span className="zc-live" aria-hidden />
        {live?.detail || m.detail || (m.output === "image" ? "Drawing the image…" : "Writing the scene…")}
      </div>
    );
  }
  // a still that "finished" with nothing drawn did not finish (lib/made-state.ts)
  const state = madeStatus(m);
  if (state === "failed") {
    return <div className="zc-meta bad">{m.output === "image" ? failLine(m.detail) : m.detail || "That one did not finish."}</div>;
  }
  if (state === "stopped") return <div className="zc-meta">Stopped</div>;
  return <div className="zc-meta">{madeMeta(m, h.modelLabel(m.model))}</div>;
}

/* one plate with the percentage and the red bar, while a send runs */
function RunningTile({ m, live }: { m: Made; live?: Live }) {
  const pct = Math.round((live?.progress ?? 0) * 100);
  return (
    <div className={`zc-tiles${m.output === "image" ? " one" : ""}`}>
      <div className="zc-tilewrap">
        <div className="zc-tile running" style={{ aspectRatio: m.output === "image" ? cssAspect(m.frame) ?? "4 / 5" : undefined }}>
          <span className="zc-pct">{pct}%</span>
          <span className="zc-bar" style={{ width: `${Math.max(4, pct)}%` }} />
        </div>
        <span className="zc-label">{m.output === "image" ? "Image 01" : "Writing…"}</span>
      </div>
    </div>
  );
}

function MadeView({ m, live, h, turn }: { m: Made; live?: Live; h: Handlers; turn: Turn }) {
  const still = useReducedMotion();
  const selected = m.shot ?? 1;
  const tile = (i: number) => ({
    initial: still ? false : { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.28, delay: Math.min(i, 6) * 0.05, ease: [0.22, 0.61, 0.36, 1] as const },
  });

  const state = madeStatus(m);
  let body: React.ReactNode = null;
  if (state === "running") body = <RunningTile m={m} live={live} />;
  else if (state === "done" && m.output === "image") {
    const ratio = cssAspect(m.frame) ?? "4 / 5";
    body = m.clip ? (
      // an effect that made a clip: it plays where a still would be drawn,
      // at its own shape, and is not a button (its controls are)
      <div className="zc-tiles one">
        <motion.div className="zc-tilewrap" {...tile(0)} style={{ maxWidth: 420 }}>
          <div className="zc-tile on clip">
            <video src={mediaSrc(m.clip)} controls muted loop playsInline preload="metadata" />
          </div>
          <span className="zc-label on">Clip 01</span>
        </motion.div>
      </div>
    ) : (
      <div className="zc-tiles one">
        <motion.div className="zc-tilewrap" {...tile(0)} style={{ maxWidth: `calc(420px * (${ratio}))` }}>
          <button type="button" className="zc-tile on" style={{ aspectRatio: ratio }} onClick={() => h.onSelect(m.id, 1)}>
            {/* done means drawn: a still with no image is `failed` above */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={mediaSrc(m.image ?? "")} alt="" />
          </button>
          <span className="zc-label on">Image 01 · selected</span>
        </motion.div>
      </div>
    );
  } else if (state === "done") {
    const parts = m.parts ?? [];
    body = parts.length ? (
      <div className={`zc-tiles${parts.length >= 4 ? " four" : ""}`}>
        {parts.map((p, i) => {
          const on = p.n === selected;
          return (
            <motion.div key={p.n} className="zc-tilewrap" {...tile(i)}>
              <button
                type="button"
                className={`zc-tile${on ? " on" : ""}`}
                aria-pressed={on}
                title={p.text || p.prompt || `Shot ${pad(p.n)}`}
                onClick={() => h.onSelect(m.id, p.n)}
              >
                {p.reference_image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={mediaSrc(p.reference_image)} alt="" />
                ) : (
                  <span className="zc-tile-n">{pad(p.n)}</span>
                )}
                {!p.reference_image && (p.text || p.prompt) ? (
                  <span className="zc-tile-text">
                    <span>{p.text || p.prompt}</span>
                  </span>
                ) : null}
                {p.media_url ? (
                  <span className="zc-play" aria-label="rendered">
                    <Play strokeWidth={2} fill="currentColor" />
                  </span>
                ) : null}
                <span className="zc-badge">{p.seconds}s</span>
              </button>
              <span className={`zc-label${on ? " on" : ""}`}>
                Shot {pad(p.n)} · {p.start}–{p.end}s{on ? " · selected" : ""}
              </span>
            </motion.div>
          );
        })}
      </div>
    ) : (
      <div className="zc-tiles one">
        <motion.div className="zc-tilewrap" {...tile(0)}>
          <div className="zc-tile on">
            <span className="zc-tile-n">01</span>
            {m.seconds ? <span className="zc-badge">{m.seconds}s</span> : null}
          </div>
          <span className="zc-label on">One continuous shot · {m.detail}</span>
        </motion.div>
      </div>
    );
  }

  // the scene's canvas: inside its project's workspace when it is filed
  // under one, else on its own (/studio/scene resolves which)
  const director = m.conceptId ? sceneHref(m.conceptId, m.output === "video" ? selected : 1) : null;

  return (
    <>
      <Meta m={m} live={live} h={h} />
      {body}
      {state === "done" ? (
        <div className="zc-actions">
          {m.output === "image" && m.image ? (
            <>
              <button type="button" className="zc-act" disabled={h.busy} onClick={() => h.onAnimate(m)}>
                <Film strokeWidth={1.6} /> Animate into a shot
              </button>
              <button type="button" className="zc-act" disabled={h.busy} onClick={() => h.onUseAsRef(m)}>
                <ImagePlus strokeWidth={1.6} /> Use as reference
              </button>
            </>
          ) : null}
          {m.output === "video" && m.conceptId ? (
            <button type="button" className="zc-act" disabled={h.busy} onClick={() => h.onPick(m)}>
              <ListVideo strokeWidth={1.6} /> Send to Queue
            </button>
          ) : null}
          {director ? (
            <Link href={director} className="zc-act">
              <Clapperboard strokeWidth={1.6} /> Open the canvas
            </Link>
          ) : null}
          {m.asset && /^gen:\d+$/.test(m.asset) ? (
            <Link href={`/studio/assets?open=${m.asset.slice(4)}`} className="zc-act">
              <ListVideo strokeWidth={1.6} /> See it in the Library
            </Link>
          ) : null}
          {/* an effect has no prompt of the box's to reuse: its card holds its choices */}
          {turn.effect ? null : (
            <button type="button" className="zc-act" disabled={h.busy} onClick={() => h.onReuse(turn)}>
              <RotateCcw strokeWidth={1.6} /> Reuse prompt
            </button>
          )}
        </div>
      ) : (state === "failed" || state === "stopped") && !turn.effect ? (
        <div className="zc-actions">
          <button type="button" className="zc-act" disabled={h.busy} onClick={() => h.onReuse(turn)}>
            <RotateCcw strokeWidth={1.6} /> Try again
          </button>
        </div>
      ) : null}
    </>
  );
}

export function ComposerStream({
  turns,
  live,
  choices,
  working,
  writing = "",
  handlers,
}: {
  turns: Turn[];
  /** progress per running send, by made id (page state) */
  live: Record<string, Live>;
  /** the Guide's offered replies after its newest answer */
  choices: string[];
  /** the Guide is answering: its detail line, drawn as a working row */
  working: string | null;
  /** its answer so far, as the model writes it (the job's `partial`) */
  writing?: string;
  handlers: Handlers;
}) {
  const still = useReducedMotion();
  if (!turns.length) return null;
  const lastAnswer = turns.map((t) => t.role === "assistant" && !t.failed).lastIndexOf(true);
  return (
    <div className="zc-stream" aria-live="polite">
      <AnimatePresence initial={false}>
        {turns.map((t, i) => (
          <motion.article
            key={t.made?.id ?? `${i}:${t.role}`}
            className="zc-turn"
            initial={still ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: [0.22, 0.61, 0.36, 1] }}
          >
            {t.role === "user" ? (
              <div className="zc-ask">
                <div className={`zc-bubble${t.failed ? " failed" : ""}`}>
                  {t.made?.refs.length ? (
                    <span className="zc-bubble-refs">
                      {t.made.refs.slice(0, 4).map((u) => (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img key={u} src={mediaSrc(u)} alt="" />
                      ))}
                      {t.made.refs.length > 4 ? <b>+{t.made.refs.length - 4}</b> : null}
                    </span>
                  ) : null}
                  {t.skill ? <span className="zc-bubble-skill">{t.skill} skill</span> : null}
                  <p>{t.content}</p>
                  {t.failed ? <span className="zc-bubble-failed">Not sent — try again</span> : null}
                </div>
              </div>
            ) : (
              <div className="zc-reply">
                {lookedLine(t.looked) ? <span className="zc-looked">{lookedLine(t.looked)}</span> : null}
                {/* a still's step card carries its prompt; the line is the same words */}
                {lineIsPrompt(t) || isSheetStep(t) || (t.effect && !t.reply) ? null : <p>{t.content}</p>}
                {t.reply?.sheet ? (
                  <ContactSheetView
                    sheet={t.reply.sheet}
                    chosen={t.chosen ?? {}}
                    kept={!!t.kept}
                    busy={handlers.busy}
                    name="The Guide"
                    onToggle={(id) => handlers.onToggleFrame(i, id)}
                    onKeep={(sh) => handlers.onKeep(i, sh)}
                  />
                ) : null}
                {t.reply?.proposal && !isMake(t.reply.proposal.tool) && !isSheetTool(t.reply.proposal.tool) ? (
                  <div className={`ccard${t.decided ? ` ${t.decided}` : ""}`}>
                    <b>{t.reply.proposal.label}</b>
                    <dl>
                      {Object.entries(t.reply.proposal.args).map(([k, v]) => (
                        <div key={k}>
                          <dt>{k}</dt>
                          <dd>{String(v)}</dd>
                        </div>
                      ))}
                    </dl>
                    {t.decided ? (
                      <span className="ccard-state">{t.decided === "done" ? "Done" : "Skipped"}</span>
                    ) : (
                      <div className="ccard-actions">
                        <button type="button" className="yes" disabled={handlers.busy} onClick={() => handlers.onDecide(i, true)}>
                          Confirm
                        </button>
                        <button type="button" disabled={handlers.busy} onClick={() => handlers.onDecide(i, false)}>
                          Skip
                        </button>
                      </div>
                    )}
                  </div>
                ) : null}
                {isStillStep(t) ? (
                  <StillStep
                    turn={t}
                    line={handlers.stillLine(t.made?.model)}
                    busy={handlers.busy}
                    onApprove={() => handlers.onApprove(i)}
                  />
                ) : null}
                {t.plan ? <PlanCard plan={t.plan} h={handlers.plan(t.plan.id)} /> : null}
                {t.effect ? (
                  <EffectStep
                    turn={t}
                    effect={handlers.effectItem(t.effect.effect)}
                    busy={handlers.busy}
                    exempt={handlers.effectExempt}
                    onChange={handlers.onEffectChange}
                    onApprove={(credits, charged) => handlers.onEffectApprove(t.effect?.id ?? "", credits, charged)}
                  />
                ) : null}
                {isSheetStep(t) ? (
                  <SheetStep
                    turn={t}
                    line={handlers.sheetLine}
                    busy={handlers.busy}
                    onApprove={() => handlers.onApproveSheet(i)}
                  />
                ) : null}
                {i === lastAnswer && choices.length ? (
                  <div className="zc-choices">
                    {choices.map((c) => (
                      <button type="button" key={c} onClick={() => handlers.onChip(c)}>
                        {c}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            )}
            {t.made ? <MadeView m={t.made} live={live[t.made.id]} h={handlers} turn={t} /> : null}
          </motion.article>
        ))}
      </AnimatePresence>
      {working !== null && writing.trim() ? (
        // the answer being written, on the left where it will land; the turn
        // that lands replaces it with the same words, so it is hidden from a
        // screen reader (this stream is a live region and would read every
        // few characters)
        <div className="zc-reply zc-typing" aria-hidden>
          <p>
            <TypedText text={writing.trim()} caret="zc-caret" />
          </p>
        </div>
      ) : null}
      {working !== null ? (
        <div className="zc-working" role="status">
          <span className="zc-live" aria-hidden /> {working || "Thinking…"}
        </div>
      ) : null}
    </div>
  );
}

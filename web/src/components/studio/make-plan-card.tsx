"use client";

/* A plan's card (lib/make-plan.ts; docs/tasks/task-studio-agent.md item 2):
   the steps the brain proposed, in order, as one checklist. Each step
   says what it is, what it will do, and what it costs; a step can be
   edited or skipped before it runs, and one that costs credits is
   approved here, beside its price. What a step MAKES is drawn under the
   card as its own turn -- the still's step card and tile, the scene's
   shots -- exactly as if it had been asked for on its own.

   The look is the step card's (still-step.css), one row per step. */
import { useState } from "react";
import { Check, ListChecks } from "lucide-react";
import {
  ahead,
  editable,
  isPaid,
  phase,
  progress,
  stepText,
  stepTitle,
  type GenerateMode,
  type Plan,
  type PlanStep,
  type Prices,
  type StepStatus,
} from "@/lib/make-plan";
import "@/components/studio/make-plan-card.css";

export type PlanHandlers = {
  busy: boolean;
  mode: GenerateMode;
  prices: Prices;
  /** an account that is not charged: prices read "not charged" */
  exempt: boolean;
  /** beside a paid step: "Nano Banana · 10 credits" */
  priceLine: (s: PlanStep) => string;
  /** run from the first unfinished step; `all` approves the priced steps first */
  onStart: (all: boolean) => void;
  onApprove: (n: number) => void;
  onEdit: (n: number, prompt: string) => void;
  onSkip: (n: number) => void;
  onRestore: (n: number) => void;
  onStop: () => void;
};

const STATUS: Record<StepStatus, string> = {
  pending: "",
  waiting: "Waiting for approval",
  running: "Working",
  done: "Done",
  failed: "Did not finish",
  skipped: "Skipped",
};

export function PlanCard({ plan, h }: { plan: Plan; h: PlanHandlers }) {
  const [editing, setEditing] = useState<number | null>(null);
  const [words, setWords] = useState("");
  const now = phase(plan);
  const { done, of } = progress(plan);
  const total = ahead(plan, h.prices);
  const current = plan.steps.find((s) => s.status === "running" || s.status === "waiting");
  const head =
    now === "idle"
      ? "Not started"
      : now === "finished"
        ? "Done"
        : now === "paused"
          ? "Paused"
          : now === "waiting"
            ? "Waiting for approval"
            : `Step ${current?.n ?? done + 1} of ${plan.steps.length}`;

  const open = (s: PlanStep) => {
    setEditing(s.n);
    setWords(typeof s.args.prompt === "string" ? s.args.prompt : "");
  };
  const save = (s: PlanStep) => {
    const next = words.trim();
    if (next && next !== s.args.prompt) h.onEdit(s.n, next);
    setEditing(null);
  };

  return (
    <div className="pl" data-phase={now}>
      <div className="pl-head">
        <ListChecks strokeWidth={1.6} />
        <b>Plan</b>
        <span>{plan.steps.length} steps</span>
        <em>{head}</em>
      </div>
      <ol className="pl-steps">
        {plan.steps.map((s) => {
          const paid = isPaid(s);
          const isEditing = editing === s.n;
          const canSkip = s.status === "pending" || s.status === "waiting" || s.status === "failed";
          return (
            <li key={s.n} className="pl-step" data-status={s.status}>
              <span className="pl-n" aria-hidden>
                {s.status === "done" ? <Check strokeWidth={2.4} /> : s.n}
              </span>
              <div className="pl-body">
                <div className="pl-title">
                  <b>{stepTitle(s)}</b>
                  {s.edited ? <i>edited</i> : null}
                  {STATUS[s.status] ? <em>{STATUS[s.status]}</em> : null}
                </div>
                {isEditing ? (
                  <textarea
                    className="pl-edit"
                    value={words}
                    rows={4}
                    maxLength={4000}
                    aria-label={`Step ${s.n}: what to make`}
                    onChange={(e) => setWords(e.target.value)}
                  />
                ) : (
                  <p className="pl-text">{stepText(plan, s)}</p>
                )}
                {s.note && s.status !== "pending" ? <small className="pl-note">{s.note}</small> : null}
                {s.why && !isEditing ? <small className="pl-why">{s.why}</small> : null}
                {s.uses.length && !isEditing ? (
                  <small className="pl-why">Held to the picture from step {s.uses.join(" and ")}</small>
                ) : null}
                <div className="pl-row">
                  <span className="pl-price">{paid ? h.priceLine(s) : "No credits"}</span>
                  <span className="pl-acts">
                    {isEditing ? (
                      <>
                        <button type="button" className="pl-link" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                        <button type="button" className="pl-link on" disabled={!words.trim()} onClick={() => save(s)}>
                          Save
                        </button>
                      </>
                    ) : (
                      <>
                        {/* a step that is not running can be changed while
                            another one runs: the plan reads each step fresh */}
                        {editable(s) ? (
                          <button type="button" className="pl-link" onClick={() => open(s)}>
                            Edit
                          </button>
                        ) : null}
                        {canSkip ? (
                          <button type="button" className="pl-link" onClick={() => h.onSkip(s.n)}>
                            Skip
                          </button>
                        ) : null}
                        {s.status === "skipped" ? (
                          <button type="button" className="pl-link" onClick={() => h.onRestore(s.n)}>
                            Bring back
                          </button>
                        ) : null}
                        {s.status === "waiting" || s.status === "failed" ? (
                          <button type="button" className="pl-approve" disabled={h.busy} onClick={() => h.onApprove(s.n)}>
                            {s.status === "failed" ? "Try again" : "Approve"}
                          </button>
                        ) : null}
                      </>
                    )}
                  </span>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="pl-foot">
        {now === "idle" || now === "paused" ? (
          <>
            <button type="button" className="pl-go" disabled={h.busy} onClick={() => h.onStart(false)}>
              {now === "idle" ? "Start" : "Resume"}
            </button>
            {h.mode === "ask" && total.priced > 0 ? (
              <button type="button" className="pl-alt" disabled={h.busy} onClick={() => h.onStart(true)}>
                Approve all · {h.exempt ? "not charged" : `${total.credits.toLocaleString()} credits`}
              </button>
            ) : null}
          </>
        ) : null}
        {now === "running" ? (
          <button type="button" className="pl-alt" onClick={h.onStop}>
            Stop
          </button>
        ) : null}
        <small>
          {now === "finished"
            ? `${done} of ${of} steps done`
            : total.priced || total.unpriced
              ? (h.exempt ? "This account is not charged" : `Still to spend: ${total.credits.toLocaleString()} credits`) +
                (total.unpriced ? " · keyframes are priced once the scene is written" : "") +
                (h.mode === "ask" ? " · each paid step asks first" : "")
              : "Nothing left in this plan costs credits"}
        </small>
      </div>
    </div>
  );
}

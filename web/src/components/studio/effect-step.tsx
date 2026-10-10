"use client";

/* An effect's card (lib/effects.ts; item 3 of docs/tasks/task-studio-agent.md):
   what will be changed, on what, with which look or words, and Approve --
   the one click that spends -- beside what it costs. The price is the
   server's (POST /api/effects/quote), asked again whenever a choice that
   moves it changes, and Approve sends that number back so the run happens
   at the price shown or not at all.

   The look is the step card's (still-step.css): this is the same kind of
   step, with its choices on it. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Wand2 } from "lucide-react";
import { quoteEffect } from "@/lib/studio-api";
import { mediaSrc } from "@/lib/composer";
import { madeStatus } from "@/lib/made-state";
import {
  missing,
  optionLabel,
  requestOf,
  takesLine,
  valueLabel,
  type Effect,
  type EffectState,
  type OptionValue,
} from "@/lib/effects";
import type { Turn } from "@/lib/assistant";
import "@/components/studio/still-step.css";
import "@/components/studio/effect-step.css";

type StepState = "waiting" | "running" | "done" | "failed";
const LABEL: Record<StepState, string> = {
  waiting: "Waiting for approval",
  running: "Working",
  done: "Done",
  failed: "Not made",
};

/* option values past this many get a filter box above the list */
const FILTER_OVER = 12;

export function EffectStep({
  turn,
  effect,
  busy,
  exempt,
  onChange,
  onApprove,
}: {
  turn: Turn;
  /** the table's row for this effect; undefined while the gallery loads */
  effect: Effect | undefined;
  busy: boolean;
  exempt: boolean;
  onChange: (next: EffectState) => void;
  /** the click that spends: `credits` is the price this card is showing,
   *  `charged` whether it is debited (false on an exempt account) */
  onApprove: (credits: number, charged: boolean) => void;
}) {
  const fx = turn.effect as EffectState;
  const status = turn.made ? madeStatus(turn.made) : undefined;
  const state: StepState = !turn.made ? "waiting" : status === "running" ? "running" : status === "done" ? "done" : "failed";
  const open = state === "waiting" || state === "failed";
  const [price, setPrice] = useState<{ credits: number; charged: boolean } | null>(null);
  const [problem, setProblem] = useState("");
  const [filter, setFilter] = useState<Record<string, string>>({});
  const asked = useRef(0);

  // the choices that can move the price: everything but the words
  const priced = useMemo(
    () => JSON.stringify([fx.effect, fx.sources.map((s) => s.ref), fx.options]),
    [fx.effect, fx.sources, fx.options],
  );
  const gap = effect ? missing(effect, fx) : "";
  // what stops a QUOTE: a missing source or a required choice. Missing
  // words do not -- the price does not wait on them.
  const unquotable = effect ? missing(effect, { ...fx, prompt: "x" }) : "loading";

  useEffect(() => {
    if (!open || unquotable) return;
    const mine = ++asked.current;
    const timer = setTimeout(() => {
      // an effect that needs words is priced with a stand-in: the price
      // never depends on what they say
      quoteEffect({ ...requestOf(fx), prompt: effect?.prompt === "required" ? fx.prompt.trim() || "x" : requestOf(fx).prompt })
        .then((q) => {
          if (mine !== asked.current) return;
          setPrice({ credits: q.credits, charged: q.charged });
          setProblem("");
        })
        .catch((e) => {
          if (mine !== asked.current) return;
          setPrice(null);
          setProblem(e instanceof Error ? e.message : "That cannot be priced.");
        });
    }, 250);
    return () => clearTimeout(timer);
    // `priced` stands for the effect, its sources and its options
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [priced, open, unquotable]);

  const set = (name: string, value: OptionValue | undefined) => {
    const options = { ...fx.options };
    if (value === undefined) delete options[name];
    else options[name] = value;
    onChange({ ...fx, options });
  };
  const priceLine = (p: { credits: number; charged: boolean }) =>
    p.charged && !exempt ? `${p.credits.toLocaleString()} credits` : `${p.credits.toLocaleString()} credits · not charged`;
  // open: the live quote. Running or done: what Approve was pressed at.
  const line = !open ? (fx.paid ? priceLine(fx.paid) : "") : unquotable ? "" : price ? priceLine(price) : problem ? "" : "Pricing…";

  return (
    <div className="ss fx" data-state={state}>
      <div className="ss-head">
        <Wand2 strokeWidth={1.6} />
        <b>Effect</b>
        <span>{fx.label}</span>
        <em>{LABEL[state]}</em>
      </div>

      <div className="fx-on">
        {fx.sources.length ? (
          fx.sources.map((s) =>
            s.thumb ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={s.ref} src={mediaSrc(s.thumb)} alt="" title={s.from} />
            ) : (
              <span key={s.ref} className="fx-clip" title={s.from}>
                clip
              </span>
            ),
          )
        ) : (
          <span className="fx-none">{fx.takes === "video" ? "No clip to work on yet" : "No image to work on yet"}</span>
        )}
        {fx.sources.length ? <small>On {fx.sources[0].from}{fx.sources.length > 1 ? ` + ${fx.sources.length - 1} more` : ""}</small> : null}
      </div>

      {effect && open
        ? Object.entries(effect.options).map(([name, o]) => {
            // one legal value and it is the default: nothing to choose
            if (o.values.length === 1 && o.default !== null) return null;
            const q = (filter[name] ?? "").trim().toLowerCase();
            const shown = q ? o.values.filter((v) => valueLabel(name, v).toLowerCase().includes(q)) : o.values;
            const current = fx.options[name];
            return (
              <label key={name} className="fx-opt">
                <span>{optionLabel(name)}</span>
                {o.values.length > FILTER_OVER ? (
                  <input
                    type="search"
                    value={filter[name] ?? ""}
                    placeholder={`Search ${o.values.length}`}
                    aria-label={`Search ${optionLabel(name)}`}
                    onChange={(e) => setFilter((f) => ({ ...f, [name]: e.target.value }))}
                  />
                ) : null}
                <select
                  value={current === undefined ? "" : String(current)}
                  aria-label={optionLabel(name)}
                  onChange={(e) => {
                    const picked = o.values.find((v) => String(v) === e.target.value);
                    set(name, picked);
                  }}
                >
                  {o.required ? (
                    <option value="" disabled>
                      Pick one
                    </option>
                  ) : o.default === null ? (
                    <option value="">None</option>
                  ) : null}
                  {/* the picked value stays listed while a search hides it */}
                  {current !== undefined && !shown.some((v) => String(v) === String(current)) ? (
                    <option value={String(current)}>{valueLabel(name, current)}</option>
                  ) : null}
                  {shown.map((v) => (
                    <option key={String(v)} value={String(v)}>
                      {valueLabel(name, v)}
                    </option>
                  ))}
                </select>
              </label>
            );
          })
        : null}

      {effect && effect.prompt !== "none" && open ? (
        <textarea
          className="fx-words"
          value={fx.prompt}
          rows={2}
          maxLength={2000}
          placeholder={
            effect.takes === "video"
              ? effect.prompt === "required"
                ? "What it should sound like…"
                : "Optional: what belongs in the new area…"
              : "What to change…"
          }
          aria-label="What to change"
          onChange={(e) => onChange({ ...fx, prompt: e.target.value })}
        />
      ) : fx.prompt ? (
        <p className="open">{fx.prompt}</p>
      ) : null}

      {!open ? (
        <p className="fx-chose">
          {Object.entries(fx.options)
            .map(([name, v]) => `${optionLabel(name)}: ${valueLabel(name, v)}`)
            .join(" · ") || (effect ? takesLine(effect) : "")}
        </p>
      ) : null}

      <div className="ss-go">
        {open ? (
          <button type="button" disabled={busy || !!gap || !price} onClick={() => price && onApprove(price.credits, price.charged && !exempt)}>
            {state === "failed" ? "Approve again" : "Approve"}
          </button>
        ) : (
          <span className="ss-ok">
            {state === "done" ? <Check strokeWidth={2.2} /> : <span className="ss-live" aria-hidden />}
            {state === "done" ? "Approved" : "Working…"}
          </span>
        )}
        <small>{open ? gap || problem || line : line}</small>
      </div>
    </div>
  );
}

"use client";

/* The effects gallery (`/effects` in the composer; lib/effects.ts): every
   effect the studio has, by what it does. Browsing runs nothing and costs
   nothing -- a pick only puts a card in the thread, and that card's
   Approve is the click that spends. An effect with nothing to act on yet
   says what it needs instead of opening a card that could not run. */
import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { X } from "lucide-react";
import { fromPrice, takesLine, unavailable, type Candidate, type Effect } from "@/lib/effects";
import "@/components/studio/effect-gallery.css";

export function EffectGallery({
  effects,
  categories,
  ready,
  exempt,
  candidates,
  on,
  tab: startTab,
  onPick,
  onClose,
}: {
  effects: Effect[];
  categories: { id: string; label: string }[];
  /** the server can run effects at all */
  ready: boolean;
  exempt: boolean;
  /** what there is to act on, for each effect's "needs…" line */
  candidates: Candidate[];
  /** opened ON one result ("this still"): the header says so */
  on?: string;
  /** the tab to open on */
  tab?: string;
  onPick: (effect: Effect) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState(
    (startTab && categories.some((c) => c.id === startTab) ? startTab : categories[0]?.id) ?? "",
  );
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const shown = effects.filter((e) => e.category === (tab || categories[0]?.id));

  return (
    <motion.div
      className="fxg"
      role="dialog"
      aria-label="Effects"
      initial={{ opacity: 0, y: 6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 6, scale: 0.98 }}
      transition={{ duration: 0.16, ease: [0.22, 0.61, 0.36, 1] }}
    >
      <div className="fxg-head">
        <b>Effects</b>
        <span>{on ? `On ${on}. ` : "Browsing is free. "}A pick shows its price before anything runs.</span>
        <button type="button" aria-label="Close effects" onClick={onClose}>
          <X strokeWidth={1.8} />
        </button>
      </div>
      <div className="fxg-tabs" role="tablist">
        {categories.map((c) => (
          <button
            key={c.id}
            type="button"
            role="tab"
            aria-selected={c.id === (tab || categories[0]?.id)}
            onClick={() => setTab(c.id)}
          >
            {c.label}
          </button>
        ))}
      </div>
      {!ready ? <p className="fxg-note">Effects are not set up on this server yet.</p> : null}
      <ul className="fxg-list">
        {shown.map((e) => {
          const why = unavailable(e, candidates);
          return (
            <li key={e.id}>
              <button type="button" disabled={!ready || !!why} onClick={() => onPick(e)}>
                <span className="fxg-name">{e.label}</span>
                <span className="fxg-blurb">{e.blurb}</span>
                <span className="fxg-meta">
                  {why ? <i>{why}</i> : takesLine(e)}
                  <em>{fromPrice(e, exempt)}</em>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </motion.div>
  );
}

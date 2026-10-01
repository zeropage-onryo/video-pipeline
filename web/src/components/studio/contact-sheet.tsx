"use client";

/* A find_references contact sheet: one row per need, every frame the hunt
   looked at, the cut ones greyed with the reason. Drawn under a Guide
   answer -- by the assistant pill and by the composer's own Guide thread
   (2026-10-01: the composer's Guide "found references" and drew nothing,
   because only the pill knew how to draw a sheet). Keeping is the
   caller's: the click hands back the chosen ids. */
import { useMemo } from "react";
import { ExternalLink } from "lucide-react";
import type { ContactSheet } from "@/lib/assistant";
import "@/components/studio/assistant.css";
/* eslint-disable @next/next/no-img-element -- frames off other hosts, drawn as-is */

export function framesOf(sheet: ContactSheet | null | undefined) {
  return sheet?.sheet?.flatMap((n) => [...n.keepers, ...n.rejected]) ?? [];
}

/* What starts ticked: the frames the look kept. */
export function keepersOf(sheet: ContactSheet | null | undefined): Record<string, boolean> {
  const sel: Record<string, boolean> = {};
  sheet?.sheet?.forEach((n) => n.keepers.forEach((k) => (sel[k.id] = true)));
  return sel;
}

export function ContactSheetView({
  sheet,
  chosen,
  kept,
  busy,
  name,
  onToggle,
  onKeep,
}: {
  sheet: ContactSheet;
  chosen: Record<string, boolean>;
  kept: boolean;
  busy: boolean;
  name: string;
  onToggle: (id: string) => void;
  onKeep: (sheet: ContactSheet) => void;
}) {
  const frames = useMemo(() => framesOf(sheet), [sheet]);
  const count = frames.filter((f) => chosen[f.id]).length;
  return (
    <div className="zpa-sheet">
      <span className="zpa-mono dim">{sheet.note}</span>
      {sheet.faces ? <span className="zpa-face">A face comes from your Elements (@name), never the web.</span> : null}
      {sheet.sheet.map((n, k) => {
        const all = [...n.keepers, ...n.rejected];
        return (
          <div key={k} className="zpa-need">
            <div className="zpa-needhead">
              <span className="zpa-mono">
                {n.role} · {n.query}
              </span>
              <span className="zpa-mono dim">
                {n.keepers.length}/{all.length}
              </span>
            </div>
            {all.length ? (
              <div className="zpa-grid">
                {all.map((f) => {
                  const rejected = n.rejected.includes(f);
                  const on = !!chosen[f.id];
                  return (
                    <span key={f.id} className="zpa-frame-wrap">
                      <button
                        type="button"
                        className={`zpa-frame${on ? " on" : ""}${rejected ? " rej" : ""}`}
                        aria-pressed={on}
                        disabled={kept}
                        title={`${f.title || f.source}${rejected ? ` — cut: ${f.why}` : f.kept_for ? ` — ${f.kept_for}` : ""}${rejected ? " · click to keep anyway" : ""}`}
                        onClick={() => onToggle(f.id)}
                      >
                        <img src={f.image_url} alt={f.title || "reference"} loading="lazy" referrerPolicy="no-referrer" />
                        <span className="zpa-tag">{rejected && !on ? `✕ ${f.why || "cut"}` : f.source}</span>
                      </button>
                      {f.source_url ? (
                        <a
                          href={f.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="zpa-src"
                          aria-label={`Where ${f.title || "this frame"} came from`}
                        >
                          <ExternalLink strokeWidth={1.8} />
                        </a>
                      ) : null}
                    </span>
                  );
                })}
              </div>
            ) : (
              <span className="zpa-mono dim">{n.note || "nothing found"}</span>
            )}
          </div>
        );
      })}
      {frames.length ? (
        <button type="button" className="zpa-keep" disabled={busy || kept || !count} onClick={() => onKeep(sheet)}>
          {kept ? "Kept · on your composer" : `Keep ${count} · 0 cr`}
        </button>
      ) : null}
      {frames.length && !kept ? (
        <span className="zpa-mono dim">Kept frames go on the composer. {name} never presses Create.</span>
      ) : null}
    </div>
  );
}

"use client";

/* The clip Inspector's Playback card (2026-10-01), the last row of
   invideo's clip Inspector (docs/reference-look/invideo-editor/
   06-clip-selected-inspector.jpg): Speed, Ripple timeline, Reverse,
   Duration. Each change is ONE op (set_speed / set_reverse) on the clip
   and its linked sound; nothing here writes the doc. */

import { useState } from "react";
import { useCut } from "@/lib/cut/store";
import { SPEED_MAX, SPEED_MIN, clipLength, speedOf, timecode, type Clip, type Doc } from "@/lib/cut/timeline";

const PRESETS = [0.25, 0.5, 1, 1.5, 2, 4];

export function PlaybackCard({ doc, clip }: { doc: Doc; clip: Clip }) {
  const op = useCut((s) => s.op);
  const speed = speedOf(clip);
  const shown = +speed.toFixed(2);
  const [typed, setTyped] = useState(String(shown));
  const [ripple, setRipple] = useState(true);

  const setSpeed = (v: number) => {
    if (!Number.isFinite(v)) return;
    const s = Math.min(SPEED_MAX, Math.max(SPEED_MIN, v));
    setTyped(String(+s.toFixed(2)));
    if (Math.abs(s - speed) < 0.005) return;
    void op("set_speed", { clip_id: clip.id, speed: s, ripple });
  };

  return (
    <div className="cx-card cx-playback">
      <h4 className="cx-h">Playback</h4>
      <div className="cx-field">
        <span className="cx-label">Speed</span>
        <span className="cx-field-row">
          <span className="cx-seg" role="group" aria-label="Speed presets">
            {PRESETS.map((p) => (
              <button
                key={p}
                type="button"
                aria-pressed={Math.abs(p - speed) < 0.005}
                onClick={() => setSpeed(p)}
              >
                {p}×
              </button>
            ))}
          </span>
          <input
            className="cx-input cx-mono cx-speed-box"
            value={typed}
            aria-label="Speed"
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Enter") setSpeed(parseFloat(typed));
              if (e.key === "Escape") setTyped(String(shown));
            }}
            onBlur={() => setSpeed(parseFloat(typed))}
          />
        </span>
      </div>
      <label className="cx-check">
        <input type="checkbox" checked={ripple} onChange={(e) => setRipple(e.target.checked)} />
        <span>Ripple timeline</span>
        <span className="cx-note-inline">what follows moves with the new length</span>
      </label>
      <label className="cx-check">
        <input
          type="checkbox"
          checked={!!clip.reverse}
          onChange={(e) => void op("set_reverse", { clip_id: clip.id, on: e.target.checked })}
        />
        <span>Reverse</span>
        {clip.reverse ? <span className="cx-note-inline">the preview steps it silently; the export plays it</span> : null}
      </label>
      <dl className="cx-kv">
        <dt>Duration</dt>
        <dd>
          {timecode(clipLength(clip), doc.fps)}
          {shown !== 1 ? ` · from ${timecode(clip.src_out - clip.src_in, doc.fps)}` : ""}
        </dd>
      </dl>
    </div>
  );
}

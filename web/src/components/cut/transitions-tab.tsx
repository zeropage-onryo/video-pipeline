"use client";

/* The bin's Transitions tab (2026-10-01): invideo has 72, grouped, with a
   search (docs/reference-look/invideo-editor/07-transitions-tab.jpg). Ours
   are ffmpeg's xfade styles -- every one renders on Fly's ffmpeg -- in the
   same groups as src/cut/doc.py. A tile plays its look on hover, drawn by
   the same `lookAt` the viewer uses. Click puts it on the selected cut (or
   the one nearest the playhead); drag it onto a clip to put it on the cut
   INTO that clip. Either way it is one op. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { applyTransition } from "@/lib/cut/actions";
import { useCut, useDrawnDoc } from "@/lib/cut/store";
import { gradeFilter, gradeTarget, gradeTint } from "@/components/cut/color";
import { GROUPS, STYLES, lookAt, type TransitionStyle } from "@/lib/cut/transitions";

export const TRANSITION_MIME = "application/x-zpf-transition";

/* The Effects tab: the transitions, and LOOKS -- one-click basic
   corrections (the Color page's set_grade) for the clip the Color page
   would grade: the selected picture clip, else the one at the playhead. */
export function EffectsTab() {
  const [view, setView] = useState<"transitions" | "looks">("transitions");
  return (
    <div className="cx-pane-body cx-xt">
      <span className="cx-seg" role="tablist" aria-label="Effects" style={{ marginBottom: 10 }}>
        <button type="button" role="tab" aria-selected={view === "transitions"} onClick={() => setView("transitions")}>
          Transitions
        </button>
        <button type="button" role="tab" aria-selected={view === "looks"} onClick={() => setView("looks")}>
          Looks
        </button>
      </span>
      {view === "transitions" ? <TransitionsTab /> : <LooksTab />}
    </div>
  );
}

export const LOOKS: { id: string; label: string; grade: { exposure?: number; contrast?: number; saturation?: number; temperature?: number } }[] = [
  { id: "natural", label: "As shot", grade: {} },
  { id: "warm", label: "Golden", grade: { temperature: 0.45, saturation: 1.1 } },
  { id: "cool", label: "Steel", grade: { temperature: -0.45, saturation: 0.9 } },
  { id: "punchy", label: "Punchy", grade: { contrast: 1.25, saturation: 1.3 } },
  { id: "faded", label: "Faded", grade: { contrast: 0.75, saturation: 0.7, exposure: 0.2 } },
  { id: "mono", label: "Mono", grade: { saturation: 0, contrast: 1.15 } },
  { id: "bright", label: "Bright", grade: { exposure: 0.5, contrast: 0.95 } },
  { id: "moody", label: "Moody", grade: { exposure: -0.5, contrast: 1.2, saturation: 0.8, temperature: -0.2 } },
];

function LooksTab() {
  const doc = useDrawnDoc();
  const selection = useCut((s) => s.selection);
  const playhead = useCut((s) => s.playhead);
  const bin = useCut((s) => s.bin);
  const op = useCut((s) => s.op);
  if (!doc) return null;
  const clip = gradeTarget(doc, selection, playhead);
  const poster = clip ? bin.find((b) => b.handle === clip.media)?.poster : null;
  return (
    <>
      <p className="cx-note">
        {clip
          ? `A look replaces ${clip.id}'s grade in one edit; fine-tune it on the Color page (⇧6).`
          : "Select a picture clip, or put the playhead on one, to give it a look."}
      </p>
      <div className="cx-xt-grid">
        {LOOKS.map((l) => (
          <button
            key={l.id}
            type="button"
            className="cx-xt-tile"
            disabled={!clip}
            title={l.label}
            onClick={() => clip && void op("set_grade", { clip_id: clip.id, reset: true, ...l.grade })}
          >
            <span className="cx-xt-demo" aria-hidden>
              <i
                className="cx-xt-look"
                style={{
                  backgroundImage: poster ? `url(${poster})` : undefined,
                  filter: gradeFilter(l.grade),
                }}
              />
              {gradeTint(l.grade) ? <i style={gradeTint(l.grade)!} /> : null}
            </span>
            <span className="cx-xt-name">{l.label}</span>
          </button>
        ))}
      </div>
    </>
  );
}

export function TransitionsTab() {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle
      ? STYLES.filter((s) => s.label.toLowerCase().includes(needle) || s.style.includes(needle) || s.group.toLowerCase().includes(needle))
      : STYLES;
  }, [q]);
  return (
    <>
      <label className="cx-xt-search">
        <Search />
        <input
          className="cx-input"
          placeholder={`Search ${STYLES.length} transitions`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
        />
      </label>
      <p className="cx-note">Click to put one on the selected cut, or drag it onto a clip. The sound always crossfades.</p>
      {GROUPS.map((g) => {
        const list = shown.filter((s) => s.group === g);
        if (!list.length) return null;
        return (
          <section key={g} className="cx-xt-group">
            <h5 className="cx-label">
              {g} <span className="cx-dim">{list.length}</span>
            </h5>
            <div className="cx-xt-grid">
              {list.map((s) => (
                <Tile key={s.style} s={s} />
              ))}
            </div>
          </section>
        );
      })}
      {!shown.length ? <p className="cx-note">No transition called “{q}”.</p> : null}
    </>
  );
}

function Tile({ s }: { s: TransitionStyle }) {
  const [p, setP] = useState(0.5);
  const raf = useRef<number | null>(null);
  const stop = () => {
    if (raf.current !== null) cancelAnimationFrame(raf.current);
    raf.current = null;
    setP(0.5);
  };
  const play = () => {
    const t0 = performance.now();
    const step = (now: number) => {
      // 1.2 s through, 0.3 s held on the incoming picture, again
      const t = ((now - t0) % 1500) / 1200;
      setP(Math.min(1, t));
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
  };
  useEffect(() => () => stop(), []);
  const look = lookAt(s.style, p);
  return (
    <button
      type="button"
      className="cx-xt-tile"
      title={`${s.label} (${s.style})`}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(TRANSITION_MIME, s.style);
        e.dataTransfer.effectAllowed = "copy";
      }}
      onMouseEnter={play}
      onMouseLeave={stop}
      onFocus={play}
      onBlur={stop}
      onClick={() => applyTransition(s.style)}
    >
      <span className="cx-xt-demo" aria-hidden>
        <i className="cx-xt-a" />
        <i className="cx-xt-b" style={{ ...(look.css as React.CSSProperties), opacity: look.fade ? p : 1 }} />
      </span>
      <span className="cx-xt-name">{s.label}</span>
    </button>
  );
}

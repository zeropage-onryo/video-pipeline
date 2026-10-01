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
import { GROUPS, STYLES, lookAt, type TransitionStyle } from "@/lib/cut/transitions";

export const TRANSITION_MIME = "application/x-zpf-transition";

export function TransitionsTab() {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle
      ? STYLES.filter((s) => s.label.toLowerCase().includes(needle) || s.style.includes(needle) || s.group.toLowerCase().includes(needle))
      : STYLES;
  }, [q]);
  return (
    <div className="cx-pane-body cx-xt">
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
    </div>
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

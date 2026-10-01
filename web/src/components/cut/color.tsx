"use client";

/* The Color page's panel (2026-10-01): a picture clip's basic correction
   -- exposure, contrast, saturation, temperature -- the "Basic
   Correction" block of invideo's grading panel
   (docs/reference-look/invideo-editor/08-color-page.jpg). Wheels, curves,
   qualifiers and LUTs are still a later phase.

   The clip is the selected picture clip, else the one the Program viewer
   shows at the playhead, so scrubbing through a cut walks the panel from
   shot to shot. A slider previews through the ghost and saves ONE
   `set_grade` on release, compared against the SAVED clip. */
import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { useCut, useDrawnDoc } from "@/lib/cut/store";
import { clipAt, findClip, stackOrder, type Clip, type Doc } from "@/lib/cut/timeline";

type Field = "exposure" | "contrast" | "saturation" | "temperature";
const FIELDS: { key: Field; label: string; min: number; max: number; neutral: number; step: number; show: (v: number) => string }[] = [
  { key: "exposure", label: "Exposure", min: -2, max: 2, neutral: 0, step: 0.05, show: (v) => `${v > 0 ? "+" : ""}${v.toFixed(2)} st` },
  { key: "contrast", label: "Contrast", min: 0.5, max: 2, neutral: 1, step: 0.01, show: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "saturation", label: "Saturation", min: 0, max: 2, neutral: 1, step: 0.01, show: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "temperature", label: "Temperature", min: -1, max: 1, neutral: 0, step: 0.02, show: (v) => (v === 0 ? "neutral" : `${v > 0 ? "warm" : "cool"} ${Math.abs(v * 100).toFixed(0)}`) },
];

/* the clip the Color page works on */
export function gradeTarget(doc: Doc, selection: { kind: string | null; ids: string[] }, playhead: number): Clip | null {
  if (selection.kind === "clip" && selection.ids.length === 1) {
    const f = findClip(doc, selection.ids[0]);
    if (f && f.track.kind === "video") return f.clip;
  }
  for (const t of stackOrder(doc.tracks)) {
    if (t.kind !== "video") continue;
    const c = clipAt(t, playhead);
    if (c) return c;
  }
  return null;
}

/* CSS for the preview: what render.py's exposure / eq / colortemperature
   do, approximated -- the export is exact */
export function gradeFilter(grade: Clip["grade"]): string | undefined {
  if (!grade) return undefined;
  const parts = [];
  if (grade.exposure) parts.push(`brightness(${Math.pow(2, grade.exposure).toFixed(3)})`);
  if (grade.contrast !== undefined && grade.contrast !== 1) parts.push(`contrast(${grade.contrast})`);
  if (grade.saturation !== undefined && grade.saturation !== 1) parts.push(`saturate(${grade.saturation})`);
  return parts.length ? parts.join(" ") : undefined;
}
/* temperature as a tinted overlay (soft-light), warm amber or cool blue */
export function gradeTint(grade: Clip["grade"]): React.CSSProperties | null {
  const t = grade?.temperature ?? 0;
  if (!t) return null;
  return {
    position: "absolute",
    inset: 0,
    pointerEvents: "none",
    mixBlendMode: "soft-light",
    background: t > 0 ? "rgb(255 140 20)" : "rgb(30 120 255)",
    opacity: Math.min(0.85, Math.abs(t) * 0.7),
  };
}

export function ColorPanel() {
  const doc = useDrawnDoc();
  const selection = useCut((s) => s.selection);
  const playhead = useCut((s) => s.playhead);
  if (!doc) return null;
  const clip = gradeTarget(doc, selection, playhead);
  if (!clip) {
    return (
      <div className="cx-card">
        <h4 className="cx-h">Color</h4>
        <p className="cx-note">Put the playhead on a picture clip, or select one, to grade it.</p>
      </div>
    );
  }
  return <Grade key={clip.id} doc={doc} clip={clip} />;
}

function Grade({ doc, clip }: { doc: Doc; clip: Clip }) {
  const op = useCut((s) => s.op);
  const [draft, setDraft] = useState<Partial<Record<Field, number>>>({});
  const value = (f: (typeof FIELDS)[number]) => draft[f.key] ?? clip.grade?.[f.key] ?? f.neutral;
  const ghost = (key: Field, v: number) => {
    setDraft((d) => ({ ...d, [key]: v }));
    useCut.setState({
      ghost: {
        ...doc,
        tracks: doc.tracks.map((t) =>
          t.clips ? { ...t, clips: t.clips.map((c) => (c.id === clip.id ? { ...c, grade: { ...c.grade, [key]: v } } : c)) } : t,
        ),
      },
    });
  };
  const commit = (key: Field, v: number) => {
    setDraft((d) => {
      const n = { ...d };
      delete n[key];
      return n;
    });
    const saved = useCut.getState().doc ? findClip(useCut.getState().doc!, clip.id)?.clip : undefined;
    const neutral = FIELDS.find((f) => f.key === key)!.neutral;
    if (Math.abs((saved?.grade?.[key] ?? neutral) - v) < 1e-9) {
      useCut.setState({ ghost: null });
      return;
    }
    void op("set_grade", { clip_id: clip.id, [key]: v }, { quiet: true });
  };
  const graded = !!clip.grade && Object.keys(clip.grade).length > 0;
  return (
    <div className="cx-card cx-grade">
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
        <h4 className="cx-h" style={{ margin: 0 }}>
          Basic correction · {clip.id}
        </h4>
        <span className="spacer" style={{ flex: 1 }} />
        <button
          type="button"
          className="cx-key-btn"
          title="Reset the grade"
          disabled={!graded}
          onClick={() => void op("set_grade", { clip_id: clip.id, reset: true })}
        >
          <RotateCcw />
        </button>
      </div>
      {FIELDS.map((f) => {
        const v = value(f);
        return (
          <label key={f.key} className="cx-field cx-grade-row" data-field={f.key}>
            <span className="cx-label">
              {f.label} <span className="cx-mono">{f.show(v)}</span>
            </span>
            <input
              type="range"
              className="cx-range"
              min={f.min}
              max={f.max}
              step={f.step}
              value={v}
              aria-label={f.label}
              onChange={(e) => ghost(f.key, Number(e.target.value))}
              onPointerUp={() => draft[f.key] !== undefined && commit(f.key, draft[f.key]!)}
              onKeyUp={() => draft[f.key] !== undefined && commit(f.key, draft[f.key]!)}
              onDoubleClick={() => commit(f.key, f.neutral)}
            />
          </label>
        );
      })}
      <p className="cx-note">
        The preview approximates the grade with CSS; the export renders it with ffmpeg (exposure, eq, colortemperature).
        Double-click a slider to reset it.
      </p>
    </div>
  );
}

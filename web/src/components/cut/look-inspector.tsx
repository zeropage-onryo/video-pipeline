"use client";

/* The clip Inspector's Transform, Crop and Opacity (2026-10-01): the
   second gap the invideo captures named (06-clip-selected-inspector.jpg),
   keyframed as Resolve does it.

   Each Transform row is one LANE (lanes.ts / src/cut/lanes.py):
   - Not animated (no key, or one): the value is a constant, and editing it
     sets that constant (a key at frame 0).
   - The diamond adds a key at the playhead with the value showing there --
     from the second key on, the row is ANIMATED: editing the value keys it
     at the playhead (auto-key), the diamond on a key removes it, ‹ › jump
     between keys, and the ease of the key under the playhead can be set.
   - ↺ resets the property (the lane goes).
   Crop and opacity are static per clip.

   Every change is ONE op on release; while a slider is dragged the store's
   ghost carries the would-be doc, so the viewer moves with the slider. */
import { useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Diamond, RotateCcw } from "lucide-react";
import { useCut } from "@/lib/cut/store";
import { EASES, MAX_CROP, PATHS, laneOf, valueOf, withKey, type Ease, type LanePath } from "@/lib/cut/lanes";
import { clipLength, findClip, type Clip, type Doc } from "@/lib/cut/timeline";

export type Row = {
  path: LanePath;
  label: string;
  /* how the value reads, and back */
  show: (v: number) => string;
  unit: string;
  toShown: (v: number) => number;
  fromShown: (v: number) => number;
  step: number;
};

const ROWS: Row[] = [
  { path: "zoom", label: "Zoom", show: (v) => v.toFixed(2), unit: "×", toShown: (v) => v, fromShown: (v) => v, step: 0.01 },
  { path: "x", label: "Position X", show: (v) => (v * 100).toFixed(1), unit: "%", toShown: (v) => v * 100, fromShown: (v) => v / 100, step: 0.5 },
  { path: "y", label: "Position Y", show: (v) => (v * 100).toFixed(1), unit: "%", toShown: (v) => v * 100, fromShown: (v) => v / 100, step: 0.5 },
  { path: "rotation", label: "Rotation", show: (v) => v.toFixed(1), unit: "°", toShown: (v) => v, fromShown: (v) => v, step: 0.5 },
];

/* The clip as SAVED -- not as drawn. While a slider is dragged the drawn
   doc is the ghost, which already carries the dragged value, so a commit
   that compared against it would always see "no change" and save nothing
   (found in the browser, 2026-10-01). Commits compare against this. */
function savedClip(id: string): Clip | undefined {
  return useCut.getState().doc ? findClip(useCut.getState().doc!, id)?.clip : undefined;
}

/* the doc with one clip replaced: the ghost a dragged slider draws */
function ghostWith(doc: Doc, clipId: string, edit: (c: Clip) => Clip): Doc {
  return {
    ...doc,
    tracks: doc.tracks.map((t) => (t.clips ? { ...t, clips: t.clips.map((c) => (c.id === clipId ? edit(c) : c)) } : t)),
  };
}

export function LookInspector({ doc, clip }: { doc: Doc; clip: Clip }) {
  const playhead = useCut((s) => s.playhead);
  const fps = doc.fps;
  const len = clipLength(clip);
  const rel = playhead - clip.at;
  const inside = rel >= 0 && rel <= len;
  return (
    <>
      <div className="cx-card">
        <h4 className="cx-h">Transform</h4>
        {!inside ? (
          <p className="cx-note" style={{ marginBottom: 8 }}>
            Put the playhead on this clip to keyframe it.
          </p>
        ) : null}
        {ROWS.map((r) => (
          <LaneRow key={r.path} doc={doc} clip={clip} row={r} rel={Math.max(0, Math.min(rel, len))} inside={inside} fps={fps} />
        ))}
      </div>
      <CropCard doc={doc} clip={clip} />
      <OpacityRow doc={doc} clip={clip} />
    </>
  );
}

export function LaneRow({
  doc,
  clip,
  row,
  rel,
  inside,
  fps,
}: {
  doc: Doc;
  clip: Clip;
  row: Row;
  rel: number;
  inside: boolean;
  fps: number;
}) {
  const op = useCut((s) => s.op);
  const seek = useCut((s) => s.seek);
  const keys = laneOf(clip, row.path)?.keys ?? [];
  const animated = keys.length > 1;
  const value = valueOf(clip, row.path, rel);
  const keyHere = keys.find((k) => k.frame === rel);
  const [min, max] = PATHS[row.path];
  const [draft, setDraft] = useState<number | null>(null);
  const shown = draft ?? value;

  // where an edit lands: the playhead when animated, else the constant
  const target = animated && inside ? rel : (keys[0]?.frame ?? 0);
  const preview = (v: number) => {
    setDraft(v);
    useCut.setState({ ghost: ghostWith(doc, clip.id, (c) => withKey(c, row.path, target, v)) });
  };
  const commit = (v: number) => {
    setDraft(null);
    const clamped = Math.max(min, Math.min(max, v));
    const saved = savedClip(clip.id);
    const was = saved ? valueOf(saved, row.path, target) : value;
    if (Math.abs(clamped - was) < 1e-9) {
      useCut.setState({ ghost: null });
      return;
    }
    void op("set_key", { clip_id: clip.id, path: row.path, frame: target, value: clamped }, { quiet: true });
  };
  const prev = [...keys].reverse().find((k) => k.frame < rel);
  const next = keys.find((k) => k.frame > rel);

  return (
    <div className="cx-lane-row cx-lane-keyed" data-animated={animated ? "1" : undefined}>
      <span className="cx-lane-label">{row.label}</span>
      <span className="cx-key-tools">
        <button
          type="button"
          className="cx-key-btn"
          title="Previous key"
          disabled={!animated || !prev}
          onClick={() => prev && seek(clip.at + prev.frame)}
        >
          <ChevronLeft />
        </button>
        <button
          type="button"
          className="cx-key-btn cx-diamond"
          aria-pressed={!!keyHere && animated}
          title={!inside ? "Put the playhead on this clip" : keyHere && animated ? "Remove this key" : "Add a key here"}
          disabled={!inside}
          onClick={() => {
            if (keyHere && animated) void op("delete_key", { clip_id: clip.id, path: row.path, frame: rel }, { quiet: true });
            else void op("set_key", { clip_id: clip.id, path: row.path, frame: rel, value }, { quiet: true });
          }}
        >
          <Diamond />
        </button>
        <button
          type="button"
          className="cx-key-btn"
          title="Next key"
          disabled={!animated || !next}
          onClick={() => next && seek(clip.at + next.frame)}
        >
          <ChevronRight />
        </button>
        <button
          type="button"
          className="cx-key-btn"
          title={`Reset ${row.label.toLowerCase()}`}
          disabled={!keys.length}
          onClick={() => void op("clear_lane", { clip_id: clip.id, path: row.path }, { quiet: true })}
        >
          <RotateCcw />
        </button>
      </span>
      <input
        type="range"
        className="cx-range"
        min={row.toShown(min)}
        max={row.toShown(max)}
        step={row.step}
        value={row.toShown(shown)}
        onChange={(e) => preview(row.fromShown(Number(e.target.value)))}
        onPointerUp={() => draft !== null && commit(draft)}
        onKeyUp={() => draft !== null && commit(draft)}
        aria-label={row.label}
      />
      <NumberBox
        value={row.toShown(shown)}
        text={row.show(shown)}
        unit={row.unit}
        onCommit={(n) => commit(row.fromShown(n))}
      />
      {animated && keyHere ? (
        <span className="cx-ease">
          {EASES.map((e) => (
            <button
              key={e}
              type="button"
              aria-pressed={(keyHere.ease ?? "linear") === e}
              title={e === "hold" ? "Hold until the next key" : e === "ease" ? "Ease in and out" : "Straight line"}
              onClick={() =>
                (keyHere.ease ?? "linear") !== e &&
                void op("set_key", { clip_id: clip.id, path: row.path, frame: rel, value: keyHere.value, ease: e as Ease }, { quiet: true })
              }
            >
              {e}
            </button>
          ))}
          <span className="cx-label" style={{ marginLeft: "auto" }}>
            key +{(rel / fps).toFixed(2)}s
          </span>
        </span>
      ) : null}
    </div>
  );
}

/* a typed value: commits on Enter or blur, Escape puts it back */
function NumberBox({ value, text, unit, onCommit }: { value: number; text: string; unit: string; onCommit: (n: number) => void }) {
  const [editing, setEditing] = useState<string | null>(null);
  // what was typed, readable by blur even before React has rendered it
  const typed = useRef<string | null>(null);
  return (
    <span className="cx-num">
      <input
        className="cx-input cx-mono"
        value={editing ?? text}
        onFocus={() => {
          typed.current = text;
          setEditing(text);
        }}
        onChange={(e) => {
          typed.current = e.target.value;
          setEditing(e.target.value);
        }}
        onBlur={() => {
          const raw = typed.current;
          typed.current = null;
          setEditing(null);
          const n = Number(raw);
          if (raw !== null && raw.trim() !== "" && Number.isFinite(n) && Math.abs(n - value) > 1e-9) onCommit(n);
        }}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") {
            typed.current = null;
            setEditing(null);
            (e.target as HTMLInputElement).blur();
          }
        }}
      />
      <span className="cx-unit">{unit}</span>
    </span>
  );
}

const SIDES = ["left", "right", "top", "bottom"] as const;

function CropCard({ doc, clip }: { doc: Doc; clip: Clip }) {
  const op = useCut((s) => s.op);
  const crop = { left: clip.crop?.left ?? 0, right: clip.crop?.right ?? 0, top: clip.crop?.top ?? 0, bottom: clip.crop?.bottom ?? 0 };
  const [draft, setDraft] = useState<typeof crop | null>(null);
  const cur = draft ?? crop;
  const set = (side: (typeof SIDES)[number], v: number) => {
    const next = { ...cur, [side]: v };
    setDraft(next);
    useCut.setState({ ghost: ghostWith(doc, clip.id, (c) => ({ ...c, crop: next })) });
  };
  const commit = () => {
    if (!draft) return;
    setDraft(null);
    const saved = savedClip(clip.id)?.crop ?? {};
    if (SIDES.every((s) => Math.abs(draft[s] - (saved[s] ?? 0)) < 1e-9)) {
      useCut.setState({ ghost: null });
      return;
    }
    void op("set_crop", { clip_id: clip.id, ...draft }, { quiet: true });
  };
  const any = SIDES.some((s) => crop[s] > 0);
  return (
    <div className="cx-card">
      <div className="cx-field-row" style={{ marginBottom: 6 }}>
        <h4 className="cx-h" style={{ flex: 1, margin: 0 }}>
          Crop
        </h4>
        <button
          type="button"
          className="cx-key-btn"
          title="Reset crop"
          disabled={!any}
          onClick={() => void op("set_crop", { clip_id: clip.id }, { quiet: true })}
        >
          <RotateCcw />
        </button>
      </div>
      {SIDES.map((side) => (
        <div key={side} className="cx-lane-row">
          <span className="cx-lane-label" style={{ textTransform: "capitalize" }}>
            {side}
          </span>
          <input
            type="range"
            className="cx-range"
            min={0}
            max={MAX_CROP * 100}
            step={0.5}
            value={cur[side] * 100}
            onChange={(e) => set(side, Number(e.target.value) / 100)}
            onPointerUp={commit}
            onKeyUp={commit}
            aria-label={`Crop ${side}`}
          />
          <span className="cx-label" style={{ width: 44, textAlign: "right" }}>
            {(cur[side] * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
}

function OpacityRow({ doc, clip }: { doc: Doc; clip: Clip }) {
  const op = useCut((s) => s.op);
  const value = clip.opacity ?? 1;
  const [draft, setDraft] = useState<number | null>(null);
  const cur = draft ?? value;
  const commit = () => {
    if (draft === null) return;
    const v = draft;
    setDraft(null);
    if (Math.abs(v - (savedClip(clip.id)?.opacity ?? 1)) < 1e-9) {
      useCut.setState({ ghost: null });
      return;
    }
    void op("set_opacity", { clip_id: clip.id, value: v }, { quiet: true });
  };
  return (
    <div className="cx-card">
      <div className="cx-lane-row">
        <span className="cx-lane-label">Opacity</span>
        <input
          type="range"
          className="cx-range"
          min={0}
          max={100}
          step={1}
          value={cur * 100}
          onChange={(e) => {
            const v = Number(e.target.value) / 100;
            setDraft(v);
            useCut.setState({ ghost: ghostWith(doc, clip.id, (c) => ({ ...c, opacity: v })) });
          }}
          onPointerUp={commit}
          onKeyUp={commit}
          aria-label="Opacity"
        />
        <span className="cx-label" style={{ width: 44, textAlign: "right" }}>
          {Math.round(cur * 100)}%
        </span>
      </div>
    </div>
  );
}

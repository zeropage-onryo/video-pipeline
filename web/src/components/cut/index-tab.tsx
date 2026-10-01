"use client";

/* The bin's Index tab (2026-10-01): the two lists invideo's bin carries
   beside its media (Edit Index, Markers), the way Resolve shows them.

   EDIT INDEX is every event on the timeline in record order -- clip or
   cue, its track, record in/out, source in/out and what is done to it
   (speed, reverse, transition, grade, fades) -- read-only, a click selects
   it and puts the playhead on it. MARKERS lists the doc's markers: click to
   go there, rename in place (Enter), remove, or add one at the playhead
   (M). Every change is one op. */
import { useMemo, useState } from "react";
import { Diamond, Plus, Trash2 } from "lucide-react";
import { useCut, useDrawnDoc } from "@/lib/cut/store";
import { addMarkerAtPlayhead } from "@/lib/cut/actions";
import { labelOf } from "@/lib/cut/transitions";
import { clipEnd, clipLength, speedOf, timecode, type Doc, type Track } from "@/lib/cut/timeline";

type Kind = "all" | Track["kind"];

export function IndexTab() {
  const [view, setView] = useState<"edits" | "markers">("edits");
  return (
    <div className="cx-pane-body cx-index">
      <span className="cx-seg" role="tablist" aria-label="Index">
        <button type="button" role="tab" aria-selected={view === "edits"} onClick={() => setView("edits")}>
          Edit index
        </button>
        <button type="button" role="tab" aria-selected={view === "markers"} onClick={() => setView("markers")}>
          Markers
        </button>
      </span>
      {view === "edits" ? <EditIndex /> : <Markers />}
    </div>
  );
}

type Row = {
  id: string;
  kind: Track["kind"];
  track: string;
  name: string;
  recIn: number;
  recOut: number;
  srcIn?: number;
  srcOut?: number;
  notes: string[];
  cue?: boolean;
};

export function editIndex(doc: Doc, names: Map<string, string>): Row[] {
  const rows: Row[] = [];
  for (const t of doc.tracks) {
    for (const c of t.clips ?? []) {
      const notes: string[] = [];
      if (clipLength(c) !== c.src_out - c.src_in) notes.push(`${+speedOf(c).toFixed(2)}×`);
      if (c.reverse) notes.push("reversed");
      if (c.transition_in) notes.push(`${labelOf(c.transition_in.style).toLowerCase()} ${c.transition_in.frames}f`);
      if (c.grade && Object.keys(c.grade).length) notes.push("graded");
      if (c.lanes?.length) notes.push("keyed");
      if (c.fade_in || c.fade_out) notes.push("fades");
      if (c.gain_db) notes.push(`${c.gain_db > 0 ? "+" : ""}${c.gain_db} dB`);
      rows.push({
        id: c.id,
        kind: t.kind,
        track: t.id,
        name: names.get(c.media) ?? c.media,
        recIn: c.at,
        recOut: clipEnd(c),
        srcIn: c.src_in,
        srcOut: c.src_out,
        notes,
      });
    }
    for (const q of t.cues ?? []) {
      rows.push({ id: q.id, kind: t.kind, track: t.id, name: q.text, recIn: q.start, recOut: q.end, notes: [], cue: true });
    }
  }
  return rows.sort((a, b) => a.recIn - b.recIn || a.track.localeCompare(b.track));
}

function EditIndex() {
  const doc = useDrawnDoc();
  const bin = useCut((s) => s.bin);
  const selection = useCut((s) => s.selection);
  const [kind, setKind] = useState<Kind>("all");
  const names = useMemo(() => new Map(bin.map((b) => [b.handle, b.name])), [bin]);
  const rows = useMemo(() => (doc ? editIndex(doc, names) : []), [doc, names]);
  if (!doc) return null;
  const fps = doc.fps;
  const shown = rows.filter((r) => kind === "all" || r.kind === kind);
  return (
    <>
      <div className="cx-filter">
        {(["all", "video", "audio", "caption"] as Kind[]).map((k) => (
          <button key={k} type="button" className="cx-btn ghost" aria-pressed={kind === k} onClick={() => setKind(k)}>
            {{ all: "All", video: "Picture", audio: "Sound", caption: "Captions" }[k]}
            <span className="cx-label" style={{ letterSpacing: 0 }}>
              {rows.filter((r) => k === "all" || r.kind === k).length}
            </span>
          </button>
        ))}
      </div>
      {shown.length ? (
        <ol className="cx-edl">
          {shown.map((r, i) => (
            <li key={r.id}>
              <button
                type="button"
                className="cx-edl-row"
                aria-current={selection.ids.includes(r.id) ? "true" : undefined}
                onClick={() => {
                  const st = useCut.getState();
                  st.select([r.id], r.cue ? "cue" : "clip");
                  st.seek(r.recIn);
                }}
              >
                <span className="cx-edl-n">{String(i + 1).padStart(3, "0")}</span>
                <span className="cx-edl-t" data-kind={r.kind}>
                  {r.track}
                </span>
                <span className="cx-edl-name">{r.name}</span>
                <span className="cx-edl-tc">
                  {timecode(r.recIn, fps)} – {timecode(r.recOut, fps)}
                </span>
                {r.srcIn !== undefined ? (
                  <span className="cx-edl-src">
                    src {timecode(r.srcIn, fps)} – {timecode(r.srcOut!, fps)}
                  </span>
                ) : null}
                {r.notes.length ? <span className="cx-edl-notes">{r.notes.join(" · ")}</span> : null}
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <p className="cx-note">Nothing on the timeline yet.</p>
      )}
    </>
  );
}

function Markers() {
  const doc = useDrawnDoc();
  const op = useCut((s) => s.op);
  const seek = useCut((s) => s.seek);
  if (!doc) return null;
  const markers = doc.markers ?? [];
  return (
    <>
      <button type="button" className="cx-btn ghost" onClick={() => addMarkerAtPlayhead()} title="Add a marker at the playhead (M)">
        <Plus /> Marker at the playhead
      </button>
      {markers.length ? (
        <ul className="cx-markers">
          {markers.map((m) => (
            <MarkerRow
              key={`${m.frame}-${m.label}`}
              frame={m.frame}
              label={m.label}
              fps={doc.fps}
              onGo={() => seek(m.frame)}
              onRename={(label) => label !== m.label && void op("set_marker", { frame: m.frame, label })}
              onDelete={() => void op("delete_marker", { frame: m.frame })}
            />
          ))}
        </ul>
      ) : (
        <p className="cx-note">No markers. Press M on the timeline to drop one at the playhead.</p>
      )}
    </>
  );
}

function MarkerRow({
  frame,
  label,
  fps,
  onGo,
  onRename,
  onDelete,
}: {
  frame: number;
  label: string;
  fps: number;
  onGo: () => void;
  onRename: (label: string) => void;
  onDelete: () => void;
}) {
  const [text, setText] = useState(label);
  return (
    <li className="cx-marker-row">
      <button type="button" className="cx-key-btn" title="Go to this marker" onClick={onGo}>
        <Diamond />
      </button>
      <button type="button" className="cx-edl-tc cx-linkish" onClick={onGo}>
        {timecode(frame, fps)}
      </button>
      <input
        className="cx-input"
        value={text}
        aria-label={`Marker at ${timecode(frame, fps)}`}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") setText(label);
        }}
        onBlur={() => onRename(text.trim() || label)}
      />
      <button type="button" className="cx-key-btn" title="Remove this marker" onClick={onDelete}>
        <Trash2 />
      </button>
    </li>
  );
}

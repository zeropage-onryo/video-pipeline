"use client";

/* The inspector (T16): what is selected, and the controls that change it.
   EVERY control is an op -- a field never writes the doc. A number field
   commits on Enter or blur (one op per decision, not per keystroke), and
   the gain slider commits on release.

   Nothing selected shows the project: its canvas (set_canvas), its fps
   and length. A Color tab has a seat in the header for the phase that
   brings grading; it is drawn disabled rather than left out, so the room
   for it is visible. */
import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useCut, useDrawnDoc } from "@/lib/cut/store";
import { deleteSelection } from "@/lib/cut/actions";
import { LookInspector } from "@/components/cut/look-inspector";
import { PlaybackCard } from "@/components/cut/playback-inspector";
import { DEFAULT_STYLE, GROUPS, STYLES, labelOf } from "@/lib/cut/transitions";
import {
  ASPECTS,
  aspectOf,
  clipLength,
  findClip,
  findCue,
  speedOf,
  timecode,
  type Aspect,
  type AudioRole,
  type Clip,
  type Cue,
  type Doc,
  type Track,
} from "@/lib/cut/timeline";

export const CAPTION_STYLES: { id: string; label: string }[] = [
  { id: "preset:bold_center", label: "Bold center" },
  { id: "preset:lower_third", label: "Lower third" },
  { id: "preset:minimal_top", label: "Minimal top" },
];

export function Inspector() {
  const doc = useDrawnDoc();
  const selection = useCut((s) => s.selection);
  const [tab, setTab] = useState<"inspect" | "color">("inspect");
  if (!doc) return null;

  let body: React.ReactNode;
  if (selection.kind === "clip" && selection.ids.length === 1) {
    const f = findClip(doc, selection.ids[0]);
    body = f ? <ClipInspector key={`${f.clip.id}-${f.clip.src_in}-${f.clip.src_out}-${f.clip.at}`} doc={doc} clip={f.clip} track={f.track} /> : null;
  } else if (selection.kind === "cue" && selection.ids.length === 1) {
    const f = findCue(doc, selection.ids[0]);
    body = f ? <CueInspector key={`${f.cue.id}-${f.cue.start}-${f.cue.end}-${f.cue.text}`} doc={doc} cue={f.cue} track={f.track} /> : null;
  } else if (selection.ids.length > 1) {
    body = (
      <div className="cx-card">
        <h4 className="cx-h">{selection.ids.length} selected</h4>
        <p className="cx-note">Delete lifts them all; Shift+Delete ripples. Edit one at a time to change its values.</p>
        <button type="button" className="cx-btn ghost" onClick={() => deleteSelection(false)}>
          <Trash2 /> Lift all
        </button>
      </div>
    );
  }

  return (
    <div className="cx-pane">
      <div className="cx-pane-head" role="tablist">
        <button type="button" role="tab" className="cx-tab" aria-selected={tab === "inspect"} onClick={() => setTab("inspect")}>
          Inspector
        </button>
        <button type="button" role="tab" className="cx-tab" aria-selected={tab === "color"} disabled title="Grading arrives in a later phase">
          Color
        </button>
      </div>
      <div className="cx-pane-body">{body ?? <ProjectInspector doc={doc} />}</div>
    </div>
  );
}

/* A frame count typed as frames OR as timecode-ish seconds ("2.5s"). */
function parseFrames(text: string, fps: number): number | null {
  const t = text.trim();
  if (!t) return null;
  if (/^-?\d+$/.test(t)) return Number(t);
  const s = /^(-?\d+(?:\.\d+)?)\s*s$/.exec(t);
  if (s) return Math.round(Number(s[1]) * fps);
  const tc = /^(\d+):(\d{1,2}):(\d{1,2})$/.exec(t); // mm:ss:ff
  if (tc) return (Number(tc[1]) * 60 + Number(tc[2])) * fps + Number(tc[3]);
  return null;
}

function FrameField({
  label,
  value,
  fps,
  onCommit,
}: {
  label: string;
  value: number;
  fps: number;
  onCommit: (frames: number) => void;
}) {
  const [text, setText] = useState(timecode(value, fps));
  const commit = () => {
    const f = parseFrames(text, fps);
    if (f === null || f === value) return setText(timecode(value, fps));
    onCommit(f);
  };
  return (
    <label className="cx-field">
      <span className="cx-label">{label}</span>
      <span className="cx-field-row">
        <button type="button" className="cx-btn ghost" title="One frame less" onClick={() => onCommit(value - 1)}>
          −
        </button>
        <input
          className="cx-input cx-mono"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") setText(timecode(value, fps));
            e.stopPropagation();
          }}
          title="mm:ss:ff, a frame count, or seconds like 2.5s"
        />
        <button type="button" className="cx-btn ghost" title="One frame more" onClick={() => onCommit(value + 1)}>
          +
        </button>
      </span>
    </label>
  );
}

function ClipInspector({ doc, clip, track }: { doc: Doc; clip: Clip; track: Track }) {
  const op = useCut((s) => s.op);
  const media = useCut((s) => s.media[clip.media]);
  const item = useCut((s) => s.bin.find((b) => b.handle === clip.media));
  const fps = doc.fps;
  const [gain, setGain] = useState(clip.gain_db ?? 0);
  const [xf, setXf] = useState(String(clip.transition_in?.frames ?? 8));
  const len = clipLength(clip);

  return (
    <>
      <div className="cx-card">
        <h4 className="cx-h" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {item?.name ?? clip.media}
        </h4>
        <dl className="cx-kv">
          <dt>Clip</dt>
          <dd>{clip.id}</dd>
          <dt>Track</dt>
          <dd>{track.id}{track.role ? ` · ${track.role}` : ""}</dd>
          <dt>Media</dt>
          <dd>{clip.media}</dd>
          <dt>Length</dt>
          <dd>{timecode(len, fps)}</dd>
          {media ? (
            <>
              <dt>Source</dt>
              <dd>{timecode(media.frames, fps)}</dd>
            </>
          ) : null}
          {clip.link ? (
            <>
              <dt>Linked to</dt>
              <dd>{clip.link}</dd>
            </>
          ) : null}
        </dl>
      </div>

      <FrameField
        label="Source in"
        value={clip.src_in}
        fps={fps}
        onCommit={(f) => {
          // trim takes TIMELINE frames: a source move is divided by the
          // speed, and a reversed clip's source in is its tail
          const d = Math.round((f - clip.src_in) / speedOf(clip));
          op("trim", { clip_id: clip.id, head: clip.reverse ? 0 : d, tail: clip.reverse ? d : 0 });
        }}
      />
      <FrameField
        label="Source out"
        value={clip.src_out}
        fps={fps}
        onCommit={(f) => {
          const d = Math.round((clip.src_out - f) / speedOf(clip));
          op("trim", { clip_id: clip.id, head: clip.reverse ? d : 0, tail: clip.reverse ? 0 : d });
        }}
      />
      <FrameField
        label="Starts at"
        value={clip.at}
        fps={fps}
        onCommit={(f) => op("move", { clip_id: clip.id, at: Math.max(0, f) })}
      />

      {track.kind === "audio" ? (
        <label className="cx-field">
          <span className="cx-label">
            Gain · {gain > 0 ? "+" : ""}
            {gain.toFixed(1)} dB
          </span>
          <input
            type="range"
            className="cx-range"
            min={-60}
            max={12}
            step={0.5}
            value={gain}
            onChange={(e) => setGain(Number(e.target.value))}
            onPointerUp={() => gain !== (clip.gain_db ?? 0) && op("set_gain", { clip_id: clip.id, db: gain })}
            onKeyUp={() => gain !== (clip.gain_db ?? 0) && op("set_gain", { clip_id: clip.id, db: gain })}
          />
        </label>
      ) : (
        <LookInspector doc={doc} clip={clip} />
      )}
      <PlaybackCard key={`${clip.id}-${clip.dur ?? 0}`} doc={doc} clip={clip} />

      <div className="cx-field">
        <span className="cx-label">Transition in</span>
        {clip.transition_in ? (
          <>
            <span className="cx-field-row">
              <select
                className="cx-input"
                value={clip.transition_in.style ?? DEFAULT_STYLE}
                onChange={(e) => op("set_transition", { clip_id: clip.id, style: e.target.value })}
                aria-label="Transition style"
              >
                {GROUPS.map((g) => (
                  <optgroup key={g} label={g}>
                    {STYLES.filter((x) => x.group === g).map((x) => (
                      <option key={x.style} value={x.style}>
                        {x.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <input
                className="cx-input cx-mono"
                style={{ width: 64 }}
                value={xf}
                onChange={(e) => setXf(e.target.value)}
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key !== "Enter") return;
                  const frames = parseFrames(xf, fps);
                  if (frames && frames > 0 && frames !== clip.transition_in?.frames)
                    op("set_transition", { clip_id: clip.id, frames });
                }}
                title="length in frames (Enter)"
                aria-label="Transition length"
              />
            </span>
            <p className="cx-note">
              {labelOf(clip.transition_in.style)} over {clip.transition_in.frames} frames (
              {(clip.transition_in.frames / fps).toFixed(2)}s) from the clip before.{" "}
              <button type="button" className="cx-link" onClick={() => op("remove_transition", { clip_id: clip.id })}>
                Make it a hard cut
              </button>
            </p>
          </>
        ) : (
          <span className="cx-field-row">
            <input
              className="cx-input cx-mono"
              value={xf}
              onChange={(e) => setXf(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
              title="frames"
            />
            <button
              type="button"
              className="cx-btn ghost"
              onClick={() => {
                const frames = parseFrames(xf, fps);
                if (frames && frames > 0) op("add_transition", { clip_id: clip.id, frames });
              }}
            >
              Add crossfade
            </button>
          </span>
        )}
        <span className="cx-note">More looks in the Transitions tab — drag one onto a clip.</span>
      </div>

      {track.kind === "audio" && track.role === "music" ? <DuckControl track={track} /> : null}

      <span className="cx-field-row" style={{ marginTop: 6 }}>
        <button type="button" className="cx-btn ghost" onClick={() => deleteSelection(false)} title="Delete">
          Lift
        </button>
        <button type="button" className="cx-btn ghost" onClick={() => deleteSelection(true)} title="Shift+Delete">
          Ripple delete
        </button>
      </span>
    </>
  );
}

function DuckControl({ track }: { track: Track }) {
  const op = useCut((s) => s.op);
  const roles: AudioRole[] = ["voice", "sfx"];
  return (
    <div className="cx-field">
      <span className="cx-label">Duck under</span>
      <span className="cx-seg">
        <button type="button" aria-pressed={!track.duck_under} onClick={() => op("duck", { track_id: track.id, under: null })}>
          Off
        </button>
        {roles.map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={track.duck_under === r}
            onClick={() => op("duck", { track_id: track.id, under: r })}
          >
            {r}
          </button>
        ))}
      </span>
      <p className="cx-note">The music drops while that track is sounding (a sidechain compressor at export).</p>
    </div>
  );
}

function CueInspector({ doc, cue, track }: { doc: Doc; cue: Cue; track: Track }) {
  const op = useCut((s) => s.op);
  const [text, setText] = useState(cue.text);
  const fps = doc.fps;
  const save = (patch: Partial<Cue>) =>
    op("set_cue", {
      track_id: track.id,
      cue_id: cue.id,
      start: patch.start ?? cue.start,
      end: patch.end ?? cue.end,
      text: patch.text ?? cue.text,
    });
  return (
    <>
      <label className="cx-field">
        <span className="cx-label">Caption text</span>
        <textarea
          className="cx-textarea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => text.trim() && text !== cue.text && save({ text: text.trim() })}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) (e.target as HTMLTextAreaElement).blur();
          }}
        />
      </label>
      <FrameField label="Starts" value={cue.start} fps={fps} onCommit={(f) => save({ start: Math.max(0, f) })} />
      <FrameField label="Ends" value={cue.end} fps={fps} onCommit={(f) => save({ end: f })} />
      <CaptionStyle track={track} />
      <button type="button" className="cx-btn ghost" onClick={() => op("delete_cue", { track_id: track.id, cue_id: cue.id })}>
        <Trash2 /> Delete cue
      </button>
    </>
  );
}

export function CaptionStyle({ track }: { track: Track }) {
  const op = useCut((s) => s.op);
  const current = track.style ?? "preset:bold_center";
  return (
    <div className="cx-field">
      <span className="cx-label">Style · {track.id}</span>
      <span className="cx-seg" style={{ flexWrap: "wrap" }}>
        {CAPTION_STYLES.map((s) => (
          <button
            key={s.id}
            type="button"
            aria-pressed={current === s.id}
            onClick={() => current !== s.id && op("set_caption_style", { track_id: track.id, style: s.id })}
          >
            {s.label}
          </button>
        ))}
      </span>
    </div>
  );
}

function ProjectInspector({ doc }: { doc: Doc }) {
  const op = useCut((s) => s.op);
  const project = useCut((s) => s.project);
  const versions = useCut((s) => s.versions.length);
  const aspect = aspectOf(doc.size);
  return (
    <>
      <div className="cx-card">
        <h4 className="cx-h">Project</h4>
        <dl className="cx-kv">
          <dt>Canvas</dt>
          <dd>
            {doc.size[0]}×{doc.size[1]}
          </dd>
          <dt>Frame rate</dt>
          <dd>{doc.fps} fps</dd>
          <dt>Length</dt>
          <dd>{timecode(doc.duration, doc.fps)}</dd>
          <dt>Tracks</dt>
          <dd>{doc.tracks.length}</dd>
          <dt>Versions</dt>
          <dd>{versions}</dd>
          {project?.concept_id ? (
            <>
              <dt>From concept</dt>
              <dd>#{project.concept_id}</dd>
            </>
          ) : null}
        </dl>
      </div>
      <div className="cx-field">
        <span className="cx-label">Aspect</span>
        <span className="cx-seg">
          {(Object.keys(ASPECTS) as Aspect[]).map((a) => (
            <button
              key={a}
              type="button"
              aria-pressed={aspect === a}
              onClick={() => {
                if (aspect === a) return;
                const [width, height] = ASPECTS[a];
                op("set_canvas", { width, height });
              }}
            >
              {a}
            </button>
          ))}
        </span>
        <p className="cx-note">Changing the canvas is an edit like any other — it makes a new version, and undo takes it back.</p>
      </div>
      <p className="cx-note">Select a clip or a caption to edit it. Every change here becomes a version you can undo.</p>
    </>
  );
}

"use client";

/* The mixer (2026-10-01), invideo's Audio page strips
   (docs/reference-look/invideo-editor/09-audio-page.jpg): one strip per
   audio track -- its role, a fader (dB) and a pan, rendered into the
   export -- plus M / S, which are MONITORING (the preview only, as on the
   track headers) and the Main strip, which says what the export does to
   the sum. Each fader / pan move previews live through the ghost and
   saves ONE `set_track_mix` on release.

   SoundInspector is the clip half: a sound clip's volume, keyable, and its
   fades. */
import { useState } from "react";
import { useCut, useDrawnDoc } from "@/lib/cut/store";
import { clipLength, type Clip, type Doc, type Track } from "@/lib/cut/timeline";
import { LaneRow, type Row } from "@/components/cut/look-inspector";
import { FrameField } from "@/components/cut/inspector";

const MIN_DB = -60;
const MAX_DB = 12;

export function Mixer() {
  const doc = useDrawnDoc();
  if (!doc) return null;
  const tracks = doc.tracks.filter((t) => t.kind === "audio");
  return (
    <div className="cx-mixer">
      <div className="cx-mixer-strips">
        {tracks.map((t) => (
          <Strip key={t.id} doc={doc} track={t} />
        ))}
        <div className="cx-mstrip cx-mstrip-main">
          <span className="cx-mstrip-id">Main</span>
          <span className="cx-mstrip-role">master</span>
          <p className="cx-note">
            The export mixes every strip, then normalises the whole cut to −14 LUFS (−1.5 dBTP), the loudness social
            platforms play at — so the faders set the BALANCE, not the final volume.
          </p>
        </div>
      </div>
      {!tracks.length ? <p className="cx-note">No audio tracks yet — add one from the timeline.</p> : null}
      <p className="cx-note">
        M / S only change what you hear here. The preview cannot boost past 0 dB or pan; the export does both.
      </p>
    </div>
  );
}

function ghostTrack(doc: Doc, trackId: string, patch: Partial<Track>): Doc {
  return { ...doc, tracks: doc.tracks.map((t) => (t.id === trackId ? { ...t, ...patch } : t)) };
}

function savedTrack(id: string): Track | undefined {
  return useCut.getState().doc?.tracks.find((t) => t.id === id);
}

function Strip({ doc, track }: { doc: Doc; track: Track }) {
  const op = useCut((s) => s.op);
  const mix = useCut((s) => s.mix[track.id]);
  const setMix = useCut((s) => s.setMix);
  const [gain, setGain] = useState<number | null>(null);
  const [pan, setPan] = useState<number | null>(null);
  const g = gain ?? track.gain_db ?? 0;
  const p = pan ?? track.pan ?? 0;

  const preview = (patch: Partial<Track>) => useCut.setState({ ghost: ghostTrack(doc, track.id, patch) });
  const commit = (key: "gain_db" | "pan", value: number) => {
    setGain(null);
    setPan(null);
    const was = savedTrack(track.id)?.[key] ?? 0;
    if (Math.abs(value - was) < 1e-6) {
      useCut.setState({ ghost: null });
      return;
    }
    void op("set_track_mix", { track_id: track.id, [key]: value }, { quiet: true });
  };

  return (
    <div className="cx-mstrip" data-role={track.role}>
      <span className="cx-mstrip-id">{track.id}</span>
      <span className="cx-mstrip-role">
        {track.role}
        {track.duck_under ? ` · ducks ${track.duck_under}` : ""}
      </span>
      <label className="cx-mstrip-pan" title="Pan (double-click: centre)">
        <span className="cx-label">{p === 0 ? "C" : `${Math.round(Math.abs(p) * 100)}${p < 0 ? "L" : "R"}`}</span>
        <input
          type="range"
          className="cx-range"
          min={-1}
          max={1}
          step={0.05}
          value={p}
          aria-label={`${track.id} pan`}
          onChange={(e) => {
            const v = Number(e.target.value);
            setPan(v);
            preview({ pan: v });
          }}
          onPointerUp={() => pan !== null && commit("pan", pan)}
          onKeyUp={() => pan !== null && commit("pan", pan)}
          onDoubleClick={() => commit("pan", 0)}
        />
      </label>
      <div className="cx-fader">
        <input
          type="range"
          className="cx-fader-input"
          min={MIN_DB}
          max={MAX_DB}
          step={0.5}
          value={g}
          aria-label={`${track.id} fader`}
          aria-orientation="vertical"
          onChange={(e) => {
            const v = Number(e.target.value);
            setGain(v);
            preview({ gain_db: v });
          }}
          onPointerUp={() => gain !== null && commit("gain_db", gain)}
          onKeyUp={() => gain !== null && commit("gain_db", gain)}
          onDoubleClick={() => commit("gain_db", 0)}
        />
      </div>
      <span className="cx-mstrip-db">
        {g > 0 ? "+" : ""}
        {g.toFixed(1)} dB
      </span>
      <span className="cx-mstrip-ms">
        <button
          type="button"
          className="cx-ms"
          data-k="m"
          aria-pressed={!!mix?.mute}
          title="Mute in the preview (not an edit)"
          onClick={() => setMix(track.id, { mute: !mix?.mute })}
        >
          M
        </button>
        <button
          type="button"
          className="cx-ms"
          data-k="s"
          aria-pressed={!!mix?.solo}
          title="Solo in the preview (not an edit)"
          onClick={() => setMix(track.id, { solo: !mix?.solo })}
        >
          S
        </button>
      </span>
    </div>
  );
}

const VOLUME: Row = {
  path: "volume",
  label: "Volume",
  show: (v) => v.toFixed(1),
  unit: "dB",
  toShown: (v) => v,
  fromShown: (v) => v,
  step: 0.5,
};

export function SoundInspector({ doc, clip }: { doc: Doc; clip: Clip }) {
  const playhead = useCut((s) => s.playhead);
  const op = useCut((s) => s.op);
  const fps = doc.fps;
  const len = clipLength(clip);
  const rel = playhead - clip.at;
  const inside = rel >= 0 && rel <= len;
  return (
    <div className="cx-card">
      <h4 className="cx-h">Volume</h4>
      {!inside ? (
        <p className="cx-note" style={{ marginBottom: 8 }}>
          Put the playhead on this clip to key its volume.
        </p>
      ) : null}
      <LaneRow doc={doc} clip={clip} row={VOLUME} rel={Math.max(0, Math.min(rel, len))} inside={inside} fps={fps} />
      <FrameField
        label="Fade in"
        value={clip.fade_in ?? 0}
        fps={fps}
        onCommit={(f) => op("set_fade", { clip_id: clip.id, fade_in: Math.max(0, Math.min(len, f)) })}
      />
      <FrameField
        label="Fade out"
        value={clip.fade_out ?? 0}
        fps={fps}
        onCommit={(f) => op("set_fade", { clip_id: clip.id, fade_out: Math.max(0, Math.min(len, f)) })}
      />
    </div>
  );
}

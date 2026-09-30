"use client";

/* The viewer (T15, decision D3): the doc PLAYED from the playhead in the
   browser, from T6's proxies. It is not frame-exact and does not try to
   be -- the ffmpeg render is the export of record, and the corner says so.

   How it plays:
   - One clock: requestAnimationFrame advances the playhead at `rate`
     (J/K/L). Every media element is a follower of that clock, never the
     other way round, so a clip that stalls cannot drag the timeline.
   - Picture: a <video> (an <img> for a still) per video clip within a
     short window around the playhead -- the current clip AND the next,
     so the cut lands on a frame that is already decoded. Each seeks to
     `src_in + (playhead - at)` and is corrected when it drifts.
   - Sound: a hidden element per audio clip, its volume from the clip's
     gain, the track's mute/solo, and a DUCKING APPROXIMATION -- a track
     that ducks under a role drops ~10 dB while a clip of that role is
     sounding. The render's sidechain compressor is smoother; this is the
     same idea at listening quality. element.volume, not Web Audio: the
     proxies are cross-origin R2 objects, and a MediaElementSource on a
     non-CORS response plays silence. Boosts above 0 dB are heard at 0 dB.
   - Picture elements are always muted: a clip's sound lives on its linked
     audio clip, and playing it twice would double it.
   - A crossfade is opacity: the incoming clip fades up over its
     transition_in frames, on top of the outgoing one.
   - Captions are drawn over the frame, in the track's style preset. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ChevronFirst,
  ChevronLast,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  StepBack,
  StepForward,
} from "lucide-react";
import { useCut, useDrawnDoc } from "@/lib/cut/store";
import { jumpCut, nudge, toEnd, toStart } from "@/lib/cut/actions";
import type { BinItem, Preview } from "@/lib/cut/api";
import { clipAt, clipEnd, endOf, stackOrder, timecode, type Clip, type Doc, type Track } from "@/lib/cut/timeline";

const DUCK = 0.32; // ~ -10 dB
const WINDOW_BEFORE_S = 0.5;
const WINDOW_AFTER_S = 2.5;

type Live = { clip: Clip; track: Track; z: number };

export function Viewer() {
  const doc = useDrawnDoc();
  const playhead = useCut((s) => s.playhead);
  const playing = useCut((s) => s.playing);
  const rate = useCut((s) => s.rate);
  const mix = useCut((s) => s.mix);
  const bin = useCut((s) => s.bin);
  const previews = useCut((s) => s.previews);
  const binByHandle = useMemo(() => new Map(bin.map((b) => [b.handle, b])), [bin]);

  /* ── the clock ── */
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const tick = (now: number) => {
      const s = useCut.getState();
      const d = s.ghost ?? s.doc;
      if (!d) return;
      acc += ((now - last) / 1000) * d.fps * s.rate;
      last = now;
      const step = acc > 0 ? Math.floor(acc) : Math.ceil(acc);
      if (step !== 0) {
        acc -= step;
        const next = s.playhead + step;
        const end = endOf(d);
        if (next >= end || next <= 0) {
          s.seek(next >= end ? end : 0);
          s.setPlaying(false);
          return;
        }
        s.seek(next);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  /* ── fit the frame to the stage ── */
  const stageRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 360, h: 640 });
  const sw = doc?.size[0] ?? 720;
  const sh = doc?.size[1] ?? 1280;
  useLayoutEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const fit = () => {
      const cw = el.clientWidth - 28;
      const ch = el.clientHeight - 28;
      const ratio = sw / sh;
      let w = cw;
      let h = w / ratio;
      if (h > ch) {
        h = ch;
        w = h * ratio;
      }
      setBox({ w: Math.max(40, Math.floor(w)), h: Math.max(40, Math.floor(h)) });
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [sw, sh]);

  const fps = doc?.fps ?? 30;
  const live = useMemo(() => (doc ? liveClips(doc, playhead) : { video: [], audio: [] }), [doc, playhead]);
  const shown = doc ? topClipAt(doc, playhead) : null;
  const anySolo = Object.values(mix).some((m) => m.solo);

  // which roles are sounding right now, for the duck
  const sounding = useMemo(() => {
    const roles = new Set<string>();
    if (!doc) return roles;
    for (const t of doc.tracks) {
      if (t.kind !== "audio" || !t.role) continue;
      const m = mix[t.id];
      if (m?.mute || (anySolo && !m?.solo)) continue;
      if (clipAt(t, playhead)) roles.add(t.role);
    }
    return roles;
  }, [doc, playhead, mix, anySolo]);

  if (!doc) return null;
  const captions = doc.tracks.filter((t) => t.kind === "caption");
  const scrub = !playing || rate < 0 || rate > 2;

  return (
    <div className="cx-viewer">
      <div className="cx-viewer-head">
        <span className="cx-label" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {shown ? (binByHandle.get(shown.media)?.name ?? shown.media) : "—"}
        </span>
        <span className="cx-label">
          {doc.size[0]}×{doc.size[1]} · {doc.fps} fps
        </span>
        <span className="cx-tc">{timecode(playhead, fps)}</span>
      </div>
      <div className="cx-stage" ref={stageRef}>
        <div className="cx-frame" style={{ width: box.w, height: box.h }}>
          {live.video.map(({ clip, z }) => (
            <PictureEl
              key={clip.id}
              clip={clip}
              z={z}
              fps={fps}
              playhead={playhead}
              playing={playing && !scrub}
              item={binByHandle.get(clip.media)}
              preview={previews[clip.media]}
            />
          ))}
          {live.audio.map(({ clip, track }) => {
            const m = mix[track.id];
            const silent = !!m?.mute || (anySolo && !m?.solo);
            const ducked = !!track.duck_under && sounding.has(track.duck_under);
            const gain = Math.min(1, Math.pow(10, (clip.gain_db ?? 0) / 20)) * (ducked ? DUCK : 1);
            return (
              <SoundEl
                key={clip.id}
                clip={clip}
                fps={fps}
                playhead={playhead}
                playing={playing && !scrub}
                volume={silent ? 0 : gain}
                item={binByHandle.get(clip.media)}
                preview={previews[clip.media]}
              />
            );
          })}
          {!shown ? (
            <div className="cx-empty-frame">
              {endOf(doc) === 0 ? "An empty cut — bring media in from the bin" : "No picture at the playhead"}
            </div>
          ) : null}
          {captions.map((t) => {
            const q = (t.cues ?? []).find((c) => c.start <= playhead && playhead < c.end);
            if (!q) return null;
            const style = t.style ?? "preset:bold_center";
            const scale = style === "preset:bold_center" ? 0.062 : 0.042;
            return (
              <div key={t.id} className="cx-caption" data-style={style} style={{ fontSize: box.h * scale, zIndex: 50 }}>
                <span>{q.text}</span>
              </div>
            );
          })}
        </div>
        <span className="cx-honest">preview — export is exact</span>
      </div>
      <Transport fps={fps} end={endOf(doc)} />
    </div>
  );
}

/* The clips worth having an element for: in the window around the
   playhead, so the next one is decoded before the cut reaches it. */
function liveClips(doc: Doc, playhead: number): { video: Live[]; audio: Live[] } {
  const before = WINDOW_BEFORE_S * doc.fps;
  const after = WINDOW_AFTER_S * doc.fps;
  const video: Live[] = [];
  const audio: Live[] = [];
  const order = stackOrder(doc.tracks).filter((t) => t.kind === "video").reverse(); // V1 first = bottom
  order.forEach((t, i) => {
    for (const c of t.clips ?? []) {
      if (clipEnd(c) > playhead - before && c.at < playhead + after) video.push({ clip: c, track: t, z: i * 100 + 1 });
    }
  });
  for (const t of doc.tracks) {
    if (t.kind !== "audio") continue;
    for (const c of t.clips ?? []) {
      if (clipEnd(c) > playhead - before && c.at < playhead + after) audio.push({ clip: c, track: t, z: 0 });
    }
  }
  // within a track the later clip is on top (it is the incoming side of a crossfade)
  video.sort((a, b) => a.z - b.z || a.clip.at - b.clip.at);
  video.forEach((v, i) => (v.z = i + 1));
  return { video, audio };
}

function topClipAt(doc: Doc, frame: number): Clip | null {
  for (const t of stackOrder(doc.tracks)) {
    if (t.kind !== "video") continue;
    const c = clipAt(t, frame);
    if (c) return c;
  }
  return null;
}

/* where in its media a clip is at the playhead, in seconds */
const sourceTime = (clip: Clip, playhead: number, fps: number) =>
  (clip.src_in + Math.max(0, Math.min(playhead, clipEnd(clip) - 1) - clip.at)) / fps;

function useFollow(
  ref: React.RefObject<HTMLMediaElement | null>,
  clip: Clip,
  playhead: number,
  fps: number,
  playing: boolean,
) {
  const active = clip.at <= playhead && playhead < clipEnd(clip);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const want = active ? sourceTime(clip, playhead, fps) : clip.src_in / fps;
    if (active && playing) {
      if (Math.abs(el.currentTime - want) > 0.25) el.currentTime = want;
      if (el.paused) el.play().catch(() => undefined);
    } else {
      if (!el.paused) el.pause();
      if (Math.abs(el.currentTime - want) > 0.5 / fps) {
        try {
          el.currentTime = want;
        } catch {
          /* not seekable yet: loadedmetadata will land it */
        }
      }
    }
  }, [ref, active, playing, playhead, clip, fps]);
  return active;
}

function PictureEl({
  clip,
  z,
  fps,
  playhead,
  playing,
  item,
  preview,
}: {
  clip: Clip;
  z: number;
  fps: number;
  playhead: number;
  playing: boolean;
  item?: BinItem;
  preview?: Preview;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const active = useFollow(ref, clip, playhead, fps, playing);
  let opacity = active ? 1 : 0;
  const xf = clip.transition_in?.frames ?? 0;
  if (active && xf && playhead < clip.at + xf) opacity = (playhead - clip.at + 1) / (xf + 1);
  if (item?.kind === "image") {
    const src = item.url ?? item.poster;
    /* eslint-disable-next-line @next/next/no-img-element */
    return src ? <img className="cx-still" src={src} alt="" style={{ opacity, zIndex: z }} /> : null;
  }
  const src = preview?.proxy ?? item?.url ?? null;
  if (!src) return null;
  return (
    <video
      ref={ref}
      src={src}
      muted
      playsInline
      preload="auto"
      style={{ opacity, zIndex: z }}
      onLoadedData={(e) => {
        // a paused <video> sitting at 0 is never painted until something
        // seeks it; a hair past the wanted time forces the first frame up
        e.currentTarget.currentTime = Math.max(0.001, sourceTime(clip, Math.max(playhead, clip.at), fps));
      }}
    />
  );
}

function SoundEl({
  clip,
  fps,
  playhead,
  playing,
  volume,
  item,
  preview,
}: {
  clip: Clip;
  fps: number;
  playhead: number;
  playing: boolean;
  volume: number;
  item?: BinItem;
  preview?: Preview;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  useFollow(ref, clip, playhead, fps, playing);
  useEffect(() => {
    if (ref.current) ref.current.volume = Math.max(0, Math.min(1, volume));
  }, [volume]);
  // a clip's sound can come from a video file (its own sound) or an
  // audio upload; a <video> element plays both, and nothing is drawn
  const src = item?.kind === "audio" ? item.url : (preview?.proxy ?? item?.url ?? null);
  if (!src) return null;
  return <video ref={ref} src={src} playsInline preload="auto" style={{ display: "none" }} />;
}

/* ── transport ── */
function Transport({ fps, end }: { fps: number; end: number }) {
  const playing = useCut((s) => s.playing);
  const rate = useCut((s) => s.rate);
  const playhead = useCut((s) => s.playhead);
  const toggle = () => {
    const s = useCut.getState();
    if (s.playing) return s.setPlaying(false);
    if (s.playhead >= end) s.seek(0);
    s.setRate(1);
    s.setPlaying(true);
  };
  return (
    <div className="cx-transport">
      <span className="cx-left">
        <span className="cx-label">{playing && rate !== 1 ? `${rate > 0 ? "▶" : "◀"} ${Math.abs(rate)}×` : ""}</span>
      </span>
      <button type="button" className="cx-btn" title="To start (Home)" onClick={toStart}>
        <ChevronFirst />
      </button>
      <button type="button" className="cx-btn" title="Previous cut (↑)" onClick={() => jumpCut(-1)}>
        <SkipBack />
      </button>
      <button type="button" className="cx-btn" title="Back one frame (←)" onClick={() => nudge(-1)}>
        <StepBack />
      </button>
      <button type="button" className="cx-btn cx-play" title="Play / pause (Space)" onClick={toggle}>
        {playing ? <Pause /> : <Play />}
      </button>
      <button type="button" className="cx-btn" title="Forward one frame (→)" onClick={() => nudge(1)}>
        <StepForward />
      </button>
      <button type="button" className="cx-btn" title="Next cut (↓)" onClick={() => jumpCut(1)}>
        <SkipForward />
      </button>
      <button type="button" className="cx-btn" title="To end (End)" onClick={toEnd}>
        <ChevronLast />
      </button>
      <span className="cx-right">
        <span className="cx-tc">{timecode(playhead, fps)}</span>
        <span className="cx-tc dim">/ {timecode(end, fps)}</span>
      </span>
    </div>
  );
}

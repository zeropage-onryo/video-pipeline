"use client";

/* The timeline (T8, T10-T12, T14): Resolve's Edit page, drawn from the doc.

   - Track headers on the left (V over A over T, the NLE stack), each with
     its role and, for sound, Mute / Solo -- those two are PREVIEW state,
     never ops: muting a track to listen is not an edit.
   - A ruler whose ticks adapt to zoom, markers on it, a red playhead with
     a flag, the drag-to-scrub behaviour every editor has.
   - Clips at `at -> at + len` with a filmstrip (video) or waveform (audio)
     from T6's artifacts, a name strip on top, a crossfade drawn as the
     diagonal overlap it is.
   - VIRTUALISED horizontally: only what intersects the scrolled window
     (plus a screen either side) is in the DOM, so a long cut scrolls as
     cheaply as a short one.

   Every change a pointer makes ends in ONE op on release (move, trim,
   split, insert, set_cue). While the pointer is down the store's `ghost`
   is the doc drawn; the op's answer replaces it. */
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Eye, Lock, Type, Volume2 } from "lucide-react";
import { useCut, useDrawnDoc } from "@/lib/cut/store";
import { applyTransition, placeMedia, splitClip } from "@/lib/cut/actions";
import { TRANSITION_MIME } from "@/components/cut/transitions-tab";
import type { BinItem, Preview } from "@/lib/cut/api";
import { keyFrames } from "@/lib/cut/lanes";
import {
  clampPps,
  clampTrim,
  clipEnd,
  clipLength,
  endOf,
  findClip,
  framesToPx,
  ghostMove,
  ghostTrim,
  partners,
  pxToFrames,
  rulerLabel,
  sourceFrameAt,
  speedOf,
  rulerStep,
  snap,
  snapMove,
  snapPoints,
  stackOrder,
  visibleClips,
  visibleCues,
  type Clip,
  type Cue,
  type Doc,
  type Track,
} from "@/lib/cut/timeline";

export const MEDIA_MIME = "application/x-zpf-media";

const HEIGHT: Record<Track["kind"], number> = { video: 66, audio: 50, caption: 34 };
const SNAP_PX = 8;
const DRAG_THRESHOLD = 3;

type Drag =
  | {
      kind: "clip";
      mode: "move" | "head" | "tail";
      id: string;
      trackId: string;
      startX: number;
      startY: number;
      origin: Doc;
      moved: boolean;
    }
  | {
      kind: "cue";
      mode: "move" | "head" | "tail";
      id: string;
      trackId: string;
      startX: number;
      origin: Doc;
      moved: boolean;
    };

export function Timeline() {
  const doc = useDrawnDoc();
  const head = useCut((s) => s.doc);
  const pps = useCut((s) => s.pps);
  const playhead = useCut((s) => s.playhead);
  const selection = useCut((s) => s.selection);
  const tool = useCut((s) => s.tool);
  const mix = useCut((s) => s.mix);
  const previews = useCut((s) => s.previews);
  const bin = useCut((s) => s.bin);
  const highlight = useCut((s) => s.highlight);

  const scrollRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ left: 0, top: 0, width: 800, height: 300 });
  const [snapLine, setSnapLine] = useState<number | null>(null);
  const [bladeAt, setBladeAt] = useState<number | null>(null);
  const [drop, setDrop] = useState<{ trackId: string; frame: number } | null>(null);
  const drag = useRef<Drag | null>(null);
  const zoomAnchor = useRef<{ frame: number; x: number } | null>(null);
  const binByHandle = useMemo(() => new Map(bin.map((b) => [b.handle, b])), [bin]);

  const fps = doc?.fps ?? 30;
  const tracks = useMemo(() => (doc ? stackOrder(doc.tracks) : []), [doc]);
  const tops = useMemo(
    () => tracks.map((_, i) => tracks.slice(0, i).reduce((h, t) => h + HEIGHT[t.kind], 0)),
    [tracks],
  );
  const lanesHeight = tracks.reduce((h, t) => h + HEIGHT[t.kind], 0);
  const end = doc ? endOf(doc) : 0;
  const contentW = Math.max(framesToPx(end + fps * 10, fps, pps), view.width);
  const anySolo = Object.values(mix).some((m) => m.solo);

  // the visible window, a screen either side
  const from = Math.max(0, pxToFrames(view.left - view.width, fps, pps));
  const to = pxToFrames(view.left + view.width * 2, fps, pps);

  /* ── scroll + size ── */
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const read = () =>
      setView({ left: el.scrollLeft, top: el.scrollTop, width: el.clientWidth, height: el.clientHeight });
    read();
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(read);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", onScroll);
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, []);

  /* T14: pinch / Cmd+scroll zooms AROUND THE POINTER -- the frame under
     the cursor stays under the cursor. A plain wheel scrolls. */
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) {
        // a vertical wheel over a horizontal-first timeline scrolls sideways
        if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && e.shiftKey) {
          e.preventDefault();
          el.scrollLeft += e.deltaY;
        }
        return;
      }
      e.preventDefault();
      const s = useCut.getState();
      const f = s.doc?.fps ?? 30;
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const frame = ((el.scrollLeft + x) / s.pps) * f;
      const next = clampPps(s.pps * Math.exp(-e.deltaY * 0.012));
      zoomAnchor.current = { frame, x };
      s.setPps(next);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);
  // after a zoom, put the anchored frame back under the pointer (or the
  // playhead back where it was on screen, for +/- and the slider)
  const prevPps = useRef(pps);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || prevPps.current === pps) return;
    const anchor = zoomAnchor.current ?? {
      frame: useCut.getState().playhead,
      x: framesToPx(useCut.getState().playhead, fps, prevPps.current) - el.scrollLeft,
    };
    el.scrollLeft = Math.max(0, framesToPx(anchor.frame, fps, pps) - anchor.x);
    zoomAnchor.current = null;
    prevPps.current = pps;
  }, [pps, fps]);

  // keep the playhead on screen while it plays
  const playing = useCut((s) => s.playing);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !playing) return;
    const x = framesToPx(playhead, fps, pps);
    if (x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = x - 80;
    else if (x < el.scrollLeft) el.scrollLeft = Math.max(0, x - 80);
  }, [playhead, playing, fps, pps]);

  /* ── geometry ── */
  const frameAtClientX = useCallback(
    (clientX: number) => {
      const el = scrollRef.current;
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      return Math.max(0, pxToFrames(clientX - rect.left + el.scrollLeft, fps, pps));
    },
    [fps, pps],
  );
  const trackAtClientY = useCallback(
    (clientY: number): Track | null => {
      const el = scrollRef.current;
      if (!el) return null;
      const y = clientY - el.getBoundingClientRect().top + el.scrollTop;
      for (let i = 0; i < tracks.length; i++) {
        if (y >= tops[i] && y < tops[i] + HEIGHT[tracks[i].kind]) return tracks[i];
      }
      return null;
    },
    [tracks, tops],
  );
  const snapRadius = pxToFrames(SNAP_PX, fps, pps) || 1;

  /* ── ruler: click / drag to seek ── */
  const onRulerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const s = useCut.getState();
    s.setActiveViewer("program");
    s.setPlaying(false);
    s.seek(frameAtClientX(e.clientX));
    const move = (ev: PointerEvent) => useCut.getState().seek(frameAtClientX(ev.clientX));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  /* ── clips: select, move, trim, blade ── */
  const onClipDown = (e: ReactPointerEvent, clip: Clip, track: Track, mode: "move" | "head" | "tail") => {
    if (e.button !== 0 || !head) return;
    e.stopPropagation();
    e.preventDefault();
    const s = useCut.getState();
    s.setActiveViewer("program");
    if (s.tool === "blade") {
      let frame = frameAtClientX(e.clientX);
      if (s.snapOn) frame = snap(frame, snapPoints(head, s.playhead), snapRadius).frame;
      if (frame > clip.at && frame < clipEnd(clip)) splitClip(clip.id, frame);
      return;
    }
    const already = s.selection.kind === "clip" && s.selection.ids.includes(clip.id);
    if (e.shiftKey) s.select([clip.id], "clip", true);
    else if (!already) s.select([clip.id], "clip");
    drag.current = {
      kind: "clip",
      mode,
      id: clip.id,
      trackId: track.id,
      startX: e.clientX,
      startY: e.clientY,
      origin: head,
      moved: false,
    };
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragUp, { once: true });
    window.addEventListener("keydown", onDragKey);
  };

  const onCueDown = (e: ReactPointerEvent, cue: Cue, track: Track, mode: "move" | "head" | "tail") => {
    if (e.button !== 0 || !head) return;
    e.stopPropagation();
    e.preventDefault();
    const s = useCut.getState();
    s.select([cue.id], "cue", e.shiftKey);
    drag.current = { kind: "cue", mode, id: cue.id, trackId: track.id, startX: e.clientX, origin: head, moved: false };
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragUp, { once: true });
    window.addEventListener("keydown", onDragKey);
  };

  // the in-progress drag's answer, recomputed per pointermove
  const pendingOp = useRef<{ op: string; args: Record<string, unknown>; ghost: Doc } | null>(null);

  const onDragMove = (ev: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = ev.clientX - d.startX;
    if (!d.moved && Math.abs(dx) < DRAG_THRESHOLD && (d.kind === "cue" || Math.abs(ev.clientY - d.startY) < DRAG_THRESHOLD))
      return;
    d.moved = true;
    const s = useCut.getState();
    const f = d.origin.fps;
    const dF = pxToFrames(dx, f, s.pps);
    const radius = pxToFrames(SNAP_PX, f, s.pps) || 1;

    if (d.kind === "cue") {
      const t = d.origin.tracks.find((x) => x.id === d.trackId);
      const cue = t?.cues?.find((q) => q.id === d.id);
      if (!t || !cue) return;
      const points = s.snapOn ? snapPoints(d.origin, s.playhead, new Set([cue.id])).filter((p) => p !== cue.start && p !== cue.end) : [];
      let start = cue.start;
      let endF = cue.end;
      let snapped: number | null = null;
      if (d.mode === "move") {
        const r = s.snapOn ? snapMove(cue.start + dF, cue.end - cue.start, points, radius) : { at: cue.start + dF, snapped: null };
        start = Math.max(0, r.at);
        endF = start + (cue.end - cue.start);
        snapped = r.snapped;
      } else if (d.mode === "head") {
        const r = s.snapOn ? snap(cue.start + dF, points, radius) : { frame: cue.start + dF, snapped: null };
        start = Math.max(0, Math.min(r.frame, cue.end - 1));
        snapped = r.snapped;
      } else {
        const r = s.snapOn ? snap(cue.end + dF, points, radius) : { frame: cue.end + dF, snapped: null };
        endF = Math.max(r.frame, cue.start + 1);
        snapped = r.snapped;
      }
      const ghost = JSON.parse(JSON.stringify(d.origin)) as Doc;
      const gq = ghost.tracks.find((x) => x.id === d.trackId)?.cues?.find((q) => q.id === d.id);
      if (gq) {
        gq.start = start;
        gq.end = endF;
      }
      setSnapLine(snapped);
      useCut.setState({ ghost });
      pendingOp.current = {
        op: "set_cue",
        args: { track_id: d.trackId, cue_id: d.id, start, end: endF, text: cue.text },
        ghost,
      };
      return;
    }

    const found = findClip(d.origin, d.id);
    if (!found) return;
    const { clip } = found;
    const group = new Set(partners(d.origin, d.id).map((c) => c.id));
    const points = s.snapOn ? snapPoints(d.origin, s.playhead, group) : [];

    if (d.mode === "move") {
      const len = clipLength(clip);
      const r = s.snapOn ? snapMove(clip.at + dF, len, points, radius) : { at: clip.at + dF, snapped: null };
      // linked partners move too, so none of them may go below zero
      const minAt = Math.max(...partners(d.origin, d.id).map((p) => clip.at - p.at));
      const at = Math.max(minAt, r.at);
      const over = trackAtClientY(ev.clientY);
      const trackId = over && over.kind === found.track.kind ? over.id : found.track.id;
      const ghost = ghostMove(d.origin, d.id, at, trackId);
      setSnapLine(r.snapped);
      useCut.setState({ ghost });
      const args: Record<string, unknown> = { clip_id: d.id, at };
      if (trackId !== found.track.id) args.track_id = trackId;
      pendingOp.current = at === clip.at && trackId === found.track.id ? null : { op: "move", args, ghost };
      return;
    }

    // trim: head positive shortens from the front; tail positive shortens
    // from the back (ops.trim's signs)
    const ripple = ev.altKey;
    const mediaFrames = s.media[clip.media]?.frames ?? null;
    let h = 0;
    let t = 0;
    let snapped: number | null = null;
    if (d.mode === "head") {
      const r = s.snapOn ? snap(clip.at + dF, points, radius) : { frame: clip.at + dF, snapped: null };
      h = r.frame - clip.at;
      snapped = r.snapped;
    } else {
      const r = s.snapOn ? snap(clipEnd(clip) + dF, points, radius) : { frame: clipEnd(clip) + dF, snapped: null };
      t = clipEnd(clip) - r.frame;
      snapped = r.snapped;
    }
    const clamped = clampTrim(clip, h, t, mediaFrames);
    if (clip.at + clamped.head < 0) clamped.head = -clip.at;
    const ghost = ghostTrim(d.origin, d.id, clamped.head, clamped.tail, ripple);
    setSnapLine(snapped);
    useCut.setState({ ghost });
    pendingOp.current =
      clamped.head === 0 && clamped.tail === 0
        ? null
        : { op: "trim", args: { clip_id: d.id, head: clamped.head, tail: clamped.tail, ripple }, ghost };
  };

  const endDrag = () => {
    window.removeEventListener("pointermove", onDragMove);
    window.removeEventListener("keydown", onDragKey);
    drag.current = null;
    setSnapLine(null);
  };
  const onDragUp = () => {
    const d = drag.current;
    const pending = pendingOp.current;
    pendingOp.current = null;
    endDrag();
    if (!d?.moved || !pending) {
      useCut.setState({ ghost: null });
      return;
    }
    void useCut.getState().op(pending.op, pending.args, { ghost: pending.ghost, quiet: true });
  };
  // Escape cancels a drag in flight: the ghost goes, nothing is sent
  const onDragKey = (ev: KeyboardEvent) => {
    if (ev.key !== "Escape") return;
    pendingOp.current = null;
    window.removeEventListener("pointerup", onDragUp);
    endDrag();
    useCut.setState({ ghost: null });
  };

  /* ── drops from the media bin (T12) ── */
  const readDrop = (e: React.DragEvent): BinItem | null => {
    try {
      const raw = e.dataTransfer.getData(MEDIA_MIME);
      return raw ? (JSON.parse(raw) as BinItem) : null;
    } catch {
      return null;
    }
  };
  const onLaneDragOver = (e: React.DragEvent, track: Track) => {
    if (track.kind === "video" && e.dataTransfer.types.includes(TRANSITION_MIME)) {
      // a transition lands on a CUT: show the nearest one on this track
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      const frame = frameAtClientX(e.clientX);
      const cuts = (track.clips ?? []).filter((c) => c.at > 0).map((c) => c.at);
      const at = cuts.length ? cuts.reduce((a, b) => (Math.abs(b - frame) < Math.abs(a - frame) ? b : a)) : frame;
      setDrop((cur) => (cur && cur.trackId === track.id && cur.frame === at ? cur : { trackId: track.id, frame: at }));
      return;
    }
    if (!e.dataTransfer.types.includes(MEDIA_MIME)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    const s = useCut.getState();
    let frame = frameAtClientX(e.clientX);
    if (s.snapOn && head) frame = snap(frame, snapPoints(head, s.playhead), snapRadius).frame;
    setDrop((cur) => (cur && cur.trackId === track.id && cur.frame === frame ? cur : { trackId: track.id, frame }));
  };
  const onLaneDrop = (e: React.DragEvent, track: Track) => {
    const style = e.dataTransfer.getData(TRANSITION_MIME);
    if (style) {
      const at = drop?.frame ?? frameAtClientX(e.clientX);
      setDrop(null);
      e.preventDefault();
      const into = (track.clips ?? []).find((c) => c.at === at);
      applyTransition(style, into?.id, at);
      return;
    }
    const item = readDrop(e);
    const at = drop?.frame ?? frameAtClientX(e.clientX);
    setDrop(null);
    if (!item) return;
    e.preventDefault();
    void placeMedia(item, track.id, at);
  };

  const onLaneDown = (e: ReactPointerEvent) => {
    if (e.button !== 0) return;
    useCut.getState().setActiveViewer("program");
    useCut.getState().clearSelection();
  };
  const onLaneMove = (e: ReactPointerEvent) => {
    if (tool !== "blade") return;
    setBladeAt(frameAtClientX(e.clientX));
  };

  if (!doc) return null;

  const x = (f: number) => framesToPx(f, fps, pps);
  const step = rulerStep(fps, pps);
  const ticks: { f: number; major: boolean }[] = [];
  const tickFrom = Math.floor(pxToFrames(view.left, fps, pps) / step.minor) * step.minor;
  const tickTo = pxToFrames(view.left + view.width, fps, pps) + step.major;
  for (let f = Math.max(0, tickFrom); f <= tickTo && ticks.length < 1500; f += step.minor) {
    ticks.push({ f, major: f % step.major === 0 });
  }

  return (
    <div className="cx-tl" data-tool={tool}>
      <div className="cx-corner">
        <span className="cx-label">Tracks</span>
      </div>
      <div className="cx-ruler" onPointerDown={onRulerDown}>
        <div className="cx-ruler-inner" style={{ width: contentW, transform: `translateX(${-view.left}px)` }}>
          {ticks.map(({ f, major }) => (
            <span key={f}>
              <i className={`cx-tick${major ? " major" : ""}`} style={{ left: x(f) }} />
              {major ? (
                <span className="cx-tick-label" style={{ left: x(f) }}>
                  {rulerLabel(f, fps, step)}
                </span>
              ) : null}
            </span>
          ))}
          {(doc.markers ?? []).map((m, i) => (
            <i key={`${m.frame}-${i}`} className="cx-marker" style={{ left: x(m.frame) }} title={m.label} />
          ))}
          {highlight ? (
            <i className="cx-highlight" style={{ left: x(highlight.from), width: x(highlight.to - highlight.from) }} />
          ) : null}
          <i className="cx-playhead-flag" style={{ left: x(playhead) }} />
        </div>
      </div>

      <div className="cx-heads">
        <div className="cx-heads-inner" style={{ transform: `translateY(${-view.top}px)` }}>
          {tracks.map((t) => (
            <TrackHead key={t.id} track={t} />
          ))}
        </div>
      </div>

      <div className="cx-scroll" ref={scrollRef}>
        <div className="cx-lanes" style={{ width: contentW, height: Math.max(lanesHeight, view.height) }}>
          {tracks.map((t, i) => {
            const m = mix[t.id];
            const muted = t.kind === "audio" && (m?.mute || (anySolo && !m?.solo));
            return (
              <div
                key={t.id}
                className={`cx-lane${drop?.trackId === t.id ? " drop" : ""}`}
                data-muted={muted ? "1" : undefined}
                style={{ position: "absolute", top: tops[i], left: 0, right: 0, height: HEIGHT[t.kind] }}
                onPointerDown={onLaneDown}
                onPointerMove={onLaneMove}
                onPointerLeave={() => setBladeAt(null)}
                onDragOver={(e) => onLaneDragOver(e, t)}
                onDragLeave={() => setDrop(null)}
                onDrop={(e) => onLaneDrop(e, t)}
              >
                {t.kind === "caption"
                  ? visibleCues(t, from, to).map((q) => (
                      <CueView
                        key={q.id}
                        cue={q}
                        left={x(q.start)}
                        width={Math.max(2, x(q.end - q.start))}
                        selected={selection.kind === "cue" && selection.ids.includes(q.id)}
                        onDown={(e, mode) => onCueDown(e, q, t, mode)}
                      />
                    ))
                  : visibleClips(t, from, to).map((c) => (
                      <ClipView
                        key={c.id}
                        clip={c}
                        track={t}
                        fps={fps}
                        pps={pps}
                        left={x(c.at)}
                        width={Math.max(2, x(clipLength(c)))}
                        height={HEIGHT[t.kind]}
                        selected={selection.kind === "clip" && selection.ids.includes(c.id)}
                        item={binByHandle.get(c.media)}
                        preview={previews[c.media]}
                        onDown={(e, mode) => onClipDown(e, c, t, mode)}
                      />
                    ))}
                {drop?.trackId === t.id ? <i className="cx-snapline" style={{ left: x(drop.frame) }} /> : null}
              </div>
            );
          })}
          {highlight ? (
            <i className="cx-highlight" style={{ left: x(highlight.from), width: x(highlight.to - highlight.from) }} />
          ) : null}
          {snapLine !== null ? <i className="cx-snapline" style={{ left: x(snapLine) }} /> : null}
          {tool === "blade" && bladeAt !== null ? <i className="cx-blade-line" style={{ left: x(bladeAt) }} /> : null}
          <i className="cx-playhead" style={{ left: x(playhead) }} />
          {tracks.every((t) => !(t.clips?.length || t.cues?.length)) ? (
            <div className="cx-empty-tl">Drag media here from the bin — or double-click it to load it into Source</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ── one track header ── */
function TrackHead({ track }: { track: Track }) {
  const mix = useCut((s) => s.mix[track.id]);
  const setMix = useCut((s) => s.setMix);
  const Icon = track.kind === "video" ? Eye : track.kind === "audio" ? Volume2 : Type;
  const role =
    track.kind === "audio"
      ? `${track.role ?? "audio"}${track.duck_under ? ` · ducks ${track.duck_under}` : ""}`
      : track.kind === "caption"
        ? (track.style ?? "text").replace("preset:", "").replace(/_/g, " ")
        : "picture";
  return (
    <div className="cx-thead" data-kind={track.kind} data-role={track.role} style={{ height: HEIGHT[track.kind] }}>
      <span className="cx-tid">{track.id}</span>
      <span className="cx-trole">{role}</span>
      {track.kind === "audio" ? (
        <>
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
        </>
      ) : (
        <Icon size={12} strokeWidth={1.5} style={{ color: "var(--dimmer)" }} />
      )}
      <Lock size={11} strokeWidth={1.5} style={{ color: "var(--dimmer)", opacity: 0.5 }} aria-hidden />
    </div>
  );
}

/* ── one clip ── */
type ClipProps = {
  clip: Clip;
  track: Track;
  fps: number;
  pps: number;
  left: number;
  width: number;
  height: number;
  selected: boolean;
  item?: BinItem;
  preview?: Preview;
  onDown: (e: ReactPointerEvent, mode: "move" | "head" | "tail") => void;
};

const ClipView = memo(function ClipView({
  clip,
  track,
  fps,
  pps,
  left,
  width,
  height,
  selected,
  item,
  preview,
  onDown,
}: ClipProps) {
  const ensurePreview = useCut((s) => s.ensurePreview);
  useEffect(() => {
    ensurePreview(clip.media);
  }, [clip.media, ensurePreview]);
  const name = item?.name ?? clip.media;
  const xf = clip.transition_in?.frames ?? 0;
  const bodyH = height - 6 - 15;
  return (
    <div
      className="cx-clip"
      data-kind={track.kind}
      data-role={track.role}
      aria-selected={selected}
      style={{ left, width }}
      onPointerDown={(e) => onDown(e, "move")}
      title={`${name} · ${clip.id}`}
    >
      <span className="cx-clip-name">{name}</span>
      {clipLength(clip) !== clip.src_out - clip.src_in || clip.reverse ? (
        <span className="cx-clip-speed" title="Speed and direction (Inspector · Playback)">
          {clip.reverse ? "◀ " : ""}
          {clipLength(clip) !== clip.src_out - clip.src_in ? `${+speedOf(clip).toFixed(2)}×` : ""}
        </span>
      ) : null}
      {track.kind === "video" ? (
        <Filmstrip clip={clip} fps={fps} pps={pps} width={width} height={bodyH} preview={preview} poster={item?.poster} />
      ) : (
        <Waveform clip={clip} fps={fps} width={width} preview={preview} />
      )}
      {track.kind === "audio" && clip.gain_db ? (
        <span className="cx-gain">
          {clip.gain_db > 0 ? "+" : ""}
          {clip.gain_db} dB
        </span>
      ) : null}
      {xf ? <i className="cx-xfade" style={{ width: framesToPx(xf, fps, pps) }} /> : null}
      {track.kind === "video" && clip.lanes ? (
        <span className="cx-clip-keys">
          {keyFrames(clip).map((f) => (
            <i key={f} style={{ left: framesToPx(f, fps, pps) }} />
          ))}
        </span>
      ) : null}
      <i className="cx-edge head" onPointerDown={(e) => onDown(e, "head")} />
      <i className="cx-edge tail" onPointerDown={(e) => onDown(e, "tail")} />
    </div>
  );
});

/* The filmstrip: T6's sprite, one tile per slot along the clip, each tile
   showing the frame nearest the SOURCE time it sits over -- so a trimmed
   clip shows its own frames, not the file's first ones. Without a sprite
   the render's poster repeats, and without that the clip is its colour. */
function Filmstrip({
  clip,
  fps,
  pps,
  width,
  height,
  preview,
  poster,
}: {
  clip: Clip;
  fps: number;
  pps: number;
  width: number;
  height: number;
  preview?: Preview;
  poster?: string | null;
}) {
  const strip = preview?.filmstrip;
  if (!strip) {
    return poster ? <i className="cx-poster" style={{ backgroundImage: `url(${poster})` }} /> : null;
  }
  const scale = height / strip.frame_height;
  const tileW = Math.max(8, strip.frame_width * scale);
  const n = Math.min(80, Math.ceil(width / tileW));
  const tiles = [];
  for (let i = 0; i < n; i++) {
    const t = sourceFrameAt(clip, ((i * tileW) / pps) * fps) / fps;
    const idx = Math.min(strip.count - 1, Math.max(0, Math.floor(t / (strip.interval || 1))));
    tiles.push(
      <i
        key={i}
        style={{
          width: tileW,
          backgroundImage: `url(${strip.url})`,
          backgroundSize: `${strip.count * strip.frame_width * scale}px ${height}px`,
          backgroundPosition: `${-idx * strip.frame_width * scale}px 0`,
        }}
      />,
    );
  }
  return <div className="cx-strip">{tiles}</div>;
}

/* Waveform peaks (T6), fetched once per handle and drawn to a canvas
   for the clip's own source span. */
const peaksCache = new Map<string, Promise<number[]>>();
function loadPeaks(url: string): Promise<number[]> {
  let p = peaksCache.get(url);
  if (!p) {
    p = fetch(url)
      .then((r) => (r.ok ? r.json() : []))
      .then((j) => (Array.isArray(j) ? j : Array.isArray(j?.peaks) ? j.peaks : []))
      .catch(() => []);
    peaksCache.set(url, p);
  }
  return p;
}

function Waveform({ clip, fps, width, preview }: { clip: Clip; fps: number; width: number; preview?: Preview }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const wave = preview?.waveform;
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !wave) return;
    let alive = true;
    loadPeaks(wave.url).then((peaks) => {
      if (!alive || !peaks.length) return;
      const w = Math.min(4096, Math.max(1, Math.round(width)));
      const h = canvas.clientHeight || 30;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "rgba(255,255,255,0.62)";
      // a reversed clip draws its span backwards; speed only squeezes it
      const a = ((clip.reverse ? clip.src_out : clip.src_in) / fps) * wave.per_second;
      const b = ((clip.reverse ? clip.src_in : clip.src_out) / fps) * wave.per_second;
      const mid = h / 2;
      for (let px = 0; px < w; px++) {
        const i0 = Math.floor(a + ((b - a) * px) / w);
        const i1 = Math.max(i0 + 1, Math.floor(a + ((b - a) * (px + 1)) / w));
        let peak = 0;
        for (let i = i0; i < i1 && i < peaks.length; i++) peak = Math.max(peak, peaks[i] ?? 0);
        const bar = Math.max(0.5, peak * (h / 2 - 1));
        ctx.fillRect(px, mid - bar, 1, bar * 2);
      }
    });
    return () => {
      alive = false;
    };
  }, [wave, clip.src_in, clip.src_out, clip.reverse, fps, width]);
  if (!wave) return null;
  return <canvas ref={ref} className="cx-wave" />;
}

/* ── one caption cue ── */
function CueView({
  cue,
  left,
  width,
  selected,
  onDown,
}: {
  cue: Cue;
  left: number;
  width: number;
  selected: boolean;
  onDown: (e: ReactPointerEvent, mode: "move" | "head" | "tail") => void;
}) {
  return (
    <div
      className="cx-clip"
      data-kind="caption"
      aria-selected={selected}
      style={{ left, width }}
      onPointerDown={(e) => onDown(e, "move")}
      title={cue.text}
    >
      <span className="cx-clip-name">{cue.text}</span>
      <i className="cx-edge head" onPointerDown={(e) => onDown(e, "head")} />
      <i className="cx-edge tail" onPointerDown={(e) => onDown(e, "tail")} />
    </div>
  );
}

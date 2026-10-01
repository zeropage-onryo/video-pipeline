/* The editor's picture of a timeline document (src/cut/doc.py), as pure
   functions (2026-09-28). No React, no fetch, no imports: node --test
   loads this file as-is (web/tests/cut-timeline.test.mjs).

   TIME IS INTEGER FRAMES, exactly as in the doc. Seconds and pixels exist
   only at the edges -- `timecode` for the reader, `framesToPx` for the
   timeline -- so a drag that lands between two frames is rounded HERE,
   once, before it becomes an op, and the server never sees a fraction.

   Nothing in this file edits a document. The UI's edits are ops sent to
   the server (the validator is the one authority on what a doc may be);
   what lives here is how a doc is DRAWN, how a drag is snapped, and the
   ghost a drag leaves while its op is in flight. */

export type TransitionIn = { kind: "xfade"; frames: number; style?: string };
/* keyframe lanes, crop and opacity on a picture clip (lanes.ts, twin of
   src/cut/lanes.py); declared here so this file stays import-free */
type LaneKey = { frame: number; value: number; ease?: "linear" | "ease" | "hold" };
export type Clip = {
  id: string;
  media: string;
  src_in: number;
  src_out: number;
  at: number;
  /* legacy, always 1: speed is `dur` against the span (src/cut/doc.py) */
  speed?: number;
  /* timeline frames when retimed; absent = the span (1x) */
  dur?: number;
  reverse?: boolean;
  link?: string;
  gain_db?: number;
  transition_in?: TransitionIn;
  lanes?: { path: "zoom" | "x" | "y" | "rotation"; keys: LaneKey[] }[];
  crop?: { left?: number; right?: number; top?: number; bottom?: number };
  opacity?: number;
};
export type Cue = { id: string; start: number; end: number; text: string };
export type TrackKind = "video" | "audio" | "caption";
export type AudioRole = "voice" | "music" | "sfx";
export type Track = {
  id: string;
  kind: TrackKind;
  role?: AudioRole;
  duck_under?: AudioRole;
  style?: string;
  clips?: Clip[];
  cues?: Cue[];
};
export type Marker = { frame: number; label: string };
export type Doc = {
  fps: number;
  size: [number, number];
  duration: number;
  tracks: Track[];
  markers: Marker[];
};

export const ASPECTS = {
  "9:16": [720, 1280],
  "16:9": [1280, 720],
  "1:1": [1080, 1080],
} as const;
export type Aspect = keyof typeof ASPECTS;

export function aspectOf(size: [number, number]): Aspect | null {
  const [w, h] = size;
  for (const [name, [aw, ah]] of Object.entries(ASPECTS)) {
    if (w * ah === h * aw) return name as Aspect;
  }
  return null;
}

/* Source frames a clip uses, and the timeline frames it covers -- `dur`
   when sped, else the span. Speed is never stored: it is span / length. */
export const clipSpan = (c: Pick<Clip, "src_in" | "src_out">) => c.src_out - c.src_in;
export const clipLength = (c: Pick<Clip, "src_in" | "src_out" | "dur">) => c.dur ?? clipSpan(c);
export const clipEnd = (c: Clip) => c.at + clipLength(c);
export const speedOf = (c: Pick<Clip, "src_in" | "src_out" | "dur">) => {
  const len = clipLength(c);
  return len ? clipSpan(c) / len : 1;
};
export const isRetimed = (c: Clip) => !!c.reverse || clipLength(c) !== clipSpan(c);
/* the source frame shown `rel` timeline frames into the clip */
export const sourceFrameAt = (c: Clip, rel: number) =>
  c.reverse ? c.src_out - rel * speedOf(c) : c.src_in + rel * speedOf(c);
export const SPEED_MIN = 0.25;
export const SPEED_MAX = 4;

/* `mm:ss:ff` -- the transport's clock. Hours only when a cut runs that
   long, which a short never does. */
export function timecode(frame: number, fps: number): string {
  const f = Math.max(0, Math.round(frame));
  const totalSeconds = Math.floor(f / fps);
  const ff = f - totalSeconds * fps;
  const ss = totalSeconds % 60;
  const mm = Math.floor(totalSeconds / 60) % 60;
  const hh = Math.floor(totalSeconds / 3600);
  const two = (n: number) => String(n).padStart(2, "0");
  return (hh ? `${two(hh)}:` : "") + `${two(mm)}:${two(ss)}:${two(ff)}`;
}

/* a short human length for a card: 0:04, 1:12 */
export function shortDuration(frames: number, fps: number): string {
  const s = Math.round(frames / fps);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const secondsToFrames = (seconds: number, fps: number) =>
  Math.max(0, Math.floor(seconds * fps + 1e-6));

/* ── zoom ──
   Zoom is pixels per SECOND on a log scale, so every step of the slider
   feels the same size whether you are looking at a minute or at frames. */
export const MIN_PPS = 4;
export const MAX_PPS = 1200;
export const clampPps = (pps: number) => Math.min(MAX_PPS, Math.max(MIN_PPS, pps));
export const ppsToSlider = (pps: number) =>
  Math.log(clampPps(pps) / MIN_PPS) / Math.log(MAX_PPS / MIN_PPS);
export const sliderToPps = (t: number) =>
  clampPps(MIN_PPS * Math.pow(MAX_PPS / MIN_PPS, Math.min(1, Math.max(0, t))));

export const framesToPx = (frames: number, fps: number, pps: number) => (frames / fps) * pps;
export const pxToFrames = (px: number, fps: number, pps: number) => Math.round((px / pps) * fps);

/* The pps that fits `frames` into `width` pixels, with a little air. */
export function fitPps(frames: number, fps: number, width: number): number {
  const seconds = Math.max(frames / fps, 1);
  return clampPps((width * 0.92) / seconds);
}

/* Ruler ticks that adapt to zoom: a labelled major tick no closer than
   ~90px, minor ticks between. At frame-level zoom the minors are frames. */
export type RulerStep = { major: number; minor: number };
export function rulerStep(fps: number, pps: number): RulerStep {
  const pxPerFrame = pps / fps;
  const candidates = [1, 2, 5, 10, 15].map((n) => ({ major: n, frames: true }))
    .concat([1, 2, 5, 10, 15, 30, 60, 120, 300, 600].map((n) => ({ major: n * fps, frames: false })));
  for (const c of candidates) {
    if (c.frames && c.major >= fps) continue;
    if (c.major * pxPerFrame >= 90) {
      const minorDiv = c.major === 1 ? 1 : c.major % 5 === 0 ? 5 : c.major % 2 === 0 ? 2 : c.major;
      let minor = Math.max(1, Math.round(c.major / minorDiv));
      // frame ticks when a frame is wide enough to see
      if (!c.frames && c.major === fps && pxPerFrame >= 6) minor = 1;
      return { major: c.major, minor };
    }
  }
  return { major: 600 * fps, minor: 60 * fps };
}

export function rulerLabel(frame: number, fps: number, step: RulerStep): string {
  if (step.major < fps) {
    const s = Math.floor(frame / fps);
    const f = frame % fps;
    return f === 0 ? `${s}s` : `${f}f`;
  }
  const s = Math.round(frame / fps);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/* ── what the tracks look like ── */
export function trackLabel(t: Track): string {
  if (t.kind === "audio" && t.role) return `${t.id} · ${t.role}`;
  if (t.kind === "caption") return `${t.id} · text`;
  return t.id;
}

/* Tracks in the order an NLE stacks them: video highest-numbered on top
   (V2 over V1, picture over picture), then audio, then text -- text at the
   bottom so captions read under the sound that carries them. */
export function stackOrder(tracks: Track[]): Track[] {
  const n = (id: string) => Number(id.replace(/\D+/g, "")) || 0;
  const v = tracks.filter((t) => t.kind === "video").sort((a, b) => n(b.id) - n(a.id));
  const a = tracks.filter((t) => t.kind === "audio").sort((x, y) => n(x.id) - n(y.id));
  const c = tracks.filter((t) => t.kind === "caption").sort((x, y) => n(x.id) - n(y.id));
  return [...v, ...a, ...c];
}

export function findClip(doc: Doc, id: string): { track: Track; clip: Clip } | null {
  for (const track of doc.tracks) {
    for (const clip of track.clips ?? []) if (clip.id === id) return { track, clip };
  }
  return null;
}

export function findCue(doc: Doc, id: string): { track: Track; cue: Cue } | null {
  for (const track of doc.tracks) {
    for (const cue of track.cues ?? []) if (cue.id === id) return { track, cue };
  }
  return null;
}

/* the clip and everything linked to it, either direction (doc.partners) */
export function partners(doc: Doc, id: string): Clip[] {
  const found = findClip(doc, id);
  if (!found) return [];
  const root = found.clip.link ?? id;
  const out: Clip[] = [];
  for (const t of doc.tracks) {
    for (const c of t.clips ?? []) if (c.id === root || c.link === root) out.push(c);
  }
  return out;
}

/* Only the clips that intersect [from, to): the timeline draws a window,
   not the whole cut, so a long project stays cheap to scroll. */
export function visibleClips(t: Track, from: number, to: number): Clip[] {
  return (t.clips ?? []).filter((c) => clipEnd(c) > from && c.at < to);
}
export function visibleCues(t: Track, from: number, to: number): Cue[] {
  return (t.cues ?? []).filter((q) => q.end > from && q.start < to);
}

/* The clip under the playhead on a track, for the preview and for split.
   With a crossfade two clips cover the same frame; the INCOMING one (the
   later `at`) is on top, as it is in the render. */
export function clipAt(t: Track, frame: number): Clip | null {
  let hit: Clip | null = null;
  for (const c of t.clips ?? []) {
    if (c.at <= frame && frame < clipEnd(c) && (!hit || c.at > hit.at)) hit = c;
  }
  return hit;
}

/* ── snapping ──
   Candidates are cut points a person aims at: the playhead, every clip's
   edges, every cue's edges, every marker, and zero. The dragged clip's own
   group is excluded, or it snaps to where it already is. */
export function snapPoints(doc: Doc, playhead: number, exclude: Set<string> = new Set()): number[] {
  const pts = new Set<number>([0, playhead]);
  for (const t of doc.tracks) {
    for (const c of t.clips ?? []) {
      if (exclude.has(c.id)) continue;
      pts.add(c.at);
      pts.add(clipEnd(c));
    }
    for (const q of t.cues ?? []) {
      pts.add(q.start);
      pts.add(q.end);
    }
  }
  for (const m of doc.markers ?? []) pts.add(m.frame);
  return [...pts].sort((a, b) => a - b);
}

/* Snap `frame` to the nearest point within `radius` frames, or leave it. */
export function snap(frame: number, points: number[], radius: number): { frame: number; snapped: number | null } {
  let best: number | null = null;
  for (const p of points) {
    if (Math.abs(p - frame) <= radius && (best === null || Math.abs(p - frame) < Math.abs(best - frame))) best = p;
  }
  return best === null ? { frame, snapped: null } : { frame: best, snapped: best };
}

/* A moved clip snaps by whichever of its two edges lands closer to a
   point: aiming its END at the playhead is as common as aiming its start. */
export function snapMove(
  at: number,
  length: number,
  points: number[],
  radius: number,
): { at: number; snapped: number | null } {
  const head = snap(at, points, radius);
  const tail = snap(at + length, points, radius);
  const dh = head.snapped === null ? Infinity : Math.abs(head.snapped - at);
  const dt = tail.snapped === null ? Infinity : Math.abs(tail.snapped - (at + length));
  if (dh === Infinity && dt === Infinity) return { at, snapped: null };
  return dh <= dt ? { at: head.frame, snapped: head.snapped } : { at: tail.frame - length, snapped: tail.snapped };
}

/* ── ghosts ──
   While a move or trim op is in flight, the timeline draws the result it
   EXPECTS -- the optimistic half of T10. These mirror src/cut/ops.py's
   move and trim closely enough to draw; the server's doc replaces the
   ghost the moment it answers, and a refusal rolls it back. */
function cloneDoc(doc: Doc): Doc {
  return JSON.parse(JSON.stringify(doc)) as Doc;
}

export function ghostMove(doc: Doc, clipId: string, at: number, trackId?: string): Doc {
  const out = cloneDoc(doc);
  const found = findClip(out, clipId);
  if (!found) return doc;
  const delta = at - found.clip.at;
  for (const c of partners(out, clipId)) c.at += delta;
  if (trackId && trackId !== found.track.id) {
    const dest = out.tracks.find((t) => t.id === trackId);
    if (dest && dest.kind === found.track.kind) {
      found.track.clips = (found.track.clips ?? []).filter((c) => c.id !== clipId);
      dest.clips = [...(dest.clips ?? []), found.clip];
    }
  }
  return out;
}

export function ghostTrim(doc: Doc, clipId: string, head: number, tail: number, ripple: boolean): Doc {
  const out = cloneDoc(doc);
  if (!findClip(out, clipId)) return doc;
  for (const t of out.tracks) {
    const ordered = [...(t.clips ?? [])].sort((a, b) => a.at - b.at);
    for (const c of ordered) {
      if (!partners(out, clipId).includes(c)) continue;
      const followers = ordered.filter((o) => o.at > c.at);
      if (isRetimed(c)) {
        // timeline frames in, the source moves by the speed (ops.trim)
        const sp = speedOf(c);
        const before = clipLength(c);
        let sh = Math.round(head * sp);
        let st = Math.round(tail * sp);
        if (c.reverse) [sh, st] = [st, sh];
        c.src_in += sh;
        c.src_out -= st;
        c.dur = before - head - tail;
      } else {
        c.src_in += head;
        c.src_out -= tail;
      }
      if (ripple) for (const f of followers) f.at -= head + tail;
      else c.at += head;
    }
  }
  return out;
}

/* How far a clip may be trimmed: never to nothing, never before the
   start of its media, never past its end (when the media's length is
   known). Returns the clamped head/tail. */
export function clampTrim(
  clip: Clip,
  head: number,
  tail: number,
  mediaFrames: number | null,
): { head: number; tail: number } {
  const len = clipLength(clip);
  const sp = speedOf(clip);
  // how far each END may extend, in timeline frames: the head of a
  // reversed clip is its source's end
  const room = (src: number) => -Math.floor(src / sp);
  const before = clip.src_in;
  const after = mediaFrames !== null ? mediaFrames - clip.src_out : Infinity;
  let h = Math.max(head, room(clip.reverse ? after : before));
  let t = after === Infinity && !clip.reverse ? tail : Math.max(tail, room(clip.reverse ? before : after));
  if (len - h - t < 1) {
    if (head !== 0) h = len - t - 1;
    else t = len - h - 1;
  }
  return { head: h, tail: t };
}

/* The last frame any clip or cue on the timeline ends at, or the cut's
   own duration when that is later. */
export function endOf(doc: Doc): number {
  let end = 0;
  for (const t of doc.tracks) {
    for (const c of t.clips ?? []) end = Math.max(end, clipEnd(c));
    for (const q of t.cues ?? []) end = Math.max(end, q.end);
  }
  return Math.max(end, doc.duration || 0);
}

/* The first free frame at the END of a track: where "append" puts a clip. */
export function trackEnd(t: Track): number {
  let end = 0;
  for (const c of t.clips ?? []) end = Math.max(end, clipEnd(c));
  for (const q of t.cues ?? []) end = Math.max(end, q.end);
  return end;
}

/* Is `frame` a cut point on this track (not inside any clip)? insert
   refuses a frame inside a clip, so the drop target moves to the nearest
   edge rather than asking the server a question it will say no to. */
export function nearestCutPoint(t: Track, frame: number): number {
  for (const c of t.clips ?? []) {
    if (c.at < frame && frame < clipEnd(c)) {
      return frame - c.at < clipEnd(c) - frame ? c.at : clipEnd(c);
    }
  }
  return frame;
}

/* ── a one-line summary of an op, for toasts and the history ── */
export function describeOp(op: string, args: Record<string, unknown>, fps: number): string {
  const f = (v: unknown) => (typeof v === "number" ? `${(v / fps).toFixed(2)}s` : "");
  switch (op) {
    case "split":
      return `Split ${args.clip_id} at ${f(args.frame)}`;
    case "move":
      return `Moved ${args.clip_id} to ${f(args.at)}`;
    case "trim":
      return `Trimmed ${args.clip_id}`;
    case "ripple_delete":
      return `Ripple-deleted ${args.clip_id}`;
    case "lift":
      return `Lifted ${args.clip_id}`;
    case "insert":
      return `Inserted a clip at ${f(args.at)}`;
    case "set_gain":
      return `Gain ${args.db} dB`;
    case "add_transition":
      return `Transition ${args.frames}f${args.style ? ` · ${String(args.style)}` : ""}`;
    case "set_transition":
      return `Transition ${args.style ? String(args.style) : ""}${args.frames ? ` ${args.frames}f` : ""}`.trim();
    case "remove_transition":
      return `Hard cut into ${args.clip_id}`;
    case "set_speed":
      return `Speed ${args.speed}×`;
    case "set_reverse":
      return args.on === false ? "Plays forwards" : "Reversed";
    default:
      return op.replace(/_/g, " ");
  }
}

"use client";

/* The editor's verbs, in one place (2026-09-28). The keyboard, the tool
   strip, the inspector and Editor mode's command palette all call these,
   so a shortcut and a button can never mean two different edits. Each one
   ends in exactly one op (or none, with a reason) -- see store.ts for
   why the UI never writes a doc. */
import type { BinItem } from "@/lib/cut/api";
import { useCut } from "@/lib/cut/store";
import {
  clipAt,
  clipEnd,
  endOf,
  findClip,
  nearestCutPoint,
  stackOrder,
  trackEnd,
  type Doc,
  type Track,
} from "@/lib/cut/timeline";

/* an image has no length of its own: it lands as a 5 s still */
export const STILL_SECONDS = 5;
/* what a drop asks for when a render's length is not known yet */
const UNPROBED_SECONDS = 600;

const state = () => useCut.getState();

function doc(): Doc | null {
  return state().doc;
}

/* The clips `B` / Cmd+B cut: the selected ones under the playhead, else
   whatever the topmost picture track shows there, else the first audio
   clip there. Linked sound follows its picture (ops.split does that). */
export function splitAtPlayhead(): void {
  const d = doc();
  if (!d) return;
  const { playhead, selection } = state();
  const inside = (id: string) => {
    const f = findClip(d, id);
    return f && f.clip.at < playhead && playhead < clipEnd(f.clip) ? f.clip : null;
  };
  let target: string | null = null;
  if (selection.kind === "clip") target = selection.ids.map(inside).find(Boolean)?.id ?? null;
  if (!target) {
    for (const t of stackOrder(d.tracks)) {
      if (t.kind === "caption") continue;
      const c = clipAt(t, playhead);
      if (c && c.at < playhead) {
        target = c.id;
        break;
      }
    }
  }
  if (!target) {
    state().toast("Nothing under the playhead to split", "err");
    return;
  }
  void state().op("split", { clip_id: target, frame: playhead });
}

export function splitClip(clipId: string, frame: number): void {
  void state().op("split", { clip_id: clipId, frame });
}

/* Delete lifts (the gap stays); Shift+Delete ripples (the gap closes).
   A selected caption cue is deleted as a cue. */
export async function deleteSelection(ripple: boolean): Promise<void> {
  const d = doc();
  const { selection } = state();
  if (!d || !selection.ids.length) return;
  if (selection.kind === "cue") {
    for (const id of selection.ids) {
      const track = d.tracks.find((t) => (t.cues ?? []).some((q) => q.id === id));
      if (track) await state().op("delete_cue", { track_id: track.id, cue_id: id });
    }
    return;
  }
  // one op per LINK GROUP: deleting a clip deletes its partners, so asking
  // again for the partner would be asking about a clip that is gone
  const seen = new Set<string>();
  for (const id of selection.ids) {
    const f = findClip(state().doc ?? d, id);
    if (!f) continue;
    const root = f.clip.link ?? f.clip.id;
    if (seen.has(root)) continue;
    seen.add(root);
    await state().op(ripple ? "ripple_delete" : "lift", { clip_id: id });
  }
}

export function addMarkerAtPlayhead(label?: string): void {
  const d = doc();
  if (!d) return;
  const n = (d.markers?.length ?? 0) + 1;
  void state().op("add_marker", { frame: state().playhead, label: label ?? `Marker ${n}` });
}

/* Where a bin item lands when nobody said where: picture on V1, sound on
   the music track (a dropped audio file is almost always a bed), each at
   the END of its track. */
function defaultTrack(d: Doc, item: BinItem): Track | undefined {
  if (item.kind === "audio") {
    const audio = d.tracks.filter((t) => t.kind === "audio");
    return audio.find((t) => t.role === "music") ?? audio[0];
  }
  return d.tracks.find((t) => t.kind === "video");
}

export function mediaFrames(item: BinItem, fps: number): number {
  if (item.kind === "image") return STILL_SECONDS * fps;
  const s = item.seconds ?? 0;
  return Math.max(1, Math.floor(s * fps + 1e-6));
}

/* THE insert (T12): a bin item onto a track at a frame. Picture with
   sound lands with its linked audio on the sfx track, the way a camera
   clip lands in any NLE. A frame inside a clip moves to that clip's
   nearest edge -- insert refuses a frame inside a clip, and a drop that
   silently splits somebody's shot is worse than one that lands beside it. */
export async function placeMedia(
  item: BinItem,
  trackId?: string,
  at?: number,
  range?: { src_in: number; src_out: number },
): Promise<boolean> {
  const d = doc();
  if (!d) return false;
  const track = trackId ? d.tracks.find((t) => t.id === trackId) : defaultTrack(d, item);
  if (!track) {
    state().toast(item.kind === "audio" ? "This cut has no audio track" : "This cut has no video track", "err");
    return false;
  }
  if (track.kind === "caption") {
    state().toast("Text tracks take captions, not media — use the Text tab", "err");
    return false;
  }
  // has_audio is null for a render nobody has probed yet: unknown, not "no"
  if (track.kind === "audio" && item.has_audio === false) {
    state().toast(`${item.name} has no sound to put on ${track.id}`, "err");
    return false;
  }
  if (track.kind === "video" && item.kind === "audio") {
    state().toast("That is a sound file — drop it on an audio track", "err");
    return false;
  }
  // a render nobody has probed yet has no length on its bin row; ask for
  // a generous one and let the server's refusal name the real length
  const unknownLength = item.kind === "video" && !item.seconds && !range;
  const frames = unknownLength ? UNPROBED_SECONDS * d.fps : mediaFrames(item, d.fps);
  const where = at === undefined ? trackEnd(track) : nearestCutPoint(track, Math.max(0, at));
  const args: Record<string, unknown> = {
    track_id: track.id,
    clip: range
      ? { media: item.handle, src_in: Math.max(0, range.src_in), src_out: Math.min(frames, range.src_out) }
      : { media: item.handle, src_in: 0, src_out: frames },
    at: where,
  };
  if (track.kind === "video" && item.kind === "video" && item.has_audio !== false) {
    const audio = d.tracks.filter((t) => t.kind === "audio");
    const sound = audio.find((t) => t.role === "sfx") ?? audio.find((t) => t.role === "voice") ?? audio[0];
    if (sound) args.sound_track = sound.id;
  }
  const unsure = unknownLength || (item.has_audio === null && !!args.sound_track);
  if (!unsure) return state().op("insert", args);

  // Up to two silent corrections, each read off the validator's own words:
  // "src_out N is past the end of <h> (F frames)" and "<h> has no sound".
  for (let tries = 0; tries < 3; tries++) {
    if (await state().op("insert", args, { silent: tries < 2 })) return true;
    const problems = state().lastError?.problems ?? [];
    let changed = false;
    for (const p of problems) {
      const end = new RegExp(`past the end of ${item.handle} \\((\\d+) frames\\)`).exec(p);
      if (end && Number(end[1]) > 0) {
        (args.clip as { src_out: number }).src_out = Number(end[1]);
        changed = true;
      }
      if (p.includes(`${item.handle} has no sound`) && args.sound_track) {
        delete args.sound_track;
        changed = true;
      }
    }
    if (!changed) {
      if (tries < 2) state().toast(problems.slice(0, 3).join(" · ") || "the insert failed", "err");
      return false;
    }
  }
  return false;
}

/* frame navigation */
export function nudge(frames: number): void {
  const s = state();
  s.setPlaying(false);
  s.seek(s.playhead + frames);
}
export function toStart(): void {
  state().setPlaying(false);
  state().seek(0);
}
export function toEnd(): void {
  const d = doc();
  state().setPlaying(false);
  state().seek(d ? endOf(d) : 0);
}

/* The next / previous cut point on any track, for the transport's
   jump buttons (Resolve's up/down arrows). */
export function jumpCut(direction: 1 | -1): void {
  const d = doc();
  if (!d) return;
  const here = state().playhead;
  const pts = new Set<number>([0, endOf(d)]);
  for (const t of d.tracks) {
    for (const c of t.clips ?? []) {
      pts.add(c.at);
      pts.add(clipEnd(c));
    }
  }
  const sorted = [...pts].sort((a, b) => a - b);
  const next = direction > 0 ? sorted.find((p) => p > here) : [...sorted].reverse().find((p) => p < here);
  if (next !== undefined) {
    state().setPlaying(false);
    state().seek(next);
  }
}

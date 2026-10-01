/* Keyframe lanes on a picture clip -- the twin of src/cut/lanes.py, for
   the preview and the Inspector (2026-10-01). Pure, no imports, so
   node --test loads it as-is (web/tests/cut-lanes.test.mjs pins it to the
   same numbers as tests/test_cut_keyframes.py).

   A lane's key `frame` is CLIP-RELATIVE: 0 is the clip's first frame on
   the timeline. One key is a constant. `ease` belongs to the key a
   segment starts at. Crop and opacity are static per clip. */

export type Ease = "linear" | "ease" | "hold";
export type Key = { frame: number; value: number; ease?: Ease };
export type Lane = { path: LanePath; keys: Key[] };
export type LanePath = "zoom" | "x" | "y" | "rotation" | "volume";
export type Crop = { left?: number; right?: number; top?: number; bottom?: number };
export type Looked = { lanes?: Lane[]; crop?: Crop; opacity?: number };

/* path -> [min, max, default]; x / y are fractions of the canvas */
export const PATHS: Record<LanePath, [number, number, number]> = {
  zoom: [0.1, 4, 1],
  x: [-1, 1, 0],
  y: [-1, 1, 0],
  rotation: [-360, 360, 0],
  /* a SOUND clip's one lane, in dB (lanes.AUDIO_PATHS) */
  volume: [-60, 12, 0],
};
export const EASES: Ease[] = ["linear", "ease", "hold"];
export const MAX_CROP = 0.45;

export const fallback = (path: LanePath) => PATHS[path][2];

export function laneOf(clip: Looked, path: LanePath): Lane | undefined {
  return (clip.lanes ?? []).find((l) => l.path === path);
}

const shape = (u: number, ease: Ease | undefined) => (ease === "hold" ? 0 : ease === "ease" ? u * u * (3 - 2 * u) : u);

export function valueAt(keys: Key[], frame: number, dflt: number): number {
  if (!keys.length) return dflt;
  if (frame <= keys[0].frame) return keys[0].value;
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (frame < b.frame) {
      const span = b.frame - a.frame;
      const u = span ? (frame - a.frame) / span : 1;
      return a.value + (b.value - a.value) * shape(u, a.ease);
    }
  }
  return keys[keys.length - 1].value;
}

export function valueOf(clip: Looked, path: LanePath, frame: number): number {
  return valueAt(laneOf(clip, path)?.keys ?? [], frame, fallback(path));
}

/* the look of a clip at a clip-relative frame, for the preview */
export function lookAt(clip: Looked, frame: number) {
  return {
    zoom: valueOf(clip, "zoom", frame),
    x: valueOf(clip, "x", frame),
    y: valueOf(clip, "y", frame),
    rotation: valueOf(clip, "rotation", frame),
    opacity: clip.opacity ?? 1,
    crop: {
      left: clip.crop?.left ?? 0,
      right: clip.crop?.right ?? 0,
      top: clip.crop?.top ?? 0,
      bottom: clip.crop?.bottom ?? 0,
    },
  };
}

/* frames (clip-relative) that hold a key on a lane that ANIMATES -- the
   timeline's diamonds and the Inspector's prev / next */
export function keyFrames(clip: Looked, path?: LanePath): number[] {
  const out = new Set<number>();
  for (const l of clip.lanes ?? []) {
    if (path && l.path !== path) continue;
    if (l.keys.length < 2 && !path) continue;
    for (const k of l.keys) out.add(k.frame);
  }
  return [...out].sort((a, b) => a - b);
}

/* What set_key would make of a lane: a ghost for the live preview while a
   slider is dragged (the server's op is still the edit). */
export function withKey<T extends Looked>(clip: T, path: LanePath, frame: number, value: number, ease?: Ease): T {
  const lanes = (clip.lanes ?? []).map((l) => ({ ...l, keys: [...l.keys] }));
  let lane = lanes.find((l) => l.path === path);
  if (!lane) {
    lane = { path, keys: [] };
    lanes.push(lane);
  }
  const prev = lane.keys.find((k) => k.frame === frame);
  lane.keys = [...lane.keys.filter((k) => k.frame !== frame), { frame, value, ease: ease ?? prev?.ease ?? "linear" }].sort(
    (a, b) => a.frame - b.frame,
  );
  return { ...clip, lanes };
}

/* Fitting the (cropped) picture into the frame, as render.py does:
   `force_original_aspect_ratio=decrease` on the cropped source. Returns
   the visible picture's box in frame pixels, and the full (uncropped)
   video element's box, positioned so the crop lines up -- the element is
   then clipped with an inset of the crop fractions. */
export function fitBoxes(frameW: number, frameH: number, mediaW: number, mediaH: number, crop: Required<Crop>) {
  const cw = mediaW * (1 - crop.left - crop.right);
  const ch = mediaH * (1 - crop.top - crop.bottom);
  const scale = Math.min(frameW / cw, frameH / ch);
  const picW = cw * scale;
  const picH = ch * scale;
  const pic = { left: (frameW - picW) / 2, top: (frameH - picH) / 2, width: picW, height: picH };
  const elW = mediaW * scale;
  const elH = mediaH * scale;
  const el = { left: -crop.left * elW, top: -crop.top * elH, width: elW, height: elH };
  return { pic, el };
}

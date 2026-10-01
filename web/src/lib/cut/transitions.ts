/* Transition styles -- the twin of src/cut/doc.py's TRANSITION_STYLES
   (2026-10-01); tests/test_cut_transitions.py checks this list names every
   style the server renders. Pure, no imports, so node --test loads it.

   The render is ffmpeg's xfade (exact). The PREVIEW is an approximation
   drawn on the incoming picture only, with CSS: wipes and irises as a
   clip-path, slides as a transform, everything else as the plain fade.
   The Transitions tab and the viewer both read `lookAt`, so a tile shows
   what the preview will. */

export type TransitionStyle = { style: string; group: string; label: string };

export const GROUPS = ["Fades", "Wipes", "Slides", "Shapes", "Slices"] as const;

const S = (group: string, pairs: [string, string][]): TransitionStyle[] =>
  pairs.map(([style, label]) => ({ style, group, label }));

export const STYLES: TransitionStyle[] = [
  ...S("Fades", [
    ["fade", "Crossfade"], ["dissolve", "Dissolve"], ["fadeblack", "Dip to black"],
    ["fadewhite", "Dip to white"], ["fadegrays", "Fade through grey"], ["fadefast", "Fast fade"],
    ["fadeslow", "Slow fade"], ["hblur", "Blur"], ["pixelize", "Pixelate"], ["distance", "Distance"],
  ]),
  ...S("Wipes", [
    ["wipeleft", "Wipe left"], ["wiperight", "Wipe right"], ["wipeup", "Wipe up"], ["wipedown", "Wipe down"],
    ["wipetl", "Wipe top-left"], ["wipetr", "Wipe top-right"], ["wipebl", "Wipe bottom-left"],
    ["wipebr", "Wipe bottom-right"], ["smoothleft", "Smooth left"], ["smoothright", "Smooth right"],
    ["smoothup", "Smooth up"], ["smoothdown", "Smooth down"], ["diagtl", "Diagonal top-left"],
    ["diagtr", "Diagonal top-right"], ["diagbl", "Diagonal bottom-left"], ["diagbr", "Diagonal bottom-right"],
    ["radial", "Clock wipe"],
  ]),
  ...S("Slides", [
    ["slideleft", "Slide left"], ["slideright", "Slide right"], ["slideup", "Slide up"], ["slidedown", "Slide down"],
    ["coverleft", "Cover left"], ["coverright", "Cover right"], ["coverup", "Cover up"], ["coverdown", "Cover down"],
    ["revealleft", "Reveal left"], ["revealright", "Reveal right"], ["revealup", "Reveal up"],
    ["revealdown", "Reveal down"],
  ]),
  ...S("Shapes", [
    ["circleopen", "Iris open"], ["circleclose", "Iris close"], ["circlecrop", "Circle crop"],
    ["rectcrop", "Box crop"], ["vertopen", "Barn door open"], ["vertclose", "Barn door close"],
    ["horzopen", "Split open"], ["horzclose", "Split close"], ["squeezeh", "Squeeze across"],
    ["squeezev", "Squeeze down"], ["zoomin", "Zoom in"],
  ]),
  ...S("Slices", [
    ["hlslice", "Slices left"], ["hrslice", "Slices right"], ["vuslice", "Slices up"], ["vdslice", "Slices down"],
    ["hlwind", "Wind left"], ["hrwind", "Wind right"], ["vuwind", "Wind up"], ["vdwind", "Wind down"],
  ]),
];

export const DEFAULT_STYLE = "fade";
export const labelOf = (style?: string) => STYLES.find((s) => s.style === (style ?? DEFAULT_STYLE))?.label ?? style ?? "Crossfade";

/* How long a transition is when it is first dropped: half a second. */
export const defaultFrames = (fps: number) => Math.max(1, Math.round(fps / 2));

const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

/* The incoming picture's look at progress p (0 -> 1) through the
   transition. Returns the CSS to merge onto it; {} means "no change"
   (the caller still applies the plain opacity fade when `fade` is true). */
export function lookAt(style: string | undefined, p: number): { css: Record<string, string | number>; fade: boolean } {
  const q = Math.max(0, Math.min(1, p));
  const r = 1 - q;
  const clip = (v: string) => ({ css: { clipPath: v }, fade: false });
  const move = (x: number, y: number) => ({ css: { translate: `${pct(x)} ${pct(y)}` }, fade: false });
  switch (style ?? DEFAULT_STYLE) {
    case "wipeleft":
    case "smoothleft":
      return clip(`inset(0 0 0 ${pct(r)})`);
    case "wiperight":
    case "smoothright":
      return clip(`inset(0 ${pct(r)} 0 0)`);
    case "wipeup":
    case "smoothup":
      return clip(`inset(${pct(r)} 0 0 0)`);
    case "wipedown":
    case "smoothdown":
      return clip(`inset(0 0 ${pct(r)} 0)`);
    case "wipetl":
    case "diagtl":
      return clip(`polygon(0 0, ${pct(2 * q)} 0, 0 ${pct(2 * q)})`);
    case "wipetr":
    case "diagtr":
      return clip(`polygon(100% 0, ${pct(1 - 2 * q)} 0, 100% ${pct(2 * q)})`);
    case "wipebl":
    case "diagbl":
      return clip(`polygon(0 100%, 0 ${pct(1 - 2 * q)}, ${pct(2 * q)} 100%)`);
    case "wipebr":
    case "diagbr":
      return clip(`polygon(100% 100%, ${pct(1 - 2 * q)} 100%, 100% ${pct(1 - 2 * q)})`);
    case "circleopen":
    case "circlecrop":
      return clip(`circle(${pct(q * 0.75)} at 50% 50%)`);
    case "rectcrop":
      return clip(`inset(${pct(r / 2)})`);
    case "vertopen":
      return clip(`inset(0 ${pct(r / 2)})`);
    case "horzopen":
      return clip(`inset(${pct(r / 2)} 0)`);
    case "slideleft":
    case "coverleft":
      return move(r, 0);
    case "slideright":
    case "coverright":
      return move(-r, 0);
    case "slideup":
    case "coverup":
      return move(0, r);
    case "slidedown":
    case "coverdown":
      return move(0, -r);
    case "zoomin":
      return { css: { scale: String(0.6 + 0.4 * q) }, fade: true };
    case "squeezeh":
      return { css: { scale: `${Math.max(0.01, q)} 1` }, fade: false };
    case "squeezev":
      return { css: { scale: `1 ${Math.max(0.01, q)}` }, fade: false };
    default:
      return { css: {}, fade: true };
  }
}

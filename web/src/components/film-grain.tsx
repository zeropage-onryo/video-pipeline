// A fixed, full-viewport grain + vignette overlay that sits above the
// page background but below content. Pure CSS/SVG -- the grain is one
// inline feTurbulence texture (no image request), the vignette a single
// radial gradient. Non-interactive and decorative, so aria-hidden.

const GRAIN =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E";

export function FilmGrain() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {/* Vignette -- pulls the eye to center, darkens the frame edges. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 90% at 50% 40%, transparent 55%, rgba(0,0,0,0.55) 100%)",
        }}
      />
      {/* Grain -- kept faint so type stays crisp. */}
      <div
        className="absolute inset-0 opacity-[0.04] mix-blend-screen"
        style={{
          backgroundImage: `url("${GRAIN}")`,
          backgroundSize: "140px 140px",
        }}
      />
    </div>
  );
}

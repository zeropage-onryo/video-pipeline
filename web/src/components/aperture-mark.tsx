// The ZPF aperture/viewfinder logo mark -- a small shutter-blade ring
// rendered as inline SVG so it stays crisp at any size and inherits
// currentColor for the signal-red accent. Decorative; label it where used.

export function ApertureMark({ className }: { className?: string }) {
  const blades = Array.from({ length: 6 });
  return (
    <svg
      viewBox="0 0 48 48"
      className={className}
      fill="none"
      stroke="currentColor"
      aria-hidden
    >
      <circle cx="24" cy="24" r="21" strokeWidth="1.5" opacity="0.35" />
      <circle cx="24" cy="24" r="8" strokeWidth="1.5" />
      {blades.map((_, i) => {
        const angle = (i / blades.length) * Math.PI * 2;
        const x1 = 24 + Math.cos(angle) * 8;
        const y1 = 24 + Math.sin(angle) * 8;
        const x2 = 24 + Math.cos(angle) * 20;
        const y2 = 24 + Math.sin(angle) * 20;
        return (
          <line
            key={i}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            strokeWidth="1.5"
            opacity="0.6"
          />
        );
      })}
    </svg>
  );
}

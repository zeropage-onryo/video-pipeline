import { ImageResponse } from "next/og";

// The share card for the landing page: the wordmark in the noir palette on
// a 1200x630 plate. Rendered at build time by Next from this route; the
// <meta og:image> tags in layout.tsx's metadata point here automatically.
// Satori ships its own default face, so no font fetch happens at build.

export const alt = "Zero Page — The AI content studio that creates for you.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const RED = "#e4002b";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 72,
          background: "radial-gradient(circle at 75% 35%, rgba(228,0,43,0.22), #0a0a0a 45%)",
          color: "#f2f2f2",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, border: `3px solid ${RED}` }} />
          <div style={{ display: "flex", fontSize: 30, fontWeight: 700, letterSpacing: 2 }}>
            ZERO<span style={{ color: RED }}>PAGE</span>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 22, letterSpacing: 8, color: RED, textTransform: "uppercase" }}>
            Your vision. Your studio.
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              marginTop: 24,
              fontSize: 100,
              fontWeight: 800,
              lineHeight: 0.92,
              textTransform: "uppercase",
              letterSpacing: -2,
            }}
          >
            {/* One span per line: Satori does not balance wrapped text, and
                the hero's own break (white, then the red payoff) is the design. */}
            <span>The AI content</span>
            <span>studio that</span>
            <span style={{ color: RED }}>creates for you.</span>
          </div>
        </div>
        <div style={{ display: "flex", fontSize: 22, letterSpacing: 6, color: "#9a9a9a", textTransform: "uppercase" }}>
          Script · Idea · Concept · Image · Video
        </div>
      </div>
    ),
    size,
  );
}

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // standalone is what the Fly image runs (node server.js on a copied
  // .next/standalone); on Vercel the platform packages the app itself and
  // its build hook looks for tracing files standalone does not write
  // (next-server.js.nft.json -- ENOENT on the first Vercel build, 2026-09-14)
  output: process.env.VERCEL ? undefined : "standalone",
  // the in-app Browser pane and curl reach the dev server as 127.0.0.1
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // The landing page's frames are the studio's own keyframes on R2
  // (src/content/landing-media.ts); next/image resizes and re-encodes
  // them, so a 2MB PNG reaches the page as a ~60KB WebP.
  images: {
    remotePatterns: [{ protocol: "https", hostname: "*.r2.dev" }],
  },
  // A separate build directory lets production validation run alongside dev.
  async rewrites() {
    const upstream = process.env.API_UPSTREAM || "http://localhost:8000";
    return [
      "/api/:path*",
      "/ui",
      "/ui/:path*",
      "/signin",
      "/auth/:path*",
      "/refs/:path*",
      "/renders/:path*",
      "/characters/:path*",
      "/props/:path*",
      "/locations/:path*",
      "/static/:path*",
      "/brand/:path*",
    ].map((source) => ({ source, destination: `${upstream}${source}` }));
  },
  distDir: process.env.NEXT_BUILD_DIR || ".next",
};

export default nextConfig;

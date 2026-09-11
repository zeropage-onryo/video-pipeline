import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // the in-app Browser pane and curl reach the dev server as 127.0.0.1
  allowedDevOrigins: ["127.0.0.1", "localhost"],
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

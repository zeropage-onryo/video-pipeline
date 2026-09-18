import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://zpf-web.vercel.app";

// The public pages only -- everything under /studio is behind sign-in and
// disallowed in robots.ts.
export default function sitemap(): MetadataRoute.Sitemap {
  const monthly = new Set(["/pricing", "/models", "/faq"]);
  return ["/", "/pricing", "/models", "/faq", "/terms", "/privacy"].map((path) => ({
    url: `${SITE_URL}${path === "/" ? "" : path}`,
    changeFrequency: path === "/" ? "weekly" : monthly.has(path) ? "monthly" : "yearly",
    priority: path === "/" ? 1 : monthly.has(path) ? 0.7 : 0.3,
  }));
}

import type { MetadataRoute } from "next";
import { MAKE_PAGES, makePath } from "@/landing-pages/pages";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://zpf-web.vercel.app";

// The public pages only -- everything under /studio is behind sign-in and
// disallowed in robots.ts. Every /make landing page is listed off its
// entry, so adding one there is adding it here.
export default function sitemap(): MetadataRoute.Sitemap {
  const monthly = new Set(["/pricing", "/models", "/faq"]);
  const fixed = ["/", "/pricing", "/models", "/faq", "/terms", "/privacy"].map((path) => ({
    url: `${SITE_URL}${path === "/" ? "" : path}`,
    changeFrequency: (path === "/" ? "weekly" : monthly.has(path) ? "monthly" : "yearly") as
      | "weekly"
      | "monthly"
      | "yearly",
    priority: path === "/" ? 1 : monthly.has(path) ? 0.7 : 0.3,
  }));
  const make = MAKE_PAGES.map((page) => ({
    url: `${SITE_URL}${makePath(page.slug)}`,
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }));
  return [...fixed, ...make];
}

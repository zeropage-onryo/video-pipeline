import type { MetadataRoute } from "next";

// Same origin rule as layout.tsx: Vercel's deployment unless
// NEXT_PUBLIC_SITE_URL names a custom domain.
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://zpf-web.vercel.app";

// The landing page is the indexed surface. /studio is the signed-in
// product and /api/ is the proxy to FastAPI -- neither is for crawlers.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/studio", "/api/"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}

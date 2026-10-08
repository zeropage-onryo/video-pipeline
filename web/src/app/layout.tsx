import type { Metadata } from "next";
import { Geist, Geist_Mono, Inter, JetBrains_Mono, Lora, Oswald } from "next/font/google";
import "./globals.css";

// PRELOAD ONLY WHAT THE FIRST SCREEN NEEDS (2026-10-08, Lighthouse). All six
// faces used to be preloaded at high priority on every page, ~190 KiB of
// font ahead of the first paint, and on a phone that held the public pages'
// LCP at 4.5-5 s. Inter (body copy, the landing skin's sans), Lora (every
// public headline) and Oswald (the condensed section titles) keep their
// preload. Oswald has to: un-preloaded, its swap re-wrapped the Ad
// Generator's wall title in the first screen and shifted the wall (CLS
// 0.025, "web font loaded"). The other three are `preload: false`: still
// declared, so a page that uses one downloads it on first use, but no page
// pays for a face it does not draw -- JetBrains Mono and Geist are the
// studio's, Geist Mono is the one-line eyebrow labels.

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  preload: false,
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  preload: false,
});

// Tall, condensed, heavy display face for headlines -- carries the
// LTX-style compressed uppercase treatment. Body copy stays on Geist.
const oswald = Oswald({
  variable: "--font-oswald",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

// The signed-in studio's faces (the ZPF design set): Inter for body
// copy, JetBrains Mono for the small uppercase labels. Loaded here so
// the studio shell can use them as CSS variables like Oswald above.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
});

// The public site's headline face (2026-09-18): a serif at weight 400
// carries every h1/h2 on the landing and legal pages. Oswald stays loaded
// above because /studio's own CSS still reads --font-oswald.
const lora = Lora({
  variable: "--font-lora",
  subsets: ["latin"],
  // 700 is for the /make pages' headline only (`.serif-bold`, 2026-10-01);
  // every other serif on the site stays at 400.
  weight: ["400", "500", "700"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500"],
  preload: false,
});

// The public origin, for absolute OG/canonical URLs. Vercel's own
// deployment is the default; NEXT_PUBLIC_SITE_URL overrides it (a custom
// domain, or a preview host).
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://zpf-web.vercel.app";

const TITLE = "Zero Page — The AI content studio that creates for you.";

const DESCRIPTION =
  "An AI content studio for filmmakers, brands, and creators. Start with a script, an idea, a concept, an image, or a video — and Zero Page creates for you.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: "%s — Zero Page",
  },
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    siteName: "Zero Page",
    title: TITLE,
    description: DESCRIPTION,
    url: "/",
    locale: "en_US",
    images: [{ url: "/og.jpg", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
  robots: { index: true, follow: true },
  icons: {
    icon: [
      { url: "/brand/zp_black_favicon_32.png", sizes: "32x32", type: "image/png" },
      { url: "/brand/zp_black_favicon_512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/brand/zp_black_favicon_512.png",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${oswald.variable} ${inter.variable} ${jetbrains.variable} ${lora.variable} h-full antialiased bg-background`}
    >
      <body className="relative min-h-full flex flex-col">
        {children}
      </body>
    </html>
  );
}

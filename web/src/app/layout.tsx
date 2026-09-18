import type { Metadata } from "next";
import { Geist, Geist_Mono, Inter, JetBrains_Mono, Lora, Oswald } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
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
  weight: ["400", "500"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500"],
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

import type { Metadata } from "next";
import { cardFonts } from "@/components/studio/card-fonts";
import { StudioShell } from "@/components/studio/shell";
import { FilmGrain } from "@/components/film-grain";

export const metadata: Metadata = {
  title: "Studio",
  robots: { index: false, follow: false },
};

/* Every signed-in page sits inside the one shell: the rail, the bar,
   the account row. The shell is a client component (it reads the
   session over the proxy); the pages under it decide their own data. */
export default function StudioLayout({ children }: { children: React.ReactNode }) {
  // The card faces' variables (card-fonts.ts), for everything under the
  // shell. display:contents -- the wrapper only carries the font variables, it
  // must not become a box between <body> and the shell's own layout
  // The grain + vignette overlay used to sit in the root layout; it moved
  // here (2026-09-18) when the public site dropped it, so the studio looks
  // exactly as it did.
  return (
    <div className={`${cardFonts} contents`}>
      <FilmGrain />
      <StudioShell>{children}</StudioShell>
    </div>
  );
}

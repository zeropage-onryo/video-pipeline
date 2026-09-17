import type { Metadata } from "next";
import { cardFonts } from "@/components/studio/card-fonts";
import { StudioShell } from "@/components/studio/shell";

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
  return (
    <div className={`${cardFonts} contents`}>
      <StudioShell>{children}</StudioShell>
    </div>
  );
}

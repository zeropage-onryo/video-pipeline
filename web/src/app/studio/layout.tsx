import type { Metadata } from "next";
import { StudioShell } from "@/components/studio/shell";

export const metadata: Metadata = {
  title: "Studio",
  robots: { index: false, follow: false },
};

/* Every signed-in page sits inside the one shell: the rail, the bar,
   the account row. The shell is a client component (it reads the
   session over the proxy); the pages under it decide their own data. */
export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return <StudioShell>{children}</StudioShell>;
}

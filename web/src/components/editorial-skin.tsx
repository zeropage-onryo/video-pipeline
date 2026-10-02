import type { ReactNode } from "react";

// The public site's skin, applied as a wrapper rather than on <html>:
// the root layout is shared with /studio, which keeps the noir tokens.
// `.editorial` (globals.css) re-declares every shadcn token underneath
// it -- warm black, white primary, Inter, 8px radius -- so every
// component below reads the new palette through the same class names.
// `tone="light"` adds `.editorial-light`, the same tokens inverted (white
// ground, black type) -- the /make landing pages wear it; the homepage
// and the legal pages stay dark.
export function EditorialSkin({
  children,
  tone = "dark",
}: {
  children: ReactNode;
  tone?: "dark" | "light";
}) {
  return (
    <div
      className={`editorial ${tone === "light" ? "editorial-light" : ""} flex min-h-svh flex-1 flex-col bg-background text-foreground`}
    >
      {children}
    </div>
  );
}

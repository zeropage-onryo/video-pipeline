"use client";

/* The editor's entry points (T23): Queue's "Ready to cut" card, an Assets
   render, a Pipeline card with a clip. One button, one door -- it makes
   (or finds) the project and navigates there, so the three places cannot
   disagree about what "open in the editor" means. */
import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { openInEditor } from "@/lib/cut/api";
import { useShell } from "@/components/studio/shell";

export function OpenInEditor({
  concept_id,
  handles,
  className,
  title = "Open in the editor",
  children,
}: {
  concept_id?: number;
  handles?: string[];
  className?: string;
  title?: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const { toast } = useShell();
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      className={className}
      title={title}
      aria-label={title}
      disabled={busy}
      aria-busy={busy}
      onClick={async () => {
        setBusy(true);
        try {
          router.push(await openInEditor({ concept_id, handles }));
        } catch (e) {
          toast(e instanceof Error ? e.message : "could not open the editor", "err");
          setBusy(false);
        }
      }}
    >
      {children}
    </button>
  );
}

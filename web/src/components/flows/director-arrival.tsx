"use client";

/* /studio/flows with no ?concept= : find the scene to open, then go there
   (lib/director-arrival.ts says which and why). While it looks, the stage
   says so; when the brand has no scene to open -- or nobody is signed in --
   it falls back to the browser-local draft, which also stays reachable on
   purpose at /studio/flows?draft=1. */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import FlowWorkspace from "@/components/flows/flow-workspace";
import { boardConcepts } from "@/lib/studio-api";
import { pickArrival } from "@/lib/director-arrival";
import { useShell } from "@/components/studio/shell";

export default function DirectorArrival() {
  const { me, brand, signedOut } = useShell();
  const router = useRouter();
  const [nothing, setNothing] = useState(false);

  useEffect(() => {
    if (!me) return; // the shell has not said who this is yet
    let stale = false;
    boardConcepts(brand || undefined)
      .then((r) => {
        if (stale) return;
        const scene = pickArrival(r.items);
        if (scene) router.replace(`/studio/flows?concept=${scene.id}&shot=1`);
        else setNothing(true);
      })
      .catch(() => {
        if (!stale) setNothing(true);
      });
    return () => {
      stale = true;
    };
  }, [me, brand, router]);

  if (nothing || signedOut) return <FlowWorkspace key="draft" />;
  return (
    <main className="flows-workspace">
      <div className="flow-modal-backdrop">
        <section className="flow-modal" role="status">
          <h2>Opening Director…</h2>
          <p>Finding your newest scene.</p>
        </section>
      </div>
    </main>
  );
}

"use client";

/* /studio/scene/<id>: one scene's canvas, resolved (2026-10-07).

   A scene filed under a project opens in that project's workspace -- the
   list, the canvas and the brief together -- so this only asks the scene
   which project it is in and replaces the URL. A scene outside any project
   (a single video made on Create) has no board to sit on, so its canvas
   opens here on its own, with Send to Queue as its way forward. */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import FlowWorkspace from "@/components/flows/flow-workspace";
import { getConceptDetail, workspaceHref } from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";

export function SceneCanvas({ id, shot }: { id: number | null; shot?: number }) {
  const { me, signedOut } = useShell();
  const router = useRouter();
  // "solo": no project (or it could not be asked) -- draw the canvas here
  const [solo, setSolo] = useState(id === null);

  useEffect(() => {
    if (id === null || (!me && !signedOut)) return;
    let stale = false;
    getConceptDetail(id)
      .then((c) => {
        if (stale) return;
        if (c.project_id) router.replace(workspaceHref(c.project_id, id, shot));
        else setSolo(true);
      })
      // not found, not signed in: the canvas says so itself
      .catch(() => !stale && setSolo(true));
    return () => {
      stale = true;
    };
  }, [id, shot, me, signedOut, router]);

  if (solo) {
    return id === null ? (
      <FlowWorkspace key="draft" />
    ) : (
      <FlowWorkspace conceptId={id} shotN={shot} nav={{ backHref: "/studio/projects", backLabel: "Back to Projects" }} />
    );
  }
  return (
    <main className="flows-workspace">
      <div className="flow-modal-backdrop">
        <section className="flow-modal" role="status">
          <h2>Opening the scene…</h2>
          <p>Finding the project it belongs to.</p>
        </section>
      </div>
    </main>
  );
}

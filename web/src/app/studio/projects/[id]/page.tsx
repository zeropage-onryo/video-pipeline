import { Suspense } from "react";
import { notFound } from "next/navigation";
import { ProjectWorkspace } from "@/components/studio/project-workspace";

/* A project's workspace (2026-10-07): its scenes, the Director canvas for
   the selected one (?scene=<id>&shot=<n>) and its brief, look and memory,
   with the assistant pill scoped to it. components/studio/project-workspace
   says how the three panes work. */
export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return (
    <Suspense fallback={null}>
      <ProjectWorkspace key={id} id={Number(id)} />
    </Suspense>
  );
}

import { Suspense } from "react";
import { notFound } from "next/navigation";
import { SceneCanvas } from "@/components/studio/scene-canvas";

/* Where a scene's canvas opens (2026-10-07): inside its project's
   workspace when it is filed under one, else on its own -- a single video
   made outside any project has no board, but its canvas still opens.
   `draft` is the browser-local draft canvas (the old /studio/flows?draft). */
export default async function ScenePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ shot?: string }>;
}) {
  const { id } = await params;
  const { shot } = await searchParams;
  if (id !== "draft" && !/^\d+$/.test(id)) notFound();
  const shotN = shot && /^\d+$/.test(shot) ? Number(shot) : undefined;
  return (
    <Suspense fallback={null}>
      <SceneCanvas key={`${id}:${shotN ?? ""}`} id={id === "draft" ? null : Number(id)} shot={shotN} />
    </Suspense>
  );
}

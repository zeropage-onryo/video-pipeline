import { redirect } from "next/navigation";
import { flowsTarget } from "@/lib/legacy-routes";

/* The standalone Director tab is gone (2026-10-07, Mike's call): the
   canvas lives inside a project's workspace (/studio/projects/<id>), or,
   for a scene made outside any project, on /studio/scene/<id>. This route
   stays only so every Director link written before keeps working:
   `?concept=` (and `&shot=`) open that scene, `?draft` the browser-local
   draft canvas, and anything else the Projects board. The vanilla /ui
   hands its scenes here too (DIRECTOR_FRONTEND_URL). */
export default async function FlowsRedirect({
  searchParams,
}: {
  searchParams: Promise<{ concept?: string; shot?: string; draft?: string }>;
}) {
  redirect(flowsTarget(await searchParams));
}

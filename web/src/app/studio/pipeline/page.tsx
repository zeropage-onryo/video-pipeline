import { redirect } from "next/navigation";
import { pipelineTarget } from "@/lib/legacy-routes";

/* The Pipeline tab is gone (2026-10-07, Mike's call): a concept is one
   scene and a project is what holds scenes, so the board of PROJECTS is
   the home and a scene is decided on inside its project's workspace.
   An old link still lands: `?concept=<id>` opens that scene (inside its
   project when it has one), anything else opens the board. */
export default async function PipelineRedirect({
  searchParams,
}: {
  searchParams: Promise<{ concept?: string }>;
}) {
  redirect(pipelineTarget(await searchParams));
}

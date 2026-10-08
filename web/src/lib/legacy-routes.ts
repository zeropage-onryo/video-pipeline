/* Where the retired Pipeline and Director URLs land (2026-10-07, Mike's
   call: one board of projects replaced both tabs). Pure, and no imports on
   purpose: tests/legacy-routes.test.mjs loads this file with node's type
   stripping, where the "@/..." alias does not resolve.

   - /studio/pipeline?concept=<id>        -> that scene (/studio/scene/<id>,
                                             which opens it inside its project)
   - /studio/pipeline                     -> the Projects board
   - /studio/flows?concept=<id>&shot=<n>  -> that scene, at that shot
   - /studio/flows?draft                  -> the browser-local draft canvas
   - /studio/flows                        -> the Projects board */

type Params = { concept?: string; shot?: string; draft?: string };

const id = (v?: string) => (v && /^\d+$/.test(v) ? v : null);

export function pipelineTarget(params: Params): string {
  const concept = id(params.concept);
  return concept ? `/studio/scene/${concept}` : "/studio/projects";
}

export function flowsTarget(params: Params): string {
  const concept = id(params.concept);
  if (concept) {
    const shot = id(params.shot);
    return `/studio/scene/${concept}${shot ? `?shot=${shot}` : ""}`;
  }
  if (params.draft !== undefined) return "/studio/scene/draft";
  return "/studio/projects";
}

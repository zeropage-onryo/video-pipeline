/* Where the Director opens when nobody named a scene (2026-09-18).

   The standing rule (Mike's, 2026-08-25): Director's arrival is the NODES
   -- the newest scene's graph -- never a composer and never a dead end.
   The React Director had neither: /studio/flows with no ?concept= opened a
   browser-local demo whose Generate button is disabled with "Open a concept
   to run the chain".

   The board lists newest first. A scene still waiting on work outranks one
   that already has its clip, because the Director is where a scene gets
   worked; a rendered one is the fallback so arrival is still a real graph.
   A row with no prompt cannot be opened (the canvas refuses it), an archived
   one left the board, and a legacy multi-shot concept is not a scene.

   No imports, on purpose: tests/director-arrival.test.mjs loads this file
   with node's type stripping, where the "@/..." alias does not resolve. */

export type ArrivalRow = {
  id: number;
  is_scene?: boolean;
  archived?: boolean;
  prompt?: string | null;
  media_url?: string | null;
};

export const openable = (c: ArrivalRow) => !!c.is_scene && !c.archived && !!(c.prompt || "").trim();

export function pickArrival<T extends ArrivalRow>(items: T[]): T | null {
  const scenes = items.filter(openable);
  return scenes.find((c) => !c.media_url) ?? scenes[0] ?? null;
}

/* What a send's record means, read honestly (2026-10-10).

   Seen live: a still whose draw failed at the provider came back from the
   job as "done" -- the scene row it rides on WAS saved -- so its step card
   read Done · Approved over a tile holding the provider's raw error. A
   record is only as done as the thing it was for: a still with no image is
   a failure, whatever the job said, and that holds for threads saved before
   the page learned it.

   Pure and import-free: tests/made-state.test.mjs runs this file as it is. */

export type MadeLike = { status: string; output: string; image?: string | null; clip?: string | null; detail?: string };

/** "done", and nothing was drawn. An effect that turned a still into a
 *  clip made something: its record holds `clip` and no `image`. */
export const undrawn = (m: MadeLike) => m.status === "done" && m.output === "image" && !m.image && !m.clip;

/** The record's state as a person should read it. */
export const madeStatus = <M extends MadeLike>(m: M): M["status"] | "failed" => (undrawn(m) ? "failed" : m.status);

/* A provider's own words -- a status code, a JSON body, a vendor's billing
   link -- as older threads saved them. The server writes a plain sentence
   now (src/failures.py); this keeps the old ones off the page too. */
const RAW = /render skipped:|HTTP Error|\{"detail"|fal\.ai/i;
export const NOT_MADE = "The still was not made. Nothing was charged.";

/** The line under a send that did not finish. */
export const failLine = (detail?: string | null) => (!detail || RAW.test(detail) ? NOT_MADE : detail);

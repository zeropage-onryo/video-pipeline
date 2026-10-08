/* The activity tray's pure half (2026-10-08, the front-end gap list vs LTX
   Studio and invideo, items 4, 5 and 7). What a job is called, where its
   result opens, what it spent, the tray's one-line summary, and when a job
   that ended is worth a browser notification. The live half -- the one
   stream connection and the store it fills -- is lib/jobs.ts.

   No "@/..." imports: tests/job-feed.test.mjs loads this with node. */

export type FeedJob = {
  id: number;
  kind: string;
  label: string;
  status: string;
  progress?: number;
  detail?: string;
  error?: string | null;
  ref_id?: number | string | null;
  output?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  cancellable?: boolean;
  credits?: number;
  credits_held?: number;
  charged?: boolean;
};

export const ENDED = ["done", "failed", "cancelled"];
export const isRunning = (job: FeedJob) => job.status === "queued" || job.status === "running";

/** Where a finished job's result is opened (the tray maps it to a link
 *  through studio-api's sceneHref, the one place scene links are built),
 *  or null when the result has no page of its own -- a Guide turn answers
 *  in its thread, an index or a preview has nothing to open. */
export type Result =
  | { to: "scene"; id: number }
  | { to: "cut"; id: string }
  | { to: "elements" }
  | { to: "assets" }
  | null;

/* the kinds whose ref_id is the concept the work was done on */
const SCENE_KINDS = new Set(["scenes", "keyframe", "render", "direct", "refine", "concept", "generate", "plan", "cut"]);

export function resultOf(job: FeedJob): Result {
  if (job.status !== "done") return null;
  // an editor export names its cut project (a uuid); an Assemble names the concept
  if (job.kind === "cut" && typeof job.ref_id === "string" && job.ref_id) return { to: "cut", id: job.ref_id };
  if (job.kind === "sheet") return { to: "elements" };
  if (typeof job.ref_id === "number" && job.ref_id > 0 && SCENE_KINDS.has(job.kind)) return { to: "scene", id: job.ref_id };
  // a Director node's render answers with the file, which is on the wall
  if (job.kind === "render" && job.output) return { to: "assets" };
  return null;
}

const cr = (n: number) => `${n.toLocaleString("en-US")} cr`;

/** What a job spent, said the way the Queue says prices: credits debited,
 *  "not charged" beside what an exempt account's render would have cost,
 *  or what a running render is holding. Null when it spent nothing. */
export function creditsLabel(job: FeedJob): string | null {
  const held = job.credits_held ?? 0;
  const spent = job.credits ?? 0;
  if (isRunning(job) && held > 0) return spent > 0 ? `${cr(spent)} · ${cr(held)} held` : `${cr(held)} held`;
  if (job.credits === undefined) return null;
  if (job.charged === false) return `${cr(spent)} · not charged`;
  return spent > 0 ? cr(spent) : null;
}

export type Summary = { running: number; failed: number; held: number; spent: number };

/** The tray's one line ("2 running · 87 cr held"), over every job it holds. */
export function summary(jobs: FeedJob[]): Summary {
  const out: Summary = { running: 0, failed: 0, held: 0, spent: 0 };
  for (const job of jobs) {
    if (isRunning(job)) {
      out.running += 1;
      out.held += job.credits_held ?? 0;
    }
    if (job.status === "failed") out.failed += 1;
    if (job.charged !== false) out.spent += job.credits ?? 0;
  }
  return out;
}

/** "just now", "4m ago", "2h ago", "3d ago" -- for a time the server wrote
 *  as ISO UTC. Empty when there is no time to say. */
export function ago(iso: string | null | undefined, now: number): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (now - t) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** How long a job ran, in seconds, or null while it runs. */
export function took(job: FeedJob): number | null {
  if (!job.started_at || !job.ended_at) return null;
  const a = Date.parse(job.started_at);
  const b = Date.parse(job.ended_at);
  return Number.isNaN(a) || Number.isNaN(b) ? null : Math.max(0, (b - a) / 1000);
}

/** Whether a job that just ended earns a browser notification: it was seen
 *  RUNNING (not replayed already finished), it ended done or failed (a
 *  cancel was the person's own doing), and it ran long enough that they
 *  may have looked away. */
export function shouldNotify(before: string | undefined, job: FeedJob, minSeconds = 20): boolean {
  if (before !== "queued" && before !== "running") return false;
  if (job.status !== "done" && job.status !== "failed") return false;
  const ran = took(job);
  return ran !== null && ran >= minSeconds;
}

/** Finished jobs newer than the last one the tray showed: the bell's dot. */
export function unseen(jobs: FeedJob[], seenId: number): number {
  return jobs.filter((j) => !isRunning(j) && j.id > seenId).length;
}

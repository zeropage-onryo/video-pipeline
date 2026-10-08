/* THE STUDIO'S ONE JOB CONNECTION (2026-10-08, gap list items 4 and 5).
   /api/jobs/stream had existed since the /ui shell and the React studio
   never opened it: the Queue polled the job list every 2.5s, the element
   sheet every 2s, the Director every 2-2.5s, the composer and the Guide
   every 0.5-1.5s, each page its own loop. Now the shell opens ONE
   EventSource per tab (startJobFeed) and everything reads from it:

   - the activity tray and the Queue read the list (useJobs);
   - every wait -- studio-api's followJob / waitForJob, the composer's
     pollJob, the balance refresh -- rides on it through setJobFeed, so a
     job's progress, its streamed words and its end arrive as they happen.

   The stream may not get through: a proxy that buffers, a network that
   drops long requests. So it is trusted only once it says hello (with the
   process's boot id -- ids restart at 1 on a restart, and a tab that saw
   another boot drops what it held). No hello within a few seconds, or a
   run of errors, and the store POLLS the list instead (fast while
   something runs, slow when idle, never in a hidden tab) and tries the
   stream again a minute later. Every wait that was riding the stream is
   told it was lost and carries on polling; nothing is ever left waiting on
   a connection that went away. */
import { useSyncExternalStore } from "react";
import { API_URL } from "@/lib/api";
import { getJob, listJobs, setJobFeed, type Job, type JobFeed } from "@/lib/studio-api";
import { ENDED, isRunning } from "@/lib/job-feed";

export type FeedMode = "off" | "connecting" | "live" | "polling";

const HELLO_MS = 6000;
const RETRY_STREAM_MS = 60_000;
const POLL_BUSY_MS = 3000;
const POLL_IDLE_MS = 15_000;
const MAX_ERRORS = 3;

let mode: FeedMode = "off";
let boot: string | null = null;
const byId = new Map<number, Job>();
let list: Job[] = [];
const listeners = new Set<() => void>();
type Watcher = { onJob: (job: Job) => void; lost: () => void };
const watchers = new Map<number, Set<Watcher>>();
let source: EventSource | null = null;
let users = 0;
let errors = 0;
let helloTimer: ReturnType<typeof setTimeout> | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let pollTimer: ReturnType<typeof setTimeout> | null = null;

const EMPTY: Job[] = [];

/* A job this tab SAW end: it held it queued or running, and the next word
   said it was over. What the bell's dot counts and what earns a browser
   notification -- a job replayed already finished is neither. */
export type Ending = { job: Job; before: string; at: number };
let endings: Ending[] = [];
const NO_ENDINGS: Ending[] = [];
const endListeners = new Set<(ending: Ending) => void>();

function changed() {
  list = [...byId.values()].sort((a, b) => b.id - a.id);
  listeners.forEach((fn) => fn());
}

function put(job: Job, prev: Job | undefined = byId.get(job.id)) {
  byId.set(job.id, job);
  if (prev && isRunning(prev) && ENDED.includes(job.status)) {
    const ending: Ending = { job, before: prev.status, at: Date.now() };
    endings = [...endings.slice(-49), ending];
    endListeners.forEach((fn) => fn(ending));
  }
  watchers.get(job.id)?.forEach((w) => w.onJob(job));
}

function loseWatchers() {
  const all = [...watchers.values()].flatMap((set) => [...set]);
  watchers.clear();
  all.forEach((w) => w.lost());
}

function setMode(next: FeedMode) {
  if (mode === next) return;
  const wasLive = mode === "live";
  mode = next;
  // a wait riding the stream carries on by polling (studio-api followJob)
  if (wasLive) loseWatchers();
  changed();
}

const feed: JobFeed = {
  live: () => mode === "live",
  watch(id, onJob, lost) {
    const w: Watcher = { onJob, lost };
    let set = watchers.get(id);
    if (!set) watchers.set(id, (set = new Set()));
    set.add(w);
    const mine = set;
    // never synchronously: the caller has not finished subscribing yet
    queueMicrotask(() => {
      if (!mine.has(w)) return;
      const known = byId.get(id);
      if (known) {
        onJob(known);
        return;
      }
      // a job the replay did not carry (older than its window, or started a
      // beat before it): asked once, then the stream carries it on
      getJob(id)
        .then((job) => {
          if (!mine.has(w) || byId.has(id)) return;
          put(job);
          changed();
        })
        .catch(() => {
          if (!mine.has(w)) return;
          mine.delete(w);
          lost();
        });
    });
    return () => {
      mine.delete(w);
      if (!mine.size && watchers.get(id) === mine) watchers.delete(id);
    };
  },
};

function connect() {
  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    startPolling();
    return;
  }
  if (mode !== "polling") setMode("connecting");
  const es = new EventSource(`${API_URL}/api/jobs/stream`, { withCredentials: !!API_URL });
  source = es;
  errors = 0;
  if (helloTimer) clearTimeout(helloTimer);
  helloTimer = setTimeout(() => mode !== "live" && fallBack(), HELLO_MS);
  es.addEventListener("hello", (e) => {
    let next: string | null = null;
    try {
      next = JSON.parse((e as MessageEvent).data).boot ?? null;
    } catch {
      /* a hello without a boot is still a hello */
    }
    // the server restarted: its job 7 is not the job 7 this tab held
    if (boot && next && next !== boot) byId.clear();
    boot = next;
    errors = 0;
    if (helloTimer) clearTimeout(helloTimer);
    stopPolling();
    setMode("live");
  });
  es.addEventListener("job", (e) => {
    try {
      put(JSON.parse((e as MessageEvent).data) as Job);
      changed();
    } catch {
      /* a malformed frame is skipped, never fatal */
    }
  });
  es.addEventListener("gone", (e) => {
    try {
      byId.delete(JSON.parse((e as MessageEvent).data).id);
      changed();
    } catch {
      /* skipped */
    }
  });
  es.onerror = () => {
    // the browser retries by itself (the server says retry: 3000); a run of
    // failures means the stream is not getting through, so poll instead
    if (mode === "live") setMode("connecting");
    errors += 1;
    if (errors >= MAX_ERRORS || es.readyState === EventSource.CLOSED) fallBack();
  };
}

function fallBack() {
  source?.close();
  source = null;
  if (helloTimer) clearTimeout(helloTimer);
  startPolling();
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    if (users > 0 && !source) connect();
  }, RETRY_STREAM_MS);
}

async function pollOnce() {
  try {
    const res = await listJobs();
    const before = new Map(byId);
    byId.clear();
    for (const job of res.items) put(job, before.get(job.id));
    changed();
  } catch {
    /* a failed read leaves the list as it was */
  }
}

function startPolling() {
  setMode("polling");
  if (pollTimer) return;
  const tick = async () => {
    pollTimer = null;
    if (users === 0 || mode !== "polling") return;
    if (document.visibilityState === "visible") await pollOnce();
    if (users === 0 || mode !== "polling") return;
    pollTimer = setTimeout(tick, list.some(isRunning) ? POLL_BUSY_MS : POLL_IDLE_MS);
  };
  void tick();
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
}

const onVisible = () => {
  // back to the tab: a polling list is re-read at once, not on its next beat
  if (document.visibilityState === "visible" && mode === "polling") void pollOnce();
};

/** Open the connection (the shell does, once signed in); the returned
 *  function closes it when the last user lets go. */
export function startJobFeed(): () => void {
  users += 1;
  if (users === 1) {
    setJobFeed(feed);
    document.addEventListener("visibilitychange", onVisible);
    connect();
  }
  return () => {
    users -= 1;
    if (users > 0) return;
    source?.close();
    source = null;
    stopPolling();
    if (helloTimer) clearTimeout(helloTimer);
    if (retryTimer) clearTimeout(retryTimer);
    document.removeEventListener("visibilitychange", onVisible);
    setJobFeed(null);
    setMode("off");
  };
}

/** A job this tab fetched itself (the Queue's approve, which must know its
 *  render before it lets the card go): held as if the stream had said it. */
export function rememberJob(job: Job) {
  if (!byId.has(job.id)) {
    put(job);
    changed();
  }
}

/** Re-read the list now when it is being polled (after a cancel or a
 *  clear); on the stream the change arrives by itself. */
export function refreshJobs() {
  if (mode !== "live" && users > 0) void pollOnce();
}

/** Drop jobs this tab knows were cleared (the server says so on the
 *  stream too; this is for a polling tab, which would otherwise show them
 *  until its next read). */
export function forgetJobs(ids: number[]) {
  ids.forEach((id) => byId.delete(id));
  changed();
}

const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

/** Every job of this account's this tab knows, newest first. */
export const useJobs = () =>
  useSyncExternalStore(
    subscribe,
    () => list,
    () => EMPTY,
  );

/** The jobs this tab saw end, oldest first (the last fifty). */
export const useJobEndings = () =>
  useSyncExternalStore(
    subscribe,
    () => endings,
    () => NO_ENDINGS,
  );

/** Hear each job end as it happens (the browser notification). */
export function onJobEnded(fn: (ending: Ending) => void): () => void {
  endListeners.add(fn);
  return () => {
    endListeners.delete(fn);
  };
}

/** How the list is arriving: live on the stream, polling, or not at all. */
export const useJobFeedMode = () =>
  useSyncExternalStore(
    subscribe,
    () => mode,
    () => "off" as FeedMode,
  );

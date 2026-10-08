"use client";

/* THE ACTIVITY TRAY (2026-10-08, the front-end gap list vs LTX Studio and
   invideo, items 5 and 7). A render finishing on another page used to say
   so only as a number on the Queue's rail badge. Now a bell in the header
   holds everything this account has running or just finished:

   - one line on top: what is running, what it is holding, what failed;
   - each job: its state, its words, its progress, what it spent ("87 cr",
     "87 cr · not charged" on the operator's account, "87 cr held" while a
     render runs -- exact, off the ledger's own settles: app/jobs.py), when,
     and Open for the result (lib/job-feed.ts resultOf), Cancel where the
     job can be cancelled;
   - the bell's dot counts the jobs this tab SAW end since the tray was last
     opened, never ones replayed already finished;
   - an opt-in browser notification for a job that ran a while and ended
     while the tab was in the background. Off until asked, and asked only on
     the click that turns it on (the browser's own permission prompt).

   Fed by the studio's one job connection (lib/jobs.ts); nothing here polls
   and nothing here spends. */
import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Popover } from "@base-ui/react/popover";
import { Ban, Bell, BellRing, Check, Loader2, X } from "lucide-react";
import { cancelJob, clearFinishedJobs, sceneHref, type Job } from "@/lib/studio-api";
import { forgetJobs, onJobEnded, useJobEndings, useJobFeedMode, useJobs } from "@/lib/jobs";
import { ago, creditsLabel, isRunning, resultOf, shouldNotify, summary, type Result } from "@/lib/job-feed";

const SHOWN = 30;
const NOTIFY_KEY = "zpf.notify";
const NOTIFY_EVENT = "zpf:notify-pref";

const hrefOf = (result: Result): string | null => {
  if (!result) return null;
  if (result.to === "scene") return sceneHref(result.id);
  if (result.to === "cut") return `/studio/cut/${encodeURIComponent(result.id)}`;
  return result.to === "elements" ? "/studio/elements" : "/studio/assets";
};

/* the notification preference: per browser, read through an external store
   so the server renders it off and the client snaps to the saved value */
const subscribeNotify = (cb: () => void) => {
  window.addEventListener(NOTIFY_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(NOTIFY_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
};
const readNotify = () => {
  try {
    return localStorage.getItem(NOTIFY_KEY) === "1";
  } catch {
    return false;
  }
};
const canNotify = () => typeof window !== "undefined" && "Notification" in window;

export function ActivityTray({ toast }: { toast: (text: string, kind?: "ok" | "err") => void }) {
  const router = useRouter();
  const jobs = useJobs();
  const mode = useJobFeedMode();
  const endings = useJobEndings();
  const notify = useSyncExternalStore(subscribeNotify, readNotify, () => false);
  const [open, setOpen] = useState(false);
  // when the tray was last looked at: the dot counts what ended after it
  const [seenAt, setSeenAt] = useState(() => Date.now());
  // the clock the "4m ago" labels are read against, set when the tray opens
  const [now, setNow] = useState(() => Date.now());

  const totals = summary(jobs);
  // what ended while the tray was open was seen as it happened
  const fresh = open ? 0 : endings.filter((e) => e.at > seenAt).length;
  const shown = jobs.slice(0, SHOWN);
  const finished = jobs.some((j) => !isRunning(j));

  // a job that ran a while and ended while this tab was in the background
  useEffect(() => {
    if (!notify || !canNotify()) return;
    return onJobEnded(({ job, before }) => {
      if (Notification.permission !== "granted" || document.visibilityState === "visible") return;
      if (!shouldNotify(before, job)) return;
      const href = hrefOf(resultOf(job));
      const note = new Notification(job.status === "done" ? `Finished: ${job.label}` : `Failed: ${job.label}`, {
        body: job.status === "done" ? job.detail || creditsLabel(job) || "" : job.error || job.detail || "",
        tag: `zpf-job-${job.id}`,
      });
      note.onclick = () => {
        window.focus();
        if (href) router.push(href);
        note.close();
      };
    });
  }, [notify, router]);

  const setNotify = async (on: boolean) => {
    if (on && canNotify() && Notification.permission !== "granted") {
      const answer = await Notification.requestPermission();
      if (answer !== "granted") {
        toast("Your browser is blocking notifications for this site", "err");
        return;
      }
    }
    try {
      localStorage.setItem(NOTIFY_KEY, on ? "1" : "0");
    } catch {
      /* a private window forgets it */
    }
    window.dispatchEvent(new Event(NOTIFY_EVENT));
  };

  const cancel = (job: Job) =>
    cancelJob(job.id).catch((e) => toast(e instanceof Error ? e.message : "Could not cancel it", "err"));
  const clear = () =>
    clearFinishedJobs()
      .then(() => forgetJobs(jobs.filter((j) => !isRunning(j)).map((j) => j.id)))
      .catch((e) => toast(e instanceof Error ? e.message : "Could not clear them", "err"));

  const line = [
    totals.running ? `${totals.running} running` : "Nothing running",
    totals.held ? `${totals.held.toLocaleString("en-US")} cr held` : "",
    totals.failed ? `${totals.failed} failed` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Popover.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        setSeenAt(Date.now());
        if (o) setNow(Date.now());
      }}
    >
      <Popover.Trigger
        className={`htray${totals.running ? " busy" : ""}`}
        aria-label={
          totals.running
            ? `Activity: ${totals.running} running`
            : fresh
              ? `Activity: ${fresh} finished since you last looked`
              : "Activity"
        }
        title="Activity: renders, keyframes, sheets and exports"
      >
        <Bell size={15} strokeWidth={1.7} />
        {totals.running ? (
          <span className="htray-count" aria-hidden>
            {totals.running > 9 ? "9+" : totals.running}
          </span>
        ) : fresh ? (
          <span className="htray-dot" aria-hidden>
            {fresh > 9 ? "9+" : fresh}
          </span>
        ) : null}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="bottom" align="end" sideOffset={8} className="z-[800]">
          <Popover.Popup className="ztray" aria-label="Activity">
            <div className="ztray-head">
              <div>
                <strong>Activity</strong>
                <span className="ztray-line">{line}</span>
              </div>
              {finished ? (
                <button type="button" className="ztray-clear" onClick={clear}>
                  Clear finished
                </button>
              ) : null}
            </div>
            {mode === "polling" ? (
              <p className="ztray-mode">Live updates are off here, so this checks every few seconds.</p>
            ) : null}
            <div className="ztray-list" role="list">
              {shown.length ? (
                shown.map((job) => {
                  const running = isRunning(job);
                  const href = hrefOf(resultOf(job));
                  const credits = creditsLabel(job);
                  const words = job.status === "failed" ? job.error || job.detail : job.detail;
                  return (
                    <div key={job.id} role="listitem" className={`ztray-row s-${job.status}`}>
                      <span className="ztray-state" aria-label={job.status}>
                        {running ? (
                          <Loader2 size={14} className="ztray-spin" />
                        ) : job.status === "done" ? (
                          <Check size={14} strokeWidth={2} />
                        ) : job.status === "failed" ? (
                          <X size={14} strokeWidth={2} />
                        ) : (
                          <Ban size={13} strokeWidth={1.8} />
                        )}
                      </span>
                      <span className="ztray-text">
                        <span className="ztray-label">{job.label}</span>
                        {words ? <span className="ztray-words">{words}</span> : null}
                        {running && job.progress > 0 ? (
                          <span className="ztray-bar" aria-hidden>
                            <i style={{ width: `${Math.round(job.progress * 100)}%` }} />
                          </span>
                        ) : null}
                        <span className="ztray-meta">
                          {[credits, running ? job.status : ago(job.ended_at, now)].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      <span className="ztray-acts">
                        {href ? (
                          <Link href={href} onClick={() => setOpen(false)}>
                            Open
                          </Link>
                        ) : null}
                        {running && job.cancellable ? (
                          <button type="button" onClick={() => cancel(job)}>
                            Cancel
                          </button>
                        ) : null}
                      </span>
                    </div>
                  );
                })
              ) : (
                <p className="ztray-empty">
                  Nothing yet. Renders, keyframes, element sheets and exports show up here while they work, with what
                  each one spent.
                </p>
              )}
            </div>
            {canNotify() ? (
              <label className="ztray-notify">
                <input type="checkbox" checked={notify} onChange={(e) => void setNotify(e.target.checked)} />
                <BellRing size={13} strokeWidth={1.7} aria-hidden />
                Notify me when a long job finishes while I’m away from this tab
              </label>
            ) : null}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

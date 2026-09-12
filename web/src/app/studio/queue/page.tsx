"use client";

/* Queue — the spend gate, then the job registry (2026-09-12, the "ZPF
   Queue" design). Rendering is the only step that costs money, so it is
   the only one with a gate in front of it, and approving here is what
   calls Runway. The pending list is derived from the rows (parked or
   picked, not archived, no clip yet), so it survives a restart; the
   Jobs list underneath IS the in-process registry, and says so. */
/* eslint-disable @next/next/no-img-element */
import { useCallback, useEffect, useState } from "react";
import { Camera, Clock, Monitor, RectangleVertical, Zap } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  announceQueueChange,
  cancelJob,
  clearJob,
  listJobs,
  queueApprove,
  queuePending,
  queueReject,
  queueShot,
  type Concept,
  type Job,
  type RunwayState,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";

const ratioLabel = (r?: string) => (r === "720:1280" ? "9:16" : r === "1280:720" ? "16:9" : r || "9:16");
type JobRow = Job & { cancellable?: boolean };

export default function QueuePage() {
  const { brand, toast } = useShell();
  const [pending, setPending] = useState<Concept[] | null>(null);
  const [runway, setRunway] = useState<RunwayState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<number, string>>({});

  const loadPending = useCallback(() => {
    queuePending(brand || undefined)
      .then((r) => {
        setPending(r.items);
        setRunway(r.runway);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Queue unavailable"));
  }, [brand]);
  const loadJobs = useCallback(() => {
    listJobs()
      .then((r) => {
        setJobs(r.items.sort((a, b) => b.id - a.id));
        setJobsError(null);
      })
      .catch((e) => setJobsError(e instanceof Error ? e.message : "Jobs unavailable"));
  }, []);
  useEffect(() => {
    loadPending();
    loadJobs();
  }, [loadPending, loadJobs]);
  // the registry moves while anything runs: poll it, and re-read the
  // rows when a render finishes (a finished clip leaves the pending list)
  const active = jobs.some((j) => ["queued", "running"].includes(j.status));
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      loadJobs();
    }, 2500);
    return () => clearInterval(timer);
  }, [active, loadJobs]);
  useEffect(() => {
    if (active) return;
    loadPending();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const canRender = !!(runway?.available && runway?.spend_ok);
  const gateLine = !runway
    ? "—"
    : !runway.available
      ? "Runway key not set — approving cannot render"
      : !runway.spend_ok
        ? "spend gate off — restart with RUNWAY_SPEND_OK=1"
        : `${runway.model} · ~$${(runway.estimate_usd || 0).toFixed(2)} a clip${runway.today != null ? ` · ${runway.today} today` : ""}`;

  const decide = async (c: Concept, what: "approve" | "reject" | "shot") => {
    setBusy((b) => ({ ...b, [c.id]: what }));
    try {
      if (what === "approve") {
        const res = await queueApprove(c.id);
        toast(res.job_id ? `Rendering ${c.n} — watch Jobs below` : `${c.n} approved`);
      } else if (what === "reject") {
        await queueReject(c.id);
        toast(`${c.n} rejected — archived, still counted`);
      } else {
        await queueShot(c.id);
        toast(`${c.n} marked shot by hand`);
      }
      loadPending();
      loadJobs();
      announceQueueChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through", "err");
    } finally {
      setBusy((b) => {
        const next = { ...b };
        delete next[c.id];
        return next;
      });
    }
  };

  const running = jobs.filter((j) => ["queued", "running"].includes(j.status)).length;

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="vhead" style={{ marginTop: 8 }}>
        <h2>Queue</h2>
        <span className="m">approving a concept here is what spends — it renders the clip through Runway</span>
        <span className="spacer" />
        <span className="m">{pending ? `${pending.length} waiting` : "—"}</span>
      </div>

      <div className="chead">
        <h3>Awaiting approval</h3>
        <span className="m">{pending ? `${pending.length} waiting` : ""}</span>
        <span className="spacer" />
        <span className="m">{gateLine}</span>
      </div>
      {error ? <div className="stateline err" style={{ padding: "0 42px 14px" }}>{error}</div> : null}
      {pending && !pending.length ? (
        <p className="stateline" style={{ padding: "0 42px" }}>
          Nothing waiting — a Studio run lands here once its keyframe is rendered, or pick a concept on Pipeline
        </p>
      ) : null}
      <div className="scenegrid">
        {(pending || []).map((c) => (
          <article key={c.id} className="scene on">
            <div className="screfs">
              {(c.refs || []).slice(0, 4).map((u) => (
                <span key={u} className="scref" style={{ backgroundImage: `url("${API_URL}${u}")` }} />
              ))}
              {!(c.refs || []).length ? <span className="m">no references</span> : null}
              <span className="spacer" />
              <span className="m">{c.spark || ""}</span>
            </div>
            <div className="schead">
              <h4>{c.title}</h4>
              <span className="m">{c.n}</span>
              <span className="spacer" />
              <span className="m">{c.parked ? "ready · awaiting approval" : "picked"}</span>
            </div>
            {c.summary ? <p className="scsum">{c.summary}</p> : null}
            {c.reference_image ? (
              <div className="scframe">
                <img src={c.reference_image.startsWith("/") ? `${API_URL}${c.reference_image}` : c.reference_image} alt="" />
              </div>
            ) : null}
            <p className="scpre">{c.prompt}</p>
            <div className="scchips">
              <span className="chip">
                <Clock size={11} /> {runway?.duration ?? 5} sec
              </span>
              <span className="chip">
                <RectangleVertical size={11} /> {ratioLabel(runway?.ratio)}
              </span>
              <span className="chip">
                <Monitor size={11} /> {runway?.model ?? "gen4_turbo"}
              </span>
            </div>
            <div className="scfoot">
              <button
                type="button"
                className="swipe shot"
                title="Mark shot — you made this outside the render pipeline"
                aria-label="Mark shot — you made this outside the render pipeline"
                disabled={!!busy[c.id]}
                onClick={() => decide(c, "shot")}
              >
                <Camera size={15} strokeWidth={1.6} />
              </button>
              <button type="button" className="tag" disabled={!!busy[c.id]} onClick={() => decide(c, "reject")}>
                {busy[c.id] === "reject" ? "…" : "Reject"}
              </button>
              <span className="m">{c.reference_image ? "anchors on the keyframe above" : c.park_reason || "text-to-video · no reference attached"}</span>
              <span className="spacer" />
              <button type="button" className="go" disabled={!canRender || !!busy[c.id]} onClick={() => decide(c, "approve")}>
                <Zap strokeWidth={2} />
                {busy[c.id] === "approve" ? "Rendering…" : canRender ? `Approve · render ~$${(runway?.estimate_usd || 0).toFixed(2)}` : "Approve · render"}
              </button>
            </div>
          </article>
        ))}
      </div>

      <div className="chead">
        <h3>Jobs</h3>
        <span className="m">live · the registry clears on restart</span>
        <span className="spacer" />
        <span className="m">
          {running} running · {jobs.length} total
        </span>
      </div>
      {jobsError ? <div className="stateline err" style={{ padding: "0 42px 14px" }}>{jobsError}</div> : null}
      <div className="qlist">
        {!jobs.length ? (
          <p className="stateline" style={{ padding: 0 }}>
            Nothing queued — jobs appear here when you create, approve, or run an eval. The queue clears on restart.
          </p>
        ) : null}
        {jobs.map((j) => {
          const live = ["queued", "running"].includes(j.status);
          return (
            <div key={j.id} className="qrow">
              <span className={`dot ${j.status === "failed" ? "bad" : live ? "run" : "ok"}`} />
              <div className="qinfo">
                <div className="qn">{j.label}</div>
                <div className="qm m">
                  {j.kind} · {j.status}
                  {j.detail ? ` · ${j.detail}` : ""}
                  {j.error ? ` · ${j.error}` : ""}
                </div>
              </div>
              <div className="qbar">
                <i style={{ width: `${Math.round((j.progress || 0) * 100)}%` }} />
              </div>
              <span className="m">{j.status}</span>
              {live ? (
                j.cancellable ? (
                  <button
                    type="button"
                    className="tag"
                    onClick={() =>
                      cancelJob(j.id)
                        .then(loadJobs)
                        .catch((e) => toast(e instanceof Error ? e.message : "Could not cancel", "err"))
                    }
                  >
                    Cancel
                  </button>
                ) : (
                  <span className="m">running</span>
                )
              ) : (
                <button
                  type="button"
                  className="tag"
                  onClick={() =>
                    clearJob(j.id)
                      .then(loadJobs)
                      .catch((e) => toast(e instanceof Error ? e.message : "Could not clear", "err"))
                  }
                >
                  Clear
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

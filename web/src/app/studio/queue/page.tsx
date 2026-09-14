"use client";

/* Queue — the spend gate, then the job registry (2026-09-12, the "ZPF
   Queue" design). Rendering is the only step that costs money, so it is
   the only one with a gate in front of it, and approving here is what
   calls the renderer. The pending list is derived from the rows (parked
   or picked, not archived, no clip yet), so it survives a restart; the
   Jobs list underneath IS the in-process registry, and says so.

   ANY REGISTERED RENDERER (the overnight branch, reconciled 2026-09-12):
   the card's selectors are `renderers` off /api/queue/pending — every
   provider with its gates, its models and each model's legal duration
   and frame axis — and approve posts {provider, model, duration, frame},
   which providers.check_render_choice refuses rather than clamps. The
   card's price is a label multiplied from the rate card; the authoritative
   estimate comes back on the approve.

   Between the two sits the SUBSCRIPTION LANE: Runway's Explore mode is
   free on the operator's Unlimited plan but has no API parameter, so the
   render happens by hand in Chrome and the finished mp4 comes back as a
   drop on its card (/api/queue/manual, operator-gated server-side; the
   `manual_lane` capability only decides whether the section is drawn). */
/* eslint-disable @next/next/no-img-element */
import { useCallback, useEffect, useState } from "react";
import { Camera, Clock, Copy, Monitor, RectangleVertical, Upload, Zap } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  announceQueueChange,
  cancelJob,
  clearJob,
  fileLaneClip,
  getCapabilities,
  listJobs,
  queueApprove,
  queueManual,
  queuePending,
  queueReject,
  queueShot,
  type Axis,
  type Concept,
  type Job,
  type LaneItem,
  type LaneModel,
  type RenderChoice,
  type RendererSpec,
  type RunwayState,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";

const RATIO_NAMES: Record<string, string> = {
  "720:1280": "9:16 · vertical",
  "1280:720": "16:9 · wide",
  "832:1104": "3:4 · portrait",
  "1104:832": "4:3 · landscape",
  "960:960": "1:1 · square",
  "1584:672": "21:9 · cinema",
};
type JobRow = Job & { cancellable?: boolean };
type Pick = { provider: string; model: string; duration: number | null; frame: string | null };

/* the default of an axis, whatever its shape */
const axisDefault = (axis?: Axis): string | number | null =>
  !axis ? null : axis.kind === "range" ? (axis.default ?? axis.min ?? null) : (axis.default ?? axis.values?.[0] ?? null);

export default function QueuePage() {
  const { brand, toast } = useShell();
  const [pending, setPending] = useState<Concept[] | null>(null);
  const [runway, setRunway] = useState<RunwayState | null>(null);
  const [renderers, setRenderers] = useState<Record<string, RendererSpec>>({});
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<number, string>>({});
  const [picks, setPicks] = useState<Record<number, Partial<Pick>>>({});
  // the lane: drawn only when the capability says so; the routes re-ask the gate
  const [laneOn, setLaneOn] = useState(false);
  const [lane, setLane] = useState<LaneItem[] | null>(null);
  const [laneModels, setLaneModels] = useState<LaneModel[]>([]);
  const [laneDefault, setLaneDefault] = useState("");
  const [lanePicks, setLanePicks] = useState<Record<number, { model?: string; ratio?: string; duration?: number; anchored?: boolean }>>({});
  const [dropping, setDropping] = useState<Record<number, string>>({});

  const loadPending = useCallback(() => {
    queuePending(brand || undefined)
      .then((r) => {
        setPending(r.items);
        setRunway(r.runway);
        setRenderers(r.renderers || {});
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Queue unavailable"));
  }, [brand]);
  const loadLane = useCallback(() => {
    queueManual(brand || undefined)
      .then((r) => {
        setLane(r.items);
        setLaneModels(r.models || []);
        setLaneDefault(r.default_model || "");
      })
      .catch(() => setLane([]));
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
    getCapabilities()
      .then((c) => setLaneOn(c.manual_lane === true))
      .catch(() => setLaneOn(false));
  }, [loadPending, loadJobs]);
  useEffect(() => {
    if (laneOn) loadLane();
  }, [laneOn, loadLane]);
  // the registry moves while anything runs: poll it, and re-read the
  // rows when a render finishes (a finished clip leaves the pending list)
  const active = jobs.some((j) => ["queued", "running"].includes(j.status));
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(loadJobs, 2500);
    return () => clearInterval(timer);
  }, [active, loadJobs]);
  useEffect(() => {
    if (active) return;
    loadPending();
    if (laneOn) loadLane();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  /* ── the selectors: the plan is the default, the pick overrides it ── */
  const pickFor = (c: Concept): Pick => {
    const p = picks[c.id] || {};
    const provider = p.provider ?? c.render_default?.provider ?? "runway";
    const spec = renderers[provider];
    const model = p.model ?? (provider === c.render_default?.provider ? c.render_default?.model : undefined) ?? spec?.default_model ?? spec?.models?.[0]?.id ?? "";
    const ms = spec?.models?.find((m) => m.id === model);
    return {
      provider,
      model,
      duration: p.duration !== undefined ? p.duration : (axisDefault(ms?.duration) as number | null),
      frame: p.frame !== undefined ? p.frame : (axisDefault(ms?.frame) as string | null),
    };
  };
  const setPick = (c: Concept, patch: Partial<Pick>) =>
    setPicks((w) => {
      const next = { ...(w[c.id] || {}), ...patch };
      // a new provider or model resets the axes to that model's defaults
      if (patch.provider !== undefined || patch.model !== undefined) {
        delete next.duration;
        delete next.frame;
      }
      return { ...w, [c.id]: next };
    });
  const modelSpec = (pick: Pick) => renderers[pick.provider]?.models?.find((m) => m.id === pick.model);
  const priceOf = (pick: Pick) => {
    const price = modelSpec(pick)?.price;
    const seconds = pick.duration ?? 0;
    if (!price) return null;
    if (price.kind === "flat") return price.usd ?? null;
    if (price.kind === "per_second") {
      const rate = price.usd ?? (pick.frame ? price.usd_by_frame?.[pick.frame] : undefined);
      return rate != null ? rate * seconds : null;
    }
    return null;
  };
  const gateFor = (provider: string) => {
    const s = renderers[provider];
    if (!s) return { ok: false, note: "—" };
    if (!s.available) return { ok: false, note: `${s.label} key not set — approving cannot render` };
    if (!s.spend_ok) return { ok: false, note: `${s.label} spend gate off — ${s.spend_env ? `set ${s.spend_env}=1` : "arm it"}` };
    return { ok: true, note: `${s.label}${s.today != null ? ` · ${s.today} today` : ""}${s.cap != null ? ` · cap ${s.cap}` : ""}` };
  };

  const decide = async (c: Concept, what: "approve" | "reject" | "shot") => {
    setBusy((b) => ({ ...b, [c.id]: what }));
    try {
      if (what === "approve") {
        const pick = pickFor(c);
        const res = await queueApprove(c.id, {
          provider: pick.provider,
          model: pick.model,
          duration: pick.duration ?? undefined,
          frame: pick.frame ?? undefined,
        } as RenderChoice);
        const r = res.render;
        toast(
          r
            ? `Rendering ${c.n} — ${r.provider} · ${r.model} · ${r.duration}s · ${r.frame} · ~$${Number(r.estimate_usd).toFixed(2)}`
            : `${c.n} approved`,
        );
      } else if (what === "reject") {
        await queueReject(c.id);
        toast(`${c.n} rejected — archived, still counted`);
      } else {
        await queueShot(c.id);
        toast(`${c.n} marked shot by hand`);
      }
      loadPending();
      loadJobs();
      if (laneOn) loadLane();
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

  /* ── the subscription lane ── */
  const lanePick = (item: LaneItem) => {
    const p = lanePicks[item.concept_id] || {};
    const model = p.model ?? (laneModels.some((m) => m.id === laneDefault) ? laneDefault : laneModels[0]?.id ?? "");
    const spec = laneModels.find((m) => m.id === model);
    const ratio = p.ratio ?? (spec?.ratios.includes(item.ratio) ? item.ratio : spec?.ratios[0] ?? item.ratio);
    const duration = p.duration ?? (spec?.durations.includes(item.duration) ? item.duration : spec?.durations[0] ?? item.duration);
    const anchored = p.anchored ?? !!item.keyframe_url;
    return { model, ratio, duration, anchored, spec };
  };
  const fileClip = async (item: LaneItem, file: File | undefined) => {
    if (!file) return;
    const pick = lanePick(item);
    setDropping((d) => ({ ...d, [item.concept_id]: "filing…" }));
    try {
      const res = await fileLaneClip(item.concept_id, file, {
        shot_n: item.shot_n,
        model: pick.model,
        ratio: pick.ratio,
        duration: pick.duration,
        anchored: pick.anchored,
      });
      toast(`${item.title} filed — free on the subscription${res.media_url ? ` · ${res.media_url}` : ""}`);
      loadPending();
      loadLane();
      announceQueueChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not file the clip", "err");
    } finally {
      setDropping((d) => {
        const next = { ...d };
        delete next[item.concept_id];
        return next;
      });
    }
  };
  const copyPrompt = async (item: LaneItem) => {
    try {
      await navigator.clipboard.writeText(item.prompt);
      toast(`${item.title}'s prompt copied — paste it into Runway`);
    } catch {
      toast("Clipboard blocked — select the prompt and copy it by hand", "err");
    }
  };

  const running = jobs.filter((j) => ["queued", "running"].includes(j.status)).length;
  const providerIds = Object.keys(renderers);

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="vhead" style={{ marginTop: 8 }}>
        <h2>Queue</h2>
        <span className="m">approving a concept here is what spends — it renders the clip on the renderer you pick</span>
        <span className="spacer" />
        <span className="m">{pending ? `${pending.length} waiting` : "—"}</span>
      </div>

      <div className="chead">
        <h3>Awaiting approval</h3>
        <span className="m">{pending ? `${pending.length} waiting` : ""}</span>
        <span className="spacer" />
        <span className="m">
          {providerIds.length
            ? providerIds.map((p) => `${renderers[p].label}: ${gateFor(p).ok ? "armed" : "off"}`).join(" · ")
            : runway
              ? runway.available
                ? `${runway.model} · ~$${(runway.estimate_usd || 0).toFixed(2)} a clip`
                : "Runway key not set — approving cannot render"
              : "—"}
        </span>
      </div>
      {error ? <div className="stateline err" style={{ padding: "0 42px 14px" }}>{error}</div> : null}
      {pending && !pending.length ? (
        <p className="stateline" style={{ padding: "0 42px" }}>
          Nothing waiting — a Studio run lands here once its keyframe is rendered, or pick a concept on Pipeline
        </p>
      ) : null}
      <div className="scenegrid">
        {(pending || []).map((c) => {
          const pick = pickFor(c);
          const spec = renderers[pick.provider];
          const ms = modelSpec(pick);
          const gate = gateFor(pick.provider);
          const price = priceOf(pick);
          const frameLabel = spec?.frame_axis === "ratio" ? "Frame" : "Resolution";
          return (
            <article key={c.id} className="scene on">
              <div className="screfs">
                {(c.refs || []).slice(0, 4).map((u) => (
                  <span key={u} className="scref" style={{ backgroundImage: `url("${u.startsWith("/") ? API_URL + u : u}")` }} />
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

              <div className="scchoice">
                <label className="scsel" title="Renderer">
                  <Zap size={11} />
                  <select aria-label="Renderer" value={pick.provider} onChange={(e) => setPick(c, { provider: e.target.value })}>
                    {providerIds.map((p) => (
                      <option key={p} value={p}>
                        {renderers[p].label}
                        {renderers[p].available ? "" : " · no key"}
                      </option>
                    ))}
                    {!providerIds.length ? <option value="runway">Runway</option> : null}
                  </select>
                </label>
                <label className="scsel" title="Model">
                  <Monitor size={11} />
                  <select aria-label="Model" value={pick.model} onChange={(e) => setPick(c, { model: e.target.value })}>
                    {(spec?.models || []).map((m) => (
                      <option key={m.id} value={m.id} disabled={m.available === false}>
                        {m.label}
                        {m.price?.kind === "per_second" && m.price.usd != null ? ` · $${m.price.usd.toFixed(2)}/s` : ""}
                        {m.available === false ? " · unreachable" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                {ms?.duration ? (
                  <label className="scsel" title={ms.duration.note || "Length"}>
                    <Clock size={11} />
                    {ms.duration.kind === "range" ? (
                      <input
                        type="number"
                        aria-label="Length in seconds"
                        min={ms.duration.min}
                        max={ms.duration.max}
                        value={pick.duration ?? ""}
                        onChange={(e) => setPick(c, { duration: Number(e.target.value) })}
                      />
                    ) : (
                      <select
                        aria-label="Length"
                        value={String(pick.duration ?? "")}
                        disabled={ms.duration.kind === "fixed"}
                        onChange={(e) => setPick(c, { duration: Number(e.target.value) })}
                      >
                        {(ms.duration.values || []).map((d) => (
                          <option key={String(d)} value={String(d)}>
                            {d} sec
                          </option>
                        ))}
                      </select>
                    )}
                  </label>
                ) : null}
                {ms?.frame ? (
                  <label className="scsel" title={ms.frame.note || frameLabel}>
                    <RectangleVertical size={11} />
                    <select
                      aria-label={frameLabel}
                      value={String(pick.frame ?? "")}
                      disabled={ms.frame.kind === "fixed"}
                      onChange={(e) => setPick(c, { frame: e.target.value })}
                    >
                      {(ms.frame.values || []).map((f) => (
                        <option key={String(f)} value={String(f)}>
                          {String(f)}
                          {RATIO_NAMES[String(f)] ? ` · ${RATIO_NAMES[String(f)]}` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>
              {ms?.frame?.kind === "fixed" && ms.frame.note ? <span className="m">{ms.frame.note}</span> : null}

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
                <span className="m">{gate.ok ? (c.reference_image ? "anchors on the keyframe above" : c.park_reason || "text-to-video · no reference attached") : gate.note}</span>
                <span className="spacer" />
                <button type="button" className="go" disabled={!gate.ok || !!busy[c.id]} onClick={() => decide(c, "approve")}>
                  <Zap strokeWidth={2} />
                  {busy[c.id] === "approve" ? "Rendering…" : `Approve · render${price != null ? ` ~$${price.toFixed(2)}` : ""}`}
                </button>
              </div>
            </article>
          );
        })}
      </div>

      {laneOn ? (
        <>
          <div className="chead">
            <h3>Subscription lane</h3>
            <span className="m">{lane ? `${lane.length} to render by hand` : ""}</span>
            <span className="spacer" />
            <span className="m">Runway Explore · free on Unlimited · rendered by hand in Chrome</span>
          </div>
          {lane && !lane.length ? (
            <p className="stateline" style={{ padding: "0 42px" }}>
              Nothing to render by hand — the lane takes the scenes you picked on Pipeline or sent from the Director
            </p>
          ) : null}
          <div className="scenegrid">
            {(lane || []).map((item) => {
              const pick = lanePick(item);
              const still = item.keyframe_url
                ? item.keyframe_url.startsWith("/")
                  ? `${API_URL}${item.keyframe_url}`
                  : item.keyframe_url
                : null;
              return (
                <article key={`lane-${item.concept_id}`} className="scene lane">
                  <div className="schead">
                    <h4>{item.title}</h4>
                    <span className="m">shot {item.shot_n}</span>
                    <span className="spacer" />
                    <span className="m">
                      {pick.duration}s · {pick.ratio}
                    </span>
                  </div>
                  <div className="scframe drag">
                    {still ? (
                      <img src={still} alt="" draggable title="Drag me into Runway's start-image slot" />
                    ) : (
                      <span className="scempty">
                        <span className="m">no keyframe · text-to-video</span>
                      </span>
                    )}
                  </div>
                  <p className="scpre">{item.prompt}</p>
                  <div className="scchoice">
                    <label className="scsel" title="What Runway rendered it as">
                      <Monitor size={11} />
                      <select
                        aria-label="Model rendered"
                        value={pick.model}
                        onChange={(e) => setLanePicks((w) => ({ ...w, [item.concept_id]: { ...w[item.concept_id], model: e.target.value, ratio: undefined, duration: undefined } }))}
                      >
                        {laneModels.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.id}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="scsel" title="Frame rendered">
                      <RectangleVertical size={11} />
                      <select aria-label="Frame rendered" value={pick.ratio} onChange={(e) => setLanePicks((w) => ({ ...w, [item.concept_id]: { ...w[item.concept_id], ratio: e.target.value } }))}>
                        {(pick.spec?.ratios || [item.ratio]).map((r) => (
                          <option key={r} value={r}>
                            {r}
                            {RATIO_NAMES[r] ? ` · ${RATIO_NAMES[r]}` : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="scsel" title="Length rendered">
                      <Clock size={11} />
                      <select aria-label="Length rendered" value={String(pick.duration)} onChange={(e) => setLanePicks((w) => ({ ...w, [item.concept_id]: { ...w[item.concept_id], duration: Number(e.target.value) } }))}>
                        {(pick.spec?.durations || [item.duration]).map((d) => (
                          <option key={d} value={String(d)}>
                            {d} sec
                          </option>
                        ))}
                      </select>
                    </label>
                    {still ? (
                      <label className="scsel" title="Was the keyframe used as the start image">
                        <input type="checkbox" checked={pick.anchored} onChange={(e) => setLanePicks((w) => ({ ...w, [item.concept_id]: { ...w[item.concept_id], anchored: e.target.checked } }))} />
                        anchored
                      </label>
                    ) : null}
                  </div>
                  <label
                    className={`lanedrop${dropping[item.concept_id] ? " busy" : ""}`}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.currentTarget.classList.add("over");
                    }}
                    onDragLeave={(e) => e.currentTarget.classList.remove("over")}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.currentTarget.classList.remove("over");
                      void fileClip(item, e.dataTransfer.files?.[0]);
                    }}
                  >
                    <input type="file" accept="video/mp4" hidden onChange={(e) => void fileClip(item, e.target.files?.[0])} />
                    <Upload size={14} strokeWidth={1.6} />
                    {dropping[item.concept_id] ?? "Drop the finished mp4 here, or click to pick it"}
                  </label>
                  <div className="scfoot">
                    <button type="button" className="tag" onClick={() => void copyPrompt(item)}>
                      <Copy size={12} strokeWidth={1.6} /> Copy prompt
                    </button>
                    <span className="spacer" />
                    <span className="m">{item.lane || "runway explore"} · filed as free</span>
                  </div>
                </article>
              );
            })}
          </div>
        </>
      ) : null}

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

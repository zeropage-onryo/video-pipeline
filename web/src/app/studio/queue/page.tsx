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
import { Popover } from "@base-ui/react/popover";
import { Camera, ChevronDown, Clock, Copy, Monitor, RectangleVertical, Upload, X } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  announceQueueChange,
  cancelJob,
  clearJob,
  fileLaneClip,
  getCapabilities,
  listJobs,
  queueApprove,
  queueQuote,
  queueManual,
  queuePending,
  queueReject,
  queueShot,
  type Concept,
  type Job,
  type LaneItem,
  type LaneModel,
  type RenderChoice,
  type RenderQuote,
  type RendererSpec,
  type RunwayState,
} from "@/lib/studio-api";
import { cardFonts } from "@/components/studio/card-fonts";
import { CARD, Hero, RefImg, RefThumbs, TAG, TAG_DARK, TitleBlock, brandName, partsOf, refItems, shotsLabel, stillsOf, windowLabel } from "@/components/studio/concept-card";
import { PreviewOverlay, type PreviewState } from "@/components/studio/preview-overlay";
import { useShell } from "@/components/studio/shell";
import {
  approveText,
  chipText,
  held,
  legalDuration,
  pickFor as pickForCard,
  planFor,
  specOf,
  withModel,
  type AxisLike,
  type Pick,
  type Renderers,
} from "@/lib/render-choice";

const RATIO_NAMES: Record<string, string> = {
  "720:1280": "9:16 · vertical",
  "1280:720": "16:9 · wide",
  "832:1104": "3:4 · portrait",
  "1104:832": "4:3 · landscape",
  "960:960": "1:1 · square",
  "1584:672": "21:9 · cinema",
};
type JobRow = Job & { cancellable?: boolean };
/* What you just did to a card, shown on it as a bone tag: RENDERING for as
   long as the approve's job is live, ARCHIVED / SHOT BY HAND for the beat
   before the card leaves the list. Display only -- the rows decide what is
   pending; this stops an approved card looking untouched, and its priced
   button looking pressable twice, while the render runs. Module-level for
   the same reason render-choice's `held` is: it outlives the page. */
type Acted = { status: "RENDERING" | "ARCHIVED" | "SHOT BY HAND"; job?: number; at: number };
const acted = new Map<number, Acted>();

const PILL =
  "min-h-11 rounded-[6px] border px-3 font-plex! text-xs! focus-visible:rounded-[6px]! disabled:cursor-not-allowed";
const pill = (on: boolean, off = false) =>
  `${PILL} ${off ? (on ? "border-noir-line3 bg-noir-line3 text-bone!" : "border-noir-line2 text-[#5e5b55]!") : on ? "border-bone bg-bone text-noir-bg!" : "border-noir-line3 text-bone! hover:border-bone"}`;
const SIDE_BTN =
  "flex size-[52px] flex-none items-center justify-center rounded-[8px] border border-noir-line bg-transparent p-0 hover:enabled:border-bone hover:enabled:text-bone! disabled:opacity-50 focus-visible:rounded-[8px]!";
const POPK = "mb-2 font-plex text-[11px] tracking-[0.14em] text-bone3";

export default function QueuePage() {
  const { brand, toast } = useShell();
  const [pending, setPending] = useState<Concept[] | null>(null);
  const [runway, setRunway] = useState<RunwayState | null>(null);
  const [renderers, setRenderers] = useState<Record<string, RendererSpec>>({});
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<number, string>>({});
  const [paint, repaint] = useState(0); // held/acted live outside state (they outlive the page)
  const [popId, setPopId] = useState<number | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  // the lane: drawn only when the capability says so; the routes re-ask the gate
  const [laneOn, setLaneOn] = useState(false);
  const [lane, setLane] = useState<LaneItem[] | null>(null);
  const [laneModels, setLaneModels] = useState<LaneModel[]>([]);
  const [laneDefault, setLaneDefault] = useState("");
  const [lanePicks, setLanePicks] = useState<Record<number, { model?: string; ratio?: string; duration?: number; anchored?: boolean }>>({});
  const [dropping, setDropping] = useState<Record<number, string>>({});

  // `stale` lets an effect drop a response that arrives after the brand
  // changed: the shell resolves the brand a beat after mount, and the
  // unscoped first request used to land AFTER the scoped one, leaving the
  // list showing every brand under a header naming one (2026-09-14).
  const loadPending = useCallback((stale: () => boolean = () => false) => {
    queuePending(brand || undefined)
      .then((r) => {
        if (stale()) return;
        setPending(r.items);
        setRunway(r.runway);
        setRenderers(r.renderers || {});
        setError(null);
      })
      .catch((e) => {
        if (!stale()) setError(e instanceof Error ? e.message : "Queue unavailable");
      });
  }, [brand]);
  const loadLane = useCallback((stale: () => boolean = () => false) => {
    queueManual(brand || undefined)
      .then((r) => {
        if (stale()) return;
        setLane(r.items);
        setLaneModels(r.models || []);
        setLaneDefault(r.default_model || "");
      })
      .catch(() => {
        if (!stale()) setLane([]);
      });
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
    loadJobs();
    getCapabilities()
      .then((c) => setLaneOn(c.manual_lane === true))
      .catch(() => setLaneOn(false));
  }, [loadJobs]);
  // the registry moves while anything runs: poll it, and re-read the
  // rows when a render finishes (a finished clip leaves the pending list)
  const active = jobs.some((j) => ["queued", "running"].includes(j.status));
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(loadJobs, 2500);
    return () => clearInterval(timer);
  }, [active, loadJobs]);
  // the rows: on mount, whenever the brand resolves or changes, whenever
  // the lane opens, and whenever the registry goes quiet (a finished clip
  // leaves the pending list). A response from before any of those
  // changed is dropped, never applied.
  useEffect(() => {
    if (active) return;
    let stale = false;
    const isStale = () => stale;
    loadPending(isStale);
    if (laneOn) loadLane(isStale);
    return () => {
      stale = true;
    };
  }, [active, laneOn, loadPending, loadLane]);

  // a RENDERING tag outlives its job by nothing: it is READ against the
  // registry, so a job that ended (or that a restart forgot) drops it
  const didFor = (c: Concept): Acted | undefined => {
    const did = acted.get(c.id);
    if (!did || did.status !== "RENDERING") return did;
    return jobs.some((j) => j.id === did.job && ["queued", "running"].includes(j.status)) ? did : undefined;
  };

  /* ── the pick: lib/render-choice.ts (the plan leads when it can render,
     else the cheapest usable model; a held pick survives repaints AND
     leaving the page) ── */
  const catalogue = renderers as unknown as Renderers;
  const pickOf = (c: Concept): Pick | null => pickForCard(catalogue, c.id, c.render_default);
  const hold = (c: Concept, pick: Pick | null) => {
    if (!pick) return;
    held.set(c.id, pick);
    repaint((n) => n + 1);
  };
  // A card the reference gate refuses. The server lists these on this page
  // since 2026-09-17 (`blocked` = preprod.reference_gate's reason), after
  // every spendable card, so a picked scene with no photos does not read as
  // a lost pick. DISPLAY ONLY: the approve route asks the gate itself and
  // refuses whatever this button looks like. The refs check is the fallback
  // for a payload from before the field existed.
  const lockedFor = (c: Concept) => !!c.blocked || !(c.refs || []).length;

  /* A TIMED SCENE'S PRICE IS THE SERVER'S (src/pricing.py). The listing
     prices the card's default pick (`c.quote`); any other pick asks /quote
     once, and the card says "pricing…" until it answers rather than fit
     windows to a model here. The same quote carries the signed tokens the
     approve echoes. */
  const [quotes, setQuotes] = useState<Record<string, RenderQuote | { error: string }>>({});
  const quoteKey = (c: Concept, pick: Pick) =>
    `${c.id}|${pick.provider}|${pick.model}|${pick.frame}${c.timeline ? "" : `|${pick.duration}`}`;
  const served = (c: Concept, pick: Pick): RenderQuote | null => {
    const q = c.quote;
    if (!q || q.error || q.provider !== pick.provider || q.model !== pick.model || q.frame !== pick.frame) return null;
    if (!q.timed && q.durations[0] !== pick.duration) return null;
    return q;
  };
  const quoteOf = (c: Concept, pick: Pick | null) => (pick ? served(c, pick) ?? quotes[quoteKey(c, pick)] ?? null : null);
  const choiceOf = (pick: Pick): RenderChoice => ({
    provider: pick.provider,
    model: pick.model,
    duration: pick.duration ?? undefined,
    frame: pick.frame ?? undefined,
  });
  useEffect(() => {
    for (const c of pending || []) {
      if (!c.timeline || lockedFor(c)) continue;
      const pick = pickOf(c);
      if (!pick) continue;
      const key = quoteKey(c, pick);
      if (served(c, pick) || key in quotes) continue;
      queueQuote(c.id, choiceOf(pick))
        .then((q) => setQuotes((w) => ({ ...w, [key]: q })))
        .catch((e) => setQuotes((w) => ({ ...w, [key]: { error: e instanceof Error ? e.message : "no price" } })));
    }
    // pickOf / served read only what is listed here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, renderers, quotes, paint]);
  const gateLine = (p: string) => {
    const r = renderers[p];
    if (!r.available) return `${r.label}: no key`;
    return `${r.label}: ready${r.today != null ? ` · ${r.today}${r.cap ? `/${r.cap}` : ""} today` : ""}`;
  };
  const decide = async (c: Concept, what: "approve" | "reject" | "shot") => {
    setBusy((b) => ({ ...b, [c.id]: what }));
    setPopId(null);
    try {
      if (what === "approve") {
        const pick = pickOf(c);
        // the pick rides on the approve with the signed quotes for it
        // (pricing.sign; the route refuses if the scene or the pick moved
        // since). A pick the listing did not price is quoted on the click,
        // so the tokens always describe THIS pick. An empty body still
        // resolves to the plan.
        let choice: RenderChoice = pick ? choiceOf(pick) : {};
        if (pick) {
          const cached = quoteOf(c, pick);
          const q = cached && !("error" in cached && cached.error) ? (cached as RenderQuote) : await queueQuote(c.id, choice);
          const tokens = (q.renders || []).map((r) => r.token).filter((t): t is string => !!t);
          if (tokens.length) choice = { ...choice, tokens };
        }
        const res = await queueApprove(c.id, choice);
        const r = res.render;
        toast(
          r
            ? `Rendering ${c.n} — ${r.provider} · ${r.model} · ${r.frame} · ~$${Number(r.estimate_usd).toFixed(2)}`
            : `${c.n} approved`,
        );
        acted.set(c.id, { status: "RENDERING", job: res.job_id, at: Date.now() });
      } else if (what === "reject") {
        await queueReject(c.id);
        toast(`${c.n} rejected — archived, still counted`);
        acted.set(c.id, { status: "ARCHIVED", at: Date.now() });
      } else {
        await queueShot(c.id);
        toast(`${c.n} marked shot by hand`);
        acted.set(c.id, { status: "SHOT BY HAND", at: Date.now() });
      }
      held.delete(c.id);
      // the registry BEFORE the card is released: the RENDERING tag is read
      // against it, and a priced button that came back live for the beat in
      // between is a button that can be pressed twice
      await listJobs()
        .then((r) => setJobs(r.items.sort((a, b) => b.id - a.id)))
        .catch(() => loadJobs());
      if (laneOn) loadLane();
      announceQueueChange();
      if (what === "approve") loadPending();
      else {
        // said on the card for a beat, then the rows are re-read and it is
        // gone -- a card that simply vanished read as a misclick
        setTimeout(() => {
          acted.delete(c.id);
          loadPending();
        }, 900);
      }
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
        <span className="spacer" />
        <span className="m">{pending ? `${pending.filter((c) => !lockedFor(c)).length} waiting` : "—"}</span>
      </div>

      <div className="chead">
        <h3>Awaiting approval</h3>
        <span className="m">
          {pending ? `${pending.filter((c) => !lockedFor(c)).length} waiting${pending.some(lockedFor) ? ` · ${pending.filter(lockedFor).length} blocked` : ""}` : ""}
        </span>
        <span className="spacer" />
        <span className="m">
          {providerIds.length
            ? providerIds.map(gateLine).join(" · ")
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
      <div className="mx-auto mb-4 grid max-w-[1680px] grid-cols-[repeat(auto-fill,minmax(min(400px,100%),1fr))] items-start gap-6 px-[42px]">
        {(pending || []).map((c) => {
          const pick = pickOf(c);
          const locked = lockedFor(c);
          const did = didFor(c);
          const r = pick ? renderers[pick.provider] : undefined;
          const spec = pick ? specOf(catalogue, pick.provider, pick.model) : null;
          const quote = quoteOf(c, pick);
          const plan = pick && spec ? planFor(spec, pick, c.timeline ? partsOf(c) : null, quote) : null;
          // one reason left, and the only one a restart could ever have fixed
          const noKey = r && !r.available ? `${r.label} key not set` : "";
          const badLength = !!(pick && spec && plan && !plan.timed && !legalDuration(spec.duration as AxisLike, Number(pick.duration)));
          // a blocked card says WHY, in the gate's own words, not how it would anchor
          const why = locked
            ? `blocked · ${c.blocked || "no reference photos attached"}`
            : c.park_reason || (c.reference_image ? "anchors on the keyframe" : "text-to-video · no keyframe yet");
          const stills = stillsOf(c);
          const parts = partsOf(c);
          return (
            <article
              key={c.id}
              data-id={c.id}
              className={`${CARD} ${locked ? "border-[#5a2320]" : "border-noir-line2"} ${did && did.status !== "RENDERING" ? "opacity-35" : ""}`}
            >
              <Hero
                concept={c}
                disabled={!stills.length && !(c.refs || []).length}
                label={`Preview ${c.reference_image ? "keyframe" : "reference"} for ${c.title}`}
                onOpen={(trigger) =>
                  setPreview(
                    stills.length
                      ? { title: c.title, kind: "KEYFRAME", index: 0, trigger, items: stills.map((url) => ({ url })) }
                      : { title: c.title, kind: "REFERENCE", index: 0, trigger, items: refItems(c) },
                  )
                }
              >
                <span className={`${TAG} ${TAG_DARK} left-3 top-3 max-w-[55%]`}>{brandName(c.brand)}</span>
                {locked ? <span className={`${TAG} right-3 top-3 bg-noir-red tracking-[0.1em] text-noir-bg`}>NO REFS</span> : null}
                {did ? <span className={`${TAG} bottom-3 right-3 bg-bone tracking-[0.1em] text-noir-bg`}>{did.status}</span> : null}
              </Hero>

              {/* the shots, as frames whose WIDTH is their share of the scene */}
              {parts.length ? (
                <div className="flex min-w-0 gap-1 px-2 pt-2" role="group" aria-label={shotsLabel(c)}>
                  {parts.map((p) => {
                    const frame = `relative block h-11 min-w-0 basis-0 overflow-hidden rounded-[4px] bg-noir-slate p-0 ${p.media_url ? "opacity-60" : ""}`;
                    const label = (
                      <span className="absolute bottom-1 left-1.5 whitespace-nowrap font-plex text-[10px] leading-none text-bone [text-shadow:0_0_3px_#000,0_0_3px_#000]">
                        {windowLabel(p)}
                        {p.media_url ? " ✓" : ""}
                      </span>
                    );
                    const grow = { flexGrow: Number(p.seconds) > 0 ? Number(p.seconds) : 1 };
                    return p.reference_image ? (
                      <button
                        type="button"
                        key={p.n}
                        style={grow}
                        className={`${frame} focus-visible:rounded-[4px]!`}
                        title={p.text || p.prompt || ""}
                        aria-label={`Preview shot ${p.n} still, ${windowLabel(p)}`}
                        onClick={(e) =>
                          setPreview({ title: c.title, kind: "KEYFRAME", trigger: e.currentTarget, index: Math.max(0, stills.indexOf(p.reference_image!)), items: stills.map((url) => ({ url })) })
                        }
                      >
                        <RefImg url={p.reference_image} className="block size-full object-cover" deadLabel="" />
                        {label}
                      </button>
                    ) : (
                      <div key={p.n} style={grow} className={frame} title={p.text || p.prompt || ""}>
                        {label}
                      </div>
                    );
                  })}
                </div>
              ) : null}

              <div className="flex min-w-0 flex-col gap-3 px-4 pb-4 pt-3.5">
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                  <TitleBlock concept={c} />
                  <div className="flex flex-none gap-1">
                    <RefThumbs
                      concept={c}
                      max={3}
                      size="sm"
                      onOpen={(index, trigger) => setPreview({ title: c.title, kind: "REFERENCE", index, trigger, items: refItems(c) })}
                    />
                  </div>
                </div>
                <p className="-mt-1 mb-0 truncate font-plex text-[11px] tracking-[0.04em] text-bone3" title={why}>
                  {c.n} · {c.parked ? "PARKED" : "PICKED"} · {why}
                </p>

                {/* the renderer: ONE chip, and a popover over the same catalogue */}
                <Popover.Root open={popId === c.id && !did && !locked && !!pick} onOpenChange={(o) => setPopId(o ? c.id : null)}>
                  <Popover.Trigger
                    disabled={locked || !pick || !!did}
                    aria-label={locked || !pick ? "Renderer locked" : `Change renderer — ${spec && plan ? chipText(spec, pick, plan) : ""}`}
                    className="flex h-11 w-full items-center justify-between gap-2 rounded-[8px] border border-noir-line bg-noir-well px-3 font-plex! text-xs! leading-none! tracking-[0.06em] text-bone! hover:enabled:border-bone focus-visible:rounded-[8px]! disabled:cursor-not-allowed disabled:text-bone3! data-[popup-open]:[&>svg]:rotate-180"
                  >
                    <span className="min-w-0 truncate">
                      {locked ? "RENDERER LOCKED" : !pick || !spec || !plan ? "NO RENDERER CONFIGURED" : chipText(spec, pick, plan)}
                    </span>
                    <ChevronDown size={16} strokeWidth={2} aria-hidden className="flex-none" />
                  </Popover.Trigger>
                  <Popover.Portal>
                    <Popover.Positioner side="bottom" align="start" sideOffset={8} className="z-[800]">
                      <Popover.Popup
                        aria-label={`Renderer for ${c.title}`}
                        className={`${cardFonts} flex w-[var(--anchor-width)] flex-col gap-2.5 rounded-[10px] border border-noir-line3 bg-noir-raise p-4 text-bone shadow-[0_18px_40px_rgb(0_0_0/0.55)] outline-none`}
                      >
                        {pick && spec && plan && r ? (
                          <>
                            <div>
                              <div className={POPK}>MODEL</div>
                              <div className="flex flex-wrap items-center gap-1.5">
                                {providerIds.map((name) => {
                                  const v = renderers[name];
                                  // a vendor with no key is one dead pill, not a row of them
                                  if (!v.available)
                                    return (
                                      <button type="button" key={name} disabled className={pill(false, true)}>
                                        {v.label} · no key
                                      </button>
                                    );
                                  return (v.models || []).map((m) => (
                                    <button
                                      type="button"
                                      key={`${name}|${m.id}`}
                                      title={v.label}
                                      disabled={m.available === false}
                                      aria-pressed={pick.provider === name && pick.model === m.id}
                                      className={pill(pick.provider === name && pick.model === m.id, m.available === false)}
                                      onClick={() => hold(c, withModel(catalogue, name, m.id))}
                                    >
                                      {m.label}
                                      {m.available === false ? " · not on this account" : ""}
                                    </button>
                                  ));
                                })}
                              </div>
                            </div>
                            <div className="mt-1 grid grid-cols-2 gap-3">
                              <div>
                                <div className={POPK}>LENGTH{plan.timed ? " · PER SHOT" : ""}</div>
                                <div className="flex flex-wrap items-center gap-1.5">
                                  {plan.timed ? (
                                    // no length control: every shot's length is its window's
                                    <span className="font-plex text-[11px] text-bone3" title={`each shot renders at its own window's length, fitted up to what ${spec.id} can make`}>
                                      {plan.lengths.length ? `${plan.lengths.join(" + ")}s · set by the windows` : plan.refused || "pricing…"}
                                    </span>
                                  ) : spec.duration.kind === "range" ? (
                                    // a real span, so 7s on a model that renders 1-20s is a real request
                                    <span className="flex items-center gap-2 font-plex text-[11px] text-bone3">
                                      <input
                                        type="number"
                                        min={spec.duration.min}
                                        max={spec.duration.max}
                                        step={1}
                                        value={pick.duration ?? ""}
                                        aria-label={`Length in seconds, ${spec.duration.min} to ${spec.duration.max}`}
                                        onChange={(e) => hold(c, { ...pick, duration: e.target.value === "" ? null : Number(e.target.value) })}
                                        className="h-11 w-[72px] rounded-[6px] border border-noir-line3 bg-noir-well text-center font-plex! text-[13px]! text-bone! outline-none focus:border-bone"
                                      />
                                      sec · {spec.duration.min}–{spec.duration.max}
                                    </span>
                                  ) : (
                                    (spec.duration.values || []).map((d) => (
                                      <button
                                        type="button"
                                        key={String(d)}
                                        disabled={spec.duration.kind === "fixed"}
                                        title={spec.duration.kind === "fixed" ? spec.duration.note || "the only length this model offers" : undefined}
                                        aria-pressed={Number(d) === pick.duration}
                                        className={pill(Number(d) === pick.duration, spec.duration.kind === "fixed")}
                                        onClick={() => hold(c, { ...pick, duration: Number(d) })}
                                      >
                                        {d}s
                                      </button>
                                    ))
                                  )}
                                </div>
                              </div>
                              <div>
                                <div className={POPK}>FRAME · {String(r.frame_axis || "resolution").toUpperCase()}</div>
                                <div className="flex flex-wrap items-center gap-1.5">
                                  {(spec.frame.values || []).map((f) => (
                                    <button
                                      type="button"
                                      key={String(f)}
                                      disabled={spec.frame.kind === "fixed"}
                                      title={spec.frame.kind === "fixed" ? spec.frame.note || "the only frame this model offers" : RATIO_NAMES[String(f)]}
                                      aria-pressed={String(f) === pick.frame}
                                      className={pill(String(f) === pick.frame, spec.frame.kind === "fixed")}
                                      onClick={() => hold(c, { ...pick, frame: String(f) })}
                                    >
                                      {String(f)}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            </div>
                            <div className="font-plex text-[11px] text-bone3">Greyed out = no API key on this account</div>
                          </>
                        ) : null}
                      </Popover.Popup>
                    </Popover.Positioner>
                  </Popover.Portal>
                </Popover.Root>

                <div className="flex min-w-0 gap-2">
                  <button
                    type="button"
                    disabled={locked || !pick || !!noKey || badLength || !!did || !!busy[c.id]}
                    onClick={() => decide(c, "approve")}
                    className="h-[52px] min-w-0 flex-1 truncate rounded-[8px] bg-noir-red px-2.5 font-bebas! text-[22px]! leading-none! tracking-[0.05em] text-noir-bg! hover:enabled:bg-noir-red2 focus-visible:rounded-[8px]! disabled:cursor-not-allowed disabled:bg-noir-line2 disabled:text-bone3!"
                  >
                    {busy[c.id] === "approve" || did?.status === "RENDERING"
                      ? "Rendering…"
                      : did
                        ? did.status
                        : locked
                          ? "Add references to approve"
                          : !pick || !spec || !plan
                            ? "No renderer is configured"
                            : noKey
                              ? noKey
                              : badLength
                                ? `${spec.id} renders ${spec.duration.min}-${spec.duration.max}s`
                                : approveText(plan)}
                  </button>
                  <button
                    type="button"
                    className={`${SIDE_BTN} text-bone!`}
                    title="Reject — archive it"
                    aria-label={`Reject ${c.title}`}
                    disabled={!!did || !!busy[c.id]}
                    onClick={() => decide(c, "reject")}
                  >
                    <X size={18} strokeWidth={2} aria-hidden />
                  </button>
                  <button
                    type="button"
                    className={`${SIDE_BTN} ${did?.status === "SHOT BY HAND" ? "border-bone! text-bone!" : "text-bone3!"}`}
                    title="Shot it yourself"
                    aria-label={`Mark ${c.title} as shot by hand — made outside the render pipeline`}
                    disabled={!!did || !!busy[c.id]}
                    onClick={() => decide(c, "shot")}
                  >
                    <Camera size={20} strokeWidth={2} aria-hidden />
                  </button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
      {preview ? <PreviewOverlay key={`${preview.title}-${preview.kind}-${preview.index}`} state={preview} onClose={() => setPreview(null)} /> : null}

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

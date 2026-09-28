"use client";

/* References — the contact sheet (2026-09-25).

   The hunt reads a spark, lists what it needs photographs OF, searches
   one need at a time and LOOKS at every frame that comes back. It banks
   NOTHING: this page is the approval, which is the half invideo's
   Referencer gets right and this pipeline never had — until today a
   crawled image went into a spark's bin with nobody having seen it, and
   the six YouTube thumbnails that reached a Zero Page scene were found
   by opening the files by hand.

   Two things the UI must not soften. A rejected frame is shown WITH its
   reason and can be overruled with a click: a check that cannot be
   argued with is a check people route around. And a frame is banked by
   the candidate id the hunt served — never a URL — so nothing here can
   put an address in the bin that no lane ever returned. */
/* eslint-disable @next/next/no-img-element */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Images, RefreshCw, X } from "lucide-react";
import {
  getReferenceSparks,
  keepReferences,
  runReferenceHunt,
  waitForJob,
  type ReferenceSheet,
  type SheetFrame,
  type SheetNeed,
  type SparkRow,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";

const CARD = "rounded-xl border border-white/10 bg-white/[0.03]";
const BTN = "rounded-lg px-3 py-1.5 text-[13px] transition disabled:opacity-40";

/* A frame the person has decided on. Keepers start in; a rejection has
   to be clicked back in, which is the asymmetry the check is for. */
type Chosen = Record<string, boolean>;

function frameKey(f: SheetFrame) {
  return f.id;
}

function Frame({
  frame,
  role,
  chosen,
  rejected,
  onToggle,
}: {
  frame: SheetFrame;
  role: string;
  chosen: boolean;
  rejected?: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      title={frame.why || frame.kept_for || ""}
      className={`group relative block overflow-hidden rounded-lg border text-left transition ${
        chosen ? "border-emerald-400/70" : "border-white/10 hover:border-white/30"
      }`}
    >
      {frame.image_url ? (
        <img
          src={frame.image_url}
          alt={frame.kept_for || frame.why || role}
          className={`h-32 w-full object-cover transition ${
            chosen ? "" : rejected ? "opacity-35 grayscale" : "opacity-80"
          }`}
        />
      ) : (
        <div className="h-32 w-full bg-white/5" />
      )}
      <span
        className={`absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${
          chosen ? "bg-emerald-400 text-black" : "bg-black/70 text-white/70"
        }`}
      >
        {chosen ? <Check size={12} /> : <X size={12} />}
      </span>
      <span className="block px-2 py-1.5 text-[11px] leading-snug text-white/60">
        {frame.kept_for || frame.why || "no note"}
      </span>
    </button>
  );
}

function Need({
  need,
  chosen,
  toggle,
}: {
  need: SheetNeed;
  chosen: Chosen;
  toggle: (id: string) => void;
}) {
  const [showRejected, setShowRejected] = useState(false);
  return (
    <section className={`${CARD} p-3`}>
      <header className="mb-2 flex flex-wrap items-baseline gap-2">
        <span className="rounded bg-white/10 px-1.5 py-0.5 text-[11px] uppercase tracking-wide">
          {need.role}
        </span>
        <span className="text-[13px] text-white/80">{need.query}</span>
        <span className="ml-auto text-[11px] text-white/40">
          {need.found} found · {need.keepers.length} passed the check
        </span>
      </header>
      {need.keepers.length ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {need.keepers.map((f) => (
            <Frame
              key={frameKey(f)}
              frame={f}
              role={need.role}
              chosen={!!chosen[f.id]}
              onToggle={() => toggle(f.id)}
            />
          ))}
        </div>
      ) : (
        <p className="text-[12px] text-white/50">{need.note || "nothing usable came back"}</p>
      )}
      {need.rejected.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setShowRejected((v) => !v)}
            className="mt-2 text-[11px] text-white/40 underline-offset-2 hover:text-white/70 hover:underline"
          >
            {showRejected ? "hide" : "show"} {need.rejected.length} rejected
          </button>
          {showRejected && (
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {need.rejected.map((f) => (
                <Frame
                  key={frameKey(f)}
                  frame={f}
                  role={need.role}
                  rejected
                  chosen={!!chosen[f.id]}
                  onToggle={() => toggle(f.id)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default function ReferencesPage() {
  const { brand, toast } = useShell();
  const [sparks, setSparks] = useState<SparkRow[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [sheet, setSheet] = useState<ReferenceSheet | null>(null);
  const [chosen, setChosen] = useState<Chosen>({});
  const [busy, setBusy] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const data = await getReferenceSparks(brand);
      setSparks(data.items);
    } catch (e) {
      toast(e instanceof Error ? e.message : "could not read the sparks", "err");
    }
  }, [brand, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const hunt = useCallback(
    async (findingId: number) => {
      setSelected(findingId);
      setSheet(null);
      setChosen({});
      setBusy("reading the scene…");
      try {
        const { job_id } = await runReferenceHunt(findingId);
        const job = await waitForJob(job_id, (j) => setBusy(j.detail || "hunting…"), 1200);
        if (job.status !== "done" || !job.output) {
          throw new Error(job.detail || "the hunt failed");
        }
        const result = JSON.parse(job.output) as ReferenceSheet;
        setSheet(result);
        // Keepers start selected; a rejection does not.
        const start: Chosen = {};
        result.sheet.forEach((n) => n.keepers.forEach((f) => (start[f.id] = true)));
        setChosen(start);
      } catch (e) {
        toast(e instanceof Error ? e.message : "the hunt failed", "err");
      } finally {
        setBusy("");
      }
    },
    [toast],
  );

  const toggle = useCallback((id: string) => {
    setChosen((c) => ({ ...c, [id]: !c[id] }));
  }, []);

  const picked = useMemo(() => Object.keys(chosen).filter((id) => chosen[id]), [chosen]);

  const bank = useCallback(async () => {
    if (selected === null || !picked.length) return;
    setBusy("banking…");
    try {
      const result = await keepReferences(selected, picked);
      toast(
        `${result.banked} kept${result.refused.length ? ` · ${result.refused.length} refused` : ""}`,
        result.banked ? "ok" : "err",
      );
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "nothing was banked", "err");
    } finally {
      setBusy("");
    }
  }, [selected, picked, toast, load]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-4 sm:p-6">
      <header className="flex items-center gap-2">
        <Images size={18} className="text-white/60" />
        <h1 className="text-[15px] tracking-wide">References</h1>
        <span className="text-[12px] text-white/40">
          every frame is looked at before it is offered — nothing is banked until you say
        </span>
        <button
          type="button"
          onClick={() => void load()}
          className={`${BTN} ml-auto border border-white/10 hover:bg-white/10`}
        >
          <RefreshCw size={13} className="mr-1 inline" /> refresh
        </button>
      </header>

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <aside className={`${CARD} max-h-[70vh] overflow-auto p-2`}>
          {sparks.length === 0 && (
            <p className="p-3 text-[12px] text-white/50">
              No unused sparks for {brand}. Run a research pass first.
            </p>
          )}
          {sparks.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => void hunt(s.id)}
              className={`mb-1 block w-full rounded-lg p-2 text-left text-[12px] leading-snug transition ${
                selected === s.id ? "bg-white/10" : "hover:bg-white/[0.06]"
              }`}
            >
              <span className="mr-2 text-white/40">#{s.id}</span>
              <span className={s.images ? "text-white/40" : "text-amber-300/80"}>
                {s.images} image{s.images === 1 ? "" : "s"}
              </span>
              <span className="mt-1 block text-white/80">{s.spark.slice(0, 160)}</span>
            </button>
          ))}
        </aside>

        <main className="flex flex-col gap-3">
          {busy && <p className="text-[12px] text-white/50">{busy}</p>}
          {!busy && !sheet && (
            <p className="text-[12px] text-white/50">
              Pick a spark to hunt references for. It costs a few model calls and banks nothing.
            </p>
          )}
          {sheet && (
            <>
              <div className="flex flex-wrap items-center gap-2 text-[12px] text-white/50">
                <span>{sheet.note}</span>
                {!sheet.checked && (
                  <span className="rounded bg-amber-400/15 px-2 py-0.5 text-amber-200">
                    some frames could not be looked at — nothing was offered for those
                  </span>
                )}
                <span className="ml-auto">planner: {sheet.planner}</span>
              </div>
              {sheet.sheet.map((need) => (
                <Need key={`${need.role}-${need.query}`} need={need} chosen={chosen} toggle={toggle} />
              ))}
              <div className="sticky bottom-3 flex items-center gap-3 rounded-xl border border-white/10 bg-black/80 p-3 backdrop-blur">
                <span className="text-[12px] text-white/60">{picked.length} selected</span>
                <button
                  type="button"
                  disabled={!picked.length || !!busy}
                  onClick={() => void bank()}
                  className={`${BTN} ml-auto bg-white text-black hover:bg-white/90`}
                >
                  Keep {picked.length || ""} for this spark
                </button>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

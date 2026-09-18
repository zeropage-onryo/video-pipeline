"use client";

/* Elements (2026-09-11, the "ZPF Elements" design): the thing you @ in
   a prompt to hold a shot to it. An element IS one asset row — the
   same character / location / prop rows the Assets wall groups photos
   under — surfaced with its plate, @handle, frame count and how many
   concepts it has grounded. It replaces Analytics in the rail.

   The cover is the collection; "See all" flips to the grid. New
   element is the same always-on create path the Jinja modal posts to
   (/api/assets/{characters|locations|props}), which also teaches the
   RAG assets shelf. Since 2026-09-18 this page reads the `elements`
   scope only -- a render is an Asset, never an element (one used to
   show up here as "@runway-image") -- and a card can be deleted: the
   row and its RAG chunk go, the photos on disk stay. An element also
   gets a REFERENCE SHEET (2026-09-18, part of adding one): drawn on
   save as a job from the real photos, it becomes the card's plate and
   rides LAST in the element's photos; "Draw sheet" on a card is the
   same route for elements saved before, or a redraw. A click on a card
   opens the element sheet (frames, @handle, notes, where it grounds,
   its own delete) -- the hover buttons on the plate are the shortcuts. */
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ImageOff, Info, LayoutGrid, Plus, Trash2 } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  boardConcepts,
  deleteAsset,
  drawSheet,
  getAssets,
  getCapabilities,
  getJob,
  type Asset,
  type Concept,
  type ElementKind,
} from "@/lib/studio-api";
import { displayPhoto, elementKind, handleOf, kindLabel } from "@/lib/elements";
import { useShell } from "@/components/studio/shell";
import { AddElement } from "@/components/studio/add-element";
import { ElementSheet } from "@/components/studio/element-sheet";

const slugOf = (url: string) => url.match(/^\/(characters|locations|props)\/([^/]+)\//)?.[2] ?? null;
const ROUTE_KIND = { character: "characters", prop: "props", location: "locations" } as const;
type RouteKind = ElementKind;
/* "character-12" -> ["characters", 12]: the id the delete route takes */
const routeOf = (a: Asset): [RouteKind, number] | null => {
  const m = a.id.match(/^(character|prop|location)-(\d+)$/);
  return m ? [ROUTE_KIND[m[1] as keyof typeof ROUTE_KIND], Number(m[2])] : null;
};

export default function ElementsPage() {
  const { brand, toast } = useShell();
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [grid, setGrid] = useState(false);
  const [howto, setHowto] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [open, setOpen] = useState<Asset | null>(null);
  const [canDraw, setCanDraw] = useState(false);
  // element id -> the job drawing its sheet; the card shows it until the job lands
  const [drawing, setDrawing] = useState<Record<string, number>>({});

  // watch a sheet job: the card says "drawing" until it lands, then reloads
  const watchSheet = (assetId: string, jobId: number, name: string) => {
    setDrawing((was) => ({ ...was, [assetId]: jobId }));
    const tick = () =>
      getJob(jobId)
        .then((job) => {
          if (job.status === "queued" || job.status === "running") {
            setTimeout(tick, 2000);
            return;
          }
          setDrawing((was) => {
            const next = { ...was };
            delete next[assetId];
            return next;
          });
          if (job.status === "done") toast(`${name} · sheet drawn`);
          else toast(`${name} · sheet not drawn: ${job.error || job.status}`, "err");
          load();
        })
        .catch(() => setTimeout(tick, 4000));
    setTimeout(tick, 1500);
  };

  const draw = (a: Asset) => {
    const route = routeOf(a);
    if (!route) return;
    drawSheet(route[0], route[1])
      .then((r) => watchSheet(a.id, r.job_id, a.name))
      .catch((e) => toast(e instanceof Error ? e.message : "Could not draw the sheet", "err"));
  };

  const remove = (a: Asset) => {
    const route = routeOf(a);
    if (!route) return;
    deleteAsset(route[0], route[1])
      .then(() => {
        setConfirming(null);
        setAssets((was) => (was ?? []).filter((x) => x.id !== a.id));
        toast(`${a.name} deleted · photos stay on disk`);
      })
      .catch((e) => toast(e instanceof Error ? e.message : "Could not delete", "err"));
  };

  const load = () => {
    getAssets(undefined, "elements")
      .then((r) => {
        setAssets(r.items);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
    boardConcepts()
      .then((r) => setConcepts(r.items))
      .catch(() => setConcepts([]));
  };
  useEffect(() => {
    load();
    getCapabilities()
      .then((c) => setCanDraw(c["nano.generate"] !== false))
      .catch(() => setCanDraw(false));
  }, []);

  // how many concepts an element has grounded: a ref url carries the
  // asset's slug, so the count is the concepts whose refs name it
  const usage = useMemo(() => {
    const bySlug = new Map<string, number>();
    for (const c of concepts) {
      const slugs = new Set((c.refs || []).map(slugOf).filter(Boolean) as string[]);
      for (const s of slugs) bySlug.set(s, (bySlug.get(s) || 0) + 1);
    }
    return bySlug;
  }, [concepts]);
  const slugFor = (a: Asset) => (a.photos[0] ? slugOf(a.photos[0]) : null) ?? handleOf(a.name).slice(1);

  const all = assets ?? [];
  const collage = all.filter((a) => displayPhoto(a)).slice(0, 4);

  return (
    <section className="view" style={{ paddingTop: 0, display: "flex", flexDirection: "column", minHeight: "calc(100vh - 80px)" }}>
      <div className="vhead" style={{ marginTop: 8 }}>
        <span className="m">{assets ? `${all.length} element${all.length === 1 ? "" : "s"} · ${brand || "—"}` : "loading…"}</span>
        <span className="spacer" />
        <button type="button" className="tag" onClick={() => setGrid((v) => !v)}>
          {grid ? "Collection cover" : `See all ${all.length}`}
        </button>
      </div>

      {error ? <div className="stateline err" style={{ padding: "14px 42px" }}>{error}</div> : null}

      {!grid ? (
        <>
          <div className="elcover">
            <div>
              <p className="kicker">Elements collection</p>
              <h1>{brand === "antihero" ? "Antihero" : "Zero Page"}</h1>
              <p className="lead">
                Save characters, props, products, or places you want to reuse, and hold every shot to them:
                @-mention one in a prompt and its frames ride into the enhance, the keyframe and the clip.
              </p>
              <div className="elactions">
                <button type="button" className="elnew" onClick={() => setAdding(true)}>
                  <Plus strokeWidth={2.2} /> New element
                </button>
                <button type="button" className="elhow" onClick={() => setHowto((v) => !v)} aria-expanded={howto}>
                  <Info strokeWidth={1.7} /> How to
                </button>
              </div>
            </div>
            <div className="elcollage" aria-hidden>
              {collage.map((a) => (
                <span key={a.id} style={{ backgroundImage: `url(${API_URL}${displayPhoto(a)})` }} />
              ))}
            </div>
          </div>
          {howto ? (
            <div className="elhowto">
              <ol>
                <li>
                  <b>Add the element</b> with three or more photos — a face from two angles and the wardrobe, or a room in
                  its real light. The photos become the frames a shot is held to.
                </li>
                <li>
                  <b>Name it in a prompt.</b> Type <code>@</code> in Studio or on the Director canvas and pick it. Studio
                  attaches its frames as references; Director drops an element card wired into the chain.
                </li>
                <li>
                  <b>Let the notes do work.</b> What you write becomes a searchable chunk on the RAG assets shelf, so the
                  writer can retrieve the jacket by description, not only by name.
                </li>
              </ol>
            </div>
          ) : null}
        </>
      ) : (
        <div className="elgrid">
          <button type="button" className="elnewcard" onClick={() => setAdding(true)}>
            <Plus strokeWidth={1.6} />
            <span className="m" style={{ fontSize: 8.5 }}>
              New element
            </span>
          </button>
          <AnimatePresence initial={false}>
          {all.map((a) => {
            const used = usage.get(slugFor(a)) || 0;
            const asking = confirming === a.id;
            const plate = displayPhoto(a);
            return (
              <motion.article
                key={a.id}
                className="elcard group relative"
                role="button"
                tabIndex={0}
                title="Open"
                onClick={() => setOpen(a)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setOpen(a);
                  }
                }}
                layout
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
              >
                <div
                  className={`elplate${plate ? "" : " blank"}${a.sheet ? " sheet" : ""}`}
                  style={plate ? { backgroundImage: `url(${API_URL}${plate})` } : undefined}
                >
                  {!plate ? (
                    <span className="m">
                      <ImageOff strokeWidth={1.6} size={13} /> no photos yet
                    </span>
                  ) : null}
                  {drawing[a.id] ? (
                    <motion.span
                      className="m absolute bottom-2 left-2 flex items-center gap-1.5 rounded-full bg-black/75 px-2.5 py-1"
                      animate={{ opacity: [0.55, 1, 0.55] }}
                      transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
                    >
                      <LayoutGrid size={10} strokeWidth={1.7} /> drawing sheet…
                    </motion.span>
                  ) : null}
                  {asking ? (
                    <div
                      className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/75 p-3 text-center"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <span className="m" style={{ fontSize: 9 }}>
                        delete {a.name}? {used ? `it grounds ${used} shot${used === 1 ? "" : "s"}` : "photos stay on disk"}
                      </span>
                      <div className="flex gap-1.5">
                        <button type="button" className="zbtn" onClick={() => setConfirming(null)}>
                          Keep
                        </button>
                        <button type="button" className="zbtn pri" onClick={() => remove(a)}>
                          Delete
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      className="absolute top-2 right-2 flex gap-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {canDraw && a.photos.length && !drawing[a.id] ? (
                        <button
                          type="button"
                          className="zdx bg-black/70"
                          aria-label={`${a.sheet ? "Redraw" : "Draw"} the sheet for ${a.name}`}
                          title={a.sheet ? "Redraw sheet · a few cents" : "Draw sheet · a few cents"}
                          onClick={() => draw(a)}
                        >
                          <LayoutGrid size={13} strokeWidth={1.7} />
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="zdx bg-black/70"
                        aria-label={`Delete ${a.name}`}
                        title="Delete"
                        onClick={() => setConfirming(a.id)}
                      >
                        <Trash2 size={13} strokeWidth={1.7} />
                      </button>
                    </div>
                  )}
                </div>
                <div className="elbody">
                  <div className="elname">
                    <b>{a.name}</b>
                    <span className="elcat">{kindLabel(elementKind(a) ?? "prop")}</span>
                  </div>
                  <p className="elhandle">{handleOf(a.name)}</p>
                </div>
                {a.photos.length > 1 ? (
                  <div className="elframes">
                    {a.photos.slice(0, 4).map((u) => (
                      <span key={u} style={{ backgroundImage: `url(${API_URL}${u})` }} />
                    ))}
                  </div>
                ) : null}
                <div className="elfoot">
                  <span className="m">
                    {a.photos.length ? `${a.photos.length} frame${a.photos.length === 1 ? "" : "s"}${a.sheet ? " · sheet" : ""}` : "no photos yet"}
                  </span>
                  <span className="spacer" />
                  <span className="m used">{used ? `in ${used} shot${used === 1 ? "" : "s"}` : "not used yet"}</span>
                </div>
              </motion.article>
            );
          })}
          </AnimatePresence>
        </div>
      )}

      {open ? (
        <ElementSheet
          asset={open}
          usedIn={usage.get(slugFor(open)) || 0}
          onClose={() => setOpen(null)}
          onDeleted={(a) => {
            setOpen(null);
            setAssets((was) => (was ?? []).filter((x) => x.id !== a.id));
            toast(`${a.name} deleted · photos stay on disk`);
          }}
        />
      ) : null}

      {adding ? (
        <AddElement
          onClose={() => setAdding(false)}
          onSaved={(name, photos, _note, sheetJob) => {
            setAdding(false);
            setGrid(true);
            toast(`${name} saved · ${photos} photo${photos === 1 ? "" : "s"}${sheetJob ? " · drawing the sheet" : " · teaching the assets shelf"}`);
            // the new card's id is only known after the reload
            getAssets(undefined, "elements")
              .then((r) => {
                setAssets(r.items);
                const made = r.items.find((a) => a.name === name);
                if (sheetJob && made) watchSheet(made.id, sheetJob, name);
              })
              .catch(() => load());
          }}
        />
      ) : null}
    </section>
  );
}

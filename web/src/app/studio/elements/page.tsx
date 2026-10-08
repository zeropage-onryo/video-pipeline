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
   show up here as a render's own "@…-image" name) -- and a card can be deleted: the
   row and its RAG chunk go, the photos on disk stay. An element also
   gets a REFERENCE SHEET (2026-09-18, part of adding one): drawn on
   save as a job from the real photos, it becomes the card's plate and
   rides LAST in the element's photos; "Draw sheet" on a card is the
   same route for elements saved before, or a redraw. A click on a card
   opens the element sheet (frames, @handle, notes, where it grounds,
   its own delete) -- the hover buttons on the plate are the shortcuts. */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { ImageOff, Info, LayoutGrid, Plus, Trash2 } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  announceBalanceChange,
  drawSheet,
  getAssets,
  getCapabilities,
  getJob,
  type Asset,
  type ElementKind,
} from "@/lib/studio-api";
import { creditsText } from "@/lib/render-choice";
import { displayPhoto, elementKind, handleOf, kindLabel } from "@/lib/elements";
import { useShell } from "@/components/studio/shell";
import { AddElement } from "@/components/studio/add-element";
import { ElementSheet, useElementDelete } from "@/components/studio/element-sheet";
import { UrlParams } from "@/components/studio/url-params";

const ROUTE_KIND = { character: "characters", prop: "props", location: "locations" } as const;
type RouteKind = ElementKind;
/* "character-12" -> ["characters", 12]: the id the delete route takes */
const routeOf = (a: Asset): [RouteKind, number] | null => {
  const m = a.id.match(/^(character|prop|location)-(\d+)$/);
  return m ? [ROUTE_KIND[m[1] as keyof typeof ROUTE_KIND], Number(m[2])] : null;
};

export default function ElementsPage() {
  const { brand, toast, balance } = useShell();
  // a sheet is one still, priced like any other before the click that draws it
  const sheetPrice = balance?.prices ? creditsText(balance.prices.still, !!balance.exempt) : null;
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [grid, setGrid] = useState(false);
  const [howto, setHowto] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [open, setOpen] = useState<Asset | null>(null);
  // the element a deep link asked for (?open=<id>, the ⌘K palette), opened
  // as soon as the list holds it; ?new=1 opens the add form
  const [want, setWant] = useState<string | null>(null);
  const router = useRouter();
  const wanted = want && assets ? (assets.find((a) => a.id === want) ?? null) : null;
  const sheet = open ?? wanted;
  const closeSheet = () => {
    setOpen(null);
    setWant(null);
  };
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
          // the still's hold settled (or was released) as the job ended
          announceBalanceChange();
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

  // the card's own delete and the sheet's go through one held delete with
  // an Undo (element-sheet.tsx): off the page now, sent when the toast closes
  const removeElement = useElementDelete();
  const hide = (a: Asset) => setAssets((was) => (was ?? []).filter((x) => x.id !== a.id));
  const remove = (a: Asset) => {
    if (!routeOf(a)) return;
    setConfirming(null);
    removeElement(a, { hide: () => hide(a), restore: () => load() });
  };

  const load = () => {
    getAssets(undefined, "elements")
      .then((r) => {
        setAssets(r.items);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
  };
  useEffect(() => {
    load();
    getCapabilities()
      .then((c) => setCanDraw(c["nano.generate"] !== false))
      .catch(() => setCanDraw(false));
  }, []);


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
                  <b>Name it in a prompt.</b> Type <code>@</code> in Studio or on a scene&rsquo;s canvas in its project and pick
                  it. Studio attaches its frames as references; the canvas drops an element card wired into the chain.
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
            const used = a.used_in ?? 0;
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
                          title={`${a.sheet ? "Redraw" : "Draw"} sheet${sheetPrice ? ` · ${sheetPrice}` : ""}`}
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

      <UrlParams
        onParams={(params) => {
          const id = params.get("open");
          const make = params.get("new");
          if (id) {
            setOpen(null);
            setWant(id);
          }
          if (make) {
            // one dialog at a time: a sheet left open is closed first
            closeSheet();
            setAdding(true);
          }
          // said once: a reload must not open it again
          if (id || make) router.replace("/studio/elements", { scroll: false });
        }}
      />
      {sheet ? (
        <ElementSheet
          asset={sheet}
          usedIn={sheet.used_in ?? 0}
          onClose={closeSheet}
          onDeleted={(a) => {
            closeSheet();
            hide(a);
          }}
          onRestored={() => load()}
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

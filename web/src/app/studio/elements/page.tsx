"use client";

/* Elements (2026-09-11, the "ZPF Elements" design): the thing you @ in
   a prompt to hold a shot to it. An element IS one asset row — the
   same character / location / prop rows the Assets wall groups photos
   under — surfaced with its plate, @handle, frame count and how many
   concepts it has grounded. It replaces Analytics in the rail.

   The cover is the collection; "See all" flips to the grid. New
   element is the same always-on create path the Jinja modal posts to
   (/api/assets/{characters|locations|props}), which also teaches the
   RAG assets shelf. */
/* eslint-disable @next/next/no-img-element */
import { useEffect, useMemo, useState } from "react";
import { ImageOff, Info, Plus } from "lucide-react";
import { API_URL } from "@/lib/api";
import { boardConcepts, getAssets, type Asset, type Concept } from "@/lib/studio-api";
import { displayPhoto, elementKind, isElement, kindLabel } from "@/lib/elements";
import { useShell } from "@/components/studio/shell";
import { AddElement } from "@/components/studio/add-element";
import { ElementSheet } from "@/components/studio/element-sheet";
import { handleOf } from "@/lib/elements";
const slugOf = (url: string) => url.match(/^\/(characters|locations|props)\/([^/]+)\//)?.[2] ?? null;

export default function ElementsPage() {
  const { brand, toast } = useShell();
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [grid, setGrid] = useState(false);
  const [howto, setHowto] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<Asset | null>(null);

  const load = () => {
    getAssets()
      .then((r) => {
        setAssets(r.items);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
    boardConcepts()
      .then((r) => setConcepts(r.items))
      .catch(() => setConcepts([]));
  };
  useEffect(load, []);

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

  // elements only: the Assets wall's generated stills are not something a
  // person created to @ (Mike's call, 2026-09-15)
  const all = (assets ?? []).filter(isElement);
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
          {all.map((a) => {
            const used = usage.get(slugFor(a)) || 0;
            return (
              <article
                key={a.id}
                className="elcard"
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
              >
                <div
                  className={`elplate${displayPhoto(a) ? "" : " blank"}`}
                  style={displayPhoto(a) ? { backgroundImage: `url(${API_URL}${displayPhoto(a)})` } : undefined}
                >
                  {!displayPhoto(a) ? (
                    <span className="m">
                      <ImageOff strokeWidth={1.6} size={13} /> no photos yet
                    </span>
                  ) : null}
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
                    {a.photos.length ? `${a.photos.length} frame${a.photos.length === 1 ? "" : "s"}` : "no photos yet"}
                  </span>
                  <span className="spacer" />
                  <span className="m used">{used ? `in ${used} shot${used === 1 ? "" : "s"}` : "not used yet"}</span>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {open ? (
        <ElementSheet
          asset={open}
          usedIn={usage.get(slugFor(open)) || 0}
          onClose={() => setOpen(null)}
          onDeleted={(a) => {
            setOpen(null);
            toast(`${a.name} deleted`);
            load();
          }}
        />
      ) : null}

      {adding ? (
        <AddElement
          onClose={() => setAdding(false)}
          onSaved={(name, photos) => {
            setAdding(false);
            setGrid(true);
            toast(`${name} saved · ${photos} photo${photos === 1 ? "" : "s"} · teaching the assets shelf`);
            load();
          }}
        />
      ) : null}
    </section>
  );
}

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
import { useEffect, useMemo, useRef, useState } from "react";
import { Image as ImageIcon, ImageOff, Info, Plus, X } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  boardConcepts,
  createAsset,
  getAssets,
  type Asset,
  type Concept,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";

const KIND: Record<"characters" | "locations" | "props", Asset["category"]> = {
  characters: "character",
  locations: "location",
  props: "prop",
};
const DETAIL_PLACEHOLDER = {
  characters: "Role (e.g. the rider)",
  locations: "unused — the vision pass describes the space",
  props: "Category (e.g. helmet)",
};

const handleOf = (name: string) => "@" + name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const slugOf = (url: string) => url.match(/^\/(characters|locations|props)\/([^/]+)\//)?.[2] ?? null;

export default function ElementsPage() {
  const { brand, toast } = useShell();
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [grid, setGrid] = useState(false);
  const [howto, setHowto] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

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

  const all = assets ?? [];
  const collage = all.filter((a) => a.poster).slice(0, 4);

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
                <span key={a.id} style={{ backgroundImage: `url(${API_URL}${a.poster})` }} />
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
              <article key={a.id} className="elcard">
                <div
                  className={`elplate${a.poster ? "" : " blank"}`}
                  style={a.poster ? { backgroundImage: `url(${API_URL}${a.poster})` } : undefined}
                >
                  {!a.poster ? (
                    <span className="m">
                      <ImageOff strokeWidth={1.6} size={13} /> no photos yet
                    </span>
                  ) : null}
                </div>
                <div className="elbody">
                  <div className="elname">
                    <b>{a.name}</b>
                    <span className="elcat">{a.category}</span>
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

function AddElement({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (name: string, photos: number) => void;
}) {
  const [kind, setKind] = useState<"characters" | "locations" | "props">("characters");
  const [detail, setDetail] = useState("");
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const previews = useMemo(() => files.slice(0, 6).map((f) => URL.createObjectURL(f)), [files]);
  const locked = kind === "locations";
  const canSave = name.trim().length > 0 && !busy && (kind !== "locations" || files.length > 0);

  async function save() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      if (!locked && detail.trim()) form.append(kind === "characters" ? "role" : "category", detail.trim());
      if (notes.trim()) form.append("notes", notes.trim());
      files.forEach((f) => form.append("photos", f, f.name));
      const res = await createAsset(kind, form);
      onSaved(name.trim(), res.photos ?? files.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
      setBusy(false);
    }
  }

  return (
    <div className="zmodal" onClick={onClose}>
      <div className="zdialog" role="dialog" aria-label="Add element" onClick={(e) => e.stopPropagation()}>
        <div className="zdhead">
          <h3>Add element</h3>
          <span className="spacer" />
          <button type="button" className="zdx" onClick={onClose} aria-label="Close">
            <X strokeWidth={1.8} />
          </button>
        </div>
        <div className="zdbody">
          <div className="zfield">
            <span className="m">What is it</span>
            <div className="zrow">
              <select
                className="zin"
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value as typeof kind);
                  setDetail("");
                }}
                aria-label="Category"
              >
                <option value="characters">Character</option>
                <option value="locations">Location · photos get described</option>
                <option value="props">Prop</option>
              </select>
              <input
                className="zin grow"
                value={detail}
                disabled={locked}
                onChange={(e) => setDetail(e.target.value)}
                placeholder={DETAIL_PLACEHOLDER[kind]}
                aria-label="Detail"
              />
            </div>
          </div>
          <div className="zfield">
            <span className="m">Name</span>
            <input className="zin" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name…" aria-label="Name" />
          </div>
          <div className="zfield">
            <span className="m">Notes</span>
            <textarea
              className="zin"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Look, wardrobe, quirks — becomes a searchable chunk on the RAG assets shelf"
              aria-label="Notes"
            />
          </div>
          <div className="zfield">
            <span className="m">Photos{locked ? " · required for a location" : ""}</span>
            <label className="zdrop">
              <input
                ref={input}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
              />
              <ImageIcon strokeWidth={1.6} />
              {files.length ? `${files.length} photo${files.length === 1 ? "" : "s"} attached` : "Pick photos, or drop them here"}
            </label>
            {previews.length ? (
              <div className="zpreviews">
                {previews.map((u) => (
                  <span key={u} style={{ backgroundImage: `url(${u})` }} />
                ))}
              </div>
            ) : null}
          </div>
          {error ? <div className="stateline err" style={{ padding: 0 }}>{error}</div> : null}
        </div>
        <div className="zdfoot">
          <span className="m">saves the {KIND[kind]} + teaches the RAG assets shelf</span>
          <span className="spacer" />
          <button type="button" className="zbtn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="zbtn pri" disabled={!canSave} onClick={() => void save()}>
            {busy ? "Saving…" : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}

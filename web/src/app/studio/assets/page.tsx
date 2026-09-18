"use client";

/* Assets — the GENERATED media wall (2026-09-18, Mike's call: Assets are
   the content the studio generated; Elements are the characters, props
   and places a scene is held to -- two things, not four chips on one
   wall). Every render as a date-grouped wall, newest day first, off
   /api/media?kind=all&scope=generated -- one row per clip or still
   carrying its provider, prompt, folder and star. You can view them,
   organize them (Images / Clips / Starred / your own folders, a provider
   filter) and delete them -- a SOFT delete: the render leaves the wall
   and the RAG shelf, the file stays, and a concept whose shot already
   carries the clip keeps it. "Make element" is the bridge to the other
   side: a still becomes a character / prop / place with that frame as
   its first photo (the Higgsfield "Create Element" move). The zoom
   slider is five whole-column stops, so a row never ends on a half tile. */
/* eslint-disable @next/next/no-img-element */
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { Download, Film, Folder, FolderInput, Image as ImageIcon, Search, Sparkles, Star, Trash2, UserRound, X } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  deleteGenerated,
  getMedia,
  organizeGenerated,
  type MediaFilter,
  type MediaItem,
  type MediaWall,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";
import { AddElement } from "@/components/studio/add-element";

type Chip = { id: string; label: string; count: number; filter: MediaFilter; icon?: "folder" | "star" };
const STEPS = [
  { cols: 10, label: "XS" },
  { cols: 7, label: "S" },
  { cols: 5, label: "M" },
  { cols: 3, label: "L" },
  { cols: 1, label: "XL" },
];
const DATE_FMT = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "long", day: "numeric" });
const dateLabel = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return DATE_FMT.format(new Date(y, m - 1, d));
};
const fileOf = (url: string) => decodeURIComponent(url.split("?")[0].split("/").pop() || "");
const EMPTY: MediaWall = { items: [], counts: { all: 0 }, wall: { image: 0, video: 0, starred: 0 }, folders: {}, providers: {} };

export default function AssetsPage() {
  const { toast } = useShell();
  const [chip, setChip] = useState("all");
  const [provider, setProvider] = useState("");
  const [query, setQuery] = useState("");
  const [step, setStep] = useState(2);
  const [wall, setWall] = useState<MediaWall | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<MediaItem | null>(null);
  const [folderDraft, setFolderDraft] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [making, setMaking] = useState<MediaItem | null>(null);
  const track = useRef<HTMLDivElement>(null);

  // the chips are derived from the set totals, so a folder appears the
  // moment a render lands in it and disappears when the last one leaves
  const chips: Chip[] = useMemo(() => {
    const w = wall ?? EMPTY;
    const out: Chip[] = [
      { id: "all", label: "All", count: w.counts.all, filter: {} },
      { id: "image", label: "Images", count: w.wall.image, filter: { kind: "image" } },
      { id: "video", label: "Clips", count: w.wall.video, filter: { kind: "video" } },
      { id: "starred", label: "Starred", count: w.wall.starred, filter: { starred: true }, icon: "star" },
    ];
    for (const [name, count] of Object.entries(w.folders)) {
      out.push({ id: `folder:${name}`, label: name, count, filter: { folder: name }, icon: "folder" });
    }
    return out;
  }, [wall]);
  const active = chips.find((c) => c.id === chip) ?? chips[0];

  const load = (q = query, c = active, p = provider) => {
    getMedia({ ...c.filter, q: q.trim() || undefined, provider: p || undefined })
      .then((r) => {
        setWall(r);
        setError(null);
        // a folder chip whose last render moved out falls back to All
        if (c.filter.folder && !(c.filter.folder in r.folders)) setChip("all");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Media unavailable"));
  };
  useEffect(() => {
    const timer = setTimeout(() => load(query, active, provider), query ? 220 : 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, chip, provider]);
  const show = (m: MediaItem | null) => {
    setOpen(m);
    setFolderDraft(m?.folder ?? "");
    setConfirming(false);
  };

  const items = wall?.items ?? null;
  const groups = useMemo(() => {
    const out: { date: string; items: MediaItem[] }[] = [];
    for (const item of items || []) {
      const last = out[out.length - 1];
      if (last && last.date === item.date) last.items.push(item);
      else out.push({ date: item.date, items: [item] });
    }
    return out;
  }, [items]);

  // one place patches the open item, the wall row and the server
  const patchOpen = (id: number, body: { folder?: string; starred?: boolean }) =>
    organizeGenerated(id, body)
      .then((r) => {
        const apply = (m: MediaItem) => (m.generated_id === id ? { ...m, folder: r.folder, starred: r.starred } : m);
        setOpen((o) => (o ? apply(o) : o));
        setWall((w) => (w ? { ...w, items: w.items.map(apply) } : w));
        load();
        return r;
      })
      .catch((e) => toast(e instanceof Error ? e.message : "Could not save", "err"));

  const remove = (m: MediaItem) => {
    if (!m.generated_id) return;
    deleteGenerated(m.generated_id)
      .then(() => {
        show(null);
        setWall((w) => (w ? { ...w, items: w.items.filter((x) => x.generated_id !== m.generated_id) } : w));
        toast(`${m.provider ?? "render"} removed from the wall · the file stays`);
        load();
      })
      .catch((e) => toast(e instanceof Error ? e.message : "Could not delete", "err"));
  };

  const pickStop = (clientX: number) => {
    const el = track.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const pad = 34;
    const t = Math.min(1, Math.max(0, (clientX - (r.left + pad)) / (r.width - pad * 1.6)));
    setStep(Math.round(t * (STEPS.length - 1)));
  };
  const onSliderDown = (e: React.MouseEvent<HTMLDivElement>) => {
    pickStop(e.clientX);
    const move = (ev: MouseEvent) => pickStop(ev.clientX);
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const shown = items?.length ?? 0;
  const total = wall?.counts.all ?? 0;
  const countLine = items ? `${shown}${shown !== total ? ` of ${total}` : ""} render${total === 1 ? "" : "s"}` : "loading…";
  const providers = Object.entries(wall?.providers ?? {});

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="vhead" style={{ marginTop: 8, flexWrap: "wrap" }}>
        <h2>Assets</h2>
        <label className="asearch">
          <Search size={14} strokeWidth={1.7} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search prompts…" aria-label="Search generated assets" />
        </label>
        <span className="m">{countLine}</span>
        <span className="spacer" />
        {providers.length > 1 ? (
          <select className="zin" value={provider} onChange={(e) => setProvider(e.target.value)} aria-label="Provider" style={{ width: "auto" }}>
            <option value="">Every provider</option>
            {providers.map(([name, n]) => (
              <option key={name} value={name}>
                {name} · {n}
              </option>
            ))}
          </select>
        ) : null}
        <div
          ref={track}
          className="azoom"
          role="slider"
          aria-label="Tile size"
          aria-valuemin={1}
          aria-valuemax={STEPS.length}
          aria-valuenow={step + 1}
          title={`Tile size · ${STEPS[step].label}`}
          onMouseDown={onSliderDown}
        >
          <Search size={13} strokeWidth={1.7} />
          <span className="aztrack">
            <span className="azknob" style={{ left: `${(step / (STEPS.length - 1)) * 100}%` }} />
          </span>
          <span className="m">{STEPS[step].label}</span>
        </div>
      </div>

      <div className="cats">
        {chips.map((c) => (
          <button type="button" key={c.id} className="cat" aria-pressed={chip === c.id} onClick={() => setChip(c.id)}>
            {c.icon === "folder" ? <Folder size={11} strokeWidth={1.7} className="mr-1.5 inline-block align-[-1px]" /> : null}
            {c.icon === "star" ? <Star size={11} strokeWidth={1.7} className="mr-1.5 inline-block align-[-1px]" /> : null}
            {c.label}
            <u>{c.count}</u>
          </button>
        ))}
      </div>

      {error ? <div className="stateline err" style={{ padding: "14px 42px" }}>{error}</div> : null}

      <div className={`wall${open ? " has-detail" : ""}`}>
        {items && !items.length ? (
          <p className="stateline" style={{ padding: "14px 42px" }}>
            {total ? "Nothing matches — clear the search or pick another chip" : "No renders yet — pick a scene to draw its keyframe, or approve one in Queue"}
          </p>
        ) : null}
        {groups.map((g) => (
          <div key={g.date} className="wgroup">
            <div className="wdate">
              <span>{dateLabel(g.date)}</span>
              <span className="m">
                {g.items.length} item{g.items.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="wgrid" style={{ gridTemplateColumns: `repeat(${STEPS[step].cols}, minmax(0, 1fr))` }}>
              <AnimatePresence initial={false}>
                {g.items.map((m) => (
                  <motion.button
                    layout
                    initial={{ opacity: 0, scale: 0.96 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.94 }}
                    transition={{ duration: 0.18, ease: "easeOut" }}
                    type="button"
                    key={m.url}
                    className={`wtile${m.kind === "video" ? " video" : ""}${open?.url === m.url ? " on" : ""}`}
                    aria-label={`${m.provider ?? m.asset_name} · ${m.kind}`}
                    style={m.kind === "image" ? { backgroundImage: `url("${API_URL}${m.url}")` } : undefined}
                    onClick={() => show(m)}
                    onMouseEnter={(e) => e.currentTarget.querySelector("video")?.play().catch(() => {})}
                    onMouseLeave={(e) => {
                      const v = e.currentTarget.querySelector("video");
                      if (v) {
                        v.pause();
                        v.currentTime = 0;
                      }
                    }}
                  >
                    {m.kind === "video" ? <video src={`${API_URL}${m.url}`} muted loop playsInline preload="metadata" /> : null}
                    {m.starred ? <Star size={11} strokeWidth={2} className="absolute top-2 right-2 fill-current text-[var(--signal)]" /> : null}
                    <span className="wname">
                      {m.kind === "video" ? <Film size={11} strokeWidth={1.6} /> : <Sparkles size={11} strokeWidth={1.6} />}
                      <span>
                        {m.provider ?? m.asset_name}
                        {m.folder ? ` · ${m.folder}` : ""}
                      </span>
                    </span>
                  </motion.button>
                ))}
              </AnimatePresence>
            </div>
          </div>
        ))}
      </div>

      <AnimatePresence>
        {open ? (
          <motion.aside
            key="detail"
            className="adetail"
            aria-label="Render detail"
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 40, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
          >
            <div className="adhead">
              <h3>{open.provider ?? open.asset_name}</h3>
              <span className="spacer" />
              <button
                type="button"
                className="zdx"
                onClick={() => open.generated_id && patchOpen(open.generated_id, { starred: !open.starred })}
                aria-label={open.starred ? "Unstar" : "Star"}
                aria-pressed={!!open.starred}
                title={open.starred ? "Unstar" : "Star"}
              >
                <Star strokeWidth={1.8} className={open.starred ? "fill-current text-[var(--signal)]" : ""} />
              </button>
              <button type="button" className="zdx" onClick={() => show(null)} aria-label="Close">
                <X strokeWidth={1.8} />
              </button>
            </div>
            <div className="adbody">
              <div className="adframe">
                {open.kind === "video" ? (
                  <video src={`${API_URL}${open.url}`} controls muted playsInline preload="metadata" />
                ) : (
                  <img src={`${API_URL}${open.url}`} alt="" />
                )}
              </div>
              <dl className="admeta">
                <dt>type</dt>
                <dd>
                  {open.kind === "video" ? <Film size={12} strokeWidth={1.6} /> : <ImageIcon size={12} strokeWidth={1.6} />} {open.kind === "video" ? "clip" : "still"}
                </dd>
                <dt>model</dt>
                <dd className="mono">{open.model ?? "—"}</dd>
                <dt>file</dt>
                <dd className="mono">{fileOf(open.url)}</dd>
                <dt>concept</dt>
                <dd>
                  {open.concept_id ? (
                    <Link href={`/studio/flows?concept=${open.concept_id}&shot=${open.shot_n ?? 1}`} className="underline underline-offset-2" title="Open in Director">
                      #{open.concept_id}
                      {open.shot_n ? ` · shot ${open.shot_n}` : ""}
                    </Link>
                  ) : (
                    "not from a concept"
                  )}
                </dd>
                <dt>folder</dt>
                <dd>
                  <form
                    className="flex min-w-0 flex-1 items-center gap-1.5"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (open.generated_id && folderDraft.trim() !== (open.folder ?? "")) {
                        patchOpen(open.generated_id, { folder: folderDraft.trim() }).then((r) =>
                          r ? toast(r.folder ? `moved to ${r.folder}` : "taken out of its folder") : null,
                        );
                      }
                    }}
                  >
                    <input
                      className="zin min-w-0 flex-1"
                      style={{ width: "auto" }}
                      list="asset-folders"
                      value={folderDraft}
                      onChange={(e) => setFolderDraft(e.target.value)}
                      placeholder="none — type to file it"
                      aria-label="Folder"
                    />
                    <datalist id="asset-folders">
                      {Object.keys(wall?.folders ?? {}).map((f) => (
                        <option key={f} value={f} />
                      ))}
                    </datalist>
                    <button type="submit" className="zdx shrink-0" aria-label="Move to folder" title="Move to folder" disabled={folderDraft.trim() === (open.folder ?? "")}>
                      <FolderInput strokeWidth={1.7} />
                    </button>
                  </form>
                </dd>
                {open.prompt ? (
                  <>
                    <dt>prompt</dt>
                    <dd className="adtext">{open.prompt}</dd>
                  </>
                ) : null}
              </dl>
            </div>
            <div className="adfoot" style={{ flexWrap: "wrap" }}>
              {open.kind === "image" ? (
                <>
                  <Link href={`/studio?attach=${encodeURIComponent(open.asset_id)}`} className="btn pri">
                    Use in a shot
                  </Link>
                  <button type="button" className="btn" onClick={() => setMaking(open)} title="Save this still as a character, prop or place">
                    <UserRound strokeWidth={1.6} /> Make element
                  </button>
                </>
              ) : null}
              <a className="btn" href={`${API_URL}${open.url.split("?")[0]}`} target="_blank" rel="noreferrer" title="Open the file" aria-label="Open the file">
                <Download strokeWidth={1.6} />
              </a>
              {confirming ? (
                <button type="button" className="btn pri" onClick={() => remove(open)} style={{ flex: "1 1 100%" }}>
                  <Trash2 strokeWidth={1.6} /> Remove from the wall — the file stays
                </button>
              ) : (
                <button type="button" className="btn" onClick={() => setConfirming(true)} title="Delete" aria-label="Delete">
                  <Trash2 strokeWidth={1.6} />
                </button>
              )}
            </div>
          </motion.aside>
        ) : null}
      </AnimatePresence>

      {making ? (
        <AddElement
          title="Make element"
          initialPhotoUrls={[making.url]}
          initialNotes={making.prompt ?? ""}
          onClose={() => setMaking(null)}
          onSaved={(name, photos, note, sheetJob) => {
            setMaking(null);
            toast(
              `${name} saved as an element · ${photos} photo${photos === 1 ? "" : "s"}${sheetJob ? " · drawing its sheet" : ""}${note ? ` · ${note}` : ""}`,
            );
          }}
        />
      ) : null}
    </section>
  );
}

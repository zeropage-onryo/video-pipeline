"use client";

/* Assets — the media wall (2026-09-12, the "ZPF Assets" design): every
   saved photo and clip as a date-grouped wall, newest day first, off
   /api/media?kind=all — one row per file carrying its owning asset.
   Category chips and search re-query the API; counts are set totals,
   never page length. The magnifier is five whole-column stops, so a row
   never ends on a half tile. Clicking a tile opens its owning asset in
   the detail rail; "Use in a shot" carries it to the Studio composer. */
/* eslint-disable @next/next/no-img-element */
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Download, Film, Image as ImageIcon, MapPin, Plus, Search, Sparkles, UserRound, Box, X } from "lucide-react";
import { API_URL } from "@/lib/api";
import {
  boardConcepts,
  getAssets,
  getMedia,
  type Asset,
  type Concept,
  type MediaCounts,
  type MediaItem,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";
import { AddElement } from "@/components/studio/add-element";

const CATS: [string, string][] = [
  ["all", "All"],
  ["location", "Locations"],
  ["character", "Characters"],
  ["prop", "Props"],
  ["generated", "Generated"],
];
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
const slugOf = (url: string) => url.match(/^\/(characters|locations|props)\/([^/]+)\//)?.[2] ?? null;
const fileOf = (url: string) => decodeURIComponent(url.split("?")[0].split("/").pop() || "");

function CatIcon({ category, size = 12 }: { category: string; size?: number }) {
  if (category === "location") return <MapPin size={size} strokeWidth={1.6} />;
  if (category === "character") return <UserRound size={size} strokeWidth={1.6} />;
  if (category === "prop") return <Box size={size} strokeWidth={1.6} />;
  if (category === "generated") return <Sparkles size={size} strokeWidth={1.6} />;
  return <ImageIcon size={size} strokeWidth={1.6} />;
}

export default function AssetsPage() {
  const { toast } = useShell();
  const [cat, setCat] = useState("all");
  const [query, setQuery] = useState("");
  const [step, setStep] = useState(2);
  const [items, setItems] = useState<MediaItem[] | null>(null);
  const [counts, setCounts] = useState<MediaCounts>({ all: 0 });
  const [assets, setAssets] = useState<Asset[]>([]);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ asset: Asset; item: MediaItem } | null>(null);
  const [adding, setAdding] = useState(false);
  const track = useRef<HTMLDivElement>(null);

  const load = (q = query, c = cat) => {
    getMedia(q.trim() || undefined, c)
      .then((r) => {
        setItems(r.items);
        setCounts(r.counts);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Media unavailable"));
  };
  useEffect(() => {
    getAssets()
      .then((r) => setAssets(r.items))
      .catch(() => setAssets([]));
    boardConcepts(undefined, true)
      .then((r) => setConcepts(r.items))
      .catch(() => setConcepts([]));
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => load(query, cat), query ? 220 : 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, cat]);

  const groups = useMemo(() => {
    const out: { date: string; items: MediaItem[] }[] = [];
    for (const item of items || []) {
      const last = out[out.length - 1];
      if (last && last.date === item.date) last.items.push(item);
      else out.push({ date: item.date, items: [item] });
    }
    return out;
  }, [items]);

  // how many concepts an asset has grounded: refs carry the asset's slug
  const usedIn = (asset: Asset) => {
    const slug = asset.photos[0] ? slugOf(asset.photos[0]) : null;
    if (!slug) return 0;
    return concepts.filter((c) => (c.refs || []).some((u) => slugOf(u) === slug)).length;
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
  const countLine = items
    ? `${shown}${shown !== counts.all ? ` of ${counts.all}` : ""} media item${counts.all === 1 ? "" : "s"}`
    : "loading…";

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="vhead" style={{ marginTop: 8, flexWrap: "wrap" }}>
        <h2>Assets</h2>
        <label className="asearch">
          <Search size={14} strokeWidth={1.7} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search names and descriptions…" aria-label="Search assets" />
        </label>
        <span className="m">{countLine}</span>
        <span className="spacer" />
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
        <button type="button" className="go" onClick={() => setAdding(true)}>
          <Plus strokeWidth={2.2} /> Add asset
        </button>
      </div>

      <div className="cats">
        {CATS.map(([id, label]) => (
          <button type="button" key={id} className="cat" aria-pressed={cat === id} onClick={() => setCat(id)}>
            {label}
            <u>{counts[id] ?? 0}</u>
          </button>
        ))}
      </div>

      {error ? <div className="stateline err" style={{ padding: "14px 42px" }}>{error}</div> : null}

      <div className={`wall${open ? " has-detail" : ""}`}>
        {items && !items.length ? (
          <p className="stateline" style={{ padding: "14px 42px" }}>
            {counts.all ? "Nothing matches — clear the search or switch category" : "No media yet — add an asset or generate your first image or clip"}
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
              {g.items.map((m) => (
                <button
                  type="button"
                  key={m.url}
                  className={`wtile${m.kind === "video" ? " video" : ""}`}
                  aria-label={`${m.asset_name} · ${m.category}`}
                  style={m.kind === "image" ? { backgroundImage: `url("${API_URL}${m.url}")` } : undefined}
                  onClick={() => {
                    const asset = assets.find((a) => a.id === m.asset_id) || {
                      id: m.asset_id,
                      category: m.category === "generated" ? "prop" : m.category,
                      name: m.asset_name,
                      photos: [m.url],
                      poster: m.kind === "image" ? m.url : null,
                      text: "",
                      meta: {},
                    };
                    setOpen({ asset, item: m });
                  }}
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
                  <span className="wname">
                    {m.kind === "video" ? <Film size={11} strokeWidth={1.6} /> : <CatIcon category={m.category} size={11} />}
                    <span>
                      {m.asset_name} · {m.category}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {open ? (
        <aside className="adetail" aria-label="Asset detail">
          <div className="adhead">
            <h3>{open.asset.name}</h3>
            <span className="spacer" />
            <button type="button" className="zdx" onClick={() => setOpen(null)} aria-label="Close">
              <X strokeWidth={1.8} />
            </button>
          </div>
          <div className="adbody">
            <div className="adframe">
              {open.item.kind === "video" ? (
                <video src={`${API_URL}${open.item.url}`} controls muted playsInline preload="metadata" />
              ) : (
                <img src={`${API_URL}${open.item.url}`} alt="" />
              )}
            </div>
            {open.asset.photos.length > 1 ? (
              <div className="adstrip">
                {open.asset.photos.map((u) => (
                  <button
                    type="button"
                    key={u}
                    className={u === open.item.url ? "on" : ""}
                    style={{ backgroundImage: `url("${API_URL}${u}")` }}
                    aria-label={fileOf(u)}
                    onClick={() => setOpen({ asset: open.asset, item: { ...open.item, url: u, kind: "image" } })}
                  />
                ))}
              </div>
            ) : null}
            <dl className="admeta">
              <dt>category</dt>
              <dd>
                <CatIcon category={open.item.category} /> {open.item.category}
              </dd>
              <dt>file</dt>
              <dd className="mono">{fileOf(open.item.url)}</dd>
              <dt>used in</dt>
              <dd>{usedIn(open.asset) ? `${usedIn(open.asset)} concept${usedIn(open.asset) === 1 ? "" : "s"}` : "not used yet"}</dd>
              {open.asset.text ? (
                <>
                  <dt>notes</dt>
                  <dd className="adtext">{open.asset.text}</dd>
                </>
              ) : null}
            </dl>
          </div>
          <div className="adfoot">
            <Link href={`/studio?attach=${encodeURIComponent(open.asset.id)}`} className="btn pri">
              Use in a shot
            </Link>
            <a className="btn" href={`${API_URL}${open.item.url.split("?")[0]}`} target="_blank" rel="noreferrer" title="Open the file" aria-label="Open the file">
              <Download strokeWidth={1.6} />
            </a>
          </div>
        </aside>
      ) : null}

      {adding ? (
        <AddElement
          title="Add asset"
          onClose={() => setAdding(false)}
          onSaved={(name, photos, note) => {
            setAdding(false);
            toast(`${name} saved · ${photos} photo${photos === 1 ? "" : "s"}${note ? ` · ${note}` : ""}`);
            getAssets()
              .then((r) => setAssets(r.items))
              .catch(() => {});
            setTimeout(() => load(), 1200);
          }}
        />
      ) : null}
    </section>
  );
}

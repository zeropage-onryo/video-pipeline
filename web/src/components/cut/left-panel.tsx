"use client";

/* The left panel: invideo's placement, the agent beside "Open Media".
   Five tabs -- Agent, Media, Text, Audio, Search -- and the tool strip's
   buttons open the same tabs, so there is one media bin, not two.

   AGENT is its own module (agent-panel.tsx): a composer with invideo's two
   modes -- Agent (a model proposing edits as Keep / Undo cards) and Editor
   (a command palette over the manual tools). */
import { useRef, useState } from "react";
import {
  AudioLines,
  Bot,
  Captions,
  Film,
  ImageIcon,
  Loader2,
  Music,
  Plus,
  Search,
  Upload,
} from "lucide-react";
import { useCut, useDrawnDoc } from "@/lib/cut/store";
import { placeMedia } from "@/lib/cut/actions";
import { searchFootage, uploadMedia, type BinItem, type SearchHit } from "@/lib/cut/api";
import { clipAt, timecode, type Doc, type Track } from "@/lib/cut/timeline";
import { MEDIA_MIME } from "@/components/cut/timeline";
import { CaptionStyle } from "@/components/cut/inspector";
import { AgentPanel, suggest } from "@/components/cut/agent-panel";

const TABS = [
  { id: "agent", label: "Agent", icon: Bot },
  { id: "media", label: "Media", icon: Film },
  { id: "text", label: "Text", icon: Captions },
  { id: "audio", label: "Audio", icon: Music },
  { id: "search", label: "Search", icon: Search },
] as const;

export function LeftPanel() {
  const tab = useCut((s) => s.leftTab);
  const setTab = useCut((s) => s.setLeftTab);
  return (
    <div className="cx-pane">
      <div className="cx-pane-head" role="tablist">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" role="tab" title={label} className="cx-tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            <Icon /> <span className="cx-tab-l">{label}</span>
          </button>
        ))}
      </div>
      {tab === "agent" ? <AgentPanel /> : null}
      {tab === "media" ? <MediaTab /> : null}
      {tab === "text" ? <TextTab /> : null}
      {tab === "audio" ? <AudioTab /> : null}
      {tab === "search" ? <SearchTab /> : null}
    </div>
  );
}

/* ── Media: the bin (T5), uploads, drag onto the timeline (T12) ── */
type BinFilter = "all" | "video" | "image" | "audio" | "upload";

export function useUpload() {
  const addToBin = useCut((s) => s.addToBin);
  const toast = useCut((s) => s.toast);
  const [busy, setBusy] = useState(0);
  const upload = async (files: FileList | File[]) => {
    const list = [...files];
    setBusy((n) => n + list.length);
    const made: BinItem[] = [];
    for (const f of list) {
      try {
        const res = await uploadMedia(f);
        const item: BinItem = res.item ?? {
          handle: res.handle,
          kind: (res.kind as BinItem["kind"]) ?? "audio",
          name: res.filename,
          seconds: res.seconds,
          width: null,
          height: null,
          has_video: res.kind !== "audio",
          has_audio: res.kind !== "image",
          size_bytes: f.size,
          url: null,
          poster: null,
          created_at: null,
          source: "upload",
        };
        addToBin(item);
        made.push(item);
      } catch (e) {
        toast(`${f.name}: ${e instanceof Error ? e.message : "upload failed"}`, "err");
      } finally {
        setBusy((n) => n - 1);
      }
    }
    if (made.length) toast(`${made.length} file${made.length > 1 ? "s" : ""} in the bin`);
    return made;
  };
  return { upload, busy };
}

function DropZone({ accept, label }: { accept: string; label: string }) {
  const { upload, busy } = useUpload();
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        type="button"
        className={`cx-drop${over ? " over" : ""}`}
        style={{ width: "100%" }}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (e.dataTransfer.files.length) void upload(e.dataTransfer.files);
        }}
      >
        {busy ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
        {busy ? `Uploading ${busy}…` : label}
      </button>
      <input
        ref={input}
        type="file"
        accept={accept}
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files?.length) void upload(e.target.files);
          e.target.value = "";
        }}
      />
    </>
  );
}

function BinTile({ item }: { item: BinItem }) {
  const fps = useCut((s) => s.doc?.fps ?? 30);
  const Icon = item.kind === "audio" ? AudioLines : item.kind === "image" ? ImageIcon : Film;
  return (
    <button
      type="button"
      className="cx-bin-item"
      draggable
      title={`${item.name} — drag onto a track, or double-click to append`}
      onDragStart={(e) => {
        e.dataTransfer.setData(MEDIA_MIME, JSON.stringify(item));
        e.dataTransfer.effectAllowed = "copy";
      }}
      onDoubleClick={() => void placeMedia(item)}
    >
      <span className="cx-bin-thumb" style={item.poster ? { backgroundImage: `url(${item.poster})` } : undefined}>
        {item.poster ? null : <Icon />}
        <span className="cx-bin-kind">{item.source === "upload" ? `${item.kind} · up` : item.kind}</span>
        {item.seconds ? (
          <span className="cx-bin-dur">{timecode(Math.round(item.seconds * fps), fps).replace(/:\d\d$/, "")}</span>
        ) : null}
      </span>
      <span className="cx-bin-name">{item.name}</span>
    </button>
  );
}

function MediaTab() {
  const bin = useCut((s) => s.bin);
  const loading = useCut((s) => s.binLoading);
  const [filter, setFilter] = useState<BinFilter>("all");
  const shown = bin.filter((b) =>
    filter === "all" ? true : filter === "upload" ? b.source === "upload" : b.kind === filter,
  );
  const count = (f: BinFilter) =>
    bin.filter((b) => (f === "all" ? true : f === "upload" ? b.source === "upload" : b.kind === f)).length;
  return (
    <div className="cx-pane-body">
      <DropZone accept="video/*,image/*,audio/*" label="Open media — drop files or browse" />
      <div className="cx-filter">
        {(["all", "video", "image", "audio", "upload"] as BinFilter[]).map((f) => (
          <button key={f} type="button" className="cx-btn ghost" aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {f === "all" ? "All" : f === "video" ? "Clips" : f === "image" ? "Stills" : f === "audio" ? "Sound" : "Uploads"}
            <span className="cx-label" style={{ letterSpacing: 0 }}>
              {count(f)}
            </span>
          </button>
        ))}
      </div>
      {loading && !bin.length ? (
        <p className="cx-note">Reading the bin…</p>
      ) : shown.length ? (
        <div className="cx-bin">
          {shown.map((b) => (
            <BinTile key={b.handle} item={b} />
          ))}
        </div>
      ) : (
        <p className="cx-note">
          {bin.length
            ? "Nothing of that kind in the bin."
            : "Your renders from Assets land here, beside anything you upload. Render a scene in the Queue, or drop a file above."}
        </p>
      )}
    </div>
  );
}

/* ── Text (T17) ── */
function TextTab() {
  const doc = useDrawnDoc();
  const op = useCut((s) => s.op);
  const playhead = useCut((s) => s.playhead);
  const select = useCut((s) => s.select);
  const seek = useCut((s) => s.seek);
  const [draft, setDraft] = useState("");
  if (!doc) return null;
  const tracks = doc.tracks.filter((t) => t.kind === "caption");

  const addCue = async () => {
    const text = draft.trim() || "Caption";
    const two = doc.fps * 2;
    const target = tracks[0];
    if (!target) {
      const ok = await op("add_caption_track", { cues: [{ start: playhead, end: playhead + two, text }] });
      if (ok) setDraft("");
      return;
    }
    const inside = (target.cues ?? []).find((q) => q.start <= playhead && playhead < q.end);
    if (inside) {
      select([inside.id], "cue");
      useCut.getState().toast("A caption is already under the playhead — selected it", "err");
      return;
    }
    const next = (target.cues ?? []).filter((q) => q.start > playhead).sort((a, b) => a.start - b.start)[0];
    const end = Math.min(playhead + two, next ? next.start : Infinity);
    const ok = await op("set_cue", { track_id: target.id, start: playhead, end, text });
    if (ok) setDraft("");
  };

  return (
    <div className="cx-pane-body">
      <div className="cx-card">
        <h4 className="cx-h">Add a caption</h4>
        <textarea
          className="cx-textarea"
          style={{ width: "100%" }}
          placeholder="What it says"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void addCue();
          }}
        />
        <div className="cx-composer-row">
          <button type="button" className="cx-go" onClick={() => void addCue()}>
            <Plus /> At {timecode(playhead, doc.fps)}
          </button>
          <span className="cx-label">⌘⏎</span>
        </div>
      </div>

      {tracks.map((t) => (
        <div key={t.id} className="cx-card">
          <CaptionStyle track={t} />
          <div className="cx-thread" style={{ gap: 4 }}>
            {(t.cues ?? []).map((q) => (
              <button
                key={q.id}
                type="button"
                className="cx-btn ghost"
                style={{ justifyContent: "flex-start", height: "auto", padding: "6px 8px", textAlign: "left" }}
                onClick={() => {
                  seek(q.start);
                  select([q.id], "cue");
                }}
              >
                <span className="cx-mono" style={{ fontSize: 10, color: "var(--dimmer)", flex: "none" }}>
                  {timecode(q.start, doc.fps)}
                </span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{q.text}</span>
              </button>
            ))}
            {!(t.cues ?? []).length ? <p className="cx-note">No cues on {t.id} yet.</p> : null}
          </div>
        </div>
      ))}

      <div className="cx-card">
        <h4 className="cx-h">Captions from speech</h4>
        <p className="cx-note" style={{ marginBottom: 10 }}>
          Cues built from the words spoken in the sound on your timeline. They arrive as a proposal you play and keep —
          clips have to be indexed first (≈ a cent a clip, offered when needed).
        </p>
        <button type="button" className="cx-btn ghost" onClick={() => void suggest("captions")}>
          <Captions /> Make captions from speech
        </button>
      </div>
    </div>
  );
}

/* ── Audio (T18) ── */
function AudioTab() {
  const doc = useDrawnDoc();
  const bin = useCut((s) => s.bin);
  if (!doc) return null;
  const audio = doc.tracks.filter((t) => t.kind === "audio");
  const sounds = bin.filter((b) => b.kind === "audio");
  return (
    <div className="cx-pane-body">
      <DropZone accept="audio/*" label="Upload music or a voiceover" />
      {sounds.length ? (
        <div className="cx-bin" style={{ marginBottom: 14 }}>
          {sounds.map((b) => (
            <BinTile key={b.handle} item={b} />
          ))}
        </div>
      ) : null}
      {audio.map((t) => (
        <AudioTrackCard key={t.id} track={t} doc={doc} />
      ))}
      <div className="cx-card">
        <h4 className="cx-h">Loudness</h4>
        <p className="cx-note">
          Export normalises the mix to −14 LUFS, the level Instagram, TikTok and YouTube play at — so set levels by ear
          relative to each other, not to the meter. Mute and solo here are for listening only; they are not edits.
        </p>
      </div>
    </div>
  );
}

function AudioTrackCard({ track, doc }: { track: Track; doc: Doc }) {
  const m = useCut((s) => s.mix[track.id]);
  const setMix = useCut((s) => s.setMix);
  const op = useCut((s) => s.op);
  const playhead = useCut((s) => s.playhead);
  const here = clipAt(track, playhead);
  return (
    <div className="cx-card">
      <div className="cx-field-row" style={{ marginBottom: 8 }}>
        <span className="cx-h" style={{ flex: 1 }}>
          {track.id} · {track.role}
        </span>
        <button type="button" className="cx-ms" data-k="m" aria-pressed={!!m?.mute} onClick={() => setMix(track.id, { mute: !m?.mute })}>
          M
        </button>
        <button type="button" className="cx-ms" data-k="s" aria-pressed={!!m?.solo} onClick={() => setMix(track.id, { solo: !m?.solo })}>
          S
        </button>
      </div>
      <p className="cx-note">
        {(track.clips ?? []).length} clip{(track.clips ?? []).length === 1 ? "" : "s"}
        {here ? ` · at the playhead: ${here.gain_db ?? 0} dB` : ""}
      </p>
      {track.role === "music" ? (
        <div className="cx-field" style={{ marginTop: 8, marginBottom: 0 }}>
          <span className="cx-label">Duck under</span>
          <span className="cx-seg">
            <button type="button" aria-pressed={!track.duck_under} onClick={() => op("duck", { track_id: track.id, under: null })}>
              Off
            </button>
            {(["voice", "sfx"] as const)
              .filter((r) => doc.tracks.some((x) => x.kind === "audio" && x.role === r))
              .map((r) => (
                <button key={r} type="button" aria-pressed={track.duck_under === r} onClick={() => op("duck", { track_id: track.id, under: r })}>
                  {r}
                </button>
              ))}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/* ── Search: the footage index (phase 2) ── */
function SearchTab() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const bin = useCut((s) => s.bin);
  const fps = useCut((s) => s.doc?.fps ?? 30);
  const toast = useCut((s) => s.toast);
  const go = async () => {
    if (!q.trim()) return;
    setBusy(true);
    try {
      const res = await searchFootage(q.trim());
      setHits(res.results);
      setNotes(res.notes ?? []);
    } catch (e) {
      toast(e instanceof Error ? e.message : "search failed", "err");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="cx-pane-body">
      <div className="cx-field-row" style={{ marginBottom: 12 }}>
        <input
          className="cx-input"
          placeholder="the shot where the door opens…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setHits(null);
          }}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter") void go();
          }}
        />
        <button type="button" className="cx-btn ghost" onClick={() => void go()} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <Search />}
        </button>
      </div>
      {notes.map((n) => (
        <p key={n} className="cx-note">
          {n}
        </p>
      ))}
      {hits && !hits.length ? <p className="cx-note">Nothing matched. Only indexed clips can be searched.</p> : null}
      <div className="cx-thread">
        {(hits ?? []).map((h, i) => {
          const item = bin.find((b) => b.handle === h.media);
          return (
            <div key={`${h.media}-${h.start_f}-${i}`} className="cx-card" style={{ marginBottom: 0 }}>
              <p className="cx-label" style={{ marginBottom: 4 }}>
                {h.concept_title ?? item?.name ?? h.media} · {timecode(h.start_f, fps)}–{timecode(h.end_f, fps)}
              </p>
              <p className="cx-note" style={{ color: "var(--text)" }}>
                {h.text || "—"}
              </p>
              {item ? (
                <button
                  type="button"
                  className="cx-btn ghost"
                  style={{ marginTop: 6 }}
                  onClick={() => void placeMedia(item, undefined, undefined, { src_in: h.start_f, src_out: h.end_f })}
                >
                  <Plus /> Append this moment
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

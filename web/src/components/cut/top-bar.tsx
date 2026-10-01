"use client";

/* The editor's top bar: back to the projects, the name (click to rename),
   undo / redo, the canvas, the save state, History, Export.

   "Saved" is literal: there is no draft. Every edit IS a version on the
   server the moment it is accepted, so the dot is green unless an op is
   in flight (amber) -- which is also why there is no Save button.

   HISTORY (T13) lists the version chain: who made each (you, the agent,
   Assemble), what it did, when. Restore moves the head there; nothing is
   deleted, so restoring is itself undoable.

   EXPORT (T24) renders a version -- the head by default, or any version
   from the list -- at a chosen aspect, as a job, and lists the exports
   that already exist per version. It spends nothing: ffmpeg on the API box. */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Dialog } from "@base-ui/react/dialog";
import { Popover } from "@base-ui/react/popover";
import { ChevronLeft, Copy, Download, History, Loader2, Redo2, Undo2, X } from "lucide-react";
import { useCut } from "@/lib/cut/store";
import { exportProject, listExports, renameProject, type ExportFormat } from "@/lib/cut/api";
import { getJob, type Job } from "@/lib/studio-api";
import { ASPECTS, aspectOf, timecode, type Aspect } from "@/lib/cut/timeline";

function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso.includes("T") || iso.endsWith("Z") ? iso : iso.replace(" ", "T") + "Z");
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function TopBar() {
  const project = useCut((s) => s.project);
  const head = useCut((s) => s.head);
  const doc = useCut((s) => s.doc);
  const busy = useCut((s) => s.busy);
  const canUndo = useCut((s) => s.canUndo);
  const canRedo = useCut((s) => s.canRedo);
  const undo = useCut((s) => s.undo);
  const redo = useCut((s) => s.redo);
  const op = useCut((s) => s.op);
  const toast = useCut((s) => s.toast);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [exportOpen, setExportOpen] = useState(false);

  useEffect(() => {
    const open = () => setExportOpen(true);
    window.addEventListener("zpf:cut-export", open);
    return () => window.removeEventListener("zpf:cut-export", open);
  }, []);

  const commitTitle = async () => {
    setEditing(false);
    const t = title.trim();
    if (!project || !t || t === project.title) return;
    try {
      const res = await renameProject(project.id, t);
      useCut.setState({ project: { ...project, ...res.project } });
    } catch (e) {
      toast(e instanceof Error ? e.message : "could not rename", "err");
    }
  };

  const aspect = doc ? aspectOf(doc.size) : null;

  return (
    <header className="cx-top">
      <Link href="/studio/cut" className="cx-back" title="All projects">
        <ChevronLeft /> Projects
      </Link>
      <span className="cx-sep" />
      {editing ? (
        <input
          className="cx-title"
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={commitTitle}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") setEditing(false);
          }}
        />
      ) : (
        <button
          type="button"
          className="cx-title"
          title="Rename"
          onClick={() => {
            setTitle(project?.title ?? "");
            setEditing(true);
          }}
        >
          {project?.title ?? "…"}
        </button>
      )}
      <span className="cx-sep" />
      <button type="button" className="cx-btn" title="Undo (⌘Z)" disabled={!canUndo} onClick={() => void undo()}>
        <Undo2 />
      </button>
      <button type="button" className="cx-btn" title="Redo (⌘⇧Z)" disabled={!canRedo} onClick={() => void redo()}>
        <Redo2 />
      </button>
      <span className="cx-sep" />
      <select
        className="cx-select"
        value={aspect ?? ""}
        title="Canvas — changing it is an edit, and undoable"
        onChange={(e) => {
          const a = e.target.value as Aspect;
          const [width, height] = ASPECTS[a];
          void op("set_canvas", { width, height });
        }}
      >
        {aspect ? null : <option value="">{doc ? `${doc.size[0]}×${doc.size[1]}` : "—"}</option>}
        {(Object.keys(ASPECTS) as Aspect[]).map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>
      <span className="spacer" />
      <span className={`cx-saved${busy ? " busy" : ""}`} title="Every edit is saved as a version the moment it lands">
        <i />
        {busy ? "Saving…" : head ? `Saved · v${head.version}` : "—"}
      </span>
      <HistoryPopover />
      <button type="button" className="cx-go" onClick={() => setExportOpen(true)} disabled={!doc || !doc.duration}>
        <Download /> Export
      </button>
      {exportOpen ? <ExportDialog onClose={() => setExportOpen(false)} /> : null}
    </header>
  );
}

function HistoryPopover() {
  const versions = useCut((s) => s.versions);
  const head = useCut((s) => s.head);
  const restore = useCut((s) => s.restore);
  const [open, setOpen] = useState(false);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger className="cx-btn ghost" title="Every version of this cut">
        <History /> History
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="bottom" align="end" sideOffset={8} className="z-[800]">
          <Popover.Popup className="cx-pop cx-portal">
            <p className="cx-label" style={{ padding: "6px 8px 8px" }}>
              {versions.length} version{versions.length === 1 ? "" : "s"} · nothing is ever deleted
            </p>
            {versions.map((v) => (
              <div key={v.id} className="cx-ver" aria-current={v.id === head?.id}>
                <span className="n">v{v.version}</span>
                <span style={{ minWidth: 0 }}>
                  <span className="s" style={{ display: "block" }}>
                    {v.op_summary}
                  </span>
                  <span className="w" data-author={v.author}>
                    {v.author} · {ago(v.created_at)}
                    {v.export_url ? " · exported" : ""}
                  </span>
                </span>
                {v.id === head?.id ? (
                  <span className="cx-label" style={{ color: "var(--signal)" }}>
                    head
                  </span>
                ) : (
                  <button
                    type="button"
                    className="cx-btn ghost"
                    onClick={() => {
                      setOpen(false);
                      void restore(v.id);
                    }}
                  >
                    Restore
                  </button>
                )}
              </div>
            ))}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

type ExportRow = { timeline_id: number; version: number; export_url: string | null; created_at: string; op_summary: string };

const FORMATS: { id: ExportFormat; label: string; verb: string; note: (at: string) => string }[] = [
  { id: "mp4", label: "Video", verb: "Render MP4", note: () => "H.264 MP4 with its sound, the render of record." },
  { id: "audio", label: "Audio only", verb: "Render audio", note: () => "The mix alone as AAC (.m4a), at −14 LUFS." },
  { id: "still", label: "Still", verb: "Render still", note: (at) => `The frame at the playhead (${at}) as a PNG, captions and all.` },
  {
    id: "project",
    label: "Editable project",
    verb: "Write project",
    note: () => "OpenTimelineIO (.otio) for Resolve or another editor, plus captions as .srt. Nothing is rendered.",
  },
];

function ExportDialog({ onClose }: { onClose: () => void }) {
  const project = useCut((s) => s.project);
  const head = useCut((s) => s.head);
  const doc = useCut((s) => s.doc);
  const versions = useCut((s) => s.versions);
  const toast = useCut((s) => s.toast);
  const refresh = useCut((s) => s.refresh);
  const [aspect, setAspect] = useState<Aspect>((doc && aspectOf(doc.size)) || "9:16");
  const [versionId, setVersionId] = useState<number | null>(head?.id ?? null);
  const [format, setFormat] = useState<ExportFormat>("mp4");
  const playhead = useCut((s) => s.playhead);
  const [job, setJob] = useState<Job | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [done, setDone] = useState<Job | null>(null);
  const [past, setPast] = useState<ExportRow[]>([]);

  const loadPast = useCallback(() => {
    if (!project) return;
    listExports(project.id)
      .then((r) => setPast(r.exports))
      .catch(() => setPast([]));
  }, [project]);
  useEffect(() => {
    loadPast();
  }, [loadPast]);

  const running = job !== null && !["done", "failed", "cancelled"].includes(job.status);

  const start = async () => {
    if (!project) return;
    setResult(null);
    setDone(null);
    try {
      const res = await exportProject(project.id, {
        timeline_id: versionId ?? undefined,
        aspect,
        format,
        frame: format === "still" ? playhead : undefined,
      });
      let j: Job = { id: res.job_id, kind: "cut", label: "export", status: "queued", progress: 0, detail: "" };
      setJob(j);
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500));
        j = await getJob(res.job_id);
        setJob(j);
        if (["done", "failed", "cancelled"].includes(j.status)) break;
      }
      if (j.status === "done") {
        setDone(j);
        setResult(j.mp4_url ?? null);
        loadPast();
        // an aspect change is a new version: pick it up
        void refresh();
      } else {
        toast(j.error || j.detail || "the export failed", "err");
      }
    } catch (e) {
      setJob(null);
      toast(e instanceof Error ? e.message : "could not start the export", "err");
    }
  };

  return (
    <Dialog.Root open onOpenChange={(o) => !o && !running && onClose()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="cx-backdrop" />
        <Dialog.Popup className="cx-dialog cx-portal">
          <div style={{ display: "flex", alignItems: "center", marginBottom: 14 }}>
            <Dialog.Title render={<h3 />}>Export</Dialog.Title>
            <span className="spacer" />
            <Dialog.Close className="cx-btn" disabled={running} aria-label="Close">
              <X />
            </Dialog.Close>
          </div>
          <p className="cx-note" style={{ marginBottom: 16 }}>
            Made by ffmpeg from the exact version you pick — sound loudness-normalised to −14 LUFS, captions burned in where
            the server&apos;s ffmpeg can (the render says so when it cannot). This is the render of record; the preview only
            approximates it. It costs no credits.
          </p>

          <div className="cx-field">
            <span className="cx-label">Make</span>
            <span className="cx-seg" role="group" aria-label="Export format">
              {FORMATS.map((f) => (
                <button key={f.id} type="button" aria-pressed={format === f.id} onClick={() => setFormat(f.id)} disabled={running}>
                  {f.label}
                </button>
              ))}
            </span>
            <p className="cx-note">{FORMATS.find((f) => f.id === format)?.note(timecode(playhead, doc?.fps ?? 30))}</p>
          </div>

          <div className="cx-field">
            <span className="cx-label">Aspect</span>
            <span className="cx-seg">
              {(Object.keys(ASPECTS) as Aspect[]).map((a) => (
                <button key={a} type="button" aria-pressed={aspect === a} onClick={() => setAspect(a)} disabled={running}>
                  {a}
                </button>
              ))}
            </span>
            {doc && aspectOf(doc.size) !== aspect ? (
              <p className="cx-note">A different canvas is saved as a new version first, so the export matches a version you can open.</p>
            ) : null}
          </div>

          <label className="cx-field">
            <span className="cx-label">Version</span>
            <select
              className="cx-select"
              value={versionId ?? ""}
              disabled={running}
              onChange={(e) => setVersionId(Number(e.target.value))}
            >
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version} — {v.op_summary}
                  {v.id === head?.id ? " (current)" : ""}
                </option>
              ))}
            </select>
          </label>

          {job ? (
            <div className="cx-field">
              <span className="cx-label">
                {job.status === "done" ? "Done" : job.status === "failed" ? "Failed" : job.detail || "Rendering…"}
              </span>
              <span className="cx-progress">
                <i style={{ width: `${Math.round((job.status === "done" ? 1 : job.progress || 0.04) * 100)}%` }} />
              </span>
            </div>
          ) : null}

          {job?.status === "done" && job.detail ? (
            // the render's own notes: what it did and anything it could not
            <p className="cx-note" style={{ marginBottom: 10 }}>
              {job.detail}
            </p>
          ) : null}
          {result ? (
            <div className="cx-card">
              <video src={result} controls playsInline style={{ width: "100%", maxHeight: 320, background: "#000", borderRadius: 8 }} />
              <div className="cx-field-row" style={{ marginTop: 10 }}>
                <a className="cx-go" href={result} download target="_blank" rel="noreferrer">
                  <Download /> Download
                </a>
                <button
                  type="button"
                  className="cx-btn ghost"
                  onClick={() =>
                    navigator.clipboard
                      .writeText(result)
                      .then(() => toast("Link copied"))
                      .catch(() => toast("Could not copy", "err"))
                  }
                >
                  <Copy /> Copy link
                </button>
              </div>
            </div>
          ) : null}

          {done && done.format === "audio" && done.file_url ? (
            <div className="cx-card">
              <audio src={done.file_url} controls style={{ width: "100%" }} />
              <a className="cx-go" href={done.file_url} download target="_blank" rel="noreferrer" style={{ marginTop: 10 }}>
                <Download /> Download .m4a
              </a>
            </div>
          ) : null}
          {done && done.format === "still" && done.file_url ? (
            <div className="cx-card">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={done.file_url} alt="The exported frame" style={{ width: "100%", maxHeight: 320, objectFit: "contain", background: "#000", borderRadius: 8 }} />
              <a className="cx-go" href={done.file_url} download target="_blank" rel="noreferrer" style={{ marginTop: 10 }}>
                <Download /> Download .png
              </a>
            </div>
          ) : null}
          {done && done.format === "project" && done.otio_url ? (
            <div className="cx-card">
              <p className="cx-note" style={{ marginTop: 0 }}>
                Import the .otio in DaVinci Resolve (File › Import › Timeline) or any OpenTimelineIO editor. Cuts, gaps,
                transitions (as dissolves), speed and markers carry over; keyframes, crop and the mix do not — they are
                kept in the file&apos;s metadata. Captions come as a separate .srt.
              </p>
              <span className="cx-field-row">
                <a className="cx-go" href={done.otio_url} download target="_blank" rel="noreferrer">
                  <Download /> .otio
                </a>
                {done.srt_url ? (
                  <a className="cx-btn ghost" href={done.srt_url} download target="_blank" rel="noreferrer">
                    <Download /> .srt
                  </a>
                ) : null}
              </span>
            </div>
          ) : null}

          <div className="cx-field-row" style={{ justifyContent: "flex-end", margin: "6px 0 18px" }}>
            <button type="button" className="cx-go" onClick={() => void start()} disabled={running || !versionId}>
              {running ? <Loader2 className="animate-spin" /> : <Download />}
              {running ? "Working…" : FORMATS.find((f) => f.id === format)?.verb}
            </button>
          </div>

          <span className="cx-label">Past exports</span>
          {past.length ? (
            <div style={{ marginTop: 6 }}>
              {past.map((p) => (
                <div key={p.timeline_id} className="cx-ver">
                  <span className="n">v{p.version}</span>
                  <span style={{ minWidth: 0 }}>
                    <span className="s" style={{ display: "block" }}>
                      {p.op_summary}
                    </span>
                    <span className="w">{ago(p.created_at)}</span>
                  </span>
                  {p.export_url ? (
                    <a className="cx-btn ghost" href={p.export_url} target="_blank" rel="noreferrer">
                      Open
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="cx-note" style={{ marginTop: 6 }}>
              No exports of this project yet.
            </p>
          )}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

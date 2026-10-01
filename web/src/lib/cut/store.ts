"use client";

/* The editor's state (2026-09-28): one zustand store per open project.

   THE RULE: the UI never writes a doc. Every change is an op posted to
   /api/cut/projects/{id}/ops, where src/cut/ops.apply runs it and the
   validator decides; the doc on screen is ALWAYS the server's head, except
   for one thing -- the ghost.

   The ghost is T10's optimism: a drag draws the result it expects the
   moment the pointer lets go, while the op is in flight. The server's
   answer replaces it. Three outcomes, three behaviours:

   - 200: the new head is the doc; the ghost goes.
   - 409 `stale`: another tab (or the agent) moved the head. Refetch it and
     replay the SAME op once against the new head -- a move by frames is
     still meaningful there. A second refusal is shown, not retried.
   - 422 `invalid`: the validator's reasons go to the toast, verbatim, and
     the ghost is dropped, which is the rollback.

   Ops are serialised: a second op waits for the first, because each is
   based on the head the first produces. */
import { create } from "zustand";
import {
  applyOp,
  CutError,
  getPreview,
  getProject,
  listBin,
  redo as redoCall,
  rollback as rollbackCall,
  undo as undoCall,
  type BinItem,
  type EditorState,
  type Head,
  type MediaInfo,
  type OpResult,
  type Preview,
  type Project,
  type Proposal,
  type VersionRow,
} from "@/lib/cut/api";
import { describeOp, endOf, type Doc } from "@/lib/cut/timeline";

export type Tool = "select" | "blade";
export type Selection = { ids: string[]; kind: "clip" | "cue" | null };
export type TrackMix = { mute?: boolean; solo?: boolean };
export type LeftTab = "agent" | "media" | "text" | "audio" | "transitions" | "search";
/* Resolve's pages (2026-10-01): one editor, three layouts over the same
   doc -- Edit, Audio (the mixer over the sound tracks) and Color (basic
   correction per picture clip). Switching is a view, never an edit. */
export type Page = "edit" | "audio" | "color";
/* Which viewer the transport keys drive (Resolve's model): clicking a
   viewer -- or loading a clip into Source -- makes it active. */
export type ActiveViewer = "source" | "program";
export type Marks = { in?: number; out?: number };
/* one line of the agent's thread. A proposal's status is the person's
   click: pending until Keep or Undo, and nothing else changes it. */
export type Turn = {
  id: string;
  role: "me" | "agent";
  text: string;
  proposal?: Proposal | null;
  status?: "pending" | "kept" | "undone";
  notes?: string[];
  needsIndex?: string[];
  /** the action to re-run once the clips are indexed */
  retry?: "cleanup" | "captions";
  working?: boolean;
};

type Toast = (text: string, kind?: "ok" | "err") => void;

export type CutStore = {
  projectId: string | null;
  loading: boolean;
  error: string | null;
  project: Project | null;
  head: Head | null;
  doc: Doc | null;
  ghost: Doc | null;
  media: MediaInfo;
  versions: VersionRow[];
  canUndo: boolean;
  canRedo: boolean;
  busy: boolean;

  selection: Selection;
  playhead: number;
  playing: boolean;
  /** J/K/L: 1 is normal, 2/4 faster, negative plays backwards */
  rate: number;
  tool: Tool;
  snapOn: boolean;
  pps: number;
  mix: Record<string, TrackMix>;
  previews: Record<string, Preview>;
  /** the region an agent proposal would change, drawn on the timeline */
  highlight: { from: number; to: number } | null;
  bin: BinItem[];
  binLoading: boolean;
  leftTab: LeftTab;
  page: Page;
  thread: Turn[];
  /** the proposal whose AFTER is on screen (its doc is the ghost) */
  previewing: string | null;

  /* the Source viewer: one bin item, its own clock, its own marks. Frames
     are at the PROJECT fps, so a marked range is already the src_in /
     src_out an op takes. */
  source: { handle: string | null; playhead: number; playing: boolean; rate: number; frames: number | null };
  /** In/Out per handle, kept for the session: reloading a clip into Source
   *  finds its marks where you left them */
  marks: Record<string, Marks>;
  activeViewer: ActiveViewer;

  toast: Toast;
  setToast: (t: Toast) => void;
  load: (id: string) => Promise<void>;
  refresh: () => Promise<void>;
  /** `silent`: a refusal is not toasted but left in `lastError` for the
   *  caller, which is how a drop learns an unprobed file's real length */
  op: (
    op: string,
    args: Record<string, unknown>,
    opts?: { ghost?: Doc; quiet?: boolean; silent?: boolean },
  ) => Promise<boolean>;
  lastError: CutError | null;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  restore: (timelineId: number) => Promise<void>;

  select: (ids: string[], kind: Selection["kind"], additive?: boolean) => void;
  clearSelection: () => void;
  seek: (frame: number) => void;
  setPlaying: (p: boolean) => void;
  setRate: (r: number) => void;
  setTool: (t: Tool) => void;
  toggleSnap: () => void;
  setPps: (pps: number) => void;
  setMix: (trackId: string, patch: TrackMix) => void;
  setHighlight: (h: { from: number; to: number } | null) => void;
  ensurePreview: (handle: string) => void;
  loadBin: () => Promise<void>;
  addToBin: (item: BinItem) => void;
  setLeftTab: (t: LeftTab) => void;
  setPage: (p: Page) => void;
  pushTurn: (t: Omit<Turn, "id">) => string;
  updateTurn: (id: string, patch: Partial<Turn>) => void;
  preview: (turnId: string | null) => void;
  loadSource: (handle: string) => void;
  sourceSeek: (frame: number) => void;
  setSourcePlaying: (p: boolean) => void;
  setSourceRate: (r: number) => void;
  /** the clip's real length, once the player has read it (a render nobody
   *  probed has none on its bin row) */
  setSourceFrames: (frames: number) => void;
  markIn: (frame?: number) => void;
  markOut: (frame?: number) => void;
  clearMarks: () => void;
  setActiveViewer: (v: ActiveViewer) => void;
};

let chain: Promise<unknown> = Promise.resolve();
const inflight = new Set<string>();

export const useCut = create<CutStore>((set, get) => {
  const adopt = (res: OpResult | EditorState) => {
    const head = res.head;
    set((s) => ({
      head,
      doc: head.doc,
      ghost: null,
      previewing: null,
      canUndo: res.can_undo,
      canRedo: res.can_redo,
      media: res.media ? { ...s.media, ...res.media } : s.media,
      versions:
        "versions" in res
          ? res.versions
          : [
              { ...head, doc: undefined } as unknown as VersionRow,
              ...s.versions.filter((v) => v.id !== head.id),
            ].sort((a, b) => b.version - a.version),
      // a selection that names clips the new doc no longer has is dropped
      selection: keepSelection(s.selection, head.doc),
      playhead: Math.min(s.playhead, Math.max(0, endOf(head.doc))),
      project: s.project ? { ...s.project, version: head.version, duration: head.doc.duration } : s.project,
    }));
  };

  const serial = <T,>(fn: () => Promise<T>): Promise<T> => {
    const next = chain.then(fn, fn);
    chain = next.catch(() => undefined);
    return next;
  };

  return {
    projectId: null,
    loading: false,
    error: null,
    project: null,
    head: null,
    doc: null,
    ghost: null,
    media: {},
    versions: [],
    canUndo: false,
    canRedo: false,
    busy: false,
    selection: { ids: [], kind: null },
    playhead: 0,
    playing: false,
    rate: 1,
    tool: "select",
    snapOn: true,
    pps: 80,
    mix: {},
    previews: {},
    highlight: null,
    lastError: null,
    bin: [],
    binLoading: false,
    leftTab: "media",
    page: "edit",
    thread: [],
    previewing: null,
    source: { handle: null, playhead: 0, playing: false, rate: 1, frames: null },
    marks: {},
    activeViewer: "program",

    toast: () => {},
    setToast: (toast) => set({ toast }),

    load: async (id) => {
      set({
        projectId: id,
        loading: true,
        error: null,
        previews: {},
        selection: { ids: [], kind: null },
        playhead: 0,
        thread: [],
        previewing: null,
        ghost: null,
        highlight: null,
        source: { handle: null, playhead: 0, playing: false, rate: 1, frames: null },
        activeViewer: "program",
      });
      try {
        const res = await getProject(id);
        set({ project: res.project, loading: false, media: res.media ?? {} });
        adopt(res);
      } catch (e) {
        set({ loading: false, error: e instanceof Error ? e.message : "could not open the project" });
      }
    },

    refresh: async () => {
      const id = get().projectId;
      if (!id) return;
      const res = await getProject(id);
      set({ project: res.project, media: { ...get().media, ...(res.media ?? {}) } });
      adopt(res);
    },

    op: (op, args, opts = {}) =>
      serial(async () => {
        const { projectId, head, doc } = get();
        if (!projectId || !head || !doc) return false;
        if (opts.ghost) set({ ghost: opts.ghost });
        set({ busy: true, lastError: null });
        const attempt = async (baseId: number, retried: boolean): Promise<boolean> => {
          try {
            const res = await applyOp(projectId, baseId, op, args);
            adopt(res);
            if (!opts.quiet) get().toast(describeOp(op, args, doc.fps));
            return true;
          } catch (e) {
            if (e instanceof CutError && e.code === "stale" && !retried) {
              // behind the head: take the new one and replay this op once
              await get().refresh();
              const fresh = get().head;
              if (fresh) return attempt(fresh.id, true);
            }
            set({ ghost: null, lastError: e instanceof CutError ? e : null });
            if (opts.silent) return false;
            const reason =
              e instanceof CutError && e.problems.length
                ? e.problems.slice(0, 3).join(" · ")
                : e instanceof Error
                  ? e.message
                  : "the edit failed";
            get().toast(reason, "err");
            return false;
          }
        };
        try {
          return await attempt(head.id, false);
        } finally {
          set({ busy: false });
        }
      }),

    undo: () =>
      serial(async () => {
        const id = get().projectId;
        if (!id || !get().canUndo) return;
        try {
          adopt(await undoCall(id));
        } catch (e) {
          get().toast(e instanceof Error ? e.message : "nothing to undo", "err");
        }
      }),

    redo: () =>
      serial(async () => {
        const id = get().projectId;
        if (!id || !get().canRedo) return;
        try {
          adopt(await redoCall(id));
        } catch (e) {
          get().toast(e instanceof Error ? e.message : "nothing to redo", "err");
        }
      }),

    restore: (timelineId) =>
      serial(async () => {
        const id = get().projectId;
        if (!id) return;
        try {
          adopt(await rollbackCall(id, timelineId));
          get().toast("Restored that version");
        } catch (e) {
          get().toast(e instanceof Error ? e.message : "could not restore", "err");
        }
      }),

    select: (ids, kind, additive = false) =>
      set((s) => {
        if (!additive || s.selection.kind !== kind) return { selection: { ids, kind } };
        const next = new Set(s.selection.ids);
        for (const id of ids) {
          if (next.has(id)) next.delete(id);
          else next.add(id);
        }
        return { selection: { ids: [...next], kind: next.size ? kind : null } };
      }),
    clearSelection: () => set({ selection: { ids: [], kind: null } }),
    seek: (frame) => {
      const doc = get().ghost ?? get().doc;
      const end = doc ? endOf(doc) : 0;
      set({ playhead: Math.max(0, Math.min(Math.round(frame), end)) });
    },
    setPlaying: (playing) =>
      set((s) => (playing ? { playing, source: { ...s.source, playing: false } } : { playing, rate: 1 })),
    setRate: (rate) => set({ rate }),
    setTool: (tool) => set({ tool }),
    toggleSnap: () => set((s) => ({ snapOn: !s.snapOn })),
    setPps: (pps) => set({ pps }),
    setMix: (trackId, patch) => set((s) => ({ mix: { ...s.mix, [trackId]: { ...s.mix[trackId], ...patch } } })),
    setHighlight: (highlight) => set({ highlight }),

    loadBin: async () => {
      const id = get().projectId;
      if (!id) return;
      set({ binLoading: true });
      try {
        const res = await listBin(id);
        set({ bin: res.items, binLoading: false });
      } catch (e) {
        set({ binLoading: false });
        get().toast(e instanceof Error ? e.message : "could not read the media bin", "err");
      }
    },
    addToBin: (item) => set((s) => ({ bin: [item, ...s.bin.filter((b) => b.handle !== item.handle)] })),
    setLeftTab: (leftTab) => set({ leftTab }),
    setPage: (page) => set({ page }),
    pushTurn: (t) => {
      const id = `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
      set((s) => ({ thread: [...s.thread.slice(-59), { ...t, id }] }));
      return id;
    },
    loadSource: (handle) =>
      set((s) => {
        const fps = s.doc?.fps ?? 30;
        const known = s.media[handle]?.frames;
        const item = s.bin.find((b) => b.handle === handle);
        const frames = known ?? (item?.kind === "image" ? 5 * fps : item?.seconds ? Math.floor(item.seconds * fps) : null);
        const m = s.marks[handle];
        return {
          source: { handle, playhead: m?.in ?? 0, playing: false, rate: 1, frames },
          activeViewer: "source",
          playing: false,
        };
      }),
    sourceSeek: (frame) =>
      set((s) => {
        const end = s.source.frames ?? Number.MAX_SAFE_INTEGER;
        return { source: { ...s.source, playhead: Math.max(0, Math.min(Math.round(frame), Math.max(0, end - 1))) } };
      }),
    setSourcePlaying: (playing) =>
      set((s) => ({ source: { ...s.source, playing, rate: playing ? s.source.rate : 1 }, ...(playing ? { playing: false } : {}) })),
    setSourceRate: (rate) => set((s) => ({ source: { ...s.source, rate } })),
    setSourceFrames: (frames) =>
      set((s) => (s.source.frames === frames ? {} : { source: { ...s.source, frames } })),
    /* An In after the Out (or an Out before the In) drops the other mark,
       as every NLE does, rather than leaving a range that runs backwards. */
    markIn: (frame) =>
      set((s) => {
        const h = s.source.handle;
        if (!h) return {};
        const f = frame ?? s.source.playhead;
        const cur = s.marks[h] ?? {};
        const next: Marks = { in: f, out: cur.out !== undefined && cur.out > f ? cur.out : undefined };
        return { marks: { ...s.marks, [h]: next } };
      }),
    markOut: (frame) =>
      set((s) => {
        const h = s.source.handle;
        if (!h) return {};
        // the Out is EXCLUSIVE (src_out): marking at the playhead keeps the
        // frame on screen, so the mark sits one past it
        const f = (frame ?? s.source.playhead) + 1;
        const cur = s.marks[h] ?? {};
        const next: Marks = { out: f, in: cur.in !== undefined && cur.in < f ? cur.in : undefined };
        return { marks: { ...s.marks, [h]: next } };
      }),
    clearMarks: () =>
      set((s) => {
        const h = s.source.handle;
        if (!h) return {};
        const rest = { ...s.marks };
        delete rest[h];
        return { marks: rest };
      }),
    setActiveViewer: (activeViewer) => set({ activeViewer }),
    updateTurn: (id, patch) => set((s) => ({ thread: s.thread.map((t) => (t.id === id ? { ...t, ...patch } : t)) })),
    /* Before/after: the proposal's doc drawn as the ghost -- the viewer and
       the timeline both read the ghost, so "after" plays as well as shows.
       Nothing is saved; switching back is dropping the ghost. */
    preview: (turnId) => {
      if (!turnId) return set({ previewing: null, ghost: null, highlight: null });
      const t = get().thread.find((x) => x.id === turnId);
      if (!t?.proposal) return;
      set({ previewing: turnId, ghost: t.proposal.doc, highlight: t.proposal.region });
    },

    /* T6's artifacts, asked for once per handle per session; a `pending`
       answer is asked again a few seconds later until it settles. */
    ensurePreview: (handle) => {
      const have = get().previews[handle];
      if ((have && have.status !== "pending") || inflight.has(handle)) return;
      inflight.add(handle);
      const ask = (delay: number) =>
        setTimeout(() => {
          getPreview(handle)
            .then((p) => {
              set((s) => ({ previews: { ...s.previews, [handle]: p } }));
              if (p.status === "pending" && delay < 60_000) ask(Math.min(delay * 2 || 2000, 16_000));
              else inflight.delete(handle);
            })
            .catch(() => {
              set((s) => ({
                previews: {
                  ...s.previews,
                  [handle]: { status: "unavailable", proxy: null, filmstrip: null, waveform: null },
                },
              }));
              inflight.delete(handle);
            });
        }, delay);
      ask(0);
    },
  };
});

function keepSelection(sel: Selection, doc: Doc): Selection {
  if (!sel.ids.length) return sel;
  const ids = new Set<string>();
  for (const t of doc.tracks) {
    for (const c of t.clips ?? []) ids.add(c.id);
    for (const q of t.cues ?? []) ids.add(q.id);
  }
  const kept = sel.ids.filter((id) => ids.has(id));
  return kept.length ? { ids: kept, kind: sel.kind } : { ids: [], kind: null };
}

/* the doc to DRAW: the ghost while an op is in flight, else the head */
export const useDrawnDoc = () => useCut((s) => s.ghost ?? s.doc);

/* what a handle is, for a clip's name and kind: the bin knows */
export const binItem = (handle: string): BinItem | undefined =>
  useCut.getState().bin.find((b) => b.handle === handle);
export const useBinItem = (handle: string) => useCut((s) => s.bin.find((b) => b.handle === handle));

/* The editor's calls into /api/cut (app/cut_routes.py), typed against
   what those routes return. Same-origin through the Next proxy, like
   every studio call, so the zp_session cookie rides along.

   Its own fetch rather than lib/api's apiFetch, for one reason: an op
   refusal carries a BODY the editor acts on -- a 409 names the head the
   tab is behind (refetch and replay), a 422 carries the validator's
   `problems` (roll the ghost back and say why). apiFetch keeps only the
   message. */
import { API_URL } from "@/lib/api";
import type { Aspect, Doc } from "@/lib/cut/timeline";

export class CutError extends Error {
  status: number;
  code: string;
  problems: string[];
  headId: number | null;
  constructor(status: number, code: string, message: string, problems: string[] = [], headId: number | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.problems = problems;
    this.headId = headId;
  }
}

async function cutFetch<T>(path: string, init?: RequestInit & { form?: FormData }): Promise<T> {
  const { form, ...rest } = init ?? {};
  const res = await fetch(`${API_URL}/api/cut${path}`, {
    credentials: "include",
    ...(form ? { method: "POST", body: form } : { headers: { "Content-Type": "application/json" } }),
    ...rest,
  });
  if (!res.ok) {
    let code = "error";
    let message = res.statusText || `request failed (${res.status})`;
    let problems: string[] = [];
    let headId: number | null = null;
    try {
      const body = await res.clone().json();
      const err = body?.error;
      if (err) {
        code = err.code ?? code;
        message = err.message ?? message;
        problems = Array.isArray(err.problems) ? err.problems : [];
        headId = typeof err.head_id === "number" ? err.head_id : null;
      } else if (body?.detail) {
        message = typeof body.detail === "string" ? body.detail : message;
      }
    } catch {
      /* not JSON */
    }
    throw new CutError(res.status, code, message, problems, headId);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

const post = <T>(path: string, body: unknown = {}) =>
  cutFetch<T>(path, { method: "POST", body: JSON.stringify(body) });

/* ── shapes ── */
export type Project = {
  id: string;
  title: string;
  timeline_key: string;
  concept_id: number | null;
  fps: number;
  size: [number, number];
  aspect: Aspect | null;
  duration: number;
  version: number | null;
  poster: string | null;
  export_url: string | null;
  created_at: string;
  updated_at: string;
};
export type VersionRow = {
  id: number;
  version: number;
  parent_id: number | null;
  author: "user" | "agent" | "assemble";
  op_summary: string;
  created_at: string;
  export_url: string | null;
};
export type Head = VersionRow & { doc: Doc };
/** handle -> what the file really is (frames at the project fps) */
export type MediaInfo = Record<string, { frames: number; video: boolean; audio: boolean; seconds: number }>;
export type EditorState = {
  project: Project;
  head: Head;
  versions: VersionRow[];
  can_undo: boolean;
  can_redo: boolean;
  media: MediaInfo;
};
export type OpResult = { head: Head; can_undo: boolean; can_redo: boolean; media?: MediaInfo };
export type BinItem = {
  handle: string;
  kind: "video" | "image" | "audio";
  name: string;
  seconds: number | null;
  width: number | null;
  height: number | null;
  has_video: boolean;
  has_audio: boolean;
  size_bytes: number | null;
  url: string | null;
  poster: string | null;
  created_at: string | null;
  source: "render" | "upload";
};
export type Preview = {
  status: "ready" | "pending" | "failed" | "unavailable";
  proxy: string | null;
  filmstrip: { url: string; frame_width: number; frame_height: number; count: number; interval: number } | null;
  waveform: { url: string; per_second: number } | null;
  note?: string;
};

/* ── projects ── */
export const listProjects = () => cutFetch<{ projects: Project[] }>("/projects");
/** `concept_id`: that scene's cut (created or returned). `handles`: a
 *  scratch project whose first version already holds those media, in
 *  order -- the Assets tile's Edit. */
export const createProject = (body: { title?: string; aspect?: Aspect; concept_id?: number; handles?: string[] }) =>
  post<{ project: Project }>("/projects", body);

/* The one door every entry point uses (T23): make-or-find the project,
   then the editor's own URL. */
export async function openInEditor(body: { concept_id?: number; handles?: string[]; title?: string }): Promise<string> {
  const res = await createProject(body);
  return `/studio/cut/${encodeURIComponent(res.project.id)}`;
}
export const getProject = (id: string) => cutFetch<EditorState>(`/projects/${encodeURIComponent(id)}`);
export const renameProject = (id: string, title: string) =>
  cutFetch<{ project: Project }>(`/projects/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
export const deleteProject = (id: string) =>
  cutFetch<{ ok: boolean }>(`/projects/${encodeURIComponent(id)}`, { method: "DELETE" });

/* ── edits: every change to a doc is one of these ── */
export const applyOp = (id: string, base_id: number, op: string, args: Record<string, unknown>) =>
  post<OpResult>(`/projects/${encodeURIComponent(id)}/ops`, { base_id, op, args });
export const undo = (id: string) => post<OpResult>(`/projects/${encodeURIComponent(id)}/undo`);
export const redo = (id: string) => post<OpResult>(`/projects/${encodeURIComponent(id)}/redo`);
export const rollback = (id: string, timeline_id: number) =>
  post<OpResult>(`/projects/${encodeURIComponent(id)}/rollback`, { timeline_id });

/* ── media ── */
export const listBin = (id: string) => cutFetch<{ items: BinItem[] }>(`/projects/${encodeURIComponent(id)}/media`);
export const uploadMedia = (file: File) => {
  const form = new FormData();
  form.append("file", file, file.name);
  return cutFetch<{ handle: string; kind: string; seconds: number | null; filename: string; item?: BinItem }>(
    "/media",
    { form },
  );
};
export const getPreview = (handle: string) => cutFetch<Preview>(`/media/${encodeURIComponent(handle)}/preview`);

/* ── export ── */
export type ExportFormat = "mp4" | "audio" | "still" | "project";
export const exportProject = (
  id: string,
  body: { timeline_id?: number; aspect?: Aspect; format?: ExportFormat; frame?: number },
) =>
  post<{ job_id: number; timeline_id: number; version: number }>(`/projects/${encodeURIComponent(id)}/export`, body);
export const listExports = (id: string) =>
  cutFetch<{
    exports: { timeline_id: number; version: number; export_url: string | null; created_at: string; op_summary: string }[];
  }>(`/projects/${encodeURIComponent(id)}/exports`);

/* the footage index (phase 2) */
export type SearchHit = {
  media: string;
  kind: string;
  start_f: number;
  end_f: number;
  speaker?: string | null;
  text?: string | null;
  media_url?: string | null;
  concept_title?: string | null;
  score?: number;
};
export const searchFootage = (q: string) =>
  cutFetch<{ results: SearchHit[]; notes: string[] }>(`/search?q=${encodeURIComponent(q)}`);

/* ── the agent (Phase E) ──
   A Proposal is an edit nobody has made yet: the ops, validated against
   `base_id` on the server BEFORE it was shown, and the doc they produce.
   Keep posts the ops back (the server re-applies and validates them again
   against the head, and saves ONE version authored "agent"); Undo is the
   card going away -- nothing was saved, so there is nothing to discard. */
export type ProposedOp = { op: string; args: Record<string, unknown> };
export type Proposal = {
  summary: string;
  ops: ProposedOp[];
  base_id: number;
  region: { from: number; to: number } | null;
  duration_delta: number;
  doc: Doc;
  kind: "agent" | "cleanup" | "captions";
};
export type AgentReply = {
  reply: string;
  proposal: Proposal | null;
  tool_runs?: { tool: string; args: Record<string, unknown>; ok: boolean }[];
  notes?: string[];
};
export const askAgent = (id: string, body: { message: string; playhead?: number; selection?: string[] }) =>
  post<{ job_id: number }>(`/projects/${encodeURIComponent(id)}/agent`, body);
export const keepProposal = (id: string, p: Pick<Proposal, "base_id" | "ops" | "summary" | "kind">) =>
  post<OpResult>(`/projects/${encodeURIComponent(id)}/agent/keep`, p);
export type Suggested = { proposal: Proposal | null; needs_index: string[]; notes: string[] };
export const proposeCleanup = (id: string, body: { base_id?: number; min_silence?: number; fillers?: boolean } = {}) =>
  post<Suggested & { found: { silences: number; fillers: number } }>(`/projects/${encodeURIComponent(id)}/cleanup`, body);
export const proposeCaptions = (id: string, body: { base_id?: number; track_id?: string; max_words?: number } = {}) =>
  post<Suggested & { cues: number }>(`/projects/${encodeURIComponent(id)}/captions`, body);
export const indexProject = (id: string) =>
  post<{ job_id: number; handles: string[] }>(`/projects/${encodeURIComponent(id)}/index`);

/* the Source viewer's Transcript tab: what the index heard and saw in one
   file, in SECONDS (the index's own fps is converted on the server) */
export type Transcript = {
  status: "indexed" | "not_indexed";
  speech: boolean | null;
  words: { start: number; end: number; text: string; speaker?: string | null }[];
  shots: { start: number; end: number; text: string }[];
};
export const getTranscript = (handle: string) =>
  cutFetch<Transcript>(`/media/${encodeURIComponent(handle)}/transcript`);

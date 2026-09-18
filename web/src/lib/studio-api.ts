/* The studio surfaces' calls into FastAPI, typed against what app/api.py
   returns today. Everything goes through the same-origin proxy
   (next.config.ts rewrites /api, /ui, /brand, the photo routes) so the
   zp_session cookie rides along untouched. Nothing here spends: the
   billed routes (scenes/run, the exec/* nodes) are the same gated ones
   the Jinja shell calls, and Send to Queue only PICKS. */
import { API_URL, ApiError, apiFetch } from "@/lib/api";

export { ApiError };

/* ── who ── */
export type Account = {
  id: number;
  slug: string;
  label: string;
  accent?: string | null;
  role?: string | null;
};
export type Me = {
  user: {
    id: string;
    email: string | null;
    display_name: string;
    avatar_url: string | null;
  };
  account: Account | null;
  accounts: Account[];
};
export const getMe = () => apiFetch<Me>("/me");

/* ── what may be drawn ── */
export type Capabilities = Record<string, boolean>;
export const getCapabilities = () => apiFetch<Capabilities>("/capabilities");

/* ── assets (elements) ── */
export type AssetCategory = "character" | "location" | "prop";
export type Asset = {
  id: string;
  category: AssetCategory;
  name: string;
  photos: string[];
  poster: string | null;
  /** the drawn reference sheet, when one exists — always LAST in `photos` (2026-09-18) */
  sheet?: string | null;
  text: string;
  meta: Record<string, unknown>;
  created_at?: string | null;
};
/* Which half of the bank (2026-09-18): `elements` is the characters /
   locations / props a shot is held to, `generated` is the renders, `all`
   is both -- the server's default, kept for the one caller that needs a
   generated id to resolve (the composer's ?attach= handoff). */
export type AssetScope = "all" | "elements" | "generated";
export const getAssets = (q?: string, scope: AssetScope = "elements") => {
  const params = new URLSearchParams({ scope });
  if (q) params.set("q", q);
  return apiFetch<{ items: Asset[] }>(`/assets?${params}`);
};

export type AssetHit = { name: string; category: AssetCategory; thumb: string | null };
export const searchAssets = (q: string) =>
  apiFetch<{ items: AssetHit[] }>(`/assets/search?q=${encodeURIComponent(q)}`);

/* Routes behind app/model_connections.mutation_header refuse any request
   that does not carry this header (403, before any work). It exists so a
   SameSite=None studio session cannot be spent by a cross-site form post:
   a custom header forces a CORS preflight. Send it from ONE place -- the
   Jinja client sends it per call site and the React composer was ported
   without it, which 403'd every Guide turn silently (2026-09-14). */
export const GUARDED_HEADERS: Record<string, string> = {
  "X-ZPF-Model-Connection": "1",
};

/* multipart: apiFetch pins a JSON content-type, so uploads go direct */
async function apiForm<T>(
  path: string,
  form: FormData,
  headers?: Record<string, string>,
): Promise<T> {
  const res = await fetch(`${API_URL}/api${path}`, {
    method: "POST",
    credentials: "include",
    ...(headers ? { headers } : {}),
    body: form,
  });
  if (!res.ok) {
    let message = res.statusText || `request failed (${res.status})`;
    try {
      const body = await res.clone().json();
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(message, res.status);
  }
  return (await res.json()) as T;
}

export type AssetCreated = {
  ok: boolean;
  slug: string;
  photos: number;
  described?: boolean;
  note?: string | null;
  /** the job drawing the element's reference sheet, when one was asked for (2026-09-18) */
  sheet_job?: number | null;
};
export type ElementKind = "characters" | "locations" | "props";
/** POST /api/assets/{kind}/{id}/sheet — draw (or redraw) an element's
 *  reference sheet from its real photos; cents on Nano Banana Pro. */
export const drawSheet = (kind: ElementKind, id: number) =>
  apiFetch<{ job_id: number }>(`/assets/${kind}/${id}/sheet`, { method: "POST", body: "{}" });
/** POST /api/assets/{characters|locations|props} — the always-on create
 *  path; every save also teaches the RAG assets shelf. */
export const createAsset = (
  kind: "characters" | "locations" | "props",
  form: FormData,
) => apiForm<AssetCreated>(`/assets/${kind}`, form);

/* ── the media wall ── */
export type MediaItem = {
  url: string;
  asset_id: string;
  asset_name: string;
  category: AssetCategory | "generated";
  kind: "image" | "video";
  date: string;
  /* generated rows only (2026-09-18) */
  generated_id?: number;
  provider?: string | null;
  model?: string | null;
  concept_id?: number | null;
  shot_n?: number | null;
  prompt?: string;
  folder?: string | null;
  starred?: boolean;
};
export type MediaCounts = Record<string, number> & { all: number };
export type MediaWall = {
  items: MediaItem[];
  counts: MediaCounts;
  wall: { image: number; video: number; starred: number };
  folders: Record<string, number>;
  providers: Record<string, number>;
};
export type MediaFilter = {
  q?: string;
  kind?: "image" | "video";
  folder?: string;
  starred?: boolean;
  provider?: string;
};
/** GET /api/media?kind=all&scope=generated — one row per render, newest
 *  first; `counts`/`wall`/`folders`/`providers` are set totals, never
 *  page length. The Assets wall is generated content only (2026-09-18). */
export const getMedia = (f: MediaFilter = {}) => {
  const params = new URLSearchParams({ kind: f.kind ?? "all", scope: "generated" });
  if (f.q) params.set("q", f.q);
  if (f.folder) params.set("folder", f.folder);
  if (f.starred) params.set("starred", "true");
  if (f.provider) params.set("provider", f.provider);
  return apiFetch<MediaWall>(`/media?${params}`);
};
/** DELETE /api/assets/{characters|props|locations}/{id} — an element. */
export const deleteAsset = (kind: "characters" | "props" | "locations", id: number) =>
  apiFetch<{ deleted: number }>(`/assets/${kind}/${id}`, { method: "DELETE" });
/** DELETE /api/assets/generated/{id} — a SOFT delete: off the wall and
 *  the RAG shelf, the file and the row stay. */
export const deleteGenerated = (id: number) =>
  apiFetch<{ deleted: number }>(`/assets/generated/${id}`, { method: "DELETE" });
/** PATCH /api/assets/generated/{id} — folder and/or star. A field left
 *  out is left alone; folder "" clears it. */
export const organizeGenerated = (id: number, body: { folder?: string; starred?: boolean }) =>
  apiFetch<{ id: number; folder: string | null; starred: boolean }>(`/assets/generated/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

/* ── the board and the queue ── */
export type Concept = {
  id: number;
  n: string;
  title: string;
  summary: string;
  logline: string;
  brand: string;
  spark: string | null;
  status: "idea" | "planned" | "shot";
  is_scene: boolean;
  picked: boolean;
  parked: boolean;
  archived: boolean;
  park_reason: string;
  refs: string[];
  prompt: string;
  media_url: string;
  reference_image: string;
  created_at?: string;
  /** the card's own default renderer, resolved server-side from the shot's planned tool */
  render_default?: { provider: string; model: string };
};
export type RunwayModel = { id: string; label: string; usd_per_second: number };
/* the overnight branch's renderer catalogue (providers.render_options):
   every registered renderer with its gates, its models and each model's
   legal duration and frame axis; a price shape the card may multiply */
export type Axis = {
  kind: "choices" | "range" | "fixed";
  values?: (string | number)[];
  min?: number;
  max?: number;
  default?: string | number | null;
  note?: string;
};
export type ModelSpec = {
  id: string;
  label: string;
  available?: boolean;
  duration: Axis;
  frame: Axis;
  verified?: string | null;
  price?: { kind: "per_second" | "flat" | "unknown"; usd?: number; usd_by_frame?: Record<string, number> };
};
export type RendererSpec = {
  label: string;
  available: boolean;
  spend_ok: boolean;
  spend_env?: string | null;
  cap?: number | null;
  today?: number | null;
  frame_axis: "ratio" | "resolution";
  models: ModelSpec[];
  default_model: string | null;
};
export type RunwayState = {
  available: boolean;
  spend_ok: boolean;
  model: string;
  estimate_usd: number;
  ratio?: string;
  duration?: number;
  models?: RunwayModel[];
  ratios?: string[];
  durations?: number[];
  today?: number | null;
};
/** what approve takes: providers.check_render_choice refuses, never clamps */
export type RenderChoice = { provider?: string; model?: string; duration?: number; frame?: string };
export type RenderResolved = { provider: string; model: string; duration: number; frame: string; estimate_usd: number };
export type PickRate = { generated: number; picked: number; rate: number | null };
/** GET /api/pipeline/concepts — the board. Ask for the archived rows
 *  too and filter client-side, so the count line can say where every
 *  card went (the 2026-09-02 lesson). */
export const boardConcepts = (brand?: string, archived = false) => {
  const params = new URLSearchParams();
  if (brand) params.set("brand", brand);
  if (archived) params.set("archived", "true");
  const qs = params.toString();
  return apiFetch<{ items: Concept[]; pick?: PickRate }>(`/pipeline/concepts${qs ? `?${qs}` : ""}`);
};
/** Leaving the board is archiving, never deleting: an unpicked row is
 *  the only negative signal pick_rate has. */
export const archiveConcept = (id: number, archived = true) =>
  apiFetch<{ ok: boolean }>(`/concepts/${id}/archive`, {
    method: "POST",
    body: JSON.stringify({ archived }),
  });
export const updateShotPrompt = (id: number, n: number, prompt: string) =>
  apiFetch<{ ok: boolean; warnings?: string[] }>(`/concepts/${id}/shots/${n}/prompt`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
/* the spend gate: approving is what calls Runway */
export const queueApprove = (id: number, choice?: RenderChoice) =>
  apiFetch<{ job_id?: number; render?: RenderResolved }>(`/queue/${id}/approve`, {
    method: "POST",
    body: JSON.stringify(choice ?? {}),
  });
export const queueReject = (id: number) =>
  apiFetch<{ ok: boolean }>(`/queue/${id}/reject`, { method: "POST", body: "{}" });
/** made by hand, outside the render lane — drops it off the pending list */
export const queueShot = (id: number) =>
  apiFetch<{ ok: boolean }>(`/queue/${id}/shot`, { method: "POST", body: JSON.stringify({ shot: true }) });
/* ── the subscription lane (operator-gated server-side; the `manual_lane`
   capability only says whether to draw the section) ── */
export type LaneModel = { id: string; durations: number[]; ratios: string[] };
export type LaneItem = {
  concept_id: number;
  title: string;
  brand: string;
  shot_n: number;
  prompt: string;
  keyframe_url: string | null;
  duration: number;
  ratio: string;
  lane?: string;
};
/** GET /api/queue/manual — the same waiting shots, addressed to a pair of
 *  hands in Chrome; a 404 for an account the lane is not open for. */
export const queueManual = (brand?: string) =>
  apiFetch<{ items: LaneItem[]; models: LaneModel[]; default_model: string }>(
    `/queue/manual${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`,
  );
/** POST /api/queue/manual/{id}/clip — the finished mp4, filed by
 *  ops/render_queue.import_clip as a FREE row; the claimed model, frame
 *  and length are refused by render_specs if the lane cannot have
 *  produced them; a second drop is refused (409). */
export const fileLaneClip = (
  id: number,
  file: File,
  claim: { shot_n?: number; model?: string; ratio?: string; duration?: number; anchored?: boolean } = {},
) => {
  const form = new FormData();
  form.append("file", file, file.name);
  if (claim.shot_n != null) form.append("shot_n", String(claim.shot_n));
  if (claim.model) form.append("model", claim.model);
  if (claim.ratio) form.append("ratio", claim.ratio);
  if (claim.duration != null) form.append("duration", String(claim.duration));
  if (claim.anchored != null) form.append("anchored", claim.anchored ? "1" : "0");
  return apiForm<{ ok: boolean; media_url?: string; [k: string]: unknown }>(`/queue/manual/${id}/clip`, form);
};

/* the in-process job registry (clears on restart, and says so) */
export const listJobs = () => apiFetch<{ items: (Job & { cancellable?: boolean })[] }>("/jobs");
export const cancelJob = (id: number) => apiFetch<Job>(`/jobs/${id}/cancel`, { method: "POST", body: "{}" });
export const clearJob = (id: number) => apiFetch<{ deleted: number }>(`/jobs/${id}`, { method: "DELETE" });
export const queuePending = (brand?: string) =>
  apiFetch<{ items: Concept[]; runway: RunwayState; renderers?: Record<string, RendererSpec> }>(
    `/queue/pending${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`,
  );
/** The pick. Puts a concept in front of the Queue's approval gate;
 *  approving THERE is what renders. */
export const pickConcept = (id: number, picked = true) =>
  apiFetch<{ ok: boolean }>(`/concepts/${id}/pick`, {
    method: "POST",
    body: JSON.stringify({ picked }),
  });

/* ── creating ── */
export type Job = {
  id: number;
  kind: string;
  label: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  detail: string;
  output?: string | null;
  error?: string | null;
  ref_id?: number | null;
  ended_at?: string | null;
};
/** POST /api/scenes/run — multipart: idea, brand, count (1–4), refs
 *  (asset photo urls) and files (uploads), exactly what the Jinja
 *  composer posts. */
export const runScenes = (form: FormData) => apiForm<{ job_id: number }>("/scenes/run", form);
/* One Guide turn. A job, not a plain response: the reasoning tier takes
   tens of seconds. Guarded -- see GUARDED_HEADERS. */
export const runCreativeGuide = (form: FormData) =>
  apiForm<{ job_id: number }>("/creative-guide", form, GUARDED_HEADERS);
export const getJob = (id: number) => apiFetch<Job>(`/jobs/${id}`);
export async function waitForJob(id: number, onTick?: (job: Job) => void, everyMs = 1500) {
  for (;;) {
    const job = await getJob(id);
    onTick?.(job);
    if (["done", "failed", "cancelled"].includes(job.status)) return job;
    await new Promise((r) => setTimeout(r, everyMs));
  }
}

/* ── presets (the camera chips) ── */
export type Preset = { id: string; label: string; how: string };
export const getPresets = () =>
  apiFetch<{ items: Preset[]; enhance_system: string }>("/presets");

/* ── the account switch and sign-out live at the API root ── */
export async function switchAccount(slug: string) {
  const body = new FormData();
  body.append("next", "/studio");
  await fetch(`${API_URL}/brand/${encodeURIComponent(slug)}`, {
    method: "POST",
    credentials: "include",
    body,
    redirect: "manual",
  }).catch(() => {});
  window.location.reload();
}

/* the queue badge listens for this; anything that picks or decides fires it */
export const QUEUE_EVENT = "zpf:queue";
export const announceQueueChange = () =>
  window.dispatchEvent(new Event(QUEUE_EVENT));

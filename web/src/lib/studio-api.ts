/* The studio surfaces' calls into FastAPI, typed against what app/api.py
   returns today. Everything goes through the same-origin proxy
   (next.config.ts rewrites /api, /ui, /brand, the photo routes) so the
   zp_session cookie rides along untouched. Nothing here spends: the
   billed routes (scenes/run, the exec/* nodes) are the same gated ones
   the Jinja shell calls, and Send to Queue only PICKS. */
import { API_URL, ApiError, apiFetch } from "@/lib/api";
import type { AssistantDirection, AssistantQuestion, ContactSheet } from "@/lib/assistant";

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

/* ── settings (2026-10-03): the person's own row and their password ──
   PATCH /api/me renames; the password and email writes each re-prove the
   person (their current password, or a code mailed by sendSecurityCode)
   and the API mints a one-call Supabase session for the write -- nothing
   of Supabase's is kept, and nothing here spends. */
export const updateMe = (display_name: string) =>
  apiFetch<Me>("/me", { method: "PATCH", body: JSON.stringify({ display_name }) });
export type Security = {
  email: string | null;
  /** what the API KNOWS: false also for a password set before it kept track */
  has_password: boolean;
  password_set_at: string | null;
  /** Supabase is wired, so a password or email change can be made */
  can_change: boolean;
  min_password_len: number;
};
export const getSecurity = () => apiFetch<Security>("/me/security");
export const sendSecurityCode = () =>
  apiFetch<{ sent: boolean; email: string }>("/me/security/code", { method: "POST" });
export type Proof = { current_password?: string; code?: string };
export const setPassword = (password: string, password2: string, proof: Proof) =>
  apiFetch<{ ok: boolean } & Security>("/me/password", {
    method: "POST",
    body: JSON.stringify({ password, password2, ...proof }),
  });
export const changeEmail = (email: string, proof: Proof) =>
  apiFetch<{ ok: boolean; pending: string; note: string }>("/me/email", {
    method: "POST",
    body: JSON.stringify({ email, ...proof }),
  });

/* ── what may be drawn ── */
export type Capabilities = Record<string, boolean>;
export const getCapabilities = () => apiFetch<Capabilities>("/capabilities");

/* ── assets (elements) ── */
export type AssetCategory = "character" | "location" | "prop";
export type Asset = {
  id: string;
  /** the studio's own rendered stills come back as "generated" beside the
   *  three element kinds (app/api.py _assets_all) */
  category: AssetCategory | "generated";
  name: string;
  photos: string[];
  poster: string | null;
  /** the drawn reference sheet, when one exists — always LAST in `photos` (2026-09-18) */
  sheet?: string | null;
  text: string;
  meta: Record<string, unknown>;
  created_at?: string | null;
  /** how many open concepts' refs name this element (scope=elements only,
   *  counted server-side through asset_shelf.parse_ref, 2026-09-25) */
  used_in?: number;
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
  /* a clip's still (2026-09-28): its t/ derivative, when R2 has one */
  poster?: string | null;
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
export type KeyframeQuote = { stills: number; each: number; credits: number };
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
  /** pricing.display for the card's default pick (GET /api/queue/pending) */
  quote?: RenderQuote;
  /* the rest of app/api.py's _concept_card, read by the image-first cards */
  hook?: string | null;
  card_line?: string;
  warnings?: string[];
  graded?: boolean;
  shot_done?: boolean;
  subscription?: boolean;
  tool?: string;
  /** Queue only: why the reference gate refuses this card ("" when it can
   *  be approved). Listed so a pick does not look lost; never approvable. */
  blocked?: string;
  /** where each reference came from, parallel to `refs` (app/api.py _ref_sources) */
  ref_sources?: import("./refs").RefSource[];
  /** the drawable size of each reference, parallel to `refs` (app/api.py
   *  _ref_thumbs, BACKLOG #0). `refs` stays the master: refs[0] anchors the render. */
  ref_thumbs?: string[];
  /** the prompt gate's own verdict (autonomy.gates_for_concepts), or null
   *  when no graph run ever ended on this concept -- never scored, NOT a
   *  pass. `passed` is what the gate said, not whether the run went on. */
  gate?: {
    score: number | null;
    passed: boolean | null;
    reason: string;
    reworks: number;
    status: string;
    outcome: string;
  } | null;
  /** the timed shots a scene renders as, or null for one that renders whole */
  timeline?: Timeline | null;
  /** what drawing this scene's keyframes would cost; null when nothing to draw (2026-09-29) */
  keyframes?: KeyframeQuote | null;
};
export type TimelinePart = {
  n: number;
  start: number;
  end: number;
  seconds: number;
  text?: string | null;
  prompt?: string | null;
  refs?: string[] | null;
  /** parallel to `refs`, the card rule (app/api.py _ref_thumbs) */
  ref_thumbs?: string[] | null;
  reference_image?: string | null;
  media_url?: string | null;
};
export type Timeline = { planned: boolean; seconds?: number | null; parts: TimelinePart[] };
export type RendererModel = { id: string; label: string; usd_per_second: number };
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
/** The default video renderer's state (app/api.py `_render_state`): fal.ai
 *  since 2026-09-26, the only video renderer. What the chips and older
 *  cards read; `renderers` is the full catalogue. */
export type RendererState = {
  label: string;
  provider: string;
  available: boolean;
  spend_ok: boolean;
  model: string;
  estimate_usd: number;
  duration?: number;
  resolution?: string;
  models?: RendererModel[];
  durations?: number[];
  today?: number | null;
};
/** src/pricing.py `display()` — the priced plan for one approve, or for
 *  the Director's Generate node: every render it would make, at what
 *  length, the provider's estimate and the credits it holds (every video
 *  render holds credits since 2026-09-26). `{error}` when the intent has no
 *  price. The server is the only place a price is computed. */
export type RenderQuote = {
  error?: string;
  provider: string;
  model: string;
  frame: string;
  timed: boolean;
  durations: number[];
  estimate_usd: number;
  credits: number | null;
  content_hash: string;
  /** tokens ride only when there is something to charge and QUOTE_SIGNING_SECRET is set */
  signed: boolean;
  renders: { part: number | null; seconds: number; estimate_usd: number; credits: number | null; token: string | null }[];
};
/** what approve takes: providers.check_render_choice refuses, never clamps */
export type RenderChoice = { provider?: string; model?: string; duration?: number; frame?: string; tokens?: string[] };
export type RenderResolved = { provider: string; model: string; duration: number; frame: string; estimate_usd: number };
export type PickRate = { generated: number; picked: number; rate: number | null };
/** The board's count line, counted on the server over the same window:
 *  scenes only; `picked` is open-and-picked (the Picked filter). */
export type BoardCounts = { open: number; picked: number; archived: number };
/** GET /api/pipeline/concepts — the board. `open` (the default) is the
 *  open cards; `archived` is the archived half of the same window, asked
 *  for only when the Archived filter is opened (2026-09-25). Either way
 *  `counts` says where every card went (the 2026-09-02 lesson) without
 *  the archived cards being fetched to count them. */
export const boardConcepts = (
  brand?: string,
  shelf: "open" | "archived" | "all" = "open",
  project?: number,
) => {
  const params = new URLSearchParams();
  if (brand) params.set("brand", brand);
  if (shelf === "archived") params.set("view", "archived");
  // "all" is both halves of the window in one read -- a project's page
  // lists every scene it holds, passed ones included (2026-09-28)
  if (shelf === "all") params.set("archived", "true");
  if (project) params.set("project", String(project));
  const qs = params.toString();
  return apiFetch<{ items: Concept[]; counts: BoardCounts; pick?: PickRate }>(
    `/pipeline/concepts${qs ? `?${qs}` : ""}`,
  );
};
/** GET /api/pipeline/arrival — the ONE scene the Director opens on, or
 *  null. The rule (app/api.py `_arrival`) lives on the server so the page
 *  asks for an id, not the whole board (2026-09-25). */
export const directorArrival = (brand?: string) =>
  apiFetch<{ id: number | null }>(`/pipeline/arrival${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`);
/** A line in the Director's scene switcher: the openable board rows only
 *  (`?view=menu`), no card, gates or sources. */
export type SceneMenuRow = {
  id: number;
  n: string;
  title: string | null;
  brand: string;
  picked: boolean;
  parked: boolean;
  has_media: boolean;
};
export const sceneMenu = (brand?: string) => {
  const params = new URLSearchParams({ view: "menu" });
  if (brand) params.set("brand", brand);
  return apiFetch<{ items: SceneMenuRow[] }>(`/pipeline/concepts?${params}`);
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
/* the spend gate: approving is what calls the renderer (fal) */
export const queueApprove = (id: number, choice?: RenderChoice) =>
  apiFetch<{ job_id?: number; render?: RenderResolved; quote?: RenderQuote | null }>(`/queue/${id}/approve`, {
    method: "POST",
    body: JSON.stringify(choice ?? {}),
  });
/** what approving WITH THIS PICK would render and cost — the server's
 *  own price; spends nothing. The Queue asks when a pick differs from the
 *  one the listing already priced. */
export const queueQuote = (id: number, choice: RenderChoice) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(choice)) if (v !== undefined && v !== null) q.set(k, String(v));
  return apiFetch<RenderQuote>(`/queue/${id}/quote?${q}`);
};
export const queueReject = (id: number) =>
  apiFetch<{ ok: boolean }>(`/queue/${id}/reject`, { method: "POST", body: "{}" });
/** made by hand, outside the render lane — drops it off the pending list */
export const queueShot = (id: number) =>
  apiFetch<{ ok: boolean }>(`/queue/${id}/shot`, { method: "POST", body: JSON.stringify({ shot: true }) });
/* ── the manual import lane (operator-gated server-side; the `manual_lane`
   capability only says whether to draw the section): a clip rendered
   anywhere, dropped on its card and filed free ── */
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
 *  hands; a 404 for an account the lane is not open for. There is no model
 *  list: what rendered the clip is free text on the drop. */
export const queueManual = (brand?: string) =>
  apiFetch<{ items: LaneItem[]; lane?: string; import_with?: string }>(
    `/queue/manual${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`,
  );
/** POST /api/queue/manual/{id}/clip — the finished mp4, filed by
 *  ops/render_queue.import_clip as a FREE row. `model` is free text (what
 *  rendered it; the server says "unspecified" when absent); a second drop
 *  is refused (409). */
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

/** POST /api/refs/upload — reference photos from disk into the shared
 *  bin (JPEG-normalised, content-addressed, mirrored to R2); returns the
 *  URLs to put on a reference card. */
export const uploadRefs = (files: File[]) => {
  const form = new FormData();
  for (const f of files) form.append("photos", f, f.name);
  return apiForm<{ urls: string[]; skipped: number }>("/refs/upload", form);
};

/* the cut (Assemble v0, docs/tasks/CUT_ASSEMBLE_V0.md): a rendered scene's
   clips -> a versioned timeline -> one MP4. Nothing here spends. */
export type CutReady = {
  concept_id: number;
  title: string;
  brand?: string | null;
  clips: number;
  poster?: string | null;
  export: { timeline_id: number; version: number; url: string | null } | null;
};
/** GET /api/cut/ready — scenes whose every shot has a clip, not archived. */
export const cutReady = (brand?: string) =>
  apiFetch<{ ready: CutReady[]; ffmpeg: boolean; captions_burn: boolean }>(
    `/cut/ready${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`,
  );
/** POST /api/cut/assemble — a job; its result carries mp4_url + version.
 *  `music` / `voice` are asset:<id> handles from cutUploadMedia. A scene
 *  that is not ready is refused (409) before any job starts. */
export const cutAssemble = (concept_id: number, opts: { music?: string; voice?: string; captions?: string } = {}) =>
  apiFetch<{ job_id: number; clips: number; notes: string[] }>("/cut/assemble", {
    method: "POST",
    body: JSON.stringify({ concept_id, ...opts }),
  });
/** POST /api/cut/media — an uploaded music bed or voiceover -> asset:<id>. */
export const cutUploadMedia = (file: File) => {
  const form = new FormData();
  form.append("file", file, file.name);
  return apiForm<{ handle: string; seconds: number; filename: string }>("/cut/media", form);
};

/* the in-process job registry (clears on restart, and says so) */
export const listJobs = () => apiFetch<{ items: (Job & { cancellable?: boolean })[] }>("/jobs");
export const cancelJob = (id: number) => apiFetch<Job>(`/jobs/${id}/cancel`, { method: "POST", body: "{}" });
export const clearJob = (id: number) => apiFetch<{ deleted: number }>(`/jobs/${id}`, { method: "DELETE" });
export const queuePending = (brand?: string) =>
  apiFetch<{ items: Concept[]; spendable?: number; renderer: RendererState; renderers?: Record<string, RendererSpec> }>(
    `/queue/pending${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`,
  );
/** GET /api/queue/count -- the rail badge's number and nothing else. The
 *  listing prices every card (signed quotes, a default and the renderer
 *  state per request), which is seconds of work the badge never needed
 *  and used to repeat on every studio page. */
export const queueCount = (brand?: string) =>
  apiFetch<{ spendable: number; blocked: number }>(
    `/queue/count${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`,
  );
/** The pick. Puts a concept in front of the Queue's approval gate;
 *  approving THERE is what renders. */
/** The priced approve for a scene's keyframes (2026-09-29): nothing is
 *  drawn until this is pressed. 402 out_of_credits when the whole strip
 *  does not fit the balance. */
export const drawKeyframes = (id: number) =>
  apiFetch<{ ok: boolean; job_id: number | null; keyframes: KeyframeQuote }>(`/concepts/${id}/keyframes`, {
    method: "POST",
  });

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
  /** a finished cut job (/api/cut/assemble) */
  mp4_url?: string | null;
  version?: number | null;
  /** an editor export (2026-10-01): what it made, and where */
  format?: "mp4" | "audio" | "still" | "project";
  file_url?: string | null;
  otio_url?: string | null;
  srt_url?: string | null;
};
/** POST /api/scenes/run — multipart: idea, brand, count (1–4), refs
 *  (asset photo urls) and files (uploads), exactly what the Jinja
 *  composer posts. */
export const runScenes = (form: FormData) => apiForm<{ job_id: number }>("/scenes/run", form);
/* One Guide turn. A job, not a plain response: the reasoning tier takes
   tens of seconds. Guarded -- see GUARDED_HEADERS. */
export const runCreativeGuide = (form: FormData) =>
  apiForm<{ job_id: number }>("/creative-guide", form, GUARDED_HEADERS);
/* What a Guide turn comes back with (src/creative_guide.Reply). A
   `proposal` is a WRITE the model asked for and nobody has run: the
   thread draws it as a confirm card and the click is runGuideAction.
   `tool_runs` are the READ tools it looked at before answering. */
export type GuideProposal = {
  tool: string;
  args: Record<string, unknown>;
  label: string;
  /** add_element (2026-10-03): the references the turn was handed, stamped by
   *  the route -- the photos the click saves. The model's args carry no URL. */
  photos?: string[];
};
/** what an add_element click made (src: app/api.py _element_from_guide) */
export type GuideElement = {
  kind: string;
  name: string;
  slug: string;
  photos: string[];
  sheet_job?: number | null;
  note?: string | null;
};
export type GuideToolRun = { tool: string; args: Record<string, unknown>; ok: boolean };
export type GuideReply = {
  message: string;
  choices?: string[];
  brief?: string;
  proposal?: GuideProposal | null;
  tool_runs?: GuideToolRun[];
  /* the assistant pill's fields (assistant=1 on the form; src/lib/assistant.ts
     has their shapes). A plain Guide turn answers them empty. */
  questions?: AssistantQuestion[];
  directions?: AssistantDirection[];
  nudge?: string;
  stage?: string;
  sheet?: ContactSheet | null;
};
/* POST /api/creative-guide/act -- the confirm card's click, and the
   ONLY thing that runs a write tool. Guarded like the turn. The server
   re-checks the tool set and refuses any URL in the arguments. */
export const runGuideAction = (proposal: GuideProposal) =>
  apiFetch<{ ok: boolean; tool: string; result: string; element?: GuideElement }>("/creative-guide/act", {
    method: "POST",
    headers: GUARDED_HEADERS,
    body: JSON.stringify({
      tool: proposal.tool,
      args: proposal.args,
      ...(proposal.photos?.length ? { photos: proposal.photos } : {}),
    }),
  });
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
/** POST /brand/{slug} THROUGH THE PROXY (API_URL is empty in production, so
 *  this is our own origin and the `brand` cookie lands first-party -- the
 *  handoff lesson). The route answers 303; `manual` keeps fetch from
 *  following it into a page nobody reads. Resolves once the cookie is set;
 *  the caller refetches /api/me, which is what says the switch took. */
export async function switchAccount(slug: string) {
  const body = new FormData();
  body.append("next", "/studio");
  await fetch(`${API_URL}/brand/${encodeURIComponent(slug)}`, {
    method: "POST",
    credentials: "include",
    body,
    redirect: "manual",
  });
}

/* the queue badge listens for this; anything that picks or decides fires it */
export const QUEUE_EVENT = "zpf:queue";
export const announceQueueChange = () =>
  window.dispatchEvent(new Event(QUEUE_EVENT));

/* ── credits (2026-09-25) ──
   GET /api/billing/balance -- src/billing.balance, the numbers the shell's
   credit pill and the Queue read. `available` is spendable NOW (lots minus
   holds still outstanding); `outstanding` is what renders in flight hold.
   `exempt` is an operator account the ledger never charges: its pill says
   so instead of a number that would never move. `portal` = a Stripe
   customer exists, so "Manage billing" has somewhere to go. */
export type CreditLot = {
  id: number;
  kind: string;
  credits: number;
  remaining: number;
  granted_at: string;
  expires_at: string | null;
};
export type Balance = {
  available: number;
  outstanding: number;
  plan: { key: string; name: string; tier: string; credits: number; monthly_usd: number } | null;
  exempt: boolean;
  lots: CreditLot[];
  schedules: { plan: string; months_released: number; months_total: number; next_release_at: string | null }[];
  checkout_configured: boolean;
  yearly_configured: boolean;
  portal: boolean;
  /** what a still costs on THIS server (app/billing.action_prices) */
  prices?: { still: number };
};
export const getBalance = () => apiFetch<Balance>("/billing/balance");
/** fired after anything that moves credit: an approve takes a hold, a
 *  finished render settles it. The shell re-reads the balance on it. */
export const BALANCE_EVENT = "zpf:balance";
export const announceBalanceChange = () => window.dispatchEvent(new Event(BALANCE_EVENT));

/* ── projects (2026-09-28) ──
   One brief and one memory per piece of work (src/projects.py). The
   memory is what the project LEARNED -- picks, passes with their reason,
   hand edits -- and every Create inside the project is written against
   the brief plus that memory, which is how its renders stay consistent. */
export type ProjectMemory = {
  kind: "pick" | "pass" | "edit" | "note";
  text: string;
  concept_id: number | null;
  at: string;
};
export type Project = {
  id: number;
  title: string;
  brief: string;
  memory: ProjectMemory[];
  archived: boolean;
  created_at: string;
  updated_at: string;
  concepts?: number;
  picked?: number;
  rendered?: number;
};
export type ProjectQuestion = { key: string; label: string };
export const listProjects = (archived = false) =>
  apiFetch<{ items: Project[]; questions: ProjectQuestion[] }>(
    `/projects${archived ? "?archived=true" : ""}`,
  );
export const getProject = (id: number) => apiFetch<Project>(`/projects/${id}`);
export const createProject = (title: string, brief: string) =>
  apiFetch<Project>("/projects", { method: "POST", body: JSON.stringify({ title, brief }) });
export const updateProject = (id: number, patch: { title?: string; brief?: string }) =>
  apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
export const archiveProject = (id: number, archived = true) =>
  apiFetch<{ ok: boolean }>(`/projects/${id}/archive`, {
    method: "POST",
    body: JSON.stringify({ archived }),
  });
export const forgetProjectMemory = (id: number, at: string) =>
  apiFetch<{ ok: boolean; removed: boolean }>(`/projects/${id}/forget`, {
    method: "POST",
    body: JSON.stringify({ at }),
  });
export const draftProjectBrief = (title: string, answers: Record<string, string>) =>
  apiFetch<{ brief: string }>("/projects/draft-brief", {
    method: "POST",
    body: JSON.stringify({ title, answers }),
  });

/* The project the Studio composer is writing inside. Carried as ?project=
   from the Projects page and remembered per browser so a reload keeps it;
   clearing it is one click on the composer's chip. */
export const ACTIVE_PROJECT_KEY = "zp.project";
export function rememberActiveProject(id: number | null) {
  try {
    if (id) localStorage.setItem(ACTIVE_PROJECT_KEY, String(id));
    else localStorage.removeItem(ACTIVE_PROJECT_KEY);
  } catch {
    /* private window: the ?project= param still works */
  }
}
export function recallActiveProject(): number | null {
  try {
    const v = Number(localStorage.getItem(ACTIVE_PROJECT_KEY));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

/* ── the composer's IMAGE output (2026-10-02) ──
   POST /api/generate/run, output=image: preset + prompt + the same two
   reference fields Create sends (`files`, `asset_photos`) -> one Nano
   Banana still saved as a one-shot concept. Not mutation_header-guarded
   (the Create route beside it is not either). `aspect` is optional and
   allowlisted server-side. */
export const runImage = (form: FormData) =>
  apiForm<{ job_id: number; image_refs: number; video_refs: number }>("/generate/run", form);

/** GET /api/concepts/{id} — the card plus its shots; the composer reads
 *  the still off the card (reference_image) or the scene's timeline. */
export type ConceptDetail = Concept & {
  duration?: number | null;
  shots?: { n: number; reference_image?: string | null; timeline?: Timeline | null }[];
};
export const getConceptDetail = (id: number) => apiFetch<ConceptDetail>(`/concepts/${id}`);

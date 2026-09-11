/**
 * The one place this app talks to the studio backend.
 *
 * Every screen imports from here and nothing else calls fetch, so wiring
 * the frontend to FastAPI later is a change to this file rather than a
 * hunt through components. While `USE_FIXTURES` is on, the same
 * functions answer from src/lib/fixtures.ts -- so the UI is built and
 * reviewed without the Python server running, and switching over is one
 * flag rather than a rewrite.
 *
 * The shapes below are the ones app/api.py actually returns today; where
 * a field does not exist server-side yet it is marked, so nobody builds
 * a screen on a promise.
 */
import { FIXTURES } from './fixtures'

// Opt-IN since the backend was wired (2026-09-10). The default is the
// real API; VITE_USE_FIXTURES=true is for working on a screen with no
// Python server running, and it is now the unusual case rather than the
// normal one.
export const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === 'true'

export class ApiError extends Error {
  // Plain fields, not constructor parameter properties: the app's
  // tsconfig sets erasableSyntaxOnly, so every TS construct here has to
  // survive being stripped rather than compiled.
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })
  if (!res.ok) {
    // app/api.py's _error() shape: {error: {code, message}}
    const body = await res.json().catch(() => null)
    throw new ApiError(
      body?.error?.message ?? `${res.status} ${res.statusText}`,
      res.status,
      body?.error?.code,
    )
  }
  return res.json() as Promise<T>
}

/* ── which model writes ───────────────────────────────────────────── */
/** GET /api/brains -- a projection of src/gemini_utils.py BRAINS. */
export interface Brain {
  id: string
  label: string
  note: string
  default: boolean
}

export async function getBrains(): Promise<{ brains: Brain[]; default: string }> {
  if (USE_FIXTURES) return FIXTURES.brains
  return request('/api/brains')
}

/* ── how long a scene is ──────────────────────────────────────────── */
/** GET /api/scene-lengths -- src/timeline.py SCENE_SECONDS_CHOICES. */
export async function getSceneLengths(): Promise<{ choices: number[]; default: number }> {
  if (USE_FIXTURES) return FIXTURES.sceneLengths
  return request('/api/scene-lengths')
}

/* ── what the shell may draw ──────────────────────────────────────── */
/** GET /api/capabilities -- derived live from keys and reachability,
 *  never a static dict. Keys are dotted: 'pipeline.run', 'scout', … */
export type Capabilities = Record<string, boolean | unknown>

export async function getCapabilities(): Promise<Capabilities> {
  if (USE_FIXTURES) return FIXTURES.capabilities
  return request('/api/capabilities')
}

/* ── the frame a scene is written for ─────────────────────────────── */
/** GET /api/render-choices -- a projection of src/render_specs.py.
 *  There is no separate resolution: a ratio here IS a frame size. */
export interface RatioChoice {
  id: string
  label: string
  size: string
}

export async function getRenderChoices(): Promise<{ ratios: RatioChoice[]; default: string }> {
  if (USE_FIXTURES) return FIXTURES.renderChoices
  return request('/api/render-choices')
}

/* ── creating scenes ──────────────────────────────────────────────── */
export interface CreateSceneInput {
  idea: string
  brand?: string
  brain?: string
  seconds?: number
  /** Stored on the scene's shot, so the Queue card defaults to it. The
   *  route REFUSES a size the renderers do not take rather than
   *  clamping it -- a silently corrected frame is a clip that comes back
   *  the wrong shape. */
  ratio?: string
  scoutFindingId?: number
  files?: File[]
  assetPhotos?: string[]
}

export interface JobStarted {
  job_id: string
  image_refs?: number
  brain?: string
}

/** POST /api/scenes/run -- multipart, because the composer can attach
 *  both freshly uploaded photos and ones picked from the asset bank. */
export async function createScenes(input: CreateSceneInput): Promise<JobStarted> {
  if (USE_FIXTURES) return FIXTURES.jobStarted
  const body = new FormData()
  body.append('idea', input.idea)
  if (input.brand) body.append('brand', input.brand)
  if (input.brain) body.append('brain', input.brain)
  if (input.seconds) body.append('seconds', String(input.seconds))
  if (input.ratio) body.append('ratio', input.ratio)
  if (input.scoutFindingId) body.append('scout_finding_id', String(input.scoutFindingId))
  input.files?.forEach((f) => body.append('files', f))
  input.assetPhotos?.forEach((u) => body.append('asset_photos', u))
  return request('/api/scenes/run', { method: 'POST', body })
}

/* ── the creative guide ───────────────────────────────────────────── */
export interface GuideMessage {
  role: 'user' | 'assistant'
  /** `content`, not `text`: src/creative_guide.py's Message model names
   *  it that, and the server validates the shape. */
  content: string
}

export interface GuideReply {
  message: string
  choices: string[]
  brief: string
}

/** POST /api/creative-guide -- one turn, as a job.
 *
 *  The X-ZPF-Model-Connection header is not decoration: a studio session
 *  is SameSite=None, so the server refuses a post without it to stop a
 *  cross-site form spending a personal model connection.
 *
 *  A 409 means the chosen personal provider is not connected — the
 *  caller should offer the studio assistant instead of retrying. */
export async function askGuide(
  conversation: GuideMessage[],
  opts: { brand?: string; provider?: string; model?: string; idea?: string } = {},
): Promise<JobStarted> {
  if (USE_FIXTURES) return FIXTURES.jobStarted
  const body = new FormData()
  body.append('conversation', JSON.stringify({ messages: conversation }))
  if (opts.brand) body.append('brand', opts.brand)
  body.append('guide_provider', opts.provider || 'gemini')
  if (opts.model) body.append('guide_model', opts.model)
  if (opts.idea) body.append('idea', opts.idea)
  return request('/api/creative-guide', {
    method: 'POST',
    body,
    headers: { 'X-ZPF-Model-Connection': '1' },
  })
}

/* ── jobs ─────────────────────────────────────────────────────────── */
export interface Job {
  id: string
  status: string
  detail?: string
  error?: string
  progress?: number
  ref_id?: number | null
  /** whatever the worker returned is folded into the finished job */
  reply?: GuideReply
  reference_urls?: string[]
}

const TERMINAL = ['done', 'failed', 'cancelled', 'error']

/** Poll until the job stops. A 404 means the registry lost it — it is
 *  in-process and a restart clears it — so that is "gone", not "failed",
 *  and it is worth saying so rather than showing a stall. */
export async function waitForJob(
  id: string,
  onTick?: (job: Job) => void,
  intervalMs = 1200,
): Promise<Job> {
  for (;;) {
    const job = await getJob(id)
    onTick?.(job)
    if (TERMINAL.includes(job.status)) return job
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/** GET /api/jobs/{id}. The registry is in-process and a restart clears
 *  it, so a poll that 404s means "gone", not "failed". */
export async function getJob(id: string): Promise<Job> {
  if (USE_FIXTURES) return FIXTURES.job
  return request(`/api/jobs/${encodeURIComponent(id)}`)
}

/* ── who is signed in ─────────────────────────────────────────────── */
/** GET /api/me -- composed from auth.current_user, auth.current_account
 *  and accounts.memberships. `accounts` is the membership list, which is
 *  what the brand switcher may offer: the cookie is a preference among
 *  brands you belong to, never a grant. */
export interface Membership {
  slug: string
  display_name: string
  role: string
}

export interface Me {
  email: string
  display_name: string
  avatar_url?: string | null
  account: Membership
  accounts: Membership[]
}

export async function getMe(): Promise<Me> {
  if (USE_FIXTURES) return FIXTURES.me
  return request('/api/me')
}

/** POST /brand/{name} -- app/main.py. The `brand` cookie is a preference
 *  among accounts you already belong to, never a grant: the server
 *  re-checks membership. Not under /api, and it answers with a redirect
 *  rather than JSON, so this reloads instead of parsing a body. */
export async function setBrand(name: string): Promise<void> {
  if (USE_FIXTURES) return
  await fetch(`/brand/${encodeURIComponent(name)}`, {
    method: 'POST',
    credentials: 'same-origin',
  })
  window.location.reload()
}

/** POST /logout -- app/auth.py. Clears the zp_session cookie. */
export async function logout(): Promise<void> {
  if (USE_FIXTURES) return
  await fetch('/logout', { method: 'POST', credentials: 'same-origin' })
  window.location.assign('/signin')
}

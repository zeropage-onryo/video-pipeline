/* The assistant pill's client half (2026-09-26, ASSISTANT_HANDOFF.md
   step 2). The brain is src/assistant_brain.py behind the same
   POST /api/creative-guide the composer's Guide mode posts; this file is
   what the floating pill needs on top of studio-api.ts's Guide helpers:

   - the persona (a name, an emoji, one of three tones), kept per account
     in localStorage until an `assistants` table exists;
   - the seven steps and which one a page sits on;
   - the bridge to the Studio composer. The pill floats over every page
     and the composer's state lives inside studio/page.tsx, so the two
     talk in window events, and a fill asked for from another page waits
     in sessionStorage until the composer mounts. The assistant only ever
     FILLS the box; Create stays the person's click. */
import { apiFetch } from "@/lib/api";
import { GUARDED_HEADERS } from "@/lib/studio-api";

export const STAGES = ["brief", "story", "cast", "references", "shots", "stills", "clips"] as const;
export type Stage = (typeof STAGES)[number];
export const STAGE_LABEL: Record<Stage, string> = {
  brief: "Brief",
  story: "Story",
  cast: "Cast",
  references: "References",
  shots: "Shots",
  stills: "Stills",
  clips: "Clips",
};

/* Where a page sits in the seven. The conversation's own step wins
   unless the page is further along (opening the Queue means clips). */
const PAGE_STAGE: [string, Stage][] = [
  ["/studio/queue", "clips"],
  ["/studio/assets", "stills"],
  ["/studio/flows", "shots"],
  ["/studio/references", "references"],
  ["/studio/elements", "cast"],
  ["/studio/pipeline", "story"],
  ["/studio", "brief"],
];
export const pageStage = (path: string): Stage =>
  PAGE_STAGE.find(([p]) => path.startsWith(p))?.[1] ?? "brief";
export const PAGE_NAME: [string, string][] = [
  ["/studio/queue", "Queue"],
  ["/studio/assets", "Assets"],
  ["/studio/flows", "Director"],
  ["/studio/references", "References"],
  ["/studio/elements", "Elements"],
  ["/studio/pipeline", "Pipeline"],
  ["/studio", "Studio"],
];
export const pageName = (path: string) => PAGE_NAME.find(([p]) => path.startsWith(p))?.[1] ?? "Studio";
export const isStage = (s: unknown): s is Stage => STAGES.includes(s as Stage);
export const laterStage = (a: Stage | "", b: Stage): Stage =>
  a && STAGES.indexOf(a) > STAGES.indexOf(b) ? a : b;

/* ── persona ── */
export type Tone = "direct" | "friendly" | "hype";
export const TONES: { id: Tone; label: string }[] = [
  { id: "direct", label: "Straight to the point" },
  { id: "friendly", label: "Friendly" },
  { id: "hype", label: "Hype" },
];
export const AVATARS = ["🦊", "🤖", "🎬", "👾", "🐺"];
export type Persona = { name: string; avatar: string; tone: Tone };

const personaKey = (account: string) => `zpf.assistant.${account || "default"}`;
export function loadPersona(account: string): Persona | null {
  try {
    const raw = localStorage.getItem(personaKey(account));
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<Persona>;
    if (!p.name || !p.avatar) return null;
    return { name: p.name, avatar: p.avatar, tone: TONES.some((t) => t.id === p.tone) ? (p.tone as Tone) : "direct" };
  } catch {
    return null;
  }
}
export function savePersona(account: string, p: Persona) {
  try {
    localStorage.setItem(personaKey(account), JSON.stringify(p));
  } catch {
    /* private window: the pill asks again next visit */
  }
}
/* The server keeps letters, digits, spaces, ' and - (assistant_brain.clean_name);
   trimming the same way here means the pill says the name the model was given. */
export const cleanName = (s: string) =>
  s.replace(/[^A-Za-z0-9 '\-]/g, "").replace(/\s+/g, " ").trim().slice(0, 24);
/* the first grapheme of whatever was typed -- one emoji, flags and ZWJ families included */
export function firstEmoji(s: string): string {
  const t = s.trim();
  if (!t) return "";
  try {
    const seg = new Intl.Segmenter(undefined, { granularity: "grapheme" });
    for (const { segment } of seg.segment(t)) return segment;
  } catch {
    /* no Segmenter: fall through */
  }
  return Array.from(t)[0] ?? "";
}

/* ── what a turn comes back with, on top of GuideReply ── */
export type AssistantQuestion = { ask: string; options: string[] };
export type AssistantDirection = {
  title: string;
  logline: string;
  turn?: string;
  /** story_judge's 0..1, null when the judge could not run */
  score?: number | null;
  verdict?: string;
};
export type SheetFrame = {
  id: string;
  image_url: string;
  source_url: string;
  source: string;
  title: string;
  kept_for: string;
  why: string;
  flags: string[];
};
export type SheetNeed = { role: string; query: string; keepers: SheetFrame[]; rejected: SheetFrame[]; note: string };
export type ContactSheet = { ok: boolean; sheet: SheetNeed[]; checked: boolean; note: string; faces?: number };

/* POST /api/creative-guide/act {tool: keep_references}: the Keep click.
   Copies the chosen frames into /refs and answers the paths the composer
   sends as `asset_photos`. Ids only -- the server refuses one it never
   served. Costs no credits. */
export type Kept = { id: string; url: string; source_url?: string; title?: string };
export const keepReferences = (ids: string[]) =>
  apiFetch<{ ok: boolean; tool: string; result: { kept: Kept[]; refused: { id: string; error: string }[] } }>(
    "/creative-guide/act",
    {
      method: "POST",
      headers: GUARDED_HEADERS,
      body: JSON.stringify({ tool: "keep_references", args: { candidate_ids: ids } }),
    },
  );


/* ── the composer bridge ── */
export const FILL_EVENT = "zpf:assistant-fill";
export const COMPOSER_EVENT = "zpf:composer-state";
const PENDING_KEY = "zpf.assistant.pending";
export type Fill = { text?: string; refs?: string[]; by: string; avatar?: string };
export type ComposerState = { idea: string; picked: string[] };

/* Ask the composer to take this. When it is mounted it takes it at once;
   otherwise it is waiting in sessionStorage for the next mount. */
export function sendToComposer(fill: Fill) {
  try {
    const was = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null") as Fill | null;
    const merged: Fill = {
      by: fill.by,
      text: fill.text ?? was?.text,
      refs: [...new Set([...(was?.refs ?? []), ...(fill.refs ?? [])])],
    };
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(merged));
  } catch {
    /* no storage: the event below still reaches a mounted composer */
  }
  window.dispatchEvent(new CustomEvent<Fill>(FILL_EVENT, { detail: fill }));
}
/* The composer calls this on mount and on every FILL_EVENT: whatever is
   waiting, once. */
export function takePendingFill(): Fill | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    sessionStorage.removeItem(PENDING_KEY);
    return raw ? (JSON.parse(raw) as Fill) : null;
  } catch {
    return null;
  }
}
export const announceComposer = (state: ComposerState) =>
  window.dispatchEvent(new CustomEvent<ComposerState>(COMPOSER_EVENT, { detail: state }));

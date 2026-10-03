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
import { GUARDED_HEADERS, type GuideReply } from "@/lib/studio-api";
import type { Made } from "@/lib/composer";

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
  /** which rubric graded it: "ad" (story_judge.judge_ad) or "story" */
  rubric?: string;
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

/* ── ONE conversation, two views (2026-10-02) ──
   The pill and the Studio composer's Guide used to hold separate threads,
   and the composer's lived only in its page's React state: clicking to
   another tab lost the talk and every frame a hunt had drawn. Both now read
   and write the one thread components/studio/assistant-thread.tsx holds,
   so a turn asked in the box is there when the pill opens on Pipeline, and
   the other way round. A Turn is the union of what either surface writes;
   each draws what it knows and leaves the rest alone. */
export type Turn = {
  role: "user" | "assistant";
  content: string;
  /** the guide never answered: drawn on the bubble, dropped from the next turn */
  failed?: boolean;
  /** an assistant turn's extras -- chips, directions, brief, proposal, the contact sheet */
  reply?: GuideReply;
  /** the sheet's frames as the person has them chosen (default: what the check kept) */
  chosen?: Record<string, boolean>;
  /** Keep has run for this sheet */
  kept?: boolean;
  /** the pill: the direction put in the composer */
  picked?: number;
  /** the pill: its next-move line after a local step (a keep, a pick) */
  nudge?: string;
  /** the composer: which board tools the guide looked at before this answer */
  looked?: string[];
  /** the composer: the proposal's confirm card has been decided */
  decided?: "done" | "skipped";
  /** the composer (2026-10-02): this user turn was a SEND, and what it made
   *  (lib/composer.ts). The pill leaves these turns out of its card and of
   *  the conversation it sends: they are the box's, not the Guide's. */
  made?: Made;
};

/* The composer's box, saved beside the thread so leaving the page keeps
   it: the idea, the guide's brief, references (picks by URL, uploads by
   the bin URL they were saved under), the mode, the "scene written" card.
   Mirrors src/assistant_store._clean_draft -- the server bounds every
   field and answers this exact shape. */
export type UploadRef = { url: string; name: string };
export type ComposerDraft = {
  idea: string;
  brief: string;
  mode: "guide" | "create";
  picked: string[];
  uploads: UploadRef[];
  written: { conceptId: number | null; detail: string } | null;
};
/* Create is the default (2026-10-02, the composer mock): the box makes;
   the Guide is a toggle beside Image | Video. */
export const EMPTY_DRAFT: ComposerDraft = { idea: "", brief: "", mode: "create", picked: [], uploads: [], written: null };
export const draftHasContent = (d: ComposerDraft | null | undefined) =>
  !!d && !!(d.idea.trim() || d.brief.trim() || d.picked.length || d.uploads.length || d.written);
/* whatever came back, in the shape the page can trust */
export function asDraft(raw: unknown): ComposerDraft {
  const d = (raw && typeof raw === "object" ? raw : {}) as Partial<ComposerDraft>;
  return {
    idea: typeof d.idea === "string" ? d.idea : "",
    brief: typeof d.brief === "string" ? d.brief : "",
    mode: d.mode === "guide" ? "guide" : "create",
    picked: Array.isArray(d.picked) ? d.picked.filter((u): u is string => typeof u === "string") : [],
    uploads: Array.isArray(d.uploads)
      ? d.uploads.filter((u): u is UploadRef => !!u && typeof u === "object" && typeof (u as UploadRef).url === "string")
      : [],
    written:
      d.written && typeof d.written === "object"
        ? { conceptId: typeof d.written.conceptId === "number" ? d.written.conceptId : null, detail: String(d.written.detail ?? "") }
        : null,
  };
}

/* ── what the server remembers (2026-09-29, src/assistant_store.py) ──
   The persona and the open project used to live only in this browser, so a
   closed tab lost the thread. localStorage/sessionStorage stay as a fast
   first paint and an offline fallback; the server's copy wins on load. */
export type SavedProject = {
  id: number;
  title: string;
  stage: string;
  turns: unknown[];
  /** the composer's box (2026-10-02); older servers answer none */
  draft?: unknown;
  updated_at: string;
};
export const getAssistantMemory = () =>
  apiFetch<{ persona: (Persona & { updated_at?: string }) | null; project: SavedProject | null }>("/assistant");
export const putPersona = (p: Persona) =>
  apiFetch<{ persona: Persona }>("/assistant/persona", {
    method: "PUT",
    headers: GUARDED_HEADERS,
    body: JSON.stringify(p),
  });
/* `draft` undefined leaves the stored draft as it is (the server's COALESCE) */
export const putProject = (turns: unknown[], stage: string, draft?: ComposerDraft) =>
  apiFetch<{ project: Omit<SavedProject, "turns" | "draft"> }>("/assistant/project", {
    method: "PUT",
    headers: GUARDED_HEADERS,
    body: JSON.stringify(draft ? { turns, stage, draft } : { turns, stage }),
  });
/* Clear the conversation: DELETED on the server, never archived (2026-10-02,
   Mike's call -- a conversation is working memory; what it made is on the
   concept, and a render carries its prompt on the Assets wall). */
export const clearProject = () =>
  apiFetch<{ ok: boolean }>("/assistant/project", { method: "DELETE", headers: GUARDED_HEADERS });
/* the Keep click against the checker, one entry per frame the sheet showed */
export type FrameVerdict = {
  id: string;
  role: string;
  query: string;
  checker_kept: boolean;
  why: string;
  person_kept: boolean;
  source_url: string;
};
export const postVerdicts = (frames: FrameVerdict[]) =>
  apiFetch<{ recorded: number }>("/assistant/reference-verdicts", {
    method: "POST",
    headers: GUARDED_HEADERS,
    body: JSON.stringify({ frames }),
  });


/* ── New session (2026-10-02, the header's button) ──
   The header lives in the shell, ABOVE the thread provider (the provider
   reads the shell for whose thread it is), so the button cannot call
   clearProject() itself: it asks through a window event, and the provider
   deletes the open conversation on the server and starts empty.
   The Studio page listens too, to stop a live run and clear what is only
   its own (progress, selection). */
export const NEW_SESSION_EVENT = "zpf:new-session";
export function requestNewSession() {
  window.dispatchEvent(new Event(NEW_SESSION_EVENT));
}

/* ── the composer bridge ──
   The pill reads what the box holds straight off the shared draft now
   (assistant-thread.tsx); what is left here is the one direction the draft
   does not cover: a fill that must say WHO filled it, so the composer can
   tag the text and ring Create. */
export const FILL_EVENT = "zpf:assistant-fill";
const PENDING_KEY = "zpf.assistant.pending";
export type Fill = { text?: string; refs?: string[]; by: string; avatar?: string };

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

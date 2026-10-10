/* The assistant pill's client half (2026-09-26, ASSISTANT_HANDOFF.md
   step 2). The brain is src/assistant_brain.py behind the same
   POST /api/creative-guide the composer's Guide mode posts; this file is
   what the floating pill needs on top of studio-api.ts's Guide helpers:

   - the persona (the mascot it wears, named for its creature, and one of
     three tones), kept per account in localStorage and src/assistant_store.py;
   - the seven steps and which one a page sits on;
   - the bridge to the Studio composer. The pill floats over every page
     and the composer's state lives inside studio/page.tsx, so the two
     talk in window events, and a fill asked for from another page waits
     in sessionStorage until the composer mounts. The assistant only ever
     FILLS the box; Create stays the person's click. */
import { apiFetch } from "@/lib/api";
import { GUARDED_HEADERS, type GuideReply } from "@/lib/studio-api";
import type { Plan } from "@/lib/make-plan";
import type { EffectState } from "@/lib/effects";
import type { Made } from "@/lib/composer";
import { decodeMascot, encodeMascot, nameOf } from "@/lib/mascot";

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
  // a project's workspace and a scene's canvas: the shot tree is open
  ["/studio/projects/", "shots"],
  ["/studio/scene", "shots"],
  ["/studio/references", "references"],
  ["/studio/elements", "cast"],
  ["/studio/projects", "story"],
  ["/studio", "brief"],
];
export const pageStage = (path: string): Stage =>
  PAGE_STAGE.find(([p]) => path.startsWith(p))?.[1] ?? "brief";
export const PAGE_NAME: [string, string][] = [
  ["/studio/queue", "Queue"],
  ["/studio/assets", "Assets"],
  ["/studio/projects/", "Project"],
  ["/studio/scene", "Scene"],
  ["/studio/references", "References"],
  ["/studio/elements", "Elements"],
  ["/studio/projects", "Projects"],
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
/* `avatar` is the mascot's code (lib/mascot.ts) and `name` is its creature's
   name, which never changes: the name follows the creature. A persona saved
   before the mascot (an emoji or a film glyph, a name the person typed) is
   read as the default, Nimbus, keeping its tone. */
export type Persona = { name: string; avatar: string; tone: Tone };
export function asMascotPersona(p: { avatar?: string | null; tone?: string | null }): Persona {
  const mascot = decodeMascot(p.avatar);
  return {
    name: nameOf(mascot),
    avatar: encodeMascot(mascot),
    tone: TONES.some((t) => t.id === p.tone) ? (p.tone as Tone) : "friendly",
  };
}

const personaKey = (account: string) => `zpf.assistant.${account || "default"}`;
export function loadPersona(account: string): Persona | null {
  try {
    const raw = localStorage.getItem(personaKey(account));
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<Persona>;
    if (!p.name || !p.avatar) return null;
    return asMascotPersona(p);
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
  /** the composer: what the guide used before this answer -- read tools by
   *  name, a skill as "skill:<title>" (lib/skills.ts lookedOf) */
  looked?: string[];
  /** the composer: the skill this message was sent with, by title */
  skill?: string;
  /** the composer: a plan the brain proposed -- its steps and where each
   *  one stands (lib/make-plan.ts). Each step's result is its own turn. */
  plan?: Plan;
  /** the composer: an effect on its way to a result (lib/effects.ts) --
   *  what it is, what it acts on, its options and words. The result is
   *  this turn's `made`. */
  effect?: EffectState;
  /** the composer: the proposal's confirm card has been decided */
  decided?: "done" | "skipped";
  /** the composer (2026-10-02): this user turn was a SEND, and what it made
   *  (lib/composer.ts). The pill leaves these turns out of its card and of
   *  the conversation it sends: they are the box's, not the Guide's. */
  made?: Made;
};

/* The composer's box, saved beside the thread so leaving the page keeps
   it: the idea, the guide's brief, references (picks by URL, uploads by
   the bin URL they were saved under), the "scene written" card.
   Mirrors src/assistant_store._clean_draft -- the server bounds every
   field and answers this exact shape (it still stores a `mode` older
   drafts wrote; nothing reads it since 2026-10-04 -- there is no Guide
   toggle, every send is the brain's). */
export type UploadRef = { url: string; name: string };
export type ComposerDraft = {
  idea: string;
  brief: string;
  picked: string[];
  uploads: UploadRef[];
  written: { conceptId: number | null; detail: string } | null;
};
export const EMPTY_DRAFT: ComposerDraft = { idea: "", brief: "", picked: [], uploads: [], written: null };
export const draftHasContent = (d: ComposerDraft | null | undefined) =>
  !!d && !!(d.idea.trim() || d.brief.trim() || d.picked.length || d.uploads.length || d.written);
/* whatever came back, in the shape the page can trust */
export function asDraft(raw: unknown): ComposerDraft {
  const d = (raw && typeof raw === "object" ? raw : {}) as Partial<ComposerDraft>;
  return {
    idea: typeof d.idea === "string" ? d.idea : "",
    brief: typeof d.brief === "string" ? d.brief : "",
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


/* ── save_as_project (2026-10-07) ──
   "Make this a project" turns the conversation into one: the server copies
   these turns into the new project's chat history and files the scenes the
   thread's sends made under it. A turn is {role, content, tool_calls?}; the
   box's own sends are user turns like any other (their words were said),
   and what each made is its concept id. A failed turn was never answered,
   so it is left out. */
const KEPT_EXTRAS = ["choices", "questions", "directions", "nudge", "stage", "brief"] as const;
export function asProjectConversation(turns: Turn[]) {
  const conversation = turns
    .filter((t) => !t.failed && t.content.trim())
    .map((t) => {
      const extras: Record<string, unknown> = {};
      for (const k of KEPT_EXTRAS) {
        const v = t.reply?.[k];
        if (v && (!Array.isArray(v) || v.length)) extras[k] = v;
      }
      return { role: t.role, content: t.content, ...(Object.keys(extras).length ? { tool_calls: extras } : {}) };
    });
  const scenes = [...new Set(turns.map((t) => t.made?.conceptId).filter((id): id is number => typeof id === "number"))];
  return { conversation, scenes };
}

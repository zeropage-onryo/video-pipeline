/* The studio composer's model (2026-10-02, the "Direction A" redesign,
   drawn to the "ZPF Composer Directions" mock the same day; chat-only
   with a READY hand-off since 2026-10-03, Mike's call).

   The box TALKS (every send is a Guide turn); the Ready menu makes two
   kinds of thing, through two routes that already existed:

   - VIDEO  -> POST /api/scenes/run  (Create): writes ONE scene, timed
     shots and all, and stops on the board. No clip is rendered here --
     the Queue is where money is spent, so the result is a written scene
     drawn as its shots, with links to Pipeline and Director, never a
     fake take grid.
   - IMAGE  -> POST /api/generate/run with output=image: one Nano Banana
     still, saved as a one-shot concept whose shot carries the image as
     its reference_image (so it opens in Director like anything else).

   ONE output per hand-off. There is no take/count control on purpose
   (2026-09-10, server-enforced as SCENE_COUNT_MAX = 1).

   WHAT A HAND-OFF MADE IS PART OF THE CONVERSATION (2026-10-02). It is a
   user turn in the studio's one thread (lib/assistant.ts `Turn`) carrying
   `made` -- this file's `Made` -- so the still a person drew is there
   when they come back from Pipeline, the same way the Guide's talk is.
   Progress ticks stay in page state (a save per tick would be a PUT a
   second); only the result and the status changes are saved. */
import { API_URL } from "@/lib/api";
import { getJob, type Job, type TimelinePart } from "@/lib/studio-api";

export type Output = "image" | "video";

/* Aspect ratios a Nano Banana still can be drawn at. The API keeps its
   own allowlist (app/api.py GENERATE_ASPECTS); an id it does not know
   falls back to the server default, never a failed call. */
export const IMAGE_ASPECTS: { id: string; label: string }[] = [
  { id: "4:5", label: "4:5" },
  { id: "1:1", label: "1:1" },
  { id: "16:9", label: "16:9" },
  { id: "9:16", label: "9:16" },
];

export type MadeStatus = "running" | "done" | "failed" | "stopped";

/** What one hand-off made -- saved on its user turn (`Turn.made`). */
export type Made = {
  id: string;
  output: Output;
  /** drawable thumbnails of the references that rode along */
  refs: string[];
  status: MadeStatus;
  /** the last detail line the job gave; the live one is page state */
  detail: string;
  /** the server job, so a run left mid-way is picked up on return */
  jobId?: number;
  conceptId?: number | null;
  /** IMAGE: the rendered still (absolute or /refs path) */
  image?: string | null;
  /** VIDEO: the scene's title and its timed shots, when it planned any */
  title?: string;
  parts?: TimelinePart[];
  seconds?: number | null;
  /** the aspect / frame label the send was made at, for the meta line */
  frame?: string;
  /** the shot (or image) the person selected; Director opens on it */
  shot?: number;
};

export const newMadeId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `m${Date.now()}${Math.random().toString(36).slice(2, 7)}`;

/** a stored media path made drawable from this origin */
export const mediaSrc = (u: string | null | undefined) =>
  !u ? "" : /^(https?:|blob:|data:)/.test(u) ? u : `${API_URL}${u}`;

/* ── the slash menu ──
   Commands are ACTIONS on the composer, never hidden prompt text: each
   one does something the person can see (a hand-off, a preset chip, a
   reference). Presets come from GET /api/presets so the menu cannot
   drift from what Enhance folds in. */
export type SlashCommand = {
  id: string;
  /** what is typed after the slash */
  cmd: string;
  desc: string;
  group: "make" | "camera" | "use";
  /** only offered once there is a finished image to act on */
  needsImage?: boolean;
};

export const BASE_COMMANDS: SlashCommand[] = [
  { id: "scene", cmd: "scene", desc: "Write the scene now (Ready → Write the scene)", group: "make" },
  { id: "still", cmd: "still", desc: "Draw a still now (Ready → Draw a still)", group: "make" },
  { id: "animate", cmd: "animate", desc: "Turn the last image into a shot", group: "use", needsImage: true },
  { id: "ref", cmd: "ref", desc: "Attach a reference image", group: "use" },
  { id: "element", cmd: "element", desc: "Reference a saved element (@)", group: "use" },
];

/** `/sc` -> the commands whose name starts with "sc" */
export function matchCommands(text: string, all: SlashCommand[], hasImage: boolean): SlashCommand[] | null {
  const m = /^\/([\w-]*)$/.exec(text);
  if (!m) return null;
  const q = m[1].toLowerCase();
  return all.filter((c) => c.cmd.startsWith(q) && (!c.needsImage || hasImage));
}

/* waitForJob without the abort: a Stop on the composer has to end the
   wait at once, whatever the server does with the cancel. Resolves to
   null when stopped. */
export async function pollJob(
  id: number,
  onTick: (job: Job) => void,
  stopped: () => boolean,
  everyMs = 1200,
): Promise<Job | null> {
  for (;;) {
    if (stopped()) return null;
    const job = await getJob(id);
    if (stopped()) return null;
    onTick(job);
    if (["done", "failed", "cancelled"].includes(job.status)) return job;
    await new Promise((r) => setTimeout(r, everyMs));
  }
}

/** "4:5" -> "4 / 5" for CSS aspect-ratio; anything else -> undefined */
export const cssAspect = (label?: string) => {
  const m = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(label ?? "");
  return m ? `${m[1]} / ${m[2]}` : undefined;
};

/** the one-line summary under a finished result: "3 shots · 16:9 · 10s" */
export function madeMeta(m: Made): string {
  if (m.output === "image") return ["1 image", m.frame].filter(Boolean).join(" · ");
  const n = m.parts?.length ?? 0;
  return [
    m.title,
    n ? `${n} shot${n === 1 ? "" : "s"}` : "one continuous shot",
    m.frame,
    m.seconds ? `${m.seconds}s` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

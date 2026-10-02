/* The studio composer's model (2026-10-02, the "Direction A" redesign).

   The box makes two kinds of thing, and they go through two routes that
   already existed before the redesign:

   - VIDEO  -> POST /api/scenes/run  (Create): writes ONE scene, timed
     shots and all, and stops on the board. No clip is rendered here --
     the Queue is where money is spent, so the result is a written scene
     with links to Pipeline and Director, never a fake take grid.
   - IMAGE  -> POST /api/generate/run with output=image: one Nano Banana
     still, saved as a one-shot concept whose shot carries the image as
     its reference_image (so it opens in Director like anything else).

   ONE output per send. There is no take/count control on purpose
   (2026-09-10, server-enforced as SCENE_COUNT_MAX = 1). */
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

export type TurnStatus = "running" | "done" | "failed" | "stopped";

/** One send and what came back, drawn above the box. */
export type Turn = {
  id: string;
  output: Output;
  prompt: string;
  /** drawable thumbnails of the references that rode along */
  refs: string[];
  status: TurnStatus;
  progress: number;
  detail: string;
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
};

export const newTurnId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `t${Date.now()}${Math.random().toString(36).slice(2, 7)}`;

/** a stored media path made drawable from this origin */
export const mediaSrc = (u: string | null | undefined) =>
  !u ? "" : /^(https?:|blob:|data:)/.test(u) ? u : `${API_URL}${u}`;

/* ── the slash menu ──
   Commands are ACTIONS on the composer, never hidden prompt text: each
   one changes a control the person can see (output, a preset chip, the
   Guide toggle, a reference). Presets come from GET /api/presets so the
   menu cannot drift from what Enhance folds in. */
export type SlashCommand = {
  id: string;
  /** what is typed after the slash */
  cmd: string;
  desc: string;
  group: "make" | "camera" | "use";
  /** only offered in this output (absent = both) */
  only?: Output;
  /** only offered once there is a finished image to act on */
  needsImage?: boolean;
};

export const BASE_COMMANDS: SlashCommand[] = [
  { id: "image", cmd: "image", desc: "Make a still", group: "make" },
  { id: "video", cmd: "video", desc: "Write a video scene", group: "make" },
  { id: "guide", cmd: "guide", desc: "Talk the idea through first", group: "make" },
  { id: "animate", cmd: "animate", desc: "Turn the last image into a scene", group: "use", needsImage: true },
  { id: "ref", cmd: "ref", desc: "Attach a reference image", group: "use" },
  { id: "element", cmd: "element", desc: "Reference a saved element (@)", group: "use" },
];

/** `/pu` -> the commands whose name starts with "pu" */
export function matchCommands(
  text: string,
  all: SlashCommand[],
  output: Output,
  hasImage: boolean,
): SlashCommand[] | null {
  const m = /^\/([\w-]*)$/.exec(text);
  if (!m) return null;
  const q = m[1].toLowerCase();
  return all.filter(
    (c) =>
      c.cmd.startsWith(q) &&
      (!c.only || c.only === output) &&
      (!c.needsImage || hasImage),
  );
}

/* the last choice of output survives a reload; storage can throw in a
   private window, and the default is simply video */
const OUTPUT_KEY = "zpf:composer:output";
export function loadOutput(): Output {
  try {
    return localStorage.getItem(OUTPUT_KEY) === "image" ? "image" : "video";
  } catch {
    return "video";
  }
}
export function saveOutput(o: Output) {
  try {
    localStorage.setItem(OUTPUT_KEY, o);
  } catch {
    /* fine */
  }
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

/* The studio composer's model (2026-10-02, the "Direction A" redesign,
   drawn to the "ZPF Composer Directions" mock the same day).

   EVERY SEND GOES TO THE BRAIN FIRST (2026-10-04, Mike: "it is all in one
   place where you can toggle between image and video that are connected
   to the reasoning/brain"). There is no Guide toggle: a send is a Guide
   turn (POST /api/creative-guide with `output`), and the model decides
   whether the person is talking an idea through (it answers, with chips
   and a brief) or asking for the thing, in which case it calls
   make_image / make_video with the prompt it wrote and the page runs
   that at once, through the two routes that already existed:

   - VIDEO  -> POST /api/scenes/run  (Create): writes ONE scene, timed
     shots and all, and stops on the board. No clip is rendered here --
     the Queue is where money is spent, so the result is a written scene
     drawn as its shots, with links to Pipeline and Director, never a
     fake take grid.
   - IMAGE  -> POST /api/generate/run with output=image and the picked
     `image_model` (GET /api/image-models: Nano Banana on the Gemini key,
     or one of fal's image models): one still, saved as a one-shot
     concept whose shot carries the image as its reference_image (so it
     opens in Director like anything else).

   Without the guide (no Gemini key: capabilities.creative_guide false) a
   send makes directly, which is what every send did before.

   ONE output per send. There is no take/count control on purpose
   (2026-09-10, server-enforced as SCENE_COUNT_MAX = 1).

   WHAT A SEND MADE IS PART OF THE CONVERSATION (2026-10-02). A send is a
   user turn in the studio's one thread (lib/assistant.ts `Turn`) carrying
   `made` -- this file's `Made` -- so the still a person drew is there
   when they come back from Pipeline, the same way the Guide's talk is.
   Progress ticks stay in page state (a save per tick would be a PUT a
   second); only the result and the status changes are saved. */
import { API_URL } from "@/lib/api";
import { followJob, type Job, type TimelinePart } from "@/lib/studio-api";
import { PLAN_TOOL } from "@/lib/make-plan";
import { EFFECT_TOOL } from "@/lib/effects";

export type Output = "image" | "video";

/* The Guide's make tools (src/guide_tools.MAKE_TOOLS). A make_video is run
   by the page the moment it arrives -- writing a scene costs nothing, the
   send was the ask. A make_image spends credits on a still, so it is drawn
   as a STEP CARD (2026-10-08, Mike: "similar to Runway's in their chat"):
   the prompt, the model and what it costs, and -- in Ask mode, below --
   an Approve it waits on. */
export const MAKE_TOOLS: Record<string, Output> = { make_image: "image", make_video: "video" };
/* A plan (lib/make-plan.ts) is several makes in a row: the studio runs it,
   never the confirm card, so every reader that asks "is this a make" says
   yes to it too. */
export const isPlanTool = (tool?: string | null) => tool === PLAN_TOOL;
export const isEffectTool = (tool?: string | null) => tool === EFFECT_TOOL;
export const isMake = (tool?: string | null) =>
  !!tool && (tool in MAKE_TOOLS || tool === PLAN_TOOL || tool === EFFECT_TOOL);

/* The Guide's element sheet (src/guide_tools.SHEET_TOOL, 2026-10-09): a
   step card like a still's, but its Approve saves the person in the
   attached photos as a character (POST /api/assets/characters, the
   composer's references as photo_urls, sheet on) and the sheet is drawn by
   the Elements route's own job -- the landing page's five-panel prompt,
   16:9, from the real photos. Never a confirm card, never /creative-guide/act. */
export const SHEET_TOOL = "make_element_sheet";
/** the `model` a sheet's Made carries, so its meta line can name it */
export const SHEET_MODEL = "element-sheet";
export const isSheetTool = (tool?: string | null) => tool === SHEET_TOOL;

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

/** What one send made -- saved on its user turn (`Turn.made`). */
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
  /** the prompt the thing was made from -- the brain's, when it made it;
   *  what Reuse prompt puts back in the box */
  prompt?: string;
  /** IMAGE: which model drew it (an /image-models id) */
  model?: string;
  /** AN EFFECT's result (lib/effects.ts): the effect that made it, a clip
   *  when it made one, and the render's id on the Assets wall -- which is
   *  how a later effect names it */
  effect?: string;
  clip?: string | null;
  asset?: string | null;
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
   one changes a control the person can see (output, a preset chip, the
   Guide toggle, a reference). Presets come from GET /api/presets so the
   menu cannot drift from what Enhance folds in. Skills (2026-10-10,
   lib/skills.ts) come from GET /api/skills the same way: a pick is a
   chip on the box, and the recipe it names rides on that one send. */
export type SlashCommand = {
  id: string;
  /** what is typed after the slash */
  cmd: string;
  desc: string;
  /** a longer line, shown on hover */
  hint?: string;
  group: "make" | "camera" | "use" | "skill";
  /** only offered in this output (absent = both) */
  only?: Output;
  /** only offered once there is a finished image to act on */
  needsImage?: boolean;
};

export const BASE_COMMANDS: SlashCommand[] = [
  { id: "image", cmd: "image", desc: "Make stills", group: "make" },
  { id: "video", cmd: "video", desc: "Write video scenes", group: "make" },
  { id: "animate", cmd: "animate", desc: "Turn the last image into a shot", group: "use", needsImage: true },
  { id: "effects", cmd: "effects", desc: "Change a still or a clip", group: "use" },
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

/* Before a still is drawn (2026-10-08, Runway Agent's setting of the same
   name): "ask" holds the step card on its Approve, "auto" draws on the send
   and the card is the step's record. Remembered per browser; Ask unless
   the person turned it off -- a still spends credits. */
export type GenerateMode = "ask" | "auto";
export const GENERATE_MODES: { id: GenerateMode; label: string; note: string }[] = [
  { id: "ask", label: "Ask before generating", note: "Review each still before it runs" },
  { id: "auto", label: "Generate automatically", note: "Skip confirmation, go straight to results" },
];
const GENERATE_KEY = "zpf:composer:generate";
export function loadGenerateMode(): GenerateMode {
  try {
    return localStorage.getItem(GENERATE_KEY) === "auto" ? "auto" : "ask";
  } catch {
    return "ask";
  }
}
export function saveGenerateMode(mode: GenerateMode) {
  try {
    localStorage.setItem(GENERATE_KEY, mode);
  } catch {
    /* fine */
  }
}

/* which image model draws, remembered the same way; "" = the server's default */
const IMAGE_MODEL_KEY = "zpf:composer:image-model";
export function loadImageModel(): string {
  try {
    return localStorage.getItem(IMAGE_MODEL_KEY) ?? "";
  } catch {
    return "";
  }
}
export function saveImageModel(id: string) {
  try {
    localStorage.setItem(IMAGE_MODEL_KEY, id);
  } catch {
    /* fine */
  }
}

/* waitForJob with a stop: a Stop on the composer has to end the wait at
   once, whatever the server does with the cancel. Resolves to null when
   stopped. On the job stream while it is live (studio-api followJob). */
export async function pollJob(
  id: number,
  onTick: (job: Job) => void,
  stopped: () => boolean,
  everyMs = 1200,
): Promise<Job | null> {
  return followJob(id, onTick, { everyMs, stopped });
}

/** "4:5" -> "4 / 5" for CSS aspect-ratio; anything else -> undefined */
export const cssAspect = (label?: string) => {
  const m = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(label ?? "");
  return m ? `${m[1]} / ${m[2]}` : undefined;
};

/** the one-line summary under a finished result: "3 shots · 16:9 · 10s" */
export function madeMeta(m: Made, modelLabel?: string): string {
  if (m.clip) return ["1 clip", modelLabel].filter(Boolean).join(" · ");
  if (m.output === "image") return ["1 image", m.frame, modelLabel].filter(Boolean).join(" · ");
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

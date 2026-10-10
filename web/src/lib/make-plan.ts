/* A plan: several makes in a row, proposed by the brain as ONE answer
   (src/guide_tools.py make_plan; docs/tasks/task-studio-agent.md item 2).

   "Make an ad from these photos" is a hero still, then the scene, then its
   keyframes, then the Queue. The brain used to be able to propose one of
   those per message. Now it proposes the list, and the studio runs it in
   order through the same doors each step always had -- the still's step
   card, the scene writer, the Elements create route, the keyframes
   approve, the pick -- so every price, charge and job is what it was.

   The plan lives on its assistant turn (`Turn.plan`) and is saved with the
   thread. A step's RESULT is an ordinary turn appended under the card (a
   still's step card and tile, a scene's shot tiles); the step only keeps
   the made id that links to it.

   What costs credits waits: with "Ask first" on, a paid step stops at
   `waiting` until its own Approve, beside its price. "Approve all" covers
   only the steps whose price was on the card when it was clicked -- a
   scene's keyframes are priced once the scene exists, so they still ask.

   Pure and import-free on purpose: tests/make-plan.test.mjs runs this file as
   it is. */

export const PLAN_TOOL = "make_plan";

export type StepDo = "image" | "scene" | "sheet" | "keep" | "keyframes" | "queue";
export type StepStatus = "pending" | "waiting" | "running" | "done" | "failed" | "skipped";

export type PlanStep = {
  /** 1-based, as the card numbers it */
  n: number;
  do: StepDo;
  /** one line from the brain: what this step is for */
  why: string;
  /** the step's own arguments, as its tool takes them */
  args: Record<string, unknown>;
  /** earlier steps whose picture this one is held to */
  uses: number[];
  /** keyframes / queue: the scene step it acts on */
  scene?: number;
  status: StepStatus;
  /** why it failed or was skipped, or what it did */
  note?: string;
  /** the turn its result was drawn into (Turn.made.id) */
  madeId?: string;
  conceptId?: number | null;
  image?: string | null;
  /** what it costs, once that is known */
  credits?: number | null;
  /** keyframes: how many stills the quote is for */
  stills?: number;
  /** the person changed it before it ran */
  edited?: boolean;
};

export type Plan = {
  id: string;
  summary: string;
  steps: PlanStep[];
  /** steps approved ahead of their turn */
  approved: number[];
  started?: boolean;
  /** the person stopped it: nothing further starts until Resume */
  stopped?: boolean;
  /** it finished once, and the conversation around it was cleared then: a
   *  step re-run later must not clear the box a second time */
  closed?: boolean;
};

export type GenerateMode = "ask" | "auto";
export type Phase = "idle" | "running" | "waiting" | "paused" | "finished";

const DOES: StepDo[] = ["image", "scene", "sheet", "keep", "keyframes", "queue"];
const PAID: StepDo[] = ["image", "sheet", "keyframes"];
export const MIN_STEPS = 2;
export const MAX_STEPS = 8;

export const isPaid = (s: PlanStep) => PAID.includes(s.do);
const over = (s: PlanStep) => s.status === "done" || s.status === "skipped";

const str = (v: unknown) => (typeof v === "string" ? v.trim() : "");
const int = (v: unknown) => (typeof v === "number" && Number.isInteger(v) ? v : null);

/** The plan off a proposal's args, as the server cleaned them
    ({summary, steps: [{n, do, args, why, uses, scene}]}). null when it is
    not a plan a card can draw: fewer than two steps a card knows. */
export function planOf(raw: unknown, id: string): Plan | null {
  const a = (raw ?? {}) as { summary?: unknown; steps?: unknown };
  if (!Array.isArray(a.steps)) return null;
  const steps: PlanStep[] = [];
  for (const item of a.steps.slice(0, MAX_STEPS)) {
    const s = (item ?? {}) as Record<string, unknown>;
    const doing = str(s.do) as StepDo;
    if (!DOES.includes(doing)) return null;
    const n = steps.length + 1;
    const args = s.args && typeof s.args === "object" && !Array.isArray(s.args) ? (s.args as Record<string, unknown>) : {};
    const uses = (Array.isArray(s.uses) ? s.uses : []).map(int).filter((u): u is number => u !== null && u >= 1 && u < n);
    const scene = int(s.scene);
    steps.push({
      n,
      do: doing,
      why: str(s.why),
      args,
      uses: [...new Set(uses)],
      ...(scene !== null && scene >= 1 && scene < n ? { scene } : {}),
      status: "pending",
    });
  }
  if (steps.length < MIN_STEPS) return null;
  return { id, summary: str(a.summary), steps, approved: [] };
}

export const stepAt = (plan: Plan, n: number) => plan.steps.find((s) => s.n === n) ?? null;

/** The scene step a keyframes / queue step acts on. */
export const sceneOf = (plan: Plan, s: PlanStep) => (s.scene ? stepAt(plan, s.scene) : null);

/** Why a step cannot run, or "" when it can: its scene was skipped, failed
    or never written. A step that only USES an earlier picture is never
    blocked by it -- without the picture it is drawn from its own prompt. */
export function blockedBy(plan: Plan, s: PlanStep): string {
  if (s.do !== "keyframes" && s.do !== "queue") return "";
  const scene = sceneOf(plan, s);
  if (!scene || scene.do !== "scene") return "there is no scene step for it";
  if (scene.status === "skipped") return `step ${scene.n} was skipped`;
  if (scene.status === "failed") return `step ${scene.n} did not finish`;
  if (scene.status === "done" && !scene.conceptId) return `step ${scene.n} wrote no scene`;
  return "";
}

/** The step the plan is on: the first one neither done nor skipped. */
export const nextStep = (plan: Plan) => plan.steps.find((s) => !over(s)) ?? null;

export const finished = (plan: Plan) => plan.steps.every(over);

/** Does this step stop for its own Approve? Only what spends, only with
    "Ask first" on, and only when it was not approved ahead of its turn. */
export const needsApproval = (plan: Plan, s: PlanStep, mode: GenerateMode) =>
  isPaid(s) && mode === "ask" && !plan.approved.includes(s.n);

export function phase(plan: Plan): Phase {
  if (finished(plan)) return "finished";
  if (plan.steps.some((s) => s.status === "running")) return "running";
  if (plan.steps.some((s) => s.status === "waiting")) return "waiting";
  return plan.started ? "paused" : "idle";
}

export function patchStep(plan: Plan, n: number, p: Partial<PlanStep>): Plan {
  return { ...plan, steps: plan.steps.map((s) => (s.n === n ? { ...s, ...p } : s)) };
}

/* The plan moved back to an earlier step (an edit, a step brought back):
   a later step that was waiting for its Approve is no longer the one the
   plan is on. It goes back to pending, so the card offers Resume and the
   plan runs from its first unfinished step again. */
const unwait = (plan: Plan): Plan => ({
  ...plan,
  steps: plan.steps.map((s) => (s.status === "waiting" ? { ...s, status: "pending" as const } : s)),
});

/** Skip a step, and with a scene the steps that only exist for it. */
export function skipStep(plan: Plan, n: number): Plan {
  const s = stepAt(plan, n);
  if (!s || s.status === "running" || s.status === "done") return plan;
  let out = patchStep(plan, n, { status: "skipped", note: "skipped" });
  if (s.do === "scene") {
    for (const d of plan.steps) {
      if (d.scene === n && !over(d) && d.status !== "running") {
        out = patchStep(out, d.n, { status: "skipped", note: `step ${n} was skipped` });
      }
    }
  }
  return out;
}

/** Change a step's arguments. One that already ran (or failed) goes back
    to pending with its result forgotten -- so the plan re-runs THAT step
    and nothing else: every other finished step stays finished. */
export function editStep(plan: Plan, n: number, args: Record<string, unknown>): Plan {
  const s = stepAt(plan, n);
  if (!s || s.status === "running") return plan;
  const ran = s.status === "done" || s.status === "failed";
  const next = { ...s.args, ...args };
  // a scene's new words say their own shot count; the brain's old one would
  // only be a stale label on the card
  if (s.do === "scene" && "prompt" in args) delete next.shots;
  return {
    ...patchStep(unwait(plan), n, {
      args: next,
      edited: true,
      ...(ran ? { status: "pending", note: undefined, madeId: undefined, image: undefined, conceptId: undefined } : {}),
    }),
    // an approval was for the step as it read then
    approved: plan.approved.filter((a) => a !== n),
  };
}

/** Bring a skipped step back. */
export function restoreStep(plan: Plan, n: number): Plan {
  const s = stepAt(plan, n);
  return s && s.status === "skipped" ? patchStep(unwait(plan), n, { status: "pending", note: undefined }) : plan;
}

export function approveStep(plan: Plan, n: number): Plan {
  return plan.approved.includes(n) ? plan : { ...plan, approved: [...plan.approved, n] };
}

/** "Approve all": every paid step still to run whose price is on the card. */
export function approveAll(plan: Plan, prices: Prices): Plan {
  const ahead = plan.steps.filter((s) => !over(s) && isPaid(s) && priceOf(s, prices) !== null).map((s) => s.n);
  return { ...plan, approved: [...new Set([...plan.approved, ...ahead])] };
}

/** The pictures a step is held to: its used steps that drew one. */
export function picturesFor(plan: Plan, s: PlanStep): string[] {
  return s.uses
    .map((u) => stepAt(plan, u))
    .filter((u): u is PlanStep => !!u && u.status === "done" && !!u.image)
    .map((u) => u.image as string);
}

export type Prices = { image: number | null; sheet: number | null };

/** What a step costs in credits, or null while that is not known: a still
    and a sheet are priced by the model picked; a scene's keyframes only
    once the scene exists (the step carries the quote then). Free steps: 0. */
export function priceOf(s: PlanStep, prices: Prices): number | null {
  if (!isPaid(s)) return 0;
  if (typeof s.credits === "number") return s.credits;
  if (s.do === "image") return prices.image;
  if (s.do === "sheet") return prices.sheet;
  return null;
}

/** The total still ahead: the credits that are known, how many paid steps
    carry a price, and how many do not have one on the card yet. */
export function ahead(plan: Plan, prices: Prices): { credits: number; priced: number; unpriced: number } {
  let credits = 0;
  let priced = 0;
  let unpriced = 0;
  for (const s of plan.steps) {
    if (over(s) || !isPaid(s)) continue;
    const p = priceOf(s, prices);
    if (p === null) unpriced += 1;
    else {
      credits += p;
      priced += 1;
    }
  }
  return { credits, priced, unpriced };
}

export const progress = (plan: Plan) => ({
  done: plan.steps.filter((s) => s.status === "done").length,
  of: plan.steps.filter((s) => s.status !== "skipped").length,
});

const KIND: Record<StepDo, string> = {
  image: "Still",
  scene: "Scene",
  sheet: "Element sheet",
  keep: "Keep references",
  keyframes: "Keyframes",
  queue: "Send to Queue",
};

/** "Scene · 3 shots · 10s" */
export function stepTitle(s: PlanStep): string {
  const bits = [KIND[s.do]];
  if (s.do === "image" && str(s.args.aspect)) bits.push(str(s.args.aspect));
  if (s.do === "scene") {
    const shots = int(s.args.shots);
    const seconds = int(s.args.seconds);
    if (shots) bits.push(`${shots} shot${shots === 1 ? "" : "s"}`);
    if (seconds) bits.push(`${seconds}s`);
  }
  if (s.do === "sheet" && str(s.args.name)) bits.push(str(s.args.name));
  return bits.join(" · ");
}

/** What the step will do, in words: its prompt, or a plain sentence. */
export function stepText(plan: Plan, s: PlanStep): string {
  if (s.do === "image" || s.do === "scene") return str(s.args.prompt);
  if (s.do === "sheet") {
    const wear = str(s.args.notes);
    return `Save ${str(s.args.name) || "this person"} as a character from the attached photos and draw the reference sheet${wear ? `, wearing ${wear}` : ""}.`;
  }
  if (s.do === "keep") {
    const k = Array.isArray(s.args.candidate_ids) ? s.args.candidate_ids.length : 0;
    return `Keep ${k} reference frame${k === 1 ? "" : "s"} from the sheet above and attach ${k === 1 ? "it" : "them"} to the box.`;
  }
  const scene = s.scene ? `the scene from step ${s.scene}` : "the scene";
  return s.do === "keyframes"
    ? `Draw the first frame of each shot in ${scene}, so the clips have something to start from.`
    : `Send ${scene} to the Queue, where its clip is priced and approved.`;
}

/** Can the person still change this step's words? */
export const editable = (s: PlanStep) => (s.do === "image" || s.do === "scene") && s.status !== "running";

export type MadeLike = { status: string; image?: string | null; conceptId?: number | null };

/** After a reload, or when a result landed while nobody was looping: bring
    each step in line with the turn its result was drawn into, and put a
    step that says "running" with nothing behind it back to pending.
    Returns the SAME plan object when nothing changed. */
export function reconcile(plan: Plan, mades: Record<string, MadeLike | undefined>, live: number[] = []): Plan {
  let out = plan;
  for (const s of plan.steps) {
    const m = s.madeId ? mades[s.madeId] : undefined;
    const drew = !!m && m.status === "done" && (s.do === "scene" ? !!m.conceptId : !!m.image);
    if (s.status === "failed") {
      // its own card's "Approve again" ran it once more, outside the plan
      if (m && m.status === "running") out = patchStep(out, s.n, { status: "running", note: undefined });
      else if (drew) out = patchStep(out, s.n, { status: "done", image: m?.image ?? null, conceptId: m?.conceptId ?? null, note: undefined });
      continue;
    }
    if (s.status !== "running") continue;
    if (m && m.status === "running") continue;
    if (m && m.status === "done") {
      out = patchStep(out, s.n, drew
        ? { status: "done", image: m.image ?? null, conceptId: m.conceptId ?? null, note: undefined }
        : { status: "failed", note: s.do === "scene" ? "no scene was written" : "nothing was drawn" });
      continue;
    }
    if (m) {
      out = patchStep(out, s.n, { status: "failed", note: m.status === "stopped" ? "stopped" : "did not finish" });
      continue;
    }
    if (!live.includes(s.n)) out = patchStep(out, s.n, { status: "pending", note: "interrupted" });
  }
  return out;
}

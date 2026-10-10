/* The skill shelf, as the composer needs it (src/skills.py, GET /api/skills).

   A skill is a recipe the brain reads before a kind of work -- a character
   sheet, a multi-shot scene. It reaches a turn two ways: the brain loads it
   itself (a `load_skill` read in reply.tool_runs), or the person picks it
   from the `/` menu, which puts a chip on the box and `skill=<name>` on that
   one send. Either way the answer's caption says which skill it used.

   Pure and import-free on purpose: tests/skills.test.mjs runs this file as
   it is. */

export type Skill = {
  name: string;
  title: string;
  /** one line: when it is the right recipe */
  summary: string;
  /** which make it usually ends in, when it has one */
  output: "image" | "video" | "";
};

export const SKILL_TOOL = "load_skill";

/* A turn's `looked` list holds tool names; a skill is kept there as
   "skill:<title>", resolved when the turn lands, so a saved thread draws
   the same caption with no shelf to look the name up in. */
export const SKILL_MARK = "skill:";

export type ToolRun = { tool: string; args?: Record<string, unknown> | null; ok?: boolean };

/** "mood-board" -> "Mood board": the title when the shelf has not loaded */
export function humanise(name: string): string {
  const words = name.replace(/[-_]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "";
}

export function skillTitle(name: string, shelf: Skill[]): string {
  const key = name.trim().toLowerCase();
  return shelf.find((s) => s.name === key)?.title ?? humanise(key);
}

/** What an answer used, for its caption: each read tool once, a skill by title. */
export function lookedOf(runs: ToolRun[] | null | undefined, shelf: Skill[]): string[] {
  const out: string[] = [];
  for (const r of runs ?? []) {
    if (!r.ok) continue;
    const name = r.tool === SKILL_TOOL && typeof r.args?.name === "string" ? r.args.name : "";
    const label = name ? `${SKILL_MARK}${skillTitle(name, shelf)}` : r.tool;
    // a load whose name never arrived is nothing a person can read
    if (label && label !== SKILL_TOOL && !out.includes(label)) out.push(label);
  }
  return out;
}

/** The caption: "used the Mood board skill · looked at board". "" for nothing. */
export function lookedLine(looked: string[] | null | undefined): string {
  const all = looked ?? [];
  const skills = all.filter((l) => l.startsWith(SKILL_MARK)).map((l) => l.slice(SKILL_MARK.length));
  const tools = all.filter((l) => !l.startsWith(SKILL_MARK) && l !== SKILL_TOOL);
  const parts: string[] = [];
  if (skills.length) parts.push(`used the ${skills.join(" + ")} skill${skills.length > 1 ? "s" : ""}`);
  if (tools.length) parts.push(`looked at ${tools.join(", ")}`);
  return parts.join(" · ");
}

/** The shelf as `/` commands: `/mood-board`, drawn under "Skills". */
export function skillCommands(shelf: Skill[]) {
  return shelf.map((s) => ({
    id: `skill:${s.name}`,
    cmd: s.name,
    desc: s.title,
    hint: s.summary,
    group: "skill" as const,
  }));
}

/** The skill a `/` command names, or undefined when it is not one. */
export function skillOfCommand(id: string, shelf: Skill[]): Skill | undefined {
  return id.startsWith("skill:") ? shelf.find((s) => `skill:${s.name}` === id) : undefined;
}

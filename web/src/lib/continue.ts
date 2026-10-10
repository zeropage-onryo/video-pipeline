/* What a finished result can be carried on to (item 4 of
   docs/tasks/task-studio-agent.md; Runway's result actions, Higgsfield's
   asset actions).

   A still or a clip in the thread used to end in a row of whatever had
   been built so far. This is the one list: for each kind of result, the
   next things a person does with it, the few they reach for most in the
   row and the rest under More. Nothing here runs anything -- an action
   that costs credits opens a priced card (an effect, a variation) and
   that card's Approve is the click that spends.

   Pure and import-free: tests/continue.test.mjs runs this file as it is. */

export type ContinueKind =
  /** opens ONE effect's priced card, bound to this result */
  | "effect"
  /** opens the effects gallery on a tab, bound to this result */
  | "gallery"
  /** the same prompt and references, drawn again: a priced step card */
  | "variation"
  /** attached as a reference with the box turned to Video */
  | "shot"
  | "reference"
  | "element"
  | "download"
  | "library"
  | "editor"
  | "canvas"
  | "queue"
  | "reuse";

export type ContinueAction = {
  /** unique in one result's list */
  id: string;
  kind: ContinueKind;
  label: string;
  /** the tooltip: what the click does, and whether anything is spent */
  title: string;
  /** kind "effect": the effects table's id */
  effect?: string;
  /** kind "gallery": the tab it opens on */
  tab?: string;
  /** in the row; the rest sit under More */
  primary: boolean;
};

export type ResultFacts = {
  output: string;
  image?: string | null;
  clip?: string | null;
  /** its render on the Assets wall, `gen:<id>` */
  asset?: string | null;
  conceptId?: number | null;
  /** it came out of an effect (lib/effects.ts) */
  effect?: string;
  prompt?: string | null;
};

/** the render's number, when `asset` is one this studio issued */
export function assetId(asset: string | null | undefined): number | null {
  const m = /^gen:(\d+)$/.exec(asset ?? "");
  return m ? Number(m[1]) : null;
}

const CARD = "Opens a card with its price. Nothing runs until you approve.";

/** The actions for one finished result, in the order they are drawn.
    `effects`: the ids the server's table holds; `ready`: it can run them. */
export function continueActions(r: ResultFacts, has: { effects: string[]; ready: boolean }): ContinueAction[] {
  const out: ContinueAction[] = [];
  const fx = (effect: string, label: string, what: string, primary: boolean) => {
    if (has.ready && has.effects.includes(effect)) {
      out.push({ id: `effect:${effect}`, kind: "effect", effect, label, title: `${what} ${CARD}`, primary });
    }
  };
  const onWall = assetId(r.asset) !== null;
  const filed = () => {
    if (!onWall) return;
    out.push({ id: "download", kind: "download", label: "Download", title: "Save the file to your computer", primary: false });
    out.push({ id: "library", kind: "library", label: "See it in the Library", title: "Open it on the Library wall", primary: false });
  };

  if (r.clip) {
    // a clip is only ever named by its render id: one that is not on the
    // wall can be watched here and nothing more
    if (onWall) {
      fx("upscale", "Upscale", "Sharpen this clip, or smooth its motion.", true);
      fx("add-sound", "Add sound", "Sound made to fit this clip's picture.", true);
      fx("reframe", "Reframe", "The same clip in a new shape.", true);
      fx("remove-video-background", "Remove background", "Cut this clip's subject out.", false);
      out.push({ id: "editor", kind: "editor", label: "Open in the editor", title: "Start a cut with this clip. Free.", primary: false });
    }
    filed();
    return out;
  }

  if (r.output === "image" && r.image) {
    // "Edit image", not "Edit": the rail's Edit is the timeline editor
    fx("nano-banana-edit", "Edit image", "Change this still by describing the change.", true);
    // a variation re-draws a PROMPT; what an effect made has none
    if (!r.effect && (r.prompt ?? "").trim()) {
      out.push({
        id: "variation",
        kind: "variation",
        label: "Variation",
        title: `The same prompt and references, drawn again. ${CARD}`,
        primary: true,
      });
    }
    if (has.ready && has.effects.length) {
      out.push({
        id: "animate",
        kind: "gallery",
        tab: "video_effect",
        label: "Animate",
        title: "Pick a ready-made motion for this still. Browsing is free.",
        primary: true,
      });
    }
    out.push({
      id: "shot",
      kind: "shot",
      label: "Turn into a shot",
      title: "Attach it as a reference and write the shot it opens. Free.",
      primary: true,
    });
    fx("remove-background", "Remove background", "Cut the subject out on a transparent background.", false);
    fx("camera-move", "Camera move", "A named camera move on this still.", false);
    out.push({ id: "reference", kind: "reference", label: "Use as reference", title: "Attach it to the box. Free.", primary: false });
    out.push({ id: "element", kind: "element", label: "Make element", title: "Save it as a character, prop or place", primary: false });
    filed();
    if (r.conceptId) out.push({ id: "canvas", kind: "canvas", label: "Open the canvas", title: "Open its scene on the canvas", primary: false });
    if (!r.effect) out.push({ id: "reuse", kind: "reuse", label: "Reuse prompt", title: "Put its prompt back in the box. Free.", primary: false });
    return out;
  }

  if (r.output === "video" && r.conceptId) {
    out.push({ id: "queue", kind: "queue", label: "Send to Queue", title: "Pick this scene. Rendering is approved in the Queue.", primary: true });
    out.push({ id: "canvas", kind: "canvas", label: "Open the canvas", title: "Open the scene on the canvas", primary: true });
  }
  if (!r.effect) out.push({ id: "reuse", kind: "reuse", label: "Reuse prompt", title: "Put its prompt back in the box. Free.", primary: true });
  return out;
}

/** The row and the More menu: an overflow of one is not worth a menu. */
export function split(actions: ContinueAction[]): { row: ContinueAction[]; more: ContinueAction[] } {
  const row = actions.filter((a) => a.primary);
  const more = actions.filter((a) => !a.primary);
  return more.length === 1 ? { row: [...row, ...more], more: [] } : { row, more };
}

/* ── the price on the send button ──
   A send is free: the brain talks, and anything it makes waits on a card.
   The one send that can spend without another click is a still with Auto
   on. The button says so before it is pressed. */
export type SendCost = { credits: number | null; line: string };

export function sendCost(on: {
  /** the brain is answering sends (else a send makes directly) */
  guide: boolean;
  output: string;
  /** "ask" | "auto" */
  generate: string;
  /** what one still costs under the picked model; null when unknown */
  stillCredits: number | null;
  exempt: boolean;
}): SendCost {
  const spends = on.output === "image" && (on.generate === "auto" || !on.guide);
  if (!spends) {
    return {
      credits: null,
      line: on.output === "image" ? "Free to send. A still waits for your Approve beside its price." : "Free to send. Writing a scene costs nothing.",
    };
  }
  if (on.stillCredits === null) return { credits: null, line: "A still may be drawn on this send." };
  const price = `${on.stillCredits.toLocaleString("en-US")} credits${on.exempt ? ", not charged" : ""}`;
  return {
    credits: on.stillCredits,
    line: on.guide ? `Auto is on: a still drawn on this send costs ${price}.` : `This send draws a still: ${price}.`,
  };
}

/* KEYBOARD VERDICTS (2026-10-08, the front-end gap list vs LTX Studio and
   invideo, item 3; BACKLOG #15's first bullet). A review is mostly
   clearing cards, and a fast reviewer should not have to reach for the
   mouse: on the Queue and on a project's scene list,

     A  approve   (the Queue: arms the priced Approve, A again or Enter
                   renders -- a keystroke must never spend on its own;
                   a project: picks, which spends nothing)
     X  reject    (the Queue's reject / a project's "Not this one",
                   both with the toast's Undo)
     →  next      ← previous   (↓ ↑ too on the scene list, a column)

   The pure half: which key is which verdict, whether a keystroke was
   typed into something, and where the cursor goes next. The listener is
   lib/use-verdict-keys.ts.

   No "@/..." imports: tests/verdict-keys.test.mjs loads this with node. */

export type Verdict = "approve" | "reject" | "next" | "prev";

export type KeyLike = {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  repeat?: boolean;
  isComposing?: boolean;
  defaultPrevented?: boolean;
};

/** The verdict a keydown asks for, or null when it is not one of ours.
 *  A modified key is never ours (⌘K is the palette's, ⌘A selects all),
 *  and a held A or X decides once, not once per repeat. Caps Lock sends
 *  "A" without Shift, so the letter is read case-blind; Shift is left
 *  free. `vertical` adds ↓ ↑ for a list drawn as a column. */
export function verdictOf(e: KeyLike, { vertical = false }: { vertical?: boolean } = {}): Verdict | null {
  if (e.defaultPrevented || e.isComposing || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return null;
  switch (e.key) {
    case "ArrowRight":
      return "next";
    case "ArrowLeft":
      return "prev";
    case "ArrowDown":
      return vertical ? "next" : null;
    case "ArrowUp":
      return vertical ? "prev" : null;
  }
  if (e.repeat) return null;
  const k = e.key.toLowerCase();
  return k === "a" ? "approve" : k === "x" ? "reject" : null;
}

export type TargetLike = { tagName?: string; isContentEditable?: boolean } | null | undefined;

const TYPED = new Set(["INPUT", "TEXTAREA", "SELECT"]);

/** Whether a keystroke went into something that takes typing: an "a" in
 *  the composer, the length box, a renamed marker is a letter, never a
 *  verdict. */
export function typingIn(target: TargetLike): boolean {
  if (!target) return false;
  if (target.isContentEditable) return true;
  return !!target.tagName && TYPED.has(target.tagName.toUpperCase());
}

/** Where ← / → put the cursor: the next (dir 1) or previous (dir -1) id
 *  in `order` that `can` take a verdict. No cursor yet (or one on a card
 *  that left the list) starts at the first such card, or the last going
 *  back. At either end it stays put -- a review has an end, it does not
 *  wrap round to the cards already decided. Null when nothing can. */
export function moveCursor(
  order: readonly number[],
  current: number | null,
  dir: 1 | -1,
  can: (id: number) => boolean = () => true,
): number | null {
  const at = current == null ? -1 : order.indexOf(current);
  if (at < 0) {
    const from = dir === 1 ? order : [...order].reverse();
    return from.find(can) ?? null;
  }
  for (let i = at + dir; i >= 0 && i < order.length; i += dir) if (can(order[i])) return order[i];
  return can(current!) ? current : null;
}

/** Where the cursor goes once `current` is decided and leaves: the next
 *  card that can still take a verdict, else the one before it, else
 *  nowhere. */
export function nextAfter(
  order: readonly number[],
  current: number,
  can: (id: number) => boolean = () => true,
): number | null {
  const at = order.indexOf(current);
  const ok = (id: number) => id !== current && can(id);
  if (at < 0) return order.find(ok) ?? null;
  for (let i = at + 1; i < order.length; i += 1) if (ok(order[i])) return order[i];
  for (let i = at - 1; i >= 0; i -= 1) if (ok(order[i])) return order[i];
  return null;
}

/* The ⌘K palette's pure half (2026-10-08): how a typed query ranks the
   palette's own commands, how a matched word is marked, and how the arrow
   keys move. The SEARCH itself is the server's (GET /api/search,
   src/search.py) -- it matches every word, case-insensitively, and this
   file matches commands by the same rule so the two halves of one list
   agree about what "matches" means.

   No "@/..." imports: tests/palette.test.mjs loads this with node. */

/** The window event any button can fire to open the palette (the rail's
 *  ⌘K hint, the header's search button), optionally with a query typed. */
export const PALETTE_EVENT = "zpf:palette";

export function openPalette(query = ""): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(PALETTE_EVENT, { detail: { query } }));
}

/** The words a query is matched on -- the server's rule (src/search.py
 *  tokens): lowercased, whitespace-separated, at most six. */
export function tokens(query: string): string[] {
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 6);
}

/** How well `query` matches one command, 0 when it does not. Every word
 *  must appear in the title or the keywords; then a title that starts with
 *  the query beats one with a word that does, which beats a title holding
 *  every word, which beats a keyword-only match. An empty query matches
 *  everything equally. */
export function scoreCommand(query: string, title: string, keywords = ""): number {
  const words = tokens(query);
  if (!words.length) return 1;
  const t = title.toLowerCase();
  const hay = `${t} ${keywords.toLowerCase()}`;
  if (!words.every((w) => hay.includes(w))) return 0;
  const q = query.trim().toLowerCase();
  if (t.startsWith(q)) return 4;
  if (t.split(/[^a-z0-9]+/).some((word) => word.startsWith(words[0]))) return 3;
  if (words.every((w) => t.includes(w))) return 2;
  return 1;
}

/** The commands that match, best first, ties kept in the order given. */
export function rankCommands<T extends { title: string; keywords?: string }>(
  items: T[],
  query: string,
  limit = 8,
): T[] {
  return items
    .map((item, i) => ({ item, i, score: scoreCommand(query, item.title, item.keywords) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || a.i - b.i)
    .slice(0, limit)
    .map((x) => x.item);
}

export type Mark = { text: string; hit: boolean };

/** `text` cut into runs, `hit` where one of the query's words matched --
 *  what the palette draws bright. Case-insensitive; the original casing is
 *  kept. */
export function marks(text: string, query: string): Mark[] {
  const words = tokens(query).filter((w) => w.length > 0);
  if (!text) return [];
  if (!words.length) return [{ text, hit: false }];
  const low = text.toLowerCase();
  const hit = new Array<boolean>(text.length).fill(false);
  for (const w of words) {
    let at = low.indexOf(w);
    while (at >= 0) {
      for (let k = at; k < at + w.length; k++) hit[k] = true;
      at = low.indexOf(w, at + w.length);
    }
  }
  const out: Mark[] = [];
  for (let i = 0; i < text.length; i++) {
    const last = out[out.length - 1];
    if (last && last.hit === hit[i]) last.text += text[i];
    else out.push({ text: text[i], hit: hit[i] });
  }
  return out;
}

/** The next active row for an arrow key: wraps at both ends; nothing to
 *  move through is -1. */
export function step(active: number, delta: number, count: number): number {
  if (count <= 0) return -1;
  if (active < 0) return delta > 0 ? 0 : count - 1;
  return (((active + delta) % count) + count) % count;
}

/** The modifier this machine's ⌘K is pressed with. */
export function modKey(platform: string): "⌘" | "Ctrl" {
  return /mac|iphone|ipad|ipod/i.test(platform) ? "⌘" : "Ctrl";
}

/** Whether a keydown is the palette's shortcut: ⌘K on a Mac, Ctrl+K
 *  elsewhere (either works anywhere -- nobody should have to think). */
export function isPaletteKey(e: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }): boolean {
  return (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k";
}

/* The assistant card's words, as pure functions (2026-10-08): how much of
   an answer still being written to show next, and what the bubble says
   when an answer lands with the card shut. No imports, so
   tests/assistant-text.test.mjs runs them under plain node. */

/* One frame of typing: from what is on screen toward what the job has
   said so far. The gap closes by a 24th each frame (at least a character),
   so a poll's worth of words reads as typing and a long gap still catches
   up in well under a second. When the target no longer starts with what
   is shown -- a retry started the words over -- it starts from nothing. */
export function typeAhead(shown: string, target: string): string {
  const from = target.startsWith(shown) ? shown : "";
  const gap = target.length - from.length;
  return gap > 0 ? target.slice(0, from.length + Math.max(1, Math.ceil(gap / 24))) : from;
}

/* The bubble's line for an answer that landed while the card was shut: its
   next move when it named one, else its first sentence (a short opener like
   "Got it." runs on to the next), clipped at a word near 110 characters. */
export function headline(nudge: string | undefined, message: string): string {
  if (nudge?.trim()) return nudge.trim();
  const words = message.trim().replace(/\s+/g, " ");
  const first = /^(.{20,}?[.!?])(\s|$)/.exec(words)?.[1] ?? words;
  return first.length > 110 ? `${first.slice(0, 107).replace(/\s+\S*$/, "")}…` : first;
}

/* Is this sentence addressed to the studio, or is it a prompt?
   (2026-10-03, Mike: "the chat isn't conversing nor giving me what I
   need" -- typed into the box in Create, "Can we create an Element sheet
   of the sugar free redbull can" went to the image renderer as a prompt
   and came back as a still of a can.)

   The composer's box is ONE field for two things: a prompt the renderer
   draws from, and a line of talk the Guide answers. The Image | Video
   segment says which the box makes; it does not know what was typed.
   This is the reading of the words themselves, and it is deliberately
   narrow: a question mark, an opener a person uses to ask or steer
   ("can we", "let's", "how about", "I'm writing"), or the studio's own
   nouns that no renderer can draw (an element sheet, the board, the
   brief). "a Red Bull can on a wet steel counter" is a prompt and stays
   one; "Can we make the can an element?" is talk. No imports, so a
   plain `node --experimental-strip-types` can run it. */

const OPENERS =
  /^(?:(?:hey|hi|hello|ok|okay|yes|yeah|no|nope|thanks|thank you|please|so|and|but|also|actually|wait|hmm|right)[,!.\s]+)*(?:can|could|would|will|should|shall|do|does|did|is|are|am|was|were|what|what's|whats|when|where|which|who|whose|why|how|let's|lets|help|tell|explain|suggest|pitch|talk|walk me|think|i'm|im|i am|i'd|i was|i think|i have|i've|i don't|i dont|we're|we are|we should|we need to|can't|cant|don't|dont|isn't|doesn't|not sure|any (?:ideas?|thoughts?)|your (?:thoughts?|take)|thoughts)\b/i;

const STUDIO_NOUNS =
  /\b(?:element sheets?|reference sheets?|turnarounds?|as an element|an element of|into an element|make (?:it|this|that|the \w+) an element|the (?:board|queue|pipeline|guide|brief|spec))\b/i;

/** true when the words read as talk for the Guide rather than a prompt */
export function readsAsTalk(text: string): boolean {
  const t = text.trim();
  if (!t || t.startsWith("/") || t.startsWith("@")) return false;
  if (/\?\s*$/.test(t)) return true;
  return OPENERS.test(t) || STUDIO_NOUNS.test(t);
}

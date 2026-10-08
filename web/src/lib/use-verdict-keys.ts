/* The listener behind the keyboard verdicts (lib/verdict-keys.ts says which
   keys and why). One window keydown per page that uses it, and it answers
   only when the keystroke is plainly meant for the list:

   - focus is on the page itself (nothing focused) or inside `region` --
     never in the header, the assistant pill, the activity tray, the
     Director canvas or the brief beside the list;
   - not typed into a field;
   - not inside a dialog, a popover, a menu or a listbox (the palette, the
     preview overlay, the scene drawer, the renderer picker all keep their
     own keys).

   The palette's ⌘K runs in the capture phase and is a modified key, so
   the two never meet. `onVerdict` returns true when it used the key,
   which is then kept from scrolling the page. */
import { useEffect, useRef, type RefObject } from "react";
import { typingIn, verdictOf, type Verdict } from "@/lib/verdict-keys";

const ELSEWHERE = '[role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"]';

export function useVerdictKeys(
  region: RefObject<HTMLElement | null>,
  onVerdict: (verdict: Verdict) => boolean,
  { vertical = false, enabled = true }: { vertical?: boolean; enabled?: boolean } = {},
) {
  // the newest handler, so the listener is bound once and still reads this render's cards
  const handler = useRef(onVerdict);
  useEffect(() => {
    handler.current = onVerdict;
  });
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const verdict = verdictOf(e, { vertical });
      if (!verdict) return;
      const t = e.target instanceof HTMLElement ? e.target : null;
      const atRest = !t || t === document.body || t === document.documentElement;
      if (!atRest && !region.current?.contains(t)) return;
      if (typingIn(t) || t?.closest(ELSEWHERE)) return;
      if (handler.current(verdict)) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [region, vertical, enabled]);
}

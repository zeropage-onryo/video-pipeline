"use client";

/* The reference preview: ONE overlay for every studio surface that shows a
   scene's pictures (Pipeline, its drawer, Queue). The React port of
   app/static/zpf/preview.js (2026-09-17).

   A Base UI Dialog does the parts that are easy to get subtly wrong by
   hand: focus moves in on open and back to the thumbnail that opened it on
   close (`finalFocus`), Tab is trapped, Esc closes -- and closes only THIS
   dialog when it was opened from the drawer, because it is rendered inside
   the drawer's tree and Base UI treats that as a nested dialog. The arrow
   keys are a handler on the popup, so they exist only while it is mounted.

   Header "TITLE · REFERENCE n / N"; caption: filename left, shelf right
   (refs.sourceLabel -- the payload carries no attribution, see refs.ts);
   the strip jumps to an index, the current one ringed red. A picture that
   will not load is a labelled slate, never a blank (RefImg). */
import { useRef, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { cardFonts } from "@/components/studio/card-fonts";
import { RefImg } from "@/components/studio/concept-card";
import { fileName, sourceLabel } from "@/lib/refs";
import { API_URL } from "@/lib/api";

/* a rendered clip rather than a picture: the renders are mp4s */
const isClip = (url: string) => /\.(mp4|webm|mov)(\?|#|$)/i.test(url);

export type PreviewItem = { url: string; name?: string; source?: string; href?: string };
export type PreviewState = {
  title: string;
  kind: "REFERENCE" | "KEYFRAME" | "CLIP";
  items: PreviewItem[];
  index: number;
  /** the element that opened it; focus goes back there */
  trigger: HTMLElement | null;
};

const navBtn =
  "flex size-14 flex-none items-center justify-center rounded-full border border-noir-line bg-noir-panel text-bone! hover:border-bone max-sm:size-11 focus-visible:rounded-full!";

export function PreviewOverlay({ state, onClose }: { state: PreviewState; onClose: () => void }) {
  const items = state.items.filter((it) => it.url);
  const [at, setAt] = useState(Math.min(Math.max(0, state.index), Math.max(0, items.length - 1)));
  const closeRef = useRef<HTMLButtonElement>(null);
  if (!items.length) return null;
  const many = items.length > 1;
  const step = (d: number) => setAt((i) => (i + d + items.length) % items.length);
  const it = items[at];
  const kind = state.kind.toLowerCase();

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Popup
          initialFocus={closeRef}
          finalFocus={() => (state.trigger?.isConnected ? state.trigger : true)}
          onKeyDown={(e) => {
            if (!many) return;
            if (e.key === "ArrowLeft") step(-1);
            else if (e.key === "ArrowRight") step(1);
            else return;
            e.preventDefault();
          }}
          className={`${cardFonts} fixed inset-0 z-[1000] flex flex-col items-center gap-4 bg-[rgb(6_6_6/0.96)] px-[clamp(16px,4vw,56px)] py-6 font-plex text-xs text-bone outline-none`}
        >
          <div className="flex w-full flex-none items-center justify-between gap-4">
            <Dialog.Title className="min-w-0 truncate text-xs font-normal tracking-[0.12em] text-bone3" aria-live="polite">
              {state.title.toUpperCase()} · {state.kind} {at + 1} / {items.length}
            </Dialog.Title>
            <Dialog.Close
              ref={closeRef}
              aria-label="Close preview"
              className="flex size-11 flex-none items-center justify-center rounded-[8px] border border-noir-line text-bone! hover:border-bone focus-visible:rounded-[8px]!"
            >
              <X size={18} strokeWidth={2} aria-hidden />
            </Dialog.Close>
          </div>

          <div className="flex min-h-0 w-full flex-1 items-center justify-center gap-6 max-sm:gap-2">
            {many ? (
              <button type="button" className={navBtn} aria-label="Previous image" onClick={() => step(-1)}>
                <ChevronLeft size={20} strokeWidth={2} aria-hidden />
              </button>
            ) : null}
            <div className="flex h-full min-w-0 max-w-[1280px] flex-1 items-center justify-center">
              {isClip(it.url) ? (
                // a rendered shot: the clip itself, not a still of it
                // (2026-09-28: #384's first shot existed and nobody could play it)
                <video
                  key={it.url}
                  src={/^https?:/.test(it.url) ? it.url : `${API_URL}${it.url}`}
                  controls
                  // muted so the browser lets it start (autoplay with sound
                  // is refused and the element then never loaded at all,
                  // measured 2026-09-28); the controls unmute it. Set and
                  // started from the ref: React applies `muted` after the
                  // autoplay decision, so the attribute alone never plays.
                  ref={(el) => {
                    if (!el) return;
                    el.muted = true;
                    void el.play().catch(() => {});
                  }}
                  muted
                  preload="auto"
                  playsInline
                  className="block max-h-full max-w-full rounded-[6px] bg-black"
                  aria-label={`${kind} ${at + 1}: ${it.name || fileName(it.url)}`}
                />
              ) : (
              <RefImg
                key={it.url}
                url={it.url}
                alt={`${kind} ${at + 1}: ${it.name || fileName(it.url)}`}
                eager
                className="block size-full rounded-[6px] object-contain"
                deadLabel={`IMAGE UNAVAILABLE · ${it.name || fileName(it.url)}`}
                deadClassName="size-full rounded-[6px] border border-dashed border-[#5a2320] p-6 text-xs tracking-[0.14em]"
              />
              )}
            </div>
            {many ? (
              <button type="button" className={navBtn} aria-label="Next image" onClick={() => step(1)}>
                <ChevronRight size={20} strokeWidth={2} aria-hidden />
              </button>
            ) : null}
          </div>

          <div className="flex w-full max-w-[1280px] flex-none justify-between gap-4 text-bone2">
            <span className="min-w-0 truncate">{it.name || fileName(it.url)}</span>
            {/* the source is a link when the payload had a page for it */}
            {it.href ? (
              <a
                href={it.href}
                target="_blank"
                rel="noopener noreferrer"
                className="max-w-[60%] flex-none truncate text-bone underline underline-offset-[3px] hover:text-noir-red2"
              >
                {it.source} ↗
              </a>
            ) : (
              <span className="max-w-[60%] flex-none truncate text-bone3">{it.source ?? sourceLabel(it.url)}</span>
            )}
          </div>

          {many ? (
            <div className="flex max-w-full flex-none gap-2 overflow-x-auto p-1">
              {items.map((t, i) => (
                <button
                  type="button"
                  key={`${t.url}-${i}`}
                  aria-label={`Show ${kind} ${i + 1}`}
                  aria-current={i === at}
                  onClick={() => setAt(i)}
                  className={`h-11 w-16 flex-none overflow-hidden rounded-[4px] border-2 bg-noir-slate focus-visible:rounded-[4px]! ${i === at ? "border-noir-red" : "border-transparent"}`}
                >
                  {isClip(t.url) ? (
                    <span className="flex size-full items-center justify-center text-[10px] tracking-[0.1em] text-bone">
                      ▶ {i + 1}
                    </span>
                  ) : (
                    <RefImg url={t.url} thumb eager className="block size-full object-cover" deadLabel="" />
                  )}
                </button>
              ))}
            </div>
          ) : null}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

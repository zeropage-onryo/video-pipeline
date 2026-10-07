"use client";

/* A scene's drawer: everything its card will not print -- the logline, the
   hook, the timed shots, every reference, the gate's verdict and the prompt,
   editable in place. Moved here from the Pipeline page (2026-10-07) when the
   Pipeline tab was folded into the Projects board, so the project workspace
   draws the same drawer the board did. */
import Link from "next/link";
import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { sceneHref, type Concept } from "@/lib/studio-api";
import {
  GATE_DOT,
  ICON_BTN,
  NoReferenceSlate,
  RefImg,
  RefThumbs,
  TAG,
  TAG_DARK,
  brandName,
  gateOf,
  heroOf,
  partsOf,
  shotsLabel,
  windowLabel,
} from "@/components/studio/concept-card";

const K = "font-plex text-[11px] tracking-[0.14em] text-bone3";

export function DrawerBody({
  c,
  closeRef,
  promptOpen,
  onTogglePrompt,
  draft,
  onDraft,
  saving,
  onSave,
  onRefs,
  onHero,
  onCanvas,
}: {
  c: Concept;
  closeRef: React.RefObject<HTMLButtonElement | null>;
  promptOpen: boolean;
  onTogglePrompt: () => void;
  draft: string;
  onDraft: (text: string) => void;
  saving: boolean;
  onSave: (text: string) => void;
  onRefs: (index: number, trigger: HTMLElement) => void;
  onHero: (trigger: HTMLElement) => void;
  /** in a project workspace the canvas is beside the list: open it there */
  onCanvas?: () => void;
}) {
  const gate = gateOf(c);
  const hero = heroOf(c);
  const parts = partsOf(c);
  const refs = c.refs || [];
  const dirty = draft.trim() !== (c.prompt || "").trim();
  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <span className="font-plex text-xs tracking-[0.12em] text-bone3">
          {brandName(c.brand)} · CONCEPT #{c.id}
        </span>
        <Dialog.Close ref={closeRef} aria-label="Close details" className={ICON_BTN}>
          <X size={18} strokeWidth={2} aria-hidden />
        </Dialog.Close>
      </div>
      <div>
        <Dialog.Title className="m-0 mb-1.5 font-bebas text-5xl font-normal leading-[0.95] tracking-[0.02em] [overflow-wrap:anywhere] max-sm:text-[38px]">
          {c.title || "Untitled"}
        </Dialog.Title>
        {c.summary ? <p className="m-0 text-base text-bone2">{c.summary}</p> : null}
      </div>

      <button
        type="button"
        disabled={hero.kind === "none"}
        aria-label={hero.kind === "keyframe" ? "Preview keyframe" : hero.kind === "ref" ? "Preview reference 1" : "No image to preview"}
        onClick={(e) => onHero(e.currentTarget)}
        className="relative aspect-video w-full overflow-hidden rounded-[8px] border border-noir-line bg-noir-slate p-0 hover:enabled:border-bone focus-visible:rounded-[8px]! disabled:cursor-default"
      >
        {hero.kind === "none" ? (
          <NoReferenceSlate />
        ) : (
          <>
            <RefImg url={hero.url} eager className="block size-full object-cover" deadClassName="absolute inset-0 text-[11px] tracking-[0.16em]" />
            <span className={`${TAG} ${TAG_DARK} bottom-2.5 right-2.5`}>{hero.kind === "keyframe" ? "KEYFRAME" : "REF 1"} · CLICK TO ENLARGE</span>
          </>
        )}
      </button>

      <section className="flex min-w-0 flex-col gap-1.5">
        <div className={K}>LOGLINE</div>
        <p className="m-0 text-[15px] leading-normal [overflow-wrap:anywhere]">{c.logline || "—"}</p>
      </section>

      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <section className="flex min-w-0 flex-col gap-1.5">
          <div className={K}>HOOK · FRAME 1</div>
          <p className="m-0 text-sm leading-[1.45] [overflow-wrap:anywhere]">{c.hook || "—"}</p>
        </section>
        <section className="flex min-w-0 flex-col gap-1.5">
          <div className={K}>SHOTS · {shotsLabel(c)}</div>
          <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
            {parts.length ? (
              parts.map((p) => (
                <li key={p.n} className="flex gap-2.5 text-[13.5px] leading-[1.4] [overflow-wrap:anywhere]">
                  <span className="min-w-[52px] flex-none font-plex text-xs text-bone3">{windowLabel(p)}</span>
                  <span>{p.text || p.prompt || ""}</span>
                </li>
              ))
            ) : (
              <li className="flex gap-2.5 text-[13.5px]">
                <span className="min-w-[52px] flex-none font-plex text-xs text-bone3">—</span>
                <span>One shot · rendered whole</span>
              </li>
            )}
          </ol>
        </section>
      </div>

      <section className="flex min-w-0 flex-col gap-2">
        <div className={K}>REFERENCES · {refs.length}</div>
        <div className="flex flex-wrap gap-2">
          {refs.length ? (
            <RefThumbs concept={c} max={99} size="lg" onOpen={onRefs} />
          ) : (
            <span className="font-plex text-xs tracking-[0.06em] text-noir-red2">NO REFERENCES — ADD BEFORE QUEUE</span>
          )}
        </div>
      </section>

      <section className="flex min-w-0 flex-col gap-2.5 border-t border-noir-line pt-4">
        <div className="flex items-center justify-between gap-3">
          <span className="flex min-w-0 items-start gap-2 font-plex text-xs [overflow-wrap:anywhere]">
            <i className={`mt-[5px] size-2 flex-none rounded-full ${GATE_DOT[gate.level]}`} />
            <span>{gate.long}</span>
          </span>
          <button
            type="button"
            aria-expanded={promptOpen}
            aria-controls="ncdprompt"
            onClick={onTogglePrompt}
            className="h-11 flex-none rounded-[8px] border border-noir-line bg-transparent px-3.5 font-plex! text-xs! tracking-[0.08em] text-bone! hover:border-bone focus-visible:rounded-[8px]!"
          >
            {promptOpen ? "HIDE PROMPT" : "SHOW PROMPT"}
          </button>
        </div>
        {(c.warnings || []).length ? (
          <ul className="m-0 list-disc pl-[18px] text-[13px] text-gate-warn">
            {c.warnings!.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : null}
        {promptOpen ? (
          <div id="ncdprompt" className="flex flex-col gap-2">
            {/* the full prompt, in mono -- and editable in place, as the
                board's prompt always was here: Save appears once it differs */}
            <textarea
              value={draft}
              onChange={(e) => onDraft(e.target.value)}
              rows={Math.min(22, Math.max(6, Math.ceil(draft.length / 58)))}
              aria-label={`Prompt for ${c.title}`}
              placeholder="No prompt on this concept yet."
              className="m-0 w-full resize-y rounded-[6px] border border-noir-line bg-noir-bg p-3 font-plex! text-xs! leading-normal! text-bone2! outline-none focus:border-bone3"
            />
            <div className="flex items-center justify-between gap-3 font-plex text-[11px] text-bone3">
              <span>{draft.length} chars</span>
              {dirty ? (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => onSave(draft.trim())}
                  className="h-11 rounded-[8px] bg-noir-red px-4 font-plex! text-xs! tracking-[0.08em] text-noir-bg! hover:enabled:bg-noir-red2 disabled:opacity-50 focus-visible:rounded-[8px]!"
                >
                  SAVE PROMPT
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 font-plex text-[11px] tracking-[0.06em] text-bone3">
          {c.media_url ? (
            <a href={c.media_url} target="_blank" rel="noreferrer" className="text-noir-red! hover:text-noir-red2!">
              RENDERED CLIP ↗
            </a>
          ) : null}
          {onCanvas ? (
            <button type="button" onClick={onCanvas} className="bg-transparent p-0 font-plex! text-[11px]! tracking-[0.06em] text-bone2! hover:text-bone!">
              OPEN THE CANVAS →
            </button>
          ) : (
            <Link href={sceneHref(c.id, 1)} className="text-bone2! hover:text-bone!">
              OPEN THE CANVAS →
            </Link>
          )}
          {c.spark ? (
            <span className="max-w-full truncate" title={c.spark}>
              SPARK · {c.spark}
            </span>
          ) : null}
        </div>
      </section>
    </>
  );
}

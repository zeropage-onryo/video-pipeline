"use client";

/* Pipeline — the board you decide on, and nothing else (2026-09-12, the
   "ZPF Pipeline" design). A concept IS one scene IS one prompt, so this
   is one grid of cards and one question: which of these is worth the
   spend. Each card leads with its PICTURE, then the title and one line,
   then the references it was written against; the logline, the hook, the
   timed shots and the prompt are in the card's drawer (2026-09-17, the
   image-first restyle -- ported from app/static/zpf/scenes.js).

   Picking is the label (pick_rate) and puts the concept in front of the
   Queue; approving THERE renders. Leaving the board is archiving, never
   deleting — an unpicked row is the only negative signal this system
   collects. Only one-shot concepts are the unit; a legacy multi-shot row
   is left to the Dev Studio. */
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Dialog } from "@base-ui/react/dialog";
import { Archive, Check, Search, Undo2, Workflow, X } from "lucide-react";
import {
  announceQueueChange,
  archiveConcept,
  boardConcepts,
  pickConcept,
  updateShotPrompt,
  type Concept,
  type PickRate,
} from "@/lib/studio-api";
import { cardFonts } from "@/components/studio/card-fonts";
import {
  CARD,
  GATE_DOT,
  Hero,
  ICON_BTN,
  NoReferenceSlate,
  RefImg,
  RefThumbs,
  TAG,
  TAG_DARK,
  TitleBlock,
  brandName,
  gateOf,
  heroOf,
  partsOf,
  refItems,
  shotsLabel,
  stillsOf,
  windowLabel,
} from "@/components/studio/concept-card";
import { PreviewOverlay, type PreviewState } from "@/components/studio/preview-overlay";
import { useShell } from "@/components/studio/shell";

type Filter = "open" | "picked" | "archived";

/* Which concepts have their prompt open in the drawer. Out here, not in
   state: the board re-reads on every pick, and a prompt that snapped shut
   each time -- or when you left the page and came back -- would be worse
   than no toggle. (The vanilla board's `openPrompts`, same reason.) */
const openPrompts = new Set<number>();

function statusOf(c: Concept) {
  // A rendered clip also says WHO PAID: a subscription clip was made by
  // hand on the operator's own plan, not billed per call.
  if (c.archived) return c.graded ? "ARCHIVED · GRADED" : "ARCHIVED · AWAITING GRADE";
  if (c.media_url) return c.subscription ? "RENDERED · SUBSCRIPTION" : "RENDERED";
  if (c.picked) return "PICKED";
  if (c.parked) return "KEYFRAMED · IN QUEUE";
  return "";
}

const K = "font-plex text-[11px] tracking-[0.14em] text-bone3";

export default function PipelinePage() {
  const { me, brand, toast } = useShell();
  const [filter, setFilter] = useState<Filter>("open");
  const [query, setQuery] = useState("");
  const [all, setAll] = useState<Concept[] | null>(null);
  const [rate, setRate] = useState<PickRate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [drawer, setDrawer] = useState<{ id: number; trigger: HTMLElement | null } | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [, bump] = useState(0); // openPrompts lives outside state; this repaints its toggle
  const drawerClose = useRef<HTMLButtonElement>(null);
  // where focus goes back to. A ref, not the `drawer` state: by the time
  // Base UI asks (finalFocus), closing has already set that state to null.
  const drawerFrom = useRef<{ id: number; trigger: HTMLElement | null } | null>(null);

  /* ONE request per brand, and only the newest answer is kept. The page
     used to fire as soon as it mounted -- before the shell knew who was
     signed in, so with no brand -- and again once it did. The unfiltered
     answer is the bigger one and lands second, so the board showed BOTH
     brands' cards under a header naming one (2026-09-18: "zeropage · 21
     open" over 16 Antihero cards; the brand has 5). Waiting for `me` drops
     the first request; the sequence number drops any late one. */
  const seq = useRef(0);
  const load = () => {
    const mine = ++seq.current;
    boardConcepts(brand || undefined, true)
      .then((r) => {
        if (mine !== seq.current) return;
        setAll(r.items.filter((c) => c.is_scene));
        setRate(r.pick ?? null);
        setError(null);
      })
      .catch((e) => {
        if (mine === seq.current) setError(e instanceof Error ? e.message : "Concepts unavailable");
      });
  };
  useEffect(() => {
    if (!me) return; // the shell has not said who this is yet
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me, brand]);

  const open = useMemo(() => (all || []).filter((c) => !c.archived), [all]);
  const gone = useMemo(() => (all || []).filter((c) => c.archived), [all]);
  const picked = useMemo(() => open.filter((c) => c.picked), [open]);
  const shelf = filter === "archived" ? gone : filter === "picked" ? picked : open;
  const counts: Record<Filter, number> = { open: open.length, picked: picked.length, archived: gone.length };
  const needle = query.trim().toLowerCase();
  const cards = useMemo(
    () =>
      needle
        ? shelf.filter((c) =>
            `${c.title} ${c.summary} ${c.logline} ${c.spark || ""} #${c.id} ${c.n}`.toLowerCase().includes(needle),
          )
        : shelf,
    [shelf, needle],
  );
  const scope = `${brand || "—"} · ${open.length} open · ${gone.length} archived`;
  const countLine = rate?.generated ? `${scope} · ${rate.picked}/${rate.generated} picked all time, all brands` : scope;
  // the drawer reads the FRESH row, so a pick made while it is open reads back
  const shown = drawer ? (all || []).find((c) => c.id === drawer.id) || null : null;

  const act = async (c: Concept, fn: () => Promise<unknown>, done?: string) => {
    setBusy((b) => ({ ...b, [c.id]: true }));
    try {
      await fn();
      if (done) toast(done);
      load();
      announceQueueChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through", "err");
    } finally {
      setBusy((b) => ({ ...b, [c.id]: false }));
    }
  };

  const previewRefs = (c: Concept, index: number, trigger: HTMLElement) =>
    setPreview({ title: c.title, kind: "REFERENCE", index, trigger, items: refItems(c) });
  const previewStills = (c: Concept, trigger: HTMLElement) => {
    const stills = stillsOf(c);
    if (!stills.length) return (c.refs || []).length ? previewRefs(c, 0, trigger) : undefined;
    setPreview({ title: c.title, kind: "KEYFRAME", index: 0, trigger, items: stills.map((url) => ({ url })) });
  };
  const overlay = preview ? <PreviewOverlay key={`${preview.title}-${preview.kind}-${preview.index}`} state={preview} onClose={() => setPreview(null)} /> : null;

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="vhead" style={{ marginTop: 8 }}>
        <h2>Pipeline</h2>
        <span className="spacer" />
        <span className="m">{countLine}</span>
      </div>
      <div className="chead">
        <h3>Concepts</h3>
        <span className="spacer" />
        <label className="csearch">
          <Search strokeWidth={1.6} />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a concept…"
            aria-label="Find a concept"
          />
        </label>
        <div className="cats" style={{ margin: 0, padding: 0 }}>
          {(["open", "picked", "archived"] as Filter[]).map((f) => (
            <button type="button" key={f} className="cat" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f[0].toUpperCase() + f.slice(1)}
              {all ? <u>{counts[f]}</u> : null}
            </button>
          ))}
        </div>
      </div>

      {error ? <div className="stateline err" style={{ padding: "0 42px 14px" }}>{error}</div> : null}
      {all && !cards.length ? (
        <p className="stateline" style={{ padding: "0 42px" }}>
          {needle && shelf.length
            ? `Nothing here matches “${query.trim()}”`
            : filter === "archived"
            ? "Nothing archived yet"
            : filter === "picked"
              ? "Nothing picked yet — the check on a card sends it to Queue"
              : "No concepts open — type an idea on Studio and hit Create"}
        </p>
      ) : null}

      {/* Image-first (2026-09-17): the picture is the card. Title and the ONE
          card line under it (c.summary is preprod.concept_summary); the
          logline, hook and prompt are the drawer's and are never printed or
          trimmed here. */}
      <div className="mx-auto mb-4 grid max-w-[1680px] grid-cols-[repeat(auto-fill,minmax(min(400px,100%),1fr))] items-start gap-6 px-[42px] max-sm:px-4">
        {/* the board before its first answer: the cards' own shape, pulsing,
            rather than an empty page that reads as "no concepts" */}
        {!all && !error
          ? Array.from({ length: 6 }, (_, i) => (
              <div key={i} aria-hidden className={`${CARD} border-noir-line2 motion-safe:animate-pulse`}>
                <div className="aspect-video w-full rounded-t-[9px] bg-noir-slate" />
                <div className="flex flex-col gap-3 px-4 pb-4 pt-3.5">
                  <div className="h-[26px] w-2/3 rounded-[4px] bg-noir-slate" />
                  <div className="h-4 w-5/6 rounded-[4px] bg-noir-raise" />
                  <div className="flex h-[52px] gap-2">
                    {[0, 1, 2, 3].map((n) => (
                      <div key={n} className="size-[52px] rounded-[6px] bg-noir-raise" />
                    ))}
                  </div>
                </div>
              </div>
            ))
          : null}
        {cards.map((c) => {
          const gate = gateOf(c);
          const status = statusOf(c);
          const live = c.picked && !c.archived && !c.media_url;
          return (
            <article
              key={c.id}
              data-id={c.id}
              /* picked: a 1px border plus a 3px ring OUTSIDE the box, so nothing moves */
              className={`${CARD} ${c.picked && !c.archived ? "border-noir-red shadow-[0_0_0_3px_#E23B2E]" : "border-noir-line2"} ${c.archived ? "opacity-50 focus-within:opacity-100 hover:opacity-100" : ""}`}
            >
              <Hero concept={c} label={`Open details for ${c.title}`} onOpen={(trigger) => {
                  drawerFrom.current = { id: c.id, trigger };
                  setDrawer({ id: c.id, trigger });
                }}>
                <span className={`${TAG} ${TAG_DARK} left-3 top-3 max-w-[55%]`}>{brandName(c.brand)}</span>
                <span className={`${TAG} ${TAG_DARK} right-3 top-3 max-w-[40%]`} title={gate.long}>
                  <i className={`size-2 flex-none rounded-full ${GATE_DOT[gate.level]}`} />
                  {gate.short}
                  {gate.score === undefined ? null : ` · ${gate.score}/10`}
                </span>
                <span className={`${TAG} ${TAG_DARK} bottom-3 left-3 max-w-[45%]`}>{shotsLabel(c)}</span>
                {status ? (
                  <span className={`${TAG} bottom-3 right-3 max-w-[50%] text-noir-bg ${live ? "bg-noir-red" : "bg-bone"}`}>{status}</span>
                ) : null}
              </Hero>
              <div className="flex min-w-0 flex-col gap-3 px-4 pb-4 pt-3.5">
                {/* wraps only when the card is phone-narrow */}
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                  <TitleBlock concept={c} />
                  <div className="flex flex-none gap-1.5">
                    {c.archived ? (
                      <button
                        type="button"
                        className={ICON_BTN}
                        title="Put back on the board"
                        aria-label={`Put ${c.title} back on the board`}
                        disabled={busy[c.id]}
                        onClick={() => act(c, () => archiveConcept(c.id, false), "Back on the board")}
                      >
                        <Undo2 size={18} strokeWidth={2} aria-hidden />
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          className={`${ICON_BTN} ${c.picked ? "border-noir-red! bg-noir-red! text-noir-bg!" : "text-bone!"}`}
                          title={c.picked ? "Picked — click to unpick" : "Pick this"}
                          aria-label={`${c.picked ? "Unpick" : "Pick"} ${c.title}`}
                          aria-pressed={c.picked}
                          disabled={busy[c.id] || !!c.media_url}
                          onClick={() =>
                            act(c, () => pickConcept(c.id, !c.picked), c.picked ? "Unpicked" : `${c.n} is in the Queue — approving it there renders`)
                          }
                        >
                          <Check size={18} strokeWidth={2} aria-hidden />
                        </button>
                        {/* archives, never deletes: an unpicked row is the only negative signal */}
                        <button
                          type="button"
                          className={ICON_BTN}
                          title="Not this one — archive"
                          aria-label={`Archive ${c.title} — take it off the board`}
                          disabled={busy[c.id]}
                          onClick={() => act(c, () => archiveConcept(c.id, true), "Archived — it still counts")}
                        >
                          <Archive size={18} strokeWidth={2} aria-hidden />
                        </button>
                      </>
                    )}
                    <Link
                      href={`/studio/flows?concept=${c.id}&shot=1`}
                      className={`${ICON_BTN} hover:border-bone hover:text-bone!`}
                      title="Open in Director"
                      aria-label={`Open ${c.title} in Director`}
                    >
                      <Workflow size={18} strokeWidth={2} aria-hidden />
                    </Link>
                  </div>
                </div>
                <div className="flex min-h-[52px] min-w-0 flex-wrap items-center gap-2">
                  {(c.refs || []).length ? (
                    <RefThumbs concept={c} onOpen={(i, trigger) => previewRefs(c, i, trigger)} />
                  ) : (
                    <span className="font-plex text-xs tracking-[0.06em] text-noir-red2">NO REFERENCES — ADD BEFORE QUEUE</span>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {/* ── the drawer: everything the card will not print ── */}
      <Dialog.Root
        open={!!shown}
        onOpenChange={(o) => {
          if (!o) setDrawer(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Backdrop className="fixed inset-0 z-[900] bg-black/60" />
          <Dialog.Popup
            initialFocus={drawerClose}
            finalFocus={() => {
              // the board may have re-read under the drawer: find the card again
              const from = drawerFrom.current;
              if (from?.trigger?.isConnected) return from.trigger;
              return document.querySelector<HTMLElement>(`article[data-id="${from?.id}"] button`) ?? true;
            }}
            className={`${cardFonts} fixed inset-y-0 right-0 z-[901] flex w-[520px] max-w-full flex-col gap-[22px] overflow-y-auto border-l border-noir-line bg-[#121211] px-8 py-7 font-tight text-sm leading-normal text-bone outline-none max-sm:px-4 max-sm:py-5 [&>*]:flex-none`}
          >
            {shown ? (
              <DrawerBody
                c={shown}
                closeRef={drawerClose}
                promptOpen={openPrompts.has(shown.id)}
                onTogglePrompt={() => {
                  if (openPrompts.has(shown.id)) openPrompts.delete(shown.id);
                  else openPrompts.add(shown.id);
                  bump((n) => n + 1);
                }}
                draft={drafts[shown.id] ?? shown.prompt ?? ""}
                onDraft={(text) => setDrafts((d) => ({ ...d, [shown.id]: text }))}
                saving={!!busy[shown.id]}
                onSave={(text) =>
                  act(shown, () => updateShotPrompt(shown.id, 1, text), "Prompt saved to the concept").then(() =>
                    setDrafts((d) => {
                      const next = { ...d };
                      delete next[shown.id];
                      return next;
                    }),
                  )
                }
                onRefs={(i, trigger) => previewRefs(shown, i, trigger)}
                onHero={(trigger) => previewStills(shown, trigger)}
              />
            ) : null}
            {/* inside the drawer's tree, so Base UI nests it: Esc closes the
                preview first and the drawer stays */}
            {shown ? overlay : null}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
      {shown ? null : overlay}
    </section>
  );
}

function DrawerBody({
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
          <Link href={`/studio/flows?concept=${c.id}&shot=1`} className="text-bone2! hover:text-bone!">
            OPEN IN DIRECTOR →
          </Link>
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

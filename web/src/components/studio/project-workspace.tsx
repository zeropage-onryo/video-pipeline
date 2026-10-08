"use client";

/* A project's workspace (2026-10-07, Mike's call: the board of projects
   replaced the Pipeline and Director tabs, and clicking a project opens
   this).

   Three panes, one project:
   - LEFT, its scenes -- the Pipeline board's cards, narrowed to this
     project: Pick (it goes to the Queue), Not this one (archive, never
     delete), and the drawer with everything a card will not print.
     Clicking a card opens its canvas.
   - CENTRE, the Director canvas for the selected scene: the same
     FlowWorkspace the Director tab drew (React Flow, the `refs` multi-wire
     port, saved shot graphs, Send to Queue), only told it is embedded so its
     links stay in here. Moving to another scene goes through the canvas's
     own save first (`leave`), so an edit still waiting on its autosave is
     never dropped.
   - RIGHT, the brief, the look and what the project has learned. There is
     no second chat: the floating pill IS the Guide, and on this page it is
     scoped to the project (assistant-thread.tsx) and keeps its history.

   The workspace PICKS, never renders: approving in the Queue is still the
   one click that spends. A scene with no references still never reaches
   the Queue (preprod.reference_gate). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Dialog } from "@base-ui/react/dialog";
import { Archive, ArchiveRestore, ArrowLeft, Check, Info, PenLine, Trash2, Undo2, X } from "lucide-react";
import FlowWorkspace from "@/components/flows/flow-workspace";
import {
  QUEUE_EVENT,
  announceQueueChange,
  archiveConcept,
  archiveProject,
  boardConcepts,
  forgetProjectMemory,
  getProject,
  pickConcept,
  rememberActiveProject,
  updateProject,
  updateShotPrompt,
  workspaceHref,
  type Concept,
  type Project,
} from "@/lib/studio-api";
import { cardFonts } from "@/components/studio/card-fonts";
import { CARD, Hero, ICON_BTN, TAG, refItems, stillsOf } from "@/components/studio/concept-card";
import { DrawerBody } from "@/components/studio/scene-drawer";
import { DeleteProjectDialog } from "@/components/studio/project-delete";
import { PreviewOverlay, type PreviewState } from "@/components/studio/preview-overlay";
import { useShell } from "@/components/studio/shell";
import { useVerdictKeys } from "@/lib/use-verdict-keys";
import { moveCursor, nextAfter } from "@/lib/verdict-keys";

type Pane = "scenes" | "canvas" | "brief";

const KIND_LABEL: Record<string, string> = { pick: "picked", pass: "passed", edit: "edited", note: "note" };
const LABEL = "font-plex text-[11px] tracking-[0.14em] text-bone3";
const FIELD =
  "w-full resize-y rounded-[6px] border border-noir-line bg-noir-bg p-2.5 font-plex! text-xs! leading-normal! text-bone2! outline-none focus:border-bone3";

function statusOf(c: Concept) {
  if (c.archived) return "PASSED";
  if (c.media_url) return "RENDERED";
  if (c.picked) return "PICKED · IN QUEUE";
  if (c.parked) return "IN QUEUE";
  return "";
}

/* the prompts the drawer has open, outside state -- the list re-reads on
   every pick, and a prompt that snapped shut each time would be worse than
   no toggle (the board's own rule) */
const openPrompts = new Set<number>();

export function ProjectWorkspace({ id }: { id: number }) {
  const { me, toast } = useShell();
  const router = useRouter();
  const params = useSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  const [missing, setMissing] = useState("");
  const [scenes, setScenes] = useState<Concept[] | null>(null);
  const [showPassed, setShowPassed] = useState(false);
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [pane, setPane] = useState<Pane>("canvas");
  const [drawer, setDrawer] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [doomed, setDoomed] = useState<Project | null>(null);
  const [, bump] = useState(0);
  // the canvas's save-then-go, handed up by FlowWorkspace (CanvasNav.registerLeave)
  const leave = useRef<((destination: string) => Promise<boolean>) | null>(null);
  const drawerClose = useRef<HTMLButtonElement>(null);
  const seq = useRef(0);

  const loadProject = useCallback(
    () =>
      getProject(id)
        .then((p) => {
          setProject(p);
          setMissing("");
        })
        .catch((e) => setMissing(e instanceof Error ? e.message : "This project could not be opened")),
    [id],
  );
  const loadScenes = useCallback(() => {
    const mine = ++seq.current;
    // "all" = both halves of the window: a project's list holds its passed
    // scenes too, behind the toggle
    boardConcepts(undefined, "all", id)
      .then((r) => mine === seq.current && setScenes(r.items.filter((c) => c.is_scene)))
      .catch((e) => mine === seq.current && toast(e instanceof Error ? e.message : "Its scenes could not be read", "err"));
  }, [id, toast]);

  useEffect(() => {
    if (!me) return;
    void loadProject();
    loadScenes();
    // the composer and the pill's "put it in the composer" both write
    // inside the project that is open (the Projects page's old handover)
    rememberActiveProject(id);
  }, [me, id, loadProject, loadScenes]);
  // Send to Queue on the canvas, a decision in the Queue, a finished job:
  // the list re-reads so its PICKED / RENDERED marks are true
  useEffect(() => {
    window.addEventListener(QUEUE_EVENT, loadScenes);
    return () => window.removeEventListener(QUEUE_EVENT, loadScenes);
  }, [loadScenes]);

  const live = useMemo(() => (scenes || []).filter((c) => !c.archived), [scenes]);
  const passed = useMemo(() => (scenes || []).filter((c) => c.archived), [scenes]);
  const listed = showPassed ? [...live, ...passed] : live;
  const asked = Number(params.get("scene")) || null;
  const shot = Number(params.get("shot")) || undefined;
  // arrival is the nodes (Mike's standing rule): no scene named opens the
  // newest one still being worked on, else the newest
  // (a scene named in the URL that is not this project's falls back too,
  // once the list has said so -- the workspace only opens its own scenes)
  const askedHere = !!asked && (!scenes || scenes.some((c) => c.id === asked));
  const selected = askedHere ? asked : live.find((c) => !c.media_url)?.id || live[0]?.id || null;

  const go = useCallback((href: string) => router.push(href, { scroll: false }), [router]);
  const registerLeave = useCallback((fn: ((destination: string) => Promise<boolean>) | null) => {
    leave.current = fn;
  }, []);
  /** Open a scene on the canvas. On a phone that also flips to the canvas
   *  pane -- except from the keys, which keep the list in view. Resolves
   *  false when the canvas could not save and stayed where it was. */
  const select = async (sceneId: number, stay = false): Promise<boolean> => {
    if (!stay) setPane("canvas");
    if (sceneId === selected) return true;
    const href = workspaceHref(id, sceneId);
    if (leave.current) return leave.current(href);
    go(href);
    return true;
  };

  /** `undo`, when given, puts an Undo on the toast that runs through this
   *  same path -- the server's inverse route, then the list re-read.
   *  Resolves true when it went through. */
  const act = async (
    c: Concept,
    fn: () => Promise<unknown>,
    done?: string,
    undo?: { run: () => Promise<unknown>; done: string },
  ): Promise<boolean> => {
    setBusy((b) => ({ ...b, [c.id]: true }));
    try {
      await fn();
      if (done)
        toast(done, "ok", undo ? { action: { label: "Undo", run: () => act(c, undo.run, undo.done) } } : undefined);
      loadScenes();
      void loadProject(); // a pick or a pass is a lesson the memory just learned
      announceQueueChange();
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through", "err");
      return false;
    } finally {
      setBusy((b) => ({ ...b, [c.id]: false }));
    }
  };
  // the card's two verdicts, one body for its buttons and its keys
  const togglePick = (c: Concept) =>
    act(c, () => pickConcept(c.id, !c.picked), c.picked ? "Unpicked" : `${c.n} is in the Queue — approving there renders it`);
  const pass = (c: Concept) =>
    act(c, () => archiveConcept(c.id, true), `${c.n} archived — it still counts`, {
      run: () => archiveConcept(c.id, false),
      done: `${c.n} is back in the project`,
    });

  /* THE KEYS (lib/verdict-keys.ts), on the scene open on the canvas -- the
     ringed card: A picks it, X passes on it, and either moves the canvas
     on to the next scene still on the list; → ↓ and ← ↑ walk the list.
     Only while focus is on the list or on nothing: the canvas, its prompt
     bar and the brief keep their own keys. A pick spends nothing (the
     Queue's Approve is the spend), so A here is one press. */
  const sceneList = useRef<HTMLElement>(null);
  // where the keys last sent the canvas. A scene change waits on the
  // canvas's own save, so a second ↓ steps on from where the first one
  // went -- but a VERDICT waits for the canvas to get there: it only ever
  // lands on the scene that is ringed and drawn, never one still loading.
  const heading = useRef<number | null>(null);
  useEffect(() => {
    heading.current = selected;
  }, [selected]);
  const goTo = (sceneId: number | null) => {
    if (sceneId == null || sceneId === heading.current) return;
    const from = selected;
    heading.current = sceneId;
    // a save that failed leaves the canvas where it was (it says why);
    // the keys go back to pointing at that scene
    void select(sceneId, true).then((went) => {
      if (!went && heading.current === sceneId) heading.current = from;
    });
    const el = sceneList.current?.querySelector<HTMLElement>(`article[data-id="${sceneId}"]`);
    el?.focus({ preventScroll: true });
    el?.scrollIntoView({ block: "nearest" });
  };
  useVerdictKeys(
    sceneList,
    (verdict) => {
      if (!listed.length) return false;
      const order = listed.map((c) => c.id);
      const at = heading.current ?? selected;
      if (verdict === "next" || verdict === "prev" || !listed.some((c) => c.id === at)) {
        goTo(moveCursor(order, listed.some((c) => c.id === at) ? at : null, verdict === "prev" ? -1 : 1));
        return true;
      }
      // the canvas is still on its way to the scene the arrows asked for
      if (at !== selected) return true;
      const here = listed.find((c) => c.id === selected)!;
      if (busy[here.id]) return true;
      const onward = () => nextAfter(order, here.id, (sid) => live.some((c) => c.id === sid));
      if (verdict === "reject") {
        if (here.archived) toast(`${here.n} is passed already`);
        else void pass(here).then((ok) => ok && goTo(onward()));
      } else if (here.archived) toast(`${here.n} was passed — put it back first`, "err");
      else if (here.media_url) toast(`${here.n} is rendered already`);
      else if (here.picked) toast(`${here.n} is picked already — it waits in the Queue`);
      else void togglePick(here).then((ok) => ok && goTo(onward()));
      return true;
    },
    { vertical: true },
  );

  const shown = drawer ? (scenes || []).find((c) => c.id === drawer) || null : null;
  const previewRefs = (c: Concept, index: number, trigger: HTMLElement) =>
    setPreview({ title: c.title, kind: "REFERENCE", index, trigger, items: refItems(c) });
  const previewStills = (c: Concept, trigger: HTMLElement) => {
    const stills = stillsOf(c);
    if (!stills.length) return (c.refs || []).length ? previewRefs(c, 0, trigger) : undefined;
    setPreview({ title: c.title, kind: "KEYFRAME", index: 0, trigger, items: stills.map((url) => ({ url })) });
  };
  const overlay = preview ? (
    <PreviewOverlay key={`${preview.title}-${preview.kind}-${preview.index}`} state={preview} onClose={() => setPreview(null)} />
  ) : null;

  if (missing && !project) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center font-tight text-bone">
        <p className="m-0 text-[15px] text-bone2">{missing}</p>
        <Link href="/studio/projects" className="text-bone!">
          ← All projects
        </Link>
      </div>
    );
  }

  const paneClass = (p: Pane) => (pane === p ? "" : "max-lg:hidden");

  return (
    <div className={`${cardFonts} absolute inset-0 flex flex-col font-tight text-sm text-bone [color-scheme:dark]`}>
      {/* phones: one pane at a time */}
      <nav className="hidden gap-1 border-b border-noir-line px-3 py-2 max-lg:flex" aria-label="Workspace panes">
        {(["scenes", "canvas", "brief"] as Pane[]).map((p) => (
          <button
            type="button"
            key={p}
            aria-pressed={pane === p}
            onClick={() => setPane(p)}
            className="h-9 flex-1 rounded-[6px] border border-noir-line bg-transparent font-plex! text-[11px]! tracking-[0.1em] text-bone2! aria-pressed:border-bone aria-pressed:text-bone!"
          >
            {p === "scenes" ? `SCENES · ${live.length}` : p === "canvas" ? "CANVAS" : "BRIEF"}
          </button>
        ))}
      </nav>
      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_300px] max-lg:grid-cols-1 max-2xl:grid-cols-[260px_minmax(0,1fr)_260px]">
        {/* ── the scenes ── */}
        <aside
          ref={sceneList}
          className={`${paneClass("scenes")} flex min-h-0 flex-col border-r border-noir-line bg-noir-well`}
          aria-label="Scenes"
        >
          <div className="flex items-center gap-2 border-b border-noir-line px-3 py-2.5">
            <Link href="/studio/projects" className={`${ICON_BTN} size-9!`} title="All projects" aria-label="All projects">
              <ArrowLeft size={16} strokeWidth={2} aria-hidden />
            </Link>
            <div className="min-w-0 flex-1">
              <div className={LABEL}>PROJECT</div>
              <div className="truncate font-bebas text-[22px] leading-none tracking-[0.03em]" title={project?.title}>
                {project?.title || "…"}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between gap-2 px-3 pb-1 pt-3">
            <span className={LABEL}>SCENES · {live.length}</span>
            {passed.length ? (
              <button
                type="button"
                onClick={() => setShowPassed((v) => !v)}
                className="bg-transparent p-0 font-plex! text-[11px]! tracking-[0.06em] text-bone3! hover:text-bone!"
              >
                {showPassed ? "HIDE PASSED" : `SHOW ${passed.length} PASSED`}
              </button>
            ) : null}
          </div>
          {listed.length ? (
            <div className="zkeys px-3 pb-1 max-lg:hidden!" aria-hidden>
              <kbd>A</kbd> pick · <kbd>X</kbd> pass · <kbd>↑</kbd>
              <kbd>↓</kbd> move
            </div>
          ) : null}
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 pb-28">
            {!scenes ? (
              Array.from({ length: 3 }, (_, i) => (
                <div key={i} aria-hidden className={`${CARD} border-noir-line2 motion-safe:animate-pulse`}>
                  <div className="aspect-video w-full rounded-t-[9px] bg-noir-slate" />
                  <div className="h-12" />
                </div>
              ))
            ) : !listed.length ? (
              <p className="m-0 text-[13.5px] leading-normal text-bone2">
                No scenes yet. Ask the assistant to continue the story, or{" "}
                <Link href={`/studio?project=${id}`} onClick={() => rememberActiveProject(id)}>
                  write one on Create
                </Link>{" "}
                — it is filed here.
              </p>
            ) : (
              listed.map((c) => {
                const on = c.id === selected;
                const status = statusOf(c);
                return (
                  <article
                    key={c.id}
                    data-id={c.id}
                    // focusable by the keys (never by Tab): the red ring is the focus mark
                    tabIndex={-1}
                    aria-current={on ? "true" : undefined}
                    className={`${CARD} outline-none ${on ? "border-noir-red shadow-[0_0_0_2px_var(--signal)]" : "border-noir-line2"} ${c.archived ? "opacity-50 hover:opacity-100" : ""}`}
                  >
                    <Hero concept={c} label={`Open ${c.title} on the canvas`} onOpen={() => select(c.id)}>
                      {status ? (
                        <span className={`${TAG} bottom-2 right-2 bg-bone text-noir-bg`}>{status}</span>
                      ) : null}
                    </Hero>
                    <div className="flex min-w-0 items-center gap-2 px-3 py-2.5">
                      <button
                        type="button"
                        onClick={() => select(c.id)}
                        className="min-w-0 flex-1 bg-transparent p-0 text-left"
                        title={c.summary || c.title}
                      >
                        <span className="block truncate font-bebas text-[20px] leading-none tracking-[0.03em] text-bone">
                          {c.title || "Untitled"}
                        </span>
                        <span className="block truncate font-plex text-[10.5px] tracking-[0.06em] text-bone3">
                          {c.n}
                          {(c.refs || []).length ? ` · ${c.refs.length} REFS` : " · NO REFERENCES"}
                        </span>
                      </button>
                      {c.archived ? (
                        <button
                          type="button"
                          className={`${ICON_BTN} size-9!`}
                          title="Put back in the project"
                          aria-label={`Put ${c.title} back`}
                          disabled={busy[c.id]}
                          onClick={() => act(c, () => archiveConcept(c.id, false), `${c.n} is back in the project`)}
                        >
                          <Undo2 size={16} strokeWidth={2} aria-hidden />
                        </button>
                      ) : (
                        <>
                          <button
                            type="button"
                            className={`${ICON_BTN} size-9! ${c.picked ? "border-noir-red! bg-noir-red! text-noir-bg!" : "text-bone!"}`}
                            title={c.picked ? "Picked — click to unpick" : "Pick this (A) — it goes to the Queue, where approving renders"}
                            aria-label={`${c.picked ? "Unpick" : "Pick"} ${c.title}`}
                            aria-pressed={c.picked}
                            aria-keyshortcuts={on && !c.picked ? "A" : undefined}
                            disabled={busy[c.id] || !!c.media_url}
                            onClick={() => togglePick(c)}
                          >
                            <Check size={16} strokeWidth={2} aria-hidden />
                          </button>
                          <button
                            type="button"
                            className={`${ICON_BTN} size-9!`}
                            title="Not this one — archive (X)"
                            aria-label={`Archive ${c.title}`}
                            aria-keyshortcuts={on ? "X" : undefined}
                            disabled={busy[c.id]}
                            onClick={() => pass(c)}
                          >
                            <Archive size={16} strokeWidth={2} aria-hidden />
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        className={`${ICON_BTN} size-9!`}
                        title="Details, shots and the prompt"
                        aria-label={`Details for ${c.title}`}
                        onClick={() => setDrawer(c.id)}
                      >
                        <Info size={16} strokeWidth={2} aria-hidden />
                      </button>
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </aside>

        {/* ── the canvas ── */}
        <div className={`${paneClass("canvas")} relative min-h-0 min-w-0 max-lg:h-full`}>
          {selected ? (
            <FlowWorkspace
              key={`${selected}:${shot || "first"}`}
              conceptId={selected}
              shotN={selected === asked ? shot : undefined}
              nav={{
                embedded: true,
                backHref: "/studio/projects",
                backLabel: "All projects",
                hrefFor: (sceneId, n) => workspaceHref(id, sceneId, n),
                go,
                registerLeave,
              }}
            />
          ) : scenes ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
              <p className="m-0 font-bebas text-[30px] leading-none tracking-[0.03em]">Nothing on the canvas yet</p>
              <p className="m-0 max-w-[420px] text-[14px] text-bone2">
                A scene written in this project opens here. Ask the assistant to continue the story, or write one on{" "}
                <Link href={`/studio?project=${id}`} onClick={() => rememberActiveProject(id)}>
                  Create
                </Link>
                .
              </p>
            </div>
          ) : null}
        </div>

        {/* ── the brief, the look, the memory ── */}
        <aside className={`${paneClass("brief")} min-h-0 overflow-y-auto border-l border-noir-line bg-noir-well`} aria-label="Project brief">
          {project ? (
            <ProjectPanel
              key={project.id}
              project={project}
              onSaved={setProject}
              onChanged={() => void loadProject()}
              onDelete={() => setDoomed(project)}
            />
          ) : (
            <p className="m-0 p-4 text-[13px] text-bone3">Opening…</p>
          )}
        </aside>
      </div>

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
            className={`${cardFonts} fixed inset-y-0 right-0 z-[901] flex w-[520px] max-w-full flex-col gap-[22px] overflow-y-auto border-l border-noir-line bg-noir-panel px-8 py-7 font-tight text-sm leading-normal text-bone outline-none max-sm:px-4 max-sm:py-5 [&>*]:flex-none`}
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
                  act(shown, () => updateShotPrompt(shown.id, 1, text), "Prompt saved to the scene").then(() =>
                    setDrafts((d) => {
                      const next = { ...d };
                      delete next[shown.id];
                      return next;
                    }),
                  )
                }
                onRefs={(i, trigger) => previewRefs(shown, i, trigger)}
                onHero={(trigger) => previewStills(shown, trigger)}
                onCanvas={() => {
                  setDrawer(null);
                  select(shown.id);
                }}
              />
            ) : null}
            {shown ? overlay : null}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
      {shown ? null : overlay}

      <DeleteProjectDialog
        project={doomed}
        onClose={() => setDoomed(null)}
        onDeleted={(p) => {
          setDoomed(null);
          rememberActiveProject(null);
          toast(`“${p.title}” and its chat history are deleted — its scenes were kept`);
          router.push("/studio/projects");
        }}
      />
    </div>
  );
}

/* The right pane: the project's name, brief and look (each saved with one
   button), what it has learned (each lesson removable), and archive /
   delete. The look is the project's own -- the studio imposes none. */
function ProjectPanel({
  project,
  onSaved,
  onChanged,
  onDelete,
}: {
  project: Project;
  onSaved: (p: Project) => void;
  onChanged: () => void;
  onDelete: () => void;
}) {
  const { toast } = useShell();
  const [title, setTitle] = useState(project.title);
  const [brief, setBrief] = useState(project.brief);
  const [look, setLook] = useState(project.look ?? "");
  const [saving, setSaving] = useState(false);
  const dirty = title.trim() !== project.title || brief !== project.brief || look !== (project.look ?? "");

  const save = async () => {
    if (!title.trim()) return toast("A project needs a name", "err");
    setSaving(true);
    try {
      onSaved(await updateProject(project.id, { title: title.trim(), brief, look }));
      toast("Saved — the next scene in this project is written against it");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "err");
    } finally {
      setSaving(false);
    }
  };
  const forget = async (at: string) => {
    try {
      await forgetProjectMemory(project.id, at);
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not remove that", "err");
    }
  };
  const toggleArchive = async () => {
    try {
      const was = project.archived;
      await archiveProject(project.id, !was);
      toast(was ? "Back on the board" : "Archived — nothing in it was deleted", "ok", {
        action: {
          label: "Undo",
          run: () =>
            archiveProject(project.id, was).then(() => {
              toast(was ? "Archived — nothing in it was deleted" : "Back on the board");
              onChanged();
            }),
        },
      });
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not archive", "err");
    }
  };
  const memory = [...project.memory].reverse();

  return (
    <div className="flex flex-col gap-5 p-4 pb-28">
      {/* at the top, clear of the floating pill at the bottom corner */}
      <div className="flex gap-2 border-b border-noir-line pb-4">
        <button
          type="button"
          onClick={() => void toggleArchive()}
          className="flex h-10 flex-1 items-center justify-center gap-2 rounded-[8px] border border-noir-line bg-transparent font-plex! text-[11px]! tracking-[0.08em] text-bone2! hover:border-bone"
        >
          {project.archived ? <ArchiveRestore size={14} aria-hidden /> : <Archive size={14} aria-hidden />}
          {project.archived ? "RESTORE" : "ARCHIVE"}
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="flex h-10 flex-1 items-center justify-center gap-2 rounded-[8px] border border-noir-line bg-transparent font-plex! text-[11px]! tracking-[0.08em] text-bone2! hover:border-noir-red hover:text-noir-red!"
        >
          <Trash2 size={14} aria-hidden /> DELETE
        </button>
      </div>
      <label className="flex flex-col gap-1.5">
        <span className={LABEL}>NAME</span>
        <input
          value={title}
          maxLength={120}
          onChange={(e) => setTitle(e.target.value)}
          className="h-10 rounded-[6px] border border-noir-line bg-noir-bg px-2.5 text-[14px] text-bone outline-none focus:border-bone3"
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className={LABEL}>BRIEF — EVERY SCENE HERE IS WRITTEN AGAINST IT</span>
        <textarea
          value={brief}
          rows={8}
          onChange={(e) => setBrief(e.target.value)}
          placeholder={"FOR: …\nLOOK: …\nALWAYS: …\nNEVER: …"}
          className={FIELD}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className={LABEL}>LOOK — EMPTY IMPOSES NONE</span>
        <textarea
          value={look}
          rows={4}
          onChange={(e) => setLook(e.target.value)}
          placeholder="Palette, light, lens, texture…"
          className={FIELD}
        />
      </label>
      {dirty ? (
        <button
          type="button"
          disabled={saving}
          onClick={() => void save()}
          className="h-10 rounded-[8px] bg-noir-red px-4 font-plex! text-xs! tracking-[0.08em] text-noir-bg! hover:enabled:bg-noir-red2 disabled:opacity-50"
        >
          {saving ? "SAVING…" : "SAVE"}
        </button>
      ) : null}
      <Link
        href={`/studio?project=${project.id}`}
        onClick={() => rememberActiveProject(project.id)}
        className="flex h-10 items-center justify-center gap-2 rounded-[8px] border border-noir-line font-plex! text-xs! tracking-[0.08em] text-bone! hover:border-bone"
      >
        <PenLine size={14} strokeWidth={2} aria-hidden /> WRITE A SCENE IN THIS PROJECT
      </Link>

      <section className="flex flex-col gap-2">
        <span className={LABEL}>WHAT IT HAS LEARNED · {memory.length}</span>
        {memory.length ? (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {memory.map((m) => (
              <li key={m.at} className="group flex items-start gap-2 text-[12.5px] leading-snug">
                <span
                  className={`mt-0.5 flex-none rounded px-1.5 py-0.5 font-plex text-[9.5px] uppercase tracking-wide ${
                    m.kind === "pass" ? "bg-noir-red/15 text-noir-red2" : "bg-gate-pass/15 text-gate-pass"
                  }`}
                >
                  {KIND_LABEL[m.kind] || m.kind}
                </span>
                <span className="min-w-0 flex-1 text-bone2 [overflow-wrap:anywhere]">{m.text}</span>
                <button
                  type="button"
                  onClick={() => void forget(m.at)}
                  className="flex-none bg-transparent p-0 text-bone3! opacity-0 transition hover:text-bone! focus-visible:opacity-100 group-hover:opacity-100"
                  title="Forget this — it stops steering the project"
                  aria-label="Forget"
                >
                  <X size={13} />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-[12.5px] text-bone3">
            Nothing yet. Pick, pass on or edit scenes here and the project remembers.
          </p>
        )}
      </section>

    </div>
  );
}

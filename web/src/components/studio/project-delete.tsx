"use client";

/* Delete a project, for good (2026-10-07, Mike's call). The one place the
   studio deletes rather than archives, so the confirm says exactly what
   goes and what stays:

   - goes: the brief, the look, what the project learned, and its chat
     history -- the conversation the pill had inside it;
   - stays: every scene. They are DETACHED, never deleted, so a rendered
     clip and its row on the Assets wall are untouched. A scene with no clip
     yet is left outside any project, with no board to appear on, so the
     dialog names each one rather than letting them quietly drop.

   Archive is the other door (hide it, keep everything) and sits beside
   Delete on both the board and the workspace. */
import { useEffect, useRef, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { deleteProject, projectScenes, type Project } from "@/lib/studio-api";
import { cardFonts } from "@/components/studio/card-fonts";

type Scene = { id: number; title: string; rendered: boolean };

export function DeleteProjectDialog({
  project,
  onClose,
  onDeleted,
}: {
  /** the project to delete; null keeps the dialog closed */
  project: Project | null;
  onClose: () => void;
  onDeleted: (project: Project) => void;
}) {
  // keyed by the project they were read for, so reopening on another
  // project never shows the first one's scenes
  const [read, setRead] = useState<{ id: number; scenes: Scene[] | null; error: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState("");
  const keep = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!project) return;
    let live = true;
    projectScenes(project.id)
      .then((r) => live && setRead({ id: project.id, scenes: r.items, error: "" }))
      .catch((e) =>
        live && setRead({ id: project.id, scenes: null, error: e instanceof Error ? e.message : "could not read its scenes" }),
      );
    return () => {
      live = false;
    };
  }, [project]);

  const mine = project && read?.id === project.id ? read : null;
  const scenes = mine?.scenes ?? null;
  const loose = (scenes || []).filter((s) => !s.rendered);
  const rendered = (scenes || []).filter((s) => s.rendered).length;

  const go = async () => {
    if (!project) return;
    setBusy(true);
    setFailed("");
    try {
      await deleteProject(project.id);
      onDeleted(project);
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "That did not go through");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root
      open={!!project}
      onOpenChange={(o) => {
        if (!o && !busy) {
          setFailed("");
          onClose();
        }
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-[950] bg-black/70" />
        <Dialog.Popup
          initialFocus={keep}
          className={`${cardFonts} fixed left-1/2 top-1/2 z-[951] flex max-h-[85vh] w-[520px] max-w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-[10px] border border-noir-line bg-[#121211] p-6 font-tight text-sm leading-normal text-bone outline-none max-sm:p-4`}
        >
          {project ? (
            <>
              <Dialog.Title className="m-0 font-bebas text-[34px] font-normal leading-none tracking-[0.02em] [overflow-wrap:anywhere]">
                Delete “{project.title}”?
              </Dialog.Title>
              <Dialog.Description className="m-0 text-[14.5px] text-bone2">
                Its brief, its look, what it has learned and <b className="text-bone">its whole chat history</b> are
                deleted for good. This cannot be undone. To hide it and keep everything, archive it instead.
              </Dialog.Description>
              <div className="flex flex-col gap-2 rounded-[8px] border border-noir-line p-3 text-[13.5px]">
                <span className="font-plex text-[11px] tracking-[0.12em] text-bone3">WHAT HAPPENS TO ITS SCENES</span>
                {mine?.error ? (
                  <span className="text-noir-red2">Could not read its scenes: {mine.error}. They are kept either way.</span>
                ) : scenes === null ? (
                  <span className="text-bone3">Reading its scenes…</span>
                ) : !scenes.length ? (
                  <span className="text-bone2">It has no scenes.</span>
                ) : (
                  <>
                    <span className="text-bone2">
                      Every scene is kept, outside any project.
                      {rendered ? ` ${rendered} rendered clip${rendered === 1 ? " stays" : "s stay"} on the Assets wall.` : ""}
                    </span>
                    {loose.length ? (
                      <>
                        <span className="text-bone2">
                          {loose.length === 1 ? "This scene has" : `These ${loose.length} scenes have`} no clip yet and
                          will be on no board afterwards:
                        </span>
                        <ul className="m-0 flex max-h-40 list-none flex-col gap-1 overflow-y-auto p-0">
                          {loose.map((s) => (
                            <li key={s.id} className="flex gap-2">
                              <span className="flex-none font-plex text-xs text-bone3">#{s.id}</span>
                              <span className="truncate">{s.title || "Untitled"}</span>
                            </li>
                          ))}
                        </ul>
                      </>
                    ) : null}
                  </>
                )}
              </div>
              {failed ? (
                <p className="m-0 text-noir-red2" role="alert">
                  {failed}
                </p>
              ) : null}
              <div className="flex flex-wrap justify-end gap-2">
                <Dialog.Close
                  ref={keep}
                  disabled={busy}
                  className="h-11 rounded-[8px] border border-noir-line bg-transparent px-4 font-plex! text-xs! tracking-[0.08em] text-bone! hover:enabled:border-bone"
                >
                  KEEP IT
                </Dialog.Close>
                <button
                  type="button"
                  disabled={busy || (scenes === null && !mine?.error)}
                  onClick={() => void go()}
                  className="h-11 rounded-[8px] bg-noir-red px-4 font-plex! text-xs! tracking-[0.08em] text-noir-bg! hover:enabled:bg-noir-red2 disabled:opacity-50"
                >
                  {busy ? "DELETING…" : "DELETE PROJECT AND CHAT"}
                </button>
              </div>
            </>
          ) : null}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

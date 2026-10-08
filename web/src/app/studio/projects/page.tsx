"use client";

/* Projects — the studio's home (2026-10-07, Mike's call).

   A concept is one scene; a PROJECT is what holds scenes -- a client's ad,
   a short, a launch -- with its own brief, look and memory. This board of
   projects replaced both the Pipeline tab and the standalone Director tab:
   a card opens the project's workspace (its scenes, the Director canvas and
   the assistant pill scoped to it), where the deciding and the canvas work
   happen.

   Two things this page deliberately does not have:
   - a "New project" control. Projects are made only through the Guide --
     tell the pill "make a project for …", or "save this as a project" after
     a conversation. An empty board says so and points at the pill.
   - a section for scenes outside any project. A single video made with no
     project is finished on the Assets wall, not here; the board is projects
     only.

   Archive hides a project and keeps everything. Delete is the one real
   delete in the studio and takes the project's chat history with it; its
   scenes are detached, never deleted (components/studio/project-delete). */
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Archive, ArchiveRestore, MessageCircle, Search, Trash2 } from "lucide-react";
import { archiveProject, listProjects, workspaceHref, type Project } from "@/lib/studio-api";
import { CARD, ICON_BTN, RefImg } from "@/components/studio/concept-card";
import { DeleteProjectDialog } from "@/components/studio/project-delete";
import { useShell } from "@/components/studio/shell";

type Shelf = "active" | "archived";

/** "today", "yesterday", "3 days ago", else the date */
function touched(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const days = Math.floor((Date.now() - t) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** the brief's first real line, for the card -- never the label lines' keys */
function briefLine(p: Project): string {
  const line = (p.brief || "")
    .split("\n")
    .map((l) => l.replace(/^\s*(FOR|LOOK|PEOPLE & PRODUCT|ALWAYS|NEVER)\s*:\s*/i, "").trim())
    .find(Boolean);
  return line || "No brief yet — the scenes follow what you ask for.";
}

export default function ProjectsBoard() {
  const { me, brand, toast } = useShell();
  const [shelf, setShelf] = useState<Shelf>("active");
  const [query, setQuery] = useState("");
  // keyed by what it was read for, so an account switch never shows the
  // previous account's projects
  const [read, setRead] = useState<{ key: string; items: Project[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [doomed, setDoomed] = useState<Project | null>(null);
  const seq = useRef(0);
  const key = `${brand}:${shelf}`;

  const load = () => {
    const mine = ++seq.current;
    const at = key;
    // archived=true is every project; the Archived shelf is its archived half
    listProjects(shelf === "archived")
      .then((r) => {
        if (mine !== seq.current) return;
        setRead({ key: at, items: shelf === "archived" ? r.items.filter((p) => p.archived) : r.items });
        setError(null);
      })
      .catch((e) => {
        if (mine === seq.current) setError(e instanceof Error ? e.message : "Projects unavailable");
      });
  };
  // an Undo pressed later re-reads the shelf showing when it is pressed
  const latestLoad = useRef(() => load());
  useEffect(() => {
    latestLoad.current = () => load();
  });
  useEffect(() => {
    if (!me) return; // the shell has not said who this is yet
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me, brand, shelf]);

  const items = read && read.key === key ? read.items : null;
  const needle = query.trim().toLowerCase();
  const shown = useMemo(
    () => (items || []).filter((p) => !needle || `${p.title} ${p.brief}`.toLowerCase().includes(needle)),
    [items, needle],
  );

  const toggleArchive = async (p: Project) => {
    setBusy((b) => ({ ...b, [p.id]: true }));
    try {
      await archiveProject(p.id, !p.archived);
      toast(p.archived ? `“${p.title}” is back on the board` : `“${p.title}” archived — nothing in it was deleted`, "ok", {
        action: {
          label: "Undo",
          run: () =>
            archiveProject(p.id, p.archived).then(() => {
              toast(p.archived ? `“${p.title}” archived — nothing in it was deleted` : `“${p.title}” is back on the board`);
              latestLoad.current();
            }),
        },
      });
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through", "err");
    } finally {
      setBusy((b) => ({ ...b, [p.id]: false }));
    }
  };

  return (
    <section className="view" style={{ paddingTop: 0 }}>
      <div className="vhead" style={{ marginTop: 8 }}>
        <h2>Projects</h2>
        <span className="spacer" />
        <span className="m">
          {items ? `${items.length} ${shelf === "archived" ? "archived" : "active"}` : brand || "—"}
        </span>
      </div>
      <div className="chead">
        <h3>{shelf === "archived" ? "Archived" : "Your projects"}</h3>
        <span className="spacer" />
        <label className="csearch">
          <Search strokeWidth={1.6} />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a project…"
            aria-label="Find a project"
          />
        </label>
        <div className="cats" style={{ margin: 0, padding: 0 }}>
          {(["active", "archived"] as Shelf[]).map((s) => (
            <button type="button" key={s} className="cat" aria-pressed={shelf === s} onClick={() => setShelf(s)}>
              {s === "active" ? "Active" : "Archived"}
            </button>
          ))}
        </div>
      </div>

      {error ? <div className="stateline err" style={{ padding: "0 42px 14px" }}>{error}</div> : null}
      {items && !shown.length ? (
        needle && items.length ? (
          <p className="stateline" style={{ padding: "0 42px" }}>
            Nothing here matches “{query.trim()}”
          </p>
        ) : shelf === "archived" ? (
          <p className="stateline" style={{ padding: "0 42px" }}>
            Nothing archived
          </p>
        ) : (
          <EmptyBoard />
        )
      ) : null}

      <div className="mx-auto mb-24 grid max-w-[1680px] grid-cols-[repeat(auto-fill,minmax(min(340px,100%),1fr))] items-start gap-6 px-[42px] max-sm:px-4">
        {!items && !error
          ? Array.from({ length: 3 }, (_, i) => (
              <div key={i} aria-hidden className={`${CARD} border-noir-line2 motion-safe:animate-pulse`}>
                <div className="aspect-video w-full rounded-t-[9px] bg-noir-slate" />
                <div className="flex flex-col gap-3 px-4 pb-4 pt-3.5">
                  <div className="h-[26px] w-2/3 rounded-[4px] bg-noir-slate" />
                  <div className="h-4 w-5/6 rounded-[4px] bg-noir-raise" />
                </div>
              </div>
            ))
          : null}
        {shown.map((p) => (
          <article
            key={p.id}
            data-id={p.id}
            className={`${CARD} border-noir-line2 ${p.archived ? "opacity-60 focus-within:opacity-100 hover:opacity-100" : ""}`}
          >
            <Link
              href={workspaceHref(p.id)}
              aria-label={`Open ${p.title}`}
              className="group relative block aspect-video w-full overflow-hidden rounded-t-[9px] bg-noir-slate focus-visible:rounded-t-[9px]!"
            >
              {p.cover ? (
                <RefImg
                  url={p.cover}
                  thumb
                  small={p.cover_thumb || ""}
                  className="block size-full object-cover group-hover:brightness-110"
                  deadLabel="COVER UNAVAILABLE"
                  deadClassName="absolute inset-0 text-[11px] tracking-[0.16em]"
                />
              ) : (
                <span className="flex size-full items-center justify-center font-plex text-[11px] tracking-[0.16em] text-bone3">
                  NO SCENES YET
                </span>
              )}
            </Link>
            <div className="flex min-w-0 flex-col gap-2 px-4 pb-4 pt-3.5">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <Link href={workspaceHref(p.id)} className="min-w-0 flex-1 text-bone! hover:text-bone!">
                  <h4 className="m-0 truncate font-bebas text-[26px] font-normal leading-none tracking-[0.03em]" title={p.title}>
                    {p.title}
                  </h4>
                  <p className="m-0 mt-1 truncate text-[14px] text-bone2" title={p.brief || undefined}>
                    {briefLine(p)}
                  </p>
                </Link>
                <div className="flex flex-none gap-1.5">
                  <button
                    type="button"
                    className={ICON_BTN}
                    disabled={busy[p.id]}
                    title={p.archived ? "Put back on the board" : "Archive — hide it, keep everything"}
                    aria-label={p.archived ? `Restore ${p.title}` : `Archive ${p.title}`}
                    onClick={() => void toggleArchive(p)}
                  >
                    {p.archived ? <ArchiveRestore size={18} strokeWidth={2} aria-hidden /> : <Archive size={18} strokeWidth={2} aria-hidden />}
                  </button>
                  <button
                    type="button"
                    className={`${ICON_BTN} hover:enabled:border-noir-red! hover:enabled:text-noir-red!`}
                    disabled={busy[p.id]}
                    title="Delete the project and its chat history"
                    aria-label={`Delete ${p.title}`}
                    onClick={() => setDoomed(p)}
                  >
                    <Trash2 size={18} strokeWidth={2} aria-hidden />
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-plex text-[11px] tracking-[0.06em] text-bone3">
                <span>
                  {p.concepts ?? 0} SCENE{p.concepts === 1 ? "" : "S"}
                </span>
                <span>{p.picked ?? 0} PICKED</span>
                <span>{p.rendered ?? 0} RENDERED</span>
                <span className="ml-auto">UPDATED {touched(p.updated_at).toUpperCase()}</span>
              </div>
            </div>
          </article>
        ))}
      </div>

      <DeleteProjectDialog
        project={doomed}
        onClose={() => setDoomed(null)}
        onDeleted={(p) => {
          setDoomed(null);
          toast(`“${p.title}” and its chat history are deleted — its scenes were kept`);
          load();
        }}
      />
    </section>
  );
}

/* Zero projects is the first thing a new account sees, so it says how a
   project starts: through the assistant, never a form. */
function EmptyBoard() {
  return (
    <div className="mx-auto mb-6 flex max-w-[640px] flex-col items-center gap-3 px-6 py-10 text-center">
      <MessageCircle size={28} strokeWidth={1.4} className="text-bone3" aria-hidden />
      <h3 className="m-0 font-bebas text-[34px] font-normal leading-none tracking-[0.03em] text-bone">No projects yet</h3>
      <p className="m-0 text-[15px] leading-normal text-bone2">
        Projects are made through the assistant. Open it at the bottom of the screen and say{" "}
        <b className="text-bone">“make a project for …”</b>, or talk an idea through and then say{" "}
        <b className="text-bone">“save this as a project”</b>. The conversation and the scenes it made go with it.
      </p>
      <p className="m-0 text-[13.5px] text-bone3">
        A single video does not need one: make it on <Link href="/studio">Create</Link> and it lands on{" "}
        <Link href="/studio/assets">Assets</Link> when it finishes.
      </p>
    </div>
  );
}

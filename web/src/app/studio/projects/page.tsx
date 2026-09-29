"use client";

/* Projects (2026-09-28, Mike's call).

   The studio stopped being two in-house channels the day ANTIHERO was
   folded into Zero Page. A piece of work -- a client's ad, a filmmaker's
   short, a launch -- is a PROJECT now, and each one carries its own saved
   memory: the brief (typed, or drafted from three answers and then edited)
   and what the project has learned from every pick, pass and hand edit
   made inside it. Every Create inside a project is written against both,
   which is what keeps its renders consistent with each other.

   This page is the only door. "Open in Studio" hands the project to the
   composer (?project=<id>); the composer carries it until the chip is
   cleared. Archiving hides a project and never deletes it. */
/* eslint-disable @next/next/no-img-element */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Archive, ArchiveRestore, FolderKanban, Plus, Sparkles, X } from "lucide-react";
import {
  archiveProject,
  boardConcepts,
  createProject,
  draftProjectBrief,
  forgetProjectMemory,
  getProject,
  listProjects,
  rememberActiveProject,
  updateProject,
  type Concept,
  type Project,
  type ProjectQuestion,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";

const CARD = "rounded-xl border border-white/10 bg-white/[0.03]";
const BTN = "rounded-lg px-3 py-1.5 text-[13px] transition disabled:opacity-40";
const FIELD =
  "w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-[13px] text-white/90 outline-none focus:border-white/30";

const KIND_LABEL: Record<string, string> = {
  pick: "picked",
  pass: "passed",
  edit: "edited",
  note: "note",
};

function NewProject({
  questions,
  onMade,
  onCancel,
}: {
  questions: ProjectQuestion[];
  onMade: (p: Project) => void;
  onCancel: () => void;
}) {
  const { toast } = useShell();
  const [title, setTitle] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState("");

  const draft = async () => {
    setBusy("drafting the brief…");
    try {
      const r = await draftProjectBrief(title || "untitled", answers);
      setBrief(r.brief);
    } catch (e) {
      toast(e instanceof Error ? e.message : "couldn't draft the brief", "err");
    } finally {
      setBusy("");
    }
  };

  const save = async () => {
    setBusy("saving…");
    try {
      onMade(await createProject(title.trim(), brief));
    } catch (e) {
      toast(e instanceof Error ? e.message : "couldn't save the project", "err");
      setBusy("");
    }
  };

  const answered = questions.some((q) => (answers[q.key] || "").trim());

  return (
    <section className={`${CARD} flex flex-col gap-3 p-4`}>
      <header className="flex items-center gap-2">
        <h2 className="text-[14px]">New project</h2>
        <button type="button" onClick={onCancel} className="ml-auto text-white/40 hover:text-white/80" aria-label="Cancel">
          <X size={16} />
        </button>
      </header>
      <input
        className={FIELD}
        placeholder="Name — e.g. Nike trail spot, “Undertow” short, Juno cocktail menu"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
      />
      <p className="text-[12px] text-white/50">
        Answer what you can and let the assistant draft the brief — or skip straight to writing it yourself.
      </p>
      {questions.map((q) => (
        <label key={q.key} className="flex flex-col gap-1">
          <span className="text-[12px] text-white/60">{q.label}</span>
          <textarea
            className={`${FIELD} min-h-[56px]`}
            value={answers[q.key] || ""}
            onChange={(e) => setAnswers((a) => ({ ...a, [q.key]: e.target.value }))}
          />
        </label>
      ))}
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!answered || !!busy}
          onClick={() => void draft()}
          className={`${BTN} border border-white/15 hover:bg-white/10`}
        >
          <Sparkles size={13} className="mr-1 inline" /> Draft the brief
        </button>
        {busy && <span className="text-[12px] text-white/50">{busy}</span>}
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-[12px] text-white/60">Brief — every scene in this project is written against it</span>
        <textarea
          className={`${FIELD} min-h-[160px] font-mono text-[12px]`}
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder={"FOR: …\nLOOK: …\nPEOPLE & PRODUCT: …\nALWAYS: …\nNEVER: …"}
        />
      </label>
      <div className="flex justify-end">
        <button
          type="button"
          disabled={!title.trim() || !!busy}
          onClick={() => void save()}
          className={`${BTN} border border-white/25 bg-white/15 text-white hover:bg-white/25`}
        >
          Create project
        </button>
      </div>
    </section>
  );
}

function ProjectDetail({ id, onChanged }: { id: number; onChanged: () => void }) {
  const { toast } = useShell();
  const [project, setProject] = useState<Project | null>(null);
  const [brief, setBrief] = useState("");
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [saving, setSaving] = useState(false);

  const fetchAll = useCallback(
    () => Promise.all([getProject(id), boardConcepts(undefined, "all", id)]),
    [id],
  );
  const apply = useCallback(([p, board]: [Project, { items: Concept[] }]) => {
    setProject(p);
    setBrief(p.brief);
    setConcepts(board.items);
  }, []);
  const load = useCallback(
    () =>
      fetchAll()
        .then(apply)
        .catch((e) => toast(e instanceof Error ? e.message : "couldn't open the project", "err")),
    [fetchAll, apply, toast],
  );

  useEffect(() => {
    let alive = true;
    fetchAll()
      .then((r) => alive && apply(r))
      .catch((e) => alive && toast(e instanceof Error ? e.message : "couldn't open the project", "err"));
    return () => {
      alive = false;
    };
  }, [fetchAll, apply, toast]);

  if (!project) return <p className="p-4 text-[12px] text-white/50">opening…</p>;

  const saveBrief = async () => {
    setSaving(true);
    try {
      setProject(await updateProject(id, { brief }));
      toast("Brief saved — the next Create in this project uses it");
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "couldn't save the brief", "err");
    } finally {
      setSaving(false);
    }
  };

  const forget = async (at: string) => {
    try {
      await forgetProjectMemory(id, at);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "couldn't remove that", "err");
    }
  };

  const toggleArchive = async () => {
    try {
      await archiveProject(id, !project.archived);
      await load();
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "couldn't archive", "err");
    }
  };

  const memory = [...project.memory].reverse();

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="text-[16px]">{project.title}</h2>
        {project.archived && (
          <span className="rounded bg-white/10 px-1.5 py-0.5 text-[11px] text-white/60">archived</span>
        )}
        <Link
          href={`/studio?project=${project.id}`}
          onClick={() => rememberActiveProject(project.id)}
          className={`${BTN} ml-auto border border-white/25 bg-white/15 text-white hover:bg-white/25`}
        >
          Open in Studio
        </Link>
        <button type="button" onClick={() => void toggleArchive()} className={`${BTN} border border-white/10 hover:bg-white/10`}>
          {project.archived ? (
            <>
              <ArchiveRestore size={13} className="mr-1 inline" /> Restore
            </>
          ) : (
            <>
              <Archive size={13} className="mr-1 inline" /> Archive
            </>
          )}
        </button>
      </header>

      <section className={`${CARD} flex flex-col gap-2 p-4`}>
        <span className="text-[12px] text-white/60">Brief</span>
        <textarea
          className={`${FIELD} min-h-[150px] font-mono text-[12px]`}
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="No brief yet — scenes follow the idea you type alone."
        />
        <div className="flex justify-end">
          <button
            type="button"
            disabled={saving || brief === project.brief}
            onClick={() => void saveBrief()}
            className={`${BTN} border border-white/15 hover:bg-white/10`}
          >
            Save brief
          </button>
        </div>
      </section>

      <section className={`${CARD} flex flex-col gap-2 p-4`}>
        <span className="text-[12px] text-white/60">
          What this project has learned — every Create here reads the newest of these
        </span>
        {memory.length === 0 ? (
          <p className="text-[12px] text-white/40">
            Nothing yet. Pick, pass on or edit scenes written in this project and it remembers.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {memory.map((m) => (
              <li key={m.at} className="group flex items-start gap-2 text-[12px] leading-snug">
                <span
                  className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                    m.kind === "pass" ? "bg-red-400/15 text-red-200" : "bg-emerald-400/15 text-emerald-200"
                  }`}
                >
                  {KIND_LABEL[m.kind] || m.kind}
                </span>
                <span className="text-white/75">{m.text}</span>
                <button
                  type="button"
                  onClick={() => void forget(m.at)}
                  className="ml-auto shrink-0 text-white/30 opacity-0 transition hover:text-white/80 group-hover:opacity-100"
                  title="Forget this — it stops steering the project"
                  aria-label="Forget"
                >
                  <X size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <span className="text-[12px] text-white/60">
          Scenes in this project · {concepts.length}
        </span>
        {concepts.length === 0 ? (
          <p className="text-[12px] text-white/40">None yet — open it in Studio and press Create.</p>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {concepts.map((c) => {
              const still = c.reference_image || c.refs[0];
              return (
                <Link key={c.id} href={`/studio/pipeline#c${c.id}`} className={`${CARD} block overflow-hidden`}>
                  {still ? (
                    <img src={still} alt="" className="h-28 w-full object-cover" />
                  ) : (
                    <div className="h-28 w-full bg-white/5" />
                  )}
                  <span className="block px-2 pt-1.5 text-[12px] text-white/85">{c.title}</span>
                  <span className="block px-2 pb-2 text-[11px] text-white/40">
                    {c.media_url ? "rendered" : c.picked ? "picked" : c.archived ? "passed" : "open"}
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

export default function ProjectsPage() {
  const { toast } = useShell();
  const [items, setItems] = useState<Project[]>([]);
  const [questions, setQuestions] = useState<ProjectQuestion[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [making, setMaking] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(
    () =>
      listProjects(showArchived)
        .then((r) => {
          setItems(r.items);
          setQuestions(r.questions);
        })
        .catch((e) => toast(e instanceof Error ? e.message : "couldn't read the projects", "err")),
    [showArchived, toast],
  );

  useEffect(() => {
    let alive = true;
    listProjects(showArchived)
      .then((r) => {
        if (!alive) return;
        setItems(r.items);
        setQuestions(r.questions);
      })
      .catch((e) => alive && toast(e instanceof Error ? e.message : "couldn't read the projects", "err"));
    return () => {
      alive = false;
    };
  }, [showArchived, toast]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-center gap-2">
        <FolderKanban size={18} className="text-white/60" />
        <h1 className="text-[15px] tracking-wide">Projects</h1>
        <span className="text-[12px] text-white/40">
          each project keeps its own brief and memory, so its scenes stay consistent
        </span>
        <label className="ml-auto flex items-center gap-1.5 text-[12px] text-white/50">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          archived
        </label>
        <button
          type="button"
          onClick={() => {
            setMaking(true);
            setSelected(null);
          }}
          className={`${BTN} border border-white/25 bg-white/15 text-white hover:bg-white/25`}
        >
          <Plus size={13} className="mr-1 inline" /> New project
        </button>
      </header>

      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <aside className={`${CARD} max-h-[75vh] overflow-auto p-2`}>
          {items.length === 0 && (
            <p className="p-3 text-[12px] text-white/50">No projects yet. Start one for each client or film.</p>
          )}
          {items.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setSelected(p.id);
                setMaking(false);
              }}
              className={`mb-1 block w-full rounded-lg p-2 text-left transition ${
                selected === p.id ? "bg-white/10" : "hover:bg-white/[0.06]"
              }`}
            >
              <span className="block text-[13px] text-white/85">
                {p.title}
                {p.archived ? <span className="ml-1 text-[11px] text-white/40">· archived</span> : null}
              </span>
              <span className="block text-[11px] text-white/40">
                {p.concepts ?? 0} scenes · {p.picked ?? 0} picked · {p.rendered ?? 0} rendered ·{" "}
                {p.memory.length} learned
              </span>
            </button>
          ))}
        </aside>

        <main>
          {making ? (
            <NewProject
              questions={questions}
              onCancel={() => setMaking(false)}
              onMade={(p) => {
                setMaking(false);
                setSelected(p.id);
                void load();
                toast(`“${p.title}” created`);
              }}
            />
          ) : selected ? (
            <ProjectDetail key={selected} id={selected} onChanged={() => void load()} />
          ) : (
            <p className="p-4 text-[12px] text-white/50">
              Pick a project to see its brief, what it has learned and its scenes — or start a new one.
            </p>
          )}
        </main>
      </div>
    </div>
  );
}

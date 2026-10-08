"use client";

/* /studio/cut -- the projects (T1, decision D2). A project is a
   `cut_projects` row: started from scratch (a blank 3-track cut at the
   aspect you pick), or opened from a rendered scene, which reuses that
   concept's Assemble history -- so the cut the Queue exported is the cut
   you open, version for version. Deleting a project hides it; its
   versions are kept, like every version in this system -- so removing one
   asks nothing first and the toast offers Undo (2026-10-08). */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Clapperboard, Film, Loader2, Plus, RectangleHorizontal, RectangleVertical, Scissors, Square, Trash2 } from "lucide-react";
import { useShell } from "@/components/studio/shell";
import { createProject, deleteProject, listProjects, restoreProject, type Project } from "@/lib/cut/api";
import { cutReady, type CutReady } from "@/lib/studio-api";
import { shortDuration, type Aspect } from "@/lib/cut/timeline";
import "@/components/cut/cut.css";

const ASPECT_ICON = { "9:16": RectangleVertical, "16:9": RectangleHorizontal, "1:1": Square } as const;

function ago(iso: string): string {
  const t = Date.parse(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function CutProjectsPage() {
  const router = useRouter();
  const { toast, brand, signedOut } = useShell();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [ready, setReady] = useState<CutReady[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  // the list failed to load: said on the page with a retry, not only in a
  // toast that is gone before it is read (an empty grid read as "no cuts")
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listProjects()
      .then((r) => {
        setProjects(r.projects);
        setError(null);
      })
      .catch((e) => {
        setProjects([]);
        if (!signedOut) setError(e instanceof Error ? e.message : "Your cuts could not be listed");
      });
    cutReady(brand || undefined)
      .then((r) => setReady(r.ready))
      .catch(() => setReady([]));
  }, [brand, signedOut]);
  useEffect(() => {
    if (brand || signedOut) load();
  }, [brand, signedOut, load]);

  const open = async (key: string, body: { aspect?: Aspect; concept_id?: number; title?: string }) => {
    setBusy(key);
    try {
      const res = await createProject(body);
      router.push(`/studio/cut/${encodeURIComponent(res.project.id)}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "could not open the project", "err");
      setBusy(null);
    }
  };

  const remove = async (p: Project) => {
    try {
      await deleteProject(p.id);
      setProjects((all) => (all ?? []).filter((x) => x.id !== p.id));
      toast(`“${p.title}” removed · its versions are kept`, "ok", {
        action: {
          label: "Undo",
          run: () =>
            restoreProject(p.id).then(() => {
              toast(`“${p.title}” is back`);
              load();
            }),
        },
      });
    } catch (e) {
      toast(e instanceof Error ? e.message : "could not remove it", "err");
    }
  };

  const withProject = new Set((projects ?? []).map((p) => p.concept_id).filter(Boolean));
  const fresh = ready.filter((r) => !withProject.has(r.concept_id));

  return (
    <main className="cxp">
      <div className="cxp-head">
        <div>
          <p className="m" style={{ marginBottom: 10 }}>
            The editor · every edit a version
          </p>
          <h1>Edit</h1>
        </div>
      </div>

      <div className="cxp-grid">
        <div className="cxp-card cxp-new">
          <Plus size={22} strokeWidth={1.4} />
          <b className="cx-h" style={{ fontSize: 15 }}>
            Start from scratch
          </b>
          <span className="cx-seg">
            {(["9:16", "16:9", "1:1"] as Aspect[]).map((a) => {
              const Icon = ASPECT_ICON[a];
              return (
                <button key={a} type="button" disabled={!!busy} onClick={() => open(`new-${a}`, { aspect: a })} title={`A blank ${a} cut`}>
                  {busy === `new-${a}` ? <Loader2 size={11} className="animate-spin" /> : <Icon size={11} style={{ verticalAlign: -1 }} />}{" "}
                  {a}
                </button>
              );
            })}
          </span>
        </div>

        {projects === null ? (
          <div className="cxp-card cxp-new">
            <Loader2 className="animate-spin" size={18} />
          </div>
        ) : null}

        {error ? (
          <div className="cxp-card cxp-new cxp-empty" role="alert">
            <b className="cx-h">Your cuts could not be listed</b>
            <span className="m">{error}</span>
            <button type="button" className="cx-btn" onClick={load}>
              Try again
            </button>
          </div>
        ) : projects && !projects.length ? (
          <div className="cxp-card cxp-new cxp-empty">
            <Scissors size={20} strokeWidth={1.4} />
            <b className="cx-h">No cuts yet</b>
            <span>
              {fresh.length
                ? "Start one from scratch, or open a rendered scene below — its clips land on the timeline in order."
                : "Start one from scratch. A scene whose clips are rendered in the Queue shows up here, ready to cut."}
            </span>
            {fresh.length ? null : (
              <Link href="/studio/queue" className="cx-btn">
                Open the Queue
              </Link>
            )}
          </div>
        ) : null}

        {(projects ?? []).map((p) => {
          const Icon = p.aspect ? ASPECT_ICON[p.aspect] : Film;
          return (
            <div key={p.id} className="cxp-card">
              <button type="button" className="cx-btn cxp-del" title="Remove from projects" onClick={() => remove(p)}>
                <Trash2 />
              </button>
              <button
                type="button"
                style={{ all: "unset", display: "block", width: "100%", cursor: "pointer" }}
                onClick={() => router.push(`/studio/cut/${encodeURIComponent(p.id)}`)}
              >
                <div className="cxp-thumb" style={p.poster ? { backgroundImage: `url(${p.poster})` } : undefined}>
                  {p.poster ? null : <Clapperboard />}
                </div>
                <div className="cxp-meta">
                  <b>{p.title}</b>
                  <span className="m" style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
                    <Icon size={11} />
                    {p.aspect ?? `${p.size[0]}×${p.size[1]}`} · {shortDuration(p.duration, p.fps)}
                    {p.version ? ` · v${p.version}` : ""} · {ago(p.updated_at)}
                  </span>
                </div>
              </button>
            </div>
          );
        })}
      </div>

      {fresh.length ? (
        <>
          <h2>From a rendered scene</h2>
          <div className="cxp-grid">
            {fresh.map((r) => (
              <button
                key={r.concept_id}
                type="button"
                className="cxp-card"
                style={{ textAlign: "left", padding: 0, cursor: "pointer" }}
                disabled={!!busy}
                onClick={() => open(`c-${r.concept_id}`, { concept_id: r.concept_id })}
              >
                <div className="cxp-thumb" style={r.poster ? { backgroundImage: `url(${r.poster})` } : undefined}>
                  {busy === `c-${r.concept_id}` ? <Loader2 className="animate-spin" /> : r.poster ? null : <Film />}
                </div>
                <div className="cxp-meta">
                  <b>{r.title}</b>
                  <span className="m" style={{ display: "block", marginTop: 6 }}>
                    #{r.concept_id} · {r.clips} clip{r.clips === 1 ? "" : "s"}
                    {r.export ? ` · cut v${r.export.version}` : ""}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </>
      ) : null}
    </main>
  );
}

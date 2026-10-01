"use client";

/* The editor (T2 onward): invideo's layout, Resolve's craft, ZPF's skin.

   ┌ top bar ─────────────────────────────────────────────────────────────┐
   │ left panel │ viewer                              │ inspector        │
   │ (agent,    ├─────────────────────────────────────┴──────────────────┤
   │  media…)   │ tool strip · ruler · tracks · playhead                 │
   └────────────┴────────────────────────────────────────────────────────┘

   Three split panes (react-resizable-panels): the left panel's width, the
   timeline's height, the inspector's width. Their sizes are the viewer's
   own convenience, kept in localStorage per browser -- wrapped, because a
   private window or blocked storage must still open the editor. The
   timeline's zoom is kept the same way, per project. */
import { useEffect, useRef } from "react";
import Link from "next/link";
import { Group, Panel, Separator, useDefaultLayout, type LayoutStorage } from "react-resizable-panels";
import { useShell } from "@/components/studio/shell";
import { useCut } from "@/lib/cut/store";
import { clampPps } from "@/lib/cut/timeline";
import { TopBar } from "@/components/cut/top-bar";
import { LeftPanel } from "@/components/cut/left-panel";
import { Viewer } from "@/components/cut/viewer";
import { SourceViewer } from "@/components/cut/source-viewer";
import { Inspector } from "@/components/cut/inspector";
import { ToolStrip } from "@/components/cut/tool-strip";
import { Timeline } from "@/components/cut/timeline";
import { useEditorKeys, zoomToFit } from "@/components/cut/commands";
import "@/components/cut/cut.css";

/* localStorage, or nothing: every read and write may throw */
const safeStorage: LayoutStorage = {
  getItem: (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  setItem: (k, v) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      /* the layout just forgets */
    }
  },
};
const zoomKey = (id: string) => `zpf.cut.zoom.${id}`;

export function Editor({ projectId }: { projectId: string }) {
  const { toast } = useShell();
  const load = useCut((s) => s.load);
  const loadBin = useCut((s) => s.loadBin);
  const loading = useCut((s) => s.loading);
  const error = useCut((s) => s.error);
  const doc = useCut((s) => s.doc);
  const tool = useCut((s) => s.tool);
  const pps = useCut((s) => s.pps);
  const zoomRestored = useRef<string | null>(null);

  useEffect(() => {
    useCut.getState().setToast(toast);
  }, [toast]);

  useEffect(() => {
    zoomRestored.current = null;
    void load(projectId).then(() => loadBin());
    return () => useCut.setState({ playing: false });
  }, [projectId, load, loadBin]);

  // T14: the zoom survives a reload, per project; a first visit fits
  useEffect(() => {
    if (!doc || zoomRestored.current === projectId) return;
    zoomRestored.current = projectId;
    const saved = safeStorage.getItem(zoomKey(projectId));
    if (saved && Number(saved) > 0) useCut.getState().setPps(clampPps(Number(saved)));
    else requestAnimationFrame(zoomToFit);
  }, [doc, projectId]);
  useEffect(() => {
    if (zoomRestored.current === projectId) safeStorage.setItem(zoomKey(projectId), String(Math.round(pps * 100) / 100));
  }, [pps, projectId]);

  useEditorKeys();

  const outer = useDefaultLayout({ id: "zpf-cut-outer", storage: safeStorage });
  const vertical = useDefaultLayout({ id: "zpf-cut-vertical", storage: safeStorage });
  // a new key with the Source pane: a remembered two-pane layout would not
  // fit three panels, and react-resizable-panels restores by panel id
  const upper = useDefaultLayout({ id: "zpf-cut-upper-src", storage: safeStorage });

  if (error) {
    return (
      <div className="cx" style={{ display: "grid", placeItems: "center" }}>
        <div style={{ textAlign: "center", maxWidth: 420 }}>
          <p className="cx-h" style={{ fontSize: 18, marginBottom: 8 }}>
            Could not open this project
          </p>
          <p className="cx-note" style={{ marginBottom: 16 }}>
            {error}
          </p>
          <Link href="/studio/cut" className="cx-go">
            All projects
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="cx" data-tool={tool}>
      <TopBar />
      <div className="cx-body">
        <Group orientation="horizontal" id="zpf-cut-outer" defaultLayout={outer.defaultLayout} onLayoutChanged={outer.onLayoutChanged}>
          <Panel id="left" defaultSize="23" minSize={250} maxSize="42" className="cx-pane">
            <LeftPanel />
          </Panel>
          <Separator className="cx-handle v" />
          <Panel id="main" minSize="45">
            <Group
              orientation="vertical"
              id="zpf-cut-vertical"
              defaultLayout={vertical.defaultLayout}
              onLayoutChanged={vertical.onLayoutChanged}
            >
              <Panel id="upper" defaultSize="56" minSize="25">
                <Group
                  orientation="horizontal"
                  id="zpf-cut-upper-src"
                  defaultLayout={upper.defaultLayout}
                  onLayoutChanged={upper.onLayoutChanged}
                >
                  <Panel id="source" defaultSize="30" minSize={220} collapsible collapsedSize={0}>
                    {doc ? <SourceViewer /> : null}
                  </Panel>
                  <Separator className="cx-handle v" />
                  <Panel id="viewer" minSize="25">
                    {doc ? <Viewer /> : <Loading loading={loading} />}
                  </Panel>
                  <Separator className="cx-handle v" />
                  <Panel id="inspector" defaultSize="24" minSize={230} maxSize="40">
                    <Inspector />
                  </Panel>
                </Group>
              </Panel>
              <Separator className="cx-handle h" />
              <Panel id="timeline" defaultSize="44" minSize={170}>
                <div className="cx-pane" style={{ background: "var(--cx-bg)" }}>
                  <ToolStrip />
                  {doc ? <Timeline /> : null}
                </div>
              </Panel>
            </Group>
          </Panel>
        </Group>
      </div>
    </div>
  );
}

function Loading({ loading }: { loading: boolean }) {
  return (
    <div className="cx-viewer" style={{ display: "grid", placeItems: "center" }}>
      <span className="cx-label">{loading ? "Opening the cut…" : ""}</span>
    </div>
  );
}

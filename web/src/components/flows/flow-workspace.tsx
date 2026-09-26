"use client";

/* The Director — the Gen Space on React Flow (2026-09-11).

   One shot's chain as cards on an infinite canvas: the prompt and its
   instructions, one element card per asset the scene was written
   against, the Gemini enhance, the Nano keyframe and the Runway clip.
   Wires are real links the runner executes (src/lib/director-graph.ts
   is the adapter). Underneath, a prompt bar edits the shot's prompt
   and an @-mention drops an element on the canvas already wired in;
   Generate runs the whole chain through the backend's Run all; Send
   to Queue only PICKS — approving in Queue is still the one spend
   gate. Every billed node stays behind its module's own gate.

   Without a concept the canvas is a browser-local draft with
   templates and JSON import/export, as before. */
/* Arbitrary reference hosts and provider outputs are displayed directly. */
/* eslint-disable @next/next/no-img-element */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  createContext,
  useContext,
  type ReactNode,
} from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  MiniMap,
  Handle,
  Position,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Edge,
  type NodeProps,
  type Connection,
} from "@xyflow/react";
import {
  ArrowLeft,
  ArrowUpRight,
  Box,
  Check,
  ChevronDown,
  Clapperboard,
  Clock,
  Copy,
  Download,
  Film,
  Grid2X2,
  Hand,
  ImagePlus,
  Layers,
  ListVideo,
  LoaderCircle,
  MapPin,
  Maximize,
  Monitor,
  MoreHorizontal,
  MousePointer2,
  Play,
  Plus,
  RectangleVertical,
  Scissors,
  Sparkles,
  Trash2,
  Type,
  Upload,
  UserRound,
  Video,
  X,
  Zap,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { apiFetch, API_URL, goToSignIn } from "@/lib/api";
import { sceneMenu, uploadRefs, type SceneMenuRow } from "@/lib/studio-api";
import {
  announceQueueChange,
  getAssets,
  getCapabilities,
  getPresets,
  pickConcept,
  type Capabilities,
  type Preset,
  type RenderQuote,
  type RunwayState,
} from "@/lib/studio-api";
import { useMentions } from "@/components/studio/mentions";
import { useShell } from "@/components/studio/shell";
import "@xyflow/react/dist/style.css";
import "./flows.css";

import {
  compatible,
  elementLabel,
  fromLegacy,
  isMedia,
  isText,
  ports,
  sceneRefs,
  seedScene,
  toLegacy,
  wireElement,
  type CardData,
  type FlowNode,
  type Kind,
  type LegacyGraph,
  type NodeState,
  type RefKind,
  type Shot,
} from "@/lib/director-graph";

type Template = "image" | "video" | "variety";
type Draft = { version: 1; name: string; nodes: FlowNode[]; edges: Edge[] };
const KEY = "zeropage.flow-draft.v1";
const titles: Record<Kind, string> = {
  prompt: "Prompt",
  image: "Nano Banana",
  video: "Runway Gen-4 Turbo",
  reference: "Reference image",
  element: "Element",
  system: "Instructions",
  enhance: "Gemini 2.5 Flash",
  ground: "Ground in references",
};
const notes: Record<Kind, string> = {
  prompt: "What happens in the shot. Written by the generator, editable here or in the bar below — @ brings an element onto the canvas.",
  system: "How the enhance treats the prompt: tighten, never summarise; keep the locks, the avoid-list and the beat order.",
  ground: "Reference-library grounding for a spark. Its output feeds the enhance as references.",
  enhance: "Takes the prompt, the instructions and every reference wired in, and returns one tightened director's prompt.",
  reference: "One plate this shot starts from.",
  element: "Reference frames from the asset library. Keeps the face, the wardrobe or the room consistent across shots.",
  image: "Renders the keyframe the clip starts from — the enhanced prompt as a still, grounded on every reference wired in.",
  video: "Takes every wire coming in and renders one clip, anchored on the keyframe. The only step that spends money.",
};
const starterText =
  "A solitary rider crosses a sunlit field. Wind moves through the tall grass, warm afternoon light, subtle film grain. A quiet, unhurried moment.";
const templates: { id: Template; title: string; text: string; image: string }[] = [
  { id: "image", title: "Image generation", text: "Turn a thought into a frame.", image: "image-study" },
  { id: "video", title: "Video generation", text: "Give your still a little motion.", image: "motion-study" },
  { id: "variety", title: "Explore variations", text: "One prompt. Three directions.", image: "model-study" },
];
function makeTemplate(type: Template): { nodes: FlowNode[]; edges: Edge[] } {
  const prompt: FlowNode = {
    id: "prompt",
    type: "studio",
    position: { x: 80, y: type === "variety" ? 235 : 140 },
    data: { kind: "prompt", label: "Prompt", text: starterText },
  };
  const image: FlowNode = {
    id: "image",
    type: "studio",
    position: { x: 530, y: 50 },
    data: { kind: "image", label: "Nano Banana" },
  };
  const nodes: FlowNode[] = [prompt, image];
  const edges: Edge[] = [{ id: "prompt-image", source: "prompt", target: "image", targetHandle: "prompt" }];
  if (type === "video") {
    nodes.push({ id: "video", type: "studio", position: { x: 980, y: 50 }, data: { kind: "video", label: titles.video } });
    edges.push(
      { id: "image-video", source: "image", target: "video", targetHandle: "reference" },
      { id: "prompt-video", source: "prompt", target: "video", targetHandle: "prompt" },
    );
  }
  if (type === "variety") {
    image.position.y = -150;
    nodes.push(
      ...[1, 2].map(
        (n): FlowNode => ({
          id: `take-${n}`,
          type: "studio",
          position: { x: 530, y: -150 + n * 380 },
          data: { kind: "image", label: `Nano Banana · Take ${n + 1}` },
        }),
      ),
    );
    edges.push(...[1, 2].map((n) => ({ id: `prompt-take-${n}`, source: "prompt", target: `take-${n}`, targetHandle: "prompt" })));
  }
  return { nodes, edges };
}

const asSrc = (url: string) => (url.startsWith("/") ? `${API_URL}${url}` : url);
const ratioLabel = (r?: string) => (r === "720:1280" ? "9:16" : r === "1280:720" ? "16:9" : r || "9:16");

const Actions = createContext<{
  update: (id: string, data: Partial<CardData>) => void;
  addFrames: (id: string, urls: string[]) => void;
  remove: (id: string) => void;
  duplicate: (id: string) => void;
  run: (id: string) => void;
  runway: RunwayState | null;
  caps: Capabilities;
}>({ update: () => {}, addFrames: () => {}, remove: () => {}, duplicate: () => {}, run: () => {}, runway: null, caps: {} });

function KindIcon({ data, size, strokeWidth }: { data: CardData; size: number; strokeWidth: number }) {
  const props = { size, strokeWidth };
  if (data.kind === "prompt") return <Type {...props} />;
  if (data.kind === "system") return <Layers {...props} />;
  if (data.kind === "video") return <Clapperboard {...props} />;
  if (data.kind === "reference") return <ImagePlus {...props} />;
  if (data.kind === "element") {
    if (data.refKind === "location") return <MapPin {...props} />;
    if (data.refKind === "prop") return <Box {...props} />;
    if (data.refKind === "character") return <UserRound {...props} />;
    return <ImagePlus {...props} />;
  }
  return <Sparkles {...props} />;
}

function gateNote(kind: Kind, caps: Capabilities) {
  if (kind === "video")
    return !caps["runway.generate"]
      ? "Runway · RUNWAYML_API_SECRET not set"
      : !caps["runway.spend"]
        ? "Runway · gated — RUNWAY_SPEND_OK=1 to arm"
        : "";
  if (kind === "image" && caps["nano.generate"] === false) return "GEMINI_API_KEY not set";
  return "";
}

/* Frames from disk (2026-09-18, Mike: a pasted URL was the only way in).
 * Upload button + drop-anywhere on the card; both go through
 * /api/refs/upload, the composer's bin, so an uploaded frame resolves
 * exactly like one attached at Create. */
const imageFiles = (list: FileList | null | undefined) =>
  Array.from(list || []).filter((f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name));

function useFrameUpload(id: string) {
  const actions = useContext(Actions);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const send = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    setNote("");
    try {
      const res = await uploadRefs(files);
      if (res.urls.length) actions.addFrames(id, res.urls);
      if (res.skipped) setNote(`${res.skipped} skipped (not a readable image)`);
    } catch (err) {
      setNote(err instanceof Error ? err.message : "upload failed");
    } finally {
      setBusy(false);
    }
  };
  return { busy, note, send };
}

const FrameCtx = createContext<ReturnType<typeof useFrameUpload> | null>(null);

function FrameDrop({ id, children }: { id: string; children: ReactNode }) {
  const up = useFrameUpload(id);
  const [over, setOver] = useState(false);
  return (
    <FrameCtx.Provider value={up}>
      <div
        className={`element-body nodrag${over ? " is-drop" : ""}`}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          e.preventDefault();
          e.stopPropagation();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          if (!e.dataTransfer.files.length) return;
          e.preventDefault();
          e.stopPropagation();
          setOver(false);
          up.send(imageFiles(e.dataTransfer.files));
        }}
      >
        {children}
        {up.note ? (
          <p role="alert" className="node-error nodrag nowheel">
            {up.note}
          </p>
        ) : null}
      </div>
    </FrameCtx.Provider>
  );
}

function FrameUpload() {
  const up = useContext(FrameCtx);
  const input = useRef<HTMLInputElement>(null);
  if (!up) return null;
  return (
    <button className="ghost frame-upload" disabled={up.busy} onClick={() => input.current?.click()} title="Upload photos from your computer (or drop them on the card)">
      {up.busy ? <LoaderCircle size={12} className="spin" /> : <Upload size={12} />} {up.busy ? "Uploading…" : "Upload"}
      <input
        ref={input}
        type="file"
        accept="image/*,.heic,.heif"
        multiple
        hidden
        onChange={(e) => {
          up.send(imageFiles(e.target.files));
          e.target.value = "";
        }}
      />
    </button>
  );
}

function StudioNode({ id, data, selected }: NodeProps<FlowNode>) {
  const actions = useContext(Actions);
  const [menu, setMenu] = useState(false);
  const ins = ports(data.kind);
  const rw = actions.runway;
  return (
    <article className={`flow-card ${selected ? "is-selected" : ""} kind-${data.kind}${data.busy ? " is-busy" : ""}${data.error ? " is-failed" : ""}${data.url || (isText(data.kind) && data.text && !["prompt", "system"].includes(data.kind)) ? " is-done" : ""}`}>
      {ins.map((port, i) => (
        <Handle
          key={port}
          type="target"
          position={Position.Left}
          id={port}
          title={`${port} · ${port === "reference" ? "image" : port === "refs" ? "images" : "text"}`}
          className={port === "reference" ? "port-image" : port === "refs" ? "port-images" : "port-text"}
          style={{ top: 66 + i * 30 }}
        />
      ))}
      <header className="node-header">
        <KindIcon data={data} size={14} strokeWidth={1.6} />
        <span>{data.label}</span>
        <button aria-label={`Options for ${data.label}`} className="nodrag node-menu-toggle" onClick={() => setMenu(!menu)}>
          <MoreHorizontal size={16} />
        </button>
      </header>
      {menu && (
        <div className="node-menu nodrag">
          <button
            onClick={() => {
              actions.duplicate(id);
              setMenu(false);
            }}
          >
            <Copy size={14} /> Duplicate
          </button>
          <button onClick={() => actions.remove(id)}>
            <Trash2 size={14} /> Delete
          </button>
        </div>
      )}

      {isText(data.kind) ? (
        <>
          <textarea
            aria-label={data.kind === "prompt" ? "Scene prompt" : data.label}
            className="nodrag nowheel prompt-field"
            placeholder={
              data.kind === "prompt"
                ? "Describe the shot… (@ to reference an element)"
                : data.kind === "system"
                  ? "Instructions for how the model should treat the prompt…"
                  : "Output will appear here"
            }
            value={data.text || ""}
            readOnly={["enhance", "ground"].includes(data.kind)}
            onChange={(e) => actions.update(id, { text: e.target.value })}
          />
          <footer className="prompt-footer">
            {["enhance", "ground"].includes(data.kind) ? (
              <>
                <span className="m">{data.text ? `${data.text.length} chars` : "text → text"}</span>
                <button className="nodrag ghost" disabled={data.busy} onClick={() => actions.run(id)}>
                  <Play size={12} /> {data.busy ? "Running…" : "Run"}
                </button>
              </>
            ) : (
              <span className="m">{(data.text || "").length} chars</span>
            )}
          </footer>
          {data.error && (
            <p role="alert" className="node-error nodrag nowheel">
              ✕ {data.error}
            </p>
          )}
        </>
      ) : data.kind === "element" ? (
        <FrameDrop id={id}>
          {data.urls?.length ? (
            <div className={`element-frames c${data.refKind === "location" ? 2 : 3}${data.refKind === "location" ? " wide" : ""}`}>
              {data.urls.map((u, i) => (
                <span key={`${u}-${i}`} className="element-frame">
                  <img src={asSrc(u)} alt="" loading="lazy" />
                  <button
                    className="frame-x"
                    title="Remove this frame"
                    onClick={() => actions.update(id, { urls: data.urls!.filter((_, j) => j !== i) })}
                  >
                    <X size={10} />
                  </button>
                </span>
              ))}
            </div>
          ) : (
            <div className="empty-media small">
              <ImagePlus size={22} strokeWidth={1.2} />
              <span>No frames yet</span>
            </div>
          )}
          <footer className="node-footer">
            <span className="m">
              {data.urls?.length || 0} frame{data.urls?.length === 1 ? "" : "s"}
            </span>
            <FrameUpload />
          </footer>
        </FrameDrop>
      ) : data.kind === "reference" ? (
        <div className="reference-body nodrag">
          {data.url ? (
            <img src={asSrc(data.url)} alt="Your reference" />
          ) : (
            <div className="empty-media">
              <ImagePlus size={28} strokeWidth={1.2} />
              <span>Add a reference image</span>
            </div>
          )}
          <label>
            <span className="m">Image url</span>
            <input
              aria-label="Reference image URL"
              placeholder="https://… or a picked photo"
              value={data.url || ""}
              onChange={(e) => actions.update(id, { url: e.target.value })}
            />
          </label>
        </div>
      ) : (
        <>
          {data.kind === "video" ? (
            <div className="node-chips nodrag">
              <span className="chip">
                <Clock size={11} /> {rw?.duration ?? 5} sec
              </span>
              <span className="chip">
                <RectangleVertical size={11} /> {ratioLabel(rw?.ratio)}
              </span>
              <span className="chip">
                <Monitor size={11} /> {rw?.model ?? "gen4_turbo"}
              </span>
              {data.camera ? (
                <span className="chip">
                  <Video size={11} /> {data.camera}
                </span>
              ) : null}
            </div>
          ) : null}
          <div className={`node-preview nodrag${data.kind === "video" ? " video" : ""}`}>
            {data.url ? (
              data.kind === "video" ? (
                <video src={asSrc(data.url)} controls muted loop playsInline preload="metadata" />
              ) : (
                <img src={asSrc(data.url)} alt="Generated frame" />
              )
            ) : (
              <div className="empty-media">
                {data.busy ? <LoaderCircle size={26} className="spin" /> : <KindIcon data={data} size={26} strokeWidth={1} />}
                <span>
                  {data.busy
                    ? data.kind === "video"
                      ? "Rendering the clip…"
                      : "Rendering the keyframe…"
                    : gateNote(data.kind, actions.caps) ||
                      (data.kind === "video" ? "The clip lands here" : "Keyframe will appear here")}
                </span>
              </div>
            )}
            {data.busy && data.url ? (
              <div className="node-overlay">
                <LoaderCircle size={14} className="spin" /> <span className="m">re-rolling</span>
              </div>
            ) : null}
            <span className="preview-tag">{data.kind === "video" ? "VIDEO" : "IMAGE"}</span>
          </div>
          {data.error && (
            <p role="alert" className="node-error nodrag nowheel">
              ✕ {data.error}
            </p>
          )}
          <footer className="node-footer nodrag">
            <span className="m">
              {data.kind === "video" && rw?.estimate_usd != null
                ? `est. $${Number(rw.estimate_usd).toFixed(2)}`
                : data.busy
                  ? "processing"
                  : data.url
                    ? "ready"
                    : data.kind === "video"
                      ? "text/image → video"
                      : "text/image → image"}
            </span>
            {data.url && data.kind === "video" ? (
              <a className="ghost" href={asSrc(data.url)} target="_blank" rel="noreferrer">
                <Download size={12} /> Export
              </a>
            ) : null}
            <button className={data.kind === "video" ? "pri" : "ghost"} disabled={data.busy} onClick={() => actions.run(id)}>
              <Play size={12} />
              {data.busy ? "Running…" : data.url ? "Re-roll" : "Run"}
            </button>
          </footer>
        </>
      )}
      <Handle
        type="source"
        position={Position.Right}
        id="output"
        className={data.kind === "element" ? "port-images" : isText(data.kind) ? "port-text" : "port-image"}
        style={{ top: "50%" }}
      />
    </article>
  );
}
const nodeTypes = { studio: StudioNode };

type Concept = {
  id: number;
  n: string;
  title: string;
  shots: Shot[];
  picked?: boolean;
  parked?: boolean;
  media_url?: string;
  runway?: RunwayState;
  generate?: RenderQuote;
};

/* The scene switcher: the header chip is a menu of the brand's open scenes,
   so moving from one scene's graph to another does not mean a trip back to
   Pipeline. The list is read when the menu opens, not on mount -- the
   canvas has enough to load. Leaving goes through `go` (flushAndGo), so
   the canvas is saved against the scene it belongs to first. */
function SceneSwitcher({
  label,
  currentId,
  brand,
  go,
}: {
  label: ReactNode;
  currentId?: number;
  brand: string;
  go: (destination: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<SceneMenuRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const toggle = () => {
    setOpen((was) => !was);
    if (rows || open) return;
    // the server returns only what the canvas can open (api `_openable`)
    sceneMenu(brand || undefined)
      .then((r) => setRows(r.items))
      .catch(() => setFailed(true));
  };
  const state = (c: SceneMenuRow) => (c.has_media ? "rendered" : c.picked ? "picked" : c.parked ? "in queue" : "");
  return (
    <span className="scene-switch" ref={box}>
      <button type="button" className="chip" aria-haspopup="menu" aria-expanded={open} onClick={toggle} title="Switch scene">
        {label}
        <ChevronDown size={12} />
      </button>
      {open ? (
        <span className="scene-menu" role="menu">
          <span className="scene-menu-head">Scenes · {brand || "all"}</span>
          <span className="scene-menu-list">
            {failed ? <span className="scene-menu-note">Could not read the board</span> : null}
            {!rows && !failed ? <span className="scene-menu-note">Reading the board…</span> : null}
            {rows && !rows.length ? <span className="scene-menu-note">No scenes yet — write one on Studio</span> : null}
            {(rows || []).map((c) => (
              <button
                type="button"
                role="menuitem"
                key={c.id}
                aria-current={c.id === currentId ? "true" : undefined}
                onClick={() => {
                  setOpen(false);
                  if (c.id !== currentId) go(`/studio/flows?concept=${c.id}&shot=1`);
                }}
              >
                <span className="scene-menu-n">{c.n}</span>
                <span className="scene-menu-title">{c.title || "Untitled"}</span>
                {state(c) ? <span className="scene-menu-state">{state(c)}</span> : null}
              </button>
            ))}
          </span>
          <span className="scene-menu-foot">
            <button type="button" role="menuitem" onClick={() => go("/studio/pipeline")}>
              All concepts on Pipeline
            </button>
            {currentId ? (
              <button type="button" role="menuitem" onClick={() => go("/studio/flows?draft=1")}>
                Local draft canvas
              </button>
            ) : null}
          </span>
        </span>
      ) : null}
    </span>
  );
}

function Workspace({ conceptId, shotN }: { conceptId?: number; shotN?: number }) {
  const shell = useShell();
  const [initial] = useState(() => makeTemplate("variety"));
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [name, setName] = useState("Untitled flow");
  const [template, setTemplate] = useState<Template>("variety");
  const [showTemplates, setShowTemplates] = useState(!conceptId);
  const [addMenu, setAddMenu] = useState(false);
  const [tool, setTool] = useState<"select" | "hand" | "cut">("select");
  const [toast, setToast] = useState("");
  const [ready, setReady] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [storageError, setStorageError] = useState(false);
  const [scene, setScene] = useState<Concept | null>(null);
  const [activeShot, setActiveShot] = useState<number | undefined>(shotN);
  const [sceneError, setSceneError] = useState("");
  const [saveState, setSaveState] = useState("Loading scene…");
  const [saveRevision, setSaveRevision] = useState(0);
  const [caps, setCaps] = useState<Capabilities>({});
  const [presets, setPresets] = useState<Preset[]>([]);
  const [assets, setAssets] = useState<{ name: string; category: string; photos: string[] }[]>([]);
  const [runJob, setRunJob] = useState<{ id: number } | null>(null);
  const [runProgress, setRunProgress] = useState("");
  const [bar, setBar] = useState("");
  const graphBase = useRef<Partial<LegacyGraph>>({});
  const seedHash = useRef<string | null>(null);
  // the reference list the scene holds right now, in the canvas's own
  // spelling of each url -- what the wiring is compared against
  const savedRefs = useRef<string[]>([]);
  const saveChain = useRef<Promise<unknown>>(Promise.resolve());
  const lastSaved = useRef("");
  const stopped = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const barRef = useRef<HTMLTextAreaElement>(null);
  const pending = useRef(new Set<string>());
  const { fitView, zoomIn, zoomOut, screenToFlowPosition, getNodes, getEdges } = useReactFlow<FlowNode>();
  const notify = useCallback((text: string) => setToast(text), []);

  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => setCaps({}));
    getPresets()
      .then((r) => setPresets(r.items || []))
      .catch(() => setPresets([]));
    getAssets()
      .then((r) => setAssets(r.items))
      .catch(() => setAssets([]));
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => fitView({ padding: 0.12, duration: 250 }), 120);
    return () => clearTimeout(timer);
  }, [showTemplates, fitView]);
  useEffect(() => {
    if (!confirm) return;
    const previous = document.activeElement;
    dialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [confirm]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4200);
    return () => clearTimeout(timer);
  }, [toast]);

  /* ── the draft (no concept): browser-local ── */
  useEffect(() => {
    if (conceptId) return;
    const timer = setTimeout(() => {
      try {
        const saved = localStorage.getItem(KEY);
        if (saved) {
          const draft = JSON.parse(saved) as Draft;
          if (validDraft(draft)) {
            setNodes(draft.nodes.map((n) => ({ ...n, data: { ...n.data, busy: !!n.data.jobId } })));
            setEdges(draft.edges);
            setName(draft.name);
            setShowTemplates(false);
          }
        }
      } catch {
        setStorageError(true);
      }
      setReady(true);
    }, 0);
    return () => clearTimeout(timer);
  }, [setNodes, setEdges, conceptId]);
  useEffect(() => {
    if (!ready || conceptId) return;
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(KEY, JSON.stringify({ version: 1, name, nodes, edges }));
        setStorageError(false);
      } catch {
        setStorageError(true);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [nodes, edges, name, ready, conceptId]);

  /* ── the scene (a concept's shot) ── */
  useEffect(() => {
    if (!conceptId) return;
    let cancelled = false;
    (async () => {
      try {
        const [detail, presetsRes, assetsRes] = await Promise.all([
          apiFetch<Concept>(`/concepts/${conceptId}`),
          getPresets().catch(() => ({ items: [], enhance_system: "" })),
          getAssets().catch(() => ({ items: [] })),
        ]);
        const shot = detail.shots.find((s) => s.n === (shotN ?? detail.shots[0]?.n));
        if (!shot) throw new Error("This scene has no written shot yet. Write its prompt from Pipeline first.");
        const saved = await apiFetch<{
          graph: LegacyGraph | null;
          states?: Record<string, NodeState>;
          seed_hash?: string;
          stale?: boolean;
        }>(`/concepts/${conceptId}/shots/${shot.n}/graph`);
        if (cancelled) return;
        const names: Record<string, string> = {};
        for (const a of assetsRes.items) {
          const slug = a.photos[0]?.match(/^\/(characters|locations|props)\/([^/]+)\//)?.[2];
          if (slug) names[slug] = a.name;
        }
        const loaded = saved.graph
          ? fromLegacy(saved.graph, saved.states || {})
          : seedScene(shot, { enhanceSystem: presetsRes.enhance_system, names });
        // a render can finish after the previous browser closed: the shot is authoritative
        const image = loaded.nodes.find((n) => n.data.kind === "image");
        const video = loaded.nodes.find((n) => n.data.kind === "video");
        if (image && shot.reference_image) image.data.url = shot.reference_image;
        if (video && shot.media_url) video.data.url = shot.media_url;
        graphBase.current = saved.graph || {};
        seedHash.current = saved.seed_hash || null;
        savedRefs.current = shot.refs || [];
        setNodes(loaded.nodes);
        setEdges(loaded.edges);
        setName(detail.title);
        setScene(detail);
        setActiveShot(shot.n);
        setReady(true);
        setSaveState(saved.stale ? "Rebuilt from the revised scene" : saved.graph ? "Saved to scene" : "Fresh canvas");
        lastSaved.current = JSON.stringify(
          toLegacy(loaded.nodes, loaded.edges, graphBase.current, { conceptId, shotN: shot.n }).graph,
        );
      } catch (error) {
        if (!cancelled) setSceneError(error instanceof Error ? error.message : "Could not load scene");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conceptId, shotN, setNodes, setEdges]);

  /* The canvas's reference wiring IS the scene's reference list
     (2026-09-18): rewiring a face here changes what Pipeline shows,
     what the reference gate checks and what Queue renders against --
     not just this drawing. Runs inside the save chain, BEFORE the graph
     save, because a new ref list is a new seed hash and the graph must
     be saved against the hash it now matches. */
  const pushRefs = async (ns: FlowNode[], es: Edge[]): Promise<string | null> => {
    if (!conceptId || !activeShot) return null;
    const next = sceneRefs(ns, es, savedRefs.current);
    if (JSON.stringify(next) === JSON.stringify(savedRefs.current)) return null;
    if (!next.length) return "keeps its last references — a scene with none can't reach the Queue";
    const res = await apiFetch<{ changed: boolean; seed_hash?: string }>(
      `/concepts/${conceptId}/shots/${activeShot}/refs`,
      { method: "PUT", body: JSON.stringify({ refs: next, seed_hash: seedHash.current ?? undefined }) },
    );
    if (res.seed_hash) seedHash.current = res.seed_hash;
    savedRefs.current = next;
    return res.changed ? `references updated (${next.length})` : null;
  };

  // autosave: the graph that ran and the graph you return to are one row
  useEffect(() => {
    if (!conceptId || !activeShot || !ready || sceneError) return;
    const payload = toLegacy(nodes, edges, graphBase.current, { conceptId, shotN: activeShot });
    const fingerprint = JSON.stringify(payload.graph);
    if (fingerprint === lastSaved.current) return;
    const timer = setTimeout(() => {
      setSaveState("Saving…");
      saveChain.current = saveChain.current
        .catch(() => {})
        .then(async () => {
          if (stopped.current) return;
          try {
            const refNote = await pushRefs(nodes, edges);
            // seed_hash is what this canvas was drawn against; the server
            // refuses (409) a save for a scene revised underneath it rather
            // than overwriting a canvas nobody here has seen
            const saved = await apiFetch<{ seed_hash?: string }>(`/concepts/${conceptId}/shots/${activeShot}/graph`, {
              method: "PUT",
              body: JSON.stringify({ graph: payload.graph, states: payload.states, name, seed_hash: seedHash.current ?? undefined }),
            });
            if (saved.seed_hash) seedHash.current = saved.seed_hash;
            lastSaved.current = fingerprint;
            setSaveState(refNote ? `Saved to scene · ${refNote}` : "Saved to scene");
          } catch (error) {
            setSaveState(`Not saved: ${error instanceof Error ? error.message : "connection lost"}`);
          }
        });
    }, 650);
    return () => clearTimeout(timer);
    // pushRefs reads refs and the deps listed here; it is not state of its own
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conceptId, activeShot, nodes, edges, name, ready, sceneError, saveRevision]);

  const savePrompt = async () => {
    if (!conceptId || !activeShot) return;
    const promptNodes = getNodes().filter((n) => ["prompt", "enhance"].includes(n.data.kind));
    const chosen = promptNodes.find((n) => n.selected) || promptNodes.find((n) => n.data.originalPrompt) || promptNodes[0];
    const prompt = chosen?.data.text?.trim();
    if (!prompt) {
      notify("Select a nonempty prompt node to save to the scene.");
      return;
    }
    try {
      await saveChain.current.catch(() => {});
      const res = await apiFetch<{ seed_hash?: string }>(`/concepts/${conceptId}/shots/${activeShot}/prompt`, {
        method: "POST",
        body: JSON.stringify({ prompt }),
      });
      // this canvas made the edit, so it is still a true drawing of the
      // shot: adopt the new hash or the next autosave is refused as stale
      if (res?.seed_hash) seedHash.current = res.seed_hash;
      lastSaved.current = "";
      setSaveRevision((n) => n + 1);
      notify("Scene prompt updated");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not save prompt");
    }
  };
  const flushAndGo = async (destination: string) => {
    if (conceptId && activeShot && ready && !sceneError) {
      try {
        stopped.current = true;
        await saveChain.current.catch(() => {});
        await pushRefs(getNodes(), getEdges());
        const payload = toLegacy(getNodes(), getEdges(), graphBase.current, { conceptId, shotN: activeShot });
        await apiFetch(`/concepts/${conceptId}/shots/${activeShot}/graph`, {
          method: "PUT",
          body: JSON.stringify({ graph: payload.graph, states: payload.states, name }),
        });
      } catch (error) {
        stopped.current = false;
        notify(`Could not save before leaving: ${error instanceof Error ? error.message : "connection lost"}`);
        return;
      }
    }
    window.location.assign(destination);
  };

  const update = useCallback(
    (id: string, data: Partial<CardData>) =>
      setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...data } } : n))),
    [setNodes],
  );
  // appended against the LIVE node, not the render's copy: an upload
  // resolves seconds later and may race a remove or a second upload
  const addFrames = useCallback(
    (id: string, urls: string[]) =>
      setNodes((ns) =>
        ns.map((n) => {
          if (n.id !== id) return n;
          const have = n.data.urls || [];
          return { ...n, data: { ...n.data, urls: [...have, ...urls.filter((u) => !have.includes(u))] } };
        }),
      ),
    [setNodes],
  );
  const remove = useCallback(
    (id: string) => {
      setNodes((ns) => ns.filter((n) => n.id !== id));
      setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    },
    [setNodes, setEdges],
  );
  const duplicate = useCallback(
    (id: string) =>
      setNodes((ns) => {
        const node = ns.find((n) => n.id === id);
        return node
          ? [
              ...ns,
              {
                ...node,
                id: crypto.randomUUID(),
                selected: false,
                position: { x: node.position.x + 45, y: node.position.y + 45 },
                data: { ...node.data, busy: false, jobId: undefined },
              },
            ]
          : ns;
      }),
    [setNodes],
  );
  const addNode = (kind: Kind) => {
    setNodes((ns) => [
      ...ns,
      {
        id: crypto.randomUUID(),
        type: "studio",
        position: screenToFlowPosition({ x: window.innerWidth / 2 - 120, y: window.innerHeight / 2 - 120 }),
        data: {
          kind,
          label: titles[kind],
          text: kind === "prompt" ? "" : undefined,
          urls: kind === "element" ? [] : undefined,
          refKind: kind === "element" ? "upload" : undefined,
        },
      },
    ]);
    setAddMenu(false);
    setShowTemplates(false);
  };

  /* an @-mention (in the bar or a prompt card) drops the element on the
     canvas, already wired into every card with a refs port */
  const addElement = (hit: { name: string; category: string; thumb: string | null }) => {
    const asset = assets.find((a) => a.name === hit.name && a.category === hit.category);
    const urls = asset ? asset.photos.slice(0, 6) : hit.thumb ? [hit.thumb] : [];
    if (!urls.length) {
      notify(`${hit.name} has no photos on file — add some on Elements`);
      return;
    }
    const refKind = hit.category as RefKind;
    const label = elementLabel(refKind, hit.name);
    const current = getNodes();
    let node = current.find((n) => n.data.kind === "element" && n.data.label === label);
    if (!node) {
      const els = current.filter((n) => n.data.kind === "element");
      const last = els.length ? els.reduce((a, b) => (b.position.y > a.position.y ? b : a)) : null;
      node = {
        id: crypto.randomUUID(),
        type: "studio",
        position: last ? { x: last.position.x, y: last.position.y + 260 } : { x: 400, y: 0 },
        data: { kind: "element", label, refKind, urls },
      };
      setNodes((ns) => [...ns, node!]);
    }
    const fresh = wireElement(node, current).filter(
      (e) => !getEdges().some((x) => x.source === e.source && x.target === e.target && x.targetHandle === "refs"),
    );
    setEdges((es) => [...es, ...fresh]);
    notify(`${hit.name} on the canvas · wired into ${fresh.length} node${fresh.length === 1 ? "" : "s"}`);
    setShowTemplates(false);
  };

  /* wiring rules: matching ports only, no cycles, one wire per single port */
  const connectionValid = (connection: Edge | Connection) => {
    if (connection.source === connection.target) return false;
    const source = getNodes().find((n) => n.id === connection.source);
    const target = getNodes().find((n) => n.id === connection.target);
    const port = connection.targetHandle || "prompt";
    if (!source || !target || !ports(target.data.kind).includes(port)) return false;
    if (!compatible(source.data.kind, port)) return false;
    const visit = (id: string, seen = new Set<string>()): boolean => {
      if (id === connection.source) return true;
      if (seen.has(id)) return false;
      seen.add(id);
      return getEdges()
        .filter((e) => e.source === id)
        .some((e) => visit(e.target, seen));
    };
    return !visit(connection.target);
  };
  const onConnect = (connection: Connection) =>
    setEdges((es) =>
      addEdge(
        connection,
        es.filter(
          (e) =>
            !(
              e.target === connection.target &&
              e.targetHandle === connection.targetHandle &&
              connection.targetHandle !== "refs"
            ),
        ),
      ),
    );

  const pickTemplate = (id: Template) => {
    if (conceptId) {
      notify("Scene graphs use their own prompt and references. Open a blank flow for templates.");
      return;
    }
    const next = makeTemplate(id);
    setNodes(next.nodes);
    setEdges(next.edges);
    setTemplate(id);
    setTimeout(() => fitView({ padding: 0.22, duration: 400 }), 60);
  };
  const exportDraft = () => {
    const blob = new Blob([JSON.stringify({ version: 1, name, nodes, edges }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name.replace(/[^a-z0-9-]/gi, "-") || "workflow"}.json`;
    a.click();
    URL.revokeObjectURL(url);
    notify("Workflow exported");
  };
  const importDraft = async (file?: File) => {
    if (!file) return;
    if (conceptId) {
      notify("Import into a blank flow to keep this scene graph intact.");
      return;
    }
    try {
      const data: unknown = JSON.parse(await file.text());
      if (!validDraft(data)) throw new Error("Choose a Zero Page workflow JSON export.");
      setNodes(data.nodes.map((n) => ({ ...n, data: { ...n.data, busy: !!n.data.jobId } })));
      setEdges(data.edges);
      setName(data.name);
      setShowTemplates(false);
      notify("Workflow imported");
      setTimeout(() => fitView({ padding: 0.2 }), 60);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not import workflow");
    }
    if (inputRef.current) inputRef.current.value = "";
  };

  /* ── a per-node run (the card's Run) ── */
  const execute = async (id: string) => {
    setConfirm(null);
    const currentNodes = getNodes();
    const node = currentNodes.find((n) => n.id === id);
    if (!node || pending.current.has(id) || node.data.busy) return;
    const inputEdges = getEdges().filter((e) => e.target === id);
    const src = (port: string) =>
      currentNodes.find((n) => n.id === inputEdges.find((e) => (e.targetHandle || "prompt") === port)?.source);
    const inputText = (port: string) => src(port)?.data.text || "";
    const prompt = inputText("prompt").trim() || (node.data.kind === "ground" ? node.data.text || "" : "");
    // the keyframe port first, then every element wired in, then the frozen refs
    const images = [
      ...new Set([
        src("reference")?.data.url,
        ...inputEdges
          .filter((e) => e.targetHandle === "refs")
          .flatMap((e) => {
            const s = currentNodes.find((n) => n.id === e.source);
            return s?.data.kind === "element" ? s.data.urls || [] : [s?.data.url];
          }),
        ...(node.data.refs || []),
      ]),
    ].filter((url): url is string => !!url && /^(https?:\/\/|\/)/.test(url));
    if (!prompt && node.data.kind !== "ground") {
      update(id, { error: "Connect a prompt or run its upstream enhancement first." });
      return;
    }
    pending.current.add(id);
    update(id, { busy: true, error: undefined });
    try {
      if (node.data.kind === "ground") {
        const result = await apiFetch<{ references: string }>("/workflows/exec/ground", {
          method: "POST",
          body: JSON.stringify({ spark: prompt }),
        });
        update(id, { text: result.references, busy: false });
        return;
      }
      const endpoint = node.data.kind === "enhance" ? "enhance" : node.data.kind === "video" ? "generate" : "nano";
      const body =
        node.data.kind === "enhance"
          ? {
              user: prompt,
              system: inputText("system"),
              references: inputText("references"),
              images,
              ground: !inputText("references"),
            }
          : {
              prompt,
              images,
              ...(conceptId && activeShot ? { concept_id: conceptId, shot_n: activeShot } : {}),
              // the signed quote the chip showed (pricing.sign); the route
              // refuses the run if the scene or the renderer moved since
              ...(node.data.kind === "video" && conceptId && scene?.generate?.renders?.[0]?.token
                ? { token: scene.generate.renders[0].token }
                : {}),
            };
      const job = await apiFetch<{ job_id: number }>(`/workflows/exec/${endpoint}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      update(id, { jobId: job.job_id });
    } catch (error) {
      update(id, { busy: false, error: error instanceof Error ? error.message : "Generation failed" });
    } finally {
      pending.current.delete(id);
    }
  };
  // per-node jobs: poll until terminal
  useEffect(() => {
    const jobs = nodes.filter((n) => n.data.jobId && n.data.busy);
    if (!jobs.length) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      await Promise.all(
        jobs.map(async (n) => {
          try {
            const job = await apiFetch<{ status: string; output?: string; error?: string }>(`/jobs/${n.data.jobId}`);
            if (cancelled) return;
            if (job.status === "done")
              update(n.id, {
                busy: false,
                jobId: undefined,
                ...(isText(n.data.kind) ? { text: job.output } : { url: job.output }),
              });
            else if (["failed", "cancelled"].includes(job.status))
              update(n.id, { busy: false, jobId: undefined, error: job.error || job.status });
            else update(n.id, { busy: true });
          } catch (error) {
            if (!cancelled)
              update(n.id, {
                busy: false,
                error: `Could not check render: ${error instanceof Error ? error.message : "connection lost"}`,
              });
          }
        }),
      );
    }, 2500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [nodes, update]);

  /* ── Generate = Run all: save, then the runner walks the graph ── */
  const runAll = async () => {
    if (!conceptId || !activeShot) {
      notify("Open a concept's scene to run the chain — a draft runs card by card.");
      return;
    }
    if (runJob) return;
    try {
      await saveChain.current.catch(() => {});
      await pushRefs(getNodes(), getEdges());
      const payload = toLegacy(getNodes(), getEdges(), graphBase.current, { conceptId, shotN: activeShot });
      const saved = await apiFetch<{ id: number }>(`/concepts/${conceptId}/shots/${activeShot}/graph`, {
        method: "PUT",
        body: JSON.stringify({ graph: payload.graph, name }),
      });
      lastSaved.current = JSON.stringify(payload.graph);
      // the runner reports node_states by the legacy id toLegacy assigned
      const byLegacy = new Map<string, string>();
      payload.ids.forEach((legacyId, nodeId) => byLegacy.set(String(legacyId), nodeId));
      setNodes((ns) =>
        ns.map((n) => (isMedia(n.data.kind) || ["enhance", "ground"].includes(n.data.kind)
          ? { ...n, data: { ...n.data, error: undefined } }
          : n)),
      );
      const job = await apiFetch<{ job_id: number }>(`/workflows/${saved.id}/run`, { method: "POST", body: "{}" });
      runMap.current = byLegacy;
      setRunJob({ id: job.job_id });
      setRunProgress("Running the chain…");
    } catch (error) {
      notify(`Run failed: ${error instanceof Error ? error.message : "connection lost"}`);
    }
  };
  const runMap = useRef(new Map<string, string>());
  useEffect(() => {
    if (!runJob) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const job = await apiFetch<{
          status: string;
          detail?: string;
          error?: string;
          progress?: number;
          node_states?: Record<string, NodeState>;
        }>(`/jobs/${runJob.id}`);
        if (cancelled) return;
        const states = job.node_states || {};
        setNodes((ns) =>
          ns.map((n) => {
            const legacyId = [...runMap.current].find(([, nodeId]) => nodeId === n.id)?.[0];
            const s = legacyId ? states[legacyId] : undefined;
            if (!s) return n;
            const done = s.status === "done";
            const out = typeof s.output === "string" ? s.output : undefined;
            return {
              ...n,
              data: {
                ...n.data,
                busy: s.status === "running",
                error: s.status === "failed" || s.status === "skipped" ? s.error || s.status : undefined,
                ...(done && ["enhance", "ground"].includes(n.data.kind) ? { text: out } : {}),
                ...(done && isMedia(n.data.kind) ? { url: out } : {}),
              },
            };
          }),
        );
        setRunProgress(job.detail || job.status);
        if (["done", "failed", "cancelled"].includes(job.status)) {
          setRunJob(null);
          setRunProgress("");
          notify(job.status === "done" ? job.detail || "Run complete" : job.error || `Run ${job.status}`);
          lastSaved.current = "";
          setSaveRevision((n) => n + 1);
          if (job.status === "done") announceQueueChange();
        }
      } catch (error) {
        if (!cancelled) {
          setRunJob(null);
          setRunProgress("");
          notify(`Lost the run: ${error instanceof Error ? error.message : "connection lost"}`);
        }
      }
    };
    const timer = setInterval(tick, 2000);
    void tick();
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runJob?.id]);

  /* ── Send to Queue: the pick. Approving there renders. ── */
  const inQueue = !!(scene && (scene.picked || scene.parked || scene.media_url));
  const sendToQueue = async () => {
    if (!scene) {
      notify("Open a concept first — the brief on Pipeline builds one");
      return;
    }
    if (inQueue) {
      void flushAndGo(`${API_URL}/ui?view=queue`);
      return;
    }
    try {
      await saveChain.current.catch(() => {});
      await pushRefs(getNodes(), getEdges());
      await pickConcept(scene.id, true);
      setScene({ ...scene, picked: true });
      announceQueueChange();
      shell.toast(`${scene.n} is in the Queue — approving it there renders the clip`);
    } catch (error) {
      notify(`Send to Queue failed: ${error instanceof Error ? error.message : "connection lost"}`);
    }
  };

  /* ── the prompt bar edits the scene's prompt card ── */
  const promptNode = useMemo(
    () => nodes.find((n) => n.data.kind === "prompt" && n.data.originalPrompt) || nodes.find((n) => n.data.kind === "prompt"),
    [nodes],
  );
  useEffect(() => {
    if (document.activeElement === barRef.current) return;
    setBar(promptNode?.data.text || "");
  }, [promptNode?.data.text]);
  const setBarText = (v: string) => {
    setBar(v);
    if (promptNode) update(promptNode.id, { text: v });
  };
  const mentions = useMentions(barRef, bar, setBarText, addElement);
  const foldPreset = (p: Preset) => {
    if (!promptNode) return;
    const text = (promptNode.data.text || "").trim();
    if (!text.includes(p.how)) setBarText((text ? text + "\n\n" : "") + p.how);
    const video = getNodes().find((n) => n.data.kind === "video");
    if (video) update(video.id, { camera: p.label });
    notify(`${p.label} folded into the prompt`);
  };

  const selectedNode = nodes.find((n) => n.selected);
  // What the Generate node would render ON and cost: the server's own
  // price (`generate`, pricing.display) laid over the Runway state the
  // chips read. Without it every Run was priced at Runway's default clip,
  // even on an account whose only key -- and bill -- is another vendor's.
  const gen = scene?.generate && !scene.generate.error ? scene.generate : null;
  const rw =
    scene?.runway && gen
      ? { ...scene.runway, model: gen.model, duration: gen.durations[0], estimate_usd: gen.estimate_usd }
      : (scene?.runway ?? null);

  return (
    <Actions.Provider
      value={{
        update,
        addFrames,
        remove,
        duplicate,
        run: (id) => {
          const node = getNodes().find((n) => n.id === id);
          if (node?.data.jobId) update(id, { busy: true, error: undefined });
          else setConfirm(id);
        },
        runway: rw,
        caps,
      }}
    >
      <main className={`flows-workspace ${showTemplates ? "templates-open" : ""} tool-${tool}${selectedNode ? " has-inspector" : ""}`}>
        <header className="flow-topbar">
          <div className="flow-breadcrumb">
            {/* the React board, not the API's legacy /ui (which only bounced
                back here through a handoff) */}
            <button aria-label="Back to Pipeline" title="Back to Pipeline" onClick={() => flushAndGo("/studio/pipeline")}>
              <ArrowLeft size={16} />
            </button>
            {scene ? (
              <SceneSwitcher
                currentId={conceptId}
                brand={shell.brand}
                go={flushAndGo}
                label={
                  <>
                    <Clapperboard size={11} /> {scene.n.toLowerCase()} · {scene.title.toLowerCase().slice(0, 26)}
                  </>
                }
              />
            ) : (
              <>
                <input aria-label="Workflow name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
                {!conceptId ? (
                  <SceneSwitcher
                    brand={shell.brand}
                    go={flushAndGo}
                    label={
                      <>
                        <Clapperboard size={11} /> open a scene
                      </>
                    }
                  />
                ) : null}
              </>
            )}
            {scene && scene.shots.length > 1 && (
              <select aria-label="Shot" value={activeShot} onChange={(e) => flushAndGo(`/studio/flows?concept=${conceptId}&shot=${e.target.value}`)}>
                {scene.shots.map((s) => (
                  <option key={s.n} value={s.n}>
                    Shot {s.n}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="flow-top-actions">
            <span className="save-indicator">
              <i />
              {conceptId ? saveState : storageError ? "Local save unavailable" : "Local draft"}
            </span>
            {conceptId && (
              <>
                <button onClick={savePrompt} disabled={!ready} className="pill-btn">
                  Save scene prompt
                </button>
                <button onClick={sendToQueue} disabled={!ready} className={`queue-btn${inQueue ? " lit" : ""}`}>
                  <ListVideo size={14} /> {scene?.media_url ? "Rendered · see Queue" : inQueue ? "In the Queue" : "Send to Queue"}
                </button>
              </>
            )}
            {!conceptId && (
              <>
                <button title="Import workflow" aria-label="Import workflow" onClick={() => inputRef.current?.click()}>
                  <Upload size={16} />
                </button>
                <button className="pill-btn" onClick={exportDraft}>
                  <Download size={14} /> Export
                </button>
              </>
            )}
          </div>
        </header>

        <section className="flow-stage" aria-label="Workflow canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onEdgeClick={(_, edge) => {
              if (tool === "cut") {
                setEdges((es) => es.filter((e) => e.id !== edge.id));
                notify("Wire cut");
              }
            }}
            isValidConnection={connectionValid}
            fitView
            fitViewOptions={{ padding: 0.12, maxZoom: 0.85 }}
            minZoom={0.2}
            maxZoom={1.7}
            panOnDrag={tool === "hand" ? true : [1, 2]}
            selectionOnDrag={tool === "select"}
            nodesDraggable={tool !== "hand"}
            deleteKeyCode={["Backspace", "Delete"]}
            onMove={(_, viewport) => setZoom(viewport.zoom)}
            defaultEdgeOptions={{ type: "default", style: { stroke: "rgb(255 255 255 / 0.28)", strokeWidth: 1.5 } }}
          >
            <Background color="rgb(255 255 255 / 0.14)" gap={26} size={1.1} />
            <MiniMap pannable zoomable nodeColor="rgb(255 255 255 / 0.3)" maskColor="rgb(4 4 5 / 0.72)" />
          </ReactFlow>
        </section>

        <div className="canvas-zoom">
          <button aria-label="Zoom out" title="Zoom out" onClick={() => zoomOut({ duration: 180 })}>
            <ZoomOut size={15} />
          </button>
          <button aria-label="Zoom in" title="Zoom in" onClick={() => zoomIn({ duration: 180 })}>
            <ZoomIn size={15} />
          </button>
          <button aria-label="Fit canvas" title="Fit to view" onClick={() => fitView({ padding: 0.18, duration: 350 })}>
            <Maximize size={15} />
          </button>
          <span>{Math.round(zoom * 100)}%</span>
        </div>

        {selectedNode ? (
          <aside className="flow-inspector">
            <div className="insp-head">
              <span className="m">node</span>
              <b>{selectedNode.data.label}</b>
              <span className="spacer" />
              <button aria-label="Close" onClick={() => setNodes((ns) => ns.map((n) => ({ ...n, selected: false })))}>
                <X size={13} />
              </button>
            </div>
            <div className="insp-body">
              <div className="insp-sec">
                <span className="m">what it does</span>
                <p>{notes[selectedNode.data.kind]}</p>
              </div>
              <div className="insp-sec">
                <span className="m">name</span>
                <input value={selectedNode.data.label} onChange={(e) => update(selectedNode.id, { label: e.target.value })} />
              </div>
              {selectedNode.data.kind === "video" && presets.length ? (
                <div className="insp-sec">
                  <span className="m">camera motion · folds a preset into the prompt</span>
                  <div className="insp-cams">
                    {presets.map((p) => (
                      <button key={p.id} className={selectedNode.data.camera === p.label ? "on" : ""} onClick={() => foldPreset(p)}>
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {selectedNode.data.kind === "video" ? (
                <div className="insp-sec">
                  <span className="m">spend</span>
                  <div className="insp-spend">
                    <b>{rw?.estimate_usd != null ? `$${Number(rw.estimate_usd).toFixed(2)}` : "—"}</b>
                    <span>
                      per {rw?.duration ?? 5}-second clip · {rw?.model ?? "gen4_turbo"}
                    </span>
                  </div>
                  {gateNote("video", caps) ? <span className="m gate">{gateNote("video", caps)}</span> : null}
                </div>
              ) : null}
              {isText(selectedNode.data.kind) && selectedNode.data.text && !["prompt", "system"].includes(selectedNode.data.kind) ? (
                <div className="insp-sec">
                  <span className="m">output</span>
                  <pre>{selectedNode.data.text}</pre>
                </div>
              ) : null}
              <div className="insp-sec">
                <span className="m">connections</span>
                <span className="insp-wires">
                  {edges.filter((e) => e.target === selectedNode.id).length} in · {edges.filter((e) => e.source === selectedNode.id).length} out
                </span>
              </div>
            </div>
            {conceptId ? (
              <div className="insp-foot">
                <button className={`queue-btn wide${inQueue ? " lit" : ""}`} onClick={sendToQueue}>
                  <ListVideo size={15} /> {inQueue ? "In the Queue" : "Send to Queue"}
                </button>
              </div>
            ) : null}
          </aside>
        ) : null}

        {showTemplates && (
          <aside className="flow-templates">
            <div className="template-title">
              <span className="m">A place to begin</span>
              <button aria-label="Close templates" onClick={() => setShowTemplates(false)}>
                <X size={15} />
              </button>
            </div>
            <h1>
              Build your creative
              <br />
              workflow.
            </h1>
            <p>Start with a template. Make it yours.</p>
            <div className="template-list">
              {templates.map((t) => (
                <button key={t.id} className={template === t.id ? "selected" : ""} onClick={() => pickTemplate(t.id)}>
                  <img src={`/flows/${t.image}.jpg`} alt="" />
                  <span>
                    <strong>{t.title}</strong>
                    <small>{t.text}</small>
                  </span>
                  <ArrowUpRight size={15} />
                </button>
              ))}
            </div>
            <small className="template-note">
              Templates replace the current canvas.
              <br />
              Export first to keep another version.
            </small>
          </aside>
        )}

        <div className="flow-bottom">
          <div className="gs-bar">
            <div className="flow-toolbar">
              <div className="add-node-wrap">
                <button aria-label="Add node" title="Add node" className={addMenu ? "tool-active" : ""} onClick={() => setAddMenu(!addMenu)}>
                  <Plus size={18} />
                </button>
                {addMenu && (
                  <div className="add-node-menu">
                    <span className="m">Add to your flow</span>
                    {(["prompt", "system", "ground", "enhance", "element", "reference", "image", "video"] as Kind[]).map((kind) => (
                      <button key={kind} onClick={() => addNode(kind)}>
                        {kind === "prompt" || kind === "system" ? (
                          <Type size={16} />
                        ) : kind === "reference" || kind === "element" ? (
                          <ImagePlus size={16} />
                        ) : kind === "video" ? (
                          <Film size={16} />
                        ) : (
                          <Sparkles size={16} />
                        )}
                        <span>
                          {titles[kind]}
                          <small>
                            {kind === "prompt"
                              ? "Write your scene"
                              : kind === "system"
                                ? "How the enhance treats the prompt"
                                : kind === "element"
                                  ? "A character, room or prop's frames"
                                  : kind === "reference"
                                    ? "One plate, by url"
                                    : kind === "image"
                                      ? "Generate the keyframe"
                                      : kind === "video"
                                        ? "Generate the clip"
                                        : kind === "ground"
                                          ? "Retrieve from the reference library"
                                          : "Text to enhanced prompt"}
                          </small>
                        </span>
                        <Plus size={12} />
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <i className="tool-divider" />
              <button aria-label="Select tool" title="Select" aria-pressed={tool === "select"} className={tool === "select" ? "tool-active" : ""} onClick={() => setTool("select")}>
                <MousePointer2 size={18} />
              </button>
              <button aria-label="Pan tool" title="Pan" aria-pressed={tool === "hand"} className={tool === "hand" ? "tool-active" : ""} onClick={() => setTool("hand")}>
                <Hand size={18} />
              </button>
              <button aria-label="Cut a wire" title="Cut a wire · click a wire" aria-pressed={tool === "cut"} className={tool === "cut" ? "tool-active" : ""} onClick={() => setTool("cut")}>
                <Scissors size={18} />
              </button>
              <button aria-label="Frame all" title="Frame all" onClick={() => fitView({ padding: 0.18, duration: 350 })}>
                <Grid2X2 size={18} />
              </button>
              {!conceptId ? (
                <button aria-label="Show templates" title="Templates" aria-pressed={showTemplates} onClick={() => setShowTemplates(!showTemplates)}>
                  <Layers size={18} />
                </button>
              ) : null}
            </div>
            <div className="gs-prompt">
              <textarea
                ref={barRef}
                rows={1}
                value={bar}
                disabled={!promptNode}
                placeholder={promptNode ? "Describe the shot… (@ to bring an element onto the canvas)" : "Add a Prompt card to start a chain"}
                onChange={(e) => setBarText(e.target.value)}
                onKeyDown={(e) => {
                  if (mentions.onKeyDown(e)) return;
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void runAll();
                }}
                onBlur={mentions.onBlur}
                aria-label="Scene prompt"
              />
              {mentions.dropdown}
            </div>
            <div className="gs-chips">
              <span className="chip">
                <Sparkles size={11} /> {rw?.model ?? "runway"}
              </span>
              <span className="chip">
                <RectangleVertical size={11} /> {ratioLabel(rw?.ratio)}
              </span>
              <span className="chip">
                <Clock size={11} /> {rw?.duration ?? 5} sec
              </span>
            </div>
            <button className="gs-go" disabled={!!runJob || !conceptId} title={conceptId ? "Run the whole chain" : "Open a concept to run the chain"} onClick={() => void runAll()}>
              {runJob ? <LoaderCircle size={15} className="spin" /> : <Sparkles size={15} />}
              {runJob ? runProgress || "Running…" : "Generate"}
            </button>
          </div>
          <span className="canvas-caption">
            {nodes.length} nodes <i /> {edges.length} connections
          </span>
        </div>

        <input ref={inputRef} type="file" accept="application/json,.json" hidden onChange={(e) => importDraft(e.target.files?.[0])} />

        {conceptId && (!ready || sceneError) && (
          <div className="flow-modal-backdrop">
            <section className="flow-modal" role="status">
              <h2>{sceneError ? "Could not open scene" : "Opening Director…"}</h2>
              <p>{sceneError || "Loading the saved prompt, references and canvas."}</p>
              {sceneError && (
                <div>
                  {/* the same sign-in every other page uses: it comes back here */}
                  <button onClick={() => goToSignIn()}>Sign in</button>
                  <button onClick={() => window.location.reload()}>Retry</button>
                  <a href="/studio/pipeline">Back to Pipeline</a>
                </div>
              )}
            </section>
          </div>
        )}
        {toast && (
          <div className="flow-toast" role="status">
            <Check size={14} />
            {toast}
          </div>
        )}
        {confirm && (
          <div className="flow-modal-backdrop" onClick={() => setConfirm(null)}>
            <section
              ref={dialogRef}
              className="flow-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="render-title"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.stopPropagation();
                  setConfirm(null);
                }
              }}
            >
              <button className="modal-close" aria-label="Close" onClick={() => setConfirm(null)}>
                <X size={18} />
              </button>
              <div className="modal-icon">
                <Zap size={23} />
              </div>
              <h2 id="render-title">Run {nodes.find((n) => n.id === confirm)?.data.label}?</h2>
              <p>
                {nodes.find((n) => n.id === confirm)?.data.kind === "video"
                  ? "This renders a clip through Runway and spends real credit — the module's own gate (RUNWAY_SPEND_OK) still has the last word."
                  : "This is a billed model call under the project's daily caps."}
              </p>
              <div>
                <button onClick={() => setConfirm(null)}>Keep editing</button>
                <button className="light-button" onClick={() => execute(confirm)}>
                  <Play size={14} /> Run
                </button>
              </div>
            </section>
          </div>
        )}
      </main>
    </Actions.Provider>
  );
}
function validDraft(value: unknown): value is Draft {
  if (!value || typeof value !== "object") return false;
  const d = value as Draft;
  if (
    d.version !== 1 ||
    typeof d.name !== "string" ||
    !Array.isArray(d.nodes) ||
    !Array.isArray(d.edges) ||
    d.nodes.length > 500 ||
    d.edges.length > 2000
  )
    return false;
  const ids = new Set<string>();
  for (const node of d.nodes) {
    if (
      !node ||
      typeof node.id !== "string" ||
      ids.has(node.id) ||
      node.type !== "studio" ||
      !Number.isFinite(node.position?.x) ||
      !Number.isFinite(node.position?.y) ||
      !node.data ||
      !["prompt", "reference", "element", "image", "video", "system", "enhance", "ground"].includes(node.data.kind) ||
      typeof node.data.label !== "string"
    )
      return false;
    if (node.data.text !== undefined && typeof node.data.text !== "string") return false;
    if (
      node.data.url !== undefined &&
      (typeof node.data.url !== "string" || (node.data.url !== "" && !/^(https?:\/\/|\/)/.test(node.data.url)))
    )
      return false;
    ids.add(node.id);
  }
  return d.edges.every((e) => e && typeof e.id === "string" && ids.has(e.source) && ids.has(e.target));
}
export default function FlowWorkspace(props: { conceptId?: number; shotN?: number }) {
  return (
    <ReactFlowProvider>
      <Workspace {...props} />
    </ReactFlowProvider>
  );
}

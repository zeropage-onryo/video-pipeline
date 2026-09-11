"use client";

/* Arbitrary reference hosts and provider outputs are displayed directly, without an image proxy. */
/* eslint-disable @next/next/no-img-element */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  createContext,
  useContext,
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
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Film,
  FolderOpen,
  Grid2X2,
  Hand,
  Home,
  ImagePlus,
  Layers,
  Maximize,
  MoreHorizontal,
  MousePointer2,
  Plus,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  Type,
  Upload,
  Workflow,
  X,
  Zap,
  ZoomIn,
  ZoomOut,
  Play,
  LoaderCircle,
} from "lucide-react";
import { apiFetch, API_URL } from "@/lib/api";
import "@xyflow/react/dist/style.css";
import "./flows.css";

import {
  fromLegacy,
  toLegacy,
  seedScene,
  isText,
  ports,
  type Kind,
  type CardData,
  type FlowNode,
  type LegacyGraph,
  type NodeState,
  type Shot,
} from "@/lib/director-graph";

type Template = "image" | "video" | "variety";
type Draft = { version: 1; name: string; nodes: FlowNode[]; edges: Edge[] };
const KEY = "zeropage.flow-draft.v1";
const titles = {
  prompt: "Prompt",
  image: "Nano Banana",
  video: "Runway",
  reference: "Reference image",
  system: "Instructions",
  enhance: "Enhance prompt",
  ground: "Ground in references",
};
const starterText =
  "A solitary rider crosses a sunlit field. Wind moves through the tall grass, warm afternoon light, subtle film grain. A quiet, unhurried moment.";
const templates: {
  id: Template;
  title: string;
  text: string;
  image: string;
}[] = [
  {
    id: "image",
    title: "Image generation",
    text: "Turn a thought into a frame.",
    image: "image-study",
  },
  {
    id: "video",
    title: "Video generation",
    text: "Give your still a little motion.",
    image: "motion-study",
  },
  {
    id: "variety",
    title: "Explore variations",
    text: "One prompt. Three directions.",
    image: "model-study",
  },
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
  const edges: Edge[] = [
    {
      id: "prompt-image",
      source: "prompt",
      target: "image",
      targetHandle: "prompt",
    },
  ];
  if (type === "video") {
    nodes.push({
      id: "video",
      type: "studio",
      position: { x: 980, y: 50 },
      data: { kind: "video", label: "Runway" },
    });
    edges.push(
      {
        id: "image-video",
        source: "image",
        target: "video",
        targetHandle: "reference",
      },
      {
        id: "prompt-video",
        source: "prompt",
        target: "video",
        targetHandle: "prompt",
      },
    );
  }
  if (type === "variety") {
    image.position.y = -150;
    nodes.push(
      ...[1, 2].map((n): FlowNode => ({
        id: `take-${n}`,
        type: "studio",
        position: { x: 530, y: -150 + n * 380 },
        data: { kind: "image", label: `Nano Banana · Take ${n + 1}` },
      })),
    );
    edges.push(
      ...[1, 2].map((n) => ({
        id: `prompt-take-${n}`,
        source: "prompt",
        target: `take-${n}`,
        targetHandle: "prompt",
      })),
    );
  }
  return { nodes, edges };
}
const Actions = createContext<{
  update: (id: string, data: Partial<CardData>) => void;
  remove: (id: string) => void;
  duplicate: (id: string) => void;
  run: (id: string) => void;
}>({ update: () => {}, remove: () => {}, duplicate: () => {}, run: () => {} });

function StudioNode({ id, data, selected }: NodeProps<FlowNode>) {
  const actions = useContext(Actions);
  const Icon =
    data.kind === "prompt"
      ? Type
      : data.kind === "video"
        ? Film
        : data.kind === "reference"
          ? ImagePlus
          : Sparkles;
  const [menu, setMenu] = useState(false);
  return (
    <article
      className={`flow-card ${selected ? "is-selected" : ""} kind-${data.kind}`}
    >
      {ports(data.kind).map((port, i) => (
        <Handle
          key={port}
          type="target"
          position={Position.Left}
          id={port}
          title={port}
          className={port === "reference" ? "port-image" : "port-text"}
          style={{ top: 39 + i * 46 }}
        />
      ))}
      <header className="node-header">
        <Icon size={15} />
        <span>{data.label}</span>
        <button
          aria-label={`Options for ${data.label}`}
          className="nodrag node-menu-toggle"
          onClick={() => setMenu(!menu)}
        >
          <MoreHorizontal size={17} />
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
            placeholder="Describe what you imagine…"
            value={data.text || ""}
            onChange={(e) => actions.update(id, { text: e.target.value })}
          />
          <footer className="prompt-footer">
            <span>@</span>
            {["enhance", "ground"].includes(data.kind) ? (
              <button
                className="nodrag"
                disabled={data.busy}
                onClick={() => actions.run(id)}
              >
                {data.busy ? "Running…" : "Run"} <Zap size={12} />
              </button>
            ) : (
              <span>
                {data.kind === "system"
                  ? "ENHANCE INSTRUCTIONS"
                  : "YOUR STARTING POINT"}
              </span>
            )}
          </footer>
          {data.error && (
            <p role="alert" className="node-error">
              {data.error}
            </p>
          )}
        </>
      ) : data.kind === "reference" ? (
        <div className="reference-body nodrag">
          {data.url ? (
            <img
              src={
                data.url.startsWith("/") ? `${API_URL}${data.url}` : data.url
              }
              alt="Your reference"
            />
          ) : (
            <div className="empty-media">
              <ImagePlus size={28} />
              <span>Add a reference image</span>
            </div>
          )}
          <label>
            Public image URL
            <input
              aria-label="Reference image URL"
              placeholder="https://…"
              value={data.url || ""}
              onChange={(e) => actions.update(id, { url: e.target.value })}
            />
          </label>
          <small>Connect to a purple image port.</small>
        </div>
      ) : (
        <>
          <div className="node-preview nodrag">
            {data.url ? (
              data.kind === "video" ? (
                <video
                  src={
                    data.url.startsWith("/")
                      ? `${API_URL}${data.url}`
                      : data.url
                  }
                  controls
                />
              ) : (
                <img
                  src={
                    data.url.startsWith("/")
                      ? `${API_URL}${data.url}`
                      : data.url
                  }
                  alt="Generated frame"
                />
              )
            ) : (
              <div className="empty-media">
                {data.busy ? (
                  <LoaderCircle size={28} className="spin" />
                ) : (
                  <Icon size={27} strokeWidth={1} />
                )}
                <span>
                  {data.busy
                    ? "Creating your next frame…"
                    : data.kind === "video"
                      ? "Your scene, in motion"
                      : "A new perspective starts here"}
                </span>
              </div>
            )}
            <span className="preview-tag">
              {data.kind === "video" ? "VIDEO" : "IMAGE"}
            </span>
          </div>
          <div className="node-meta">
            <span>
              <Layers size={12} /> {data.kind === "video" ? "Motion" : "Still"}
            </span>
            <span>Provider defaults</span>
            <span>01</span>
          </div>
          {data.error && (
            <p role="alert" className="node-error nodrag nowheel">
              {data.error}
            </p>
          )}
          <footer className="node-footer nodrag">
            <span>
              {data.busy
                ? "Processing"
                : data.url
                  ? "Ready"
                  : "Ready to create"}
            </span>
            <button disabled={data.busy} onClick={() => actions.run(id)}>
              <Zap size={12} />
              {data.busy ? "Running…" : "Generate"}
            </button>
          </footer>
        </>
      )}
      {!!data.refs?.length && (
        <div className="node-references nodrag">
          {data.refs.map((url, i) => (
            <img
              key={`${url}-${i}`}
              src={url.startsWith("/") ? `${API_URL}${url}` : url}
              alt={`Scene reference ${i + 1}`}
              title={`Scene reference ${i + 1}`}
            />
          ))}
        </div>
      )}
      <Handle
        type="source"
        position={Position.Right}
        id="output"
        className={isText(data.kind) ? "port-text" : "port-image"}
        style={{ top: data.kind === "prompt" ? "50%" : 39 }}
      />
    </article>
  );
}
const nodeTypes = { studio: StudioNode };

function Workspace({
  conceptId,
  shotN,
}: {
  conceptId?: number;
  shotN?: number;
}) {
  const [initial] = useState(() => makeTemplate("variety"));
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(
    initial.nodes,
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [view, setView] = useState<"home" | "flow">("flow");
  const [name, setName] = useState("Untitled flow");
  const [sidebar, setSidebar] = useState(false);
  const [template, setTemplate] = useState<Template>("variety");
  const [showTemplates, setShowTemplates] = useState(!conceptId);
  const [addMenu, setAddMenu] = useState(false);
  const [tool, setTool] = useState<"select" | "hand">("select");
  const [toast, setToast] = useState("");
  const [ready, setReady] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [search, setSearch] = useState("");
  const [storageError, setStorageError] = useState(false);
  const [scene, setScene] = useState<{
    id: number;
    title: string;
    shots: Shot[];
  } | null>(null);
  const [activeShot, setActiveShot] = useState<number | undefined>(shotN);
  const [sceneError, setSceneError] = useState("");
  const [saveState, setSaveState] = useState("Loading scene…");
  const [saveRevision, setSaveRevision] = useState(0);
  const graphBase = useRef<Partial<LegacyGraph>>({});
  const seedHash = useRef<string | null>(null);
  const saveChain = useRef<Promise<unknown>>(Promise.resolve());
  const lastSaved = useRef("");
  const stopped = useRef(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const pending = useRef(new Set<string>());
  const { fitView, zoomIn, zoomOut, screenToFlowPosition, getNodes, getEdges } =
    useReactFlow<FlowNode>();
  const notify = useCallback((text: string) => setToast(text), []);
  useEffect(() => {
    if (view !== "flow") return;
    const timer = setTimeout(
      () => fitView({ padding: 0.12, duration: 250 }),
      120,
    );
    return () => clearTimeout(timer);
  }, [showTemplates, sidebar, view, fitView]);
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
  useEffect(() => {
    if (conceptId) return;
    const timer = setTimeout(() => {
      try {
        const saved = localStorage.getItem(KEY);
        if (saved) {
          const draft = JSON.parse(saved) as Draft;
          if (validDraft(draft)) {
            setNodes(
              draft.nodes.map((n) => ({
                ...n,
                data: { ...n.data, busy: !!n.data.jobId },
              })),
            );
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
        localStorage.setItem(
          KEY,
          JSON.stringify({ version: 1, name, nodes, edges }),
        );
        setStorageError(false);
      } catch {
        setStorageError(true);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [nodes, edges, name, ready, conceptId]);
  useEffect(() => {
    if (!conceptId) return;
    let cancelled = false;
    (async () => {
      try {
        const detail = await apiFetch<{
          id: number;
          title: string;
          shots: Shot[];
        }>(`/concepts/${conceptId}`);
        const shot = detail.shots.find(
          (s) => s.n === (shotN ?? detail.shots[0]?.n),
        );
        if (!shot)
          throw new Error(
            "This scene has no written shot yet. Write its prompt from Pipeline first.",
          );
        const saved = await apiFetch<{
          graph: LegacyGraph | null;
          states?: Record<string, NodeState>;
          seed_hash?: string;
          stale?: boolean;
        }>(`/concepts/${conceptId}/shots/${shot.n}/graph`);
        if (cancelled) return;
        const loaded = saved.graph
          ? fromLegacy(saved.graph, saved.states || {})
          : seedScene(shot);
        // A render can finish after the previous browser closed. The shot is authoritative.
        const image = loaded.nodes.find((n) => n.data.kind === "image");
        const video = loaded.nodes.find((n) => n.data.kind === "video");
        if (image && shot.reference_image)
          image.data.url = shot.reference_image;
        if (video && shot.media_url) video.data.url = shot.media_url;
        graphBase.current = saved.graph || {};
        seedHash.current = saved.seed_hash || null;
        setNodes(loaded.nodes);
        setEdges(loaded.edges);
        setName(detail.title);
        setScene(detail);
        setActiveShot(shot.n);
        setReady(true);
        setSaveState(
          saved.stale ? "Rebuilt from revised scene" : "Saved to scene",
        );
        lastSaved.current = JSON.stringify(
          toLegacy(loaded.nodes, loaded.edges, graphBase.current, {
            conceptId,
            shotN: shot.n,
          }),
        );
      } catch (error) {
        if (!cancelled)
          setSceneError(
            error instanceof Error ? error.message : "Could not load scene",
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conceptId, shotN, setNodes, setEdges]);
  useEffect(() => {
    if (!conceptId || !activeShot || !ready || sceneError) return;
    const payload = toLegacy(nodes, edges, graphBase.current, {
      conceptId,
      shotN: activeShot,
    });
    const fingerprint = JSON.stringify(payload);
    if (fingerprint === lastSaved.current) return;
    const timer = setTimeout(() => {
      setSaveState("Saving…");
      saveChain.current = saveChain.current
        .catch(() => {})
        .then(async () => {
          if (stopped.current) return;
          try {
            await apiFetch(`/concepts/${conceptId}/shots/${activeShot}/graph`, {
              method: "PUT",
              body: JSON.stringify({
                ...payload,
                name,
                seed_hash: seedHash.current,
              }),
            });
            lastSaved.current = fingerprint;
            setSaveState("Saved to scene");
          } catch (error) {
            setSaveState(
              `Not saved: ${error instanceof Error ? error.message : "connection lost"}`,
            );
          }
        });
    }, 650);
    return () => clearTimeout(timer);
  }, [
    conceptId,
    activeShot,
    nodes,
    edges,
    name,
    ready,
    sceneError,
    saveRevision,
  ]);
  const savePrompt = async () => {
    if (!conceptId || !activeShot) return;
    const promptNodes = getNodes().filter((n) => ["prompt", "enhance"].includes(n.data.kind));
    const chosen =
      promptNodes.find((n) => n.selected) ||
      promptNodes.find((n) => n.data.originalPrompt) ||
      promptNodes[0];
    const prompt = chosen?.data.text?.trim();
    if (!prompt) {
      notify("Select a nonempty prompt node to save to the scene.");
      return;
    }
    try {
      await saveChain.current.catch(() => {});
      await apiFetch(`/concepts/${conceptId}/shots/${activeShot}/prompt`, {
        method: "POST",
        body: JSON.stringify({ prompt }),
      });
      const fresh = await apiFetch<{ seed_hash?: string }>(
        `/concepts/${conceptId}/shots/${activeShot}/graph`,
      );
      seedHash.current = fresh.seed_hash || null;
      lastSaved.current = "";
      setSaveRevision((n) => n + 1);
      notify("Scene prompt updated");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not save prompt");
    }
  };
  const leaveScene = async (destination: string) => {
    if (conceptId && activeShot && ready && !sceneError) {
      try {
        stopped.current = true;
        await saveChain.current.catch(() => {});
        const payload = toLegacy(getNodes(), getEdges(), graphBase.current, {
          conceptId,
          shotN: activeShot,
        });
        await apiFetch(`/concepts/${conceptId}/shots/${activeShot}/graph`, {
          method: "PUT",
          body: JSON.stringify({
            ...payload,
            name,
            seed_hash: seedHash.current,
          }),
        });
      } catch (error) {
        stopped.current = false;
        notify(
          `Could not save before leaving: ${error instanceof Error ? error.message : "connection lost"}`,
        );
        return;
      }
    }
    window.location.assign(destination);
  };
  const update = useCallback(
    (id: string, data: Partial<CardData>) =>
      setNodes((ns) =>
        ns.map((n) =>
          n.id === id ? { ...n, data: { ...n.data, ...data } } : n,
        ),
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
        position: screenToFlowPosition({
          x: window.innerWidth / 2 - 120,
          y: window.innerHeight / 2 - 80,
        }),
        data: {
          kind,
          label: titles[kind],
          text: kind === "prompt" ? "" : undefined,
        },
      },
    ]);
    setAddMenu(false);
    setShowTemplates(false);
  };
  const connectionValid = (connection: Edge | Connection) => {
    if (connection.source === connection.target) return false;
    const source = getNodes().find((n) => n.id === connection.source);
    const target = getNodes().find((n) => n.id === connection.target);
    if (
      !source ||
      !target ||
      !ports(target.data.kind).includes(connection.targetHandle || "prompt")
    )
      return false;
    if (connection.targetHandle !== "reference" && !isText(source.data.kind))
      return false;
    if (
      connection.targetHandle === "reference" &&
      !["image", "reference"].includes(source.data.kind)
    )
      return false;
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
              connection.targetHandle !== "reference"
            ),
        ),
      ),
    );
  const pickTemplate = (id: Template) => {
    if (conceptId) {
      notify(
        "Scene graphs use their own prompt and references. Open a blank flow for templates.",
      );
      return;
    }
    const next = makeTemplate(id);
    setNodes(next.nodes);
    setEdges(next.edges);
    setTemplate(id);
    setTimeout(() => fitView({ padding: 0.22, duration: 400 }), 60);
  };
  const exportDraft = () => {
    const blob = new Blob(
      [JSON.stringify({ version: 1, name, nodes, edges }, null, 2)],
      { type: "application/json" },
    );
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
      if (!validDraft(data))
        throw new Error("Choose a ZeroPage workflow JSON export.");
      setNodes(
        data.nodes.map((n) => ({
          ...n,
          data: { ...n.data, busy: !!n.data.jobId },
        })),
      );
      setEdges(data.edges);
      setName(data.name);
      setShowTemplates(false);
      notify("Workflow imported");
      setTimeout(() => fitView({ padding: 0.2 }), 60);
    } catch (error) {
      notify(
        error instanceof Error ? error.message : "Could not import workflow",
      );
    }
    if (inputRef.current) inputRef.current.value = "";
  };
  const execute = async (id: string) => {
    setConfirm(null);
    const currentNodes = getNodes();
    const node = currentNodes.find((n) => n.id === id);
    if (!node || pending.current.has(id) || node.data.busy) return;
    const inputEdges = getEdges().filter((e) => e.target === id);
    const inputs = inputEdges
      .map((e) => currentNodes.find((n) => n.id === e.source))
      .filter((n): n is FlowNode => !!n);
    const inputText = (port: string) =>
      currentNodes.find(
        (n) =>
          n.id ===
          inputEdges.find((e) => (e.targetHandle || "prompt") === port)?.source,
      )?.data.text || "";
    const prompt =
      inputText("prompt").trim() ||
      (node.data.kind === "ground" ? node.data.text || "" : "");
    const images = [
      ...new Set([
        ...inputs
          .filter((n) => ["image", "reference"].includes(n.data.kind))
          .map((n) => n.data.url),
        ...(node.data.refs || []),
      ]),
    ].filter((url): url is string => !!url && /^(https?:\/\/|\/)/.test(url));
    if (!prompt && node.data.kind !== "ground") {
      update(id, {
        error: "Connect a prompt or run its upstream enhancement first.",
      });
      return;
    }
    if (node.data.kind === "video" && !images.length) {
      update(id, { error: "Connect an image before rendering video." });
      return;
    }
    pending.current.add(id);
    update(id, { busy: true, error: undefined });
    try {
      if (node.data.kind === "ground") {
        const result = await apiFetch<{ references: string }>(
          "/workflows/exec/ground",
          { method: "POST", body: JSON.stringify({ spark: prompt }) },
        );
        update(id, { text: result.references, busy: false });
        return;
      }
      const endpoint =
        node.data.kind === "enhance"
          ? "enhance"
          : node.data.kind === "video"
            ? "generate"
            : "nano";
      const body =
        node.data.kind === "enhance"
          ? {
              user: prompt,
              system: inputText("system"),
              references: inputText("references"),
              images,
              ground: !!node.data.legacy?.properties?.auto_ground,
            }
          : {
              prompt,
              images,
              ...(conceptId && activeShot
                ? { concept_id: conceptId, shot_n: activeShot }
                : {}),
            };
      const job = await apiFetch<{ job_id: number }>(
        `/workflows/exec/${endpoint}`,
        { method: "POST", body: JSON.stringify(body) },
      );
      update(id, { jobId: job.job_id });
    } catch (error) {
      update(id, {
        busy: false,
        error: error instanceof Error ? error.message : "Generation failed",
      });
    } finally {
      pending.current.delete(id);
    }
  };
  useEffect(() => {
    const jobs = nodes.filter((n) => n.data.jobId && n.data.busy);
    if (!jobs.length) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      await Promise.all(
        jobs.map(async (n) => {
          try {
            const job = await apiFetch<{
              status: string;
              output?: string;
              error?: string;
            }>(`/jobs/${n.data.jobId}`);
            if (cancelled) return;
            if (job.status === "done")
              update(n.id, {
                busy: false,
                jobId: undefined,
                ...(isText(n.data.kind)
                  ? { text: job.output }
                  : { url: job.output }),
              });
            else if (["failed", "cancelled"].includes(job.status))
              update(n.id, {
                busy: false,
                jobId: undefined,
                error: job.error || job.status,
              });
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

  return (
    <Actions.Provider
      value={{
        update,
        remove,
        duplicate,
        run: (id) => {
          const node = getNodes().find((n) => n.id === id);
          if (node?.data.jobId) update(id, { busy: true, error: undefined });
          else setConfirm(id);
        },
      }}
    >
      <main
        className={`flows-workspace ${sidebar ? "rail-expanded" : ""} ${showTemplates ? "templates-open" : ""}`}
      >
        <aside className="flows-rail">
          <button
            className="zp-symbol"
            aria-label="Toggle sidebar"
            onClick={() => setSidebar(!sidebar)}
          >
            z<span>p</span>
            <i />
          </button>
          <nav>
            <button
              aria-label="Home"
              className={view === "home" ? "active" : ""}
              onClick={() => conceptId ? leaveScene(`${API_URL}/ui?view=pipeline`) : setView("home")}
            >
              <Home size={18} />
              <span>Home</span>
            </button>
            <button
              aria-label="Flows"
              className={view === "flow" ? "active" : ""}
              onClick={() => setView("flow")}
            >
              <Workflow size={18} />
              <span>Flows</span>
            </button>
            <button onClick={() => leaveScene(`${API_URL}/ui?view=assets`)} title="Asset library">
              <Layers size={18} />
              <span>Assets</span>
            </button>
          </nav>
          <div className="rail-bottom">
            <button onClick={() => leaveScene("/studio")} title="Studio account">
              <Settings2 size={18} />
              <span>Studio account</span>
            </button>
            <button
              aria-label="Expand sidebar"
              onClick={() => setSidebar(!sidebar)}
            >
              {sidebar ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
              <span>Collapse</span>
            </button>
            <div className="avatar">Z</div>
          </div>
        </aside>
        {view === "home" ? (
          <section className="flows-home">
            <header>
              <div>
                <span className="eyebrow">ZERO PAGE / CREATIVE STUDIO</span>
                <h1>Your next idea starts here.</h1>
              </div>
              <button
                className="light-button"
                onClick={() => {
                  setView("flow");
                  setAddMenu(true);
                }}
              >
                <Plus size={16} /> Open canvas
              </button>
            </header>
            <div className="home-banners">
              <button
                className="banner banner-flow"
                onClick={() => setView("flow")}
              >
                <div className="banner-graph">
                  <i />
                  <i />
                  <i />
                  <svg viewBox="0 0 400 150">
                    <path d="M100 75 C190 75 170 25 260 25 M100 75 C190 75 170 125 260 125" />
                  </svg>
                </div>
                <span className="eyebrow">IDEAS, CONNECTED</span>
                <h2>Flows</h2>
                <p>Build your own creative process.</p>
                <ArrowUpRight />
              </button>
              <button
                className="banner banner-canvas"
                onClick={() => {
                  setView("flow");
                  setShowTemplates(true);
                }}
              >
                <span className="eyebrow">ROOM TO EXPLORE</span>
                <h2>
                  One canvas.
                  <br />
                  Every possibility.
                </h2>
                <p>From a first thought to the final frame.</p>
                <ArrowUpRight />
              </button>
            </div>
            <div className="project-bar">
              <h2>
                My projects <span>1</span>
              </h2>
              <label>
                <Search size={15} />
                <input
                  aria-label="Search projects"
                  placeholder="Search projects"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
            </div>
            {name.toLowerCase().includes(search.toLowerCase()) ? (
              <button className="project-card" onClick={() => setView("flow")}>
                <div className="project-art">
                  <Workflow size={42} strokeWidth={1} />
                  <span>FLOW</span>
                </div>
                <strong>{name}</strong>
                <small>{nodes.length} nodes · Saved on this device</small>
              </button>
            ) : (
              <p className="muted">No matching projects.</p>
            )}
            <div className="home-dock">
              <button
                onClick={() => {
                  setView("flow");
                  setShowTemplates(true);
                }}
              >
                <Sparkles size={20} />
                <span>Create</span>
                <div className="dock-preview">
                  <strong>A little inspiration.</strong>
                  <p>Start with an image, a scene, or a new direction.</p>
                </div>
              </button>
              <button onClick={() => setView("flow")}>
                <Workflow size={20} />
                <span>Flows</span>
                <div className="dock-preview">
                  <strong>Make the connection.</strong>
                  <p>Build a creative workflow, one node at a time.</p>
                </div>
              </button>
              <button onClick={() => inputRef.current?.click()}>
                <FolderOpen size={20} />
                <span>Open</span>
              </button>
            </div>
          </section>
        ) : (
          <>
            <header className="flow-topbar">
              <div className="flow-breadcrumb">
                <button
                  aria-label="Back to projects"
                  onClick={() =>
                    conceptId
                      ? leaveScene(`${API_URL}/ui?view=pipeline`)
                      : setView("home")
                  }
                >
                  <ArrowLeft size={16} />
                </button>
                <span>{conceptId ? "Director" : "Flows"}</span>
                <span className="slash">/</span>
                <input
                  readOnly={!!conceptId}
                  aria-label="Workflow name"
                  value={name}
                  maxLength={80}
                  onChange={(e) => setName(e.target.value)}
                />
                <ChevronDown size={13} />
              </div>
              <div className="flow-top-actions">
                {conceptId && (
                  <>
                    <button onClick={() => { lastSaved.current = ""; setSaveRevision(n => n + 1); }} disabled={!ready}>Save canvas</button>
                    <button onClick={savePrompt} disabled={!ready}>
                      Save scene prompt
                    </button>
                    <button
                      onClick={() => leaveScene(`${API_URL}/ui?view=queue`)}
                    >
                      Queue <ArrowUpRight size={14} />
                    </button>
                  </>
                )}
                {scene && scene.shots.length > 1 && (
                  <select
                    aria-label="Shot"
                    value={activeShot}
                    onChange={(e) =>
                      leaveScene(
                        `/studio/flows?concept=${conceptId}&shot=${e.target.value}`,
                      )
                    }
                  >
                    {scene.shots.map((s) => (
                      <option key={s.n} value={s.n}>
                        Shot {s.n}
                      </option>
                    ))}
                  </select>
                )}

                <span className="save-indicator">
                  <i />
                  {conceptId
                    ? saveState
                    : storageError
                      ? "Local save unavailable"
                      : "Local draft"}
                </span>
                <button
                  title="Import workflow"
                  aria-label="Import workflow"
                  onClick={() => inputRef.current?.click()}
                >
                  <Upload size={16} />
                </button>
                <button className="export-button" onClick={exportDraft}>
                  <Download size={14} /> Export
                </button>
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
                isValidConnection={connectionValid}
                fitView
                fitViewOptions={{ padding: 0.12, maxZoom: 0.85 }}
                minZoom={0.2}
                maxZoom={1.7}
                panOnDrag={tool === "hand" ? true : [1, 2]}
                selectionOnDrag={tool === "select"}
                nodesDraggable={tool === "select"}
                deleteKeyCode={["Backspace", "Delete"]}
                onMove={(_, viewport) => setZoom(viewport.zoom)}
                defaultEdgeOptions={{
                  type: "default",
                  style: { stroke: "#4a5050", strokeWidth: 1.3 },
                }}
              >
                <Background color="#202323" gap={28} size={0.65} />
                <MiniMap
                  pannable
                  zoomable
                  nodeColor="#343a38"
                  maskColor="rgba(5,7,6,.65)"
                />
              </ReactFlow>
            </section>
            <div className="canvas-zoom">
              <button
                aria-label="Zoom out"
                onClick={() => zoomOut({ duration: 180 })}
              >
                <ZoomOut size={17} />
              </button>
              <button
                aria-label="Zoom in"
                onClick={() => zoomIn({ duration: 180 })}
              >
                <ZoomIn size={17} />
              </button>
              <button
                aria-label="Fit canvas"
                onClick={() => fitView({ padding: 0.22, duration: 350 })}
              >
                <Maximize size={16} />
              </button>
              <span>{Math.round(zoom * 100)}%</span>
            </div>
            {showTemplates && (
              <aside className="flow-templates">
                <div className="template-title">
                  <span className="eyebrow">A PLACE TO BEGIN</span>
                  <button
                    aria-label="Close templates"
                    onClick={() => setShowTemplates(false)}
                  >
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
                    <button
                      key={t.id}
                      className={template === t.id ? "selected" : ""}
                      onClick={() => pickTemplate(t.id)}
                    >
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
              <span className="canvas-caption">
                {nodes.length} NODES <i />
                {edges.length} CONNECTIONS
              </span>
              <div className="flow-toolbar">
                <div className="add-node-wrap">
                  <button
                    aria-label="Add node"
                    className={addMenu ? "tool-active" : ""}
                    onClick={() => setAddMenu(!addMenu)}
                  >
                    <Plus size={21} />
                  </button>
                  {addMenu && (
                    <div className="add-node-menu">
                      <span className="eyebrow">ADD TO YOUR FLOW</span>
                      {(
                        ["prompt", "system", "ground", "enhance", "reference", "image", "video"] as Kind[]
                      ).map((kind) => (
                        <button key={kind} onClick={() => addNode(kind)}>
                          {kind === "prompt" ? (
                            <Type size={17} />
                          ) : kind === "reference" ? (
                            <ImagePlus size={17} />
                          ) : kind === "video" ? (
                            <Film size={17} />
                          ) : (
                            <Sparkles size={17} />
                          )}
                          <span>
                            {titles[kind]}
                            <small>
                              {kind === "prompt"
                                ? "Write your scene"
                                : kind === "reference"
                                  ? "Ground your idea"
                                  : kind === "image"
                                    ? "Generate a still"
                                    : "Generate motion"}
                            </small>
                          </span>
                          <Plus size={13} />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <i className="tool-divider" />
                <button
                  aria-label="Select tool"
                  aria-pressed={tool === "select"}
                  className={tool === "select" ? "tool-active" : ""}
                  onClick={() => setTool("select")}
                >
                  <MousePointer2 size={20} />
                </button>
                <button
                  aria-label="Pan tool"
                  aria-pressed={tool === "hand"}
                  className={tool === "hand" ? "tool-active" : ""}
                  onClick={() => setTool("hand")}
                >
                  <Hand size={20} />
                </button>
                <i className="tool-divider" />
                <button
                  aria-label="Show templates"
                  aria-pressed={showTemplates}
                  onClick={() => setShowTemplates(!showTemplates)}
                >
                  <Grid2X2 size={19} />
                </button>
                <button
                  aria-label="Duplicate selected nodes"
                  onClick={() => {
                    const selected = nodes.filter((n) => n.selected);
                    if (!selected.length) notify("Select a node to duplicate");
                    selected.forEach((n) => duplicate(n.id));
                  }}
                >
                  <Copy size={18} />
                </button>
                <button
                  aria-label="Delete selected nodes"
                  onClick={() => {
                    const selected = nodes.filter((n) => n.selected);
                    if (!selected.length) notify("Select a node to delete");
                    selected.forEach((n) => remove(n.id));
                  }}
                >
                  <Trash2 size={18} />
                </button>
              </div>
              <span className="canvas-hint">
                Scroll to zoom · Drag to select
              </span>
            </div>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(e) => importDraft(e.target.files?.[0])}
        />
        {conceptId && (!ready || sceneError) && (
          <div className="flow-modal-backdrop">
            <section className="flow-modal" role="status">
              <h2>
                {sceneError ? "Could not open scene" : "Opening Director…"}
              </h2>
              <p>
                {sceneError ||
                  "Loading the saved prompt, references and canvas."}
              </p>
              {sceneError && (
                <div>
                  <a
                    href={`${API_URL}/signin`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Sign in
                  </a>
                  <button onClick={() => window.location.reload()}>
                    Retry
                  </button>
                  <a
                    href={`${API_URL}/ui?view=director&concept=${conceptId}&legacy=1`}
                  >
                    Legacy Director
                  </a>
                </div>
              )}
            </section>
          </div>
        )}
        {toast && (
          <div className="flow-toast" role="status">
            <Check size={16} />
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
                if (e.key !== "Tab") return;
                const buttons = Array.from(
                  e.currentTarget.querySelectorAll<HTMLButtonElement>("button"),
                );
                const first = buttons[0],
                  last = buttons[buttons.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last?.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first?.focus();
                }
              }}
            >
              <button
                className="modal-close"
                aria-label="Close"
                onClick={() => setConfirm(null)}
              >
                <X size={18} />
              </button>
              <div className="modal-icon">
                <Zap size={23} />
              </div>
              <h2 id="render-title">Bring this frame to life.</h2>
              <p>
                Generate with {nodes.find((n) => n.id === confirm)?.data.label}.
                This uses your connected provider and may spend render credits.
                Your account’s daily limits apply.
              </p>
              <small>
                Sign in through Studio first. Provider settings use your
                existing backend defaults.
              </small>
              <div>
                <button onClick={() => setConfirm(null)}>Keep editing</button>
                <button
                  className="light-button"
                  onClick={() => execute(confirm)}
                >
                  <Play size={14} /> Generate
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
      ![
        "prompt",
        "reference",
        "image",
        "video",
        "system",
        "enhance",
        "ground",
      ].includes(node.data.kind) ||
      typeof node.data.label !== "string"
    )
      return false;
    if (node.data.text !== undefined && typeof node.data.text !== "string")
      return false;
    if (
      node.data.url !== undefined &&
      (typeof node.data.url !== "string" ||
        (node.data.url !== "" && !/^(https?:\/\/|\/)/.test(node.data.url)))
    )
      return false;
    ids.add(node.id);
  }
  return d.edges.every(
    (e) =>
      e && typeof e.id === "string" && ids.has(e.source) && ids.has(e.target),
  );
}
export default function FlowWorkspace(props: {
  conceptId?: number;
  shotN?: number;
}) {
  return (
    <ReactFlowProvider>
      <Workspace {...props} />
    </ReactFlowProvider>
  );
}

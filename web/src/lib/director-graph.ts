/* The Director's graph adapter: React Flow cards on the client, the
   runner's LiteGraph JSON on the wire (app/workflow_runner.py). One
   file owns both directions so a card added here cannot be saved in a
   shape the runner does not execute.

   2026-09-11: element cards. A scene's references used to seed one
   card PER PHOTO; now they group into one card per asset — a
   character's frames, a room's plates, the composer's uploads — as a
   `zpf/reference_set` node whose value is its url list, wired into the
   billed nodes' `refs` port, the one port that takes several wires
   (workflow_runner.MULTI_LINK_PORTS). The seeded chain is the full
   one: prompt → instructions → enhance → keyframe → clip. */
import type { Node, Edge } from "@xyflow/react";

export type Kind =
  | "prompt"
  | "system"
  | "enhance"
  | "ground"
  | "image"
  | "video"
  | "reference"
  | "element";
export type RefKind = "character" | "location" | "prop" | "upload" | "web";
export type LegacyNode = {
  id: number;
  type: string;
  title?: string;
  pos?: number[];
  properties?: Record<string, unknown>;
  inputs?: { name: string; type?: string; link?: number | null; links?: number[] }[];
  [key: string]: unknown;
};
export type CardData = {
  kind: Kind;
  label: string;
  text?: string;
  url?: string;
  urls?: string[];
  refKind?: RefKind;
  busy?: boolean;
  error?: string;
  jobId?: number;
  legacy?: LegacyNode;
  refs?: string[];
  originalPrompt?: boolean;
  camera?: string;
};
export type FlowNode = Node<CardData, "studio">;
export type NodeState = {
  status: string;
  kind?: string | null;
  output?: string | string[] | null;
  error?: string | null;
};
export type LegacyGraph = {
  nodes: LegacyNode[];
  links?: (number | string)[][];
  [key: string]: unknown;
};
export type Shot = {
  n: number;
  prompt?: string;
  written_prompt?: string;
  desc?: string;
  refs?: string[];
  reference_image?: string;
  media_url?: string;
};
export const types: Record<Kind, string> = {
  prompt: "zpf/user_prompt",
  system: "zpf/system_prompt",
  enhance: "zpf/enhance",
  ground: "zpf/ground",
  image: "zpf/nano_banana",
  video: "zpf/generate",
  reference: "zpf/reference_image",
  element: "zpf/reference_set",
};
export const isText = (kind: Kind) => ["prompt", "system", "enhance", "ground"].includes(kind);
export const isMedia = (kind: Kind) => ["image", "video"].includes(kind);
export const isSource = (kind: Kind) => ["reference", "element"].includes(kind);
export const MULTI = new Set(["refs"]);

/** the input handles a card offers, in port order */
export const ports = (kind: Kind): string[] =>
  kind === "enhance"
    ? ["system", "prompt", "reference", "references", "refs"]
    : kind === "ground"
      ? ["prompt"]
      : isMedia(kind)
        ? ["prompt", "reference", "refs"]
        : [];
const legacyPort = (kind: Kind, port: string) =>
  port === "reference"
    ? "image"
    : port === "prompt" && kind === "enhance"
      ? "user"
      : port === "prompt" && kind === "ground"
        ? "spark"
        : port;
const portType = (port: string) =>
  port === "reference" ? "image" : port === "refs" ? "images" : "text";
const outputOf = (kind: Kind) =>
  kind === "element"
    ? { name: "images", type: "images" }
    : kind === "video"
      ? { name: "media", type: "media" }
      : isText(kind)
        ? { name: "text", type: "text" }
        : { name: "image", type: "image" };
/** may a wire from `from` land on `port` of `to`? */
export const compatible = (from: Kind, port: string) =>
  port === "reference"
    ? ["image", "reference"].includes(from)
    : port === "refs"
      ? ["element", "reference", "image"].includes(from)
      : isText(from);

/* ── grouping a shot's references into element cards ── */
export type RefGroup = { key: string; refKind: RefKind; label: string; urls: string[] };
const titleCase = (slug: string) =>
  slug.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export function groupRefs(refs: string[], names: Record<string, string> = {}): RefGroup[] {
  const groups = new Map<string, RefGroup>();
  for (const url of refs) {
    if (typeof url !== "string" || !url) continue;
    const m = url.match(/^\/(characters|locations|props)\/([^/]+)\//);
    let key: string, refKind: RefKind, label: string;
    if (m) {
      refKind = m[1].slice(0, -1) as RefKind;
      key = `${refKind}:${m[2]}`;
      label = names[key] || names[m[2]] || titleCase(m[2]);
    } else if (url.startsWith("/refs/")) {
      refKind = "upload";
      key = "upload";
      label = "Composer uploads";
    } else {
      refKind = "web";
      key = "web";
      label = "Scouted frames";
    }
    if (!groups.has(key)) groups.set(key, { key, refKind, label, urls: [] });
    groups.get(key)!.urls.push(url);
  }
  return [...groups.values()];
}
export const elementLabel = (refKind: RefKind | undefined, label: string) =>
  `${refKind === "location" ? "Location" : refKind === "prop" ? "Prop" : refKind === "upload" ? "Upload" : refKind === "web" ? "Reference" : "Element"} · ${label}`;
const estHeight = (g: RefGroup) => {
  const cols = g.refKind === "location" ? 2 : 3;
  const cell = (360 - 24 - (cols - 1) * 6) / cols;
  const rows = Math.ceil(g.urls.length / cols);
  return 44 + 24 + rows * (g.refKind === "location" ? cell * 0.75 : cell) + (rows - 1) * 6 + 44;
};

export function seedScene(
  shot: Shot,
  opts: { enhanceSystem?: string; names?: Record<string, string> } = {},
): { nodes: FlowNode[]; edges: Edge[] } {
  // the prompt node seeds from what the GENERATOR wrote (written_prompt)
  // when the chain has touched the scene, so Run never enhances an
  // already-enhanced prompt; else the stored prompt
  const text = shot.written_prompt || shot.prompt || shot.desc || "";
  const groups = groupRefs(shot.refs || [], opts.names);
  const colX = groups.length ? 830 : 400;
  const nodes: FlowNode[] = [
    {
      id: "scene-prompt",
      type: "studio",
      position: { x: 0, y: 0 },
      data: { kind: "prompt", label: `Shot ${shot.n} · prompt`, text, originalPrompt: true },
    },
    {
      id: "scene-system",
      type: "studio",
      position: { x: 0, y: 352 },
      data: { kind: "system", label: "Instructions", text: opts.enhanceSystem || "" },
    },
    {
      id: "scene-enhance",
      type: "studio",
      position: { x: colX, y: 0 },
      data: { kind: "enhance", label: "Gemini 2.5 Flash", refs: shot.refs || [] },
    },
    {
      id: "scene-image",
      type: "studio",
      position: { x: colX, y: 330 },
      data: { kind: "image", label: "Nano Banana", url: shot.reference_image || undefined, refs: shot.refs || [] },
    },
    {
      id: "scene-video",
      type: "studio",
      position: { x: colX + 430, y: 40 },
      data: { kind: "video", label: "Runway Gen-4 Turbo", url: shot.media_url || undefined, refs: shot.refs || [] },
    },
  ];
  let y = 0;
  groups.forEach((g) => {
    nodes.push({
      id: `scene-el-${g.key.replace(/[^a-z0-9]+/gi, "-")}`,
      type: "studio",
      position: { x: 400, y },
      data: { kind: "element", label: elementLabel(g.refKind, g.label), refKind: g.refKind, urls: g.urls },
    });
    y += estHeight(g) + 24;
  });
  const edges: Edge[] = [
    { id: "prompt-enhance", source: "scene-prompt", target: "scene-enhance", targetHandle: "prompt" },
    { id: "system-enhance", source: "scene-system", target: "scene-enhance", targetHandle: "system" },
    { id: "enhance-image", source: "scene-enhance", target: "scene-image", targetHandle: "prompt" },
    { id: "enhance-video", source: "scene-enhance", target: "scene-video", targetHandle: "prompt" },
    { id: "image-video", source: "scene-image", target: "scene-video", targetHandle: "reference" },
  ];
  for (const n of nodes) {
    if (n.data.kind !== "element") continue;
    for (const target of ["scene-enhance", "scene-image", "scene-video"]) {
      edges.push({ id: `${n.id}-${target}`, source: n.id, target, targetHandle: "refs" });
    }
  }
  return { nodes, edges };
}

/** the edges an element card gets when it lands on a canvas: into
 *  every card that has a refs port */
export function wireElement(node: FlowNode, nodes: FlowNode[]): Edge[] {
  return nodes
    .filter((n) => n.id !== node.id && ports(n.data.kind).includes("refs"))
    .map((n) => ({ id: `${node.id}-${n.id}`, source: node.id, target: n.id, targetHandle: "refs" }));
}

export function fromLegacy(
  graph: LegacyGraph,
  states: Record<string, NodeState> = {},
): { nodes: FlowNode[]; edges: Edge[] } {
  const nodes = graph.nodes.map((legacy): FlowNode => {
    const kind = (Object.keys(types) as Kind[]).find((k) => types[k] === legacy.type);
    if (!kind)
      throw new Error(`This graph contains ${legacy.type}. Open the legacy Director to preserve that node.`);
    const props = legacy.properties || {};
    const state = states[String(legacy.id)];
    const result = typeof state?.output === "string" ? state.output : undefined;
    const urls = Array.isArray(props.urls) ? (props.urls as string[]) : [];
    return {
      id: String(legacy.id),
      type: "studio",
      position: { x: legacy.pos?.[0] || 0, y: legacy.pos?.[1] || 0 },
      data: {
        kind,
        label: legacy.title || kind,
        legacy,
        text: ["prompt", "system"].includes(kind)
          ? String(props.text || "")
          : isText(kind)
            ? result
            : undefined,
        url: kind === "reference" ? String(props.url || "") : isMedia(kind) ? result : undefined,
        urls: kind === "element" ? urls : undefined,
        refKind: kind === "element" ? ((props.kind as RefKind) || "upload") : undefined,
        refs: [
          ...new Set([
            ...(Array.isArray(props.ref_urls) ? (props.ref_urls as string[]) : []),
            ...(typeof props.image_url === "string" && props.image_url ? [props.image_url] : []),
          ]),
        ],
        camera: typeof props.camera === "string" ? props.camera : undefined,
        error: state?.error || undefined,
        originalPrompt: kind === "prompt" && !!props.concept_id,
      },
    };
  });
  const edges: Edge[] = (graph.links || []).map((link) => {
    const target = graph.nodes.find((n) => n.id === link[3]);
    const input = target?.inputs?.[Number(link[4])]?.name || "prompt";
    return {
      id: String(link[0]),
      source: String(link[1]),
      sourceHandle: "output",
      target: String(link[3]),
      targetHandle: input === "image" ? "reference" : ["user", "spark"].includes(input) ? "prompt" : input,
    };
  });
  const saved = graph.react_flow as
    | { nodes?: FlowNode[]; edges?: Edge[]; legacySignature?: string }
    | undefined;
  if (saved?.nodes && saved?.edges && saved.legacySignature === JSON.stringify([graph.nodes, graph.links])) {
    for (const node of nodes) {
      const prior = saved.nodes.find((n) => n.id === node.id);
      if (prior) node.data = { ...prior.data, ...node.data, jobId: prior.data.jobId, busy: !!prior.data.jobId };
    }
    return { nodes, edges: saved.edges };
  }
  return { nodes, edges };
}

export function toLegacy(
  nodes: FlowNode[],
  edges: Edge[],
  base: Partial<LegacyGraph> = {},
  context?: { conceptId: number; shotN: number },
) {
  const ids = new Map(nodes.map((n, i) => [n.id, i + 1]));
  const links: (number | string)[][] = [];
  const states: Record<string, NodeState> = {};
  const anyElement = nodes.some((n) => n.data.kind === "element");
  const converted = nodes.map((node, index) => {
    const { data } = node;
    const properties: Record<string, unknown> = {
      ...data.legacy?.properties,
      ...(context ? { concept_id: context.conceptId, shot_n: context.shotN } : {}),
    };
    if (["prompt", "system"].includes(data.kind)) properties.text = data.text || "";
    if (data.kind === "reference") properties.url = data.url || "";
    if (data.kind === "element") {
      properties.urls = [...(data.urls || [])];
      properties.kind = data.refKind || "upload";
      properties.label = data.label.replace(/^[^·]+·\s*/, "");
    }
    if (data.camera) properties.camera = data.camera;
    const inputEdges = edges.filter((e) => e.target === node.id);
    // what is wired in IS the reference list: the single image port,
    // then every element card on the refs port. The frozen refs on the
    // card only stand in when no element has been drawn at all (a
    // graph from before element cards existed).
    const wiredRefs: string[] = [];
    for (const e of inputEdges) {
      const src = nodes.find((n) => n.id === e.source);
      if (!src) continue;
      if (e.targetHandle === "reference" && src.data.url) wiredRefs.push(src.data.url);
      if (e.targetHandle === "refs") {
        if (src.data.kind === "element") wiredRefs.push(...(src.data.urls || []));
        else if (src.data.url) wiredRefs.push(src.data.url);
      }
    }
    if (ports(data.kind).includes("refs")) {
      properties.ref_urls = [...new Set([...wiredRefs, ...(anyElement ? [] : data.refs || [])])];
    }
    const inputs = ports(data.kind).map((port) => ({
      name: legacyPort(data.kind, port),
      type: portType(port),
      link: null as number | null,
      ...(MULTI.has(port) ? { links: [] as number[] } : {}),
    }));
    for (const edge of inputEdges) {
      const port = edge.targetHandle || "prompt";
      const portIndex = ports(data.kind).indexOf(port);
      if (portIndex < 0 || !ids.has(edge.source)) continue;
      const slot = inputs[portIndex] as { link: number | null; links?: number[]; type: string };
      if (!MULTI.has(port) && slot.link !== null) continue; // one wire per single port
      const id = links.length + 1;
      if (slot.link === null) slot.link = id;
      if (slot.links) slot.links.push(id);
      links.push([id, ids.get(edge.source)!, 0, index + 1, portIndex, slot.type]);
    }
    const output = isText(data.kind) ? data.text : isMedia(data.kind) ? data.url : undefined;
    if ((output || data.error) && !["prompt", "system"].includes(data.kind))
      states[String(index + 1)] = {
        status: data.error ? "failed" : "done",
        kind: isText(data.kind) ? "text" : data.kind === "video" ? "media" : "image",
        output: output || null,
        error: data.error || null,
      };
    const out = outputOf(data.kind);
    return {
      ...data.legacy,
      id: index + 1,
      type: types[data.kind],
      title: data.label,
      pos: [node.position.x, node.position.y],
      size: data.legacy?.size || [360, 320],
      flags: {},
      order: index,
      mode: 0,
      properties,
      inputs,
      outputs: [{ name: out.name, type: out.type, links: [] as number[] }],
    };
  });
  for (const node of converted)
    node.outputs[0].links = links.filter((l) => l[1] === node.id).map((l) => Number(l[0]));
  return {
    graph: {
      ...base,
      nodes: converted,
      links,
      last_node_id: nodes.length,
      last_link_id: links.length,
      version: 0.4,
      react_flow: {
        version: 2,
        legacySignature: JSON.stringify([converted, links]),
        nodes: nodes.map((n) => ({ ...n, id: String(ids.get(n.id)), data: { ...n.data, legacy: undefined } })),
        edges: edges.map((e) => ({ ...e, source: String(ids.get(e.source)), target: String(ids.get(e.target)) })),
      },
    },
    states,
    ids,
  };
}

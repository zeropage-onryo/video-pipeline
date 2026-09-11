import type { Node, Edge } from "@xyflow/react";

export type Kind =
  "prompt" | "system" | "enhance" | "ground" | "image" | "video" | "reference";
export type LegacyNode = {
  id: number;
  type: string;
  title?: string;
  pos?: number[];
  properties?: Record<string, unknown>;
  inputs?: { name: string; type?: string; link?: number | null }[];
  [key: string]: unknown;
};
export type CardData = {
  kind: Kind;
  label: string;
  text?: string;
  url?: string;
  busy?: boolean;
  error?: string;
  jobId?: number;
  legacy?: LegacyNode;
  refs?: string[];
  originalPrompt?: boolean;
};
export type FlowNode = Node<CardData, "studio">;
export type NodeState = {
  status: string;
  kind?: string | null;
  output?: string | null;
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
};
export const isText = (kind: Kind) =>
  ["prompt", "system", "enhance", "ground"].includes(kind);
export const ports = (kind: Kind) =>
  kind === "enhance"
    ? ["system", "prompt", "reference", "references"]
    : kind === "ground"
      ? ["prompt"]
      : ["image", "video"].includes(kind)
        ? ["prompt", "reference"]
        : [];
const legacyPort = (kind: Kind, port: string) =>
  port === "reference"
    ? "image"
    : port === "prompt" && kind === "enhance"
      ? "user"
      : port === "prompt" && kind === "ground"
        ? "spark"
        : port;
export function seedScene(shot: Shot): { nodes: FlowNode[]; edges: Edge[] } {
  const nodes: FlowNode[] = [
    {
      id: "scene-prompt",
      type: "studio",
      position: { x: 60, y: 180 },
      data: {
        kind: "prompt",
        label: `Shot ${shot.n} · prompt`,
        text: shot.prompt || shot.written_prompt || shot.desc || "",
        originalPrompt: true,
      },
    },
    {
      id: "scene-image",
      type: "studio",
      position: { x: 530, y: 120 },
      data: {
        kind: "image",
        label: "Nano Banana",
        url: shot.reference_image || undefined,
        refs: shot.refs || [],
      },
    },
    {
      id: "scene-video",
      type: "studio",
      position: { x: 990, y: 120 },
      data: {
        kind: "video",
        label: "Runway",
        url: shot.media_url || undefined,
        refs: shot.refs || [],
      },
    },
    ...(shot.refs || []).map((url, i): FlowNode => ({
      id: `scene-ref-${i}`,
      type: "studio",
      position: { x: 60, y: 520 + i * 320 },
      data: { kind: "reference", label: `Reference ${i + 1}`, url },
    })),
  ];
  const edges: Edge[] = [
    {
      id: "prompt-image",
      source: "scene-prompt",
      target: "scene-image",
      targetHandle: "prompt",
    },
    {
      id: "prompt-video",
      source: "scene-prompt",
      target: "scene-video",
      targetHandle: "prompt",
    },
    {
      id: "image-video",
      source: "scene-image",
      target: "scene-video",
      targetHandle: "reference",
    },
  ];
  nodes
    .filter((n) => n.data.kind === "reference")
    .forEach((n) =>
      edges.push({
        id: `${n.id}-image`,
        source: n.id,
        target: "scene-image",
        targetHandle: "reference",
      }),
    );
  return { nodes, edges };
}
export function fromLegacy(
  graph: LegacyGraph,
  states: Record<string, NodeState> = {},
): { nodes: FlowNode[]; edges: Edge[] } {
  const nodes = graph.nodes.map((legacy): FlowNode => {
    const kind = (Object.keys(types) as Kind[]).find(
      (k) => types[k] === legacy.type,
    );
    if (!kind)
      throw new Error(
        `This graph contains ${legacy.type}. Open the legacy Director to preserve that node.`,
      );
    const props = legacy.properties || {};
    const state = states[String(legacy.id)];
    const result = state?.output || undefined;
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
        url:
          kind === "reference"
            ? String(props.url || "")
            : !isText(kind)
              ? result
              : undefined,
        refs: [...new Set([...(Array.isArray(props.ref_urls) ? (props.ref_urls as string[]) : []), ...(typeof props.image_url === "string" && props.image_url ? [props.image_url] : [])])],
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
      targetHandle:
        input === "image"
          ? "reference"
          : ["user", "spark"].includes(input)
            ? "prompt"
            : input,
    };
  });
  const saved = graph.react_flow as
    { nodes?: FlowNode[]; edges?: Edge[]; legacySignature?: string } | undefined;
  if (saved?.nodes && saved?.edges && saved.legacySignature === JSON.stringify([graph.nodes, graph.links])) {
    for (const node of nodes) {
      const prior = saved.nodes.find((n) => n.id === node.id);
      if (prior)
        node.data = {
          ...prior.data,
          ...node.data,
          jobId: prior.data.jobId,
          busy: !!prior.data.jobId,
        };
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
  const converted = nodes.map((node, index) => {
    const { data } = node;
    const properties: Record<string, unknown> = {
      ...data.legacy?.properties,
      ...(context
        ? { concept_id: context.conceptId, shot_n: context.shotN }
        : {}),
    };
    if (["prompt", "system"].includes(data.kind))
      properties.text = data.text || "";
    if (data.kind === "reference") properties.url = data.url || "";
    const inputEdges = edges.filter((e) => e.target === node.id);
    const refNodes = inputEdges
      .filter((e) => e.targetHandle === "reference")
      .map((e) => nodes.find((n) => n.id === e.source));
    properties.ref_urls = [
      ...new Set([
        ...refNodes.map((n) => n?.data.url).filter(Boolean),
        ...(data.refs || []),
      ]),
    ];
    const inputs = ports(data.kind).map((port) => ({
      name: legacyPort(data.kind, port),
      type: port === "reference" ? "image" : "text",
      link: null as number | null,
    }));
    for (const edge of inputEdges) {
      const portIndex = ports(data.kind).indexOf(edge.targetHandle || "prompt");
      if (portIndex < 0 || !ids.has(edge.source)) continue;
      // LiteGraph has one wired image input; other reference URLs ride in ref_urls.
      if (inputs[portIndex].link !== null) continue;
      const id = links.length + 1;
      inputs[portIndex].link = id;
      links.push([
        id,
        ids.get(edge.source)!,
        0,
        index + 1,
        portIndex,
        inputs[portIndex].type,
      ]);
    }
    const output = isText(data.kind) ? data.text : data.url;
    if (output || data.error)
      states[String(index + 1)] = {
        status: data.error ? "failed" : "done",
        kind: isText(data.kind) ? "text" : data.kind === "video" ? "media" : "image",
        output: output || null,
        error: data.error || null,
      };
    return {
      ...data.legacy,
      id: index + 1,
      type: types[data.kind],
      title: data.label,
      pos: [node.position.x, node.position.y],
      size: data.legacy?.size || [336, 320],
      flags: {},
      order: index,
      mode: 0,
      properties,
      inputs,
      outputs: [
        {
          name: isText(data.kind) ? "text" : "image",
          type: isText(data.kind) ? "text" : "image",
          links: [] as number[],
        },
      ],
    };
  });
  for (const node of converted)
    node.outputs[0].links = links
      .filter((l) => l[1] === node.id)
      .map((l) => Number(l[0]));
  return {
    graph: {
      ...base,
      nodes: converted,
      links,
      last_node_id: nodes.length,
      last_link_id: links.length,
      version: 0.4,
      react_flow: {
        version: 1,
        legacySignature: JSON.stringify([converted, links]),
        nodes: nodes.map((n) => ({
          ...n,
          id: String(ids.get(n.id)),
          data: { ...n.data, legacy: undefined },
        })),
        edges: edges.map((e) => ({
          ...e,
          source: String(ids.get(e.source)),
          target: String(ids.get(e.target)),
        })),
      },
    },
    states,
  };
}

/* Gen Space — the Director view's node canvas (2026-09-10, from the
   "ZPF Gen Space" design; the shape LTX Studio's gen space has).

   What it is: ONE shot's chain drawn as cards on an infinite canvas —
   the prompt and its instructions, the reference sets the scene was
   written against (a character's frames, a room's plates, the
   composer's uploads), the Gemini enhance, the Nano keyframe, the
   video model (fal) and its output — wired with real links, and a floating
   prompt bar underneath that edits the shot's prompt and drops an
   element onto the canvas (already wired in) when you @-mention it.

   What it replaced: LiteGraph drawing the same chain onto a bitmap
   <canvas>. A bitmap could show a face being NAMED in a prompt but
   never a face; here a card holds the photos, the keyframe and the
   clip themselves. The graph model is our own (this file's `G`) but
   the JSON it saves and runs is still LiteGraph's serialize() shape,
   so the runner (app/workflow_runner.py), the saved shot graphs and
   the seeded "Prompt enhancement" template are untouched by the
   swap. One addition on both sides: a `refs` port that takes several
   wires, because the character AND the room feed one billed node.

   Every billed node stays behind its module's own gate (the fal spend
   gate and credit hold, NANO_DAILY_CAP) — this canvas cannot spend around them, and Send to
   Queue only PICKS the concept: approving in Queue is what renders. */
import { api, bus, enhanceSystemText, esc, loadAssets, loadPresets,
         refreshQueueBadge, state, stateline, wireMentions } from './shared.js';

const $ = id => document.getElementById(id);

/* ── icons (lucide outlines, inline so nothing loads off a CDN) ── */
const ICON = {
  image: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="m21 15-4.5-4.5L6 21"/>',
  type: '<path d="M4 7V4h16v3M9 20h6M12 4v16"/>',
  text: '<path d="M17 6.1H3M21 12.1H3M15.1 18H3"/>',
  user: '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
  box: '<path d="m12 3 9 4.5v9L12 21l-9-4.5v-9z"/><path d="m3 7.5 9 4.5 9-4.5M12 12v9"/>',
  sparkles: '<path d="m12 3 1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  clap: '<path d="M4 11h16v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="m4 11-1.5-4 15.5-4 1.5 4z"/><path d="m8 9.5 3-6M13 8.3l3-6"/>',
  layers: '<path d="m12 3 9 4.5-9 4.5-9-4.5z"/><path d="m3 12 9 4.5 9-4.5"/><path d="m3 16.5 9 4.5 9-4.5"/>',
  play: '<path d="M7 4l12 8-12 8z"/>',
  replace: '<path d="M14 4a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-5a1 1 0 0 1-1-1z"/><path d="M3 15a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M14 17h3a3 3 0 0 0 3-3v-1M10 7H7a3 3 0 0 0-3 3v1"/>',
  repeat: '<path d="m2 9 3-3 3 3"/><path d="M13 18H7a2 2 0 0 1-2-2V6"/><path d="m22 15-3 3-3-3"/><path d="M11 6h6a2 2 0 0 1 2 2v10"/>',
  download: '<path d="M12 3v12M6 11l6 6 6-6"/><path d="M4 21h16"/>',
  at: '<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  ratio: '<rect x="7" y="3" width="10" height="18" rx="2"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3"/>',
  loader: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
};
const icon = (name, cls = '') =>
  `<svg class="gsi ${cls}" viewBox="0 0 24 24">${ICON[name] || ''}</svg>`;

/* ── the catalogue: what a node type is, draws as, and plugs into ──
   inputs/outputs are [name, type]. `refs` is the one multi-wire port
   (workflow_runner.MULTI_LINK_PORTS): several reference sets feed one
   billed node. Sizes are widths; heights come from the rendered card. */
const CATALOG = {
  'zpf/user_prompt': { title: 'Prompt', icon: 'type', cat: 'Text', w: 360,
    note: 'What happens in the shot. Written by the generator, editable here or in the bar below — @ brings an element onto the canvas.',
    inputs: [], outputs: [['text', 'text']], props: () => ({ text: '' }) },
  'zpf/system_prompt': { title: 'Instructions', icon: 'text', cat: 'Text', w: 360,
    note: 'How the enhance should treat the prompt: tighten, never summarise; keep the locks, the avoid-list and the beat order.',
    inputs: [], outputs: [['text', 'text']], props: () => ({ text: '' }) },
  'zpf/ground': { title: 'Ground in References', icon: 'layers', cat: 'Text', w: 360,
    note: 'Reference-library grounding for a spark (pgvector). Its output feeds the enhance as references.',
    inputs: [['spark', 'text']], outputs: [['references', 'text']], props: () => ({ text: '' }) },
  'zpf/enhance': { title: 'Gemini 2.5 Flash', icon: 'sparkles', cat: 'Text', w: 380,
    note: 'Takes the prompt, the instructions and every reference wired in, and returns one tightened director’s prompt. Grounds on the RAG library on the backend.',
    inputs: [['system', 'text'], ['user', 'text'], ['image', 'image'], ['references', 'text'], ['refs', 'images']],
    outputs: [['text', 'text']], props: () => ({ auto_ground: true }) },
  'zpf/reference_image': { title: 'Reference Image', icon: 'image', cat: 'Image', w: 360,
    note: 'One plate this shot starts from. Swapping it re-runs everything downstream.',
    inputs: [], outputs: [['image', 'image']], props: () => ({ url: '' }) },
  'zpf/reference_set': { title: 'Element', icon: 'user', cat: 'Image', w: 360,
    note: 'Reference frames from the asset library. Keeps the face, the wardrobe or the room consistent across shots.',
    inputs: [], outputs: [['images', 'images']], props: () => ({ urls: [], kind: 'upload', label: '' }) },
  'zpf/nano_banana': { title: 'Nano Banana', icon: 'image', cat: 'Image', w: 380,
    note: 'Renders the keyframe the clip starts from — the enhanced prompt as a still, grounded on every reference wired in.',
    inputs: [['prompt', 'text'], ['image', 'image'], ['refs', 'images']],
    outputs: [['image', 'image']], props: () => ({}) },
  'zpf/generate': { title: 'Video clip', icon: 'sparkles', cat: 'Video', w: 380,
    note: 'Takes every wire coming in and renders one clip, anchored on the keyframe. The only step that spends money — approving in Queue is what calls it unattended.',
    inputs: [['prompt', 'text'], ['image', 'image'], ['refs', 'images']],
    outputs: [['media', 'media']], props: () => ({}) },
};
const MULTI = new Set(['refs']);
const BILLED = new Set(['zpf/enhance', 'zpf/nano_banana', 'zpf/generate', 'zpf/ground']);
const PURE = new Set(['zpf/system_prompt', 'zpf/user_prompt', 'zpf/reference_image', 'zpf/reference_set']);
const SET_ICON = { character: 'user', location: 'pin', prop: 'box', upload: 'image', web: 'image' };
const SET_LABEL = { character: 'Element', location: 'Location', prop: 'Prop', upload: 'Upload', web: 'Reference' };

/* ── the graph model (LiteGraph's serialize() shape in, same shape out) ── */
let G = newGraph();

function newGraph() {
  return { nodes: new Map(), links: new Map(), lastNodeId: 0, lastLinkId: 0 };
}

function makeNode(type, opts = {}) {
  const c = CATALOG[type] || { title: type, icon: 'box', w: 320, inputs: [], outputs: [], props: () => ({}) };
  const node = {
    id: opts.id || ++G.lastNodeId,
    type,
    title: opts.title || c.title,
    pos: opts.pos ? [...opts.pos] : [0, 0],
    size: [c.w, 200],
    properties: Object.assign(c.props ? c.props() : {}, opts.properties || {}),
    inputs: (opts.inputs || c.inputs).map(slot => Array.isArray(slot)
      ? { name: slot[0], type: slot[1], link: null, links: MULTI.has(slot[0]) ? [] : undefined }
      : { name: slot.name, type: slot.type, link: null, links: MULTI.has(slot.name) ? [] : undefined }),
    outputs: (opts.outputs || c.outputs).map(slot => Array.isArray(slot)
      ? { name: slot[0], type: slot[1], links: [] } : { name: slot.name, type: slot.type, links: [] }),
    _out: null, _state: 'idle', _note: '',
  };
  G.lastNodeId = Math.max(G.lastNodeId, node.id);
  G.nodes.set(node.id, node);
  return node;
}

// can a wire of `from` type land on a port of `to` type? Text and text,
// image and image, and the refs port takes any image or image list.
function compatible(from, to) {
  if (from === to) return true;
  if (to === 'images') return from === 'image' || from === 'images';
  return false;
}

function connect(from, fromSlot, to, toSlot, id = null) {
  const out = from.outputs[fromSlot];
  const inp = to.inputs[toSlot];
  if (!out || !inp || from.id === to.id) return null;
  if (!compatible(out.type, inp.type)) return null;
  if (!MULTI.has(inp.name) && inp.link != null) removeLink(inp.link);
  // the same wire twice is one wire
  for (const id of (inp.links || [inp.link])) {
    const l = id != null && G.links.get(id);
    if (l && l.origin_id === from.id && l.origin_slot === fromSlot) return l;
  }
  // a saved graph keeps its link ids so the runner's node_states line up
  if (id != null) G.lastLinkId = Math.max(G.lastLinkId, id);
  const link = { id: id != null ? id : ++G.lastLinkId, origin_id: from.id, origin_slot: fromSlot,
                 target_id: to.id, target_slot: toSlot, type: out.type };
  G.links.set(link.id, link);
  out.links.push(link.id);
  if (MULTI.has(inp.name)) {
    inp.links.push(link.id);
    if (inp.link == null) inp.link = link.id;    // the single-link readers see the first
  } else {
    inp.link = link.id;
  }
  return link;
}

function removeLink(id) {
  const link = G.links.get(id);
  if (!link) return;
  G.links.delete(id);
  const from = G.nodes.get(link.origin_id);
  const to = G.nodes.get(link.target_id);
  if (from && from.outputs[link.origin_slot]) {
    from.outputs[link.origin_slot].links = from.outputs[link.origin_slot].links.filter(l => l !== id);
  }
  if (to && to.inputs[link.target_slot]) {
    const inp = to.inputs[link.target_slot];
    if (inp.links) {
      inp.links = inp.links.filter(l => l !== id);
      inp.link = inp.links[0] ?? null;
    } else if (inp.link === id) {
      inp.link = null;
    }
  }
}

function removeNode(id) {
  const node = G.nodes.get(id);
  if (!node) return;
  for (const link of [...G.links.values()]) {
    if (link.origin_id === id || link.target_id === id) removeLink(link.id);
  }
  G.nodes.delete(id);
}

function serialize() {
  const nodes = [...G.nodes.values()].map((n, i) => ({
    id: n.id, type: n.type, title: n.title,
    pos: [Math.round(n.pos[0]), Math.round(n.pos[1])],
    size: [Math.round(n.size[0]), Math.round(n.size[1])],
    flags: {}, order: i, mode: 0,
    inputs: n.inputs.map(s => s.links
      ? { name: s.name, type: s.type, link: s.link, links: [...s.links] }
      : { name: s.name, type: s.type, link: s.link }),
    outputs: n.outputs.map(s => ({ name: s.name, type: s.type, links: [...s.links] })),
    properties: JSON.parse(JSON.stringify(n.properties)),
  }));
  const links = [...G.links.values()].map(l =>
    [l.id, l.origin_id, l.origin_slot, l.target_id, l.target_slot, l.type]);
  return { last_node_id: G.lastNodeId, last_link_id: G.lastLinkId, nodes, links,
           groups: [], config: {}, version: 0.4 };
}

/* Tolerant of the older LiteGraph-written rows: a node's ports come
   from the catalogue (so a graph saved before the `refs` port existed
   gains it), links are re-attached by slot index, and a type the
   catalogue does not know keeps whatever ports it was saved with. */
function configure(json) {
  G = newGraph();
  for (const raw of json.nodes || []) {
    const known = CATALOG[raw.type];
    makeNode(raw.type, {
      id: raw.id, title: raw.title, pos: raw.pos || [0, 0],
      properties: raw.properties || {},
      inputs: known ? undefined : (raw.inputs || []),
      outputs: known ? undefined : (raw.outputs || []),
    });
  }
  const rows = (json.links || []).map(l => Array.isArray(l)
    ? { id: l[0], origin_id: l[1], origin_slot: l[2], target_id: l[3], target_slot: l[4], type: l[5] }
    : l);
  for (const l of rows) {
    const from = G.nodes.get(l.origin_id);
    const to = G.nodes.get(l.target_id);
    if (!from || !to) continue;
    connect(from, l.origin_slot, to, l.target_slot, l.id);
  }
  G.lastNodeId = Math.max(G.lastNodeId, json.last_node_id || 0);
  G.lastLinkId = Math.max(G.lastLinkId, json.last_link_id || 0);
}

/* ── node values (client side, for a per-node Run) ── */

function nodeValue(node) {
  if (node._out !== undefined && node._out !== null) return node._out;
  if (node.type === 'zpf/reference_image') return node.properties.url || '';
  if (node.type === 'zpf/reference_set') return node.properties.urls || [];
  if (PURE.has(node.type)) return node.properties.text || '';
  return null;
}

function inputNode(node, name) {
  const slot = node.inputs.find(i => i.name === name);
  const link = slot && slot.link != null ? G.links.get(slot.link) : null;
  return link ? G.nodes.get(link.origin_id) : null;
}

function inputVal(node, name) {
  const src = inputNode(node, name);
  return src ? nodeValue(src) : null;
}

function inputVals(node, name) {
  const slot = node.inputs.find(i => i.name === name);
  if (!slot) return [];
  const ids = slot.links || (slot.link != null ? [slot.link] : []);
  const out = [];
  for (const id of ids) {
    const link = G.links.get(id);
    const src = link && G.nodes.get(link.origin_id);
    const v = src ? nodeValue(src) : null;
    if (Array.isArray(v)) out.push(...v); else if (v) out.push(v);
  }
  return out;
}

/* Every reference image a node grounds on, in the same order the
   server builds it (workflow_runner.node_reference_urls): the wired
   keyframe, the reference sets wired into `refs`, the frozen ref_urls,
   the image_url fallback. Deduplicated. */
function referenceUrls(node) {
  const out = [];
  const push = u => { if (u && typeof u === 'string' && !out.includes(u)) out.push(u); };
  push(inputVal(node, 'image'));
  inputVals(node, 'refs').forEach(push);
  (node.properties.ref_urls || []).forEach(push);
  push(node.properties.image_url);
  return out;
}

// what is wired in IS the reference list: before every save the billed
// nodes' frozen ref_urls are rewritten from the wires, so the drawing
// and the run never disagree
function freezeRefs() {
  for (const node of G.nodes.values()) {
    if (!node.inputs.some(i => i.name === 'refs')) continue;
    node.properties.ref_urls = inputVals(node, 'refs');
  }
}

/* ── view state ── */
let zoom = 1;
let pan = { x: 0, y: 0 };
let sel = null;                // selected node id, or 'out:<id>' for a derived output card
let tool = 'select';
let spaceHeld = false;
const els = new Map();         // node id -> card element; output cards keyed 'out:<id>'
let wired = false;
let pendingFit = false;

let currentId = null;          // the saved workflow row this canvas edits (library mode)
let runAllJobId = null;
const nodeJobs = new Map();    // job id -> node id, for per-node runs
let runProgress = 0;           // the run-all job's fraction, for the output overlay

/* director-tab state */
let canvasOpen = false;
let directorConceptId = null;
let landingJobId = null;
let briefTouched = false;
let planOverride = null;
let landingRequested = false;
let directorConcept = null;
let activeShotN = null;
const shotGraphs = new Map();  // shot n -> serialized graph with local edits
let enhanceSystem = '';
const seededTexts = new Map();
const attached = new Set();

/* ── geometry ── */
const HEAD = 44;               // card header height
const PORT_Y0 = HEAD + 22;     // first input port, from the card top
const PORT_GAP = 30;

function inputPos(node, i) {
  return [node.pos[0], node.pos[1] + PORT_Y0 + i * PORT_GAP];
}
function outputPos(node, j) {
  const n = node.outputs.length;
  if (n === 1) return [node.pos[0] + node.size[0], node.pos[1] + node.size[1] / 2];
  return [node.pos[0] + node.size[0], node.pos[1] + PORT_Y0 + j * PORT_GAP];
}
function outPos(node) {
  return node.properties.out_pos || [node.pos[0], node.pos[1] + node.size[1] + 90];
}

function toWorld(clientX, clientY) {
  const r = $('gscanvas').getBoundingClientRect();
  return [(clientX - r.left - pan.x) / zoom, (clientY - r.top - pan.y) / zoom];
}

function applyView() {
  $('gsworld').style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;
  const c = $('gscanvas');
  c.style.backgroundSize = `${26 * zoom}px ${26 * zoom}px`;
  c.style.backgroundPosition = `${pan.x}px ${pan.y}px`;
  $('gszoomlabel').textContent = `${Math.round(zoom * 100)}%`;
  paintMini();
  positionMenu();
}

function zoomAt(factor, clientX, clientY) {
  const r = $('gscanvas').getBoundingClientRect();
  const cx = clientX === undefined ? r.width / 2 : clientX - r.left;
  const cy = clientY === undefined ? r.height / 2 : clientY - r.top;
  const next = Math.min(1.6, Math.max(0.3, zoom * factor));
  pan.x = cx - (cx - pan.x) * (next / zoom);
  pan.y = cy - (cy - pan.y) * (next / zoom);
  zoom = next;
  applyView();
}

function bounds() {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const take = (x, y, w, h) => {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y);
    x1 = Math.max(x1, x + w); y1 = Math.max(y1, y + h);
  };
  for (const n of G.nodes.values()) {
    take(n.pos[0], n.pos[1], n.size[0], n.size[1]);
    if (n.type === 'zpf/generate') {
      const el = els.get('out:' + n.id);
      const p = outPos(n);
      take(p[0], p[1], 460, el ? el.offsetHeight : 372);
    }
  }
  return isFinite(x0) ? { x0, y0, x1, y1 } : null;
}

/* Frame the whole graph: every card's bounds, scaled to fill the
   canvas with a margin, centred. Called on arrival and resize so the
   graph is never parked off the edge. */
function fitView() {
  const b = bounds();
  const r = $('gscanvas').getBoundingClientRect();
  if (!b || !r.width) return;
  const pad = 72;
  const inspector = $('gsinspect').hidden ? 0 : 320;
  const w = r.width - inspector, h = r.height - 120;   // the bar sits over the bottom
  zoom = Math.max(0.3, Math.min(1.15, Math.min((w - pad * 2) / (b.x1 - b.x0), (h - pad * 2) / (b.y1 - b.y0))));
  pan.x = (w - (b.x1 - b.x0) * zoom) / 2 - b.x0 * zoom;
  pan.y = (h - (b.y1 - b.y0) * zoom) / 2 - b.y0 * zoom + 8;
  applyView();
}

function fitWhenSized() {
  const r = $('gscanvas').getBoundingClientRect();
  if (!r.width || !r.height || !pendingFit) return;
  pendingFit = false;
  layout();
  fitView();
}

/* ── rendering ── */

function stateClass(node) {
  return node._state === 'running' ? ' running' : node._state === 'failed' ? ' failed'
    : node._state === 'done' ? ' done' : node._state === 'skipped' ? ' skipped' : '';
}

function refSetTitle(node) {
  const p = node.properties;
  return `${SET_LABEL[p.kind] || 'Element'}${p.label ? ' · ' + p.label : ''}`;
}

function nodeTitle(node) {
  return node.type === 'zpf/reference_set' && !node._renamed ? refSetTitle(node) : node.title;
}

/* What the Generate node would render ON and what that costs: the
   server's own price (pricing.display, served as `generate` on the
   concept) laid over the default renderer's state the chips read. */
function generateState() {
  const c = directorConcept || {};
  const g = c.generate && !c.generate.error ? c.generate : null;
  return g
    ? { ...(c.renderer || {}), model: g.model, duration: g.durations[0], estimate_usd: g.estimate_usd }
    : (c.renderer || {});
}

function gateNote(type) {
  if (type === 'zpf/generate') {
    // running this node IS the spend approval (2026-09-09), and it
    // renders on whatever this account has a key for (providers.renderer_for,
    // 2026-09-11) -- so a missing key is the only thing that can gate it
    return state.caps['video.generate'] ? ''
      : 'Video rendering is not configured on this server (FAL_KEY)';
  }
  if (type === 'zpf/nano_banana' && !state.caps['nano.generate']) return 'GEMINI_API_KEY not set';
  if (type === 'zpf/enhance' && !state.caps['enhance']) return 'GEMINI_API_KEY not set';
  return '';
}

function frames(urls, cols, ratio, removable) {
  return `<div class="gsframes c${cols}">${urls.map((u, i) => `
    <span class="gsframe" style="aspect-ratio:${ratio}${i === 0 ? ';--ring:rgb(255 255 255 / .2)' : ''}">
      <img src="${esc(u)}" alt="" loading="lazy">
      ${removable ? `<button class="gsfx" data-act="unframe" data-i="${i}" title="Remove this frame">${icon('x')}</button>` : ''}
    </span>`).join('')}</div>`;
}

function bodyHTML(node) {
  const p = node.properties;
  const failed = node._state === 'failed';
  const skipped = node._state === 'skipped';
  const errline = failed ? `<div class="gserr">✕ ${esc(node._note || 'failed')}</div>`
    : skipped ? `<div class="gserr dim">${esc(node._note || 'skipped')}</div>` : '';

  switch (node.type) {
    case 'zpf/user_prompt':
      return `<div class="mentionwrap"><textarea class="gsta" rows="4" placeholder="Describe the shot… (@ to reference an element)">${esc(p.text || '')}</textarea><div class="mentiondrop" hidden></div></div>
        <div class="gsfoot">${icon('at')}<span class="m gscount">${(p.text || '').length} chars</span></div>`;
    case 'zpf/system_prompt':
      return `<p class="gspre">${esc(p.text || '') || '<i>No instructions — the enhance falls back to prompts/enhance_system.txt</i>'}</p>
        <div class="gsfoot"><span class="m">${(p.text || '').length} chars</span><span class="spacer"></span><button class="gsbtn ghost" data-act="edit">Edit</button></div>`;
    case 'zpf/ground':
      return `<p class="gspre">${node._out ? esc(node._out) : failed ? '' : `<i>${esc(p.text || 'Output will appear here')}</i>`}</p>${errline}
        <div class="gsfoot"><span class="spacer"></span><button class="gsbtn ghost" data-act="run">${icon('play')}Run</button></div>`;
    case 'zpf/reference_image':
      return `<div class="gsplate">${p.url ? `<img src="${esc(p.url)}" alt="">` : '<span class="gschecker"></span><span class="gsempty">No image picked</span>'}</div>
        <div class="gsfoot"><button class="gsbtn ghost" data-act="media">${icon('replace')}${p.url ? 'Replace' : 'Pick image'}</button></div>`;
    case 'zpf/reference_set': {
      const urls = p.urls || [];
      const cols = p.kind === 'location' ? 2 : 3;
      const ratio = p.kind === 'location' ? '4 / 3' : '1';
      return `${urls.length ? frames(urls, cols, ratio, true) : '<div class="gsplate small"><span class="gschecker"></span><span class="gsempty">No frames yet</span></div>'}
        <div class="gsfoot"><span class="m">${urls.length} frame${urls.length === 1 ? '' : 's'}</span><span class="spacer"></span><button class="gsbtn ghost" data-act="media">${icon('plus')}Add frame</button></div>`;
    }
    case 'zpf/enhance':
      return `<p class="gspre tall">${node._out ? esc(node._out) : (failed || skipped) ? '' : `<i>${esc(gateNote(node.type) || 'Output will appear here')}</i>`}</p>${errline}
        <div class="gsfoot"><span class="m">${node._out ? (node._out.length + ' chars') : 'text → text'}</span><span class="spacer"></span><button class="gsbtn ghost" data-act="run">${icon('play')}Run</button></div>`;
    case 'zpf/nano_banana':
      return `<div class="gsplate">${node._out && !failed ? `<img src="${esc(node._out)}" alt="">`
          : `<span class="gschecker"></span><span class="gsempty">${esc(failed ? '' : (node._note || gateNote(node.type) || 'Keyframe will appear here'))}</span>`}
          ${node._state === 'running' ? overlayHTML('rendering · keyframe') : ''}</div>${errline}
        <div class="gsfoot"><span class="m">${node._out ? 'keyframe' : 'text/image → image'}</span><span class="spacer"></span><button class="gsbtn ghost" data-act="run">${icon('play')}Run</button></div>`;
    case 'zpf/generate': {
      const rw = generateState();
      const ratio = rw.ratio === '720:1280' ? '9:16' : rw.ratio === '1280:720' ? '16:9' : (rw.ratio || '9:16');
      const cam = p.camera ? `<span class="gschip">${icon('video')}${esc(p.camera)}</span>` : '';
      return `<div class="gschips">
          <span class="gschip">${icon('clock')}${esc(String(rw.duration || 5))} sec</span>
          <span class="gschip">${icon('ratio')}${esc(ratio)}</span>
          <span class="gschip">${icon('monitor')}${esc(rw.model || 'video')}</span>${cam}</div>${errline}
        <div class="gsfoot"><span class="m">${rw.estimate_usd != null ? 'est. $' + Number(rw.estimate_usd).toFixed(2) : esc(gateNote(node.type) || 'text/image → video')}</span><span class="spacer"></span>
          <button class="gsbtn pri" data-act="run">${icon('play')}${node._state === 'running' ? 'Running' : 'Run'}</button></div>`;
    }
    default:
      return `<p class="gspre">${node._out ? esc(String(node._out)) : `<i>${esc(p.text || p.url || '')}</i>`}</p>${errline}`;
  }
}

function overlayHTML(label) {
  const pct = Math.round(runProgress * 100);
  return `<div class="gsoverlay"><div class="gsorow">${icon('loader', 'spin')}<span class="m light">${esc(label)}</span><span class="spacer"></span><span class="m">${pct}%</span></div><div class="gsobar"><i style="width:${pct}%"></i></div></div>`;
}

function headerHTML(node) {
  const c = CATALOG[node.type] || {};
  const ic = node.type === 'zpf/reference_set' ? SET_ICON[node.properties.kind] || 'image' : c.icon || 'box';
  const n = [...G.nodes.keys()].indexOf(node.id) + 1;
  return `<div class="gshead">${icon(ic)}<b>${esc(nodeTitle(node))}</b><span class="spacer"></span>
    <span class="m gsn">${node.type === 'zpf/generate' ? 'generate' : String(n).padStart(2, '0')}</span></div>`;
}

function portsHTML(node) {
  const ins = node.inputs.map((s, i) => `<span class="gsport in${s.link != null ? ' on' : ''}" data-slot="${i}" title="${esc(s.name)} · ${esc(s.type)}" style="top:${PORT_Y0 + i * PORT_GAP}px"></span>`).join('');
  const outs = node.outputs.map((s, j) => `<span class="gsport out${s.links.length ? ' on' : ''}" data-slot="${j}" title="${esc(s.name)} · ${esc(s.type)}" style="${node.outputs.length === 1 ? 'top:50%;margin-top:-6px' : 'top:' + (PORT_Y0 + j * PORT_GAP) + 'px'}"></span>`).join('');
  return ins + outs;
}

function buildNodeEl(node) {
  const el = document.createElement('div');
  el.className = 'gsnode';
  el.dataset.id = node.id;
  paintNode(node, el);
  return el;
}

function paintNode(node, el = els.get(node.id)) {
  if (!el) return;
  const focused = document.activeElement;
  const keepText = focused && el.contains(focused) && focused.tagName === 'TEXTAREA';
  if (keepText) {
    // typing: only the counter and the state class move
    el.className = 'gsnode' + stateClass(node) + (sel === node.id ? ' sel' : '');
    const count = el.querySelector('.gscount');
    if (count) count.textContent = `${(node.properties.text || '').length} chars`;
    return;
  }
  el.className = 'gsnode' + stateClass(node) + (sel === node.id ? ' sel' : '');
  el.style.width = node.size[0] + 'px';
  el.style.minHeight = (PORT_Y0 + Math.max(node.inputs.length, node.outputs.length) * PORT_GAP) + 'px';
  el.innerHTML = headerHTML(node) + `<div class="gsbody">${bodyHTML(node)}</div>` + portsHTML(node);
  wireNodeEl(node, el);
}

function wireNodeEl(node, el) {
  const ta = el.querySelector('textarea.gsta');
  if (ta) {
    ta.addEventListener('input', () => {
      node.properties.text = ta.value;
      node._out = null;
      const count = el.querySelector('.gscount');
      if (count) count.textContent = `${ta.value.length} chars`;
      if (node === promptNode()) syncBar();
    });
    ta.addEventListener('change', () => { layout(); });
    const drop = el.querySelector('.mentiondrop');
    if (drop) wireMentions(ta, drop, addElementFromMention);
  }
  el.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    nodeAction(node, b.dataset.act, b.dataset);
  }));
  el.querySelectorAll('img').forEach(img => img.addEventListener('load', () => layout(), { once: true }));
}

function nodeAction(node, act, data = {}) {
  if (act === 'run') runNode(node);
  else if (act === 'edit') { select(node.id); $('gsitext').focus(); }
  else if (act === 'media') openModal(node, 'media');
  else if (act === 'unframe') {
    node.properties.urls.splice(Number(data.i), 1);
    node._out = null;
    paintNode(node); layout();
  }
}

/* the derived output card under a video node: the clip (or the
   keyframe while there is none), status, re-roll and export */
function outputHTML(node) {
  const running = node._state === 'running';
  const clip = node._out && node._state !== 'failed' ? node._out : '';
  const still = inputVal(node, 'image') || node.properties.image_url || '';
  const status = running ? 'rendering' : clip ? 'done' : node._state === 'failed' ? 'failed'
    : node._state === 'skipped' ? 'skipped' : 'queued';
  const rw = generateState();
  const ratio = rw.ratio === '720:1280' ? '9:16' : (rw.ratio || '9:16');
  return `<div class="gshead">${icon('clap')}<b>Output${directorConcept ? ' · ' + esc(directorConcept.n.toLowerCase()) : ''}</b><span class="spacer"></span>
      <span class="gsstatus${status === 'done' || running ? ' lit' : ''}${status === 'failed' ? ' bad' : ''}">${status}</span></div>
    <div class="gsbody">
      <div class="gsplate video">
        ${clip ? `<video src="${esc(clip)}" muted loop playsinline preload="metadata" controls></video>`
          : still ? `<img src="${esc(still)}" alt="" class="${running ? 'dimmed' : 'dimmed more'}">` : '<span class="gschecker"></span><span class="gsempty">The clip lands here</span>'}
        ${running ? overlayHTML('rendering · lane ' + esc(rw.model || 'video')) : ''}
      </div>
      ${node._state === 'failed' ? `<div class="gserr">✕ ${esc(node._note || 'failed')}</div>` : node._state === 'skipped' ? `<div class="gserr dim">${esc(node._note || 'skipped')}</div>` : ''}
      <div class="gsfoot">
        <button class="gsbtn" data-act="run">${icon('repeat')}Re-roll</button>
        <button class="gsbtn ghost" data-act="export" ${clip ? '' : 'disabled'}>${icon('download')}Export</button>
        <span class="spacer"></span><span class="m">${esc(String(rw.duration || 5))}s · ${esc(ratio)}</span>
      </div>
    </div>
    <span class="gsport in on top" title="media"></span>`;
}

function buildOutputEl(node) {
  const el = document.createElement('div');
  el.className = 'gsnode out';
  el.dataset.for = node.id;
  paintOutput(node, el);
  return el;
}

function paintOutput(node, el = els.get('out:' + node.id)) {
  if (!el) return;
  el.className = 'gsnode out' + stateClass(node) + (sel === 'out:' + node.id ? ' sel' : '');
  el.innerHTML = outputHTML(node);
  el.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    if (b.dataset.act === 'run') runNode(node);
    else if (b.dataset.act === 'export' && node._out) window.open(node._out, '_blank');
  }));
  el.querySelectorAll('img,video').forEach(m => m.addEventListener('loadedmetadata', () => layout(), { once: true }));
  el.querySelectorAll('img').forEach(m => m.addEventListener('load', () => layout(), { once: true }));
}

function mountNodes() {
  const host = $('gsnodes');
  host.innerHTML = '';
  els.clear();
  for (const node of G.nodes.values()) {
    const el = buildNodeEl(node);
    els.set(node.id, el);
    host.appendChild(el);
    if (node.type === 'zpf/generate') {
      const out = buildOutputEl(node);
      els.set('out:' + node.id, out);
      host.appendChild(out);
    }
  }
  layout();
  syncBar();
}

function repaintAll() {
  for (const node of G.nodes.values()) {
    paintNode(node);
    if (node.type === 'zpf/generate') paintOutput(node);
  }
  layout();
  if (sel !== null) paintInspector();
}

/* positions + wires + minimap, cheap enough to run on every drag frame */
function layout() {
  for (const node of G.nodes.values()) {
    const el = els.get(node.id);
    if (!el) continue;
    el.style.transform = `translate3d(${node.pos[0]}px, ${node.pos[1]}px, 0)`;
    node.size = [el.offsetWidth || node.size[0], el.offsetHeight || node.size[1]];
    if (node.type === 'zpf/generate') {
      const out = els.get('out:' + node.id);
      const p = outPos(node);
      if (out) out.style.transform = `translate3d(${p[0]}px, ${p[1]}px, 0)`;
    }
  }
  drawWires();
  paintMini();
  positionMenu();
}

function curve(x1, y1, x2, y2) {
  const dx = Math.max(50, Math.abs(x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}
function curveDown(x1, y1, x2, y2) {
  const dy = Math.max(36, Math.abs(y2 - y1) * 0.6);
  return `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
}

function drawWires() {
  const g = $('gswireg');
  const paths = [];
  for (const link of G.links.values()) {
    const from = G.nodes.get(link.origin_id), to = G.nodes.get(link.target_id);
    if (!from || !to) continue;
    const [x1, y1] = outputPos(from, link.origin_slot);
    const [x2, y2] = inputPos(to, link.target_slot);
    const d = curve(x1, y1, x2 - 1, y2);
    paths.push(`<path class="gswire${link.type === 'images' ? ' refs' : ''}" d="${d}"/><path class="gshit" data-link="${link.id}" d="${d}"><title>cut this wire</title></path>`);
  }
  for (const node of G.nodes.values()) {
    if (node.type !== 'zpf/generate') continue;
    const p = outPos(node);
    const out = els.get('out:' + node.id);
    const w = out ? out.offsetWidth : 460;
    paths.push(`<path class="gswire media" d="${curveDown(node.pos[0] + node.size[0] / 2, node.pos[1] + node.size[1], p[0] + w / 2, p[1] - 1)}"/>`);
  }
  g.innerHTML = paths.join('');
  g.querySelectorAll('.gshit').forEach(h => h.addEventListener('click', e => {
    if (tool !== 'cut' && !e.altKey) return;
    e.stopPropagation();
    removeLink(Number(h.dataset.link));
    repaintAll();
    toast('empty', 'Wire cut');
  }));
}

function paintMini() {
  const mini = $('gsmini');
  const b = bounds();
  const r = $('gscanvas').getBoundingClientRect();
  if (!b || !r.width) { mini.querySelectorAll('.gsmn').forEach(n => n.remove()); return; }
  const W = 190, H = 120, m = 8;
  const sx = (W - m * 2) / Math.max(1, b.x1 - b.x0), sy = (H - m * 2) / Math.max(1, b.y1 - b.y0);
  const s = Math.min(sx, sy);
  const bits = [];
  for (const node of G.nodes.values()) {
    const on = sel === node.id;
    bits.push(`<span class="gsmn${on ? ' on' : ''}" style="left:${m + (node.pos[0] - b.x0) * s}px;top:${m + (node.pos[1] - b.y0) * s}px;width:${node.size[0] * s}px;height:${node.size[1] * s}px"></span>`);
    if (node.type === 'zpf/generate') {
      const p = outPos(node), el = els.get('out:' + node.id);
      bits.push(`<span class="gsmn${sel === 'out:' + node.id ? ' on' : ''}" style="left:${m + (p[0] - b.x0) * s}px;top:${m + (p[1] - b.y0) * s}px;width:${460 * s}px;height:${(el ? el.offsetHeight : 372) * s}px"></span>`);
    }
  }
  // the viewport, in world units
  const vx = (-pan.x) / zoom, vy = (-pan.y) / zoom, vw = r.width / zoom, vh = r.height / zoom;
  bits.push(`<span class="gsmn view" style="left:${m + (vx - b.x0) * s}px;top:${m + (vy - b.y0) * s}px;width:${vw * s}px;height:${vh * s}px"></span>`);
  mini.querySelectorAll('.gsmn').forEach(n => n.remove());
  mini.insertAdjacentHTML('afterbegin', bits.join(''));
}

/* ── selection: the floating menu over the card + the inspector ── */

function select(id) {
  sel = id;
  for (const node of G.nodes.values()) {
    const el = els.get(node.id);
    if (el) el.classList.toggle('sel', sel === node.id);
    const out = els.get('out:' + node.id);
    if (out) out.classList.toggle('sel', sel === 'out:' + node.id);
  }
  positionMenu();
  paintInspector();
  paintMini();
}

function selectedNode() {
  if (sel === null) return null;
  if (typeof sel === 'string' && sel.startsWith('out:')) return G.nodes.get(Number(sel.slice(4))) || null;
  return G.nodes.get(sel) || null;
}

function positionMenu() {
  const menu = $('gsmenu');
  const node = selectedNode();
  if (!node) { menu.hidden = true; return; }
  const isOut = typeof sel === 'string';
  const p = isOut ? outPos(node) : node.pos;
  const el = els.get(isOut ? 'out:' + node.id : node.id);
  const w = el ? el.offsetWidth : node.size[0];
  menu.hidden = false;
  menu.style.transform = `translate3d(${p[0] + w - 106}px, ${p[1] - 46}px, 0)`;
  menu.querySelector('[data-act="run"]').hidden = !BILLED.has(node.type);
  menu.querySelector('[data-act="open"]').hidden = !(node._out && /^(https?:|\/renders\/|\/refs\/|data:)/.test(String(node._out)));
  menu.querySelector('[data-act="delete"]').hidden = isOut;
}

function paintInspector() {
  const asideEl = $('gsinspect');
  const node = selectedNode();
  const wasHidden = asideEl.hidden;
  asideEl.hidden = !node;
  $('gs').classList.toggle('inspecting', !!node);
  if (!node) { if (!wasHidden) layout(); return; }
  const c = CATALOG[node.type] || {};
  const isOut = typeof sel === 'string';
  $('gsititle').textContent = isOut ? 'Output' : nodeTitle(node);
  $('gsinote').textContent = isOut ? 'The rendered clip. Re-roll makes a variation on the same wires; approving in Queue renders unattended.' : (c.note || '');
  const name = $('gsiname');
  name.value = isOut ? 'Output' : nodeTitle(node);
  name.disabled = isOut;
  name.oninput = () => { node.title = name.value; node._renamed = true; paintNode(node); layout(); };

  const textsec = $('gsitextsec');
  const isText = ['zpf/user_prompt', 'zpf/system_prompt', 'zpf/ground'].includes(node.type) && !isOut;
  textsec.hidden = !isText;
  if (isText) {
    $('gsitextlabel').textContent = node.type === 'zpf/ground' ? 'fallback spark — used when the spark port is unconnected'
      : node.type === 'zpf/system_prompt' ? 'instructions' : 'prompt';
    const ta = $('gsitext');
    ta.value = node.properties.text || '';
    ta.oninput = () => {
      node.properties.text = ta.value; node._out = null;
      const card = els.get(node.id);
      const cardTa = card && card.querySelector('textarea.gsta');
      if (cardTa) cardTa.value = ta.value;
      const count = card && card.querySelector('.gscount');
      if (count) count.textContent = `${ta.value.length} chars`;
      if (node.type === 'zpf/system_prompt') { paintNode(node); }
      if (node === promptNode()) syncBar();
    };
  }

  const isGen = node.type === 'zpf/generate';
  $('gsicamsec').hidden = !isGen;
  $('gsispendsec').hidden = !isGen;
  if (isGen) {
    paintCamera(node);
    const rw = generateState();
    $('gsispend').textContent = rw.estimate_usd != null ? '$' + Number(rw.estimate_usd).toFixed(2) : '—';
    $('gsispendnote').textContent = `per ${rw.duration || 5}-second clip · ${rw.model || 'video'}`;
    $('gsigate').textContent = gateNote(node.type) || (rw.today != null ? `${rw.today} rendered today` : '');
  }

  const outsec = $('gsioutsec');
  const hasOut = node._out != null && node._out !== '' && !isOut;
  outsec.hidden = !hasOut;
  if (hasOut) $('gsiout').textContent = String(node._out);

  const ins = node.inputs.reduce((n, s) => n + ((s.links && s.links.length) || (s.link != null ? 1 : 0)), 0);
  const outs = node.outputs.reduce((n, s) => n + s.links.length, 0);
  $('gsiwires').textContent = isOut ? '1 in · 0 out' : `${ins} in · ${outs} out`;
  if (wasHidden) layout();
}

/* the camera chips fold a preset into the prompt — the runner has no
   camera parameter, the prompt IS where the move lives */
let presets = [];
function paintCamera(node) {
  const host = $('gsicam');
  host.innerHTML = presets.map(p =>
    `<button class="gsicamb${node.properties.camera === p.label ? ' on' : ''}" data-id="${esc(p.id)}">${esc(p.label)}</button>`).join('')
    || '<span class="m">no presets on file</span>';
  host.querySelectorAll('.gsicamb').forEach(b => b.onclick = () => {
    const preset = presets.find(p => p.id === b.dataset.id);
    const prompt = promptNode();
    if (!preset || !prompt) return;
    node.properties.camera = preset.label;
    const text = (prompt.properties.text || '').trim();
    if (!text.includes(preset.how)) {
      prompt.properties.text = (text ? text + '\n\n' : '') + preset.how;
      prompt._out = null;
      paintNode(prompt);
      syncBar();
    }
    paintNode(node);
    paintCamera(node);
    layout();
    toast('empty', `${preset.label} folded into the prompt`);
  });
}

/* ── the prompt bar: the shot's prompt node, edited from the bottom ── */

function promptNode() {
  for (const n of G.nodes.values()) if (n.type === 'zpf/user_prompt') return n;
  return null;
}

let barSyncing = false;
function syncBar() {
  const bar = $('gsprompttext');
  const node = promptNode();
  if (document.activeElement === bar) return;
  barSyncing = true;
  bar.value = node ? (node.properties.text || '') : '';
  bar.disabled = !node;
  bar.placeholder = node ? 'Describe the shot… (@ to bring an element onto the canvas)'
    : 'Add a Prompt node to start a chain';
  autosize(bar);
  barSyncing = false;
}

function autosize(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(160, ta.scrollHeight) + 'px';
}

function wireBar() {
  const bar = $('gsprompttext');
  bar.addEventListener('input', () => {
    if (barSyncing) return;
    autosize(bar);
    const node = promptNode();
    if (!node) return;
    node.properties.text = bar.value;
    node._out = null;
    const card = els.get(node.id);
    const ta = card && card.querySelector('textarea.gsta');
    if (ta && ta !== document.activeElement) ta.value = bar.value;
    const count = card && card.querySelector('.gscount');
    if (count) count.textContent = `${bar.value.length} chars`;
  });
  bar.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); runAll(); }
  });
  wireMentions(bar, $('gsmentions'), addElementFromMention);
}

/* @Michael in any prompt box → the element's frames land on the canvas
   as a reference set, wired into the enhance, the keyframe and the
   clip. The search row carries name + category; the frames come from
   the cached assets payload. */
async function addElementFromMention(item) {
  let assets;
  try { assets = await loadAssets(); } catch { assets = { items: [] }; }
  const asset = (assets.items || []).find(a => a.name === item.name && a.category === item.category);
  const urls = asset ? (asset.photos || []).slice(0, 6) : (item.thumb ? [item.thumb] : []);
  if (!urls.length) { toast('empty', `${item.name} has no photos on file — add some on Assets`); return; }
  addReferenceSet({ kind: item.category, label: item.name, urls });
}

function addReferenceSet({ kind, label, urls }) {
  // already on the canvas? then just make sure it is wired
  let node = [...G.nodes.values()].find(n =>
    n.type === 'zpf/reference_set' && n.properties.label === label && n.properties.kind === kind);
  if (!node) {
    // stack under the last reference set, or in the middle of the view
    const sets = [...G.nodes.values()].filter(n => n.type === 'zpf/reference_set');
    let pos;
    if (sets.length) {
      const last = sets.reduce((a, b) => (b.pos[1] > a.pos[1] ? b : a));
      pos = [last.pos[0], last.pos[1] + last.size[1] + 24];
    } else {
      const r = $('gscanvas').getBoundingClientRect();
      const [wx, wy] = toWorld(r.left + r.width * 0.35, r.top + r.height * 0.4);
      pos = [wx, wy];
    }
    node = makeNode('zpf/reference_set', { pos, properties: { kind, label, urls: [...urls] } });
  }
  let wiredTo = 0;
  for (const target of G.nodes.values()) {
    const slot = target.inputs.findIndex(i => i.name === 'refs');
    if (slot < 0) continue;
    if (connect(node, 0, target, slot)) wiredTo += 1;
  }
  mountNodes();
  select(node.id);
  toast('empty', `${label} on the canvas${wiredTo ? ` · wired into ${wiredTo} node${wiredTo === 1 ? '' : 's'}` : ''}`);
}

/* ── the modal (media picker for reference nodes; output viewer) ── */

let modal = { node: null, mode: null };

function openModal(node, mode) {
  modal = { node, mode };
  $('wfmtitle').textContent = nodeTitle(node) + (mode === 'view' ? ' · output' : '');
  const isMedia = mode === 'media';
  $('wfmtextwrap').hidden = isMedia;
  $('wfmmediawrap').hidden = !isMedia;
  $('wfmsave').hidden = mode === 'view';
  $('wfmmeta').textContent = '';
  $('wfmpresetrow').hidden = true;
  if (mode === 'view') {
    $('wfmlabel').textContent = 'Output';
    $('wfmtext').value = node._out ?? node._note ?? '';
    $('wfmtext').readOnly = true;
  } else if (isMedia) {
    $('wfmurl').value = node.type === 'zpf/reference_image' ? (node.properties.url || '') : '';
    $('wfmmeta').textContent = node.type === 'zpf/reference_set' ? 'adds a frame to the set' : '';
    renderModalMedia();
  }
  $('dscrim').setAttribute('data-open', '');
  $('wfmodal').setAttribute('data-open', '');
}

export function closeWorkflowModal() {
  if (!$('wfmodal').hasAttribute('data-open')) return;
  $('wfmodal').removeAttribute('data-open');
  $('dscrim').removeAttribute('data-open');
  modal = { node: null, mode: null };
}

async function renderModalMedia() {
  const grid = $('wfmgrid');
  grid.innerHTML = '<div class="probeblank">Loading media…</div>';
  let media;
  try {
    media = await api('/api/media');
  } catch (e) {
    grid.innerHTML = `<div class="probeblank" style="color:var(--signal)">${esc(e.message)}</div>`;
    return;
  }
  if (!media.items.length) {
    grid.innerHTML = '<div class="probeblank">No saved media yet — photos added on Assets appear here</div>';
    return;
  }
  grid.innerHTML = media.items.map(m => `
    <button class="mtile" type="button" data-u="${esc(m.url)}"
            aria-pressed="${$('wfmurl').value === m.url}"
            style="background-image:url('${m.url}')">
      <span class="mname">${esc(m.asset_name)}</span>
    </button>`).join('');
  grid.querySelectorAll('.mtile').forEach(tile => tile.onclick = () => {
    $('wfmurl').value = tile.dataset.u;
    grid.querySelectorAll('.mtile').forEach(t => t.setAttribute('aria-pressed', String(t === tile)));
  });
}

function applyModal() {
  const { node, mode } = modal;
  if (node && mode === 'media') {
    const url = $('wfmurl').value.trim();
    if (node.type === 'zpf/reference_set') {
      if (url && !node.properties.urls.includes(url)) node.properties.urls.push(url);
    } else {
      node.properties.url = url;
    }
    node._out = null;
    setNodeState(node, 'idle');
    paintNode(node); layout();
  }
  closeWorkflowModal();
}

/* ── run plumbing ── */

function setNodeState(node, st, note) {
  node._state = st;
  if (note !== undefined) node._note = note;
  paintNode(node);
  if (node.type === 'zpf/generate') paintOutput(node);
  layout();
  if (selectedNode() === node) paintInspector();
}

async function runNode(node) {
  try {
    if (node.type === 'zpf/ground') {
      setNodeState(node, 'running');
      const res = await api('/api/workflows/exec/ground', {
        method: 'POST', body: { spark: inputVal(node, 'spark') || node.properties.text || '' } });
      node._out = res.references;
      setNodeState(node, 'done', res.references ? '' : 'no references — library empty or store down');
    } else if (node.type === 'zpf/enhance') {
      setNodeState(node, 'running');
      const references = inputVal(node, 'references') || '';
      const res = await api('/api/workflows/exec/enhance', {
        method: 'POST',
        body: { system: inputVal(node, 'system') || '', user: inputVal(node, 'user') || '',
                references, ground: !references && !!node.properties.auto_ground,
                images: referenceUrls(node) } });
      nodeJobs.set(res.job_id, node.id);
    } else if (node.type === 'zpf/generate') {
      setNodeState(node, 'running');
      // the signed quote the chip showed rides along when this node is a
      // concept's shot (pricing.sign); the route refuses the run if the
      // scene or the renderer moved since
      const gen = (directorConcept && directorConcept.generate) || {};
      const token = gen.renders && gen.renders[0] && gen.renders[0].token;
      const p = node.properties || {};
      const shotRef = token && p.concept_id && p.shot_n && Number(p.concept_id) === Number(directorConcept.id)
        ? { concept_id: Number(p.concept_id), shot_n: Number(p.shot_n), token } : {};
      const res = await api('/api/workflows/exec/generate', {
        method: 'POST', body: { prompt: inputVal(node, 'prompt') || '', images: referenceUrls(node), ...shotRef } });
      nodeJobs.set(res.job_id, node.id);
    } else if (node.type === 'zpf/nano_banana') {
      setNodeState(node, 'running');
      const res = await api('/api/workflows/exec/nano', {
        method: 'POST', body: { prompt: inputVal(node, 'prompt') || '', images: referenceUrls(node) } });
      nodeJobs.set(res.job_id, node.id);
    }
  } catch (e) {
    setNodeState(node, 'failed', e.message);
  }
}

function clearRunState() {
  for (const node of G.nodes.values()) { node._out = null; node._note = ''; node._state = 'idle'; }
  runProgress = 0;
}

let toastTimer = null;
function toast(kind, message, retry) {
  stateline($('wfstate'), kind, message, retry);
  clearTimeout(toastTimer);
  if (kind === 'empty') toastTimer = setTimeout(() => stateline($('wfstate'), null), 5000);
}

async function saveWorkflow(quiet = false) {
  const name = $('wfname').value.trim() || 'Untitled workflow';
  freezeRefs();
  const body = { name, graph: serialize() };
  try {
    if (currentId) {
      await api(`/api/workflows/${currentId}`, { method: 'PUT', body });
    } else {
      body.brand = state.brand;
      const res = await api('/api/workflows', { method: 'POST', body });
      currentId = res.id;
    }
  } catch (e) {
    toast('error', `Save failed: ${e.message}`);
    throw e;
  }
  $('wfsaved').textContent = 'Saved just now';
  if (!quiet) toast('empty', `Saved "${name}"`);
  await loadList();
  return currentId;
}

async function loadList() {
  const pick = $('wfpick');
  let items = [];
  try {
    items = (await api('/api/workflows?brand=' + encodeURIComponent(state.brand))).items;
  } catch { /* the picker just stays empty */ }
  pick.innerHTML = '<option value="">Open…</option>' + items.map(w =>
    `<option value="${w.id}" ${w.id === currentId ? 'selected' : ''}>${esc(w.name)} · ${w.node_count} node${w.node_count === 1 ? '' : 's'}</option>`).join('');
}

function setConceptScope(concept) {
  directorConceptId = concept ? concept.id : null;
  const chip = $('dirchip');
  chip.hidden = !concept;
  if (concept) {
    const title = String(concept.title || '').toLowerCase();
    $('wfconcept').textContent = `${concept.n.toLowerCase()} · ${title.length > 26 ? title.slice(0, 25) + '…' : title}`;
  }
  $('wfsaveconcept').hidden = !concept;
  $('wfmore').hidden = !!concept;
  $('wfmore').open = false;
  paintQueueButton();
  if (!concept) {
    directorConcept = null;
    activeShotN = null;
    shotGraphs.clear();
  }
  renderShotDock();
}

function paintQueueButton() {
  const c = directorConcept;
  for (const id of ['sendqueue', 'gsisend']) {
    const b = $(id);
    if (id === 'sendqueue') b.hidden = !c;
    b.disabled = false;
    b.querySelector('span').textContent = !c ? 'Send to Queue'
      : c.media_url ? 'Rendered · see Queue'
      : (c.picked || c.parked) ? 'In the Queue' : 'Send to Queue';
    b.classList.toggle('lit', !!(c && (c.picked || c.parked)));
  }
}

/* Send to Queue = the pick. Nothing spends here: the concept lands in
   front of the Queue's approval gate, and approving THERE renders. */
async function sendToQueue() {
  const c = directorConcept;
  if (!c) { toast('empty', 'Open a concept first — the brief builds one'); return; }
  if (c.picked || c.parked || c.media_url) {
    (await import('./app.js')).go('queue');
    return;
  }
  for (const id of ['sendqueue', 'gsisend']) $(id).disabled = true;
  try {
    await api(`/api/concepts/${c.id}/pick`, { method: 'POST', body: { picked: true } });
    c.picked = true;
    paintQueueButton();
    refreshQueueBadge();
    toast('empty', `${c.n} is in the Queue — approving it there renders the clip`);
  } catch (e) {
    paintQueueButton();
    toast('error', `Send to Queue failed: ${e.message}`);
  }
}

function showCanvas() {
  canvasOpen = true;
  document.documentElement.dataset.gs = 'canvas';
  $('dirlanding').hidden = true;
  $('dircanvas').hidden = false;
  pendingFit = true;
  requestAnimationFrame(() => { layout(); fitWhenSized(); });
}

async function openWorkflow(id) {
  let w;
  try {
    w = await api(`/api/workflows/${id}`);
  } catch (e) {
    toast('error', `Could not open: ${e.message}`);
    return;
  }
  currentId = w.id;
  $('wfname').value = w.name;
  configure(w.graph && w.graph.nodes ? w.graph : { nodes: [], links: [] });
  clearRunState();
  sel = null;
  setConceptScope(null);
  mountNodes();
  showCanvas();
  paintInspector();
  toast(null);
}

function newWorkflow() {
  currentId = null;
  $('wfname').value = '';
  G = newGraph();
  $('wfpick').value = '';
  sel = null;
  setConceptScope(null);
  mountNodes();
  showCanvas();
  paintInspector();
  toast('empty', 'Empty canvas — the + adds a node');
}

async function deleteWorkflow() {
  if (!currentId) { newWorkflow(); return; }
  try {
    await api(`/api/workflows/${currentId}`, { method: 'DELETE' });
  } catch (e) {
    toast('error', `Delete failed: ${e.message}`);
    return;
  }
  newWorkflow();
  await loadList();
}

async function runAll() {
  if (!G.nodes.size) { toast('empty', 'Nothing to run — add nodes first'); return; }
  const btn = $('wfrunall');
  btn.disabled = true;
  try {
    // The runner executes a SAVED graph, so a run always saves first —
    // to the shot's own row in concept mode, so the graph that ran and
    // the graph you come back to are one row.
    freezeRefs();
    let runId;
    if (directorConceptId && activeShotN !== null) {
      const serialized = serialize();
      shotGraphs.set(activeShotN, serialized);
      const res = await api(`/api/concepts/${directorConceptId}/shots/${activeShotN}/graph`,
        { method: 'PUT', body: { graph: serialized, name: directorConcept ? directorConcept.title : null } });
      runId = res.id;
    } else {
      await saveWorkflow(true);
      runId = currentId;
    }
    clearRunState();
    repaintAll();
    const res = await api(`/api/workflows/${runId}/run`, { method: 'POST', body: {} });
    runAllJobId = res.job_id;
    toast('loading', 'Running the chain…');
  } catch (e) {
    toast('error', `Run failed: ${e.message}`);
    btn.disabled = false;
  }
}

function applyNodeStates(states, opts = {}) {
  if (!states) return;
  for (const [id, s] of Object.entries(states)) {
    const node = G.nodes.get(Number(id));
    if (!node) continue;
    if (s.status === 'done') {
      node._out = s.output;
      if (!opts.quiet) maybeAttachShotOutput(node);
    }
    node._state = s.status === 'running' ? 'running' : s.status === 'done' ? 'done'
      : s.status === 'failed' ? 'failed' : s.status === 'skipped' ? 'skipped' : 'idle';
    node._note = s.error || '';
  }
  repaintAll();
}

/* A shot-scoped node's finished render lands back on its shot: a
   Generate clip attaches as media_url, a Nano image as the shot's
   reference_image. */
function maybeAttachShotOutput(node) {
  const p = node.properties || {};
  if (!node._out || !directorConceptId || !p.shot_n) return;
  const key = `${node.id}·${node._out}`;
  if (attached.has(key)) return;
  attached.add(key);
  const url = new URL(node._out, location.origin).href;
  if (node.type === 'zpf/generate') {
    api(`/api/concepts/${directorConceptId}/shots/${p.shot_n}/media`, { method: 'POST', body: { url } })
      .then(() => {
        toast('empty', `Clip attached to shot ${p.shot_n}`);
        const shot = directorConcept && directorConcept.shots.find(s => s.n === p.shot_n);
        if (shot) { shot.media_url = url; renderShotDock(); }
        if (directorConcept) { directorConcept.media_url = url; paintQueueButton(); }
      })
      .catch(e => toast('error', `Clip attach failed: ${e.message}`));
  } else if (node.type === 'zpf/nano_banana') {
    api(`/api/concepts/${directorConceptId}/shots/${p.shot_n}/reference`, { method: 'POST', body: { url } })
      .then(() => toast('empty', `Keyframe attached as shot ${p.shot_n}'s reference`))
      .catch(e => toast('error', `Reference attach failed: ${e.message}`));
  }
}

/* ── the node palette (the bar's +) ── */

const NODE_CATALOG = [
  { type: 'zpf/user_prompt', title: 'Prompt', sub: 'The raw prompt — the start of the chain', cat: 'Text', glyph: 'T', grad: 'linear-gradient(135deg,#6d5bd0,#a78bfa)' },
  { type: 'zpf/system_prompt', title: 'Instructions', sub: 'How the enhance treats the prompt', cat: 'Text', glyph: 'S', grad: 'linear-gradient(135deg,#7c3aed,#c4b5fd)' },
  { type: 'zpf/ground', title: 'Ground in References', sub: 'Reference-library grounding for a spark', cat: 'Text', glyph: '¶', grad: 'linear-gradient(135deg,#166534,#4ade80)' },
  { type: 'zpf/enhance', title: 'Gemini 2.5 Flash', sub: 'Text to enhanced prompt', cat: 'Text', glyph: '✦', grad: 'linear-gradient(135deg,#1d4ed8,#60a5fa)' },
  { type: 'zpf/reference_set', title: 'Element', sub: 'A character, room or prop’s frames from Assets', cat: 'Image', glyph: '@', grad: 'linear-gradient(135deg,#9f1239,#E4002B)' },
  { type: 'zpf/reference_image', title: 'Reference Image', sub: 'One saved photo, as a plate', cat: 'Image', glyph: '▣', grad: 'linear-gradient(135deg,#0e7490,#67e8f9)' },
  { type: 'zpf/nano_banana', title: 'Nano Banana', sub: 'Text/Image to Image · the keyframe', cat: 'Image', glyph: '✦', grad: 'linear-gradient(135deg,#b45309,#fbbf24)' },
  { type: 'zpf/generate', title: 'Generate', sub: 'Text/Image to Video · any keyed renderer', cat: 'Video', glyph: '▶', grad: 'linear-gradient(135deg,#9f1239,#f87171)' },
];
const PALETTE_CATS = ['All', 'Text', 'Image', 'Video'];
let paletteCat = 'All';
let paletteKeep = false;

function addNodeAtCenter(type) {
  const r = $('gscanvas').getBoundingClientRect();
  const c = CATALOG[type];
  const [wx, wy] = toWorld(r.left + r.width / 2, r.top + r.height / 2 - 60);
  const node = makeNode(type, { pos: [wx - c.w / 2, wy - 100] });
  if (type === 'zpf/system_prompt' && enhanceSystem) node.properties.text = enhanceSystem;
  mountNodes();
  select(node.id);
}

function renderPalette() {
  const q = $('wfpsearch').value.trim().toLowerCase();
  $('wfpcats').innerHTML = PALETTE_CATS.map(c =>
    `<button class="wfpcat${c === paletteCat ? ' on' : ''}" data-c="${c}">${c === 'All' ? 'All nodes' : c}</button>`).join('');
  $('wfpcats').querySelectorAll('.wfpcat').forEach(b =>
    b.onclick = () => { paletteCat = b.dataset.c; renderPalette(); });
  const rows = NODE_CATALOG.filter(e =>
    (paletteCat === 'All' || e.cat === paletteCat)
    && (!q || `${e.title} ${e.sub} ${e.cat}`.toLowerCase().includes(q)));
  $('wfplist').innerHTML = rows.map(e => `
    <button class="wfprow" data-t="${e.type}">
      <span class="wfpicon" style="background:${e.grad}">${e.glyph}</span>
      <span class="wfpname">${esc(e.title)}<small>${esc(e.sub)}</small></span>
      <span class="wfpchev">›</span>
    </button>`).join('') || '<div class="wfpempty">No nodes match</div>';
  $('wfplist').querySelectorAll('.wfprow').forEach(b => b.onclick = () => {
    addNodeAtCenter(b.dataset.t);
    if (!paletteKeep) closePalette();
  });
}

function openPalette() {
  $('wfpalette').hidden = false;
  $('wfaddbtn').setAttribute('aria-expanded', 'true');
  renderPalette();
  setTimeout(() => $('wfpsearch').focus(), 40);
}

function closePalette() {
  $('wfpalette').hidden = true;
  $('wfaddbtn').setAttribute('aria-expanded', 'false');
}

function wirePalette() {
  $('wfaddbtn').onclick = () => $('wfpalette').hidden ? openPalette() : closePalette();
  $('wfpsearch').oninput = renderPalette;
  $('wfpkeep').onclick = () => {
    paletteKeep = !paletteKeep;
    $('wfpkeep').setAttribute('aria-checked', String(paletteKeep));
  };
  document.addEventListener('pointerdown', e => {
    if ($('wfpalette').hidden) return;
    if (!$('wfpalette').contains(e.target) && !$('wfaddbtn').contains(e.target)) closePalette();
  });
}

/* ── pointer interaction: drag, pan, zoom, wire ── */

function setTool(next) {
  tool = next;
  $('gscanvas').dataset.tool = next;
  document.querySelectorAll('.gstool[data-tool]').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.tool === next)));
}

function isEditable(target) {
  return target.closest && target.closest('textarea, input, select, button, a, video, .mentiondrop');
}

let dragWire = null;   // {node, slot, x, y}

function wireCanvas() {
  const canvas = $('gscanvas');

  canvas.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    const port = e.target.closest && e.target.closest('.gsport.out');
    const card = e.target.closest && e.target.closest('.gsnode');
    const panning = tool === 'pan' || spaceHeld || (!card && tool !== 'cut');

    if (port && card && !panning) {
      // start a wire from an output port
      e.preventDefault(); e.stopPropagation();
      const node = G.nodes.get(Number(card.dataset.id));
      dragWire = { node, slot: Number(port.dataset.slot) };
      const [x, y] = outputPos(node, dragWire.slot);
      const path = $('gsdragwire');
      path.hidden = false;
      path.setAttribute('d', curve(x, y, x, y));
      const move = ev => {
        const [wx, wy] = toWorld(ev.clientX, ev.clientY);
        path.setAttribute('d', curve(x, y, wx, wy));
      };
      const up = ev => {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        path.hidden = true;
        const under = document.elementFromPoint(ev.clientX, ev.clientY);
        const inPort = under && under.closest && under.closest('.gsport.in:not(.top)');
        const toCard = inPort && inPort.closest('.gsnode');
        if (toCard && toCard.dataset.id) {
          const to = G.nodes.get(Number(toCard.dataset.id));
          const made = connect(dragWire.node, dragWire.slot, to, Number(inPort.dataset.slot));
          if (made) { repaintAll(); toast('empty', `${nodeTitle(dragWire.node)} → ${nodeTitle(to)} · ${to.inputs[made.target_slot].name}`); }
          else toast('error', `Those ports don't match — ${dragWire.node.outputs[dragWire.slot].type} can't feed ${to.inputs[Number(inPort.dataset.slot)].type}`);
        }
        dragWire = null;
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
      return;
    }

    if (card && !panning) {
      if (isEditable(e.target)) return;      // typing in a card, or its buttons
      e.preventDefault();
      const isOut = !!card.dataset.for;
      const node = G.nodes.get(Number(isOut ? card.dataset.for : card.dataset.id));
      select(isOut ? 'out:' + node.id : node.id);
      const sx = e.clientX, sy = e.clientY;
      const start = isOut ? [...outPos(node)] : [...node.pos];
      let moved = false;
      const move = ev => {
        const nx = start[0] + (ev.clientX - sx) / zoom, ny = start[1] + (ev.clientY - sy) / zoom;
        moved = true;
        if (isOut) node.properties.out_pos = [nx, ny]; else node.pos = [nx, ny];
        layout();
      };
      const up = () => {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        card.classList.remove('dragging');
        if (moved) layout();
      };
      card.classList.add('dragging');
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
      return;
    }

    if (tool === 'cut') return;
    // pan
    if (isEditable(e.target)) return;
    e.preventDefault();
    const sx = e.clientX, sy = e.clientY, start = { ...pan };
    let moved = false;
    canvas.classList.add('panning');
    const move = ev => {
      pan = { x: start.x + (ev.clientX - sx), y: start.y + (ev.clientY - sy) };
      moved = true;
      applyView();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      canvas.classList.remove('panning');
      if (!moved && !card) select(null);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  });

  canvas.addEventListener('wheel', e => {
    if (isEditable(e.target) && !e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      zoomAt(e.deltaY > 0 ? 0.92 : 1.08, e.clientX, e.clientY);
    } else {
      pan = { x: pan.x - e.deltaX, y: pan.y - e.deltaY };
      applyView();
    }
  }, { passive: false });

  canvas.addEventListener('dblclick', e => {
    if (e.target.closest('.gsnode') || isEditable(e.target)) return;
    openPalette();
  });

  // the floating menu over the selected card
  $('gsmenu').querySelectorAll('[data-act]').forEach(b => b.addEventListener('mousedown', e => e.stopPropagation()));
  $('gsmenu').querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    const node = selectedNode();
    if (!node) return;
    if (b.dataset.act === 'run') runNode(node);
    else if (b.dataset.act === 'open') window.open(node._out, '_blank');
    else if (b.dataset.act === 'delete') deleteSelected();
  }));

  addEventListener('keydown', e => {
    if (document.documentElement.dataset.v !== 'director' || !canvasOpen) return;
    const typing = isEditable(e.target);
    if (e.key === ' ' && !typing) { spaceHeld = true; canvas.classList.add('space'); e.preventDefault(); }
    if ((e.key === 'Delete' || e.key === 'Backspace') && !typing && sel !== null) { e.preventDefault(); deleteSelected(); }
    if (e.key === 'Escape') { if (!$('wfpalette').hidden) closePalette(); else select(null); }
    if (!typing && !e.metaKey && !e.ctrlKey) {
      if (e.key === 'v') setTool('select');
      if (e.key === 'h') setTool('pan');
      if (e.key === 'x') setTool('cut');
      if (e.key === 'f') fitView();
    }
  });
  addEventListener('keyup', e => {
    if (e.key === ' ') { spaceHeld = false; canvas.classList.remove('space'); }
  });
}

function deleteSelected() {
  const node = selectedNode();
  if (!node || typeof sel === 'string') return;
  removeNode(node.id);
  sel = null;
  mountNodes();
  paintInspector();
  toast('empty', `${nodeTitle(node)} removed`);
}

/* tooltips: one element, drawn off whichever icon-only control is
   hovered — the native title arrives a second late in the OS's look */
function wireTips() {
  const gs = $('gs');
  const tip = $('gstip');
  gs.addEventListener('mouseover', e => {
    const b = e.target.closest && e.target.closest('[title], [data-tip]');
    if (!b || !gs.contains(b)) return;
    if (b.hasAttribute('title')) { b.dataset.tip = b.getAttribute('title'); b.removeAttribute('title'); }
    const r = b.getBoundingClientRect();
    const host = gs.getBoundingClientRect();
    tip.textContent = b.dataset.tip;
    tip.hidden = false;
    tip.style.left = (r.left + r.width / 2 - host.left) + 'px';
    tip.style.top = (r.top - host.top - 8) + 'px';
  });
  gs.addEventListener('mouseout', e => {
    const to = e.relatedTarget;
    if (to && to.closest && to.closest('[data-tip]')) return;
    tip.hidden = true;
  });
}

/* ── boot ── */

export function initWorkflows() {
  if (wired) return;
  wired = true;

  wireCanvas();
  wireBar();
  wirePalette();
  wireTips();

  $('gszoomin').onclick = () => zoomAt(1.15);
  $('gszoomout').onclick = () => zoomAt(1 / 1.15);
  $('wffit').onclick = fitView;
  $('gsframe').onclick = fitView;
  document.querySelectorAll('.gstool[data-tool]').forEach(b => b.onclick = () => setTool(b.dataset.tool));
  $('gsiclose').onclick = () => select(null);
  $('sendqueue').onclick = sendToQueue;
  $('gsisend').onclick = sendToQueue;

  $('wfsave').onclick = () => saveWorkflow();
  $('wfnew').onclick = newWorkflow;
  $('wfdel').onclick = deleteWorkflow;
  $('wfrunall').onclick = runAll;
  $('wfpick').onchange = () => {
    const id = Number($('wfpick').value);
    if (id) openWorkflow(id);
  };

  $('wfmclose').onclick = closeWorkflowModal;
  $('wfmcancel').onclick = closeWorkflowModal;
  $('wfmsave').onclick = applyModal;
  $('dscrim').addEventListener('click', closeWorkflowModal);

  loadPresets().then(p => { presets = p; });

  // the Director landing composer
  wireMentions($('dirbrief'), $('dirmentions'));
  $('dirbrief').addEventListener('input', () => { briefTouched = true; planOverride = null; });
  $('dirgo').onclick = () => (planOverride ? planOverride() : submitLandingBrief());
  $('wfback').onclick = () => {
    canvasOpen = false;
    planOverride = null;
    landingRequested = true;
    renderDirectorTab();
  };
  $('wfsaveconcept').onclick = saveToConcept;

  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => { fitWhenSized(); paintMini(); }).observe($('gscanvas'));
  }

  bus.addEventListener('job', e => {
    const job = e.detail;
    if (nodeJobs.has(job.id)) {
      const node = G.nodes.get(nodeJobs.get(job.id));
      if (node) {
        if (['queued', 'running'].includes(job.status)) {
          runProgress = job.progress || 0;
          if (node.type === 'zpf/generate') paintOutput(node); else paintNode(node);
        } else if (job.status === 'done') {
          nodeJobs.delete(job.id);
          node._out = job.output ?? '';
          setNodeState(node, 'done');
          maybeAttachShotOutput(node);
        } else if (['failed', 'cancelled'].includes(job.status)) {
          nodeJobs.delete(job.id);
          setNodeState(node, 'failed', job.error || job.status);
        }
      }
    }
    if (job.id === runAllJobId) {
      runProgress = job.progress || 0;
      applyNodeStates(job.node_states);
      if (['done', 'failed', 'cancelled'].includes(job.status)) {
        runAllJobId = null;
        $('wfrunall').disabled = false;
        if (directorConceptId && activeShotN !== null) {
          shotGraphs.set(activeShotN, serialize());
          saveShotGraph(activeShotN, job.node_states);
        }
        if (job.status === 'done') toast('empty', job.detail || 'Run complete');
        else toast('error', job.error || `Run ${job.status}`);
      }
    }
    if (job.id === landingJobId && ['done', 'failed'].includes(job.status)) {
      landingJobId = null;
      $('dirgo').disabled = false; $('dirgo').textContent = 'Build the scene';
      if (job.status === 'done' && job.ref_id) {
        stateline($('dirstate'), null);
        openConceptInDirector(job.ref_id);
      } else {
        stateline($('dirstate'), 'error', job.error || 'Generation failed');
      }
    }
  });
}

async function ensureDirectorView() {
  if (document.documentElement.dataset.v !== 'director') {
    (await import('./app.js')).go('director');
  }
}

/* ── the Director landing: chat-first entry, same engine as Create ── */

async function submitLandingBrief() {
  const text = $('dirbrief').value.trim();
  if (!text) return;
  const go = $('dirgo');
  go.disabled = true; go.textContent = 'Building…';
  try {
    const body = new FormData();
    body.append('prompt', text);
    const res = await api('/api/pipeline/run', { method: 'POST', body });
    landingJobId = res.job_id;
    stateline($('dirstate'), 'loading', 'Generating the scene — it opens on the canvas when the job finishes');
  } catch (e) {
    go.disabled = false; go.textContent = 'Build the scene';
    stateline($('dirstate'), 'error', e.message);
  }
}

async function renderLanding() {
  document.documentElement.dataset.gs = 'landing';
  $('dirlanding').hidden = false;
  $('dircanvas').hidden = true;
  let data;
  try {
    data = await api('/api/director/landing?brand=' + encodeURIComponent(state.brand));
  } catch { data = { sample_prompt: '', chips: [] }; }
  const brief = $('dirbrief');
  if (!briefTouched && !brief.value.trim() && data.sample_prompt) brief.value = data.sample_prompt;
  $('dirchips').innerHTML = (data.chips || []).map((c, i) =>
    `<button class="cat" data-i="${i}">Start a ${esc(c.label.replace(/^The /, ''))}</button>`).join('');
  $('dirchips').querySelectorAll('.cat').forEach(b => b.onclick = () => {
    brief.value = data.chips[+b.dataset.i].text;
    briefTouched = true;
    planOverride = null;
    brief.focus();
  });
  $('dirnote').textContent = data.chips.length ? 'a chip pre-fills its format — edit, then build' : '';
}

/* ── concept → canvas: ONE shot's chain at a time ── */

// group a shot's reference urls into reference-set nodes: one per
// asset (the url carries the category and the slug), uploads together
function groupRefs(refs, assets) {
  const groups = new Map();
  const nameFor = (category, slug) => {
    const hit = (assets && assets.items || []).find(a =>
      a.category === category && (a.photos || []).some(p => p.includes(`/${slug}/`)));
    return hit ? hit.name : slug.replace(/[-_]+/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
  };
  for (const url of refs || []) {
    if (typeof url !== 'string' || !url) continue;
    let m = url.match(/^\/(characters|locations|props)\/([^/]+)\//);
    let key, kind, label;
    if (m) {
      kind = m[1].slice(0, -1);
      key = `${kind}:${m[2]}`;
      label = nameFor(kind, m[2]);
    } else if (url.startsWith('/refs/')) {
      kind = 'upload'; key = 'upload'; label = 'Composer uploads';
    } else {
      kind = 'web'; key = 'web'; label = 'Scouted frames';
    }
    if (!groups.has(key)) groups.set(key, { kind, label, urls: [] });
    groups.get(key).urls.push(url);
  }
  return [...groups.values()];
}

function estSetHeight(set) {
  const cols = set.kind === 'location' ? 2 : 3;
  const cellW = (360 - 24 - (cols - 1) * 6) / cols;
  const cellH = set.kind === 'location' ? cellW * 0.75 : cellW;
  const rows = Math.ceil(set.urls.length / cols);
  return HEAD + 24 + rows * cellH + (rows - 1) * 6 + 44;
}

async function shotChainGraph(d, s) {
  // The shot's short prompt → Instructions → Gemini 2.5 Flash → Nano
  // keyframe → video clip, with the scene's reference sets as their
  // own cards wired into the three billed nodes' `refs` port. The
  // User Prompt seeds from what the GENERATOR wrote (written_prompt),
  // never the enhanced text, or Run would enhance an enhanced prompt.
  const text = s.written_prompt || s.prompt || s.desc || '';
  seededTexts.set(`${d.id}·${s.n}`, text);
  let assets = null;
  try { assets = await loadAssets(); } catch { /* slugs stand in for names */ }
  const sets = groupRefs(s.refs || [], assets);
  const refs = [...(s.refs || [])];
  const shot = { concept_id: d.id, shot_n: s.n };

  G = newGraph();
  const prompt = makeNode('zpf/user_prompt', { title: `Shot ${s.n} · prompt`, pos: [0, 0],
    properties: { text, ...shot } });
  const instr = makeNode('zpf/system_prompt', { title: 'Instructions', pos: [0, 352],
    properties: { text: enhanceSystem } });
  let y = 0;
  const setNodes = sets.map(set => {
    const node = makeNode('zpf/reference_set', { pos: [400, y], properties: { kind: set.kind, label: set.label, urls: set.urls } });
    y += estSetHeight(set) + 24;
    return node;
  });
  const colX = sets.length ? 830 : 400;
  const enhance = makeNode('zpf/enhance', { title: 'Gemini 2.5 Flash', pos: [colX, 0],
    properties: { auto_ground: true, ref_urls: refs, image_url: s.reference_image || '' } });
  const nano = makeNode('zpf/nano_banana', { title: 'Nano Banana', pos: [colX, 330],
    properties: { ...shot, ref_urls: refs, image_url: s.reference_image || '' } });
  const gen = makeNode('zpf/generate', { title: 'Video clip', pos: [colX + 430, 40],
    properties: { ...shot, ref_urls: refs, image_url: s.reference_image || '',
                  out_pos: [colX + 430, 350] } });
  connect(prompt, 0, enhance, 1);
  connect(instr, 0, enhance, 0);
  connect(enhance, 0, nano, 0);
  connect(enhance, 0, gen, 0);
  connect(nano, 0, gen, 1);
  for (const setNode of setNodes) {
    for (const target of [enhance, nano, gen]) {
      connect(setNode, 0, target, target.inputs.findIndex(i => i.name === 'refs'));
    }
  }
  return serialize();
}

function renderShotDock() {
  const dock = $('shotdock');
  if (!directorConcept || directorConcept.shots.length < 2) { dock.hidden = true; dock.innerHTML = ''; return; }
  dock.hidden = false;
  let lastScene;
  const bits = [];
  for (const s of directorConcept.shots) {
    const scene = s.scene_title ? `Scene ${s.scene_n ?? '?'} · ${s.scene_title}` : '';
    if (scene && scene !== lastScene) { bits.push(`<span class="dockscene">${esc(scene)}</span>`); lastScene = scene; }
    bits.push(`<button class="dockshot${s.n === activeShotN ? ' on' : ''}" data-n="${s.n}">Shot ${esc(String(s.n))}${s.media_url ? ' <i class="dot">●</i>' : ''}</button>`);
  }
  dock.innerHTML = bits.join('');
  dock.querySelectorAll('.dockshot').forEach(b => b.onclick = () => activateShot(+b.dataset.n));
}

async function activateShot(n) {
  if (!directorConcept) return;
  const shot = directorConcept.shots.find(s => s.n === n);
  if (!shot) return;
  if (activeShotN !== null && G.nodes.size) {
    freezeRefs();
    shotGraphs.set(activeShotN, serialize());
    saveShotGraph(activeShotN);
  }
  activeShotN = n;
  // in-session edits win; then the canvas saved on this shot's last
  // visit; only then a fresh chain built from the shot
  let serialized = shotGraphs.get(n);
  let states = null;
  if (!serialized) {
    const saved = await loadShotGraph(n);
    if (saved && saved.graph && (saved.graph.nodes || []).length) {
      serialized = saved.graph;
      states = saved.states;
    }
  }
  configure(serialized || await shotChainGraph(directorConcept, shot));
  clearRunState();
  sel = null;
  if (states) applyNodeStates(states, { quiet: true });
  mountNodes();
  paintInspector();
  renderShotDock();
  pendingFit = true;
  fitWhenSized();
}

async function saveShotGraph(n, states) {
  if (!directorConceptId || n === null || n === undefined) return;
  const serialized = shotGraphs.get(n) || (G.nodes.size ? serialize() : null);
  if (!serialized || !(serialized.nodes || []).length) return;
  try {
    await api(`/api/concepts/${directorConceptId}/shots/${n}/graph`, {
      method: 'PUT',
      body: { graph: serialized, states: states || null, name: directorConcept ? directorConcept.title : null },
    });
    $('wfsaved').textContent = 'Saved just now';
  } catch { /* the drawing is not the deliverable */ }
}

async function loadShotGraph(n) {
  if (!directorConceptId) return null;
  try {
    return await api(`/api/concepts/${directorConceptId}/shots/${n}/graph`);
  } catch {
    return null;
  }
}

export async function openConceptInDirector(id) {
  let d;
  try {
    d = await api(`/api/concepts/${id}`);
  } catch (e) {
    await ensureDirectorView();
    stateline($('dirstate'), 'error', `Could not open concept: ${e.message}`);
    return;
  }
  // The React Director (web/, its own Fly app) is where a planned
  // concept opens when the shell knows its address -- DIRECTOR_FRONTEND_URL
  // on the body -- unless ?legacy=1 asks for this canvas explicitly.
  const reactDirector = document.body.dataset.directorUrl;
  if ((d.shots || []).length && reactDirector
      && new URLSearchParams(location.search).get('legacy') !== '1') {
    const destination = new URL(reactDirector, location.origin);
    destination.searchParams.set('concept', id);
    destination.searchParams.set('shot', d.shots[0].n);
    location.assign(destination.href);
    return;
  }
  if (!(d.shots || []).length) {
    canvasOpen = false;
    landingRequested = true;
    await ensureDirectorView();
    renderLanding();
    briefTouched = true;
    $('dirbrief').value = [d.title, d.logline || d.hook || ''].filter(Boolean).join(' — ');
    stateline($('dirstate'), 'empty',
      `${d.n} · "${d.title}" has no shot plan yet — Build the scene plans its shots, then it opens here`);
    const go = $('dirgo');
    planOverride = async () => {
      go.disabled = true; go.textContent = 'Planning…';
      try {
        await api(`/api/concepts/${id}/approve`, { method: 'POST', body: {} });
        const watch = e2 => {
          const job = e2.detail;
          if (job.ref_id === id && job.kind === 'plan' && ['done', 'failed'].includes(job.status)) {
            bus.removeEventListener('job', watch);
            go.disabled = false; go.textContent = 'Build the scene';
            planOverride = null;
            if (job.status === 'done') openConceptInDirector(id);
            else stateline($('dirstate'), 'error', job.error || 'Planning failed');
          }
        };
        bus.addEventListener('job', watch);
        stateline($('dirstate'), 'loading', 'Planning the shot list…');
      } catch (e) {
        go.disabled = false; go.textContent = 'Build the scene';
        planOverride = null;
        stateline($('dirstate'), 'error', e.message);
      }
    };
    return;
  }

  currentId = null;
  $('wfpick').value = '';
  $('wfname').value = d.title;
  attached.clear();
  enhanceSystem = await enhanceSystemText();
  directorConcept = d;
  activeShotN = null;
  shotGraphs.clear();
  setConceptScope(d);
  canvasOpen = true;
  landingRequested = false;
  await ensureDirectorView();
  showCanvas();
  await activateShot(d.shots[0].n);
  toast(null);
}

async function saveToConcept() {
  if (!directorConceptId || !directorConcept) return;
  if (activeShotN !== null && G.nodes.size) shotGraphs.set(activeShotN, serialize());
  const btn = $('wfsaveconcept');
  btn.disabled = true;
  let saved = 0, warnings = 0;
  try {
    for (const [n, serialized] of shotGraphs) {
      const promptEl = (serialized.nodes || []).find(node =>
        node.type === 'zpf/user_prompt' && node.properties && node.properties.shot_n === n);
      if (!promptEl) continue;
      const text = (promptEl.properties.text || '').trim();
      if (!text || text === seededTexts.get(`${directorConceptId}·${n}`)) continue;
      const res = await api(`/api/concepts/${directorConceptId}/shots/${n}/prompt`,
        { method: 'POST', body: { prompt: text } });
      seededTexts.set(`${directorConceptId}·${n}`, text);
      saved += 1;
      warnings = (res.warnings || []).length;
    }
    if (saved) $('wfsaved').textContent = 'Saved just now';
    toast('empty', saved
      ? `Saved ${saved} shot prompt(s) to the concept${warnings ? ` · ${warnings} warning(s)` : ''}`
      : 'No edits to save — the shots are as loaded');
  } catch (e) {
    toast('error', `Save to concept failed: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

export async function renderDirectorTab() {
  if (!wired) return;
  if (canvasOpen) {
    document.documentElement.dataset.gs = 'canvas';
    $('dirlanding').hidden = true;
    $('dircanvas').hidden = false;
    requestAnimationFrame(() => { layout(); if (pendingFit) fitWhenSized(); });
    await loadList();
    return;
  }
  // arrival is the NODES, never a composer: open the newest planned
  // concept's scene graph; the brief is the fallback or an explicit ← away
  if (!landingRequested) {
    try {
      const data = await api(`/api/pipeline/concepts?brand=${encodeURIComponent(state.brand)}`);
      const planned = data.items.find(c => c.status !== 'idea');
      if (planned) { await openConceptInDirector(planned.id); return; }
    } catch { /* fall through to the landing */ }
  }
  await Promise.all([renderLanding(), loadList()]);
}

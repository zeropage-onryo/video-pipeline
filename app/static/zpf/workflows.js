/* Workflows view: a real node-graph editor (LiteGraph, vendored) for
   wiring custom generation pipelines — prompts → grounding/enhance →
   generate — the Runway-workflows shape. Each node type maps onto a
   backend that already exists (reference_block, Gemini via
   generate_with_retry, nano_banana.generate_from_prompt for images,
   runway.generate_from_prompt for video). Per-node Run calls the exec
   endpoints; Run all saves, then executes server-side in topological
   order, and the canvas lights nodes up from the same jobs SSE feed
   everything else uses. A Runway render sits behind the module's own
   spend gate (RUNWAY_SPEND_OK) — this canvas cannot spend around it;
   Nano Banana rides the already-billed Gemini key under NANO_DAILY_CAP.
   The view opens onto the newest saved graph (the seeded "Prompt
   enhancement" template on a fresh DB), never a blank grid. */
import { api, bus, esc, state, stateline } from './shared.js';

const LG = window.LiteGraph;

const PORT = { text: '#4c9a6c', image: '#5a8fd6', media: '#E4002B' };
const STATE_BOX = { idle: '#55534f', running: '#E4002B', done: '#2f7d4f', failed: '#c9a227' };

let graph = null;
let canvas = null;
let currentId = null;          // the saved workflow row this canvas edits
let runAllJobId = null;
const nodeJobs = new Map();    // job id -> node id, for per-node runs
let wired = false;

const $ = id => document.getElementById(id);

/* ── node value plumbing (client side, for per-node Run) ── */

const PURE = new Set(['zpf/system_prompt', 'zpf/user_prompt', 'zpf/reference_image']);

function nodeValue(node) {
  if (node._out !== undefined && node._out !== null) return node._out;
  if (node.type === 'zpf/reference_image') return node.properties.url || '';
  if (PURE.has(node.type)) return node.properties.text || '';
  return null;
}

function inputVal(node, name) {
  const idx = (node.inputs || []).findIndex(i => i.name === name);
  if (idx < 0) return null;
  const src = node.getInputNode(idx);
  return src ? nodeValue(src) : null;
}

function setNodeState(node, st, note) {
  node._state = st;
  node.boxcolor = STATE_BOX[st] || STATE_BOX.idle;
  if (note !== undefined) node._note = note;
  if (canvas) canvas.setDirty(true, true);
}

/* ── drawing: wrapped text previews on the node body, like the
   reference screenshot's prompt cards ── */

function wrapLines(text, maxChars, maxLines) {
  const words = String(text).replace(/\s+/g, ' ').trim().split(' ');
  const lines = [];
  let line = '';
  for (const w of words) {
    if ((line + ' ' + w).trim().length > maxChars) {
      lines.push(line.trim());
      line = w;
      if (lines.length >= maxLines) { lines[maxLines - 1] += '…'; return lines; }
    } else {
      line = (line + ' ' + w).trim();
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, maxLines);
}

function drawBody(node, ctx, lines, color) {
  const top = 8 + (node.widgets ? node.widgets.length : 0) * 24 + 16;
  ctx.font = '11px "JetBrains Mono", monospace';
  ctx.fillStyle = color;
  lines.forEach((l, i) => ctx.fillText(l, 12, top + i * 15, node.size[0] - 24));
}

function previewDrawer(placeholder) {
  return function(ctx) {
    if (this.flags.collapsed) return;
    const failed = this._state === 'failed';
    const shown = failed ? ('✕ ' + (this._note || 'failed'))
      : this._out != null && this._out !== '' ? this._out
      : (this.properties.text || this.properties.url || '');
    const dim = !shown;
    const lines = wrapLines(shown || placeholder, Math.floor(this.size[0] / 7), 7);
    drawBody(this, ctx, lines,
      failed ? '#c9a227' : this._out != null && this._out !== '' ? '#f4f3f2' : dim ? '#55534f' : '#8e8c8a');
  };
}

/* thumbnails for the Reference Image node */
const thumbCache = new Map();
function thumbFor(url) {
  if (!url) return null;
  if (!thumbCache.has(url)) {
    const img = new Image();
    img.src = url;
    img.onload = () => canvas && canvas.setDirty(true, true);
    thumbCache.set(url, img);
  }
  const img = thumbCache.get(url);
  return img && img.complete && img.naturalWidth ? img : null;
}

/* ── the modal editor (text nodes + reference-image picker + output
   viewer). Reuses the deny-screen styling; #dscrim is the shared
   scrim. ── */

let modal = { node: null, mode: null };

function openModal(node, mode) {
  modal = { node, mode };
  $('wfmtitle').textContent = node.title + (mode === 'view' ? ' · output' : '');
  const textwrap = $('wfmtextwrap');
  const mediawrap = $('wfmmediawrap');
  const isMedia = mode === 'media';
  textwrap.hidden = isMedia;
  mediawrap.hidden = !isMedia;
  $('wfmsave').hidden = mode === 'view';
  $('wfmmeta').textContent = '';
  if (mode === 'text') {
    $('wfmlabel').textContent = node.type === 'zpf/ground'
      ? 'Fallback spark — used when the spark port is unconnected' : 'Text';
    $('wfmtext').value = node.properties.text || '';
    $('wfmtext').readOnly = false;
  } else if (mode === 'view') {
    $('wfmlabel').textContent = 'Output';
    $('wfmtext').value = node._out ?? node._note ?? '';
    $('wfmtext').readOnly = true;
  } else if (isMedia) {
    $('wfmurl').value = node.properties.url || '';
    renderModalMedia();
  }
  $('dscrim').setAttribute('data-open', '');
  $('wfmodal').setAttribute('data-open', '');
  if (mode === 'text') setTimeout(() => $('wfmtext').focus(), 40);
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
    grid.innerHTML = '<div class="probeblank">No saved media yet — photos added on /assets appear here</div>';
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
    grid.querySelectorAll('.mtile').forEach(t =>
      t.setAttribute('aria-pressed', String(t === tile)));
  });
}

function applyModal() {
  const { node, mode } = modal;
  if (node && mode === 'text') {
    node.properties.text = $('wfmtext').value;
    node._out = null;
    setNodeState(node, 'idle');
  } else if (node && mode === 'media') {
    node.properties.url = $('wfmurl').value.trim();
    node._out = null;
    setNodeState(node, 'idle');
  }
  closeWorkflowModal();
}

/* ── per-node Run ── */

async function runNode(node) {
  try {
    if (node.type === 'zpf/ground') {
      setNodeState(node, 'running');
      const res = await api('/api/workflows/exec/ground', {
        method: 'POST',
        body: { spark: inputVal(node, 'spark') || node.properties.text || '' },
      });
      node._out = res.references;
      setNodeState(node, 'done',
        res.references ? '' : 'no references — library empty or store down');
    } else if (node.type === 'zpf/enhance') {
      setNodeState(node, 'running');
      const image = inputVal(node, 'image');
      const res = await api('/api/workflows/exec/enhance', {
        method: 'POST',
        body: {
          system: inputVal(node, 'system') || '',
          user: inputVal(node, 'user') || '',
          images: image ? [image] : [],
        },
      });
      nodeJobs.set(res.job_id, node.id);
    } else if (node.type === 'zpf/generate') {
      setNodeState(node, 'running');
      const res = await api('/api/workflows/exec/generate', {
        method: 'POST',
        body: { prompt: inputVal(node, 'prompt') || '',
                image: inputVal(node, 'image') || null },
      });
      nodeJobs.set(res.job_id, node.id);
    } else if (node.type === 'zpf/nano_banana') {
      setNodeState(node, 'running');
      const res = await api('/api/workflows/exec/nano', {
        method: 'POST',
        body: { prompt: inputVal(node, 'prompt') || '',
                image: inputVal(node, 'image') || null },
      });
      nodeJobs.set(res.job_id, node.id);
    }
  } catch (e) {
    setNodeState(node, 'failed', e.message);
  }
}

/* ── node type definitions ── */

function registerNodes() {
  // only the five v1 types in the add menu — the stock library would
  // drown them
  if (LG.clearRegisteredTypes) LG.clearRegisteredTypes();

  function textNode(self, placeholder) {
    self.addOutput('text', 'text');
    self.properties = { text: '' };
    self.size = [260, 170];
    self.addWidget('button', '✎ Edit text', null, () => openModal(self, 'text'));
    self.onDrawForeground = previewDrawer(placeholder);
    self.onDblClick = () => openModal(self, 'text');
  }

  function SystemPrompt() {
    textNode(this, 'Instructions for how the model should behave…');
  }
  SystemPrompt.title = 'System Prompt';

  function UserPrompt() {
    textNode(this, 'The prompt to enhance or render…');
    // opened from the Studio composer with something typed? start there
    const composer = document.getElementById('prompt');
    if (composer && composer.value.trim()) this.properties.text = composer.value.trim();
  }
  UserPrompt.title = 'User Prompt';

  function ReferenceImage() {
    this.addOutput('image', 'image');
    this.properties = { url: '' };
    this.size = [240, 190];
    const self = this;
    this.addWidget('button', '🖼 Pick image', null, () => openModal(self, 'media'));
    this.onDblClick = () => openModal(self, 'media');
    this.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      const url = this.properties.url;
      const top = 8 + this.widgets.length * 24 + 8;
      if (!url) {
        drawBody(this, ctx, ['no image picked'], '#55534f');
        return;
      }
      const img = thumbFor(url);
      if (img) {
        const h = this.size[1] - top - 26;
        const w = this.size[0] - 24;
        const scale = Math.min(w / img.naturalWidth, h / img.naturalHeight);
        ctx.drawImage(img, 12, top, img.naturalWidth * scale, img.naturalHeight * scale);
      }
      ctx.font = '9px "JetBrains Mono", monospace';
      ctx.fillStyle = '#8e8c8a';
      ctx.fillText(url.split('/').pop().split('?')[0], 12, this.size[1] - 8, this.size[0] - 24);
    };
  }
  ReferenceImage.title = 'Reference Image';

  function Ground() {
    this.addInput('spark', 'text');
    this.addOutput('references', 'text');
    this.properties = { text: '' };
    this.size = [260, 170];
    const self = this;
    this.addWidget('button', '▶ Run', null, () => runNode(self));
    this.addWidget('button', '✎ Fallback spark', null, () => openModal(self, 'text'));
    this.addWidget('button', '👁 View output', null, () => openModal(self, 'view'));
    this.onDrawForeground = previewDrawer('Retrieves reference-library grounding for the spark');
    this.onDblClick = () => openModal(self, 'view');
  }
  Ground.title = 'Ground in References';

  function Enhance() {
    this.addInput('system', 'text');
    this.addInput('user', 'text');
    this.addInput('image', 'image');
    this.addOutput('text', 'text');
    this.properties = {};
    this.size = [280, 190];
    const self = this;
    this.addWidget('button', '▶ Run', null, () => runNode(self));
    this.addWidget('button', '👁 View output', null, () => openModal(self, 'view'));
    this.onDrawForeground = previewDrawer('Gemini — expands the wired prompts into one detailed prompt');
    this.onDblClick = () => openModal(self, 'view');
  }
  Enhance.title = 'LLM Enhance';

  function Generate() {
    this.addInput('prompt', 'text');
    this.addInput('image', 'image');
    this.addOutput('media', 'media');
    this.properties = {};
    this.size = [280, 190];
    const self = this;
    this.addWidget('button', '▶ Run · billed', null, () => runNode(self));
    this.addWidget('button', '👁 View output', null, () => openModal(self, 'view'));
    this.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      const gate = state.caps['runway.generate']
        ? (state.caps['runway.spend'] ? 'runway · spend approved'
                                      : 'runway · gated — RUNWAY_SPEND_OK=1 to arm')
        : 'runway · RUNWAYML_API_SECRET not set';
      const shown = this._state === 'failed' ? ('✕ ' + (this._note || 'failed'))
        : this._out ? this._out : gate;
      drawBody(this, ctx, wrapLines(shown, Math.floor(this.size[0] / 7), 6),
        this._state === 'failed' ? '#c9a227' : this._out ? '#f4f3f2' : '#55534f');
    };
    this.onDblClick = () => {
      if (this._out) window.open(this._out, '_blank');
      else openModal(self, 'view');
    };
  }
  Generate.title = 'Generate';

  function NanoBanana() {
    this.addInput('prompt', 'text');
    this.addInput('image', 'image');
    this.addOutput('image', 'image');
    this.properties = {};
    this.size = [300, 260];
    const self = this;
    this.addWidget('button', '▶ Run · billed', null, () => runNode(self));
    this.addWidget('button', '👁 View output', null, () => openModal(self, 'view'));
    this.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      const top = 8 + this.widgets.length * 24 + 8;
      if (this._out && this._state !== 'failed') {
        const img = thumbFor(this._out);
        if (img) {
          const h = this.size[1] - top - 12;
          const w = this.size[0] - 24;
          const scale = Math.min(w / img.naturalWidth, h / img.naturalHeight);
          ctx.drawImage(img, 12, top, img.naturalWidth * scale, img.naturalHeight * scale);
        } else {
          drawBody(this, ctx, ['loading preview…'], '#8e8c8a');
        }
        return;
      }
      const gate = state.caps['nano.generate']
        ? 'gemini image — output will appear here'
        : 'GEMINI_API_KEY not set';
      const shown = this._state === 'failed' ? ('✕ ' + (this._note || 'failed')) : gate;
      drawBody(this, ctx, wrapLines(shown, Math.floor(this.size[0] / 7), 6),
        this._state === 'failed' ? '#c9a227' : '#55534f');
    };
    this.onDblClick = () => {
      if (this._out) window.open(this._out, '_blank');
      else openModal(self, 'view');
    };
  }
  NanoBanana.title = 'Nano Banana';

  LG.registerNodeType('zpf/system_prompt', SystemPrompt);
  LG.registerNodeType('zpf/user_prompt', UserPrompt);
  LG.registerNodeType('zpf/reference_image', ReferenceImage);
  LG.registerNodeType('zpf/ground', Ground);
  LG.registerNodeType('zpf/enhance', Enhance);
  LG.registerNodeType('zpf/generate', Generate);
  LG.registerNodeType('zpf/nano_banana', NanoBanana);
}

/* ── theming: the zpf palette instead of LiteGraph's default look ── */

function theme() {
  LG.NODE_DEFAULT_COLOR = '#151518';
  LG.NODE_DEFAULT_BGCOLOR = '#0c0c0f';
  LG.NODE_DEFAULT_BOXCOLOR = '#55534f';
  LG.NODE_TITLE_COLOR = '#f4f3f2';
  LG.NODE_SELECTED_TITLE_COLOR = '#ffffff';
  LG.NODE_TEXT_COLOR = '#8e8c8a';
  LG.NODE_DEFAULT_SHAPE = 'box';
  LG.WIDGET_BGCOLOR = '#17171b';
  LG.WIDGET_OUTLINE_COLOR = '#2a2a2e';
  LG.WIDGET_TEXT_COLOR = '#f4f3f2';
  LG.WIDGET_SECONDARY_TEXT_COLOR = '#8e8c8a';
  window.LGraphCanvas.link_type_colors = Object.assign(
    {}, window.LGraphCanvas.link_type_colors, PORT);
}

function themeCanvas(c) {
  c.clear_background_color = '#050506';
  c.background_image = null;
  c.show_info = false;
  c.render_shadows = false;
  c.render_connection_arrows = false;
  c.connections_width = 2;
  c.default_connection_color_byType = Object.assign({}, PORT);
  c.default_connection_color_byTypeOff = Object.assign({}, PORT);
  c.highquality_render = true;
}

/* ── save / load / run all ── */

function wfStateline(kind, message, retry) {
  stateline($('wfstate'), kind, message, retry);
}

function clearRunState() {
  if (!graph) return;
  for (const node of graph._nodes || []) {
    node._out = null;
    node._note = '';
    setNodeState(node, 'idle');
  }
}

async function saveWorkflow(quiet = false) {
  const name = $('wfname').value.trim() || 'Untitled workflow';
  const body = { name, graph: graph.serialize() };
  try {
    if (currentId) {
      await api(`/api/workflows/${currentId}`, { method: 'PUT', body });
    } else {
      body.brand = state.brand;
      const res = await api('/api/workflows', { method: 'POST', body });
      currentId = res.id;
    }
  } catch (e) {
    wfStateline('error', `Save failed: ${e.message}`);
    throw e;
  }
  if (!quiet) wfStateline('empty', `Saved "${name}"`);
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

async function openWorkflow(id) {
  let w;
  try {
    w = await api(`/api/workflows/${id}`);
  } catch (e) {
    wfStateline('error', `Could not open: ${e.message}`);
    return;
  }
  currentId = w.id;
  $('wfname').value = w.name;
  graph.clear();
  if (w.graph && w.graph.nodes) graph.configure(w.graph);
  clearRunState();
  wfStateline(null);
  canvas.setDirty(true, true);
}

function newWorkflow() {
  currentId = null;
  $('wfname').value = '';
  graph.clear();
  $('wfpick').value = '';
  wfStateline(null);
  canvas.setDirty(true, true);
}

async function deleteWorkflow() {
  if (!currentId) { newWorkflow(); return; }
  try {
    await api(`/api/workflows/${currentId}`, { method: 'DELETE' });
  } catch (e) {
    wfStateline('error', `Delete failed: ${e.message}`);
    return;
  }
  newWorkflow();
  await loadList();
}

async function runAll() {
  if (!(graph._nodes || []).length) {
    wfStateline('empty', 'Nothing to run — add nodes first');
    return;
  }
  const btn = $('wfrunall');
  btn.disabled = true;
  try {
    await saveWorkflow(true);                      // run executes the SAVED graph
    clearRunState();
    const res = await api(`/api/workflows/${currentId}/run`, { method: 'POST', body: {} });
    runAllJobId = res.job_id;
    wfStateline('loading', 'Running…');
  } catch (e) {
    wfStateline('error', `Run failed: ${e.message}`);
    btn.disabled = false;
  }
}

function applyNodeStates(states) {
  if (!states || !graph) return;
  for (const [id, s] of Object.entries(states)) {
    const node = graph.getNodeById(Number(id));
    if (!node) continue;
    if (s.status === 'done') node._out = s.output;
    setNodeState(node,
      s.status === 'running' ? 'running'
        : s.status === 'done' ? 'done'
        : s.status === 'failed' ? 'failed' : 'idle',
      s.error || '');
    if (s.status === 'skipped') { node.boxcolor = '#2a2a2e'; node._note = s.error || 'skipped'; }
  }
  canvas.setDirty(true, true);
}

/* ── boot ── */

function resizeCanvas() {
  const el = $('wfcanvas');
  const rect = el.getBoundingClientRect();
  if (rect.width && rect.height) canvas.resize(rect.width, rect.height);
}

export function initWorkflows() {
  if (wired) return;
  wired = true;
  if (!LG) {
    wfStateline('error', 'LiteGraph failed to load — check /static/zpf/vendor/litegraph.js');
    return;
  }
  theme();
  registerNodes();
  graph = new window.LGraph();
  canvas = new window.LGraphCanvas('#wfcanvas', graph);
  canvas.allow_searchbox = true;
  themeCanvas(canvas);

  $('wfsave').onclick = () => saveWorkflow();
  $('wfnew').onclick = newWorkflow;
  $('wfdel').onclick = deleteWorkflow;
  $('wfrunall').onclick = runAll;
  $('wfpick').onchange = () => {
    const id = Number($('wfpick').value);
    if (id) openWorkflow(id);
  };
  $('wfadd').onchange = () => {
    const type = $('wfadd').value;
    $('wfadd').value = '';
    if (!type) return;
    const node = LG.createNode(type);
    if (!node) return;
    // drop it near the centre of the current view
    const rect = $('wfcanvas').getBoundingClientRect();
    node.pos = canvas.convertCanvasToOffset([rect.width / 2 - 130, rect.height / 2 - 80]);
    graph.add(node);
    canvas.setDirty(true, true);
  };

  $('wfmclose').onclick = closeWorkflowModal;
  $('wfmcancel').onclick = closeWorkflowModal;
  $('wfmsave').onclick = applyModal;
  $('dscrim').addEventListener('click', closeWorkflowModal);

  bus.addEventListener('job', e => {
    const job = e.detail;
    if (nodeJobs.has(job.id)) {
      const node = graph.getNodeById(nodeJobs.get(job.id));
      if (node) {
        if (job.status === 'done') {
          nodeJobs.delete(job.id);
          node._out = job.output ?? '';
          setNodeState(node, 'done');
        } else if (['failed', 'cancelled'].includes(job.status)) {
          nodeJobs.delete(job.id);
          setNodeState(node, 'failed', job.error || job.status);
        }
      }
    }
    if (job.id === runAllJobId) {
      applyNodeStates(job.node_states);
      if (['done', 'failed', 'cancelled'].includes(job.status)) {
        runAllJobId = null;
        $('wfrunall').disabled = false;
        if (job.status === 'done') wfStateline('empty', job.detail || 'Run complete');
        else wfStateline('error', job.error || `Run ${job.status}`);
      }
    }
  });

  addEventListener('resize', () => {
    if (document.documentElement.dataset.v === 'workflows') resizeCanvas();
  });
}

export async function renderWorkflows() {
  if (!canvas) return;
  // the view was display:none until now — size the canvas to reality
  requestAnimationFrame(() => { resizeCanvas(); canvas.setDirty(true, true); });
  await loadList();
  // arrive on the typical workflow, not a blank grid: open the newest
  // saved graph (the seeded "Prompt enhancement" template on a fresh
  // DB) whenever nothing is on the canvas yet
  if (!currentId && !(graph._nodes || []).length) {
    const first = $('wfpick').querySelector('option[value]:not([value=""])');
    if (first) {
      $('wfpick').value = first.value;
      await openWorkflow(Number(first.value));
    }
  }
}

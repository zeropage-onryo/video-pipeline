/* Director mode — the Pipeline view's third tab, and what the old
   Workflows view actually was: a real node-graph editor (LiteGraph,
   vendored) whose point is a VISIBLE improvement pipeline — an idea
   starts as plain text in a User Prompt node and the graph downstream
   (Ground → Enhance → Generate) improves it step by step into a strong
   final prompt and render. Two ways in: the chat-first landing (a real
   pre-filled sample brief + quick-start format chips; submitting runs
   the same concept engine Concept tab uses and lands straight on the
   canvas) or opening any existing concept, which pre-loads one node
   chain per shot, grouped by scene, seeded with director_prompt()'s
   text. Edits save back onto the concept via update_concept_shots;
   a shot node's finished render attaches back onto its shot. Generic
   saved workflows (the seeded "Prompt enhancement" template) still
   open from the same toolbar. Every billed node stays behind its
   module's own gate (RUNWAY_SPEND_OK, NANO_DAILY_CAP) — this canvas
   cannot spend around them. */
import { api, bus, esc, fillPresetSelect, loadPresets, state, stateline, wireMentions } from './shared.js';

const LG = window.LiteGraph;

const PORT = { text: '#4c9a6c', image: '#5a8fd6', media: '#E4002B' };
const STATE_BOX = { idle: '#55534f', running: '#E4002B', done: '#2f7d4f', failed: '#c9a227' };

let graph = null;
let canvas = null;
let currentId = null;          // the saved workflow row this canvas edits
let runAllJobId = null;
const nodeJobs = new Map();    // job id -> node id, for per-node runs
let wired = false;

/* director-tab state */
let canvasOpen = false;        // false = the landing composer is showing
let directorConceptId = null;  // the concept this canvas is scoped to
let landingJobId = null;       // the landing brief's concept job
let briefTouched = false;      // don't overwrite what the person typed
let planOverride = null;       // "Build the scene" repurposed for the no-plan flow
let landingRequested = false;  // ← Brief was pressed: hold the landing, don't auto-reopen

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
  $('wfmpresetrow').hidden = mode !== 'text';
  if (mode === 'text') {
    $('wfmlabel').textContent = node.type === 'zpf/ground'
      ? 'Fallback spark — used when the spark port is unconnected' : 'Text';
    $('wfmtext').value = node.properties.text || '';
    $('wfmtext').readOnly = false;
    loadPresets().then(p => fillPresetSelect($('wfmpreset'), p));
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
          references: inputVal(node, 'references') || '',
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
    this.addInput('references', 'text');
    this.addOutput('text', 'text');
    this.properties = {};
    this.size = [280, 200];
    const self = this;
    this.addWidget('button', '▶ Run', null, () => runNode(self));
    this.addWidget('button', '👁 View output', null, () => openModal(self, 'view'));
    this.onDrawForeground = previewDrawer('Enhances your prompt with vivid details — references ground it');
    this.onDblClick = () => openModal(self, 'view');
  }
  Enhance.title = 'Gemini 2.5 Flash';

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

function setConceptScope(concept) {
  // concept: the /api/concepts/{id} payload, or null for a generic graph
  directorConceptId = concept ? concept.id : null;
  $('wfconcept').textContent = concept
    ? `${concept.n} · ${concept.shots.length} shot${concept.shots.length === 1 ? '' : 's'}`
    : '';
  $('wfsaveconcept').hidden = !concept;
  // concept mode keeps the toolbar clean: the workflow-library controls
  // (open/new/delete/save-as-workflow) only matter for generic graphs
  for (const id of ['wfpick', 'wfnew', 'wfdel', 'wfsave']) {
    $(id).hidden = !!concept;
  }
  if (!concept) {
    directorConcept = null;
    activeShotN = null;
    shotGraphs.clear();
  }
  renderShotDock();
}

function showCanvas() {
  canvasOpen = true;
  $('dirlanding').hidden = true;
  $('dircanvas').hidden = false;
  requestAnimationFrame(() => { resizeCanvas(); canvas.setDirty(true, true); });
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
  setConceptScope(null);
  showCanvas();
  wfStateline(null);
  canvas.setDirty(true, true);
}

function newWorkflow() {
  currentId = null;
  $('wfname').value = '';
  graph.clear();
  $('wfpick').value = '';
  setConceptScope(null);
  showCanvas();
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
    if (s.status === 'done') { node._out = s.output; maybeAttachShotOutput(node); }
    setNodeState(node,
      s.status === 'running' ? 'running'
        : s.status === 'done' ? 'done'
        : s.status === 'failed' ? 'failed' : 'idle',
      s.error || '');
    if (s.status === 'skipped') { node.boxcolor = '#2a2a2e'; node._note = s.error || 'skipped'; }
  }
  canvas.setDirty(true, true);
}

/* A shot-scoped node's finished render lands back on its shot: a
   Generate clip attaches as media_url, a Nano image as the shot's
   reference_image — regenerating one shot never touches the others.
   Relative /renders/ URLs become absolute so the media route's
   http(s) check accepts them. */
const attached = new Set();   // node.id + url, so re-renders don't re-post
function maybeAttachShotOutput(node) {
  const p = node.properties || {};
  if (!directorConceptId || !p.shot_n || !node._out) return;
  const key = `${node.id}·${node._out}`;
  if (attached.has(key)) return;
  attached.add(key);
  const url = new URL(node._out, location.origin).href;
  if (node.type === 'zpf/generate') {
    api(`/api/concepts/${directorConceptId}/shots/${p.shot_n}/media`,
      { method: 'POST', body: { url } })
      .then(() => {
        wfStateline('empty', `Clip attached to shot ${p.shot_n}`);
        const shot = directorConcept
          && directorConcept.shots.find(s => s.n === p.shot_n);
        if (shot) { shot.media_url = url; renderShotDock(); }
      })
      .catch(e => wfStateline('error', `Clip attach failed: ${e.message}`));
  } else if (node.type === 'zpf/nano_banana') {
    api(`/api/concepts/${directorConceptId}/shots/${p.shot_n}/reference`,
      { method: 'POST', body: { url } })
      .then(() => wfStateline('empty', `Image attached as shot ${p.shot_n}'s reference`))
      .catch(e => wfStateline('error', `Reference attach failed: ${e.message}`));
  }
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

  // the modal's preset picker + @ mentions — the same helpers the
  // Generate tab uses, available per-node
  $('wfmpreset').onchange = async () => {
    const id = $('wfmpreset').value;
    $('wfmpreset').value = '';
    if (!id) return;
    const preset = (await loadPresets()).find(p => p.id === id);
    if (!preset) return;
    const ta = $('wfmtext');
    ta.value = (ta.value.trim() ? ta.value.trim() + '\n\n' : '') + preset.how;
    ta.focus();
  };
  wireMentions($('wfmtext'), $('wfmmentions'));

  // the Director landing composer
  wireMentions($('dirbrief'), $('dirmentions'));
  // typing in the brief means "a fresh brief" — drop any no-plan override
  $('dirbrief').addEventListener('input', () => {
    briefTouched = true;
    planOverride = null;
  });
  $('dirgo').onclick = () => (planOverride ? planOverride() : submitLandingBrief());
  $('wfback').onclick = () => {
    canvasOpen = false;
    planOverride = null;
    landingRequested = true;    // an explicit ask for the brief — hold it
    renderDirectorTab();
  };
  $('wfsaveconcept').onclick = saveToConcept;

  bus.addEventListener('job', e => {
    const job = e.detail;
    if (nodeJobs.has(job.id)) {
      const node = graph.getNodeById(nodeJobs.get(job.id));
      if (node) {
        if (job.status === 'done') {
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
      applyNodeStates(job.node_states);
      if (['done', 'failed', 'cancelled'].includes(job.status)) {
        runAllJobId = null;
        $('wfrunall').disabled = false;
        if (job.status === 'done') wfStateline('empty', job.detail || 'Run complete');
        else wfStateline('error', job.error || `Run ${job.status}`);
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

  addEventListener('resize', () => {
    if (document.documentElement.dataset.v === 'director' && canvasOpen) resizeCanvas();
  });
}

/* Director is a top-level rail view now — make sure it's fronted. */
async function ensureDirectorView() {
  if (document.documentElement.dataset.v !== 'director') {
    (await import('./app.js')).go('director');
  }
}

/* ── the Director landing: chat-first entry, same engine as Concept ── */

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
    stateline($('dirstate'), 'loading',
      'Generating the scene — it opens on the canvas when the job finishes');
  } catch (e) {
    go.disabled = false; go.textContent = 'Build the scene';
    stateline($('dirstate'), 'error', e.message);
  }
}

async function renderLanding() {
  $('dirlanding').hidden = false;
  $('dircanvas').hidden = true;
  let data;
  try {
    data = await api('/api/director/landing?brand=' + encodeURIComponent(state.brand));
  } catch { data = { sample_prompt: '', chips: [] }; }
  const brief = $('dirbrief');
  if (!briefTouched && !brief.value.trim() && data.sample_prompt) {
    // a real, editable example brief — not placeholder ghost text
    brief.value = data.sample_prompt;
  }
  $('dirchips').innerHTML = (data.chips || []).map((c, i) =>
    `<button class="cat" data-i="${i}">Start a ${esc(c.label.replace(/^The /, ''))}</button>`).join('');
  $('dirchips').querySelectorAll('.cat').forEach(b => b.onclick = () => {
    brief.value = data.chips[+b.dataset.i].text;
    briefTouched = true;
    planOverride = null;
    brief.focus();
  });
  $('dirnote').textContent = data.chips.length
    ? 'a chip pre-fills its format — edit, then build' : '';
}

/* ── concept → canvas: ONE shot's chain at a time ──
   The canvas edits a single shot; every other shot sits in the dock
   under the canvas (the Runway-workflows shape Mike pointed at) and
   clicking one pulls its nodes up. Edits made to a shot are kept
   in-memory when switching (shotGraphs) and persist to the concept
   only through Save to concept. */

// what each shot node was seeded with, keyed "concept·shot" — Save to
// concept only writes nodes whose text actually changed, so opening a
// concept and saving untouched never rewrites the stored prompts with
// the composed director_prompt rendering
const seededTexts = new Map();

let directorConcept = null;    // the /api/concepts/{id} payload on the canvas
let activeShotN = null;        // which shot's chain is up right now
const shotGraphs = new Map();  // shot n -> serialized graph with local edits

function shotChainGraph(d, s) {
  // Hand-built in LiteGraph's own serialize() shape (the
  // default_template pattern): User Prompt (the editable start of the
  // idea — director_prompt()'s story-aware text) → Ground → Gemini 2.5
  // Flash (references grounding it, the vivid-details instruction as
  // its default system) → Generate, plus a Reference Image node when
  // the shot already carries one. One clean row per the reference
  // screenshot — each node takes what came in and makes it better.
  const hasRef = !!s.reference_image;
  const text = s.director_prompt || s.prompt || s.desc || '';
  seededTexts.set(`${d.id}·${s.n}`, text);

  const nodes = [
    { id: 1, type: 'zpf/user_prompt', title: `Shot ${s.n} · prompt`,
      pos: [40, 140], size: [300, 230], flags: {}, order: 0, mode: 0,
      outputs: [{ name: 'text', type: 'text', links: [1, 2] }],
      properties: { text, concept_id: d.id, shot_n: s.n } },
    { id: 2, type: 'zpf/ground', title: 'Ground in References',
      pos: [400, 140], size: [260, 170], flags: {}, order: 1, mode: 0,
      inputs: [{ name: 'spark', type: 'text', link: 1 }],
      outputs: [{ name: 'references', type: 'text', links: [3] }],
      properties: { text: '' } },
    { id: 3, type: 'zpf/enhance', title: 'Gemini 2.5 Flash',
      pos: [720, 140], size: [280, 200], flags: {}, order: 2, mode: 0,
      inputs: [{ name: 'system', type: 'text', link: null },
               { name: 'user', type: 'text', link: 2 },
               { name: 'image', type: 'image', link: hasRef ? 5 : null },
               { name: 'references', type: 'text', link: 3 }],
      outputs: [{ name: 'text', type: 'text', links: [4] }],
      properties: {} },
    { id: 4, type: 'zpf/generate', title: `Generate · shot ${s.n}`,
      pos: [1060, 140], size: [280, 190], flags: {}, order: 3, mode: 0,
      inputs: [{ name: 'prompt', type: 'text', link: 4 },
               { name: 'image', type: 'image', link: hasRef ? 6 : null }],
      outputs: [{ name: 'media', type: 'media', links: null }],
      properties: { concept_id: d.id, shot_n: s.n } },
  ];
  const links = [[1, 1, 0, 2, 0, 'text'],
                 [2, 1, 0, 3, 1, 'text'],
                 [3, 2, 0, 3, 3, 'text'],
                 [4, 3, 0, 4, 0, 'text']];
  if (hasRef) {
    nodes.push({ id: 5, type: 'zpf/reference_image',
      title: `Reference · shot ${s.n}`,
      pos: [400, 380], size: [240, 190], flags: {}, order: 0, mode: 0,
      outputs: [{ name: 'image', type: 'image', links: [5, 6] }],
      properties: { url: s.reference_image } });
    links.push([5, 5, 0, 3, 2, 'image'], [6, 5, 0, 4, 1, 'image']);
  }
  return { last_node_id: 6, last_link_id: 6, nodes, links,
           groups: [], config: {}, version: 0.4 };
}

function renderShotDock() {
  const dock = $('shotdock');
  if (!directorConcept) { dock.hidden = true; dock.innerHTML = ''; return; }
  dock.hidden = false;
  let lastScene;
  const bits = [];
  for (const s of directorConcept.shots) {
    const scene = s.scene_title
      ? `Scene ${s.scene_n ?? '?'} · ${s.scene_title}` : '';
    if (scene && scene !== lastScene) {
      bits.push(`<span class="dockscene">${esc(scene)}</span>`);
      lastScene = scene;
    }
    bits.push(`<button class="dockshot${s.n === activeShotN ? ' on' : ''}" data-n="${s.n}">
      Shot ${esc(String(s.n))}${s.media_url ? ' <i class="dot">●</i>' : ''}
    </button>`);
  }
  dock.innerHTML = bits.join('');
  dock.querySelectorAll('.dockshot').forEach(b =>
    b.onclick = () => activateShot(+b.dataset.n));
}

function activateShot(n) {
  if (!directorConcept) return;
  const shot = directorConcept.shots.find(s => s.n === n);
  if (!shot) return;
  // pocket the current shot's edits before switching — nothing is lost
  if (activeShotN !== null && graph) {
    shotGraphs.set(activeShotN, graph.serialize());
  }
  activeShotN = n;
  graph.clear();
  graph.configure(shotGraphs.get(n) || shotChainGraph(directorConcept, shot));
  clearRunState();
  renderShotDock();
  canvas.setDirty(true, true);
}

export async function openConceptInDirector(id) {
  // no approval gate: any concept opens directly — approval/teaching is
  // the dev console's ongoing background loop, never a checkpoint here
  let d;
  try {
    d = await api(`/api/concepts/${id}`);
  } catch (e) {
    await ensureDirectorView();
    stateline($('dirstate'), 'error', `Could not open concept: ${e.message}`);
    return;
  }
  if (!(d.shots || []).length) {
    // an idea without a plan yet: no shots means no shot nodes — offer
    // the (billed) plan step right here instead of gating on approval
    canvasOpen = false;
    landingRequested = true;    // hold this landing — don't auto-open another concept
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
          if (job.ref_id === id && job.kind === 'plan'
              && ['done', 'failed'].includes(job.status)) {
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

  currentId = null;               // the canvas is concept-scoped, not a saved workflow row
  $('wfpick').value = '';
  $('wfname').value = d.title;
  attached.clear();
  directorConcept = d;
  activeShotN = null;
  shotGraphs.clear();
  setConceptScope(d);
  activateShot(d.shots[0].n);     // one shot at a time — the rest wait in the dock
  canvasOpen = true;              // before the view fronts, so its render lands on the canvas
  landingRequested = false;
  await ensureDirectorView();
  showCanvas();
  wfStateline(null);
}

async function saveToConcept() {
  // persist each edited shot's prompt back onto the concept —
  // update_concept_shots under the hood, title/hook/logline untouched.
  // Edits live per shot in shotGraphs (plus whatever's on the canvas
  // right now), so shots never opened are never touched.
  if (!directorConceptId || !directorConcept) return;
  if (activeShotN !== null && graph) {
    shotGraphs.set(activeShotN, graph.serialize());
  }
  const btn = $('wfsaveconcept');
  btn.disabled = true;
  let saved = 0, warnings = 0;
  try {
    for (const [n, serialized] of shotGraphs) {
      const promptNode = (serialized.nodes || []).find(node =>
        node.type === 'zpf/user_prompt'
        && node.properties && node.properties.shot_n === n);
      if (!promptNode) continue;
      const text = (promptNode.properties.text || '').trim();
      if (!text) continue;
      // only what actually changed — an untouched shot must not have
      // its stored prompt rewritten with the composed seed text
      if (text === seededTexts.get(`${directorConceptId}·${n}`)) continue;
      const res = await api(
        `/api/concepts/${directorConceptId}/shots/${n}/prompt`,
        { method: 'POST', body: { prompt: text } });
      seededTexts.set(`${directorConceptId}·${n}`, text);
      saved += 1;
      warnings = (res.warnings || []).length;
    }
    wfStateline('empty', saved
      ? `Saved ${saved} shot prompt(s) to the concept`
        + (warnings ? ` · ${warnings} warning(s)` : '')
      : 'No edits to save — the shots are as loaded');
  } catch (e) {
    wfStateline('error', `Save to concept failed: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

export async function renderDirectorTab() {
  if (!canvas) return;
  if (canvasOpen) {
    $('dirlanding').hidden = true;
    $('dircanvas').hidden = false;
    requestAnimationFrame(() => { resizeCanvas(); canvas.setDirty(true, true); });
    await loadList();
    return;
  }
  // arrival is the NODES, never a composer: open the newest planned
  // concept's scene graph. The brief composer is the fallback (nothing
  // planned yet) or an explicit ← Brief away.
  if (!landingRequested) {
    try {
      const data = await api(`/api/pipeline/concepts?brand=${encodeURIComponent(state.brand)}`);
      const planned = data.items.find(c => c.status !== 'idea');
      if (planned) {
        await openConceptInDirector(planned.id);
        return;
      }
    } catch { /* fall through to the landing */ }
  }
  await Promise.all([renderLanding(), loadList()]);
}

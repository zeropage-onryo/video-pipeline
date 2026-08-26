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
import { api, bus, enhanceSystemText, esc, fillPresetSelect, loadPresets, state, stateline, wireMentions } from './shared.js';

const LG = window.LiteGraph;

/* The Runway-style canvas palette. One source of truth for everything
   drawn on the <canvas>; the DOM chrome reads the same values from the
   #v-director CSS custom properties in zpf.css — keep the two in sync. */
const T = {
  canvasBg: '#0a0a0a',
  canvasDot: '#1f1f1f',
  nodeBg: '#18181b',
  nodeBorder: '#2a2a2e',
  nodeBorderHover: '#3a3a40',
  headerIconBg: '#27272a',
  textPrimary: '#f4f4f5',
  textSecondary: '#8a8a92',
  accentPurple: '#a78bfa',
  accentGreen: '#4ade80',
  accentRed: '#f87171',
  accentBlue: '#60a5fa',
  buttonGhostBg: '#1c1c1f',
  divider: '#26262a',
};

// connected ports and their edges are green; an unconnected port is a
// hollow blue ring (drawn in the drawNode patch below)
const PORT = { text: T.accentGreen, image: T.accentGreen, media: T.accentGreen };
const STATE_BOX = { idle: T.textSecondary, running: T.accentBlue, done: T.accentGreen, failed: T.accentRed };
const UI_FONT = '-apple-system, "Segoe UI", Inter, sans-serif';

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

function bodyTop() {
  // ports sit ON the card edge with no labeled rows (see the drawNode
  // patch in theme()), so the body starts right under the header
  return 18;
}

function drawBody(node, ctx, lines, color) {
  const top = bodyTop(node);
  ctx.font = `13px ${UI_FONT}`;
  ctx.fillStyle = color;
  lines.forEach((l, i) => ctx.fillText(l, 14, top + i * 18, node.size[0] - 28));
}

// the empty-output well: "Output will appear here", centered
function drawEmptyWell(node, ctx, text) {
  ctx.font = `13px ${UI_FONT}`;
  ctx.fillStyle = T.textSecondary;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const lines = wrapLines(text, Math.floor(node.size[0] / 7.5), 4);
  const y0 = (node.size[1] - 36) / 2 - (lines.length - 1) * 9;
  lines.forEach((l, i) =>
    ctx.fillText(l, node.size[0] / 2, y0 + i * 18, node.size[0] - 28));
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
}

function bodyLines(node) {
  // how many preview lines fit between the header and the action pill
  return Math.max(2, Math.floor((node.size[1] - bodyTop() - 40) / 18));
}

/* the floating caption above a node — a Runway-style annotation box,
   never wired to anything. Set node._caption = {text, color} once. */
function drawCaption(node, ctx) {
  const cap = node._caption;
  if (!cap || node.flags.collapsed) return;
  ctx.font = `13px ${UI_FONT}`;
  const lines = wrapLines(cap.text, 26, 3);
  const padX = 14, padY = 10, lineH = 18;
  const w = Math.min(208, Math.max(...lines.map(l => ctx.measureText(l).width)) + padX * 2);
  const h = lines.length * lineH + padY * 2;
  const x = 0;
  const y = -LG.NODE_TITLE_HEIGHT - h - 16;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 10);
  ctx.fillStyle = 'rgba(24,24,27,.9)';
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = cap.color;
  ctx.stroke();
  ctx.lineWidth = 1;
  ctx.fillStyle = T.textPrimary;
  lines.forEach((l, i) => ctx.fillText(l, x + padX, y + padY + 13 + i * lineH));
}

function previewDrawer(placeholder) {
  return function(ctx) {
    if (this.flags.collapsed) return;
    const failed = this._state === 'failed';
    const shown = failed ? ('✕ ' + (this._note || 'failed'))
      : this._out != null && this._out !== '' ? this._out
      : (this.properties.text || this.properties.url || '');
    if (!shown) {
      drawEmptyWell(this, ctx, placeholder);
      return;
    }
    const lines = wrapLines(shown, Math.floor(this.size[0] / 7), bodyLines(this));
    drawBody(this, ctx, lines,
      failed ? T.accentRed : this._out != null && this._out !== '' ? T.textPrimary : T.textSecondary);
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
      // the shot's own reference and the RAG grounding ride invisibly
      // (image_url / auto_ground properties) — the Director chain keeps
      // grounding on the backend, no extra nodes on the canvas
      const image = inputVal(node, 'image') || node.properties.image_url;
      const references = inputVal(node, 'references') || '';
      const res = await api('/api/workflows/exec/enhance', {
        method: 'POST',
        body: {
          system: inputVal(node, 'system') || '',
          user: inputVal(node, 'user') || '',
          references,
          ground: !references && !!node.properties.auto_ground,
          images: image ? [image] : [],
        },
      });
      nodeJobs.set(res.job_id, node.id);
    } else if (node.type === 'zpf/generate') {
      setNodeState(node, 'running');
      const res = await api('/api/workflows/exec/generate', {
        method: 'POST',
        body: { prompt: inputVal(node, 'prompt') || '',
                image: inputVal(node, 'image') || node.properties.image_url || null },
      });
      nodeJobs.set(res.job_id, node.id);
    } else if (node.type === 'zpf/nano_banana') {
      setNodeState(node, 'running');
      const res = await api('/api/workflows/exec/nano', {
        method: 'POST',
        body: { prompt: inputVal(node, 'prompt') || '',
                image: inputVal(node, 'image') || node.properties.image_url || null },
      });
      nodeJobs.set(res.job_id, node.id);
    }
  } catch (e) {
    setNodeState(node, 'failed', e.message);
  }
}

/* ── node chrome: one action pill in the bottom-right corner (the
   reference screenshot's shape) instead of stacked widget rows.
   Double-click stays the inspector: edit for text nodes, output view
   (or the rendered file) for the rest. ── */

function drawPill(node, ctx, label) {
  ctx.font = `12px ${UI_FONT}`;
  const w = Math.max(60, ctx.measureText(label).width + 26);
  const h = 26;
  const x = node.size[0] - w - 12;
  const y = node.size[1] - h - 10;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 13);
  ctx.fillStyle = T.buttonGhostBg;
  ctx.fill();
  ctx.strokeStyle = T.nodeBorder;
  ctx.stroke();
  ctx.fillStyle = T.textSecondary;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, x + w / 2, y + h / 2 + 0.5);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  node._pill = { x, y, w, h };
}

/* the raw text node's bottom-right "N characters" counter — it doubles
   as the click target that opens the editor (same _pill hit zone) */
function drawCharCount(node, ctx) {
  const label = `${(node.properties.text || '').length} characters`;
  ctx.font = `11px ${UI_FONT}`;
  const w = ctx.measureText(label).width;
  const x = node.size[0] - w - 14;
  const y = node.size[1] - 14;
  ctx.fillStyle = T.textSecondary;
  ctx.fillText(label, x, y);
  node._pill = { x: x - 8, y: y - 16, w: w + 16, h: 24 };
}

function wirePill(node, action) {
  node.onMouseDown = function(e, local) {
    const p = this._pill;
    if (p && local[0] >= p.x && local[0] <= p.x + p.w
        && local[1] >= p.y && local[1] <= p.y + p.h) {
      action(this);
      return true;
    }
  };
}

/* ── node type definitions ── */

/* the 24px rounded-square icon chip in a model node's header; the
   sparkle doubles as the run-state light (idle/running/done/failed) */
function drawTitleChip(ctx, titleHeight) {
  const s = 22;
  const x = 8, y = -titleHeight + (titleHeight - s) / 2;
  ctx.beginPath();
  ctx.roundRect(x, y, s, s, 6);
  ctx.fillStyle = T.headerIconBg;
  ctx.fill();
  ctx.font = `12px ${UI_FONT}`;
  ctx.fillStyle = this.boxcolor || T.textSecondary;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('✦', x + s / 2, y + s / 2 + 0.5);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
}

// pure input nodes get the stripped-down chrome: no icon chip at all
function noTitleBox() {}

/* the "no image yet" checkerboard — signals image output specifically */
function drawCheckerboard(node, ctx) {
  const top = bodyTop(), sq = 12;
  const w = node.size[0] - 28, h = node.size[1] - top - 44;
  ctx.save();
  ctx.beginPath();
  ctx.rect(14, top, w, h);
  ctx.clip();
  ctx.fillStyle = T.nodeBorder;
  ctx.globalAlpha = 0.35;
  for (let y = 0; y * sq < h; y++) {
    for (let x = y % 2; x * sq < w; x += 2) {
      ctx.fillRect(14 + x * sq, top + y * sq, sq, sq);
    }
  }
  ctx.restore();
}

function registerNodes() {
  // only the v1 types in the add menu — the stock library would
  // drown them
  if (LG.clearRegisteredTypes) LG.clearRegisteredTypes();

  function textNode(self, placeholder) {
    self.addOutput('text', 'text');
    self.properties = { text: '' };
    self.size = [300, 190];
    self.onDrawTitleBox = noTitleBox;
    self.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      drawCaption(this, ctx);
      // a borderless-textarea look: the text (or its placeholder)
      // top-left, a character counter bottom-right
      const text = this.properties.text || '';
      const lines = wrapLines(text || placeholder, Math.floor(this.size[0] / 7), bodyLines(this));
      drawBody(this, ctx, lines, text ? T.textPrimary : T.textSecondary);
      drawCharCount(this, ctx);
    };
    wirePill(self, n => openModal(n, 'text'));
    self.onDblClick = () => openModal(self, 'text');
  }

  function SystemPrompt() {
    textNode(this, 'Instructions for how the model should behave…');
    this._caption = { color: T.accentPurple, text: 'Instructions for how to write the prompt' };
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
    this.size = [260, 210];
    this.onDrawTitleBox = noTitleBox;
    const self = this;
    this.onDblClick = () => openModal(self, 'media');
    this.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      drawCaption(this, ctx);
      const url = this.properties.url;
      const top = bodyTop();
      if (!url) {
        drawCheckerboard(this, ctx);
        drawEmptyWell(this, ctx, 'No image picked');
      } else {
        const img = thumbFor(url);
        if (img) {
          const h = this.size[1] - top - 44;
          const w = this.size[0] - 28;
          const scale = Math.min(w / img.naturalWidth, h / img.naturalHeight);
          ctx.drawImage(img, 14, top, img.naturalWidth * scale, img.naturalHeight * scale);
        }
        ctx.font = `11px ${UI_FONT}`;
        ctx.fillStyle = T.textSecondary;
        ctx.fillText(url.split('/').pop().split('?')[0], 14, this.size[1] - 16, this.size[0] - 110);
      }
      drawPill(this, ctx, 'Pick image');
    };
    wirePill(this, n => openModal(n, 'media'));
  }
  ReferenceImage.title = 'Reference Image';

  function Ground() {
    this.addInput('spark', 'text');
    this.addOutput('references', 'text');
    this.properties = { text: '' };
    this.size = [280, 200];
    this.onDrawTitleBox = drawTitleChip;
    const self = this;
    const drawer = previewDrawer('Output will appear here');
    this.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      drawCaption(this, ctx);
      drawer.call(this, ctx);
      drawPill(this, ctx, 'Run ⓘ');
    };
    wirePill(this, runNode);
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
    this.size = [320, 280];
    this.onDrawTitleBox = drawTitleChip;
    this._caption = { color: T.accentGreen, text: 'Enhances your prompt with vivid details' };
    const self = this;
    const drawer = previewDrawer('Output will appear here');
    this.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      drawCaption(this, ctx);
      drawer.call(this, ctx);
      drawPill(this, ctx, 'Run ⓘ');
    };
    wirePill(this, runNode);
    this.onDblClick = () => openModal(self, 'view');
  }
  Enhance.title = 'Gemini 2.5 Flash';

  function Generate() {
    this.addInput('prompt', 'text');
    this.addInput('image', 'image');
    this.addOutput('media', 'media');
    this.properties = {};
    this.size = [320, 280];
    this.onDrawTitleBox = drawTitleChip;
    this._caption = { color: T.accentRed, text: 'Renders the clip from the prompt and keyframe' };
    const self = this;
    this.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      drawCaption(this, ctx);
      if (this._state === 'failed') {
        drawBody(this, ctx,
          wrapLines('✕ ' + (this._note || 'failed'), Math.floor(this.size[0] / 7), bodyLines(this)),
          T.accentRed);
      } else if (this._out) {
        drawBody(this, ctx, wrapLines(this._out, Math.floor(this.size[0] / 7), bodyLines(this)),
          T.textPrimary);
      } else {
        const gate = state.caps['runway.generate']
          ? (state.caps['runway.spend'] ? 'Output will appear here'
                                        : 'Runway · gated — RUNWAY_SPEND_OK=1 to arm')
          : 'Runway · RUNWAYML_API_SECRET not set';
        // a skipped node carries the server's own reason — show that
        drawEmptyWell(this, ctx, this._note || gate);
      }
      drawPill(this, ctx, 'Run · $');
    };
    wirePill(this, runNode);
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
    this.size = [320, 300];
    this.onDrawTitleBox = drawTitleChip;
    this._caption = { color: T.accentRed, text: 'Renders the keyframe the clip starts from' };
    const self = this;
    this.onDrawForeground = function(ctx) {
      if (this.flags.collapsed) return;
      drawCaption(this, ctx);
      const top = bodyTop();
      if (this._out && this._state !== 'failed') {
        const img = thumbFor(this._out);
        if (img) {
          const h = this.size[1] - top - 44;
          const w = this.size[0] - 28;
          const scale = Math.min(w / img.naturalWidth, h / img.naturalHeight);
          ctx.drawImage(img, 14, top, img.naturalWidth * scale, img.naturalHeight * scale);
        } else {
          drawBody(this, ctx, ['loading preview…'], T.textSecondary);
        }
      } else if (this._state === 'failed') {
        drawBody(this, ctx,
          wrapLines('✕ ' + (this._note || 'failed'), Math.floor(this.size[0] / 7), bodyLines(this)),
          T.accentRed);
      } else {
        // the transparent-checkerboard placeholder: image output, none yet
        drawCheckerboard(this, ctx);
        if (!state.caps['nano.generate']) drawEmptyWell(this, ctx, 'GEMINI_API_KEY not set');
      }
      drawPill(this, ctx, 'Run ⓘ');
    };
    wirePill(this, runNode);
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

/* ── theming: the Runway-style dark canvas instead of LiteGraph's
   default look. Cards are one #18181b surface with a 1px border and a
   hairline header divider; ports are unlabeled dots sitting ON the card
   edges — hollow blue when unconnected, solid green when wired. ── */

// a 24px-tile 1px dot grid, generated once — LiteGraph tiles
// background_image as the canvas pattern
function dotGridURI() {
  const c = document.createElement('canvas');
  c.width = c.height = 24;
  const x = c.getContext('2d');
  x.fillStyle = T.canvasDot;
  x.fillRect(0, 0, 2, 2);
  return c.toDataURL();
}

let protoPatched = false;
function patchNodeChrome() {
  if (protoPatched) return;
  protoPatched = true;
  const proto = window.LGraphCanvas.prototype;

  const origShape = proto.drawNodeShape;
  proto.drawNodeShape = function(node, ctx, size, fgcolor, bgcolor, selected, mouseOver) {
    origShape.call(this, node, ctx, size, fgcolor, bgcolor, selected, mouseOver);
    if (node.flags.collapsed) return;
    // repaint the stock header separator as a token hairline
    ctx.fillStyle = bgcolor || T.nodeBg;
    ctx.fillRect(0, -1, size[0] + 1, 2);
    ctx.fillStyle = T.divider;
    ctx.fillRect(0, -1, size[0] + 1, 1);
    // the 1px card border (stock LiteGraph only outlines selection)
    ctx.beginPath();
    ctx.roundRect(0, -LG.NODE_TITLE_HEIGHT, size[0] + 1, size[1] + LG.NODE_TITLE_HEIGHT,
      this.round_radius);
    ctx.strokeStyle = (selected || mouseOver) ? T.nodeBorderHover : T.nodeBorder;
    ctx.lineWidth = 1;
    ctx.stroke();
  };

  const origDrawNode = proto.drawNode;
  proto.drawNode = function(node, ctx) {
    if (!node.flags.collapsed) {
      // ports live ON the card edge, unlabeled — pin each slot's pos
      // every frame so resizes track, and blank the row labels
      (node.inputs || []).forEach((s, i) => {
        s.label = '';
        s.pos = [0, 26 + i * 22];
      });
      (node.outputs || []).forEach((s, i) => {
        s.label = '';
        s.pos = [node.size[0], 26 + i * 22];
      });
    }
    origDrawNode.call(this, node, ctx);
    if (node.flags.collapsed) return;
    // overdraw the stock dots: solid green when wired, hollow blue ring
    // when waiting for a connection
    const dot = (x, y, connected) => {
      ctx.beginPath();
      ctx.arc(x, y, 4.5, 0, Math.PI * 2);
      if (connected) {
        ctx.fillStyle = T.accentGreen;
        ctx.fill();
      } else {
        ctx.fillStyle = T.nodeBg;
        ctx.fill();
        ctx.strokeStyle = T.accentBlue;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.lineWidth = 1;
      }
    };
    (node.inputs || []).forEach(s => dot(s.pos[0], s.pos[1], s.link != null));
    (node.outputs || []).forEach(s => dot(s.pos[0], s.pos[1], !!(s.links && s.links.length)));
  };
}

function theme() {
  LG.NODE_DEFAULT_COLOR = T.nodeBg;      // header
  LG.NODE_DEFAULT_BGCOLOR = T.nodeBg;    // body — one surface, divider drawn in the patch
  LG.NODE_DEFAULT_BOXCOLOR = T.textSecondary;
  LG.NODE_BOX_OUTLINE_COLOR = T.nodeBorderHover;
  LG.NODE_TITLE_COLOR = T.textPrimary;
  LG.NODE_SELECTED_TITLE_COLOR = T.textPrimary;
  LG.NODE_TEXT_COLOR = T.textSecondary;
  LG.WIDGET_BGCOLOR = T.buttonGhostBg;
  LG.WIDGET_OUTLINE_COLOR = T.nodeBorder;
  LG.WIDGET_TEXT_COLOR = T.textPrimary;
  LG.WIDGET_SECONDARY_TEXT_COLOR = T.textSecondary;
  window.LGraphCanvas.link_type_colors = Object.assign(
    {}, window.LGraphCanvas.link_type_colors, PORT);
  patchNodeChrome();
}

function themeCanvas(c) {
  c.clear_background_color = T.canvasBg;
  c.background_image = dotGridURI();
  c.zoom_modify_alpha = false;           // the dot grid holds steady across zoom
  c.render_canvas_border = false;        // no stray origin rectangle on the grid
  c.show_info = false;
  c.render_shadows = false;
  c.render_connection_arrows = false;
  c.render_curved_connections = true;    // slight bezier between ports
  c.connections_width = 2;
  c.round_radius = 14;
  c.title_text_font = `600 14px ${UI_FONT}`;
  c.inner_text_font = `12px ${UI_FONT}`;
  c.default_connection_color_byType = Object.assign({}, PORT);
  c.default_connection_color_byTypeOff = {
    text: T.accentBlue, image: T.accentBlue, media: T.accentBlue,
  };
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
  $('wfsaved').textContent = 'Saved just now';
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
  for (const id of ['wfpick', 'wfnew', 'wfdel', 'wfsave', 'wfmore']) {
    $(id).hidden = !!concept;
  }
  $('wfmore').open = false;
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
  // arrival shows the whole chain; if the view isn't measurable yet the
  // ResizeObserver runs the fit as soon as it is
  pendingFit = true;
  requestAnimationFrame(() => {
    resizeCanvas();
    fitWhenSized();
    canvas.setDirty(true, true);
  });
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

/* ── the node search palette (the left rail's "+") ── */

const NODE_CATALOG = [
  { type: 'zpf/user_prompt', title: 'User Prompt', sub: 'The raw prompt — the start of the chain',
    cat: 'Text', glyph: 'T', grad: 'linear-gradient(135deg,#6d5bd0,#a78bfa)' },
  { type: 'zpf/system_prompt', title: 'System Prompt', sub: 'Instructions for how the model behaves',
    cat: 'Text', glyph: 'S', grad: 'linear-gradient(135deg,#7c3aed,#c4b5fd)' },
  { type: 'zpf/ground', title: 'Ground in References', sub: 'Reference-library grounding for a spark',
    cat: 'Text', glyph: '¶', grad: 'linear-gradient(135deg,#166534,#4ade80)' },
  { type: 'zpf/enhance', title: 'Gemini 2.5 Flash', sub: 'Text to enhanced prompt',
    cat: 'Text', glyph: '✦', grad: 'linear-gradient(135deg,#1d4ed8,#60a5fa)' },
  { type: 'zpf/reference_image', title: 'Reference Image', sub: 'A saved photo from Assets, as grounding',
    cat: 'Image', glyph: '▣', grad: 'linear-gradient(135deg,#0e7490,#67e8f9)' },
  { type: 'zpf/nano_banana', title: 'Nano Banana', sub: 'Text/Image to Image',
    cat: 'Image', glyph: '✦', grad: 'linear-gradient(135deg,#b45309,#fbbf24)' },
  { type: 'zpf/generate', title: 'Generate', sub: 'Text/Image to Video · Runway',
    cat: 'Video', glyph: '▶', grad: 'linear-gradient(135deg,#9f1239,#f87171)' },
];
const PALETTE_CATS = ['All', 'Text', 'Image', 'Video'];
let paletteCat = 'All';
let paletteKeep = false;   // the footer toggle: stay open to add several

function addNodeAtCenter(type) {
  const node = LG.createNode(type);
  if (!node) return;
  // drop it near the centre of the current view
  const rect = $('wfcanvas').getBoundingClientRect();
  const w = (node.size && node.size[0]) || 260;
  const h = (node.size && node.size[1]) || 160;
  node.pos = canvas.convertCanvasToOffset([rect.width / 2 - w / 2, rect.height / 2 - h / 2]);
  graph.add(node);
  canvas.setDirty(true, true);
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
  $('wfaddbtn').onclick = () =>
    $('wfpalette').hidden ? openPalette() : closePalette();
  $('wfpsearch').oninput = renderPalette;
  $('wfpkeep').onclick = () => {
    paletteKeep = !paletteKeep;
    $('wfpkeep').setAttribute('aria-checked', String(paletteKeep));
  };
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !$('wfpalette').hidden) closePalette();
  });
  document.addEventListener('pointerdown', e => {
    if ($('wfpalette').hidden) return;
    if (!$('wfpalette').contains(e.target) && !$('wfaddbtn').contains(e.target)) closePalette();
  });
}

// centre the whole graph in the viewport (the rail's grid button)
function fitView() {
  const ns = (graph && graph._nodes) || [];
  if (!ns.length) return;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const n of ns) {
    x0 = Math.min(x0, n.pos[0]);
    y0 = Math.min(y0, n.pos[1] - LG.NODE_TITLE_HEIGHT - 90);  // caption headroom
    x1 = Math.max(x1, n.pos[0] + n.size[0]);
    y1 = Math.max(y1, n.pos[1] + n.size[1]);
  }
  const rect = $('wfcanvas').getBoundingClientRect();
  const pad = 80;
  const rail = 120;               // the + and the floating rail sit over this strip
  const scale = Math.max(0.2, Math.min(1.2,
    (rect.width - pad - rail) / (x1 - x0), (rect.height - pad) / (y1 - y0)));
  canvas.ds.scale = scale;
  // centre in the clear area to the RIGHT of the rail, so the first
  // node never lands underneath it
  canvas.ds.offset[0] = (rail + (rect.width - rail) / 2) / scale - (x0 + x1) / 2;
  canvas.ds.offset[1] = rect.height / (2 * scale) - (y0 + y1) / 2;
  canvas.setDirty(true, true);
}

/* ── boot ── */

function resizeCanvas() {
  const el = $('wfcanvas');
  const rect = el.getBoundingClientRect();
  if (rect.width && rect.height) canvas.resize(rect.width, rect.height);
}

/* The canvas is built while the Director view is still hidden, so it
   starts at zero size — and LiteGraph's render loop draws nothing at
   all on a zero-sized canvas. Guessing when the view becomes visible
   with a rAF is a race (it lost, intermittently, and the canvas came
   up blank until something else forced a redraw). A ResizeObserver
   waits for a real size instead of guessing, and the deferred fit runs
   the moment there is a viewport to fit into. */
let pendingFit = false;

function fitWhenSized() {
  const rect = $('wfcanvas').getBoundingClientRect();
  if (!rect.width || !rect.height) return;    // still hidden — the observer will call back
  if (!pendingFit) return;
  pendingFit = false;
  fitView();
}

function watchCanvasSize() {
  if (typeof ResizeObserver !== 'function') return;
  new ResizeObserver(() => {
    resizeCanvas();
    fitWhenSized();
    canvas.setDirty(true, true);
  }).observe($('wfcanvas').parentElement);
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
  watchCanvasSize();

  $('wfsave').onclick = () => saveWorkflow();
  $('wfnew').onclick = newWorkflow;
  $('wfdel').onclick = deleteWorkflow;
  $('wfrunall').onclick = runAll;
  $('wfpick').onchange = () => {
    const id = Number($('wfpick').value);
    if (id) openWorkflow(id);
  };
  wirePalette();
  $('wffit').onclick = fitView;
  $('wffolder').onclick = () => {
    const more = $('wfmore');
    if (!more.hidden) more.open = !more.open;
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
let enhanceSystem = '';        // prompts/enhance_system.txt, fetched once

function shotChainGraph(d, s) {
  // Hand-built in LiteGraph's own serialize() shape (the
  // default_template pattern). The shot's short prompt → the
  // enhancement Instructions → Gemini 2.5 Flash → Nano Banana keyframe
  // → Runway clip. The keyframe is not a side branch: it feeds
  // Generate's image port, so the clip is anchored on the still we
  // just approved rather than starting from text alone. The shot's own
  // reference image and the RAG retrieval still ride on the BACKEND
  // (the enhance node's image_url / auto_ground properties), not as
  // extra nodes.
  const text = s.desc || s.prompt || '';
  seededTexts.set(`${d.id}·${s.n}`, text);

  const nodes = [
    { id: 1, type: 'zpf/user_prompt', title: `Shot ${s.n} · prompt`,
      pos: [60, 200], size: [300, 200], flags: {}, order: 0, mode: 0,
      outputs: [{ name: 'text', type: 'text', links: [1] }],
      properties: { text, concept_id: d.id, shot_n: s.n } },
    { id: 2, type: 'zpf/system_prompt', title: 'Instructions',
      pos: [60, 540], size: [300, 210], flags: {}, order: 1, mode: 0,
      outputs: [{ name: 'text', type: 'text', links: [2] }],
      properties: { text: enhanceSystem } },
    { id: 3, type: 'zpf/enhance', title: 'Gemini 2.5 Flash',
      pos: [470, 330], size: [320, 280], flags: {}, order: 2, mode: 0,
      inputs: [{ name: 'system', type: 'text', link: 2 },
               { name: 'user', type: 'text', link: 1 },
               { name: 'image', type: 'image', link: null },
               { name: 'references', type: 'text', link: null }],
      // one enhanced prompt, two consumers: the keyframe and the clip
      outputs: [{ name: 'text', type: 'text', links: [3, 4] }],
      properties: { auto_ground: true,
                    image_url: s.reference_image || '' } },
    { id: 4, type: 'zpf/nano_banana', title: 'Nano Banana',
      pos: [900, 300], size: [320, 300], flags: {}, order: 3, mode: 0,
      inputs: [{ name: 'prompt', type: 'text', link: 3 },
               { name: 'image', type: 'image', link: null }],
      outputs: [{ name: 'image', type: 'image', links: [5] }],
      properties: { concept_id: d.id, shot_n: s.n,
                    image_url: s.reference_image || '' } },
    { id: 5, type: 'zpf/generate', title: 'Generate',
      pos: [1330, 320], size: [320, 280], flags: {}, order: 4, mode: 0,
      // the enhanced prompt AND the keyframe Nano just rendered
      inputs: [{ name: 'prompt', type: 'text', link: 4 },
               { name: 'image', type: 'image', link: 5 }],
      outputs: [{ name: 'media', type: 'media', links: null }],
      properties: { concept_id: d.id, shot_n: s.n } },
  ];
  const links = [[1, 1, 0, 3, 1, 'text'],
                 [2, 2, 0, 3, 0, 'text'],
                 [3, 3, 0, 4, 0, 'text'],
                 [4, 3, 0, 5, 0, 'text'],
                 [5, 4, 0, 5, 1, 'image']];
  return { last_node_id: 5, last_link_id: 5, nodes, links,
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
  pendingFit = true;
  fitWhenSized();
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
  enhanceSystem = await enhanceSystemText();
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
    if (saved) $('wfsaved').textContent = 'Saved just now';
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

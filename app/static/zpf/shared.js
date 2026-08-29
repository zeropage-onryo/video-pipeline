/* Shared client core: fetch wrapper, state, capability gating, and the
   tiny DOM helpers every view uses. No fixtures anywhere -- a view that
   can't reach its endpoint shows an error line with a retry, never
   made-up data. */

export const state = {
  caps: {},
  brand: document.body.dataset.brand || 'antihero',
  assets: null,          // cached /api/assets payload
  jobs: new Map(),       // id -> job, fed by SSE
  denyReasons: [],
};

export const bus = new EventTarget();

export async function api(path, opts = {}) {
  const init = { headers: {}, ...opts };
  if (init.body !== undefined && typeof init.body !== 'string'
      && !(init.body instanceof FormData)) {
    init.body = JSON.stringify(init.body);
    init.headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    const message = data && data.error ? data.error.message
      : data && data.detail ? JSON.stringify(data.detail)
      : `${res.status} ${res.statusText}`;
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }
  return data;
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function fmtN(n) {
  if (n === null || n === undefined) return '—';
  return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(n);
}

export function pct(x, digits = 0) {
  return x === null || x === undefined ? '—' : (x * 100).toFixed(digits) + '%';
}

/* stateline: the loading/empty/error surface. kind: 'loading'|'empty'|'error'|null */
export function stateline(node, kind, message, retry) {
  if (!node) return;
  if (!kind) { node.hidden = true; node.innerHTML = ''; return; }
  node.hidden = false;
  node.className = 'stateline' + (kind === 'error' ? ' err' : '');
  node.innerHTML = esc(message || kind);
  if (retry) {
    const b = document.createElement('button');
    b.textContent = 'Retry';
    b.onclick = retry;
    node.appendChild(b);
  }
}

export function applyCaps(caps) {
  state.caps = caps;
  document.querySelectorAll('[data-cap]').forEach(node => {
    const key = node.dataset.cap;
    node.hidden = !caps[key];
  });
}

export async function loadAssets(force = false) {
  if (state.assets && !force) return state.assets;
  state.assets = await api('/api/assets');
  return state.assets;
}

/* Presets: prompts/presets.json via /api/presets, cached once. The
   same payload carries the enhancement instruction the Director
   chain's Instructions node seeds with. */
let presetsCache = null;
async function presetsPayload() {
  if (presetsCache) return presetsCache;
  try {
    presetsCache = await api('/api/presets');
  } catch { presetsCache = { items: [], enhance_system: '' }; }
  return presetsCache;
}
export async function loadPresets() {
  return (await presetsPayload()).items;
}
export async function enhanceSystemText() {
  return (await presetsPayload()).enhance_system || '';
}

export function fillPresetSelect(select, presets) {
  const keep = select.querySelector('option').outerHTML;
  select.innerHTML = keep + presets.map(p =>
    `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');
}

/* `@` mentions: typing @word in a textarea autocompletes against
   /api/assets/search (characters + props + locations in one list).
   Picking one replaces the @word with the asset's name and calls
   onPick(item) so the caller can auto-attach its reference photo. */
export function wireMentions(textarea, dropdown, onPick) {
  let items = [];
  let cursor = 0;
  let token = null;   // {start, end} of the active @word, or null

  const close = () => { dropdown.hidden = true; items = []; token = null; };

  const paint = () => {
    if (!items.length) { close(); return; }
    dropdown.hidden = false;
    dropdown.innerHTML = items.map((it, i) => `
      <button type="button" class="mention${i === cursor ? ' cur' : ''}" data-i="${i}">
        ${it.thumb ? `<span class="mth" style="background-image:url('${it.thumb}')"></span>` : '<span class="mth"></span>'}
        <span>${esc(it.name)}</span><span class="mcat">${esc(it.category)}</span>
      </button>`).join('');
    dropdown.querySelectorAll('.mention').forEach(b => {
      b.onmousedown = e => { e.preventDefault(); pick(items[+b.dataset.i]); };
    });
  };

  const pick = item => {
    if (!token) return close();
    const value = textarea.value;
    textarea.value = value.slice(0, token.start) + item.name + value.slice(token.end);
    const at = token.start + item.name.length;
    textarea.setSelectionRange(at, at);
    textarea.focus();
    close();
    if (onPick) onPick(item);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  };

  let timer = null;
  textarea.addEventListener('input', () => {
    const pos = textarea.selectionStart;
    const before = textarea.value.slice(0, pos);
    const match = before.match(/@([\w -]{0,40})$/);
    if (!match) { close(); return; }
    token = { start: pos - match[0].length, end: pos };
    const q = match[1].trim();
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const res = await api('/api/assets/search?q=' + encodeURIComponent(q));
        items = res.items; cursor = 0; paint();
      } catch { close(); }
    }, 120);
  });
  textarea.addEventListener('keydown', e => {
    if (dropdown.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); cursor = Math.min(items.length - 1, cursor + 1); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); cursor = Math.max(0, cursor - 1); paint(); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pick(items[cursor]); }
    else if (e.key === 'Escape') { e.stopPropagation(); close(); }
  });
  textarea.addEventListener('blur', () => setTimeout(close, 150));
}

/* Multi-photo hover scrub: real photos stand in for sprite frames. */
export function wireScrub(frameEl, photos, slEl) {
  if (!photos || photos.length < 2) { if (slEl) slEl.classList.add('off'); return; }
  frameEl.addEventListener('mousemove', e => {
    const r = frameEl.getBoundingClientRect();
    const f = Math.max(0, Math.min(.999, (e.clientX - r.left) / r.width));
    frameEl.style.backgroundImage = `url("${photos[Math.floor(f * photos.length)]}")`;
    const v = Math.max(2, Math.min(98, f * 100)) + '%';
    if (slEl) slEl.style.setProperty('--s', v);
  });
  frameEl.addEventListener('mouseleave', () => {
    frameEl.style.backgroundImage = `url("${photos[0]}")`;
    if (slEl) slEl.style.setProperty('--s', '14%');
  });
}

/* Detail rail */
const detail = () => document.getElementById('detail');

export function openAssetDetail(asset) {
  const dn = document.getElementById('dn');
  const df = document.getElementById('df');
  const dstrip = document.getElementById('dstrip');
  const dmeta = document.getElementById('dmeta');
  const dtr = document.getElementById('dtr');
  dn.textContent = asset.name;
  const media = asset.media || (asset.photos || []).map(url => ({ url, kind: 'image' }));
  const show = item => {
    df.innerHTML = '';
    df.style.backgroundImage = 'none';
    if (!item) return;
    if (item.kind === 'video') {
      df.innerHTML = `<video src="${esc(item.url)}" controls playsinline preload="metadata"></video>`;
    } else {
      df.style.backgroundImage = `url("${item.url}")`;
    }
  };
  show(media[0] || (asset.poster ? { url: asset.poster, kind: 'image' } : null));
  dstrip.innerHTML = media.map((item, i) =>
    `<button class="th${item.kind === 'video' ? ' video' : ''}" data-i="${i}"
      ${item.kind === 'image' ? `style="background-image:url('${esc(item.url)}')"` : ''}>${item.kind === 'video' ? '▶' : ''}</button>`).join('');
  dstrip.querySelectorAll('.th').forEach(t => {
    t.onclick = () => show(media[Number(t.dataset.i)]);
  });
  const rows = [
    ['Category', asset.category],
    ['Media', media.length],
  ];
  if (asset.meta) {
    for (const [k, v] of Object.entries(asset.meta)) {
      if (v !== null && v !== undefined && v !== '') rows.push([k.replace(/_/g, ' '), v]);
    }
  }
  if (asset.created_at) rows.push(['Added', String(asset.created_at).slice(0, 10)]);
  dmeta.innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
  dtr.textContent = asset.text || 'No description yet.';
  detail().setAttribute('data-open', '');
}

export function closeDetail() { detail().removeAttribute('data-open'); }

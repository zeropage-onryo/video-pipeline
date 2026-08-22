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
  if (init.body !== undefined && typeof init.body !== 'string') {
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
  df.style.backgroundImage = asset.poster ? `url("${asset.poster}")` : 'none';
  dstrip.innerHTML = (asset.photos || []).map(p =>
    `<div class="th" style="background-image:url('${p}')" data-p="${esc(p)}"></div>`).join('');
  dstrip.querySelectorAll('.th').forEach(t => {
    t.onclick = () => { df.style.backgroundImage = `url("${t.dataset.p}")`; };
  });
  const rows = [
    ['Category', asset.category],
    ['Photos', (asset.photos || []).length],
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

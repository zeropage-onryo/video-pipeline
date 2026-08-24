/* Boot: capabilities first (everything gates on them), then the field,
   the router, the palette, the brand pill, and the jobs SSE feed. */
import { api, applyCaps, bus, closeDetail, esc, state, stateline } from './shared.js';
import { initField } from './field.js';
import { initStudio, renderStudio } from './studio.js';
import { renderAssets } from './assets.js';
import { initPipeline, renderPipeline, closeDeny } from './pipeline.js';
import { initEvals, renderEvals } from './evals.js';
import { renderAnalytics } from './analytics.js';
import { initQueue, renderQueue } from './queue.js';

const VIEWS = {
  studio: { label: 'Studio', render: renderStudio },
  assets: { label: 'Assets', render: renderAssets },
  pipeline: { label: 'Pipeline', render: renderPipeline },
  evals: { label: 'Evals', render: renderEvals },
  analytics: { label: 'Analytics', render: renderAnalytics },
  queue: { label: 'Queue', render: renderQueue },
};

export function go(view) {
  if (!VIEWS[view]) view = 'studio';
  document.documentElement.dataset.v = view;
  document.querySelectorAll('.view').forEach(el =>
    el.classList.toggle('on', el.id === 'v-' + view));
  document.querySelectorAll('.rnav a').forEach(a =>
    a.toggleAttribute('aria-current', a.dataset.view === view));
  document.querySelector('.cur').textContent = VIEWS[view].label;
  VIEWS[view].render();
  scrollTo({ top: 0, behavior: 'smooth' });
}

/* ── brand pill — opens the real account switcher. Which accounts a
   person can enter is a membership question now, so the picker is a
   server page; choosing one still posts /brand/{slug} under the hood. ── */
const BRAND_LABEL = { antihero: 'ANTIHERO', zeropage: 'Zero Page Films' };

function paintBrand() {
  document.getElementById('brandpill').textContent =
    `${BRAND_LABEL[state.brand] || state.brand} · switch`;
}

function openAccountPicker() {
  location.href = '/ui/accounts';
}

async function signOut() {
  await fetch('/auth/logout', { method: 'POST' });
  location.href = '/signin';
}

/* ── jobs: one SSE feed drives the rail, the queue view, and the
   pipeline/evals refreshes ── */
function connectJobs() {
  const source = new EventSource('/api/jobs/stream');
  source.addEventListener('job', e => {
    const job = JSON.parse(e.data);
    state.jobs.set(job.id, job);
    paintJobsRail();
    bus.dispatchEvent(new CustomEvent('job', { detail: job }));
  });
  source.onerror = () => {
    source.close();
    setTimeout(connectJobs, 4000);   // dev-reload friendly reconnect
  };
}

function paintJobsRail() {
  const rail = document.getElementById('jobs');
  const items = [...state.jobs.values()]
    .sort((a, b) => b.id - a.id)
    .filter(j => ['queued', 'running'].includes(j.status)
             || (j.ended_at && Date.now() - Date.parse(j.ended_at) < 60_000))
    .slice(0, 5);
  rail.innerHTML = items.map(j => {
    const running = ['queued', 'running'].includes(j.status);
    const cls = j.status === 'failed' ? 'f' : running ? 'r' : 'd';
    return `<div class="job"><span class="jd ${cls}"></span>
      <span style="font-size:11.5px;color:${running ? 'var(--text)' : 'var(--dim)'}">${esc(j.label)}</span>
      <span class="jb"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></span>
      <span class="m">${esc(running ? (j.detail || j.status) : j.status)}</span></div>`;
  }).join('');
}

/* ── palette ── */
let palItems = [];
let palCursor = 0;
let palTimer = null;

function palCommands() {
  const cmds = Object.keys(VIEWS).map(v =>
    ({ l: 'Go to ' + VIEWS[v].label, k: 'View', run: () => go(v) }));
  if (state.caps['pipeline.run']) {
    cmds.push({ l: 'New concept from a spark', k: 'Action', run: () => {
      go('studio'); setTimeout(() => document.getElementById('prompt').focus(), 60);
    }});
  }
  if (state.caps['evals.run']) {
    cmds.push({ l: 'Run retrieval eval', k: 'Action', run: async () => {
      await api('/api/evals/run', { method: 'POST', body: {} }).catch(() => {});
      go('queue');
    }});
  }
  cmds.push({ l: 'Switch account', k: 'Action', run: openAccountPicker });
  cmds.push({ l: 'Sign out', k: 'Action', run: signOut });
  return cmds;
}

function palOpen() {
  document.getElementById('scrim').setAttribute('data-open', '');
  document.getElementById('pal').setAttribute('data-open', '');
  const pq = document.getElementById('pq');
  pq.value = '';
  palItems = palCommands(); palCursor = 0;
  palPaint(); pq.focus();
}

function palClose() {
  document.getElementById('scrim').removeAttribute('data-open');
  document.getElementById('pal').removeAttribute('data-open');
}

function palPaint() {
  const plist = document.getElementById('plist');
  plist.innerHTML = palItems.slice(0, 8).map((c, i) =>
    `<div class="pc" ${i === palCursor ? 'data-cur' : ''} data-i="${i}"><span class="l">${esc(c.l)}</span><span class="k">${esc(c.k)}</span></div>`).join('')
    || '<div class="probeblank">No match</div>';
  plist.querySelectorAll('.pc').forEach(el => el.onclick = () => palRun(palItems[+el.dataset.i]));
}

function palRun(cmd) {
  palClose();
  if (cmd) cmd.run();
}

async function palFilter(text) {
  const needle = text.toLowerCase().trim();
  const cmds = palCommands().filter(c => c.l.toLowerCase().includes(needle));
  palItems = cmds; palCursor = 0; palPaint();
  if (needle.length < 2) return;
  try {
    const res = await api('/api/assets?q=' + encodeURIComponent(needle));
    if (document.getElementById('pq').value.toLowerCase().trim() !== needle) return;
    palItems = cmds.concat(res.items.slice(0, 6).map(a => ({
      l: a.name, k: a.category,
      run: () => { go('assets'); import('./shared.js').then(m => m.openAssetDetail(a)); },
    })));
    palPaint();
  } catch { /* assets search failing leaves the command list */ }
}

/* ── wiring ── */
initField();
initStudio(go);
initPipeline();
initEvals();
initQueue();
paintBrand();
document.getElementById('brandpill').onclick = openAccountPicker;
document.getElementById('mark').onclick = () => go('studio');
document.querySelectorAll('.rnav a').forEach(a => a.onclick = () => go(a.dataset.view));
document.getElementById('dx').onclick = closeDetail;
document.getElementById('scrim').onclick = palClose;

const pq = document.getElementById('pq');
pq.addEventListener('input', () => {
  clearTimeout(palTimer);
  palTimer = setTimeout(() => palFilter(pq.value), 160);
});
pq.addEventListener('keydown', e => {
  if (e.key === 'ArrowDown') { e.preventDefault(); palCursor = Math.min(palItems.slice(0, 8).length - 1, palCursor + 1); palPaint(); }
  if (e.key === 'ArrowUp') { e.preventDefault(); palCursor = Math.max(0, palCursor - 1); palPaint(); }
  if (e.key === 'Enter') { e.preventDefault(); palRun(palItems[palCursor]); }
});

addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palOpen(); return; }
  if (e.key === 'Escape') { palClose(); closeDeny(); closeDetail(); }
});

/* hero parallax, straight from the prototype */
if (!matchMedia('(prefers-reduced-motion:reduce)').matches) {
  const hero = document.querySelector('.hero');
  let tick = false;
  addEventListener('scroll', () => {
    if (tick) return; tick = true;
    requestAnimationFrame(() => {
      const y = Math.min(scrollY, innerHeight);
      hero.style.transform = 'translateY(' + (y * .16) + 'px)';
      hero.style.opacity = String(Math.max(0, 1 - y / (innerHeight * .85)));
      tick = false;
    });
  }, { passive: true });
}

/* boot: capabilities gate everything, so they come first */
(async () => {
  try {
    applyCaps(await api('/api/capabilities'));
  } catch (e) {
    stateline(document.getElementById('railstate'), 'error',
      `Capabilities unavailable: ${e.message} — controls stay hidden`, () => location.reload());
    applyCaps({});
  }
  connectJobs();
  go('studio');
})();

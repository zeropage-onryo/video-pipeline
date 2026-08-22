/* Evals view: the retrieval harness made interactive. Metrics come
   from stored runs (computed server-side); the probe uses the same
   /api/retrieve the composer uses; marking a probe result correct adds
   a golden query. The client never calculates a metric. */
import { api, bus, esc, state, stateline } from './shared.js';

let runs = [];
let selectedRun = null;   // full run detail (with per_query)
let probeQuery = '';
let probeMarks = new Set();
let wired = false;

export function initEvals() {
  if (wired) return;
  wired = true;
  document.getElementById('runeval').onclick = runEval;
  const probe = document.getElementById('probe');
  let t = null;
  probe.addEventListener('input', () => { clearTimeout(t); t = setTimeout(renderProbe, 350); });
  document.getElementById('probesave').onclick = saveProbe;
  bus.addEventListener('job', e => {
    const job = e.detail;
    if (document.documentElement.dataset.v === 'evals' && job.kind === 'eval'
        && ['done', 'failed'].includes(job.status)) {
      renderEvals();
    }
  });
}

export async function renderEvals() {
  const estate = document.getElementById('estate');
  stateline(estate, 'loading', 'Loading runs…');
  try {
    runs = (await api('/api/evals/runs')).items;
    if (runs.length) {
      const targetId = selectedRun && runs.some(r => r.id === selectedRun.id)
        ? selectedRun.id : runs[runs.length - 1].id;
      selectedRun = await api(`/api/evals/runs/${targetId}`);
    } else {
      selectedRun = null;
    }
  } catch (e) {
    stateline(estate, 'error', `Evals unavailable: ${e.message}`, renderEvals);
    return;
  }
  stateline(estate, null);
  renderMetrics();
  renderBars();
  await renderGolden();
}

function renderMetrics() {
  const box = document.getElementById('emetrics');
  const label = document.getElementById('runlabel');
  if (!selectedRun) {
    label.textContent = 'no runs yet';
    box.innerHTML = '';
    return;
  }
  const r = selectedRun;
  const idx = runs.findIndex(x => x.id === r.id);
  const prev = idx > 0 ? runs[idx - 1] : null;
  label.textContent = `${r.label} · ${r.n} queries · k=${r.k}${idx === runs.length - 1 ? ' · latest' : ''}`;
  const delta = (v, p, dp = 2) => {
    if (p === null || p === undefined) return '';
    const d = v - p, sign = d > 0 ? '+' : '';
    return `<span class="delta" style="color:${d >= 0 ? '#4c9a6c' : 'var(--signal)'}">${sign}${d.toFixed(dp)}</span>`;
  };
  box.innerHTML = [
    [r.hit_rate.toFixed(2), `Hit@${r.k}`, delta(r.hit_rate, prev?.hit_rate)],
    [r.mrr.toFixed(2), 'MRR', delta(r.mrr, prev?.mrr)],
    [r.p50_ms !== null ? r.p50_ms + ' ms' : '—', 'p50 latency', prev?.p50_ms != null && r.p50_ms != null ? delta(r.p50_ms, prev.p50_ms, 0) : ''],
    [String(r.n), 'Queries', ''],
  ].map(m => `<div class="metric"><div class="mv">${m[0]}${m[2]}</div><div class="md">${m[1]}</div></div>`).join('');
}

function renderBars() {
  const bars = document.getElementById('bars');
  const blank = document.getElementById('barsblank');
  blank.hidden = !!runs.length;
  if (!runs.length) { bars.innerHTML = ''; return; }
  const hmax = Math.max(...runs.map(x => x.hit_rate), 0.01) * 1.1;
  bars.innerHTML = runs.map(x =>
    `<div class="bar2${selectedRun && x.id === selectedRun.id ? ' sel' : ''}" data-id="${x.id}"
          style="height:${Math.max(4, x.hit_rate / hmax * 100)}%"
          data-v="${x.hit_rate.toFixed(2)}" title="${esc(x.label)} · ${esc(String(x.created_at).slice(0, 16))}"></div>`).join('');
  bars.querySelectorAll('.bar2').forEach(b => b.onclick = async () => {
    selectedRun = await api(`/api/evals/runs/${b.dataset.id}`);
    renderMetrics(); renderBars(); renderGolden();
  });
}

async function renderGolden() {
  const box = document.getElementById('golden');
  let golden;
  try {
    golden = (await api('/api/evals/golden')).items;
  } catch (e) {
    box.innerHTML = `<div class="probeblank" style="color:var(--signal)">${esc(e.message)}</div>`;
    return;
  }
  if (!golden.length) {
    box.innerHTML = '<div class="probeblank">Golden set is empty — add queries from the probe</div>';
    return;
  }
  const byQuery = {};
  (selectedRun?.per_query || []).forEach(pq => { byQuery[pq.query] = pq; });
  box.innerHTML = golden.map((g, i) => {
    const pq = byQuery[g.query];
    const rank = pq ? (pq.retrieved.findIndex(s => g.relevant.includes(s)) + 1) : null;
    const rankCls = pq ? (rank === 1 ? 'ok' : rank ? '' : 'miss') : '';
    return `<div>
      <div class="gq" data-i="${i}" aria-expanded="false">
        <span>${esc(g.query)}</span>
        <span class="v" title="${esc(g.relevant.join(', '))}">${esc(g.relevant.map(r => r.split('/').pop()).join(', '))}</span>
        <span class="v ${rankCls}">${pq ? (rank ? 'rank ' + rank : 'miss') : 'not in run'}</span>
        <span class="v">${pq ? pq.reciprocal_rank.toFixed(2) : '—'}</span>
        <button class="del" data-id="${g.id}" title="Remove from golden set">✕</button>
        <span class="chev">›</span>
      </div>
      <div class="gdetail" data-i="${i}">
        ${pq ? pq.retrieved.map((s, j) => `
          <div class="pr${g.relevant.includes(s) ? ' gold' : ''}" style="grid-template-columns:26px 1fr">
            <span class="rank">${j + 1}</span>
            <span class="rn">${esc(s)}</span>
          </div>`).join('') : '<div class="probeblank">Not part of the selected run — run the eval again</div>'}
      </div></div>`;
  }).join('');
  box.querySelectorAll('.gq').forEach(el => el.onclick = e => {
    if (e.target.classList.contains('del')) return;
    const det = box.querySelector(`.gdetail[data-i="${el.dataset.i}"]`);
    const on = el.getAttribute('aria-expanded') === 'true';
    el.setAttribute('aria-expanded', String(!on));
    on ? det.removeAttribute('data-open') : det.setAttribute('data-open', '');
  });
  box.querySelectorAll('.del').forEach(b => b.onclick = async () => {
    await api(`/api/evals/golden/${b.dataset.id}`, { method: 'DELETE' });
    renderGolden();
  });
}

async function runEval() {
  const btn = document.getElementById('runeval');
  btn.disabled = true; btn.textContent = 'Running…';
  try {
    await api('/api/evals/run', { method: 'POST', body: {} });
    // completion arrives on the job bus; button resets there
  } catch (e) {
    stateline(document.getElementById('estate'), 'error', e.message);
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = 'Run eval'; }, 1200);
}

async function renderProbe() {
  probeQuery = document.getElementById('probe').value.trim();
  probeMarks = new Set();
  const out = document.getElementById('probeout');
  const foot = document.getElementById('probefoot');
  if (!probeQuery) {
    out.innerHTML = '<div class="probeblank">Enter a query to see what retrieval returns</div>';
    foot.hidden = true;
    return;
  }
  out.innerHTML = '<div class="probeblank">Retrieving…</div>';
  let res;
  try {
    res = await api('/api/retrieve', { method: 'POST', body: { query: probeQuery, k: 5 } });
  } catch (e) {
    out.innerHTML = `<div class="probeblank" style="color:var(--signal)">${esc(e.message)}</div>`;
    foot.hidden = true;
    return;
  }
  if (!res.hits.length) {
    out.innerHTML = '<div class="probeblank">Nothing retrieved</div>';
    foot.hidden = true;
    return;
  }
  out.innerHTML = res.hits.map((h, i) => `
    <div class="pr">
      <span class="rank">${i + 1}</span>
      <span class="rn" title="${esc(h.chunk.slice(0, 200))}">${esc(h.source)} <span class="sr">· ${esc(h.domain)}</span></span>
      <span class="rs">${h.score.toFixed(2)}</span>
      <button class="mk" data-s="${esc(h.source)}" aria-pressed="false" title="Mark as correct">✓</button>
    </div>`).join('');
  out.querySelectorAll('.mk').forEach(b => b.onclick = () => {
    const on = b.getAttribute('aria-pressed') === 'true';
    b.setAttribute('aria-pressed', String(!on));
    on ? probeMarks.delete(b.dataset.s) : probeMarks.add(b.dataset.s);
    document.getElementById('probemeta').textContent = `${probeMarks.size} marked correct`;
  });
  foot.hidden = false;
  document.getElementById('probemeta').textContent =
    `${res.latency_ms} ms · mark which results are correct`;
}

async function saveProbe() {
  if (!probeQuery || !probeMarks.size) return;
  try {
    await api('/api/evals/golden', {
      method: 'POST',
      body: { query: probeQuery, relevant: [...probeMarks], source: 'probe' },
    });
  } catch (e) {
    document.getElementById('probemeta').textContent = e.message;
    return;
  }
  document.getElementById('probe').value = '';
  probeQuery = ''; probeMarks = new Set();
  document.getElementById('probeout').innerHTML = '<div class="probeblank">Added to the golden set</div>';
  document.getElementById('probefoot').hidden = true;
  renderGolden();
}

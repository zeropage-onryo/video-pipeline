/* The Dev Studio Stats tab's eval instruments: metrics from stored runs
   (computed server-side), the probe via the same retrieve endpoint the
   composer uses, marking a probe result correct adds a golden query.
   The client never calculates a metric.

   Endpoints are prefixed with window.ZP_API_BASE — the Dev Studio sets
   it to "/studio", pointing these calls at the dev router's own
   delegations (app/main.py) rather than the session-gated /api twins.
   The console reads every stat in the project without a login; the
   posture flag DEV_TOOLS is what gates the whole surface. Unset it and
   these routes don't exist. A 401 is still handled below in case the
   base is ever pointed back at /api. */
(() => {
  const $ = id => document.getElementById(id);
  const BASE = window.ZP_API_BASE || '';
  const esc = s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  async function api(path, opts = {}) {
    path = BASE + path;
    const init = { headers: {}, ...opts };
    if (init.body !== undefined && typeof init.body !== 'string') {
      init.body = JSON.stringify(init.body);
      init.headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(path, init);
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON error body */ }
    if (!res.ok) {
      const message = res.status === 401
        ? 'the eval API requires a session — sign in at /signin first'
        : (data && data.error ? data.error.message : `${res.status} ${res.statusText}`);
      const err = new Error(message);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function toast(message, isError) {
    const box = $('estate');
    if (!message) { box.hidden = true; box.textContent = ''; return; }
    box.hidden = false;
    box.textContent = message;
    box.style.color = isError ? 'var(--red)' : 'var(--ink)';
  }

  let runs = [];
  let selectedRun = null;
  let probeQuery = '';
  let probeMarks = new Set();

  async function load() {
    try {
      runs = (await api('/api/evals/runs')).items;
      if (runs.length) {
        const targetId = selectedRun && runs.some(r => r.id === selectedRun.id)
          ? selectedRun.id : runs[runs.length - 1].id;
        selectedRun = await api(`/api/evals/runs/${targetId}`);
      } else {
        selectedRun = null;
      }
      toast(null);
    } catch (e) {
      toast(`Evals unavailable: ${e.message}`, true);
      return;
    }
    renderMetrics();
    renderBars();
    await renderGolden();
  }

  function renderMetrics() {
    const box = $('emetrics');
    const label = $('runlabel');
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
      if (p === null || p === undefined || v === null || v === undefined) return '';
      const d = v - p, sign = d > 0 ? '+' : '';
      return `<span class="delta" style="color:${d >= 0 ? 'var(--good)' : 'var(--red)'}">${sign}${d.toFixed(dp)}</span>`;
    };
    box.innerHTML = [
      [r.hit_rate.toFixed(2), `Hit@${r.k}`, delta(r.hit_rate, prev?.hit_rate)],
      [r.mrr.toFixed(2), 'MRR', delta(r.mrr, prev?.mrr)],
      [r.p50_ms !== null ? r.p50_ms + ' ms' : '—', 'p50 latency', delta(r.p50_ms, prev?.p50_ms, 0)],
      [String(r.n), 'Queries', ''],
    ].map(m => `<div class="tile"><div class="k">${m[1]}</div><div class="v">${m[0]}${m[2]}</div></div>`).join('');
  }

  function renderBars() {
    const bars = $('bars');
    const blank = $('barsblank');
    blank.hidden = !!runs.length;
    if (!runs.length) { bars.innerHTML = ''; return; }
    const hmax = Math.max(...runs.map(x => x.hit_rate), 0.01) * 1.1;
    bars.innerHTML = runs.map(x =>
      `<button class="ebar${selectedRun && x.id === selectedRun.id ? ' sel' : ''}" data-id="${x.id}"
            style="height:${Math.max(6, x.hit_rate / hmax * 100)}%"
            data-v="${x.hit_rate.toFixed(2)}" title="${esc(x.label)} · ${esc(String(x.created_at).slice(0, 16))}"></button>`).join('');
    bars.querySelectorAll('.ebar').forEach(b => b.onclick = async () => {
      selectedRun = await api(`/api/evals/runs/${b.dataset.id}`);
      renderMetrics(); renderBars(); renderGolden();
    });
  }

  async function renderGolden() {
    const box = $('golden');
    let golden;
    try {
      golden = (await api('/api/evals/golden')).items;
    } catch (e) {
      box.innerHTML = `<div class="blank" style="color:var(--red)">${esc(e.message)}</div>`;
      return;
    }
    if (!golden.length) {
      box.innerHTML = '<div class="blank">Golden set is empty — add queries from the probe</div>';
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
        </div>
        <div class="gdetail" data-i="${i}">
          ${pq ? pq.retrieved.map((s, j) => `
            <div class="prow${g.relevant.includes(s) ? ' gold' : ''}" style="grid-template-columns:26px 1fr">
              <span class="rank">${j + 1}</span>
              <span class="rn">${esc(s)}</span>
            </div>`).join('') : '<div class="blank">Not part of the selected run — run the eval again</div>'}
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
    const btn = $('runeval');
    btn.disabled = true; btn.textContent = 'Running…';
    let started;
    try {
      started = await api('/api/evals/run', { method: 'POST', body: {} });
    } catch (e) {
      toast(e.message, true);
      btn.disabled = false; btn.textContent = 'Run eval';
      return;
    }
    // no SSE on the dev page — poll the job until it settles
    const poll = setInterval(async () => {
      let job;
      try {
        job = await api(`/api/jobs/${started.job_id}`);
      } catch { return; }
      if (['done', 'failed', 'cancelled'].includes(job.status)) {
        clearInterval(poll);
        btn.disabled = false; btn.textContent = 'Run eval';
        if (job.status === 'failed') toast(`Eval failed: ${job.error}`, true);
        load();
      }
    }, 1200);
  }

  let probeTimer = null;

  async function renderProbe() {
    probeQuery = $('probe').value.trim();
    probeMarks = new Set();
    const out = $('probeout');
    const foot = $('probefoot');
    if (!probeQuery) {
      out.innerHTML = '<div class="blank">Enter a query to see what retrieval returns</div>';
      foot.hidden = true;
      return;
    }
    out.innerHTML = '<div class="blank">Retrieving…</div>';
    let res;
    try {
      res = await api('/api/retrieve', { method: 'POST', body: { query: probeQuery, k: 5 } });
    } catch (e) {
      out.innerHTML = `<div class="blank" style="color:var(--red)">${esc(e.message)}</div>`;
      foot.hidden = true;
      return;
    }
    if (!res.hits.length) {
      out.innerHTML = '<div class="blank">Nothing retrieved</div>';
      foot.hidden = true;
      return;
    }
    out.innerHTML = res.hits.map((h, i) => `
      <div class="prow">
        <span class="rank">${i + 1}</span>
        <span class="rn" title="${esc(h.chunk.slice(0, 200))}">${esc(h.source)} <span class="dim">· ${esc(h.domain)}</span></span>
        <span class="rs">${h.score.toFixed(2)}</span>
        <button class="mk" data-s="${esc(h.source)}" aria-pressed="false" title="Mark as correct">✓</button>
      </div>`).join('');
    out.querySelectorAll('.mk').forEach(b => b.onclick = () => {
      const on = b.getAttribute('aria-pressed') === 'true';
      b.setAttribute('aria-pressed', String(!on));
      on ? probeMarks.delete(b.dataset.s) : probeMarks.add(b.dataset.s);
      $('probemeta').textContent = `${probeMarks.size} marked correct`;
    });
    foot.hidden = false;
    $('probemeta').textContent = `${res.latency_ms} ms · mark which results are correct`;
  }

  async function saveProbe() {
    if (!probeQuery || !probeMarks.size) return;
    try {
      await api('/api/evals/golden', {
        method: 'POST',
        body: { query: probeQuery, relevant: [...probeMarks], source: 'probe' },
      });
    } catch (e) {
      $('probemeta').textContent = e.message;
      return;
    }
    $('probe').value = '';
    probeQuery = ''; probeMarks = new Set();
    $('probeout').innerHTML = '<div class="blank">Added to the golden set</div>';
    $('probefoot').hidden = true;
    renderGolden();
  }

  $('runeval').onclick = runEval;
  $('probesave').onclick = saveProbe;
  $('probe').addEventListener('input', () => {
    clearTimeout(probeTimer);
    probeTimer = setTimeout(renderProbe, 350);
  });
  load();
})();

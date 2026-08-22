/* Pipeline view — the real pre-production loop. Concepts awaiting a
   decision (approve = plan the shot list, the shortlist label; deny =
   reasons + note recorded as a correction and a RAG feedback chunk),
   the hold queue underneath, and the agreement numbers that gate
   autonomy. */
import { api, bus, esc, pct, state, stateline } from './shared.js';

let denyTarget = null;
let denyReasons = new Set();
let wired = false;

export function initPipeline() {
  if (wired) return;
  wired = true;
  const dscrim = document.getElementById('dscrim');
  document.getElementById('dncancel').onclick = closeDeny;
  document.getElementById('dnback').onclick = closeDeny;
  dscrim.onclick = closeDeny;
  document.getElementById('dnsave').onclick = saveDeny;
  // re-render when a generate/plan job lands while the view is open
  bus.addEventListener('job', e => {
    const job = e.detail;
    if (document.documentElement.dataset.v === 'pipeline'
        && ['concept', 'plan'].includes(job.kind)
        && ['done', 'failed'].includes(job.status)) {
      renderPipeline();
    }
  });
}

export async function renderPipeline() {
  document.getElementById('pbrand').textContent = `brand · ${state.brand}`;
  await Promise.all([renderConcepts(), renderHolds()]);
}

async function renderConcepts() {
  const cstate = document.getElementById('cstate');
  const box = document.getElementById('concepts');
  stateline(cstate, 'loading', 'Loading concepts…');
  let data;
  try {
    data = await api(`/api/pipeline/concepts?brand=${encodeURIComponent(state.brand)}`);
  } catch (e) {
    box.innerHTML = '';
    stateline(cstate, 'error', `Concepts unavailable: ${e.message}`, renderConcepts);
    return;
  }
  stateline(cstate, null);
  state.denyReasons = data.deny_reasons;

  const ideas = data.items.filter(c => c.status === 'idea');
  document.getElementById('ccount').textContent =
    `${ideas.length} awaiting review · ${data.items.length} total`;

  // shortlist / shoot rates — the two labels, straight from the API
  const sl = data.shortlist, sh = data.shoot;
  document.getElementById('pmetrics').innerHTML = [
    [sl.rate === null ? '—' : pct(sl.rate), `Shortlist rate · ${sl.shortlisted}/${sl.generated}`],
    [sh.rate === null ? '—' : pct(sh.rate), `Shoot rate · ${sh.shot}/${sh.generated}`],
  ].map(([v, l]) => `<div class="metric"><div class="mv">${v}</div><div class="md">${esc(l)}</div></div>`).join('');

  if (!data.items.length) {
    box.innerHTML = '';
    stateline(cstate, 'empty', 'No concepts yet — type a spark in the Studio composer and hit Create');
    return;
  }

  const canPlan = state.caps['pipeline.run'];
  box.innerHTML = data.items.slice(0, 12).map(c => `
    <div class="concept${c.status !== 'idea' ? ' approved' : ''}" data-id="${c.id}">
      <div class="cn">${esc(c.n)} · ${c.status === 'idea' ? 'idea' : c.shot_count + ' shots'}${c.ai_shot_count ? ' · ' + c.ai_shot_count + ' ai' : ''}</div>
      <h4>${esc(c.title)}</h4>
      <div class="clog">${esc(c.logline || c.hook || '')}</div>
      ${c.grounded.length ? `<div class="cplates">${c.grounded.map(g =>
        g.poster ? `<div class="th" style="background-image:url('${g.poster}')" title="${esc(g.name)}"></div>`
                 : `<span class="m">${esc(g.name)}</span>`).join('')}<span class="m">grounded</span></div>` : ''}
      ${c.warnings.length ? `<div class="cwarn">${c.warnings.map(w => '⚠ ' + esc(w)).join('<br>')}</div>` : ''}
      ${c.status === 'idea'
        ? `<div class="cact">
             ${canPlan ? `<button class="approve" data-a="ok" data-id="${c.id}">Approve · plan shots</button>` : ''}
             <button class="denybtn" data-a="no" data-id="${c.id}">Deny</button>
           </div>`
        : `<div class="cstate"><span class="dot ${c.status === 'shot' ? 'ok' : 'run'}"></span>${
             c.status === 'shot' ? 'Shot' : 'Planned · ready to shoot'}</div>`}
    </div>`).join('');

  box.querySelectorAll('[data-a]').forEach(b => {
    b.onclick = () => b.dataset.a === 'ok' ? approve(+b.dataset.id) : openDeny(+b.dataset.id, data.items);
  });

  // planned shortlist panel
  const planned = data.items.filter(c => c.status !== 'idea');
  document.getElementById('planned').innerHTML = planned.length
    ? planned.map(c => `
        <div class="trow" style="grid-template-columns:1fr 110px 90px">
          <span class="q">${esc(c.title)}</span>
          <span class="v">${c.shot_count} shots</span>
          <span class="v">${c.status === 'shot' ? 'shot ✓' : 'planned'}</span>
        </div>`).join('')
    : '<div class="probeblank">Nothing planned yet</div>';
}

async function approve(id) {
  try {
    await api(`/api/concepts/${id}/approve`, { method: 'POST', body: {} });
    const card = document.querySelector(`.concept[data-id="${id}"]`);
    if (card) {
      const act = card.querySelector('.cact');
      if (act) act.outerHTML = '<div class="cstate"><span class="dot run"></span>Planning shot list…</div>';
    }
  } catch (e) {
    stateline(document.getElementById('cstate'), 'error', e.message, renderConcepts);
  }
}

function openDeny(id, items) {
  denyTarget = items.find(c => c.id === id);
  denyReasons = new Set();
  document.getElementById('dntitle').textContent = 'Deny · ' + denyTarget.title;
  document.getElementById('dnnote').value = '';
  document.getElementById('dnmeta').textContent =
    `${denyTarget.n} · correction + rag chunk`;
  const reasons = document.getElementById('reasons');
  reasons.innerHTML = state.denyReasons.map(r =>
    `<button class="reason" aria-pressed="false" data-r="${esc(r)}">${esc(r)}</button>`).join('');
  reasons.querySelectorAll('.reason').forEach(b => b.onclick = () => {
    const on = b.getAttribute('aria-pressed') === 'true';
    b.setAttribute('aria-pressed', String(!on));
    on ? denyReasons.delete(b.dataset.r) : denyReasons.add(b.dataset.r);
  });
  document.getElementById('dscrim').setAttribute('data-open', '');
  document.getElementById('deny').setAttribute('data-open', '');
}

export function closeDeny() {
  document.getElementById('dscrim').removeAttribute('data-open');
  document.getElementById('deny').removeAttribute('data-open');
  denyTarget = null;
}

async function saveDeny() {
  if (!denyTarget) return closeDeny();
  if (!denyReasons.size) {
    document.getElementById('dnmeta').textContent = 'pick at least one reason';
    return;
  }
  const btn = document.getElementById('dnsave');
  btn.disabled = true;
  try {
    const res = await api(`/api/concepts/${denyTarget.id}/deny`, {
      method: 'POST',
      body: { reasons: [...denyReasons], note: document.getElementById('dnnote').value.trim() || null },
    });
    closeDeny();
    const note = res.chunks_written
      ? `Recorded — correction #${res.correction_id}, ${res.chunks_written} chunk(s) to rag`
      : `Recorded correction #${res.correction_id} — rag chunk failed: ${res.chunk_error}`;
    stateline(document.getElementById('cstate'), res.chunks_written ? 'empty' : 'error', note);
    setTimeout(renderConcepts, 1400);
  } catch (e) {
    document.getElementById('dnmeta').textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function renderHolds() {
  const hstate = document.getElementById('hstate');
  const box = document.getElementById('holds');
  let data;
  try {
    data = await api(`/api/holds?channel=${encodeURIComponent(state.brand)}`);
  } catch (e) {
    box.innerHTML = '';
    stateline(hstate, 'error', `Holds unavailable: ${e.message}`, renderHolds);
    return;
  }
  stateline(hstate, null);

  // agreement metrics join the two shortlist cards
  const ag = data.agreement, gate = data.gate, pr = data.pass_rate;
  const extra = [
    [ag.agreement === null ? '—' : pct(ag.agreement), `Evaluator agreement · ${ag.graded} graded`],
    [gate.agreement === null ? '—' : pct(gate.agreement), `Gate agreement · ${gate.graded} graded`],
    [pr.rate === null ? '—' : pct(pr.rate), `First-try pass · ${pr.passed}/${pr.total}`],
  ].map(([v, l]) => `<div class="metric"><div class="mv">${v}</div><div class="md">${esc(l)}</div></div>`).join('');
  document.getElementById('pmetrics').insertAdjacentHTML('beforeend', extra);
  if (data.killed) {
    document.getElementById('pmetrics').insertAdjacentHTML('beforeend',
      '<div class="metric"><div class="mv" style="color:var(--signal)">KILL</div><div class="md">Global kill switch is ON</div></div>');
  }

  box.innerHTML = data.items.length
    ? data.items.map(h => `
        <div class="holdrow" data-id="${h.id}">
          <span class="dot run"></span>
          <div>
            <div>${esc(h.reason)}</div>
            <div class="hm">${esc(h.channel)} · ${esc(String(h.created_at).slice(0, 16))}${h.caption ? ' · ' + esc(h.caption.slice(0, 60)) : ''}</div>
          </div>
          <div class="hact">
            <button class="hbtn ok" data-s="approved">Approve</button>
            <button class="hbtn no" data-s="rejected">Reject</button>
          </div>
          <span></span>
        </div>`).join('')
    : '<div class="probeblank">Nothing held — the queue is clear</div>';
  box.querySelectorAll('.hbtn').forEach(b => b.onclick = async () => {
    const row = b.closest('.holdrow');
    try {
      await api(`/api/holds/${row.dataset.id}/resolve`,
        { method: 'POST', body: { status: b.dataset.s } });
      renderPipeline();
    } catch (e) {
      stateline(hstate, 'error', e.message, renderHolds);
    }
  });
}

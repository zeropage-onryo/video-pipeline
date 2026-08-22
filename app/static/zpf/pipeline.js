/* Pipeline view — the real pre-production loop. Concepts awaiting a
   decision (approve = plan the shot list, the shortlist label; deny =
   reasons + note recorded as a correction and a RAG feedback chunk),
   the hold queue underneath, and the agreement numbers that gate
   autonomy. */
import { api, bus, esc, pct, state, stateline } from './shared.js';

let denyTarget = null;
let denyReasons = new Set();
let wired = false;
let openSceneId = null;   // which concept's scene board is open

export function initPipeline() {
  if (wired) return;
  wired = true;
  const dscrim = document.getElementById('dscrim');
  document.getElementById('dncancel').onclick = closeDeny;
  document.getElementById('dnback').onclick = closeDeny;
  dscrim.onclick = closeDeny;
  document.getElementById('dnsave').onclick = saveDeny;

  // the scene composer — same billed path as Studio's Create
  const scenePrompt = document.getElementById('sceneprompt');
  const sceneGo = document.getElementById('scenego');
  const fire = async () => {
    const text = scenePrompt.value.trim();
    if (!text) return;
    sceneGo.disabled = true; sceneGo.textContent = 'Generating…';
    try {
      await api('/api/pipeline/run', { method: 'POST', body: { prompt: text } });
      scenePrompt.value = '';
      stateline(document.getElementById('cstate'), 'empty',
        'Scene generating — it lands below when the job finishes');
    } catch (e) {
      stateline(document.getElementById('cstate'), 'error', e.message);
    } finally {
      sceneGo.disabled = false; sceneGo.textContent = 'Generate scene';
    }
  };
  sceneGo.onclick = fire;
  scenePrompt.addEventListener('keydown', e => { if (e.key === 'Enter') fire(); });

  // re-render when a generate/plan job lands while the view is open;
  // a finished plan opens its scene board so the prompts are right there
  bus.addEventListener('job', e => {
    const job = e.detail;
    if (document.documentElement.dataset.v === 'pipeline'
        && ['concept', 'plan', 'render'].includes(job.kind)
        && ['done', 'failed'].includes(job.status)) {
      if (job.status === 'done' && job.ref_id) openSceneId = job.ref_id;
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
        : `<div class="cact">
             <button class="approve" data-a="scene" data-id="${c.id}">Open scene · ${c.shot_count} shots</button>
           </div>`}
    </div>`).join('');

  box.querySelectorAll('[data-a]').forEach(b => {
    b.onclick = () => {
      if (b.dataset.a === 'ok') return approve(+b.dataset.id);
      if (b.dataset.a === 'scene') return openScene(+b.dataset.id);
      openDeny(+b.dataset.id, data.items);
    };
  });

  // a board that was open (or just planned) re-opens after re-render
  if (openSceneId && data.items.some(c => c.id === openSceneId && c.status !== 'idea')) {
    openScene(openSceneId, false);
  } else if (openSceneId) {
    openSceneId = null;
    document.getElementById('sceneboard').innerHTML = '';
  }

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

/* ── the scene board: shot-by-shot prompts out, clip URLs back in ── */

async function openScene(id, scroll = true) {
  const board = document.getElementById('sceneboard');
  openSceneId = id;
  let d;
  try {
    d = await api(`/api/concepts/${id}`);
  } catch (e) {
    board.innerHTML = `<div class="stateline err">${esc(e.message)}</div>`;
    return;
  }
  const clips = d.shots.filter(s => s.media_url).length;
  const isClip = u => /\.(mp4|mov|webm|m4v)(\?|$)/i.test(u || '');

  board.innerHTML = `<div class="sboard">
    <div class="sbhead">
      <h3>${esc(d.title)}</h3>
      <span class="m">${esc(d.n)}${d.duration ? ' · ' + esc(d.duration) : ''} · ${clips}/${d.shots.length} clips attached</span>
      <button class="x" id="sbclose">✕</button>
    </div>
    <div class="sbsub">${esc(d.logline || '')}${d.edit_note ? ' — ' + esc(d.edit_note) : ''}</div>
    <div class="filmstrip">${d.shots.map(s => s.media_url
      ? `<div class="ftile has">${isClip(s.media_url)
          ? `<video src="${esc(s.media_url)}" muted preload="metadata"></video>`
          : `clip ${s.n}`}</div>`
      : `<div class="ftile pending">shot ${esc(String(s.n))}</div>`).join('')}</div>
    <div class="shotrows">${d.shots.map(s => shotRow(s, d.runway)).join('')}</div>
  </div>`;

  document.getElementById('sbclose').onclick = () => {
    openSceneId = null;
    board.innerHTML = '';
  };

  board.querySelectorAll('.copybtn').forEach(b => b.onclick = async () => {
    const pre = board.querySelector(`pre[data-p="${b.dataset.p}"]`);
    try {
      await navigator.clipboard.writeText(pre.textContent);
      b.textContent = 'Copied'; b.classList.add('ok');
      setTimeout(() => { b.textContent = 'Copy'; b.classList.remove('ok'); }, 1600);
    } catch { b.textContent = 'select + ⌘C'; }
  });
  board.querySelectorAll('.dirtoggle').forEach(b => b.onclick = () => {
    const blk = board.querySelector(`.promptblk[data-d="${b.dataset.d}"]`);
    blk.hidden = !blk.hidden;
    b.textContent = blk.hidden ? '▸ director prompt (openart)' : '▾ director prompt (openart)';
  });
  board.querySelectorAll('.rgen').forEach(b => b.onclick = async () => {
    const label = b.textContent;
    b.disabled = true; b.textContent = 'Rendering…';
    try {
      await api(`/api/concepts/${id}/shots/${b.dataset.m}/generate`,
        { method: 'POST', body: {} });
      b.textContent = 'Rendering — watch the job rail';
      // the render job's completion re-opens the board via the job bus
    } catch (e) {
      b.disabled = false;
      b.textContent = label;
      stateline(document.getElementById('cstate'), 'error', e.message);
    }
  });
  board.querySelectorAll('.attach').forEach(b => b.onclick = async () => {
    const input = board.querySelector(`input[data-m="${b.dataset.m}"]`);
    const url = input.value.trim();
    if (!url) return;
    b.disabled = true; b.textContent = '…';
    try {
      await api(`/api/concepts/${id}/shots/${b.dataset.m}/media`,
        { method: 'POST', body: { url } });
      openScene(id, false);           // re-read: server truth, never optimistic
      renderConcepts();
    } catch (e) {
      b.disabled = false; b.textContent = 'Attach';
      input.value = ''; input.placeholder = e.message;
    }
  });
  if (scroll) board.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function shotRow(s, rw) {
  const isAI = s.source === 'AI';
  const isClip = /\.(mp4|mov|webm|m4v)(\?|$)/i.test(s.media_url || '');
  return `<div class="shotrow">
    <div class="shothead">
      <span class="sn2">Shot ${esc(String(s.n))}</span>
      <span class="pill">${esc(s.type || '')}</span>
      <span class="pill${isAI ? ' ai' : ''}">${isAI ? 'AI · ' + esc(s.tool || '?') : 'camera · ' + esc(s.cam || '?')}</span>
      ${s.location ? `<span class="pill">${esc(s.location)}</span>` : ''}
      ${s.media_url ? '<span class="pill clip">clip attached</span>' : ''}
    </div>
    ${s.desc ? `<div class="shotdesc">${esc(s.desc)}</div>` : ''}
    ${s.light ? `<div class="shotlight">light · ${esc(s.light)}</div>` : ''}
    ${isAI && s.prompt ? `
      <div class="promptblk">
        <div class="plabel">${esc(s.tool || 'ai')} prompt — paste into the tool</div>
        <pre data-p="t${esc(String(s.n))}">${esc(s.prompt)}</pre>
        <button class="copybtn" data-p="t${esc(String(s.n))}">Copy</button>
      </div>
      ${rw && rw.available ? `
        <div class="mediarow" style="margin-top:10px">
          <button class="btn pri rgen" data-m="${esc(String(s.n))}" ${rw.spend_ok ? '' : 'disabled'}>
            Render via Runway API · ${esc(rw.model)} · ~$${rw.estimate_usd.toFixed(2)}</button>
          <span class="m">${rw.spend_ok
            ? (s.reference_image ? 'anchors on the attached reference' : 'text-to-video · no reference attached')
            : 'spend gate off — restart the server with RUNWAY_SPEND_OK=1, or render free in the Runway app'}</span>
        </div>` : ''}` : ''}
    ${s.director_prompt ? `
    <button class="dirtoggle" data-d="d${esc(String(s.n))}">▸ director prompt (openart)</button>
    <div class="promptblk" data-d="d${esc(String(s.n))}" hidden>
      <pre data-p="d${esc(String(s.n))}">${esc(s.director_prompt)}</pre>
      <button class="copybtn" data-p="d${esc(String(s.n))}" style="top:10px">Copy</button>
    </div>` : ''}
    ${s.media_url ? `
      <div class="clipview">
        ${isClip ? `<video src="${esc(s.media_url)}" controls preload="metadata"></video>` : ''}
        <a href="${esc(s.media_url)}" target="_blank" rel="noopener">${esc(s.media_url)}</a>
      </div>` : ''}
    <div class="mediarow">
      <input class="search" data-m="${esc(String(s.n))}"
             placeholder="${s.media_url ? 'Replace the clip — paste a new public URL' : 'Paste the rendered clip’s public URL (Runway export, R2…)'}">
      <button class="btn attach" data-m="${esc(String(s.n))}">Attach</button>
    </div>
  </div>`;
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

/* Queue: the approval gate, then the job registry.

   Rendering is the only step in this pipeline that spends real money,
   so it is the only one with a gate in front of it (2026-08-28).
   A scene arrives here two ways: the Studio chain PARKS it once it has
   a concept, an enhanced prompt and a keyframe -- everything that can
   be done without spending -- or you pick a text-only concept off the
   Pipeline board yourself. Approving is what actually calls Runway,
   and on a parked scene approving is also the pick.

   The pending list is derived from the rows (parked or picked, not
   archived, no clip yet) rather than from the jobs registry -- the registry is an
   in-process dict that a restart clears, and an approval queue that
   quietly emptied itself on restart would be a queue that lies. The
   Jobs list underneath IS that registry, and says so. */
import { api, bus, esc, state, stateline } from './shared.js';

let wired = false;

const $ = id => document.getElementById(id);

export function initQueue() {
  if (wired) return;
  wired = true;
  bus.addEventListener('job', e => {
    if (document.documentElement.dataset.v !== 'queue') return;
    paint();
    // a finished render leaves the pending list, so re-read the rows
    if (['done', 'failed'].includes(e.detail.status)) renderPending();
  });
}

export async function renderQueue() {
  await Promise.all([renderPending(), renderJobs()]);
}

/* ── awaiting approval ── */

async function renderPending() {
  const list = $('pendlist');
  let data;
  stateline($('pendstate'), 'loading', 'Loading…');
  try {
    data = await api('/api/queue/pending?brand=' + encodeURIComponent(state.brand));
  } catch (e) {
    list.innerHTML = '';
    stateline($('pendstate'), 'error', `Queue unavailable: ${e.message}`, renderPending);
    return;
  }
  stateline($('pendstate'), null);

  const rw = data.runway || {};
  // the spend gate, stated honestly rather than shown as a dead button
  $('rwstate').textContent = !rw.available
    ? 'Runway key not set — approving cannot render'
    : !rw.spend_ok
      ? 'spend gate off — restart with RUNWAY_SPEND_OK=1'
      : `${esc(rw.model)} · ~$${(rw.estimate_usd || 0).toFixed(2)} a clip`
        + (rw.today === null || rw.today === undefined ? '' : ` · ${rw.today} today`);

  const canRender = rw.available && rw.spend_ok;
  $('pendcount').textContent = `${data.items.length} waiting`;

  list.innerHTML = data.items.length ? data.items.map(c => {
    const refs = (c.refs || []).map(url =>
      `<span class="scref" style="background-image:url('${esc(url)}')"></span>`).join('');
    return `
    <article class="glass scene on" data-id="${c.id}">
      <div class="screfs">
        ${refs || '<span class="m">no references</span>'}
        <span class="spacer"></span>
        <span class="m">${esc(c.spark || '')}</span>
      </div>
      <div class="schead">
        <h4>${esc(c.title)}</h4>
        <span class="m">${esc(c.n || '')}</span>
        <span class="spacer"></span>
        <span class="m">${c.parked ? 'READY · AWAITING APPROVAL' : 'PICKED'}</span>
      </div>
      ${c.reference_image
        ? `<img class="scshot" src="${esc(c.reference_image)}" alt="">` : ''}
      <p class="scprompt">${esc(c.prompt)}</p>
      <div class="scfoot">
        <button class="tag" data-act="reject">Reject</button>
        <span class="m">${c.reference_image
          ? 'anchors on the keyframe above'
          : esc(c.park_reason || 'text-to-video · no reference attached')}</span>
        <span class="spacer"></span>
        <button class="go" data-act="approve" ${canRender ? '' : 'disabled'}>
          ${canRender ? `Approve · render ~$${(rw.estimate_usd || 0).toFixed(2)}` : 'Approve · render'}
        </button>
      </div>
    </article>`;
  }).join('')
    : '<div class="probeblank">Nothing waiting — a Studio run lands here once its keyframe is rendered, or pick a concept on Pipeline</div>';

  list.querySelectorAll('.scene').forEach(el => {
    const id = Number(el.dataset.id);
    el.querySelectorAll('[data-act]').forEach(btn => btn.onclick = async () => {
      const approve = btn.dataset.act === 'approve';
      btn.disabled = true;
      btn.textContent = approve ? 'Rendering…' : '…';
      try {
        await api(`/api/queue/${id}/${approve ? 'approve' : 'reject'}`,
          { method: 'POST', body: {} });
        renderPending();
      } catch (e) {
        btn.disabled = false;
        btn.textContent = approve ? 'Approve · render' : 'Reject';
        stateline($('pendstate'), 'error', e.message);
      }
    });
  });
}

/* ── the job registry ── */

async function renderJobs() {
  const qstate = $('qstate');
  try {
    const data = await api('/api/jobs');
    state.jobs.clear();
    data.items.forEach(j => state.jobs.set(j.id, j));
    stateline(qstate, null);
  } catch (e) {
    stateline(qstate, 'error', `Jobs unavailable: ${e.message}`, renderJobs);
    return;
  }
  paint();
}

function paint() {
  const items = [...state.jobs.values()].sort((a, b) => b.id - a.id);
  const running = items.filter(j => ['queued', 'running'].includes(j.status)).length;
  $('qcount').textContent = `${running} running · ${items.length} total`;
  const box = $('qlist');
  if (!items.length) {
    box.innerHTML = '<div class="probeblank" style="padding-left:0">Nothing queued — jobs appear here when you create, approve, or run an eval. The queue clears on restart.</div>';
    return;
  }
  box.innerHTML = items.map(j => {
    const active = ['queued', 'running'].includes(j.status);
    const dot = j.status === 'failed' ? 'run' : active ? 'run' : 'ok';
    const action = active
      ? (j.cancellable ? `<button class="qx" data-a="cancel" data-id="${j.id}">Cancel</button>` : '<span class="m">running</span>')
      : `<button class="qx" data-a="clear" data-id="${j.id}">Clear</button>`;
    return `<div class="qrow">
      <span class="dot ${dot}"></span>
      <div>
        <div class="qn">${esc(j.label)}</div>
        <div class="qm">${esc(j.kind)} · ${esc(j.status)}${j.detail ? ' · ' + esc(j.detail) : ''}${j.error ? ' · ' + esc(j.error) : ''}</div>
      </div>
      <div class="qbar"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>
      <span class="qt">${esc(j.status)}</span>
      ${action}
    </div>`;
  }).join('');
  box.querySelectorAll('.qx').forEach(b => b.onclick = async () => {
    try {
      if (b.dataset.a === 'cancel') {
        await api(`/api/jobs/${b.dataset.id}/cancel`, { method: 'POST', body: {} });
      } else {
        await api(`/api/jobs/${b.dataset.id}`, { method: 'DELETE' });
        state.jobs.delete(+b.dataset.id);
      }
      paint();
    } catch (e) {
      stateline($('qstate'), 'error', e.message, renderJobs);
    }
  });
}

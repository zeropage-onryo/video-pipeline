/* Queue view: the jobs registry, live over the same SSE feed as the
   rail. Cancel renders only for jobs that can actually be cancelled. */
import { api, bus, esc, state, stateline } from './shared.js';

let wired = false;

export function initQueue() {
  if (wired) return;
  wired = true;
  bus.addEventListener('job', () => {
    if (document.documentElement.dataset.v === 'queue') paint();
  });
}

export async function renderQueue() {
  const qstate = document.getElementById('qstate');
  try {
    const data = await api('/api/jobs');
    state.jobs.clear();
    data.items.forEach(j => state.jobs.set(j.id, j));
    stateline(qstate, null);
  } catch (e) {
    stateline(qstate, 'error', `Jobs unavailable: ${e.message}`, renderQueue);
    return;
  }
  paint();
}

function paint() {
  const items = [...state.jobs.values()].sort((a, b) => b.id - a.id);
  const running = items.filter(j => ['queued', 'running'].includes(j.status)).length;
  document.getElementById('qcount').textContent = `${running} running · ${items.length} total`;
  const box = document.getElementById('qlist');
  if (!items.length) {
    box.innerHTML = '<div class="probeblank" style="padding-left:0">Nothing queued — jobs appear here when you create, plan, or run an eval. The queue clears on restart.</div>';
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
      stateline(document.getElementById('qstate'), 'error', e.message, renderQueue);
    }
  });
}

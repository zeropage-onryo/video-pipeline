/* Renderer keys — bring your own, per account.

   2026-09-12. src/account_keys.py has held encrypted per-account
   credentials since 2026-09-03 and had no front door: the only way in was
   `python -m src.account_keys set` on the server, so a pilot user could
   not bring a key at all and every render they approved billed the
   operator's. This panel is that door, on the Queue, because the Queue is
   where a missing key is discovered.

   IT NEVER SHOWS A KEY. The server does not return one -- not masked,
   not truncated -- so this file has nothing to render but WHOSE
   credential would pay (this account's, the operator's environment, or
   nothing) and when it was stored. A field that has just been typed into
   is cleared the moment it is saved, so the page never holds a secret
   longer than the request. */
import { api, esc, stateline } from './shared.js';

const $ = id => document.getElementById(id);

/* The mutation header model_connections established: the session cookie
   is SameSite=None on the hosted deployment, so a form on another origin
   could POST a key onto somebody's account. A custom header forces a
   CORS preflight; the route refuses without it. */
const KEY_HEADER = { 'x-zpf-renderer-key': '1' };

let items = [];
let wired = false;

function sourceLine(item) {
  if (item.source === 'account') {
    return `your key${item.stored_at ? ' · saved ' + esc(String(item.stored_at).slice(0, 10)) : ''}`;
  }
  if (item.source === 'env') return "the studio's own key";
  return 'no key — approving refuses';
}

function card(item) {
  const fields = item.fields.map((f, i) => `
    <label class="keyfield">
      <span class="m">${esc(f.label)}</span>
      <input type="password" autocomplete="off" spellcheck="false"
             data-field="${i}" placeholder="paste to replace">
    </label>`).join('');
  // the env var names are the answer to "why does this say the studio's
  // key" and to "what do I set on a server instead of typing here"
  const env = (item.env_names || []).map(names => names[0]).filter(Boolean).join(' · ');
  return `
    <div class="keycard${item.source ? '' : ' off'}" data-provider="${esc(item.provider)}">
      <div class="keyhead">
        <strong>${esc(item.label)}</strong>
        <span class="spacer"></span>
        <span class="m keysource">${sourceLine(item)}</span>
      </div>
      ${fields}
      <div class="keyfoot">
        <button class="go" data-act="save">Save key</button>
        ${item.source === 'account'
          ? '<button class="tag" data-act="clear">Remove</button>' : ''}
        <span class="spacer"></span>
        <span class="m">${env ? 'server env: ' + esc(env) : ''}</span>
      </div>
    </div>`;
}

function paint() {
  const list = $('keyslist');
  if (!list) return;
  list.innerHTML = items.map(card).join('');
  const mine = items.filter(i => i.source === 'account').length;
  const ready = items.filter(i => i.source).length;
  $('keyssummary').textContent =
    `Renderer keys — ${ready} of ${items.length} ready${mine ? `, ${mine} yours` : ''}`;
}

export async function renderRendererKeys() {
  if (!$('keyslist')) return;
  try {
    items = (await api('/api/renderer-keys')).items || [];
    stateline($('keysstate'), null);
    paint();
  } catch (e) {
    stateline($('keysstate'), 'error', e.message, renderRendererKeys);
  }
  if (wired) return;
  wired = true;
  $('keyslist').addEventListener('click', async ev => {
    const button = ev.target.closest('button[data-act]');
    if (!button) return;
    const card = button.closest('.keycard');
    const provider = card.dataset.provider;
    const inputs = [...card.querySelectorAll('input[data-field]')];
    button.disabled = true;
    try {
      const saved = button.dataset.act === 'save'
        ? await api(`/api/renderer-keys/${provider}`,
                    { method: 'PUT', headers: { ...KEY_HEADER },
                      body: { values: inputs.map(i => i.value) } })
        : await api(`/api/renderer-keys/${provider}`,
                    { method: 'DELETE', headers: { ...KEY_HEADER } });
      // the typed secret leaves the page the moment it is stored
      inputs.forEach(i => { i.value = ''; });
      items = items.map(i => (i.provider === provider ? saved : i));
      stateline($('keysstate'), 'ok',
                `${saved.label}: ${sourceLine(saved)}. The Queue picks it up on the next reload.`);
      paint();
    } catch (e) {
      button.disabled = false;
      stateline($('keysstate'), 'error', e.message);
    }
  });
}

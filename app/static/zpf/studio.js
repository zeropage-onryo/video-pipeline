/* Studio view: the composer with live RAG grounding, and the asset
   carousel. Create posts /api/pipeline/run and routes to Pipeline. */
import { api, esc, loadAssets, openAssetDetail, state, stateline, wireScrub } from './shared.js';

const promptEl = () => document.getElementById('prompt');
let debounceTimer = null;
let railFilter = 'all';

export function initStudio(go) {
  const prompt = promptEl();
  const goBtn = document.getElementById('go');
  const cbox = document.getElementById('cbox');

  prompt.addEventListener('focus', () => cbox.classList.add('awake'));
  prompt.addEventListener('blur', () => cbox.classList.remove('awake'));
  prompt.addEventListener('input', () => {
    goBtn.disabled = !prompt.value.trim();
    if (!state.caps.retrieve) return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(retrieve, 300);
  });

  goBtn.addEventListener('click', async () => {
    const text = prompt.value.trim();
    if (!text) return;
    goBtn.disabled = true;
    goBtn.textContent = 'Creating…';
    try {
      await api('/api/pipeline/run', { method: 'POST', body: { prompt: text } });
      prompt.value = '';
      go('pipeline');
    } catch (e) {
      const hits = document.getElementById('hits');
      document.getElementById('retr').setAttribute('data-on', '');
      hits.innerHTML = `<div class="probeblank" style="color:var(--signal)">${esc(e.message)}</div>`;
    } finally {
      goBtn.textContent = 'Create';
      goBtn.disabled = !prompt.value.trim();
    }
  });

  document.getElementById('arrow').onclick = () => {
    const hrail = document.getElementById('hrail');
    hrail.scrollBy({ left: hrail.clientWidth * .8, behavior: 'smooth' });
  };

  initUpload();
}

/* ── the + upload dropdown: rooms, characters, props — each posts to
   the engine endpoint that already owns that asset type ── */

const UPLOAD_KINDS = {
  location: { action: '/locations/upload', label: 'Room name — e.g. garage, kitchen',
              note: 'Photos are saved and the room is described by vision (needs the Gemini key).' },
  character: { action: '/characters/new', label: 'Character name — e.g. Michael',
               note: 'Reference photos for casting and prompt grounding.' },
  prop: { action: '/props/new', label: 'Prop name — e.g. Ducati 959',
          note: 'Reference photos so prompts name it instead of re-describing it.' },
};
let upKind = null;

function initUpload() {
  const plus = document.getElementById('up');
  const menu = document.getElementById('upmenu');
  const form = document.getElementById('upform');
  const files = document.getElementById('upfiles');
  const fileLabel = document.getElementById('upfilelabel');
  const note = document.getElementById('upnote');

  plus.onclick = () => {
    const open = menu.hidden;
    menu.hidden = !open;
    plus.setAttribute('aria-expanded', String(open));
    if (!open) { upKind = null; form.hidden = true; note.textContent = ''; resetKinds(); }
  };

  function resetKinds() {
    document.querySelectorAll('#upkinds .chip').forEach(c =>
      c.setAttribute('aria-pressed', 'false'));
  }

  document.querySelectorAll('#upkinds .chip').forEach(chip => chip.onclick = () => {
    resetKinds();
    chip.setAttribute('aria-pressed', 'true');
    upKind = chip.dataset.k;
    form.hidden = false;
    document.getElementById('upname').placeholder = UPLOAD_KINDS[upKind].label;
    note.textContent = UPLOAD_KINDS[upKind].note;
    document.getElementById('upname').focus();
  });

  files.onchange = () => {
    fileLabel.textContent = files.files.length
      ? `${files.files.length} photo${files.files.length === 1 ? '' : 's'} selected`
      : 'Choose photos…';
  };

  form.onsubmit = async e => {
    e.preventDefault();
    if (!upKind) return;
    const name = document.getElementById('upname').value.trim();
    if (!name) { note.textContent = 'a name is required'; return; }
    if (!files.files.length) { note.textContent = 'pick at least one photo'; return; }
    const go = document.getElementById('upgo');
    go.disabled = true; go.textContent = 'Uploading…';
    note.textContent = '';
    try {
      const body = new FormData();
      body.append('name', name);
      body.append('next', '/ui');
      for (const f of files.files) body.append('photos', f);
      const res = await fetch(UPLOAD_KINDS[upKind].action, { method: 'POST', body });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      // the engine endpoints redirect with ?message= — surface it verbatim
      const message = new URL(res.url, location.origin).searchParams.get('message');
      note.textContent = message || 'Uploaded.';
      form.reset();
      fileLabel.textContent = 'Choose photos…';
      await loadAssets(true);          // the carousel shows the new asset
      renderStudio();
    } catch (err) {
      note.textContent = `Upload failed: ${err.message}`;
    } finally {
      go.disabled = false; go.textContent = 'Upload';
    }
  };
}

async function retrieve() {
  const q = promptEl().value.trim();
  const retr = document.getElementById('retr');
  const hits = document.getElementById('hits');
  const lat = document.getElementById('lat');
  if (q.length < 3) { retr.removeAttribute('data-on'); lat.textContent = '—'; return; }
  retr.setAttribute('data-on', '');
  try {
    const res = await api('/api/retrieve', { method: 'POST', body: { query: q, k: 4 } });
    lat.textContent = `${res.latency_ms} ms · ${res.model}`;
    if (!res.hits.length) {
      hits.innerHTML = '<div class="probeblank">Nothing retrieved — the library has no match</div>';
      return;
    }
    hits.innerHTML = res.hits.map((h, i) => `
      <div class="hit" style="animation-delay:${i * 46}ms">
        <div>
          <div class="nm">${esc(h.source)} <span class="sr">· ${esc(h.domain)}</span></div>
          <div class="snip">${esc(h.chunk.slice(0, 160))}</div>
        </div>
        <span></span>
        <span class="sc">${h.score.toFixed(2)}</span>
      </div>`).join('');
  } catch (e) {
    lat.textContent = '—';
    hits.innerHTML = `<div class="probeblank" style="color:var(--signal)">${esc(e.message)}</div>`;
  }
}

export async function renderStudio() {
  const railstate = document.getElementById('railstate');
  const hrail = document.getElementById('hrail');
  const filters = document.getElementById('rowfilters');
  stateline(railstate, 'loading', 'Loading assets…');
  let data;
  try {
    data = await loadAssets();
  } catch (e) {
    hrail.innerHTML = '';
    filters.innerHTML = '';
    stateline(railstate, 'error', `Assets unavailable: ${e.message}`, renderStudio);
    return;
  }
  stateline(railstate, null);
  const counts = data.counts;
  const cats = [['all', 'All'], ['location', 'Rooms'], ['character', 'Characters'], ['prop', 'Props']];
  filters.innerHTML = cats.map(([k, l]) =>
    `<button class="chip" aria-pressed="${railFilter === k}" data-f="${k}">${l} · ${counts[k] ?? 0}</button>`).join('');
  filters.querySelectorAll('.chip').forEach(c => c.onclick = () => {
    railFilter = c.dataset.f; renderStudio();
  });
  const items = data.items.filter(a => railFilter === 'all' || a.category === railFilter);
  if (!items.length) {
    hrail.innerHTML = '';
    stateline(railstate, 'empty',
      'No assets yet — photograph rooms, cast and props on the Assets engine page (/assets)');
    return;
  }
  hrail.innerHTML = items.slice(0, 12).map(a => `
    <article class="card" data-id="${a.id}">
      <div class="fr${a.poster ? '' : ' blank'}" ${a.poster ? `style="background-image:url('${a.poster}')"` : ''}></div>
      <div class="cap"><b>${esc(a.name)}</b><span class="tc">${esc(a.category)}</span></div>
    </article>`).join('');
  hrail.querySelectorAll('.card').forEach(card => {
    const asset = items.find(x => x.id === card.dataset.id);
    wireScrub(card.querySelector('.fr'), asset.photos);
    card.onclick = () => openAssetDetail(asset);
  });
}

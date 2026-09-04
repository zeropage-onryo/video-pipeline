/* Studio view: the composer with live RAG grounding, and the asset
   carousel.

   The idea is typed HERE and nowhere else (2026-08-28). Create posts
   /api/scenes/run -- one idea, 1-4 standalone concepts out -- and routes
   to Pipeline, which is now purely the deciding surface. The references
   picked here (uploads, or photos out of the asset bank) ride into the
   generation as vision input AND are stored on each concept's shot, so
   they reach the keyframe and the clip later. */
import { api, esc, loadAssets, openAssetDetail, state, stateline, wireMentions, wireScrub } from './shared.js';

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
    reflectSparkEdits();
    if (!state.caps.retrieve) return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(retrieve, 300);
  });

  // @asset mentions: naming a character/prop/room in the idea attaches its
  // photo as a reference for THIS call, the same pathway the + menu and
  // scout bin use -- so a run grounds only on what's typed or attached,
  // never the whole bank (src/asset_shelf.in_scope on the server side).
  wireMentions(prompt, document.getElementById('promptmentions'), item => {
    if (item.thumb) addAttachment({ kind: 'asset', url: item.thumb, origin: 'mention' });
  });

  goBtn.addEventListener('click', async () => {
    const text = prompt.value.trim();
    if (!text) return;
    goBtn.disabled = true;
    goBtn.textContent = 'Writing…';
    try {
      await api('/api/scenes/run', { method: 'POST', body: collectRunForm(text) });
      prompt.value = '';
      clearScout();
      clearAttachments();
      document.getElementById('upmenu').hidden = true;
      document.getElementById('up').setAttribute('aria-expanded', 'false');
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
  initScout();
}

/* ── the research scout ──────────────────────────────────────────────
   The magnifier fills the composer from src/scout.py's bank: one
   researched line into the idea box, and the pass's reference images
   pre-attached as ordinary picks the person can unpick.

   The images arrive as /refs/<sha>.jpg URLs -- the same shape a photo
   dragged onto this composer gets -- so they need no special handling
   anywhere downstream: they attach as 'asset' kind, post as
   asset_photos, resolve through _resolve_asset_photo, and land on the
   shot. That is the entire reason the scout writes into data/refs
   rather than a bin of its own.

   An empty bank runs a pass first. A crawl is tens of seconds, so the
   button narrates rather than sitting still, and polls for the result
   instead of blocking on the job's own SSE feed. ── */

let scoutFindingId = 0;
let scoutSparkText = '';        // what the scout actually proposed
const SCOUT_POLL_MS = 3000;
const SCOUT_POLL_TRIES = 40;      // ~2 minutes, past a slow grounded crawl

function initScout() {
  const btn = document.getElementById('scoutbtn');
  if (!btn) return;
  btn.onclick = () => loadScoutSpark(btn);
  const clear = document.getElementById('scoutclear');
  if (clear) clear.onclick = clearScout;
}

async function loadScoutSpark(btn) {
  const card = document.getElementById('scoutcard');
  const why = document.getElementById('scoutwhy');
  btn.disabled = true;
  card.hidden = false;
  why.innerHTML = '<div class="probeblank">Looking for a researched spark…</div>';
  try {
    let found = await api(`/api/scout/spark?brand=${encodeURIComponent(state.brand)}`);
    if (!found.spark) {
      why.innerHTML = '<div class="probeblank">Nothing banked — crawling now, this takes a minute…</div>';
      await api('/api/scout/run', { method: 'POST', body: { brand: state.brand } });
      found = await pollForSpark();
    }
    if (!found || !found.spark) {
      why.innerHTML = '<div class="probeblank">The crawl found nothing usable — try again, or type an idea</div>';
      return;
    }
    applyScoutSpark(found);
  } catch (e) {
    why.innerHTML = `<div class="probeblank" style="color:var(--signal)">${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

async function pollForSpark() {
  for (let i = 0; i < SCOUT_POLL_TRIES; i++) {
    await new Promise(r => setTimeout(r, SCOUT_POLL_MS));
    try {
      const found = await api(`/api/scout/spark?brand=${encodeURIComponent(state.brand)}`);
      if (found.spark) return found;
    } catch { /* a blip mid-crawl is not a failed crawl -- keep waiting */ }
  }
  return null;
}

function applyScoutSpark(found) {
  const prompt = promptEl();
  scoutFindingId = found.finding_id || 0;
  scoutSparkText = found.spark;
  prompt.value = found.spark;
  prompt.dispatchEvent(new Event('input'));      // wakes Create + grounding

  const score = document.getElementById('scoutscore');
  score.textContent = found.score == null ? '—' : `${Number(found.score).toFixed(2)} confidence`;

  const sources = (found.sources || []).map(s =>
    `<a class="ssrc" href="${esc(s)}" target="_blank" rel="noopener noreferrer">${esc(shortHost(s))}</a>`).join('');
  document.getElementById('scoutwhy').innerHTML = `
    <div class="swhy">${esc(found.rationale || '')}</div>
    ${found.evidence ? `<div class="sev">${esc(found.evidence)}</div>` : ''}
    ${sources ? `<div class="ssrcs">${sources}</div>` : ''}`;

  // Every bin image keeps a link to the post it came from. These are
  // other people's frames used as mood reference, so an unattributed
  // tile would be the wrong thing to put in front of a person about to
  // render from it.
  const bin = document.getElementById('scoutbin');
  const images = found.bin || [];
  bin.innerHTML = images.length
    ? images.map(b => `
        <figure class="btile" style="background-image:url('${esc(b.url)}')">
          <figcaption>
            <a href="${esc(b.source_url)}" target="_blank" rel="noopener noreferrer"
               title="${esc(b.title)}">${esc(b.lane)}${b.metric ? ' · ' + esc(b.metric) : ''}</a>
          </figcaption>
        </figure>`).join('')
    : '<div class="probeblank">No reference images in this pass</div>';

  clearAttachments();
  for (const b of images) addAttachment({ kind: 'asset', url: b.url, origin: 'scout' });
}

function shortHost(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); }
  catch { return url.slice(0, 28); }
}

function clearScout() {
  scoutFindingId = 0;
  scoutSparkText = '';
  document.getElementById('scoutcard').hidden = true;
  clearAttachments();
}

/* Whether the box still holds what the scout proposed. Typing over a
   loaded spark makes the idea Mike's own, and his ideas are a separate
   path from the scout's -- so the claim stops following it. Compared
   loosely (case, punctuation, surrounding space) because fixing a
   capital letter is not changing your mind.

   The server checks this too and is the actual guarantee (scout.claims);
   this half exists so the composer TELLS him which path he is on
   instead of silently deciding. */
function scoutSparkIntact() {
  const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  return !!scoutFindingId && norm(promptEl().value) === norm(scoutSparkText);
}

function reflectSparkEdits() {
  if (!scoutFindingId) return;
  const head = document.getElementById('scoutlabel');
  if (head) {
    const intact = scoutSparkIntact();
    head.textContent = intact
      ? 'Researched spark'
      : 'Your idea — the researched references will not be attached';
    document.getElementById('scoutbin').classList.toggle('dropped', !intact);
    for (const tile of document.querySelectorAll('.attachbar .attach[data-origin="scout"]')) {
      tile.classList.toggle('dropped', !intact);
    }
  }
}

/* ── the + media panel: previously saved photos to pick from, plus a
   drop-or-upload tile. Selections attach to THIS generation as image
   references (the same image_refs path the engine composer uses). ── */

const MAX_ATTACH = 6;
const attachments = [];   // {kind:'asset', url} | {kind:'file', file, url(objectURL)}

function initUpload() {
  const plus = document.getElementById('up');
  const menu = document.getElementById('upmenu');
  const files = document.getElementById('upfiles');
  const note = document.getElementById('upnote');
  const cbox = document.getElementById('cbox');

  plus.onclick = async () => {
    const open = menu.hidden;
    menu.hidden = !open;
    plus.setAttribute('aria-expanded', String(open));
    if (open) await renderMediaGrid();
    else note.textContent = '';
  };

  files.onchange = () => {
    for (const f of files.files) addAttachment({ kind: 'file', file: f,
                                                 url: URL.createObjectURL(f) });
    files.value = '';
  };

  // drag & drop straight onto the composer
  ['dragover', 'drop'].forEach(evt => cbox.addEventListener(evt, e => {
    e.preventDefault();
    if (evt === 'drop') {
      for (const f of e.dataTransfer.files) {
        if (f.type.startsWith('image/')) {
          addAttachment({ kind: 'file', file: f, url: URL.createObjectURL(f) });
        }
      }
    }
  }));
}

function addAttachment(item) {
  const note = document.getElementById('upnote');
  if (attachments.length >= MAX_ATTACH) {
    note.textContent = `at most ${MAX_ATTACH} references per generation`;
    return false;
  }
  attachments.push(item);
  renderAttachments();
  return true;
}

function removeAttachment(index) {
  const [gone] = attachments.splice(index, 1);
  if (gone && gone.kind === 'file') URL.revokeObjectURL(gone.url);
  renderAttachments();
  const tile = document.querySelector(`.mtile[data-u="${CSS.escape(gone?.url || '')}"]`);
  if (tile) tile.setAttribute('aria-pressed', 'false');
}

function renderAttachments() {
  const bar = document.getElementById('attachbar');
  bar.innerHTML = attachments.map((a, i) =>
    `<div class="attach" data-origin="${esc(a.origin || 'user')}"
          style="background-image:url('${a.url}')" title="${esc(a.kind)}">
       <button class="ax" data-i="${i}" aria-label="Remove">✕</button>
     </div>`).join('');
  bar.querySelectorAll('.ax').forEach(b => b.onclick = () => removeAttachment(+b.dataset.i));
  reflectSparkEdits();          // re-rendering must not lose the dropped marking
}

async function renderMediaGrid() {
  const grid = document.getElementById('mgrid');
  const count = document.getElementById('mcount');
  grid.innerHTML = '<div class="probeblank">Loading media…</div>';
  let media;
  try {
    media = await api('/api/media');
  } catch (e) {
    grid.innerHTML = `<div class="probeblank" style="color:var(--signal)">${esc(e.message)}</div>`;
    return;
  }
  count.textContent = `${media.counts.all} saved`;
  const selected = new Set(attachments.filter(a => a.kind === 'asset').map(a => a.url));
  grid.innerHTML = `
    <button class="mtile mdrop" id="mdrop" type="button">
      <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4m0 0 4 4m-4-4-4 4M4 20h16"/></svg>
      Drop or upload files
      <small>image · this generation only</small>
    </button>` +
    media.items.map(m => `
      <button class="mtile" type="button" data-u="${esc(m.url)}"
              aria-pressed="${selected.has(m.url)}"
              style="background-image:url('${m.url}')">
        <span class="mname">${esc(m.asset_name)}</span>
      </button>`).join('');
  if (!media.items.length) {
    grid.insertAdjacentHTML('beforeend',
      '<div class="probeblank">No saved media yet — photos added on /assets appear here</div>');
  }
  document.getElementById('mdrop').onclick = () =>
    document.getElementById('upfiles').click();
  grid.querySelectorAll('.mtile[data-u]').forEach(tile => tile.onclick = () => {
    const url = tile.dataset.u;
    const existing = attachments.findIndex(a => a.kind === 'asset' && a.url === url);
    if (existing >= 0) {
      removeAttachment(existing);
      tile.setAttribute('aria-pressed', 'false');
    } else if (addAttachment({ kind: 'asset', url })) {
      tile.setAttribute('aria-pressed', 'true');
    }
  });
}

export function collectRunForm(idea) {
  const body = new FormData();
  body.append('idea', idea);
  const count = document.getElementById('ccount');
  body.append('count', count ? count.value : '4');
  // Whatever research is on screen rides along, edited or not, and the
  // SERVER rules on it (scout.claims): if the idea has walked away from
  // the spark, it claims nothing and drops that pass's images. Deciding
  // here instead would put the boundary in a client-side flag -- which
  // is the thing that goes stale. This half is for honest UI only.
  if (scoutFindingId) body.append('scout_finding_id', String(scoutFindingId));
  for (const a of attachments) {
    if (a.kind === 'file') body.append('files', a.file);
    else body.append('asset_photos', a.url);
  }
  return body;
}

export function clearAttachments() {
  while (attachments.length) removeAttachment(0);
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

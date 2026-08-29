/* Assets view: every saved photo as a date-grouped gallery (real file
   dates from /api/media), newest first — the all-assets browse surface.
   Clicking a photo opens its owning asset's detail rail. Search and
   category tabs re-query the API; counts are set totals from the
   response, never page length. */
import { api, esc, loadAssets, openAssetDetail, stateline } from './shared.js';

let acat = 'all';
let searchTimer = null;
let wired = false;

const DATE_FMT = new Intl.DateTimeFormat(undefined,
  { year: 'numeric', month: 'long', day: 'numeric' });

function dateLabel(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return DATE_FMT.format(new Date(y, m - 1, d));
}

export async function renderAssets() {
  const astate = document.getElementById('astate');
  const gallery = document.getElementById('gallery');
  const cats = document.getElementById('cats');
  const search = document.getElementById('asearch');

  if (!wired) {
    wired = true;
    search.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(renderAssets, 220);
    });
    wireAddModal();
  }

  stateline(astate, 'loading', 'Loading media…');
  let media, assets;
  try {
    const params = new URLSearchParams();
    if (search.value.trim()) params.set('q', search.value.trim());
    if (acat !== 'all') params.set('category', acat);
    [media, assets] = await Promise.all([
      api('/api/media?kind=all&' + params.toString()),
      loadAssets(true),
    ]);
  } catch (e) {
    gallery.innerHTML = '';
    stateline(astate, 'error', `Media unavailable: ${e.message}`, renderAssets);
    return;
  }
  stateline(astate, null);

  const CATS = [['all', 'All'], ['location', 'Locations'], ['character', 'Characters'],
    ['prop', 'Props'], ['generated', 'Generated']];
  cats.innerHTML = CATS.map(([k, l]) =>
    `<button class="cat" data-c="${k}" aria-pressed="${acat === k}">${l}<u>${media.counts[k] ?? 0}</u></button>`).join('');
  cats.querySelectorAll('.cat').forEach(b => b.onclick = () => { acat = b.dataset.c; renderAssets(); });

  document.getElementById('lcount').textContent =
    `${media.items.length}${media.items.length !== media.counts.all ? ' of ' + media.counts.all : ''} media item${media.counts.all === 1 ? '' : 's'}`;

  if (!media.items.length) {
    gallery.innerHTML = '';
    stateline(astate, 'empty', media.counts.all
      ? 'Nothing matches — clear the search or switch category'
      : 'No media yet — add an asset or generate your first image or clip');
    return;
  }

  // group by real file date, newest day first (items arrive sorted)
  const groups = [];
  for (const item of media.items) {
    const last = groups[groups.length - 1];
    if (last && last.date === item.date) last.items.push(item);
    else groups.push({ date: item.date, items: [item] });
  }

  gallery.innerHTML = groups.map(g => `
    <div class="gdate">${esc(dateLabel(g.date))}
      <span class="m">${g.items.length} item${g.items.length === 1 ? '' : 's'}</span></div>
    <div class="gphotos">${g.items.map(m => `
      <button class="gph${m.kind === 'video' ? ' video' : ''}" type="button"
              data-a="${esc(m.asset_id)}"
              ${m.kind === 'image' ? `style="background-image:url('${esc(m.url)}')"` : ''}>
        ${m.kind === 'video' ? `<video src="${esc(m.url)}" muted loop playsinline preload="metadata"></video>` : ''}
        <span class="mname">${esc(m.asset_name)} · ${esc(m.category)}</span>
      </button>`).join('')}
    </div>`).join('');

  gallery.querySelectorAll('.gph').forEach(tile => tile.onclick = () => {
    const asset = assets.items.find(a => a.id === tile.dataset.a);
    if (asset) openAssetDetail(asset);
  });
  gallery.querySelectorAll('.gph.video').forEach(tile => {
    const video = tile.querySelector('video');
    tile.onmouseenter = () => video.play().catch(() => {});
    tile.onmouseleave = () => { video.pause(); video.currentTime = 0; };
  });
}

/* ── add-asset modal: name + detail + notes + photos, straight to the
   always-on /api/assets/{category} create routes. The save response
   carries the RAG-shelf result, surfaced in the stateline so a down
   store is visible, never silent. ── */

const DETAIL_PLACEHOLDER = {
  characters: 'Role (e.g. the rider)',
  locations: 'unused — the vision pass describes the space',
  props: 'Category (e.g. helmet)',
};

function wireAddModal() {
  const modal = document.getElementById('addmodal');
  const cat = document.getElementById('addcat');
  const detail = document.getElementById('adddetail');
  const open = () => {
    document.getElementById('addname').value = '';
    document.getElementById('addnotes').value = '';
    document.getElementById('addphotos').value = '';
    detail.value = '';
    syncCat();
    modal.setAttribute('data-open', '');
  };
  const close = () => modal.removeAttribute('data-open');
  const syncCat = () => {
    detail.placeholder = DETAIL_PLACEHOLDER[cat.value];
    detail.disabled = cat.value === 'locations';
  };
  cat.onchange = syncCat;
  document.getElementById('addasset').onclick = open;
  document.getElementById('addclose').onclick = close;
  document.getElementById('addcancel').onclick = close;
  document.getElementById('addsave').onclick = async () => {
    const meta = document.getElementById('addmeta');
    const name = document.getElementById('addname').value.trim();
    const photos = document.getElementById('addphotos').files;
    if (!name) { meta.textContent = 'a name is required'; return; }
    if (cat.value === 'locations' && !photos.length) {
      meta.textContent = 'a location needs at least one photo'; return;
    }
    const body = new FormData();
    body.append('name', name);
    if (cat.value === 'characters') body.append('role', detail.value.trim());
    if (cat.value === 'props') body.append('category', detail.value.trim());
    body.append('notes', document.getElementById('addnotes').value.trim());
    for (const f of photos) body.append('photos', f);
    const btn = document.getElementById('addsave');
    btn.disabled = true; meta.textContent = 'saving…';
    try {
      const res = await api(`/api/assets/${cat.value}`, { method: 'POST', body });
      close();
      const rag = res.rag && res.rag.ok
        ? `${res.rag.chunks} chunk(s) to the rag assets shelf`
        : `rag shelf skipped: ${res.rag && res.rag.error || 'store unavailable'}`;
      stateline(document.getElementById('astate'), res.rag && res.rag.ok ? 'empty' : 'error',
        `Added ${name} — ${res.note ? res.note + ' · ' : ''}${rag}`);
      await loadAssets(true);
      setTimeout(renderAssets, 1400);
    } catch (e) {
      meta.textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  };
}

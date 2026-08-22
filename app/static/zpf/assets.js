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
  }

  stateline(astate, 'loading', 'Loading media…');
  let media, assets;
  try {
    const params = new URLSearchParams();
    if (search.value.trim()) params.set('q', search.value.trim());
    if (acat !== 'all') params.set('category', acat);
    [media, assets] = await Promise.all([
      api('/api/media?' + params.toString()),
      loadAssets(),
    ]);
  } catch (e) {
    gallery.innerHTML = '';
    stateline(astate, 'error', `Media unavailable: ${e.message}`, renderAssets);
    return;
  }
  stateline(astate, null);

  const CATS = [['all', 'All'], ['location', 'Locations'], ['character', 'Characters'], ['prop', 'Props']];
  cats.innerHTML = CATS.map(([k, l]) =>
    `<button class="cat" data-c="${k}" aria-pressed="${acat === k}">${l}<u>${media.counts[k] ?? 0}</u></button>`).join('');
  cats.querySelectorAll('.cat').forEach(b => b.onclick = () => { acat = b.dataset.c; renderAssets(); });

  document.getElementById('lcount').textContent =
    `${media.items.length}${media.items.length !== media.counts.all ? ' of ' + media.counts.all : ''} photo${media.counts.all === 1 ? '' : 's'}`;

  if (!media.items.length) {
    gallery.innerHTML = '';
    stateline(astate, 'empty', media.counts.all
      ? 'Nothing matches — clear the search or switch category'
      : 'No media yet — add photos with the + on the Studio composer or on /assets');
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
      <span class="m">${g.items.length} photo${g.items.length === 1 ? '' : 's'}</span></div>
    <div class="gphotos">${g.items.map(m => `
      <button class="gph" type="button" data-a="${esc(m.asset_id)}"
              style="background-image:url('${esc(m.url)}')">
        <span class="mname">${esc(m.asset_name)} · ${esc(m.category)}</span>
      </button>`).join('')}
    </div>`).join('');

  gallery.querySelectorAll('.gph').forEach(tile => tile.onclick = () => {
    const asset = assets.items.find(a => a.id === tile.dataset.a);
    if (asset) openAssetDetail(asset);
  });
}

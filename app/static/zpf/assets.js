/* Assets view: the unified grounding library — locations, characters,
   props — straight from the DB. Search + category tabs re-query the
   API; counts are set totals from the response, never page length. */
import { api, esc, openAssetDetail, state, stateline, wireScrub } from './shared.js';

let acat = 'all';
let searchTimer = null;
let wired = false;

export async function renderAssets() {
  const astate = document.getElementById('astate');
  const grid = document.getElementById('grid');
  const cats = document.getElementById('cats');
  const search = document.getElementById('asearch');

  if (!wired) {
    wired = true;
    search.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(renderAssets, 220);
    });
  }

  stateline(astate, 'loading', 'Loading…');
  let data;
  try {
    const params = new URLSearchParams();
    if (search.value.trim()) params.set('q', search.value.trim());
    if (acat !== 'all') params.set('category', acat);
    data = await api('/api/assets?' + params.toString());
  } catch (e) {
    grid.innerHTML = '';
    stateline(astate, 'error', `Assets unavailable: ${e.message}`, renderAssets);
    return;
  }
  stateline(astate, null);

  const CATS = [['all', 'All'], ['location', 'Locations'], ['character', 'Characters'], ['prop', 'Props']];
  cats.innerHTML = CATS.map(([k, l]) =>
    `<button class="cat" data-c="${k}" aria-pressed="${acat === k}">${l}<u>${data.counts[k] ?? 0}</u></button>`).join('');
  cats.querySelectorAll('.cat').forEach(b => b.onclick = () => { acat = b.dataset.c; renderAssets(); });

  document.getElementById('lcount').textContent =
    `${data.items.length}${data.items.length !== data.counts.all ? ' of ' + data.counts.all : ''} asset${data.counts.all === 1 ? '' : 's'}`;

  if (!data.items.length) {
    grid.innerHTML = '';
    stateline(astate, 'empty', data.counts.all
      ? 'Nothing matches — clear the search or switch category'
      : 'No assets yet — add rooms, cast and props on the engine page (/assets)');
    return;
  }
  grid.innerHTML = data.items.map(a => `
    <article class="plate in" data-id="${a.id}" tabindex="0">
      <div class="fr${a.poster ? '' : ' blank'}" ${a.poster ? `style="background-image:url('${a.poster}')"` : ''}>
        <span class="badge">${esc(a.category)}</span>
        <div class="sl"><i></i></div>
      </div>
      <div class="pfoot"><span class="pname">${esc(a.name)}</span><span class="tc">${(a.photos || []).length} photo${(a.photos || []).length === 1 ? '' : 's'}</span></div>
    </article>`).join('');
  grid.querySelectorAll('.plate').forEach(el => {
    const asset = data.items.find(x => x.id === el.dataset.id);
    wireScrub(el.querySelector('.fr'), asset.photos, el.querySelector('.sl'));
    el.onclick = () => openAssetDetail(asset);
    el.onkeydown = e => { if (e.key === 'Enter') openAssetDetail(asset); };
  });
}

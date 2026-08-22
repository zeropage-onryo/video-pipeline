/* Analytics view: the real metrics snapshots. Two brands never average
   together — the toggle re-queries everything with ?brand=. Views is
   the headline number because views is what the DB records; no daily
   rollups exist yet, so no daily chart is rendered. */
import { api, esc, fmtN, state, stateline } from './shared.js';

const AUDS = [['antihero', 'ANTIHERO'], ['zeropage', 'Zero Page Films']];
let aud = null;
let plat = 'all';

export async function renderAnalytics() {
  if (aud === null) aud = state.brand;
  const anstate = document.getElementById('anstate');
  stateline(anstate, 'loading', 'Loading…');

  document.getElementById('auds').innerHTML = AUDS.map(([k, l]) =>
    `<button class="aud" data-a="${k}" aria-pressed="${aud === k}">${l}</button>`).join('');
  document.querySelectorAll('#auds .aud').forEach(b => b.onclick = () => {
    aud = b.dataset.a; plat = 'all'; renderAnalytics();
  });

  let summary, posts, accounts;
  try {
    const params = `brand=${aud}${plat !== 'all' ? '&platform=' + plat : ''}`;
    [summary, posts, accounts] = await Promise.all([
      api(`/api/analytics/summary?${params}`),
      api(`/api/analytics/posts?${params}`),
      api('/api/analytics/accounts'),
    ]);
  } catch (e) {
    stateline(anstate, 'error', `Analytics unavailable: ${e.message}`, renderAnalytics);
    return;
  }
  stateline(anstate, null);

  const PLATFORMS = [['all', 'All'], ['instagram', 'Instagram'], ['youtube', 'YouTube'], ['tiktok', 'TikTok']];
  document.getElementById('plats').innerHTML = PLATFORMS.map(([k, l]) =>
    `<button class="cat" data-p="${k}" aria-pressed="${plat === k}">${l}<u>${summary.platform_counts[k] ?? 0}</u></button>`).join('');
  document.querySelectorAll('#plats .cat').forEach(b => b.onclick = () => {
    plat = b.dataset.p; renderAnalytics();
  });

  const t = summary.tiles;
  document.getElementById('akpis').innerHTML = [
    [fmtN(t.views), 'Views'],
    [fmtN(t.likes), 'Likes'],
    [fmtN(t.comments), 'Comments'],
    [fmtN(t.saves), 'Saves'],
    [String(t.videos), 'Videos tracked'],
  ].map(([v, l]) => `<div class="metric"><div class="mv">${v}</div><div class="md">${l}</div></div>`).join('');

  const latest = posts.items
    .map(p => p.captured_at).filter(Boolean).sort().pop();
  document.getElementById('stamp').textContent = latest
    ? `latest snapshot ${String(latest).slice(0, 10)}`
    : 'no snapshots recorded yet';

  const box = document.getElementById('posts');
  if (!posts.items.length) {
    box.innerHTML = '<div class="probeblank">No videos tracked yet — add one on /videos/new or import a channel</div>';
  } else {
    box.innerHTML =
      `<div class="phead"><span>Post</span><span>Views</span><span>Likes</span><span>Comments</span><span>Saves</span><span></span></div>` +
      posts.items.map(p => {
        const canRefresh = state.caps['analytics.' + p.platform];
        return `<div class="post" data-id="${p.video_id}">
          <div>
            <div class="pt">${esc(p.title)}</div>
            <div class="pm">${esc(p.platform)} · ${esc(String(p.posted_at).slice(0, 10))}${p.brand ? ' · ' + esc(p.brand) : ''}</div>
            ${p.views !== null ? `<div class="vbar"><i style="width:${p.pct}%"></i></div>` : ''}
          </div>
          <div class="pv"><b>${fmtN(p.views)}</b></div>
          <div class="pv">${fmtN(p.likes)}</div>
          <div class="pv">${fmtN(p.comments)}</div>
          <div class="pv">${fmtN(p.saves)}</div>
          <div>${canRefresh ? `<button class="refresh" data-id="${p.video_id}">Refresh</button>` : ''}</div>
        </div>`;
      }).join('');
    box.querySelectorAll('.refresh').forEach(b => b.onclick = async () => {
      b.disabled = true; b.textContent = '…';
      try {
        await api(`/api/videos/${b.dataset.id}/refresh`, { method: 'POST', body: {} });
        renderAnalytics();
      } catch (e) {
        b.textContent = 'failed';
        b.title = e.message;
        setTimeout(() => { b.disabled = false; b.textContent = 'Refresh'; }, 2500);
      }
    });
  }

  document.getElementById('conns').innerHTML =
    accounts.apis.map(a => `
      <div class="conn">
        <span class="dot ${a.configured ? 'ok' : 'idle'}"></span>
        <div class="cinfo"><div class="cname">${esc(a.label)}</div><div class="capi">${esc(a.platform)}</div></div>
        <div class="csync">${a.configured ? 'key set' : 'no key'}</div>
      </div>`).join('') +
    accounts.channels.map(c => `
      <div class="conn">
        <span class="dot ${c.autonomy === 'auto' ? 'ok' : c.autonomy === 'queue' ? 'run' : 'idle'}"></span>
        <div class="cinfo"><div class="cname">${esc(c.name)}</div><div class="capi">channel · targets ${esc(c.targets || 'none')}</div></div>
        <div class="csync">${esc(c.autonomy)}</div>
      </div>`).join('');
}

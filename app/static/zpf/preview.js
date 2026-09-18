/* The reference preview: one overlay for every surface that shows a
   scene's pictures -- the Pipeline board, the Queue, the Dev Studio's
   grade tab. No library. It brings its own stylesheet (preview.css) so a
   page only has to import this file.

   TWO THINGS LIVE HERE BESIDES THE OVERLAY, because every caller needs
   them and three copies would drift:

   - `parseRef` is the JS twin of src/asset_shelf.parse_ref, the ONE
     parser of a reference URL. A ref is stored as the public R2 URL when
     R2 is configured and as the local route when it is not, and both
     shapes have to read the same (2026-09-08). Same rules, same order:
     strip the query, take the path of an absolute URL, refuse a path
     that climbs, drop the local route's "photo" segment.
   - `sourcesFor` prefers the LOCAL route. app/main.py's photo routes and
     the /refs mount serve the file when this machine has it and 302 into
     R2 when it does not, so asking the local route first reads his Mac's
     photos off disk and still resolves on the deployed site. The stored
     URL is the second try; a labelled placeholder is the last. Never a
     blank.

   The payload carries a reference as a bare URL -- no source_url, no
   attribution (that lives on scout_bin rows, and the card API does not
   join it). So the caption's right side says what the URL itself proves:
   which shelf the photo came off. A caller that HAS a source passes
   `source` on the item and it wins. */

const ROOTS = { characters: 'character', props: 'prop', locations: 'location' };

export function parseRef(url) {
  let raw = String(url || '').split('?')[0].trim();
  if (!raw) return null;
  if (raw.includes('://')) {
    try { raw = new URL(raw).pathname; } catch { return null; }
  }
  let parts = raw.replace(/^\/+|\/+$/g, '').split('/').filter(Boolean);
  if (!parts.length || parts.some(p => p === '.' || p === '..')) return null;
  if (parts.length === 4 && parts[2] === 'photo') parts = [parts[0], parts[1], parts[3]];
  if (parts.length === 2 && parts[0] === 'refs') {
    return { kind: 'refs', plural: 'refs', slug: '', filename: parts[1] };
  }
  if (parts.length === 3 && ROOTS[parts[0]]) {
    return { kind: ROOTS[parts[0]], plural: parts[0], slug: parts[1], filename: parts[2] };
  }
  return null;
}

function localRoute(ref, thumb) {
  if (ref.kind === 'refs') return `/refs/${encodeURIComponent(ref.filename)}`;
  return `/${ref.plural}/${encodeURIComponent(ref.slug)}/photo/`
    + `${encodeURIComponent(ref.filename)}${thumb ? '?thumb=1' : ''}`;
}

/* every URL worth trying for this picture, best first */
export function sourcesFor(url, { thumb = false } = {}) {
  const ref = parseRef(url);
  const out = ref ? [localRoute(ref, thumb)] : [];
  if (thumb && ref && ref.kind !== 'refs') out.push(localRoute(ref, false));
  if (url && !out.includes(url)) out.push(url);
  return out;
}

export function fileName(url) {
  const ref = parseRef(url);
  if (ref) return decodeURIComponent(ref.filename);
  const path = String(url || '').split('?')[0];
  return decodeURIComponent(path.slice(path.lastIndexOf('/') + 1)) || 'image';
}

export function sourceLabel(url) {
  const ref = parseRef(url);
  if (ref) {
    return ref.kind === 'refs' ? 'REFERENCE BIN'
      : `ASSET BANK · ${ref.kind.toUpperCase()} · ${decodeURIComponent(ref.slug)}`;
  }
  if (/\/renders\//.test(String(url))) return 'DRAWN BY THE PIPELINE';
  try { return new URL(url, location.href).hostname.toUpperCase(); } catch { return ''; }
}

export const refItem = url => ({ url, name: fileName(url), source: sourceLabel(url) });

/* An item from the card's `ref_sources` row (2026-09-17): the page a
   scouted frame was taken from, as a LINK -- these are other people's
   frames held as mood reference, and the attribution has to be one click
   from the picture. An upload has no page and says so; a bin image the
   bin has no row for says THAT, rather than implying a source. Only
   http(s) is ever linked. */
export function sourcedItem(row) {
  const item = refItem(row.url);
  const href = /^https?:\/\//i.test(row.source_url || '') ? row.source_url : '';
  if (href) {
    let host = href;
    try { host = new URL(href).hostname.replace(/^www\./, ''); } catch { /* keep the url */ }
    return { ...item, href,
             source: `${(row.lane || 'scouted').toUpperCase()} · ${host}${row.title ? ' · ' + row.title : ''}` };
  }
  if (row.kind === 'refs') {
    return { ...item, source: row.lane === 'composer' ? 'YOUR UPLOAD · NO SOURCE PAGE'
      : row.lane ? `${row.lane.toUpperCase()} · NO SOURCE ON FILE` : 'REFERENCE BIN · NO SOURCE ON FILE' };
  }
  return item;
}

/* Walk an <img> down its sources; `broken` fires once every one failed.
   Works for markup already in the page: <img data-srcs="a|b">. */
export function loadChain(img, sources, broken) {
  const queue = sources.slice();
  const next = () => {
    const src = queue.shift();
    if (src === undefined) { img.onerror = null; broken && broken(img); return; }
    img.src = src;
  };
  img.onerror = next;
  next();
}

/* `<img data-srcs>` written into innerHTML by a card: start them all, and
   swap a dead one for a labelled slate where it stands */
export function hydrateImages(root) {
  ensureStyles();     // .zpv-dead, the slate a dead image becomes, lives there
  root.querySelectorAll('img[data-srcs]').forEach(img => {
    const sources = img.dataset.srcs.split('|').filter(Boolean);
    img.removeAttribute('data-srcs');
    loadChain(img, sources, dead => {
      const slate = document.createElement('span');
      slate.className = 'zpv-dead';
      slate.textContent = dead.dataset.deadLabel || 'IMAGE UNAVAILABLE';
      dead.replaceWith(slate);
    });
  });
}

/* the markup for one such image; `thumb` asks the photo route for its
   cached 480px JPEG first */
export function imgTag(url, { thumb = false, cls = '', alt = '', dead = '' } = {}) {
  const e = s => String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  return `<img class="${e(cls)}" alt="${e(alt)}" loading="lazy" decoding="async"`
    + ` data-dead-label="${e(dead)}" data-srcs="${e(sourcesFor(url, { thumb }).join('|'))}">`;
}

/* ── the overlay ── */

const ICON = {
  x: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  prev: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>',
  next: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>',
};

let live = null;      // the one open overlay: { el, onKey, trigger }

function ensureStyles() {
  if (document.querySelector('link[data-zpv]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/static/zpf/preview.css';
  link.dataset.zpv = '';
  document.head.appendChild(link);
}

export function closePreview() {
  if (!live) return;
  const { el, onKey, trigger } = live;
  live = null;
  // the handler exists only while the overlay does
  document.removeEventListener('keydown', onKey, true);
  el.remove();
  if (trigger && trigger.isConnected) trigger.focus();
}

/* openPreview({ title, items: [{url, name?, source?}], index, kind, trigger })
   `kind` is the word in the header: REFERENCE, or KEYFRAME for stills. */
export function openPreview({ title = '', items = [], index = 0, kind = 'REFERENCE',
                              trigger = document.activeElement } = {}) {
  items = items.filter(it => it && it.url).map(it => ({ ...refItem(it.url), ...it }));
  if (!items.length) return;
  closePreview();
  ensureStyles();

  const many = items.length > 1;
  let at = Math.min(Math.max(0, index), items.length - 1);

  const el = document.createElement('div');
  el.className = 'zpv';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  el.setAttribute('aria-label', `${title} — ${kind.toLowerCase()} preview`);
  el.innerHTML = `
    <div class="zpv-head">
      <span class="zpv-title" aria-live="polite"></span>
      <button type="button" class="zpv-btn" data-zpv="close" aria-label="Close preview">${ICON.x}</button>
    </div>
    <div class="zpv-stage">
      <button type="button" class="zpv-nav" data-zpv="prev" aria-label="Previous image"${many ? '' : ' hidden'}>${ICON.prev}</button>
      <div class="zpv-frame">
        <img class="zpv-img" alt="">
        <div class="zpv-broken" hidden></div>
      </div>
      <button type="button" class="zpv-nav" data-zpv="next" aria-label="Next image"${many ? '' : ' hidden'}>${ICON.next}</button>
    </div>
    <div class="zpv-cap"><span class="zpv-name"></span><span class="zpv-source"></span></div>
    <div class="zpv-strip"${many ? '' : ' hidden'}></div>`;

  const q = sel => el.querySelector(sel);
  const strip = q('.zpv-strip');
  items.forEach((it, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'zpv-thumb';
    b.dataset.i = String(i);
    b.setAttribute('aria-label', `Show ${kind.toLowerCase()} ${i + 1}`);
    const img = document.createElement('img');
    img.alt = '';
    b.appendChild(img);
    strip.appendChild(b);
    loadChain(img, sourcesFor(it.url, { thumb: true }), dead => dead.remove());
  });

  function show(i) {
    at = (i + items.length) % items.length;
    const it = items[at];
    q('.zpv-title').textContent =
      `${String(title).toUpperCase()} · ${kind} ${at + 1} / ${items.length}`;
    q('.zpv-name').textContent = it.name;
    // the source is a link when the payload had a page for it
    const src = q('.zpv-source');
    src.textContent = '';
    if (it.href) {
      const a = document.createElement('a');
      a.href = it.href;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = `${it.source} ↗`;
      src.appendChild(a);
    } else {
      src.textContent = it.source || '';
    }
    const img = q('.zpv-img');
    const broken = q('.zpv-broken');
    img.hidden = false;
    broken.hidden = true;
    img.alt = `${kind.toLowerCase()} ${at + 1}: ${it.name}`;
    loadChain(img, sourcesFor(it.url), () => {
      // labelled, never blank: say which file would have been here
      img.hidden = true;
      img.removeAttribute('src');
      broken.hidden = false;
      broken.textContent = `IMAGE UNAVAILABLE · ${it.name}`;
    });
    strip.querySelectorAll('.zpv-thumb').forEach((b, n) =>
      b.setAttribute('aria-current', String(n === at)));
  }

  el.addEventListener('click', ev => {
    const btn = ev.target.closest('button');
    if (!btn) { if (ev.target === el) closePreview(); return; }
    if (btn.dataset.i !== undefined) show(Number(btn.dataset.i));
    else if (btn.dataset.zpv === 'close') closePreview();
    else if (btn.dataset.zpv === 'prev') show(at - 1);
    else if (btn.dataset.zpv === 'next') show(at + 1);
  });

  const onKey = ev => {
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); closePreview(); return; }
    if (ev.key === 'ArrowLeft' && many) { ev.preventDefault(); show(at - 1); return; }
    if (ev.key === 'ArrowRight' && many) { ev.preventDefault(); show(at + 1); return; }
    if (ev.key === 'Tab') {
      // focus stays inside while the page behind it is covered
      const stops = [...el.querySelectorAll('button:not([hidden]), a[href]')];
      const first = stops[0], last = stops[stops.length - 1];
      if (!el.contains(document.activeElement)) { ev.preventDefault(); first.focus(); }
      else if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    }
  };

  document.body.appendChild(el);
  // capture phase, so Esc closes the preview and not the drawer under it
  document.addEventListener('keydown', onKey, true);
  live = { el, onKey, trigger };
  show(at);
  q('[data-zpv="close"]').focus();
}

/* Server-rendered pages (the grade tab): any element carrying
   data-zpv-group="<title>" whose buttons carry data-zpv-src. */
export function wirePreview(root = document) {
  ensureStyles();     // the thumbnails are styled by the same sheet
  root.querySelectorAll('[data-zpv-group]').forEach(group => {
    const buttons = [...group.querySelectorAll('button[data-zpv-src]')];
    // the server wrote plain <img src>, so a page without JS still shows
    // them; with JS a dead one walks the same chain as everywhere else
    buttons.forEach(btn => {
      const img = btn.querySelector('img');
      if (!img) return;
      const rest = sourcesFor(btn.dataset.zpvSrc).filter(u => u !== img.getAttribute('src'));
      const fail = () => loadChain(img, rest, dead => {
        const slate = document.createElement('span');
        slate.className = 'zpv-dead';
        slate.textContent = 'IMAGE UNAVAILABLE';
        dead.replaceWith(slate);
      });
      if (img.complete && !img.naturalWidth) fail(); else img.onerror = fail;
    });
    buttons.forEach((btn, i) => btn.addEventListener('click', () => openPreview({
      title: group.dataset.zpvGroup,
      kind: group.dataset.zpvKind || 'REFERENCE',
      items: buttons.map(b => ({ url: b.dataset.zpvSrc })),
      index: i,
      trigger: btn,
    })));
  });
}

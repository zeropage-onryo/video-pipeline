/* The board: the concepts one idea produced, and the pick.

   A concept IS a scene IS one prompt -- one row in shoot_concepts with a
   single shot -- so this is the only card in the product and there is no
   second data model behind it. What the board asks is one question:
   which of these is worth the spend.

   Each card leads with its picture, then the title and one line, then
   the references it was written against; the prompt that came back is
   in the card's drawer (2026-09-17). Picking one is the
   label (preprod.pick_rate). Nothing renders from here: a picked
   concept moves to Queue, and approving it there is what calls Runway.

   The card leads with ONE line saying what happens (2026-08-31). A
   scene prompt is ~1200 characters of camera, grade, beats and
   avoid-list, and four of those open at once meant reading every one to
   find out what the concepts even were -- so the summary is the card
   and the prompt is folded away behind a toggle. The line comes from
   the writer (`logline`); app/api.py caps it to one line and derives
   one from the prompt for rows written before it was asked for.

   Leaving the board is archiving, never deleting (2026-08-28). An
   unpicked row is the only negative signal this system collects -- if
   the ones you passed over were deleted, pick_rate would read 100%
   forever and a prompt change could never be measured. So an archived
   concept stops being a card, keeps counting, and keeps sitting in the
   Dev Studio's ungraded pool until it is graded. */
import { api, bus, esc, refreshQueueBadge, state, stateline } from './shared.js';
import { openConceptInDirector } from './genspace.js';
import { ICON, brandName, gateOf, heroMarkup, heroOf, partsOf, previewRefs,
         previewStills, refThumbs, shotsLabel, windowLabel } from './cards.js';
import { hydrateImages, imgTag } from './preview.js';

let wired = false;
let filter = '';               // '' open | picked | archived
let items = [];
// which concepts have their prompt open (in the drawer since 2026-09-17).
// Kept out here because the board re-renders whole on every pick/archive,
// and a prompt that snapped shut every time you picked would be worse
// than no toggle.
const openPrompts = new Set();

const $ = id => document.getElementById(id);

function boardState(kind, message, retry) {
  stateline($('scstate'), kind, message, retry);
}

/* ── a card ──
   Image-first (2026-09-17). The picture is the card: the keyframe, else
   the first reference, else a red slate -- because what decides a pick is
   what the scene will look like, and the old card led with a row of 28px
   dots. Title and the ONE card line under it (c.summary is
   preprod.concept_summary: card_line first, the logline only as the
   fallback the server already chose). The logline, the hook and the
   prompt are the drawer's; they are never printed or trimmed here. */

function statusOf(c) {
  // what this card is waiting on, said plainly. A rendered clip also says
  // WHO PAID: a subscription clip was made by hand on the operator's own
  // consumer plan (ops/render_queue.py), not billed per call, and that is
  // otherwise invisible -- same mp4, same folder, same URL shape.
  return c.archived ? (c.graded ? 'ARCHIVED · GRADED' : 'ARCHIVED · AWAITING GRADE')
    : c.media_url ? (c.subscription ? 'RENDERED · SUBSCRIPTION' : 'RENDERED')
    : c.picked ? 'PICKED'
    : c.parked ? 'KEYFRAMED · IN QUEUE'
    : '';
}

function card(c) {
  const gate = gateOf(c);
  const status = statusOf(c);
  const title = esc(c.title || 'Untitled');
  return `
  <article class="nc${c.picked ? ' picked' : ''}${c.archived ? ' off' : ''}" data-id="${c.id}">
    <button type="button" class="nc-hero" data-act="open"
            aria-label="Open details for ${title}">
      ${heroMarkup(c)}
      <span class="nc-tag tl">${esc(brandName(c.brand))}</span>
      <span class="nc-tag tr" title="${esc(gate.long)}"><i class="nc-dot ${gate.level}"></i>${gate.short}${gate.score === undefined ? '' : ` · ${gate.score}/10`}</span>
      <span class="nc-tag bl">${esc(shotsLabel(c))}</span>
      ${status ? `<span class="nc-tag br${c.picked && !c.archived && !c.media_url ? ' red' : ' bone'}">${esc(status)}</span>` : ''}
    </button>
    <div class="nc-body">
      <div class="nc-row">
        <div class="nc-text">
          <h4 class="nc-title" title="${title}">${title}</h4>
          ${c.summary ? `<p class="nc-line" title="${esc(c.summary)}">${esc(c.summary)}</p>` : ''}
        </div>
        <!-- pick toggles picked_at, archive archives (never deletes -- an
             unpicked row is the only negative signal here). Same two
             calls as before, as icons. -->
        <div class="nc-acts">
          ${c.archived
            ? `<button type="button" class="nc-icon" data-act="restore" title="Put back on the board"
                       aria-label="Put ${title} back on the board">${ICON.restore}</button>`
            : `<button type="button" class="nc-icon pick${c.picked ? ' on' : ''}" data-act="pick"
                       title="${c.picked ? 'Picked — click to unpick' : 'Pick this'}"
                       aria-pressed="${c.picked ? 'true' : 'false'}"
                       aria-label="${c.picked ? 'Unpick' : 'Pick'} ${title}">${ICON.check}</button>
               <button type="button" class="nc-icon" data-act="archive" title="Not this one — archive"
                       aria-label="Archive ${title} — take it off the board">${ICON.archive}</button>`}
          <button type="button" class="nc-icon" data-act="direct" title="Open in Director"
                  aria-label="Open ${title} in Director">${ICON.nodes}</button>
        </div>
      </div>
      <div class="nc-refs">
        ${(c.refs || []).length ? refThumbs(c)
          : '<span class="nc-norefs">NO REFERENCES — ADD BEFORE QUEUE</span>'}
      </div>
    </div>
  </article>`;
}

/* ── the drawer ──
   Everything the card will not print: the full logline, the hook, the
   timed shots, every reference, the readiness line and the prompt. One
   element on <body>; its Esc handler exists only while it is open. The
   prompt's open state is `openPrompts`, keyed by concept, exactly as the
   card's <details> kept it -- the board repaints whole on every pick,
   and the drawer repaints with it. */

let drawerId = null;
let drawerTrigger = null;

function drawerEl() {
  let el = document.getElementById('ncdrawer');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'ncdrawer';
  el.hidden = true;
  el.innerHTML = `
    <button type="button" class="ncd-back" data-d="close" aria-label="Close details" tabindex="-1"></button>
    <aside class="ncd" role="dialog" aria-modal="true" aria-labelledby="ncdtitle"></aside>`;
  document.body.appendChild(el);
  el.addEventListener('click', onDrawerClick);
  return el;
}

function onDrawerKey(ev) {
  if (ev.key === 'Escape') { ev.preventDefault(); closeDrawer(); }
}

function drawerMarkup(c) {
  const gate = gateOf(c);
  const hero = heroOf(c);
  const parts = partsOf(c);
  const refs = c.refs || [];
  const open = openPrompts.has(c.id);
  const shots = parts.length
    ? parts.map(p => `<li><span class="ncd-t">${esc(windowLabel(p))}</span><span>${esc(p.text || p.prompt || '')}</span></li>`).join('')
    : '<li><span class="ncd-t">—</span><span>One shot · rendered whole</span></li>';
  return `
    <div class="ncd-top">
      <span class="ncd-k">${esc(brandName(c.brand))} · CONCEPT #${c.id}</span>
      <button type="button" class="nc-icon" data-d="close" aria-label="Close details">${ICON.x}</button>
    </div>
    <div>
      <h2 class="ncd-title" id="ncdtitle">${esc(c.title || 'Untitled')}</h2>
      ${c.summary ? `<p class="ncd-line">${esc(c.summary)}</p>` : ''}
    </div>
    <button type="button" class="ncd-hero" data-d="hero"${hero.kind === 'none' ? ' disabled' : ''}
            aria-label="${hero.kind === 'keyframe' ? 'Preview keyframe' : hero.kind === 'ref' ? 'Preview reference 1' : 'No image to preview'}">
      ${hero.kind === 'none'
        ? '<span class="nc-slate"><span>NO REFERENCE</span><small>cannot render yet</small></span>'
        : imgTag(hero.url, { cls: 'nc-heroimg', dead: 'IMAGE UNAVAILABLE' })
          + `<span class="nc-tag br">${hero.kind === 'keyframe' ? 'KEYFRAME' : 'REF 1'} · CLICK TO ENLARGE</span>`}
    </button>
    <section>
      <div class="ncd-k">LOGLINE</div>
      <p class="ncd-p">${esc(c.logline || '—')}</p>
    </section>
    <div class="ncd-two">
      <section>
        <div class="ncd-k">HOOK · FRAME 1</div>
        <p class="ncd-p sm">${esc(c.hook || '—')}</p>
      </section>
      <section>
        <div class="ncd-k">SHOTS · ${esc(shotsLabel(c))}</div>
        <ol class="ncd-shots">${shots}</ol>
      </section>
    </div>
    <section>
      <div class="ncd-k">REFERENCES · ${refs.length}</div>
      <div class="ncd-refs">
        ${refs.length ? refThumbs(c, { max: 99, cls: 'nc-ref lg' })
          : '<span class="nc-norefs">NO REFERENCES — ADD BEFORE QUEUE</span>'}
      </div>
    </section>
    <section class="ncd-gate">
      <div class="ncd-gaterow">
        <span class="ncd-gatetext"><i class="nc-dot ${gate.level}"></i><span>${esc(gate.long)}</span></span>
        <button type="button" class="ncd-toggle" data-d="prompt" aria-expanded="${open}"
                aria-controls="ncdprompt">${open ? 'HIDE PROMPT' : 'SHOW PROMPT'}</button>
      </div>
      ${(c.warnings || []).length
        ? `<ul class="ncd-warn">${c.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
      <pre class="ncd-prompt" id="ncdprompt"${open ? '' : ' hidden'}>${esc(c.prompt || 'No prompt on this concept yet.')}</pre>
      <div class="ncd-links">
        ${c.media_url ? `<a href="${esc(c.media_url)}" target="_blank" rel="noreferrer">RENDERED CLIP ↗</a>` : ''}
        ${c.spark ? `<span title="${esc(c.spark)}">SPARK · ${esc(c.spark)}</span>` : ''}
      </div>
    </section>`;
}

function paintDrawer() {
  const c = items.find(x => x.id === drawerId);
  // picked or archived out of the filter it was opened from: nothing to show
  if (!c) { closeDrawer(); return; }
  const aside = drawerEl().querySelector('.ncd');
  const scroll = aside.scrollTop;
  aside.innerHTML = drawerMarkup(c);
  hydrateImages(aside);
  aside.scrollTop = scroll;
}

function openDrawer(id, trigger) {
  const el = drawerEl();
  const wasOpen = drawerId !== null;
  drawerId = id;
  drawerTrigger = trigger;
  el.hidden = false;
  paintDrawer();
  if (drawerId === null) return;
  if (!wasOpen) document.addEventListener('keydown', onDrawerKey);
  el.querySelector('.ncd [data-d="close"]').focus();
}

function closeDrawer() {
  if (drawerId === null) return;
  const id = drawerId;
  drawerId = null;
  document.removeEventListener('keydown', onDrawerKey);
  drawerEl().hidden = true;
  // the board may have repainted under the drawer: find the card again
  const back = (drawerTrigger && drawerTrigger.isConnected) ? drawerTrigger
    : document.querySelector(`#scenelist .nc[data-id="${id}"] .nc-hero`);
  drawerTrigger = null;
  if (back) back.focus();
}

function onDrawerClick(ev) {
  const c = items.find(x => x.id === drawerId);
  const btn = ev.target.closest('button');
  if (!btn || !c) return;
  if (btn.dataset.ref !== undefined) { previewRefs(c, Number(btn.dataset.ref), btn); return; }
  const what = btn.dataset.d;
  if (what === 'close') closeDrawer();
  else if (what === 'hero') previewStills(c, c.reference_image, btn);
  else if (what === 'prompt') {
    if (openPrompts.has(c.id)) openPrompts.delete(c.id); else openPrompts.add(c.id);
    const open = openPrompts.has(c.id);
    btn.textContent = open ? 'HIDE PROMPT' : 'SHOW PROMPT';
    btn.setAttribute('aria-expanded', String(open));
    document.getElementById('ncdprompt').hidden = !open;
  }
}

/* ── the board ── */

export async function renderBoard() {
  const list = $('scenelist');
  let body;
  boardState('loading', 'Loading concepts…');
  try {
    // always ask for the archived ones too, whichever tab is showing.
    // The board is scoped twice -- by brand and by archived -- and a
    // count line that can only see one side of the second scope is how
    // "11 shown · 2/29 picked" ended up reading as 18 missing cards
    // (2026-09-02). One request that knows both numbers can say where
    // everything went; the tabs are a filter over what it returned.
    body = await api('/api/pipeline/concepts?brand='
                     + encodeURIComponent(state.brand) + '&archived=true');
  } catch (e) {
    list.innerHTML = '';
    boardState('error', `Concepts unavailable: ${e.message}`, renderBoard);
    return;
  }
  boardState(null);

  // only one-shot concepts are the unit; a legacy multi-shot row is a
  // different decision and is left to the Dev Studio
  const all = (body.items || []).filter(c => c.is_scene);
  const open = all.filter(c => !c.archived);
  const gone = all.filter(c => c.archived);
  const wantArchived = filter === 'archived';
  items = wantArchived ? gone
    : filter === 'picked' ? open.filter(c => c.picked)
    : open;

  // Named scopes, because every number here answers a different
  // question: open/archived are THIS BRAND, and pick_rate is the
  // account's measurement across both -- windowing it by brand would
  // make it a different statistic (see preprod.pick_rate).
  const rate = body.pick || {};
  const scope = `${state.brand} · ${open.length} open · ${gone.length} archived`;
  $('sccount2').textContent = rate.generated
    ? `${scope} · ${rate.picked}/${rate.generated} picked all time, all brands`
    : scope;

  list.innerHTML = items.length ? items.map(card).join('')
    : `<div class="probeblank">${wantArchived
        ? 'Nothing archived yet'
        : filter === 'picked'
          ? 'Nothing picked yet — the check on a card sends it to Queue'
          : 'No concepts open — type an idea on Studio and hit Create'}</div>`;

  hydrateImages(list);
  // the drawer shows a row of this list; repaint it off the fresh one so
  // a pick made while it is open reads back, prompt still open
  if (drawerId !== null) paintDrawer();

  list.querySelectorAll('.nc').forEach(el => {
    const id = Number(el.dataset.id);
    el.querySelectorAll('[data-ref]').forEach(btn => btn.onclick = () =>
      previewRefs(items.find(c => c.id === id), Number(btn.dataset.ref), btn));
    el.querySelectorAll('[data-act]').forEach(btn => btn.onclick = async () => {
      const act = btn.dataset.act;
      if (act === 'open') { openDrawer(id, btn); return; }
      if (act === 'direct') { openConceptInDirector(id); return; }
      const concept = items.find(c => c.id === id);
      btn.disabled = true;
      try {
        if (act === 'pick') {
          await api(`/api/concepts/${id}/pick`,
            { method: 'POST', body: { picked: !concept.picked } });
        } else {
          await api(`/api/concepts/${id}/archive`,
            { method: 'POST', body: { archived: act === 'archive' } });
        }
        renderBoard();
        refreshQueueBadge();
      } catch (e) {
        btn.disabled = false;
        boardState('error', e.message);
      }
    });
  });
}

export function initBoard() {
  if (wired) return;
  wired = true;
  $('scfilters').querySelectorAll('.cat').forEach(b => b.onclick = () => {
    filter = b.dataset.scf;
    $('scfilters').querySelectorAll('.cat').forEach(o =>
      o.setAttribute('aria-pressed', String(o === b)));
    renderBoard();
  });
  // a Create fired from Studio lands here, so the board says what it is
  // waiting for rather than sitting empty
  bus.addEventListener('job', e => {
    const job = e.detail;
    if (document.documentElement.dataset.v !== 'pipeline') return;
    if (!['scenes', 'concept', 'render', 'direct', 'refine'].includes(job.kind)) return;
    if (['queued', 'running'].includes(job.status)) {
      // The chain saves every concept at the writing stage and then
      // spends most of the run enhancing and keyframing them one at a
      // time. Once the cards exist, show them — otherwise the board
      // sits under a spinner for a minute over finished work. The job
      // rail keeps narrating the rest.
      const landed = /^(enhancing|rendering keyframe|parked)/.test(job.detail || '');
      if (landed) renderBoard();
      else boardState('loading', job.detail || 'Writing — they appear here as they land');
    } else if (job.status === 'done') {
      renderBoard();
    } else if (job.status === 'failed') {
      boardState('error', job.error || 'Generation failed');
    }
  });
}

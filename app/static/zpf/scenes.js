/* The board: the concepts one idea produced, and the pick.

   A concept IS a scene IS one prompt -- one row in shoot_concepts with a
   single shot -- so this is the only card in the product and there is no
   second data model behind it. What the board asks is one question:
   which of these is worth the spend.

   Each card carries the references it was written against ABOVE, the
   concept, and the prompt that came back BELOW. Picking one is the
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
import { api, bus, esc, state, stateline } from './shared.js';
import { openConceptInDirector } from './workflows.js';

let wired = false;
let filter = '';               // '' open | picked | archived
let items = [];
// which cards have their prompt open. Kept out here because the board
// re-renders whole on every pick/archive, and a <details> that snapped
// shut every time you picked a sibling would be worse than no toggle.
const openPrompts = new Set();

const $ = id => document.getElementById(id);

function boardState(kind, message, retry) {
  stateline($('scstate'), kind, message, retry);
}

/* ── a card ── */

function card(c) {
  const refs = (c.refs || []).map(url =>
    `<span class="scref" style="background-image:url('${esc(url)}')"></span>`).join('');
  const shot = c.reference_image
    ? `<img class="scshot" src="${esc(c.reference_image)}" alt="">` : '';
  const clip = c.media_url
    ? `<a class="tag" href="${esc(c.media_url)}" target="_blank" rel="noreferrer">clip ↗</a>` : '';
  // what this card is waiting on, said plainly
  const status = c.archived ? (c.graded ? 'ARCHIVED · GRADED' : 'ARCHIVED · AWAITING GRADE')
    : c.media_url ? 'RENDERED'
    : c.picked ? 'PICKED · AWAITING APPROVAL IN QUEUE'
    : c.parked ? 'KEYFRAMED · AWAITING APPROVAL IN QUEUE'
    : '';
  return `
  <article class="glass scene${c.picked || c.parked ? ' on' : ''}${c.archived ? ' off' : ''}" data-id="${c.id}">
    <div class="screfs">
      ${refs || '<span class="m">no references</span>'}
      <span class="spacer"></span>
      <span class="m">${esc(c.spark || '')}</span>
    </div>
    <div class="schead">
      <h4>${esc(c.title)}</h4>
      <span class="m">${esc(c.n || '')}</span>
      <span class="spacer"></span>
      ${clip}
      <span class="m">${status}</span>
    </div>
    ${c.summary ? `<p class="scsum" title="${esc(c.summary)}">${esc(c.summary)}</p>` : ''}
    ${shot}
    <details class="scdet"${openPrompts.has(c.id) ? ' open' : ''}>
      <summary class="m">Prompt</summary>
      <p class="scprompt">${esc(c.prompt)}</p>
    </details>
    ${(c.warnings || []).length
      ? `<div class="cwarn">${c.warnings.map(w => '⚠ ' + esc(w)).join('<br>')}</div>` : ''}
    <!-- the verdict, as two icons (2026-09-02): the whole board is one
         binary question asked of four cards at once, and X / check reads
         faster than two words of the same size. Same two calls behind
         them as before: pick toggles picked_at, X archives (never
         deletes -- an unpicked row is the only negative signal here). -->
    <div class="scfoot">
      ${c.archived
        ? '<button class="tag" data-act="restore">Put back on the board</button>'
        : `<button class="swipe no" data-act="archive" title="Not this one"
                   aria-label="Not this one — take it off the board">✕</button>
           <button class="swipe yes${c.picked ? ' on' : ''}" data-act="pick"
                   title="${c.picked ? 'Picked — click to unpick' : 'Pick this'}"
                   aria-pressed="${c.picked ? 'true' : 'false'}"
                   aria-label="${c.picked ? 'Unpick this concept' : 'Pick this concept'}">✓</button>`}
      <span class="spacer"></span>
      <button class="go" data-act="direct">Open in Director</button>
    </div>
  </article>`;
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

  list.querySelectorAll('.scene').forEach(el => {
    const id = Number(el.dataset.id);
    const det = el.querySelector('.scdet');
    if (det) det.addEventListener('toggle', () =>
      det.open ? openPrompts.add(id) : openPrompts.delete(id));
    el.querySelectorAll('[data-act]').forEach(btn => btn.onclick = async () => {
      const act = btn.dataset.act;
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

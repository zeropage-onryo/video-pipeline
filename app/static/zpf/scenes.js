/* Scenes — the unit you pick between.

   One idea in, several standalone scenes out. A scene IS a one-shot
   concept (Mike's 2026-08-26 shape) -- no second data model -- so these
   cards read /api/pipeline/concepts and every one of them opens in
   Director, renders and posts exactly as concepts always did.

   Each card is laid out the way Mike asked for it: the references it
   was grounded in ABOVE, the scene itself, and the prompt that came
   back BELOW. Picking one is the label (preprod.pick_rate), and a
   picked scene's references ride into the enhance, the keyframe and
   the clip when it reaches the canvas. */
import { api, bus, esc, state, stateline, wireMentions } from './shared.js';
import { openConceptInDirector } from './workflows.js';

let wired = false;
let filter = '';               // '' | idea | picked
let runJobId = null;
const attached = [];           // reference photos picked for the next run

const $ = id => document.getElementById(id);

function scState(kind, message) {
  stateline($('scstate'), kind, message);
}

/* ── the composer ── */

async function pickReferences() {
  // the same media the Studio composer attaches from: real asset photos
  let media;
  try {
    media = await api('/api/media');
  } catch (e) {
    scState('error', `Could not load media: ${e.message}`);
    return;
  }
  if (!media.items.length) {
    scState('empty', 'No photos yet — add rooms, characters or props on Assets first');
    return;
  }
  // a lightweight picker reusing the workflow modal's grid styling
  const grid = $('wfmgrid');
  $('wfmtitle').textContent = 'Attach references';
  $('wfmtextwrap').hidden = true;
  $('wfmmediawrap').hidden = false;
  $('wfmpresetrow').hidden = true;
  $('wfmsave').hidden = false;
  $('wfmsave').textContent = 'Attach';
  grid.innerHTML = media.items.map(m => `
    <button class="mtile" type="button" data-u="${esc(m.url)}"
            aria-pressed="${attached.includes(m.url)}"
            style="background-image:url('${m.url}')">
      <span class="mname">${esc(m.asset_name)}</span>
    </button>`).join('');
  grid.querySelectorAll('.mtile').forEach(tile => tile.onclick = () => {
    const url = tile.dataset.u;
    const at = attached.indexOf(url);
    if (at >= 0) attached.splice(at, 1); else attached.push(url);
    tile.setAttribute('aria-pressed', String(attached.includes(url)));
  });
  $('dscrim').setAttribute('data-open', '');
  $('wfmodal').setAttribute('data-open', '');
  $('wfmsave').onclick = () => {
    $('wfmodal').removeAttribute('data-open');
    $('dscrim').removeAttribute('data-open');
    $('wfmsave').textContent = 'Save';
    renderAttached();
  };
}

function renderAttached() {
  $('scattach').innerHTML = attached.map((url, i) => `
    <span class="gatt" style="background-image:url('${url}')">
      <button class="ax" data-i="${i}" aria-label="Remove reference">✕</button>
    </span>`).join('');
  $('scattach').querySelectorAll('.ax').forEach(b => b.onclick = () => {
    attached.splice(+b.dataset.i, 1);
    renderAttached();
  });
}

async function runScenes() {
  const idea = $('sceneidea').value.trim();
  if (!idea) return;
  const go = $('scgo');
  go.disabled = true; go.textContent = 'Writing…';
  try {
    const res = await api('/api/scenes/run', {
      method: 'POST',
      body: { idea, count: Number($('sccount').value) || 4,
              refs: attached, brand: state.brand },
    });
    runJobId = res.job_id;
    scState('loading', 'Writing the scenes — they appear here as they land');
  } catch (e) {
    go.disabled = false; go.textContent = 'Write the scenes';
    scState('error', e.message);
  }
}

/* ── the board ── */

function card(scene) {
  const refs = (scene.refs || []).map(url =>
    `<span class="scref" style="background-image:url('${esc(url)}')"></span>`).join('');
  const shot = scene.reference_image
    ? `<img class="scshot" src="${esc(scene.reference_image)}" alt="">` : '';
  const clip = scene.media_url
    ? `<a class="tag" href="${esc(scene.media_url)}" target="_blank" rel="noreferrer">clip ↗</a>` : '';
  const picked = !!scene.picked;
  return `
  <article class="glass scene${picked ? ' on' : ''}" data-id="${scene.id}">
    <div class="screfs">
      ${refs || '<span class="m">no references</span>'}
      <span class="spacer"></span>
      <span class="m">${esc(scene.spark || '')}</span>
    </div>
    <div class="schead">
      <h4>${esc(scene.title)}</h4>
      <span class="m">${esc(scene.n || '')}</span>
      <span class="spacer"></span>
      ${clip}
      <span class="m">${picked ? 'PICKED' : ''}</span>
    </div>
    ${shot}
    <p class="scprompt">${esc(scene.prompt)}</p>
    <div class="scfoot">
      <button class="tag" data-act="pick">${picked ? 'Unpick' : 'Pick this'}</button>
      <span class="spacer"></span>
      <button class="go" data-act="direct">Open in Director</button>
    </div>
  </article>`;
}

export async function renderScenes() {
  const list = $('scenelist');
  let body;
  try {
    body = await api('/api/pipeline/concepts?brand=' + encodeURIComponent(state.brand));
  } catch (e) {
    scState('error', e.message);
    return;
  }
  // only one-shot concepts are scenes; a legacy multi-shot concept is a
  // different thing and stays on the Concept tab
  let items = (body.items || []).filter(c => c.is_scene);
  if (filter === 'picked') items = items.filter(c => c.picked);
  if (filter === 'idea') items = items.filter(c => !c.picked);
  const rate = body.pick || {};
  $('sccount2').textContent = rate.generated
    ? `${items.length} shown · ${rate.picked}/${rate.generated} picked`
    : `${items.length}`;
  list.innerHTML = items.length ? items.map(card).join('')
    : '<div class="probeblank">No scenes yet — type an idea above and write some</div>';

  list.querySelectorAll('.scene').forEach(el => {
    const id = Number(el.dataset.id);
    el.querySelectorAll('[data-act]').forEach(btn => btn.onclick = async () => {
      const act = btn.dataset.act;
      if (act === 'direct') { openConceptInDirector(id); return; }
      const scene = items.find(s => s.id === id);
      try {
        await api(`/api/concepts/${id}/pick`,
          { method: 'POST', body: { picked: !scene.picked } });
        renderScenes();
      } catch (e) {
        scState('error', e.message);
      }
    });
  });
}

export function initScenes() {
  if (wired) return;
  wired = true;
  $('scgo').onclick = runScenes;
  $('scup').onclick = pickReferences;
  wireMentions($('sceneidea'), $('scmentions'));
  $('scfilters').querySelectorAll('.cat').forEach(b => b.onclick = () => {
    filter = b.dataset.scf;
    $('scfilters').querySelectorAll('.cat').forEach(o =>
      o.setAttribute('aria-pressed', String(o === b)));
    renderScenes();
  });
  bus.addEventListener('job', e => {
    const job = e.detail;
    if (job.id !== runJobId || !['done', 'failed'].includes(job.status)) return;
    runJobId = null;
    $('scgo').disabled = false; $('scgo').textContent = 'Write the scenes';
    if (job.status === 'done') {
      scState(null);
      renderScenes();
    } else {
      scState('error', job.error || 'Generation failed');
    }
  });
}

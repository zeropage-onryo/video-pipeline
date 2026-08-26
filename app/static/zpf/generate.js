/* Generate tab — Higgsfield-simple single generation over the same four
   primitives Concept uses. Pick a camera preset, type an instruction
   (@ pulls a character/prop/room from the memory bank and auto-attaches
   its reference photo), optionally attach image/video references, hit
   Generate. The server grounds (reference_block), enhances (Gemini,
   preset folded in), saves the result as a REAL one-shot concept row
   (or appends a shot to an existing concept), then renders through the
   honestly-gated Nano/Runway paths. */
import { api, bus, esc, loadPresets, fillPresetSelect, state, stateline, wireMentions } from './shared.js';

let wired = false;
let uploads = [];        // File objects
let assetPhotos = [];    // picked site-relative photo URLs (from @ mentions)
let pendingJob = null;

const $ = id => document.getElementById(id);

function paintAttachments() {
  const bar = $('genattach');
  bar.innerHTML = [
    ...assetPhotos.map((u, i) => `
      <span class="gatt" data-k="a" data-i="${i}" style="background-image:url('${u}')">
        <button class="ax" title="Remove">✕</button></span>`),
    ...uploads.map((f, i) => `
      <span class="gatt file" data-k="f" data-i="${i}">
        <span class="an">${esc(f.name)}</span>
        <button class="ax" title="Remove">✕</button></span>`),
  ].join('');
  bar.querySelectorAll('.ax').forEach(x => x.onclick = () => {
    const holder = x.closest('.gatt');
    if (holder.dataset.k === 'a') assetPhotos.splice(+holder.dataset.i, 1);
    else uploads.splice(+holder.dataset.i, 1);
    paintAttachments();
  });
}

async function fillConceptPicker() {
  const pick = $('genconcept');
  const current = pick.value;
  try {
    const data = await api(`/api/pipeline/concepts?brand=${encodeURIComponent(state.brand)}`);
    pick.innerHTML = '<option value="">Save as new concept</option>' +
      data.items.map(c =>
        `<option value="${c.id}">Attach to ${esc(c.n)} · ${esc(c.title)}</option>`).join('');
    pick.value = current;
  } catch { /* the picker just stays "new concept" */ }
}

function paintResult(job) {
  const box = $('genresult');
  if (job.status === 'failed') {
    stateline($('genstate'), 'error', job.error || 'Generation failed');
    box.innerHTML = '';
    return;
  }
  stateline($('genstate'), null);
  box.innerHTML = `<div class="glass panel" style="margin-inline:42px">
    <div class="ptitle">SHOOT-${String(job.ref_id).padStart(2, '0')} · ${esc(job.detail || 'saved')}</div>
    <div class="promptblk"><div class="plabel">enhanced prompt — stored on the shot</div>
      <pre>${esc(job.output || '')}</pre></div>
    <div class="mediarow">
      <button class="btn" id="genopenconcept">Open in Concept tab</button>
      <button class="btn pri" id="genopendirector">Open in Director</button>
    </div>
  </div>`;
  $('genopenconcept').onclick = () =>
    import('./pipeline.js').then(m => m.showTab('concept', job.ref_id));
  $('genopendirector').onclick = () =>
    import('./workflows.js').then(m => m.openConceptInDirector(job.ref_id));
}

export function initGenerate() {
  if (wired) return;
  wired = true;

  const prompt = $('genprompt');
  const go = $('gengo');
  prompt.addEventListener('input', () =>
    go.disabled = !prompt.value.trim() || !state.caps['pipeline.run']);

  wireMentions(prompt, $('genmentions'), item => {
    // a mention names the asset in the prompt AND anchors its photo
    if (item.thumb && !assetPhotos.includes(item.thumb)) {
      assetPhotos.push(item.thumb);
      paintAttachments();
    }
  });

  $('genup').onclick = () => $('genfiles').click();
  $('genfiles').onchange = () => {
    uploads.push(...$('genfiles').files);
    $('genfiles').value = '';
    paintAttachments();
  };

  go.onclick = async () => {
    const text = prompt.value.trim();
    if (!text) return;
    go.disabled = true; go.textContent = 'Generating…';
    const body = new FormData();
    body.append('prompt', text);
    if ($('genpreset').value) body.append('preset', $('genpreset').value);
    body.append('output', $('genout').value);
    if ($('genconcept').value) body.append('concept_id', $('genconcept').value);
    uploads.forEach(f => body.append('files', f));
    assetPhotos.forEach(u => body.append('asset_photos', u));
    try {
      const res = await api('/api/generate/run', { method: 'POST', body });
      pendingJob = res.job_id;
      stateline($('genstate'), 'loading', 'Generating — grounding, enhancing, rendering…');
      $('genresult').innerHTML = '';
    } catch (e) {
      stateline($('genstate'), 'error', e.message);
    } finally {
      go.disabled = !prompt.value.trim(); go.textContent = 'Generate';
    }
  };

  bus.addEventListener('job', e => {
    const job = e.detail;
    if (job.id === pendingJob && ['done', 'failed'].includes(job.status)) {
      pendingJob = null;
      paintResult(job);
    }
  });
}

export async function renderGenerate() {
  $('gengo').disabled = !$('genprompt').value.trim() || !state.caps['pipeline.run'];
  fillPresetSelect($('genpreset'), await loadPresets());
  await fillConceptPicker();
}

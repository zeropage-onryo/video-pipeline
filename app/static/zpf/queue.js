/* Queue: the approval gate, then the job registry.

   Rendering is the only step in this pipeline that spends real money,
   so it is the only one with a gate in front of it (2026-08-28).
   A scene arrives here two ways: the Studio chain PARKS it once it has
   a concept, an enhanced prompt and a keyframe -- everything that can
   be done without spending -- or you pick a text-only concept off the
   Pipeline board yourself. Approving is what actually calls Runway,
   and on a parked scene approving is also the pick.

   The pending list is derived from the rows (parked or picked, not
   archived, no clip yet) rather than from the jobs registry -- the registry is an
   in-process dict that a restart clears, and an approval queue that
   quietly emptied itself on restart would be a queue that lies. The
   Jobs list underneath IS that registry, and says so.

   Between the two sits the SUBSCRIPTION LANE, which is the opposite
   kind of spend: Runway's Explore Mode is free on the operator's
   Unlimited plan but has no API parameter, so the render happens by
   hand in Chrome and the finished mp4 comes back as a drag onto its
   card. Its markup is server-rendered behind the operator flag
   (app/main.py's /ui), so on any other account #lanelist does not exist
   and everything below no-ops -- and the routes re-ask the gate anyway,
   because a missing section is presentation and not protection. */
import { ICON, brandName, heroMarkup, heroOf, partsOf, previewRefs, previewStills,
         refThumbs, shotsLabel, windowLabel } from './cards.js';
import { hydrateImages, imgTag } from './preview.js';
import { renderRendererKeys } from './renderer-keys.js';
import { api, bus, esc, refreshQueueBadge, state, stateline } from './shared.js';

let wired = false;

/* The renderer you picked on a card, kept by concept id across repaints
   of the pending list (2026-09-11). Repaints happen without you asking --
   any job finishing re-reads the rows -- and each one used to rebuild the
   card from its default, so a card moved from Runway to Kling was put
   back on Runway between the pick and the click. Keyed by id, so it can
   never follow you onto a different scene; dropped once that card is
   approved or rejected. */
const held = new Map();

/* What you just did to a card, shown on it as a bone tag (2026-09-17):
   RENDERING for as long as the approve's job is live, ARCHIVED / SHOT BY
   HAND for the beat before the card leaves the list. Display only -- the
   rows decide what is pending; this only stops an approved card looking
   untouched, and its priced button looking pressable twice, while the
   render runs. */
const acted = new Map();      // concept id -> { status, job?, at }

/* Which card's renderer popover is open. Out here for held's reason: a
   repaint nobody asked for must not close it under the pointer. Its
   dismiss listeners exist only while it is open. */
let openPop = null;
let repaintZone = () => {};

function onPopDismiss(ev) {
  if (ev.type === 'keydown') {
    if (ev.key !== 'Escape') return;
    const id = openPop;
    setPop(null);
    // the chip was rebuilt by the repaint: focus the new one
    document.querySelector(`#pendlist .nc[data-id="${id}"] .nq-chip`)?.focus();
    return;
  }
  if (ev.target.closest && ev.target.closest('.nq-chipwrap')) return;
  setPop(null);
}

function setPop(id) {
  const before = openPop;
  if (before === id) return;
  openPop = id;
  if (before === null && id !== null) {
    document.addEventListener('pointerdown', onPopDismiss);
    document.addEventListener('keydown', onPopDismiss);
  } else if (id === null) {
    document.removeEventListener('pointerdown', onPopDismiss);
    document.removeEventListener('keydown', onPopDismiss);
  }
  if (before !== null) repaintZone(before);
  if (id !== null) repaintZone(id);
}

/* The lane's list of a timed scene's shots: window, still, its own refs,
   a tick once its clip is back. At module level because renderLane calls
   it too -- it used to live inside renderPending, out of the lane's
   reach, so a lane card would have thrown a ReferenceError. */
function shotStrip(c) {
  const tl = c.timeline;
  if (!tl || !(tl.parts || []).length) return '';
  const rows = tl.parts.map(p => {
    const refs = (p.refs || []).map(url =>
      `<span class="scref sm" style="background-image:url('${esc(url)}')"></span>`).join('');
    return `<li class="scpart${p.media_url ? ' done' : ''}">
      <span class="m scwin">${esc(p.start)}–${esc(p.end)}s</span>
      ${p.reference_image ? `<img class="scpartshot" src="${esc(p.reference_image)}" alt="">` : ''}
      <span class="scparttext" title="${esc(p.prompt || p.text || '')}">${esc(p.text || p.prompt || '')}</span>
      <span class="scpartrefs">${refs}</span>
      ${p.media_url ? `<a class="m" href="${esc(p.media_url)}" target="_blank" rel="noopener">clip ✓</a>` : ''}
    </li>`;
  }).join('');
  const head = tl.planned
    ? `${tl.parts.length} shots · ${esc(tl.seconds)}s · each rendered on its own`
    : `${tl.parts.length} timed shots · planned when you approve`;
  return `<details class="scparts" open><summary class="m">${head}</summary><ol>${rows}</ol></details>`;
}

const $ = id => document.getElementById(id);

export function initQueue() {
  if (wired) return;
  wired = true;
  bus.addEventListener('job', e => {
    if (document.documentElement.dataset.v !== 'queue') return;
    paint();
    // a finished render leaves the pending list, so re-read the rows
    if (['done', 'failed'].includes(e.detail.status)) renderPending();
  });
}

export async function renderQueue() {
  // arriving on the view is not a repaint: a popover left open when
  // you walked away does not greet you on the way back (the PICK does)
  setPop(null);
  await Promise.all([renderPending(), renderLane(), renderJobs(),
                     renderRendererKeys()]);
}

/* ── awaiting approval ── */

async function renderPending() {
  const list = $('pendlist');
  let data;
  stateline($('pendstate'), 'loading', 'Loading…');
  try {
    data = await api('/api/queue/pending?brand=' + encodeURIComponent(state.brand));
  } catch (e) {
    list.innerHTML = '';
    stateline($('pendstate'), 'error', `Queue unavailable: ${e.message}`, renderPending);
    return;
  }
  stateline($('pendstate'), null);

  const renderers = data.renderers || {};
  const order = Object.keys(renderers);

  /* Each vendor's state, stated honestly rather than shown as a dead
     button. Before 2026-09-08 this line described Runway alone, because
     Runway was the only thing approving could call; before 2026-09-09 it
     also reported a spend gate, which is gone -- pressing Approve IS the
     approval now, so a key is the only thing that can be missing. What
     is still worth printing is the day's count against the cap, which is
     the only automatic wall left. */
  $('rwstate').textContent = order.length
    ? order.map(name => {
        const r = renderers[name];
        if (!r.available) return `${r.label}: no key`;
        const today = (r.today === null || r.today === undefined) ? ''
          : ` · ${r.today}${r.cap ? '/' + r.cap : ''} today`;
        return `${r.label}: ready${today}`;
      }).join('  ·  ')
    : 'No renderer is configured — approving cannot render';

  const cards = new Map(data.items.map(c => [c.id, c]));
  /* The picked renderer per card, held only for this paint. A pick is a
     decision about ONE approve, not a preference to remember: the next
     scene may be planned for a different tool, and silently carrying the
     last choice onto it is how you spend $3.20 of Veo on something you
     meant to run through LTX. */
  const picks = new Map();

  /* A renderer is usable when it has a key AND the model is reachable on
     this account. Both halves matter: Runway's models always report
     available (render_specs has no per-account probe), so reading only
     the model let a keyless vendor win the default. */
  const usable = (provider, model) => {
    const r = renderers[provider];
    const spec = specOf(provider, model);
    return !!(r && r.available && spec && spec.available);
  };

  const specOf = (provider, model) =>
    ((renderers[provider] || {}).models || []).find(m => m.id === model) || null;

  /* The fallback when the plan cannot render: the CHEAPEST usable model
     at its own default length, not the first in registry order -- the
     registry lists Veo second, and a card quietly defaulting to a $3
     preview render because Runway had no key is the silent-spend shape
     the picks comment above is warning about. Unpriced models sort last. */
  function firstUsable() {
    let best = null;
    for (const name of order) {
      // a vendor with no key is not usable, however many models it lists
      if (!renderers[name].available) continue;
      for (const m of renderers[name].models || []) {
        if (!m.available) continue;
        const usd = estimate(m, { frame: m.frame.default }, m.duration.default);
        const cost = (usd === null || usd === undefined) ? Infinity : usd;
        if (!best || cost < best.cost) best = { provider: name, model: m.id, cost };
      }
    }
    return best && { provider: best.provider, model: best.model };
  }

  function pickFor(card) {
    if (picks.has(card.id)) return picks.get(card.id);
    const kept = held.get(card.id);
    if (kept && usable(kept.provider, kept.model)) {
      picks.set(card.id, kept);
      return kept;
    }
    // the server resolved the shot's planned tool into (provider, model)
    // with the same function the approve route uses -- see render_default
    const want = card.render_default || {};
    // THE PLAN, UNLESS IT CANNOT RENDER (2026-09-11). Every scene the
    // chain writes is planned for RUNWAY, and on an account with no
    // Runway key that opened every card on a dead button reading "Runway
    // key not set" -- and any repaint (a job finishing, coming back to
    // the Queue) snapped a card you had moved to Kling back onto it. A
    // plan nobody can render is not a default; the first vendor that
    // CAN is. The planned renderer still leads whenever it has a key.
    const base = usable(want.provider, want.model)
      ? { provider: want.provider, model: want.model }
      : (firstUsable() || (specOf(want.provider, want.model)
          ? { provider: want.provider, model: want.model } : null));
    let pick = null;
    if (base) {
      const spec = specOf(base.provider, base.model);
      pick = { ...base, duration: spec.duration.default, frame: spec.frame.default };
    }
    picks.set(card.id, pick);
    return pick;
  }

  /* A LABEL, not an invoice. The server computes the authoritative
     estimate in providers.check_render_choice on the way in and hands it
     back on the approve response; this multiplies the rate card the
     catalogue ships so that dragging a duration does not cost a request
     per keystroke. tests/test_providers.py asserts the two agree for
     every model, duration and frame. */
  function estimate(spec, pick, seconds = pick.duration) {
    const price = spec && spec.price;
    if (!price) return null;
    if (price.kind === 'flat') return price.usd;
    const per = price.usd_by_frame ? price.usd_by_frame[pick.frame] : price.usd;
    return (per === undefined || per === null) ? null : per * seconds;
  }

  /* A timed scene's shots each render at their own window's length,
     fitted UP to what the model can make -- the JS twin of
     timeline.fit_seconds, for the reason estimate() above exists: the
     server's check_timeline_choice is the authoritative number and comes
     back on the approve response; this is the label while you pick. */
  function fitSeconds(axis, seconds) {
    const want = Math.max(1, Math.ceil(Number(seconds) || 1));
    if (axis.kind === 'range') return Math.min(Math.max(want, axis.min), axis.max);
    const values = (axis.values || []).map(Number).sort((a, b) => a - b);
    if (!values.length) return want;
    if (axis.kind === 'fixed') return values[0];
    return values.find(v => v >= want) ?? values[values.length - 1];
  }

  function shotsToRender(card) {
    const tl = card.timeline;
    return tl ? (tl.parts || []).filter(p => !p.media_url) : null;
  }

  /* ── the renderer, as ONE chip and a popover (2026-09-17) ──
     Same catalogue, same three axis kinds, same held pick; what changed
     is that three selects became pills behind one 44px button that reads
     the whole choice back ("KLING 2.1 · 5S · 720P"). */

  // a card the reference gate would refuse. _waiting() already keeps such
  // a row out of this list, so today this is never true of a real card;
  // it is drawn for the day one arrives, and it is DISPLAY -- the server
  // refuses the approve whatever the button looks like.
  const lockedFor = card => !(card.refs || []).length;

  function pills(role, axis, value, unit) {
    if (axis.kind === 'range') {
      // a real span, so 7s on a model that renders 1-20s is a real
      // request rather than a value rounded to the nearest pill
      return `<span class="nq-span"><input class="nq-num" type="number" data-role="${role}"
                min="${axis.min}" max="${axis.max}" step="1" value="${esc(value)}"
                aria-label="Length in seconds, ${axis.min} to ${axis.max}"><span>sec · ${axis.min}–${axis.max}</span></span>`;
    }
    // "fixed" is an admission, not an option: the note says whether this
    // vendor offers one value or whether nobody here has verified the list
    const fixed = axis.kind === 'fixed';
    return axis.values.map(v => `
      <button type="button" class="nq-pill" data-role="${role}" data-value="${esc(v)}"
              aria-pressed="${String(v) === String(value)}"${fixed ? ' disabled' : ''}
              title="${esc(fixed ? (axis.note || 'the only value this model offers') : '')}">${esc(v)}${unit}</button>`).join('');
  }

  function modelPills(pick) {
    return order.map(name => {
      const r = renderers[name];
      // a vendor with no key is one dead pill, not a row of them
      if (!r.available) {
        return `<button type="button" class="nq-pill" disabled>${esc(r.label)} · no key</button>`;
      }
      return (r.models || []).map(m => `
        <button type="button" class="nq-pill" data-role="model" data-value="${esc(name)}|${esc(m.id)}"
                aria-pressed="${pick.provider === name && pick.model === m.id}"${m.available ? '' : ' disabled'}
                title="${esc(r.label)}">${esc(m.label)}${m.available ? '' : ' · not on this account'}</button>`).join('');
    }).join('');
  }

  /* what an approve would make and cost: the count, the lengths, the
     label's price. null usd = a model with no rate card, said as such */
  function plan(card, spec, pick) {
    const todo = shotsToRender(card);
    if (!todo) return { timed: false, n: 1, lengths: [pick.duration], usd: estimate(spec, pick) };
    const lengths = todo.map(p => fitSeconds(spec.duration, p.seconds));
    const each = lengths.map(sec => estimate(spec, pick, sec));
    return { timed: true, n: todo.length, lengths,
             usd: each.some(v => v === null || v === undefined) ? null
               : each.reduce((sum, v) => sum + v, 0) };
  }

  const approveText = ({ n, usd }) =>
    `Approve · ${n} shot${n === 1 ? '' : 's'} · ${usd === null || usd === undefined ? 'unpriced' : '~$' + usd.toFixed(2)}`;

  function renderZone(card) {
    const pick = pickFor(card);
    const locked = lockedFor(card);
    const did = acted.get(card.id);
    const title = esc(card.title || 'this scene');
    const side = `
        <button type="button" class="nq-side" data-act="reject" title="Reject — archive it"
                aria-label="Reject ${title}"${did ? ' disabled' : ''}>${ICON.x}</button>
        <button type="button" class="nq-side${did && did.status === 'SHOT BY HAND' ? ' on' : ''}" data-act="shot"
                title="Shot it yourself"${did ? ' disabled' : ''}
                aria-label="Mark ${title} as shot by hand — made outside the render pipeline">${ICON.camera}</button>`;
    if (!pick || locked) {
      const why = locked ? 'Add references to approve' : 'No renderer is configured';
      return `
      <div class="nq-chipwrap">
        <button type="button" class="nq-chip" disabled aria-label="Renderer locked">
          <span>${locked ? 'RENDERER LOCKED' : 'NO RENDERER CONFIGURED'}</span>${ICON.caret}</button>
      </div>
      <div class="nq-actions">
        <button type="button" class="nq-approve" data-act="approve" disabled>${why}</button>${side}
      </div>`;
    }
    const r = renderers[pick.provider];
    const spec = specOf(pick.provider, pick.model);
    // one reason left, and it is the only one a restart could ever have
    // fixed: no key for this vendor
    const blocked = r.available ? '' : `${r.label} key not set`;
    const p = plan(card, spec, pick);
    const chip = `${spec.label} · ${p.timed ? `${p.n} shot${p.n === 1 ? '' : 's'}` : `${pick.duration}s`} · ${pick.frame}`.toUpperCase();
    const open = openPop === card.id && !did;
    const pop = !open ? '' : `
        <div class="nq-pop" role="dialog" aria-label="Renderer for ${title}">
          <div class="nq-popk">MODEL</div>
          <div class="nq-pills">${modelPills(pick)}</div>
          <div class="nq-two">
            <div>
              <div class="nq-popk">LENGTH${p.timed ? ' · PER SHOT' : ''}</div>
              <div class="nq-pills">${p.timed
                // no length control: every shot's length is its window's
                ? `<span class="nq-note" title="each shot renders at its own window's length, fitted up to what ${esc(spec.id)} can make">${esc(p.lengths.join(' + '))}s · set by the windows</span>`
                : pills('duration', spec.duration, pick.duration, 's')}</div>
            </div>
            <div>
              <div class="nq-popk">FRAME · ${esc(String(r.frame_axis || 'resolution').toUpperCase())}</div>
              <div class="nq-pills">${pills('frame', spec.frame, pick.frame, '')}</div>
            </div>
          </div>
          <div class="nq-note">Greyed out = no API key on this account</div>
        </div>`;
    return `
      <div class="nq-chipwrap">
        <button type="button" class="nq-chip" data-act="chip" aria-haspopup="dialog" aria-expanded="${open}"
                aria-label="Change renderer — ${esc(chip)}"${did ? ' disabled' : ''}>
          <span>${esc(chip)}</span>${ICON.caret}</button>${pop}
      </div>
      <div class="nq-actions">
        <button type="button" class="nq-approve${blocked ? ' rblocked' : ''}" data-act="approve"${blocked || did ? ' disabled' : ''}>
          ${did ? esc(did.status === 'RENDERING' ? 'Rendering…' : did.status)
            : blocked ? esc(blocked) : esc(approveText(p))}</button>${side}
      </div>`;
  }

  /* The shots a timed scene renders as, as frames whose WIDTH is their
     share of the scene: window label, the still that shot's clip anchors
     on (click to enlarge), a tick once its clip is back. An unplanned
     timeline shows bare windows -- the approve plans them first. */
  function shotFrames(c) {
    const parts = partsOf(c);
    if (!parts.length) return '';
    return `<div class="nq-shots" role="group" aria-label="${esc(shotsLabel(c))}">` + parts.map(p => {
      const grow = Number(p.seconds) > 0 ? Number(p.seconds) : 1;
      const label = `<span class="nq-win">${esc(windowLabel(p))}${p.media_url ? ' ✓' : ''}</span>`;
      const tip = esc(p.text || p.prompt || '');
      return p.reference_image
        ? `<button type="button" class="nq-shot${p.media_url ? ' done' : ''}" style="flex-grow:${grow}" title="${tip}"
                   data-still="${esc(p.reference_image)}"
                   aria-label="Preview shot ${esc(p.n)} still, ${esc(windowLabel(p))}">${imgTag(p.reference_image, { dead: '' })}${label}</button>`
        : `<div class="nq-shot${p.media_url ? ' done' : ''}" style="flex-grow:${grow}" title="${tip}">${label}</div>`;
    }).join('') + '</div>';
  }

  // a RENDERING tag outlives its job by nothing: once the registry says
  // the job ended (or, after a restart, has never heard of it) it goes
  for (const [id, did] of acted) {
    if (did.status !== 'RENDERING') continue;
    const job = state.jobs.get(did.job);
    const live = job ? ['queued', 'running'].includes(job.status) : Date.now() - did.at < 5000;
    if (!live || !cards.has(id)) acted.delete(id);
  }
  if (openPop !== null && !cards.has(openPop)) setPop(null);

  const lockedCount = data.items.filter(lockedFor).length;
  $('pendcount').textContent = `${data.items.length} waiting`
    + (lockedCount ? ` · ${lockedCount} blocked` : '');

  list.innerHTML = data.items.length ? data.items.map(c => {
    const locked = lockedFor(c);
    const did = acted.get(c.id);
    const title = esc(c.title || 'Untitled');
    const hero = heroOf(c);
    const why = c.park_reason
      || (c.reference_image ? 'anchors on the keyframe' : 'text-to-video · no keyframe yet');
    return `
    <article class="nc nq${locked ? ' locked' : ''}${did && did.status !== 'RENDERING' ? ' acted' : ''}" data-id="${c.id}">
      <button type="button" class="nc-hero" data-act="key"${hero.kind === 'none' ? ' disabled' : ''}
              aria-label="Preview ${hero.kind === 'ref' ? 'reference' : 'keyframe'} for ${title}">
        ${heroMarkup(c)}
        <span class="nc-tag tl">${esc(brandName(c.brand))}</span>
        ${locked ? '<span class="nc-tag tr red">NO REFS</span>' : ''}
        <span class="nc-tag br bone" data-role="status"${did ? '' : ' hidden'}>${esc(did ? did.status : '')}</span>
      </button>
      ${shotFrames(c)}
      <div class="nc-body">
        <div class="nc-row">
          <div class="nc-text">
            <h4 class="nc-title" title="${title}">${title}</h4>
            ${c.summary ? `<p class="nc-line" title="${esc(c.summary)}">${esc(c.summary)}</p>` : ''}
          </div>
          <div class="nq-refs">${refThumbs(c, { max: 3, cls: 'nc-ref sm' })}</div>
        </div>
        <p class="nq-why" title="${esc(why)}">${esc(c.n || '')} · ${c.parked ? 'PARKED' : 'PICKED'} · ${esc(why)}</p>
        <div class="nq-zone">${renderZone(c)}</div>
      </div>
    </article>`;
  }).join('')
    : '<div class="probeblank">Nothing waiting — a Studio run lands here once its keyframe is rendered, or pick a concept on Pipeline</div>';

  hydrateImages(list);

  repaintZone = (id, focus) => {
    const el = list.querySelector(`.nc[data-id="${id}"]`);
    const card = cards.get(id);
    if (!el || !card) return;
    el.querySelector('.nq-zone').innerHTML = renderZone(card);
    // the pill you pressed was just rebuilt: put the focus back on it
    const again = focus && [...el.querySelectorAll('.nq-pop [data-role]')].find(n =>
      n.dataset.role === focus.role && n.dataset.value === focus.value);
    if (again) again.focus();
  };

  function choose(id, role, value) {
    const pick = picks.get(id);
    if (!pick) return;
    if (role === 'model') {
      const [provider, model] = value.split('|');
      const spec = specOf(provider, model);
      // the new model's own defaults, never the old model's values --
      // 20s is legal on LTX and refused by Runway, and carrying it
      // across would put a number in the box the server will reject
      picks.set(id, { provider, model,
                      duration: spec.duration.default, frame: spec.frame.default });
    } else if (role === 'duration') {
      const axis = specOf(pick.provider, pick.model).duration;
      const seconds = Number(value);
      const legal = Number.isFinite(seconds) && (axis.kind === 'range'
        ? seconds >= axis.min && seconds <= axis.max
        : axis.values.map(Number).includes(seconds));
      // an out-of-range length keeps the last legal one, and the
      // repaint below puts that back in the box. The server REFUSES
      // rather than clamps (providers.check_render_choice), so a field
      // quietly disagreeing with what is about to be spent is the one
      // outcome worth ruling out here.
      if (legal) pick.duration = seconds;
    } else {
      pick.frame = value;
    }
    held.set(id, picks.get(id));
    repaintZone(id, { role, value });
  }

  /* Delegated, not per-button: changing the model redraws the zone (a
     different model has different legal durations and frames), which
     would drop handlers bound to the elements inside it. */
  list.querySelectorAll('.nc').forEach(el => {
    const id = Number(el.dataset.id);
    const card = cards.get(id);

    el.addEventListener('change', ev => {
      const control = ev.target.closest('input[data-role="duration"]');
      if (control) choose(id, 'duration', control.value);
    });

    el.addEventListener('input', ev => {
      // a number input fires `input` per keystroke; repaint the price
      // without rebuilding the controls under the cursor
      const control = ev.target.closest('input[data-role="duration"]');
      const pick = picks.get(id);
      if (!control || !pick) return;
      const button = el.querySelector('button[data-act="approve"]');
      // a vendor gate (no key) already disabled this button and typing
      // must not undo that -- .rblocked is the zone saying so, which is
      // why this is not a plain `button.disabled` check the keystroke
      // below would then flip back on
      if (!button || el.querySelector('.rblocked')) return;
      const spec = specOf(pick.provider, pick.model);
      const seconds = Number(control.value);
      const legal = control.value !== '' && Number.isFinite(seconds)
        && seconds >= spec.duration.min && seconds <= spec.duration.max;
      // the button goes dead while the box says something the model
      // cannot render, so the length shown and the length spent are
      // never two different numbers
      button.disabled = !legal;
      if (legal) { pick.duration = seconds; held.set(id, pick); }
      button.textContent = legal
        ? approveText(plan(card, spec, pick))
        : `${spec.id} renders ${spec.duration.min}-${spec.duration.max}s`;
    });

    el.addEventListener('click', async ev => {
      const btn = ev.target.closest('button');
      if (!btn || btn.disabled) return;
      if (btn.dataset.ref !== undefined) { previewRefs(card, Number(btn.dataset.ref), btn); return; }
      if (btn.dataset.still) { previewStills(card, btn.dataset.still, btn); return; }
      if (btn.dataset.role) { choose(id, btn.dataset.role, btn.dataset.value); return; }
      const act = btn.dataset.act;
      if (!act) return;
      if (act === 'key') { previewStills(card, card.reference_image, btn); return; }
      if (act === 'chip') { setPop(openPop === id ? null : id); return; }
      if (openPop === id) setPop(null);
      const tag = status => {
        const node = el.querySelector('[data-role="status"]');
        node.textContent = status;
        node.hidden = false;
      };
      btn.disabled = true;
      // the camera doesn't render or reject -- it just marks the card
      // as made by hand and drops it off the pending list
      if (act === 'shot' || act === 'reject') {
        const status = act === 'shot' ? 'SHOT BY HAND' : 'ARCHIVED';
        try {
          await api(`/api/queue/${id}/${act}`,
            { method: 'POST', body: act === 'shot' ? { shot: true } : {} });
          held.delete(id);
          acted.set(id, { status, at: Date.now() });
          // said on the card for a beat, then the rows are re-read and
          // it is gone -- a card that simply vanished read as a misclick
          tag(status);
          el.classList.add('acted');
          repaintZone(id);
          setTimeout(() => { acted.delete(id); renderPending(); }, 900);
          refreshQueueBadge();
        } catch (e) {
          btn.disabled = false;
          stateline($('pendstate'), 'error', e.message);
        }
        return;
      }
      const label = btn.textContent;
      btn.textContent = 'Rendering…';
      try {
        // the pick rides on the approve. An empty body still works and
        // resolves to the shot's planned tool -- see ApproveBody.
        const out = await api(`/api/queue/${id}/approve`,
          { method: 'POST', body: picks.get(id) || {} });
        held.delete(id);
        acted.set(id, { status: 'RENDERING', job: out && out.job_id, at: Date.now() });
        renderPending();
        refreshQueueBadge();
      } catch (e) {
        btn.disabled = false;
        btn.textContent = label;
        stateline($('pendstate'), 'error', e.message);
      }
    });
  });
}


/* ── the subscription lane ──
   One card per waiting shot, carrying the three things a human needs in
   front of the Runway web app: the gate-passed prompt to paste, the
   keyframe to drag into the start-image slot, and the duration/ratio to
   set (the app resets duration to 5s on every reload -- docs/RUNBOOK.md
   2026-09-06 -- which is why it is printed on every card). The drop
   target files what comes back. */

async function renderLane() {
  const list = $('lanelist');
  if (!list) return;              // not an operator: the section is not on the page
  let data;
  stateline($('lanestate'), 'loading', 'Loading…');
  try {
    data = await api('/api/queue/manual?brand=' + encodeURIComponent(state.brand));
  } catch (e) {
    list.innerHTML = '';
    stateline($('lanestate'), 'error', `Lane unavailable: ${e.message}`, renderLane);
    return;
  }
  stateline($('lanestate'), null);
  $('lanecount').textContent = `${data.items.length} to render`;

  const models = data.models || [];
  list.innerHTML = data.items.length ? data.items.map(c => {
    const opts = models.map(m =>
      `<option value="${esc(m.id)}"${m.id === data.default_model ? ' selected' : ''}>${esc(m.id)}</option>`).join('');
    return `
    <article class="glass scene" data-id="${c.concept_id}" data-shot="${c.shot_n}">
      <div class="schead">
        <h4>${esc(c.title)}</h4>
        <span class="m">shot ${esc(c.shot_n)}</span>
        <span class="spacer"></span>
        <span class="m">${esc(c.duration)}s · ${esc(c.ratio)}</span>
      </div>
      ${c.keyframe_url ? `
      <a href="${esc(c.keyframe_url)}" download title="Drag me into Runway's start-image slot">
        <img class="scshot" src="${esc(c.keyframe_url)}" alt="keyframe" draggable="true">
      </a>` : '<div class="probeblank">no keyframe — this one is text-to-video</div>'}
      <p class="scprompt">${esc(c.prompt)}</p>
      ${shotStrip(c)}
      <div class="scfoot">
        <button class="tag" data-act="copy">Copy prompt</button>
        <span class="m" data-role="note">${esc(c.lane)}</span>
      </div>
      <label class="lanedrop" data-role="drop">
        <input type="file" accept="video/mp4" hidden data-role="file">
        <span data-role="dropnote">Drop the finished mp4 here</span>
      </label>
      <div class="scfoot">
        <select class="tag" data-role="model">${opts}</select>
        <select class="tag" data-role="duration">
          ${[5, 10].map(d => `<option value="${d}"${d === c.duration ? ' selected' : ''}>${d}s</option>`).join('')}
        </select>
        <span class="m">as generated — a wrong number is refused, never rounded</span>
      </div>
    </article>`;
  }).join('')
    : '<div class="probeblank">Nothing waiting on the lane</div>';

  list.querySelectorAll('.scene').forEach(wireLaneCard);
}

function wireLaneCard(card) {
  const id = Number(card.dataset.id);
  const shotN = Number(card.dataset.shot);
  const note = card.querySelector('[data-role="note"]');
  const drop = card.querySelector('[data-role="drop"]');
  const file = card.querySelector('[data-role="file"]');
  const dropnote = card.querySelector('[data-role="dropnote"]');

  card.querySelector('[data-act="copy"]').onclick = async () => {
    const text = card.querySelector('.scprompt').textContent;
    try {
      await navigator.clipboard.writeText(text);
      note.textContent = 'prompt copied — paste it into Runway';
    } catch {
      // clipboard is permissioned; selecting the prompt is the fallback
      // that always works
      const range = document.createRange();
      range.selectNodeContents(card.querySelector('.scprompt'));
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      note.textContent = 'selected — copy it with ⌘C';
    }
  };

  // A drop is a gesture, and gestures repeat -- a browser can fire twice
  // and a hand drops again when the card has not visibly changed. The
  // route refuses the second one with a 409, but that refusal arrives
  // while the FIRST drop's success is already re-rendering the lane,
  // and the re-render clears #lanestate: the honest answer was being
  // raced off the page, so a repeat drop looked exactly like nothing
  // happening. Holding the card while its own upload is in flight means
  // the repeat never becomes a second request in the first place.
  let filing = false;

  const send = async f => {
    if (!f) return;
    if (filing) {
      dropnote.textContent = 'still filing the last drop — wait for it';
      return;
    }
    filing = true;
    const body = new FormData();
    body.append('file', f);
    body.append('shot_n', String(shotN));
    body.append('model', card.querySelector('[data-role="model"]').value);
    body.append('duration', card.querySelector('[data-role="duration"]').value);
    // the keyframe IS the start image on this lane when there is one
    body.append('anchored', card.querySelector('.scshot') ? '1' : '0');
    drop.classList.remove('over', 'bad');
    dropnote.textContent = 'Filing…';
    try {
      await api(`/api/queue/manual/${id}/clip`, { method: 'POST', body });
      // it has a clip now, so it leaves both lists at once
      renderLane();
      renderPending();
    } catch (e) {
      // ON THE CARD, not only in the section's stateline. The drop
      // target is per-shot, so a refusal printed above the grid does
      // not say WHICH shot was refused -- and resetting the note to its
      // neutral prompt reads as though the drop never landed. The
      // stateline still echoes it, because that is where every other
      // failure on this page is announced.
      drop.classList.add('bad');
      dropnote.textContent = e.message;
      stateline($('lanestate'), 'error', e.message);
    } finally {
      filing = false;
    }
  };

  // No click handler: the file input lives INSIDE this label, so the
  // label already forwards a click to it. Calling file.click() as well
  // activated the input twice and opened the picker twice -- a second
  // dialog waiting behind the one you just used.
  file.onchange = () => { send(file.files[0]); file.value = ''; };
  ['dragenter', 'dragover'].forEach(evt => drop.addEventListener(evt, e => {
    e.preventDefault();
    drop.classList.add('over');
  }));
  ['dragleave', 'dragend'].forEach(evt => drop.addEventListener(evt, () =>
    drop.classList.remove('over')));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    send(e.dataTransfer.files[0]);
  });
}

/* ── the job registry ── */

async function renderJobs() {
  const qstate = $('qstate');
  try {
    const data = await api('/api/jobs');
    state.jobs.clear();
    data.items.forEach(j => state.jobs.set(j.id, j));
    stateline(qstate, null);
  } catch (e) {
    stateline(qstate, 'error', `Jobs unavailable: ${e.message}`, renderJobs);
    return;
  }
  paint();
}

function paint() {
  const items = [...state.jobs.values()].sort((a, b) => b.id - a.id);
  const running = items.filter(j => ['queued', 'running'].includes(j.status)).length;
  $('qcount').textContent = `${running} running · ${items.length} total`;
  const box = $('qlist');
  if (!items.length) {
    box.innerHTML = '<div class="probeblank" style="padding-left:0">Nothing queued — jobs appear here when you create, approve, or run an eval. The queue clears on restart.</div>';
    return;
  }
  box.innerHTML = items.map(j => {
    const active = ['queued', 'running'].includes(j.status);
    const dot = j.status === 'failed' ? 'run' : active ? 'run' : 'ok';
    const action = active
      ? (j.cancellable ? `<button class="qx" data-a="cancel" data-id="${j.id}">Cancel</button>` : '<span class="m">running</span>')
      : `<button class="qx" data-a="clear" data-id="${j.id}">Clear</button>`;
    return `<div class="qrow">
      <span class="dot ${dot}"></span>
      <div>
        <div class="qn">${esc(j.label)}</div>
        <div class="qm">${esc(j.kind)} · ${esc(j.status)}${j.detail ? ' · ' + esc(j.detail) : ''}${j.error ? ' · ' + esc(j.error) : ''}</div>
      </div>
      <div class="qbar"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>
      <span class="qt">${esc(j.status)}</span>
      ${action}
    </div>`;
  }).join('');
  box.querySelectorAll('.qx').forEach(b => b.onclick = async () => {
    try {
      if (b.dataset.a === 'cancel') {
        await api(`/api/jobs/${b.dataset.id}/cancel`, { method: 'POST', body: {} });
      } else {
        await api(`/api/jobs/${b.dataset.id}`, { method: 'DELETE' });
        state.jobs.delete(+b.dataset.id);
      }
      paint();
    } catch (e) {
      stateline($('qstate'), 'error', e.message, renderJobs);
    }
  });
}

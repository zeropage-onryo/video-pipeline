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

  /* A TIMED SCENE'S PRICE IS THE SERVER'S (src/pricing.py, 2026-09-17).
     Each shot renders at its own window's length fitted UP to what the
     model can make, and that fitting used to be done twice -- here, as a
     JS twin of timeline.fit_seconds, and again on approve. Two
     implementations of a price is how a person is shown one number and
     charged another, so the twin is gone: the listing carries
     pricing.display for the card's default pick (`card.quote`), and a
     pick that differs asks GET /api/queue/{id}/quote once and repaints.
     Until that answers the button names the shots without a number,
     which is honest; it never shows arithmetic of its own. */
  const quotes = new Map();
  const quoteKey = (card, pick) => `${card.id}|${pick.provider}|${pick.model}|${pick.frame}`
    + (card.timeline ? '' : `|${pick.duration}`);
  const matches = (q, pick, timed = true) => !!q && !q.error && q.timed === timed
    && q.provider === pick.provider && q.model === pick.model && q.frame === pick.frame
    && (timed || q.durations[0] === Number(pick.duration));
  const pickQuery = (card, pick) => new URLSearchParams(card.timeline
    ? { provider: pick.provider, model: pick.model, frame: pick.frame }
    : { provider: pick.provider, model: pick.model, frame: pick.frame, duration: pick.duration });

  /* THE QUOTE THE APPROVE ECHOES. The server signs one token per shot
     into the price it shows (pricing.sign, when QUOTE_SIGNING_SECRET is
     set); approving sends them back and the route refuses if the scene
     or the pick moved since. A pick the listing did not price is asked
     of /quote on the click, so the tokens always describe THIS pick --
     never a stale set from the card's default. */
  async function quoteFor(card, pick) {
    const timed = !!card.timeline;
    if (matches(card.quote, pick, timed)) return card.quote;
    const key = quoteKey(card, pick);
    const cached = quotes.get(key);
    if (cached && !cached.error) return cached;
    const q = await api(`/api/queue/${card.id}/quote?${pickQuery(card, pick)}`);
    quotes.set(key, q);
    return q;
  }

  function timedQuote(card, pick) {
    if (matches(card.quote, pick)) return card.quote;
    const key = quoteKey(card, pick);
    if (quotes.has(key)) return quotes.get(key);
    quotes.set(key, null);                       // in flight: ask once
    api(`/api/queue/${card.id}/quote?${pickQuery(card, pick)}`)
      .then(q => quotes.set(key, q), e => quotes.set(key, { error: e.message }))
      .then(() => {
        const now = picks.get(card.id);
        const zone = list.querySelector(`.scene[data-id="${card.id}"] .rzone`);
        // only if the person is still on this pick -- a slow answer must
        // not repaint the zone back onto a model they have moved off
        if (zone && now && quoteKey(card, now) === key) zone.innerHTML = renderZone(card);
      });
    return null;
  }

  function shotsToRender(card) {
    const tl = card.timeline;
    return tl ? (tl.parts || []).filter(p => !p.media_url) : null;
  }

  function axisControl(role, axis, value, label) {
    if (axis.kind === 'range') {
      // a real span, so 7s on a model that renders 1-20s is a real
      // request rather than a value rounded to the nearest chip
      // the unit is spelled out beside a free number box: a select can
      // print "5s" in the option, a spinner cannot, and "5" alone next
      // to a resolution reads as anything
      return `<span class="rspan"><input class="rctl" type="number" data-role="${role}"
                min="${axis.min}" max="${axis.max}" step="1" value="${esc(value)}"
                title="${esc(label)}: ${axis.min}-${axis.max}s"><span class="m">sec</span></span>`;
    }
    const opts = axis.values.map(v =>
      `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}>${esc(v)}${role === 'duration' ? 's' : ''}</option>`).join('');
    // "fixed" is an admission, not an option: the note says whether this
    // vendor offers one value or whether nobody here has verified the list
    return `<select class="rctl" data-role="${role}"${axis.kind === 'fixed' ? ' disabled' : ''}
              title="${esc(axis.kind === 'fixed' && axis.note ? axis.note : label)}">${opts}</select>`;
  }

  function modelSelect(pick) {
    return `<select class="rctl rmodel" data-role="model" aria-label="Renderer and model">`
      + order.map(name => {
        const r = renderers[name];
        const opts = (r.models || []).map(m => {
          const sel = (pick.provider === name && pick.model === m.id) ? ' selected' : '';
          const off = m.available ? '' : ' disabled';
          const why = m.available ? '' : ' — not on this account';
          return `<option value="${esc(name)}|${esc(m.id)}"${off}${sel}>${esc(m.label)}${why}</option>`;
        }).join('');
        return opts ? `<optgroup label="${esc(r.label)}${r.available ? '' : ' (no key)'}">${opts}</optgroup>` : '';
      }).join('') + `</select>`;
  }

  function renderZone(card) {
    const pick = pickFor(card);
    if (!pick) return '<span class="m">no renderer is configured — approving cannot render</span>';
    const r = renderers[pick.provider];
    const spec = specOf(pick.provider, pick.model);
    // one reason left, and it is the only one a restart could ever have
    // fixed: no key for this vendor
    const blocked = r.available ? '' : `${r.label} key not set`;
    const todo = shotsToRender(card);
    if (todo) {
      // no duration control: every shot's length is its window's
      const q = timedQuote(card, pick);
      const what = `${todo.length} shot${todo.length === 1 ? '' : 's'}`;
      const refused = q && q.error ? q.error : '';
      const lengths = q && !q.error ? `${q.durations.join(' + ')}s` : (refused ? '' : 'pricing…');
      const price = q && !q.error ? ` ~$${Number(q.estimate_usd).toFixed(2)}` : '';
      const off = blocked || refused;
      return `
      ${modelSelect(pick)}
      <span class="m" title="each shot renders at its own window's length, fitted up to what ${esc(spec.id)} can make">${esc(what)}${lengths ? ' · ' + esc(lengths) : ''}</span>
      ${axisControl('frame', spec.frame, pick.frame, r.frame_axis)}
      <button class="go" data-act="approve"${off ? ' disabled' : ''}>
        ${blocked ? 'Approve · render' : `Approve · render ${esc(what)}${price}`}
      </button>
      ${off ? `<span class="m rblocked">${esc(blocked || refused)}</span>` : ''}`;
    }
    const usd = estimate(spec, pick);
    return `
      ${modelSelect(pick)}
      ${axisControl('duration', spec.duration, pick.duration, 'duration')}
      ${axisControl('frame', spec.frame, pick.frame, r.frame_axis)}
      <button class="go" data-act="approve"${blocked ? ' disabled' : ''}>
        ${blocked ? 'Approve · render' : `Approve · render ~$${(usd === null ? 0 : usd).toFixed(2)}`}
      </button>
      ${blocked ? `<span class="m rblocked">${esc(blocked)}</span>` : ''}`;
  }

  /* The shots a timed scene renders as, in order: window, its still (the
     frame that shot's clip anchors on), its own refs, and a tick once its
     clip is back. An unplanned timeline shows the bare windows -- the
     approve plans them before the first clip. */
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

  $('pendcount').textContent = `${data.items.length} waiting`;

  list.innerHTML = data.items.length ? data.items.map(c => {
    const refs = (c.refs || []).map(url =>
      `<span class="scref" style="background-image:url('${esc(url)}')"></span>`).join('');
    return `
    <article class="glass scene on" data-id="${c.id}">
      <div class="screfs">
        ${refs || '<span class="m">no references</span>'}
        <span class="spacer"></span>
        <span class="m">${esc(c.spark || '')}</span>
      </div>
      <div class="schead">
        <h4>${esc(c.title)}</h4>
        <span class="m">${esc(c.n || '')}</span>
        <span class="spacer"></span>
        <span class="m">${c.parked ? 'READY · AWAITING APPROVAL' : 'PICKED'}</span>
      </div>
      ${c.summary ? `<p class="scsum" title="${esc(c.summary)}">${esc(c.summary)}</p>` : ''}
      ${c.reference_image
        ? `<img class="scshot" src="${esc(c.reference_image)}" alt="">` : ''}
      <p class="scprompt">${esc(c.prompt)}</p>
      ${shotStrip(c)}
      <div class="scfoot">
        <button class="swipe shot" data-act="shot" title="Shot it yourself"
                aria-label="Mark shot -- you made this outside the render pipeline">📷</button>
        <button class="tag" data-act="reject">Reject</button>
        <span class="m">${c.reference_image
          ? 'anchors on the keyframe above'
          : esc(c.park_reason || 'text-to-video · no reference attached')}</span>
        <span class="spacer"></span>
        <span class="rzone">${renderZone(c)}</span>
      </div>
    </article>`;
  }).join('')
    : '<div class="probeblank">Nothing waiting — a Studio run lands here once its keyframe is rendered, or pick a concept on Pipeline</div>';

  /* Delegated, not per-button: changing the model redraws the zone (a
     different model has different legal durations and frames), which
     would drop handlers bound to the elements inside it. */
  list.querySelectorAll('.scene').forEach(el => {
    const id = Number(el.dataset.id);
    const card = cards.get(id);
    const zone = () => el.querySelector('.rzone');

    el.addEventListener('change', ev => {
      const control = ev.target.closest('[data-role]');
      if (!control) return;
      const pick = picks.get(id);
      if (!pick) return;
      if (control.dataset.role === 'model') {
        const [provider, model] = control.value.split('|');
        const spec = specOf(provider, model);
        // the new model's own defaults, never the old model's values --
        // 20s is legal on LTX and refused by Runway, and carrying it
        // across would put a number in the box the server will reject
        picks.set(id, { provider, model,
                        duration: spec.duration.default, frame: spec.frame.default });
      } else if (control.dataset.role === 'duration') {
        const axis = specOf(pick.provider, pick.model).duration;
        const seconds = Number(control.value);
        const legal = Number.isFinite(seconds) && (axis.kind === 'range'
          ? seconds >= axis.min && seconds <= axis.max
          : axis.values.includes(seconds));
        // an out-of-range length keeps the last legal one, and the
        // repaint below puts that back in the box. The server REFUSES
        // rather than clamps (providers.check_render_choice), so a field
        // quietly disagreeing with what is about to be spent is the one
        // outcome worth ruling out here.
        if (legal) pick.duration = seconds;
      } else {
        pick.frame = control.value;
      }
      held.set(id, picks.get(id));
      zone().innerHTML = renderZone(card);
    });

    el.addEventListener('input', ev => {
      // a number input fires `input` per keystroke; repaint the price
      // without rebuilding the controls under the cursor
      const control = ev.target.closest('input[data-role="duration"]');
      const pick = picks.get(id);
      if (!control || !pick) return;
      const button = el.querySelector('button[data-act="approve"]');
      // a vendor gate (no key, spend approval off) already disabled this
      // button and typing must not undo that -- .rblocked is the zone
      // saying so, which is why this is not a plain `button.disabled`
      // check the keystroke below would then flip back on
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
      const usd = estimate(spec, pick);
      button.textContent = legal
        ? `Approve · render ~$${(usd === null ? 0 : usd).toFixed(2)}`
        : `${spec.id} renders ${spec.duration.min}-${spec.duration.max}s`;
    });

    el.addEventListener('click', async ev => {
      const btn = ev.target.closest('[data-act]');
      if (!btn || btn.disabled) return;
      const act = btn.dataset.act;
      btn.disabled = true;
      // the camera doesn't render or reject -- it just marks the card
      // as made by hand and drops it off the pending list, so its label
      // never needs a "…" render state the other two do
      if (act === 'shot') {
        try {
          await api(`/api/queue/${id}/shot`, { method: 'POST', body: { shot: true } });
          renderPending();
          refreshQueueBadge();
        } catch (e) {
          btn.disabled = false;
          stateline($('pendstate'), 'error', e.message);
        }
        return;
      }
      const approve = act === 'approve';
      const label = btn.textContent;
      btn.textContent = approve ? 'Rendering…' : '…';
      try {
        // the pick rides on the approve, with the signed quotes for it
        // (quoteFor). An empty body still works and resolves to the
        // shot's planned tool -- see ApproveBody.
        let body = {};
        if (approve) {
          const pick = picks.get(id) || {};
          const q = await quoteFor(card, pick);
          const tokens = ((q && q.renders) || []).map(r => r.token).filter(Boolean);
          body = tokens.length ? { ...pick, tokens } : pick;
        }
        await api(`/api/queue/${id}/${approve ? 'approve' : 'reject'}`,
          { method: 'POST', body });
        held.delete(id);
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

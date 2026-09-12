/* The LTX-shaped composer chrome, and the rail that opens on hover.
   2026-09-10, Mike's call: "make it similar to LTX, keep a send button
   like Runway's".

   THE RULE THIS MODULE FOLLOWS: it restyles and rearranges, it does not
   rewire. #guidesend and #go keep their own handlers in
   creative-guide.js / studio.js; the mode pill decides which of the two
   the round send button clicks, and the selects that feed
   collectRunForm (#cbrain, #cseconds, #ccount) are MOVED into the
   control row rather than replaced -- same ids, same values, same
   readers. A composer that looked right and posted differently would be
   the worst possible version of this change. */

const $ = id => document.getElementById(id);
const store = {
  get(k, fallback) { try { return localStorage.getItem(k) ?? fallback; } catch { return fallback; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window: the pin just forgets */ } },
};

/* ── the rail ──────────────────────────────────────────────────────
   Hover is pure CSS (width + opacity) so it stays smooth and works
   before this module loads. The only thing JS owns is the pin, which
   has to survive a reload or it is a toggle nobody uses twice. */
function initRail() {
  const rail = $('rail'), pin = $('railpin');
  if (!rail || !pin) return;
  const apply = on => {
    rail.toggleAttribute('data-pinned', on);
    pin.setAttribute('aria-pressed', String(on));
    pin.title = on ? 'Let the rail collapse' : 'Keep the rail open';
  };
  apply(store.get('zpf.rail.pinned', '0') === '1');
  pin.addEventListener('click', () => {
    const on = !rail.hasAttribute('data-pinned');
    apply(on);
    store.set('zpf.rail.pinned', on ? '1' : '0');
  });
}

/* ── one popover implementation, used by the mode and model pills ── */
function popover(anchor, build) {
  const pop = document.createElement('div');
  pop.className = 'pop';
  pop.hidden = true;
  document.body.appendChild(pop);

  const place = () => {
    const r = anchor.getBoundingClientRect();
    pop.style.visibility = 'hidden';
    pop.hidden = false;
    const h = pop.offsetHeight, w = pop.offsetWidth;
    // above the pill when there is room, below when there is not --
    // this row sits near the bottom of the viewport most of the time.
    const top = r.top - h - 10 > 8 ? r.top - h - 10 : r.bottom + 10;
    pop.style.top = `${Math.round(top + window.scrollY)}px`;
    pop.style.left = `${Math.round(Math.min(r.left, window.innerWidth - w - 12) + window.scrollX)}px`;
    pop.style.visibility = '';
  };
  const close = () => {
    pop.hidden = true;
    anchor.setAttribute('aria-expanded', 'false');
  };
  const open = () => {
    pop.innerHTML = '';
    build(pop, close);
    place();
    anchor.setAttribute('aria-expanded', 'true');
  };
  anchor.addEventListener('click', e => {
    e.stopPropagation();
    pop.hidden ? open() : close();
  });
  document.addEventListener('click', e => {
    if (!pop.hidden && !pop.contains(e.target)) close();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  window.addEventListener('resize', () => { if (!pop.hidden) place(); });
  return { close };
}

function icon(d, cls = '') {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
}
const CHECK = 'm5 13 4 4L19 7';

/* ── the mode switch: what does the round button do ───────────────── */
const MODES = [
  { id: 'guide', label: 'Guide', note: 'Talk the idea through first. Send goes to your creative partner.',
    d: 'M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z' },
  { id: 'create', label: 'Create', note: 'Skip the conversation and write scenes from what is in the box.',
    d: 'M5 3v18l14-9z' },
];

function initMode(sync) {
  const box = $('cbox'), pill = $('modepill'), label = $('modelabel');
  if (!box || !pill) return;
  const set = id => {
    box.dataset.mode = id;
    const m = MODES.find(x => x.id === id) || MODES[0];
    label.textContent = m.label;
    pill.querySelector('svg:not(.chev)').innerHTML = `<path d="${m.d}"/>`;
    store.set('zpf.composer.mode', id);
    sync();
  };
  popover(pill, (pop, close) => {
    pop.innerHTML = `<div class="popgroup">Send does</div>` + MODES.map(m => `
      <button type="button" class="popitem" data-id="${m.id}"
              aria-selected="${box.dataset.mode === m.id}">
        <span class="popicon">${icon(m.d)}</span>
        <span class="popbody">
          <span class="popname">${m.label}</span>
          <span class="popnote">${m.note}</span>
        </span>
        <span class="popcheck">${icon(CHECK)}</span>
      </button>`).join('');
    pop.querySelectorAll('.popitem').forEach(b =>
      b.addEventListener('click', () => { set(b.dataset.id); close(); }));
  });
  set(store.get('zpf.composer.mode', 'guide'));
}

/* ── the model pill, over the #cbrain select that already exists ───
   The select stays in the DOM (hidden) because collectRunForm reads
   its .value -- the pill is a skin on a real control, not a second
   source of truth. Rows come from /api/brains, which is a projection
   of gemini_utils.BRAINS. */
const BRAIN_ICON = 'M12 4a4 4 0 0 0-4 4 3 3 0 0 0-1 5.8V17a3 3 0 0 0 5 2.2A3 3 0 0 0 17 17v-3.2A3 3 0 0 0 16 8a4 4 0 0 0-4-4z';

async function initBrainPill(api) {
  const pill = $('brainpill'), label = $('brainlabel'), select = $('cbrain');
  if (!pill || !select) return;
  let brains = [];
  try {
    brains = (await api('/api/brains')).brains || [];
  } catch {
    // the pill is useless without the menu, and a control that cannot
    // say what it would do is worse than no control
    pill.hidden = true;
    return;
  }
  select.hidden = true;
  if (!select.options.length) {
    select.innerHTML = brains.map(b =>
      `<option value="${b.id}"${b.default ? ' selected' : ''}>${b.label}</option>`).join('');
  }
  const reflect = () => {
    const b = brains.find(x => x.id === select.value) || brains[0];
    if (b) label.textContent = b.label;
    pill.classList.toggle('accent', !!b && !b.default);
  };
  popover(pill, (pop, close) => {
    pop.innerHTML = `<div class="popgroup">Which model writes</div>` + brains.map(b => `
      <button type="button" class="popitem" data-id="${b.id}"
              aria-selected="${select.value === b.id}">
        <span class="popicon">${icon(BRAIN_ICON)}</span>
        <span class="popbody">
          <span class="popname">${b.label}${b.default ? '' : '<i class="popbadge hot">slower</i>'}</span>
          <span class="popnote">${b.note || ''}</span>
        </span>
        <span class="popcheck">${icon(CHECK)}</span>
      </button>`).join('');
    pop.querySelectorAll('.popitem').forEach(b => b.addEventListener('click', () => {
      select.value = b.dataset.id;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      reflect();
      close();
    }));
  });
  reflect();
}

/* ── the render row ────────────────────────────────────────────────
   #cseconds and #ccount already exist and already post; they are moved
   here and re-skinned, not recreated.

   Ratio and resolution are the two LTX pills this pipeline has no
   composer-side endpoint for yet: the legal sets live in
   src/render_specs.py and reach the client only through the Queue's
   own renderer state. They are posted as `ratio` / `resolution` so the
   choice rides with the run, and FastAPI ignores a form field nobody
   reads -- so this is inert until /api/scenes/run reads them and
   stores them as the Queue card's default. WHEN THAT LANDS, these two
   lists must come from a projection route the way /api/brains does;
   a hardcoded list here is exactly the copy that goes stale. */
const RATIOS = [
  { id: '720:1280', label: '9:16', note: 'Vertical — Reels, Shorts, TikTok' },
  { id: '1280:720', label: '16:9', note: 'Landscape' },
  { id: '960:960', label: '1:1', note: 'Square' },
];
const RESOLUTIONS = [
  { id: '720p', label: '720p', note: 'Cheaper per second' },
  { id: '1080p', label: '1080p', note: 'What the render lanes bill at full rate' },
];

function choicePill(id, iconPath, options, initial, title) {
  const wrap = $('ltxrender');
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'pill';
  btn.id = `${id}pill`;
  btn.title = title;
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-haspopup', 'listbox');
  const hidden = document.createElement('input');
  hidden.type = 'hidden';
  hidden.id = id;
  hidden.name = id;
  hidden.value = initial;
  const paint = () => {
    const o = options.find(x => x.id === hidden.value) || options[0];
    btn.innerHTML = `${icon(iconPath)}<span class="plabel">${o.label}</span>` +
      `<svg class="chev" viewBox="0 0 24 24" stroke-linecap="round"><path d="m6 9 6 6 6-6"/></svg>`;
  };
  wrap.append(btn, hidden);
  paint();
  popover(btn, (pop, close) => {
    pop.innerHTML = `<div class="popgroup">${title}</div>` + options.map(o => `
      <button type="button" class="popitem" data-id="${o.id}"
              aria-selected="${hidden.value === o.id}">
        <span class="popicon">${icon(iconPath)}</span>
        <span class="popbody"><span class="popname">${o.label}</span>
        <span class="popnote">${o.note}</span></span>
        <span class="popcheck">${icon(CHECK)}</span>
      </button>`).join('');
    pop.querySelectorAll('.popitem').forEach(b => b.addEventListener('click', () => {
      hidden.value = b.dataset.id; paint(); close();
    }));
  });
}

function initRenderRow() {
  const wrap = $('ltxrender');
  if (!wrap) return;
  // move, never rebuild: #cseconds is already wired to /api/scene-lengths.
  // There is deliberately no concept-count pill -- one Create writes ONE
  // scene (2026-09-10, Mike's call; api.SCENE_COUNT_MAX).
  ['cseconds'].forEach(id => { const el = $(id); if (el) wrap.appendChild(el); });
  choicePill('ratio', 'M3 6h18v12H3z', RATIOS, store.get('zpf.ratio', '720:1280'), 'Aspect ratio');
  choicePill('resolution', 'M4 4h7v7H4zM13 13h7v7h-7z', RESOLUTIONS, store.get('zpf.resolution', '720p'), 'Resolution');
  ['ratio', 'resolution'].forEach(id => {
    const el = $(id);
    if (el) new MutationObserver(() => store.set(`zpf.${id}`, el.value))
      .observe(el, { attributes: true, attributeFilter: ['value'] });
  });
}

/* ── the send button ───────────────────────────────────────────────
   One button, two destinations, and it MIRRORS the real one's disabled
   state rather than deciding for itself -- creative-guide.js owns when
   "Create scenes" is allowed, and a send button that lights up when the
   thing behind it is refusing is a lie. */
function initSend() {
  const box = $('cbox'), send = $('send'), prompt = $('prompt');
  if (!send || !box) return;
  const target = () => $(box.dataset.mode === 'create' ? 'go' : 'guidesend');
  const sync = () => {
    const t = target();
    const typed = !!(prompt && prompt.value.trim());
    send.disabled = box.dataset.mode === 'create' ? !!(t && t.disabled) : !typed;
    send.setAttribute('aria-label',
      box.dataset.mode === 'create' ? 'Create scenes' : 'Send to your creative partner');
  };
  send.addEventListener('click', () => {
    const t = target();
    if (t && !t.disabled) t.click();
  });
  if (prompt) prompt.addEventListener('input', sync);
  const go = $('go');
  if (go) new MutationObserver(sync).observe(go, { attributes: true, attributeFilter: ['disabled'] });
  sync();
  return sync;
}

/* the guide's settings disclosure: everything it holds is real and
   already wired, it just does not belong on screen before anyone has
   typed a word. */
function initGear() {
  const gear = $('guidegear'), panel = $('guidesettings');
  if (!gear || !panel) return;
  gear.addEventListener('click', () => {
    const open = panel.hidden;
    panel.hidden = !open;
    gear.setAttribute('aria-expanded', String(open));
  });
}

/* the two slot buttons are affordances over controls that exist */
function initSlots() {
  const up = $('up'), ref = $('slotref'), asset = $('slotasset'), prompt = $('prompt');
  if (ref && up) ref.addEventListener('click', () => up.click());
  if (asset && prompt) asset.addEventListener('click', () => {
    prompt.focus();
    // '@' is what wireMentions listens for -- typing it for the person
    // is the whole affordance
    prompt.setRangeText('@', prompt.selectionStart, prompt.selectionEnd, 'end');
    prompt.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

export function initComposerChrome(api) {
  initRail();
  const sync = initSend() || (() => {});
  initMode(sync);
  initRenderRow();
  initSlots();
  initGear();
  initBrainPill(api);
}

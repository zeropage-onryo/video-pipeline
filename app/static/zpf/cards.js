/* What the Pipeline card and the Queue card share (2026-09-17): the
   image-first top, the tags laid over it, the reference thumbnails and
   the readiness dot. One row in the database is one card in the product,
   so the two boards must not grow two ideas of what its picture is.

   Everything here is DISPLAY over the payload app/api.py's _concept_card
   already sends. Nothing below decides anything: the reference gate, the
   spend gate and the pick are the server's. */
import { esc } from './shared.js';
import { imgTag, openPreview, refItem } from './preview.js';

export const ICON = {
  check: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5L20 7"/></svg>',
  archive: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/></svg>',
  restore: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M4 4v5h5"/></svg>',
  nodes: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="7" height="6" rx="1"/><rect x="14" y="14" width="7" height="6" rx="1"/><path d="M10 7h3a2 2 0 0 1 2 2v5"/></svg>',
  x: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  camera: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  caret: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>',
};

export const brandName = b => String(b || '').replace(/zeropage/i, 'ZERO PAGE').toUpperCase();

/* the timed shots, or [] for a scene that renders whole */
export const partsOf = c => (c.timeline && c.timeline.parts) || [];

export const windowLabel = p => `${p.start}–${p.end}s`;

/* "3 SHOTS · 12S". A scene with no windows is one shot, and its length
   is not on the card payload, so none is claimed. */
export function shotsLabel(c) {
  const parts = partsOf(c);
  if (!parts.length) return '1 SHOT';
  const total = c.timeline.seconds ?? parts[parts.length - 1].end;
  return `${parts.length} SHOT${parts.length === 1 ? '' : 'S'} · ${total}S`;
}

/* READY / CHECK / BLOCKED.

   BLOCKED is the reference gate's own fact (no refs,
   preprod.reference_gate) and outranks everything: nothing renders
   without photographs, whatever a judge thought of the writing.

   Then THE PROMPT GATE'S VERDICT, when the concept has one. `c.gate` is
   autonomy.gates_for_concepts on the card payload since 2026-09-17:
   {score, passed, reason, reworks, status, outcome}, the same reading the
   MCP `idea` tool makes. A pass with no warnings is READY; a fail is CHECK,
   never BLOCKED -- the gates are advisory (2026-09-07), the run parked
   anyway, and a judge that agreed with the grade 38% of the time gets to
   raise a flag, not close a door.

   `c.gate` null means NO GRAPH RUN EVER SCORED THIS (a Studio Create stops
   on the board unscored). That is said as such -- "never scored" -- and
   the dot falls back to what the card does carry: validate_concept's
   warnings. It must not read as a pass. */
export function gateOf(c) {
  const refs = c.refs || [];
  if (!refs.length) {
    return { level: 'fail', short: 'BLOCKED', long: 'Blocked · no reference images' };
  }
  const warnings = c.warnings || [];
  const flagged = warnings.length
    ? ` · ${warnings.length} warning${warnings.length === 1 ? '' : 's'} on file` : '';
  const g = c.gate;
  if (g && g.score !== null && g.score !== undefined) {
    const reworked = g.reworks ? ` · after ${g.reworks} rework${g.reworks === 1 ? '' : 's'}` : '';
    if (g.passed && !warnings.length) {
      return { level: 'pass', short: 'READY', score: g.score,
               long: `Prompt gate ${g.score}/10 · passed${reworked}` };
    }
    return { level: 'warn', short: 'CHECK', score: g.score,
             long: g.passed
               ? `Prompt gate ${g.score}/10 · passed${reworked}${flagged}`
               : `Prompt gate ${g.score}/10 · ${g.reason || 'did not pass'}${reworked}${flagged}` };
  }
  // a run that ended before the gate scored anything says why it ended
  const unscored = g ? `Not scored · ${g.outcome || 'the run ended before the prompt gate'}`
    : 'Never scored · written by Create, which stops on the board';
  if (warnings.length) return { level: 'warn', short: 'CHECK', long: `${unscored}${flagged}` };
  return { level: 'pass', short: 'READY', long: `${unscored} · references attached` };
}

/* The card's picture: the keyframe if one was drawn, else the first
   reference, else the red slate. `kind` says which, for the label. */
export function heroOf(c) {
  const refs = c.refs || [];
  if (c.reference_image) return { kind: 'keyframe', url: c.reference_image };
  if (refs.length) return { kind: 'ref', url: refs[0] };
  return { kind: 'none', url: '' };
}

export function heroMarkup(c) {
  const hero = heroOf(c);
  if (hero.kind === 'none') {
    return `<span class="nc-slate"><span>NO REFERENCE</span><small>cannot render yet</small></span>`;
  }
  return imgTag(hero.url, {
    thumb: hero.kind === 'ref', cls: 'nc-heroimg',
    dead: hero.kind === 'keyframe' ? 'KEYFRAME UNAVAILABLE' : 'REFERENCE UNAVAILABLE',
  }) + (hero.kind === 'ref' ? '<span class="nc-tag bl2">REF 1 · NO KEYFRAME YET</span>' : '');
}

/* Up to `max` thumbnails, then one "+N" tile that opens the preview at
   the first hidden one. Each is a real button carrying its index. */
export function refThumbs(c, { max = 4, cls = 'nc-ref' } = {}) {
  const refs = c.refs || [];
  const shown = refs.slice(0, max).map((url, i) => `
    <button type="button" class="${cls}" data-ref="${i}"
            aria-label="Preview reference ${i + 1} of ${refs.length}: ${esc(refItem(url).name)}">
      ${imgTag(url, { thumb: true, dead: 'N/A' })}<span class="nc-num">${i + 1}</span>
    </button>`).join('');
  const more = refs.length > max
    ? `<button type="button" class="${cls} more" data-ref="${max}"
               aria-label="Preview ${refs.length - max} more references">+${refs.length - max}</button>`
    : '';
  return shown + more;
}

export function previewRefs(c, index, trigger) {
  openPreview({ title: c.title, kind: 'REFERENCE', index, trigger,
                items: (c.refs || []).map(url => ({ url })) });
}

/* the stills: the scene's keyframe, then each timed shot's own. Shot 1's
   still IS the scene's keyframe, so it is not listed twice. */
export function stillsOf(c) {
  const urls = [];
  if (c.reference_image) urls.push(c.reference_image);
  partsOf(c).forEach(p => {
    if (p.reference_image && !urls.includes(p.reference_image)) urls.push(p.reference_image);
  });
  return urls;
}

export function previewStills(c, url, trigger) {
  const stills = stillsOf(c);
  if (!stills.length) { if ((c.refs || []).length) previewRefs(c, 0, trigger); return; }
  openPreview({ title: c.title, kind: 'KEYFRAME', trigger,
                index: Math.max(0, stills.indexOf(url)),
                items: stills.map(u => ({ url: u })) });
}

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  planOf, nextStep, finished, phase, needsApproval, blockedBy, skipStep, editStep, restoreStep,
  approveStep, approveAll, picturesFor, priceOf, ahead, progress, stepTitle, stepText, patchStep,
  reconcile, editable, isPaid, stepAt,
} from '../src/lib/make-plan.ts';

const ARGS = {
  summary: 'A 10s ad for the can',
  steps: [
    { n: 1, do: 'image', args: { prompt: 'the exact can on wet steel', aspect: '4:5' }, why: 'the hero frame', uses: [] },
    { n: 2, do: 'scene', args: { prompt: 'she lifts the can', seconds: 10, shots: 3 }, why: 'the ad', uses: [1] },
    { n: 3, do: 'keyframes', args: {}, why: 'first frames', uses: [], scene: 2 },
    { n: 4, do: 'queue', args: {}, why: 'ready to render', uses: [], scene: 2 },
  ],
};
const plan = () => planOf(ARGS, 'p1');
const PRICES = { image: 10, sheet: 33 };

test('a plan is read off the proposal, and anything a card cannot draw is not a plan', () => {
  const p = plan();
  assert.equal(p.steps.length, 4);
  assert.deepEqual(p.steps.map((s) => s.status), ['pending', 'pending', 'pending', 'pending']);
  assert.deepEqual(p.steps[1].uses, [1]);
  assert.equal(p.steps[2].scene, 2);
  assert.equal(planOf({ steps: [ARGS.steps[0]] }, 'x'), null);                       // one step is a make, not a plan
  assert.equal(planOf({ steps: [ARGS.steps[0], { do: 'render' }] }, 'x'), null);     // a step nobody knows
  assert.equal(planOf(null, 'x'), null);
  // a step can only use, or act on, a step BEFORE it
  const odd = planOf({ steps: [{ do: 'image', args: {}, uses: [1, 2, 'a'] }, { do: 'queue', scene: 2 }] }, 'x');
  assert.deepEqual(odd.steps[0].uses, []);
  assert.equal(odd.steps[1].scene, undefined);
});

test('only what spends waits, only with Ask first on, and not when approved ahead', () => {
  let p = plan();
  assert.deepEqual(p.steps.map(isPaid), [true, false, true, false]);
  assert.equal(needsApproval(p, p.steps[0], 'ask'), true);
  assert.equal(needsApproval(p, p.steps[0], 'auto'), false);
  assert.equal(needsApproval(p, p.steps[1], 'ask'), false);
  p = approveStep(p, 1);
  assert.equal(needsApproval(p, p.steps[0], 'ask'), false);
});

test('Approve all covers the prices on the card and never the keyframes nobody has priced', () => {
  let p = approveAll(plan(), PRICES);
  assert.deepEqual(p.approved, [1]);
  assert.equal(needsApproval(p, p.steps[2], 'ask'), true);
  // once the scene exists the keyframes carry a quote, and can be approved
  p = patchStep(p, 3, { credits: 30 });
  assert.deepEqual(approveAll(p, PRICES).approved, [1, 3]);
  // with no price for the picked model, nothing is approved blind
  assert.deepEqual(approveAll(plan(), { image: null, sheet: null }).approved, []);
});

test('the total ahead is what is known, and says how many steps are not priced yet', () => {
  const p = plan();
  assert.deepEqual(ahead(p, PRICES), { credits: 10, priced: 1, unpriced: 1 });
  assert.deepEqual(ahead(patchStep(p, 3, { credits: 30 }), PRICES), { credits: 40, priced: 2, unpriced: 0 });
  assert.deepEqual(ahead(patchStep(p, 1, { status: 'done' }), PRICES), { credits: 0, priced: 0, unpriced: 1 });
  // an account that is not charged still has priced steps to approve
  assert.deepEqual(ahead(p, { image: 0, sheet: 0 }), { credits: 0, priced: 1, unpriced: 1 });
  assert.equal(priceOf(p.steps[1], PRICES), 0);
  assert.equal(priceOf(p.steps[2], PRICES), null);
});

test('the plan is on its first unfinished step, and its phase follows the steps', () => {
  let p = plan();
  assert.equal(phase(p), 'idle');
  assert.equal(nextStep(p).n, 1);
  p = patchStep({ ...p, started: true }, 1, { status: 'waiting' });
  assert.equal(phase(p), 'waiting');
  p = patchStep(p, 1, { status: 'running' });
  assert.equal(phase(p), 'running');
  p = patchStep(p, 1, { status: 'done', image: '/refs/a.jpg' });
  assert.equal(phase(p), 'paused');
  assert.equal(nextStep(p).n, 2);
  for (const n of [2, 3, 4]) p = patchStep(p, n, { status: n === 3 ? 'skipped' : 'done' });
  assert.equal(finished(p), true);
  assert.equal(phase(p), 'finished');
  assert.equal(nextStep(p), null);
  assert.deepEqual(progress(p), { done: 3, of: 3 });
});

test('skipping a scene takes the steps that only exist for it', () => {
  const p = skipStep(plan(), 2);
  assert.deepEqual(p.steps.map((s) => s.status), ['pending', 'skipped', 'skipped', 'skipped']);
  assert.match(stepAt(p, 3).note, /step 2 was skipped/);
  // a step that ran is not skipped after the fact, and one can come back
  const ran = patchStep(plan(), 1, { status: 'done' });
  assert.equal(skipStep(ran, 1), ran);
  assert.equal(restoreStep(skipStep(plan(), 1), 1).steps[0].status, 'pending');
  const back = restoreStep(patchStep(skipStep(plan(), 1), 2, { status: 'waiting' }), 1);
  assert.deepEqual(back.steps.map((s) => s.status).slice(0, 2), ['pending', 'pending']);
});

test('keyframes and the Queue need their scene; a used picture is never a blocker', () => {
  let p = plan();
  assert.equal(blockedBy(p, p.steps[2]), '');
  p = patchStep(p, 2, { status: 'failed' });
  assert.match(blockedBy(p, p.steps[2]), /step 2 did not finish/);
  p = patchStep(p, 2, { status: 'done', conceptId: null });
  assert.match(blockedBy(p, p.steps[3]), /wrote no scene/);
  p = patchStep(skipStep(plan(), 1), 2, { status: 'pending' });
  assert.equal(blockedBy(p, p.steps[1]), '');
  assert.deepEqual(picturesFor(p, p.steps[1]), []);
  p = patchStep(plan(), 1, { status: 'done', image: '/refs/hero.jpg' });
  assert.deepEqual(picturesFor(p, p.steps[1]), ['/refs/hero.jpg']);
});

test('editing a finished step re-runs that step and nothing else', () => {
  let p = plan();
  for (const n of [1, 2, 3, 4]) p = patchStep(p, n, { status: 'done', madeId: `m${n}`, image: '/x.jpg', conceptId: 7 });
  p = approveStep(p, 1);
  const edited = editStep(p, 1, { prompt: 'the can, warmer light' });
  assert.equal(edited.steps[0].status, 'pending');
  assert.equal(edited.steps[0].args.prompt, 'the can, warmer light');
  assert.equal(edited.steps[0].args.aspect, '4:5');
  assert.equal(edited.steps[0].madeId, undefined);
  assert.equal(edited.steps[0].edited, true);
  assert.deepEqual(edited.steps.slice(1).map((s) => s.status), ['done', 'done', 'done']);
  assert.deepEqual(edited.approved, []);                 // the approval was for the old words
  assert.equal(nextStep(edited).n, 1);
  // the plan was waiting on a LATER step: it is on the edited one now, so
  // that wait is over and the card offers Resume
  let waiting = patchStep({ ...p, started: true }, 3, { status: 'waiting' });
  waiting = editStep(waiting, 1, { prompt: 'again' });
  assert.deepEqual(waiting.steps.map((s) => s.status), ['pending', 'done', 'pending', 'done']);
  assert.equal(phase(waiting), 'paused');
  // editing the step the plan is waiting on ends that wait too: the approval is asked again
  let own = patchStep({ ...plan(), started: true }, 1, { status: 'waiting' });
  own = editStep(own, 1, { prompt: 'different words' });
  assert.equal(own.steps[0].status, 'pending');
  assert.equal(phase(own), 'paused');
  // a scene's new words carry their own count: the old one is not kept as a label
  const recut = editStep(plan(), 2, { prompt: 'He slides the can. Cut it into exactly 2 shots.' });
  assert.equal(recut.steps[1].args.shots, undefined);
  assert.equal(recut.steps[1].args.seconds, 10);
  assert.equal(stepTitle(recut.steps[1]), 'Scene · 10s');
  // a pending step keeps its place; a running one cannot be edited
  assert.equal(editStep(plan(), 2, { prompt: 'x' }).steps[1].status, 'pending');
  const running = patchStep(plan(), 1, { status: 'running' });
  assert.equal(editStep(running, 1, { prompt: 'x' }), running);
  assert.equal(editable(running.steps[0]), false);
  assert.equal(editable(plan().steps[2]), false);
});

test('a step says what it is and what it will do', () => {
  const p = plan();
  assert.equal(stepTitle(p.steps[0]), 'Still · 4:5');
  assert.equal(stepTitle(p.steps[1]), 'Scene · 3 shots · 10s');
  assert.equal(stepText(p, p.steps[0]), 'the exact can on wet steel');
  assert.match(stepText(p, p.steps[2]), /first frame of each shot in the scene from step 2/);
  assert.match(stepText(p, p.steps[3]), /Queue, where its clip is priced and approved/);
  const more = planOf({ steps: [
    { do: 'sheet', args: { name: 'Ana', notes: 'a red coat' } },
    { do: 'keep', args: { candidate_ids: ['c1', 'c2'] } },
  ] }, 'p2');
  assert.equal(stepTitle(more.steps[0]), 'Element sheet · Ana');
  assert.match(stepText(more, more.steps[0]), /Save Ana as a character .* wearing a red coat\./);
  assert.match(stepText(more, more.steps[1]), /Keep 2 reference frames/);
});

test('after a reload each step follows the turn its result went into', () => {
  let p = patchStep(plan(), 1, { status: 'running', madeId: 'm1' });
  assert.equal(reconcile(p, { m1: { status: 'running' } }), p);                    // still going: untouched
  assert.equal(reconcile(p, { m1: { status: 'done', image: '/a.jpg' } }).steps[0].status, 'done');
  // "done" with nothing drawn is a failure, never a finished step
  const empty = reconcile(p, { m1: { status: 'done', image: null } }).steps[0];
  assert.equal(empty.status, 'failed');
  assert.match(empty.note, /nothing was drawn/);
  assert.equal(reconcile(p, { m1: { status: 'stopped' } }).steps[0].note, 'stopped');
  // a scene is done when it wrote a concept
  p = patchStep(plan(), 2, { status: 'running', madeId: 'm2' });
  assert.equal(reconcile(p, { m2: { status: 'done', conceptId: 9 } }).steps[1].conceptId, 9);
  assert.equal(reconcile(p, { m2: { status: 'done', conceptId: null } }).steps[1].status, 'failed');
  // a failed still approved again on its own card: the step follows it
  p = patchStep(plan(), 1, { status: 'failed', madeId: 'm1', note: 'nothing was drawn' });
  assert.equal(reconcile(p, { m1: { status: 'running' } }).steps[0].status, 'running');
  assert.equal(reconcile(p, { m1: { status: 'done', image: '/b.jpg' } }).steps[0].image, '/b.jpg');
  assert.equal(reconcile(p, { m1: { status: 'failed' } }), p);
  // running with nothing behind it and nobody looping: back to pending
  p = patchStep(plan(), 3, { status: 'running' });
  assert.equal(reconcile(p, {}).steps[2].status, 'pending');
  assert.equal(reconcile(p, {}, [3]), p);
});

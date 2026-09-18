import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { held, usable, firstUsable, defaultPick, pickFor, withModel, planFor, approveText, chipText, legalDuration, specOf } from '../src/lib/render-choice.ts';

const choices = (values, d) => ({ kind: 'choices', values, default: d });
const renderers = {
  runway: { label: 'Runway', available: false, models: [
    { id: 'gen4_turbo', label: 'Gen-4 Turbo', available: true, duration: choices([5, 10], 5), frame: choices(['720:1280'], '720:1280'), price: { kind: 'per_second', usd: 0.05 } }] },
  veo: { label: 'Veo', available: true, models: [
    { id: 'veo-3', label: 'Veo 3', available: true, duration: { kind: 'fixed', values: [8], default: 8 }, frame: choices(['720p'], '720p'), price: { kind: 'per_second', usd: 0.4 } }] },
  fal: { label: 'fal.ai', available: true, frame_axis: 'resolution', models: [
    { id: 'kling', label: 'Kling', available: true, duration: choices([5, 10], 5), frame: choices(['1080p'], '1080p'), price: { kind: 'per_second', usd: 0.07 } },
    { id: 'ltx', label: 'LTX', available: true, duration: { kind: 'range', min: 1, max: 20, default: 6 }, frame: choices(['1080p', '2160p'], '1080p'), price: { kind: 'per_second', usd_by_frame: { '1080p': 0.04, '2160p': 0.16 } } },
    { id: 'ghost', label: 'Ghost', available: false, duration: choices([5], 5), frame: choices(['1080p'], '1080p'), price: { kind: 'flat', usd: 0.01 } }] },
};
beforeEach(() => held.clear());

test('a keyless vendor is never usable, whatever its models report', () => {
  assert.equal(usable(renderers, 'runway', 'gen4_turbo'), false);
  assert.equal(usable(renderers, 'fal', 'ghost'), false);
  assert.equal(usable(renderers, 'fal', 'kling'), true);
});

test('the plan leads when it can render; otherwise the CHEAPEST usable model, not registry order', () => {
  assert.deepEqual(defaultPick(renderers, { provider: 'fal', model: 'kling' }), { provider: 'fal', model: 'kling', duration: 5, frame: '1080p' });
  // planned for keyless Runway: LTX 6s@0.04 = $0.24 beats Kling $0.35 and Veo $3.20
  assert.deepEqual(defaultPick(renderers, { provider: 'runway', model: 'gen4_turbo' }), { provider: 'fal', model: 'ltx', duration: 6, frame: '1080p' });
  assert.equal(firstUsable({ runway: renderers.runway }), null);
  // nothing usable anywhere: the plan is still shown, on a dead button
  assert.equal(defaultPick({ runway: renderers.runway }, { provider: 'runway', model: 'gen4_turbo' }).provider, 'runway');
});

test('a held pick survives, until it stops being usable', () => {
  held.set(7, { provider: 'fal', model: 'ltx', duration: 9, frame: '2160p' });
  assert.equal(pickFor(renderers, 7, { provider: 'fal', model: 'kling' }).duration, 9);
  held.set(8, { provider: 'runway', model: 'gen4_turbo', duration: 5, frame: '720:1280' });
  assert.equal(pickFor(renderers, 8, { provider: 'fal', model: 'kling' }).model, 'kling');
});

test('a new model takes its own defaults', () => {
  assert.deepEqual(withModel(renderers, 'veo', 'veo-3'), { provider: 'veo', model: 'veo-3', duration: 8, frame: '720p' });
});

test('a legal length is the model\'s own set', () => {
  const kling = specOf(renderers, 'fal', 'kling').duration;
  assert.equal(legalDuration(kling, 7), false);
  assert.equal(legalDuration(specOf(renderers, 'fal', 'ltx').duration, 7), true);
});

test('the button carries shot count and price; a timed scene is priced by the server', () => {
  const spec = specOf(renderers, 'fal', 'kling');
  const pick = withModel(renderers, 'fal', 'kling');
  const parts = [{ seconds: 3 }, { seconds: 4, media_url: 'x.mp4' }, { seconds: 7 }];
  // the server's quote for this pick: the windows fitted, the done shot skipped
  const quote = { timed: true, durations: [5, 10], estimate_usd: 1.05 };
  const plan = planFor(spec, pick, parts, quote);
  assert.deepEqual(plan.lengths, [5, 10]);
  assert.equal(approveText(plan), 'Approve · 2 shots · ~$1.05');
  assert.equal(chipText(spec, pick, plan), 'KLING · 2 SHOTS · 1080P');
  // no quote yet: the shots are named, the number is not made up here
  const waiting = planFor(spec, pick, parts);
  assert.deepEqual(waiting.lengths, []);
  assert.equal(approveText(waiting), 'Approve · 2 shots · pricing…');
  assert.equal(approveText(planFor(spec, pick, parts, { error: 'no', timed: true, durations: [], estimate_usd: 0 })), 'Approve · 2 shots · refused');
  const whole = planFor(spec, pick, null);
  assert.equal(approveText(whole), 'Approve · 1 shot · ~$0.35');
  assert.equal(chipText(spec, pick, whole), 'KLING · 5S · 1080P');
  assert.equal(approveText(planFor({ ...spec, price: undefined }, pick, null)), 'Approve · 1 shot · unpriced');
});

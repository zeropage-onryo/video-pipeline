import { test } from 'node:test';
import assert from 'node:assert/strict';
import { continueActions, split, assetId, sendCost } from '../src/lib/continue.ts';

const ALL = ['nano-banana-edit', 'flux-kontext-pro', 'seedream-edit', 'remove-background', 'kling-effect',
  'pixverse-effect', 'camera-move', 'upscale', 'add-sound', 'reframe', 'reframe-hq',
  'remove-video-background', 'remove-video-background-pro'];
const has = { effects: ALL, ready: true };
const ids = (list) => list.map((a) => a.id);

test('a still: the few next moves in the row, the rest under More', () => {
  const still = { output: 'image', image: '/renders/a.png', asset: 'gen:7', conceptId: 3, prompt: 'a can on wet steel' };
  const { row, more } = split(continueActions(still, has));
  assert.deepEqual(ids(row), ['effect:nano-banana-edit', 'variation', 'animate', 'shot']);
  assert.deepEqual(ids(more), ['effect:remove-background', 'effect:camera-move', 'reference', 'element',
    'download', 'library', 'canvas', 'reuse']);
  // an action that can cost credits says a card comes first
  for (const a of [...row, ...more].filter((x) => x.kind === 'effect' || x.kind === 'variation')) {
    assert.match(a.title, /Nothing runs until you approve/);
  }
  assert.equal(row.find((a) => a.id === 'animate').tab, 'video_effect');
});

test('a still with no render id cannot be downloaded or opened on the wall', () => {
  const list = ids(continueActions({ output: 'image', image: '/refs/x.jpg', prompt: 'p' }, has));
  assert.ok(!list.includes('download') && !list.includes('library') && !list.includes('canvas'));
  assert.ok(list.includes('effect:nano-banana-edit'));   // an effect takes it as the box holds it
});

test('what an effect made has no prompt to draw again or put back', () => {
  const cut = { output: 'image', image: '/renders/cut.png', asset: 'gen:9', effect: 'remove-background', prompt: '' };
  const list = ids(continueActions(cut, has));
  assert.ok(!list.includes('variation') && !list.includes('reuse'));
  assert.ok(list.includes('effect:nano-banana-edit') && list.includes('element'));
  // a still with an empty prompt has nothing to vary either
  assert.ok(!ids(continueActions({ output: 'image', image: '/a.png', prompt: '  ' }, has)).includes('variation'));
});

test('a clip is finished, opened in the editor, saved; and only when it is on the wall', () => {
  const clip = { output: 'image', clip: '/renders/c.mp4', asset: 'gen:12', effect: 'kling-effect' };
  const { row, more } = split(continueActions(clip, has));
  assert.deepEqual(ids(row), ['effect:upscale', 'effect:add-sound', 'effect:reframe']);
  assert.deepEqual(ids(more), ['effect:remove-video-background', 'editor', 'download', 'library']);
  // a clip is named by its render id and nothing else
  assert.deepEqual(continueActions({ output: 'image', clip: '/renders/c.mp4', effect: 'kling-effect' }, has), []);
  assert.deepEqual(continueActions({ output: 'image', clip: '/c.mp4', asset: 'https://x/y.mp4' }, has), []);
});

test('a written scene keeps the three it had', () => {
  const scene = { output: 'video', conceptId: 41, prompt: 'she lifts the can' };
  const { row, more } = split(continueActions(scene, has));
  assert.deepEqual(ids(row), ['queue', 'canvas', 'reuse']);
  assert.deepEqual(more, []);
});

test('with effects off, nothing offers one; an effect the table lacks is not offered', () => {
  const still = { output: 'image', image: '/a.png', asset: 'gen:1', prompt: 'p' };
  const off = continueActions(still, { effects: ALL, ready: false });
  assert.ok(off.every((a) => a.kind !== 'effect' && a.kind !== 'gallery'));
  assert.deepEqual(ids(split(off).row), ['variation', 'shot']);
  const few = ids(continueActions(still, { effects: ['remove-background'], ready: true }));
  assert.ok(!few.includes('effect:nano-banana-edit') && few.includes('effect:remove-background'));
});

test('an overflow of one stays in the row', () => {
  const { row, more } = split([
    { id: 'a', kind: 'shot', label: 'A', title: '', primary: true },
    { id: 'b', kind: 'reuse', label: 'B', title: '', primary: false },
  ]);
  assert.deepEqual(ids(row), ['a', 'b']);
  assert.deepEqual(more, []);
});

test('a render id is only ever gen:<number>', () => {
  assert.equal(assetId('gen:42'), 42);
  for (const bad of ['gen:', 'gen:4x', 'asset:4', 'https://a/gen:4', '', null, undefined]) assert.equal(assetId(bad), null);
});

test('the send button says what a send can spend, and only then', () => {
  const base = { guide: true, output: 'image', generate: 'ask', stillCredits: 10, exempt: false };
  // Ask first: the send is free, the still waits on its card
  assert.equal(sendCost(base).credits, null);
  assert.match(sendCost(base).line, /Free to send/);
  // a scene is written for nothing, whatever the mode
  assert.equal(sendCost({ ...base, output: 'video', generate: 'auto' }).credits, null);
  // Auto + a still: the one send that can spend without another click
  const auto = sendCost({ ...base, generate: 'auto' });
  assert.equal(auto.credits, 10);
  assert.match(auto.line, /Auto is on.*10 credits\.$/);
  assert.match(sendCost({ ...base, generate: 'auto', exempt: true }).line, /10 credits, not charged/);
  assert.equal(sendCost({ ...base, generate: 'auto', stillCredits: 1250 }).line.includes('1,250 credits'), true);
  // no brain: a send in Image draws at once
  assert.equal(sendCost({ ...base, guide: false }).credits, 10);
  // a price that is not known is never invented
  const unknown = sendCost({ ...base, generate: 'auto', stillCredits: null });
  assert.equal(unknown.credits, null);
  assert.doesNotMatch(unknown.line, /\d/);
  // credits, never money
  for (const c of [base, { ...base, generate: 'auto' }]) assert.doesNotMatch(sendCost(c).line, /\$|usd|dollar/i);
});

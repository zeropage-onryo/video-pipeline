import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clipLength, speedOf, sourceFrameAt, isRetimed, ghostTrim, clampTrim } from '../src/lib/cut/timeline.ts';

// the same numbers as tests/test_cut_speed.py -- the preview and the ops
// must agree on where a sped or reversed clip is
const doc = (extra = {}) => ({
  fps: 30, size: [720, 1280], duration: 120, markers: [],
  tracks: [
    { id: 'V1', kind: 'video', clips: [
      { id: 'c1', media: 'gen:1', src_in: 0, src_out: 120, at: 0, dur: 60, ...extra },
      { id: 'c2', media: 'gen:2', src_in: 0, src_out: 60, at: 60 }] },
  ],
});

test('length is dur; speed is span / length', () => {
  const c = doc().tracks[0].clips[0];
  assert.equal(clipLength(c), 60);
  assert.equal(speedOf(c), 2);
  assert.ok(isRetimed(c));
  assert.ok(!isRetimed(doc().tracks[0].clips[1]));
});

test('source frame through the speed, from the end when reversed', () => {
  const c = { id: 'c', media: 'gen:1', at: 100, src_in: 30, src_out: 90, dur: 30 };
  assert.equal(sourceFrameAt(c, 10), 50);
  assert.equal(sourceFrameAt({ ...c, reverse: true }, 10), 70);
});

test('ghostTrim on a fast clip moves the source by the speed (ops.trim)', () => {
  const g = ghostTrim(doc(), 'c1', 10, 5, true);
  const [c1, c2] = g.tracks[0].clips;
  assert.deepEqual([c1.at, c1.src_in, c1.src_out, c1.dur], [0, 20, 110, 45]);
  assert.equal(c2.at, 45);
  const r = ghostTrim(doc({ reverse: true }), 'c1', 10, 0, false);
  assert.deepEqual([r.tracks[0].clips[0].at, r.tracks[0].clips[0].src_in, r.tracks[0].clips[0].src_out], [10, 0, 100]);
});

test('clampTrim on a fast clip counts the source room in timeline frames', () => {
  const c = { id: 'c', media: 'gen:1', src_in: 20, src_out: 100, at: 0, dur: 40 };   // 2x
  assert.deepEqual(clampTrim(c, -50, 0, 120), { head: -10, tail: 0 });
  assert.deepEqual(clampTrim(c, 0, -50, 120), { head: 0, tail: -10 });
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aspectOf, timecode, rulerStep, rulerLabel, stackOrder, partners, clipAt, snap, snapMove, snapPoints,
  ghostMove, ghostTrim, clampTrim, nearestCutPoint, trackEnd, endOf, fitPps, ppsToSlider, sliderToPps,
  framesToPx, pxToFrames, visibleClips, describeOp,
} from '../src/lib/cut/timeline.ts';

// the doc shape src/cut/doc.py writes: a picture clip and its own sound, linked
const doc = () => ({
  fps: 30, size: [720, 1280], duration: 300,
  tracks: [
    { id: 'A2', kind: 'audio', role: 'music', clips: [{ id: 'm1', media: 'asset:1', src_in: 0, src_out: 300, at: 0 }] },
    { id: 'V1', kind: 'video', clips: [
      { id: 'c1', media: 'gen:1', src_in: 0, src_out: 150, at: 0 },
      { id: 'c2', media: 'gen:2', src_in: 30, src_out: 180, at: 150 }] },
    { id: 'A1', kind: 'audio', role: 'sfx', clips: [
      { id: 'c1a', media: 'gen:1', src_in: 0, src_out: 150, at: 0, link: 'c1' },
      { id: 'c2a', media: 'gen:2', src_in: 30, src_out: 180, at: 150, link: 'c2' }] },
    { id: 'T1', kind: 'caption', style: 'preset:bold_center', cues: [{ id: 'q1', start: 10, end: 40, text: 'hi' }] },
    { id: 'V2', kind: 'video', clips: [] },
  ],
  markers: [{ frame: 200, label: 'Chapter 2' }],
});

test('timecode is mm:ss:ff at the project fps', () => {
  assert.equal(timecode(0, 30), '00:00:00');
  assert.equal(timecode(29, 30), '00:00:29');
  assert.equal(timecode(30 * 64 + 12, 30), '01:04:12');
  assert.equal(timecode(30 * 3600, 30), '01:00:00:00');
});

test('aspect is read off the canvas size, and an odd size has none', () => {
  assert.equal(aspectOf([720, 1280]), '9:16');
  assert.equal(aspectOf([1080, 1920]), '9:16');
  assert.equal(aspectOf([1280, 720]), '16:9');
  assert.equal(aspectOf([1080, 1080]), '1:1');
  assert.equal(aspectOf([1000, 700]), null);
});

test('tracks stack as an NLE draws them: V2 over V1, then audio, then text', () => {
  assert.deepEqual(stackOrder(doc().tracks).map((t) => t.id), ['V2', 'V1', 'A1', 'A2', 'T1']);
});

test('a clip and its linked sound are one unit, asked from either side', () => {
  assert.deepEqual(partners(doc(), 'c2').map((c) => c.id).sort(), ['c2', 'c2a']);
  assert.deepEqual(partners(doc(), 'c2a').map((c) => c.id).sort(), ['c2', 'c2a']);
  assert.deepEqual(partners(doc(), 'nope'), []);
});

test('the clip under the playhead; a crossfade shows the incoming one', () => {
  const v1 = doc().tracks[1];
  assert.equal(clipAt(v1, 0).id, 'c1');
  assert.equal(clipAt(v1, 149).id, 'c1');
  assert.equal(clipAt(v1, 150).id, 'c2');
  assert.equal(clipAt(v1, 300), null);
  v1.clips[1].at = 142; // an 8-frame crossfade
  assert.equal(clipAt(v1, 145).id, 'c2');
});

test('ruler steps keep labelled ticks at least ~90px apart at every zoom', () => {
  for (const pps of [4, 10, 40, 80, 200, 600, 1200]) {
    const step = rulerStep(30, pps);
    assert.ok(framesToPx(step.major, 30, pps) >= 90, `pps ${pps}`);
    assert.ok(step.minor >= 1 && step.major % step.minor === 0, `pps ${pps}`);
  }
  // zoomed in far enough, the labels are frames
  const deep = rulerStep(30, 1200);
  assert.ok(deep.major < 30);
  assert.equal(rulerLabel(45, 30, deep), '15f');
  assert.equal(rulerLabel(60, 30, rulerStep(30, 80)), '2s');
  assert.equal(rulerLabel(30 * 75, 30, rulerStep(30, 4)), '1:15');
});

test('zoom slider round-trips and clamps', () => {
  for (const pps of [4, 17, 80, 400, 1200]) assert.ok(Math.abs(sliderToPps(ppsToSlider(pps)) - pps) < 1e-6);
  assert.equal(sliderToPps(-1), 4);
  assert.equal(sliderToPps(2), 1200);
  assert.equal(pxToFrames(framesToPx(77, 30, 80), 30, 80), 77);
});

test('snap points: playhead, clip edges, cues, markers, zero -- minus the dragged group', () => {
  const pts = snapPoints(doc(), 99, new Set(['c2', 'c2a']));
  for (const p of [0, 99, 150, 10, 40, 200, 300]) assert.ok(pts.includes(p), `has ${p}`);
  assert.ok(!pts.includes(300 + 1));
  assert.equal(snap(147, pts, 5).frame, 150);
  assert.equal(snap(147, pts, 2).snapped, null);
});

test('a moved clip snaps by whichever edge is closer', () => {
  const pts = [0, 100, 250];
  assert.deepEqual(snapMove(97, 50, pts, 5), { at: 100, snapped: 100 });  // head to 100
  assert.deepEqual(snapMove(202, 50, pts, 5), { at: 200, snapped: 250 }); // tail to 250
  assert.deepEqual(snapMove(160, 50, pts, 5), { at: 160, snapped: null });
});

test('ghostMove moves the partners by the same amount and never touches the input', () => {
  const d = doc();
  const g = ghostMove(d, 'c2', 200);
  assert.equal(g.tracks[1].clips[1].at, 200);
  assert.equal(g.tracks[2].clips[1].at, 200);
  assert.equal(d.tracks[1].clips[1].at, 150, 'input untouched');
  const onto = ghostMove(d, 'c2', 150, 'V2');
  assert.equal(onto.tracks[4].clips[0].id, 'c2');
  assert.equal(onto.tracks[1].clips.length, 1);
  // a video clip cannot land on an audio track
  assert.equal(ghostMove(d, 'c2', 150, 'A2').tracks[3 - 3].clips.length, 1);
});

test('ghostTrim: head trim moves the start; ripple closes the gap behind', () => {
  const d = doc();
  const g = ghostTrim(d, 'c1', 10, 0, false);
  assert.deepEqual([g.tracks[1].clips[0].src_in, g.tracks[1].clips[0].at], [10, 10]);
  assert.equal(g.tracks[2].clips[0].src_in, 10, 'sound trimmed with it');
  const r = ghostTrim(d, 'c1', 0, 30, true);
  assert.equal(r.tracks[1].clips[0].src_out, 120);
  assert.equal(r.tracks[1].clips[1].at, 120, 'the next clip closes up');
});

test('clampTrim: never before the media start, past its end, or to nothing', () => {
  const c = { id: 'c', media: 'gen:1', src_in: 10, src_out: 40, at: 0 };
  assert.deepEqual(clampTrim(c, -50, 0, 100), { head: -10, tail: 0 });
  assert.deepEqual(clampTrim(c, 0, -100, 100), { head: 0, tail: -60 });
  assert.deepEqual(clampTrim(c, 40, 0, null), { head: 29, tail: 0 });
  assert.deepEqual(clampTrim(c, 0, 45, null), { head: 0, tail: 29 });
});

test('a drop inside a clip moves to its nearest edge; append is the track end', () => {
  const v1 = doc().tracks[1];
  assert.equal(nearestCutPoint(v1, 20), 0);
  assert.equal(nearestCutPoint(v1, 140), 150);
  assert.equal(nearestCutPoint(v1, 150), 150);
  assert.equal(nearestCutPoint(v1, 400), 400);
  assert.equal(trackEnd(v1), 300);
  assert.equal(trackEnd(doc().tracks[3]), 40);
  assert.equal(endOf(doc()), 300);
});

test('fitPps fits the cut into the width with air, within the zoom range', () => {
  const pps = fitPps(300, 30, 1000);
  assert.ok(framesToPx(300, 30, pps) <= 1000 && framesToPx(300, 30, pps) > 800);
  assert.equal(fitPps(30 * 3600 * 5, 30, 500), 4);
});

test('only the clips in the visible window are drawn', () => {
  const v1 = doc().tracks[1];
  assert.deepEqual(visibleClips(v1, 160, 400).map((c) => c.id), ['c2']);
  assert.deepEqual(visibleClips(v1, 0, 150).map((c) => c.id), ['c1']);
});

test('describeOp says what happened in words', () => {
  assert.equal(describeOp('split', { clip_id: 'c1', frame: 45 }, 30), 'Split c1 at 1.50s');
  assert.equal(describeOp('set_canvas', {}, 30), 'set canvas');
});

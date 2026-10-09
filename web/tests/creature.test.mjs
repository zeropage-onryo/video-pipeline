import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_PARK, DOCK, clampDock, clickIntent, readPark, snapPark } from '../src/lib/creature.ts';

test('a stored park is read back, and anything else is the default', () => {
  assert.deepEqual(readPark(JSON.stringify({ side: 'left', y: 180.4, small: true })), { side: 'left', y: 180, small: true });
  for (const bad of [null, undefined, '', 'nope', '[]', '1', JSON.stringify({ side: 'up', y: 'x', small: 'yes' })])
    assert.deepEqual(readPark(bad), { side: 'right', y: DEFAULT_PARK.y, small: false }, String(bad));
  assert.equal(readPark(JSON.stringify({ y: -40 })).y, 0);
});

test('a drag lets go on the nearer side, inside the window', () => {
  const view = { width: 1440, height: 900 };
  const at = (left, top) => snapPark({ left, top, width: 320, height: 320 }, view, false);
  assert.equal(at(100, 400).side, 'left');
  assert.equal(at(1000, 400).side, 'right');
  assert.equal(at(1000, 400).y, 180); // 900 - (400 + 320)
  assert.equal(at(1000, 700).y, 0); // dropped below the window: sits on its bottom
  assert.equal(at(1000, -200).y, 900 - 72 - 320); // dropped over the header: kept under it
  assert.equal(snapPark({ left: 10, top: 10, width: 80, height: 80 }, view, true).small, true);
});

test('one click waits for a second; a pair makes it small; a small one comes back at once', () => {
  assert.equal(clickIntent(0, false), 'now'); // Enter or Space
  assert.equal(clickIntent(1, false), 'later');
  assert.equal(clickIntent(2, false), 'double');
  assert.equal(clickIntent(3, false), 'ignore');
  assert.equal(clickIntent(0, true), 'now');
  assert.equal(clickIntent(1, true), 'now');
  assert.equal(clickIntent(2, true), 'ignore');
});

test('the dock is never shorter than its minimum nor taller than most of the window', () => {
  assert.equal(clampDock(100, 900), DOCK.min);
  assert.equal(clampDock(5000, 900), Math.round(900 * DOCK.share));
  assert.equal(clampDock(400, 900), 400);
  assert.equal(clampDock(NaN, 900), DOCK.start);
  assert.equal(clampDock(400, 300), DOCK.min); // a tiny window still gets the minimum
});

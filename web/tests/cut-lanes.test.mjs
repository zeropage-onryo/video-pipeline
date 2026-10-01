import { test } from 'node:test';
import assert from 'node:assert/strict';
import { valueAt, valueOf, lookAt, keyFrames, withKey, fitBoxes } from '../src/lib/cut/lanes.ts';

// the same keys and numbers as tests/test_cut_keyframes.py -- the preview
// and the render must agree on every frame
const K = [{ frame: 0, value: 1.0, ease: 'linear' }, { frame: 30, value: 2.0, ease: 'ease' },
  { frame: 60, value: 2.0, ease: 'hold' }, { frame: 90, value: 1.0, ease: 'linear' }];
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} vs ${b}`);

test('value_at holds outside and interpolates inside', () => {
  near(valueAt(K, -5, 9), 1.0);
  near(valueAt(K, 15, 9), 1.5);
  near(valueAt(K, 45, 9), 2.0);
  near(valueAt(K, 75, 9), 2.0);
  near(valueAt(K, 90, 9), 1.0);
  near(valueAt(K, 200, 9), 1.0);
  near(valueAt([], 10, 9), 9);
});

test('ease is smoothstep', () => {
  const k = [{ frame: 0, value: 0, ease: 'ease' }, { frame: 100, value: 1, ease: 'linear' }];
  near(valueAt(k, 25, 0), 0.15625);
  near(valueAt(k, 50, 0), 0.5);
});

test('a clip with no lanes is its defaults, and the look carries crop and opacity', () => {
  const look = lookAt({ crop: { left: 0.1 }, opacity: 0.5 }, 10);
  assert.deepEqual(look, { zoom: 1, x: 0, y: 0, rotation: 0, opacity: 0.5, crop: { left: 0.1, right: 0, top: 0, bottom: 0 } });
  near(valueOf({ lanes: [{ path: 'zoom', keys: K }] }, 'zoom', 15), 1.5);
});

test('keyFrames lists animating lanes only, unless a path is asked for', () => {
  const clip = { lanes: [{ path: 'zoom', keys: K }, { path: 'x', keys: [{ frame: 0, value: 0.2 }] }] };
  assert.deepEqual(keyFrames(clip), [0, 30, 60, 90]);
  assert.deepEqual(keyFrames(clip, 'x'), [0]);
});

test('withKey upserts in frame order, keeps an existing ease, and never touches the input', () => {
  const clip = { lanes: [{ path: 'zoom', keys: [{ frame: 0, value: 1, ease: 'ease' }] }] };
  const out = withKey(withKey(clip, 'zoom', 30, 1.5), 'zoom', 0, 1.2);
  assert.deepEqual(out.lanes[0].keys, [{ frame: 0, value: 1.2, ease: 'ease' }, { frame: 30, value: 1.5, ease: 'linear' }]);
  assert.equal(clip.lanes[0].keys.length, 1);
});

test('fitBoxes fits the CROPPED picture, as the render does', () => {
  // a 1440x1440 square into a 720x1280 frame: fits by width, letterboxed
  const plain = fitBoxes(720, 1280, 1440, 1440, { left: 0, right: 0, top: 0, bottom: 0 });
  assert.deepEqual(plain.pic, { left: 0, top: 280, width: 720, height: 720 });
  // cropping half the width away makes it 720x1440 -> fits by height now
  const cropped = fitBoxes(720, 1280, 1440, 1440, { left: 0.25, right: 0.25, top: 0, bottom: 0 });
  near(cropped.pic.height, 1280);
  near(cropped.pic.width, 640);
  near(cropped.el.width, 1280);       // the whole element, before the inset clips it
  near(cropped.el.left, -320);
});

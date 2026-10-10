import { test } from 'node:test';
import assert from 'node:assert/strict';
import { undrawn, madeStatus, failLine, NOT_MADE } from '../src/lib/made-state.ts';

test('a still that finished with nothing drawn is a failure, whatever the job said', () => {
  const empty = { status: 'done', output: 'image', image: null };
  assert.equal(undrawn(empty), true);
  assert.equal(madeStatus(empty), 'failed');
  assert.equal(madeStatus({ status: 'done', output: 'image', image: '/refs/a.jpg' }), 'done');
  // a scene has no image of its own: done is done
  assert.equal(madeStatus({ status: 'done', output: 'video' }), 'done');
  assert.equal(madeStatus({ status: 'running', output: 'image' }), 'running');
  assert.equal(madeStatus({ status: 'stopped', output: 'image' }), 'stopped');
});

test('an effect that turned a still into a clip made something', () => {
  // its record holds a clip and no image; reading it as "nothing drawn"
  // put Not made over a clip that was sitting on the Assets wall
  const clip = { status: 'done', output: 'image', image: null, clip: '/renders/fal/x.mp4' };
  assert.equal(undrawn(clip), false);
  assert.equal(madeStatus(clip), 'done');
  assert.equal(madeStatus({ status: 'done', output: 'image', image: null, clip: null }), 'failed');
});

test('a provider\'s raw words never reach the line, a plain sentence does', () => {
  const seenLive = 'image render skipped: HTTP Error 403: Forbidden -- {"detail":"User is locked. Reason: Exhausted balance. Top up your balance at fal.ai/dashboard/billing."}';
  assert.equal(failLine(seenLive), NOT_MADE);
  assert.equal(failLine(''), NOT_MADE);
  assert.equal(failLine(undefined), NOT_MADE);
  const plain = 'The still was not made: the image service is busy. Try again in a minute. Nothing was charged.';
  assert.equal(failLine(plain), plain);
  assert.equal(failLine('out of credits: this still needs 36 and the account has 4 -- top up to continue'),
    'out of credits: this still needs 36 and the account has 4 -- top up to continue');
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resultOf, creditsLabel, summary, ago, took, shouldNotify, unseen } from '../src/lib/job-feed.ts';

const job = (o) => ({ id: 1, kind: 'render', label: 'x', status: 'done', ...o });

test('a finished job opens where its result lives, or nowhere', () => {
  assert.deepEqual(resultOf(job({ ref_id: 12 })), { to: 'scene', id: 12 });
  assert.deepEqual(resultOf(job({ kind: 'keyframe', ref_id: 3 })), { to: 'scene', id: 3 });
  assert.deepEqual(resultOf(job({ kind: 'cut', ref_id: 'a1b2-uuid' })), { to: 'cut', id: 'a1b2-uuid' });
  assert.deepEqual(resultOf(job({ kind: 'cut', ref_id: 375 })), { to: 'scene', id: 375 });     // an Assemble
  assert.deepEqual(resultOf(job({ kind: 'sheet', output: '/characters/nova/sheet.jpg' })), { to: 'elements' });
  assert.deepEqual(resultOf(job({ ref_id: null, output: '/renders/x.png' })), { to: 'assets' });  // a Director node
  assert.equal(resultOf(job({ kind: 'guide' })), null);
  assert.equal(resultOf(job({ kind: 'index', ref_id: 5 })), null);
  assert.equal(resultOf(job({ status: 'failed', ref_id: 12 })), null);                       // nothing to open
});

test('credits are said the way the Queue says prices', () => {
  assert.equal(creditsLabel(job({ credits: 174, charged: true })), '174 cr');
  assert.equal(creditsLabel(job({ credits: 87, charged: false })), '87 cr · not charged');
  assert.equal(creditsLabel(job({ status: 'running', credits: 0, credits_held: 87, charged: true })), '87 cr held');
  assert.equal(creditsLabel(job({ status: 'running', credits: 87, credits_held: 87, charged: true })), '87 cr · 87 cr held');
  assert.equal(creditsLabel(job({ credits: 0, credits_held: 0, charged: true })), null);  // released: spent nothing
  assert.equal(creditsLabel(job({})), null);                                                // never metered
  assert.equal(creditsLabel(job({ credits: 1840 })), '1,840 cr');
});

test('the summary counts running, failed, held and spent -- uncharged is not spent', () => {
  const s = summary([
    job({ status: 'running', credits_held: 87 }),
    job({ status: 'queued' }),
    job({ status: 'failed' }),
    job({ credits: 174, charged: true }),
    job({ credits: 87, charged: false }),
  ]);
  assert.deepEqual(s, { running: 2, failed: 1, held: 87, spent: 174 });
});

test('ago and took read the server\'s ISO times', () => {
  const now = Date.parse('2026-10-08T12:00:00+00:00');
  assert.equal(ago('2026-10-08T11:59:30+00:00', now), 'just now');
  assert.equal(ago('2026-10-08T11:56:00+00:00', now), '4m ago');
  assert.equal(ago('2026-10-08T10:00:00+00:00', now), '2h ago');
  assert.equal(ago('2026-10-05T12:00:00+00:00', now), '3d ago');
  assert.equal(ago(null, now), '');
  assert.equal(took(job({ started_at: '2026-10-08T12:00:00+00:00', ended_at: '2026-10-08T12:01:30+00:00' })), 90);
  assert.equal(took(job({ started_at: '2026-10-08T12:00:00+00:00', ended_at: null })), null);
});

test('only a job seen running that ended long after it started is worth a notification', () => {
  const long = job({ started_at: '2026-10-08T12:00:00+00:00', ended_at: '2026-10-08T12:01:00+00:00' });
  const short = job({ started_at: '2026-10-08T12:00:00+00:00', ended_at: '2026-10-08T12:00:05+00:00' });
  assert.equal(shouldNotify('running', long), true);
  assert.equal(shouldNotify('running', { ...long, status: 'failed' }), true);
  assert.equal(shouldNotify('running', { ...long, status: 'cancelled' }), false);   // the person's own doing
  assert.equal(shouldNotify('running', short), false);
  assert.equal(shouldNotify(undefined, long), false);                               // replayed already finished
  assert.equal(shouldNotify('done', long), false);
});

test('the bell\'s dot counts finished jobs newer than the last one shown', () => {
  const jobs = [job({ id: 9 }), job({ id: 8, status: 'running' }), job({ id: 7 }), job({ id: 5 })];
  assert.equal(unseen(jobs, 6), 2);
  assert.equal(unseen(jobs, 9), 0);
});

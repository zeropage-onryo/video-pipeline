import { test } from 'node:test';
import assert from 'node:assert/strict';
import { headline, typeAhead } from '../src/lib/assistant-text.ts';

test('typing catches up with the words so far, a little each frame', () => {
  const target = 'Here is the room as I see it: a dive bar after last call, sodium light on wet glass.';
  let shown = '';
  const frames = [];
  while (shown !== target) {
    const next = typeAhead(shown, target);
    assert.ok(target.startsWith(next), 'only ever a start of the answer');
    assert.ok(next.length > shown.length, 'every frame moves');
    shown = next;
    frames.push(shown.length);
    assert.ok(frames.length < 120, 'catches up well inside two seconds at 60fps');
  }
  assert.ok(frames[0] < 10, 'the first frame does not dump the whole poll');
});

test('more words keep typing on from where it was; a retry starts over', () => {
  assert.equal(typeAhead('Here is', 'Here is the room'), 'Here is ');
  assert.equal(typeAhead('Here is the room', 'Here is the room'), 'Here is the room');
  assert.equal(typeAhead('Half an ans', 'Whole'), 'W');
  assert.equal(typeAhead('anything', ''), '');
});

test('the bubble says the next move, else the first sentence', () => {
  assert.equal(headline('Keep the frames you like', 'Long answer.'), 'Keep the frames you like');
  assert.equal(headline('  ', 'Here is the room as I see it. Then more.'), 'Here is the room as I see it.');
  // a short opener runs on to the next sentence rather than saying only "Got it."
  assert.equal(
    headline(undefined, 'Got it. Do you want it to feel lonely, or like the night is just getting started?'),
    'Got it. Do you want it to feel lonely, or like the night is just getting started?',
  );
  const long = headline('', 'word '.repeat(60).trim());
  assert.ok(long.length <= 108 && long.endsWith('…') && !long.includes('wor…'));
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tokens, scoreCommand, rankCommands, marks, step, modKey, isPaletteKey } from '../src/lib/palette.ts';

test('tokens follow the server rule: lowercase words, at most six', () => {
  assert.deepEqual(tokens('  Open   THE queue '), ['open', 'the', 'queue']);
  assert.deepEqual(tokens('a b c d e f g h'), ['a', 'b', 'c', 'd', 'e', 'f']);
  assert.deepEqual(tokens(''), []);
});

test('every word must match, in the title or the keywords', () => {
  assert.equal(scoreCommand('queue', 'Go to Queue'), 3);
  assert.equal(scoreCommand('approve', 'Go to Queue', 'approve render spend'), 1);
  assert.equal(scoreCommand('approve zebra', 'Go to Queue', 'approve render spend'), 0);
  assert.equal(scoreCommand('', 'Anything'), 1);
});

test('a title that starts with the query outranks a word match and a keyword match', () => {
  const items = [
    { title: 'Go to Queue', keywords: 'approve render' },
    { title: 'Draw keyframes', keywords: 'queue stills' },
    { title: 'Queue settings' },
  ];
  assert.deepEqual(rankCommands(items, 'queue').map((i) => i.title), ['Queue settings', 'Go to Queue', 'Draw keyframes']);
  // ties keep the order given, and the limit holds
  assert.deepEqual(rankCommands(items, '', 2).map((i) => i.title), ['Go to Queue', 'Draw keyframes']);
});

test('marks cut text into the runs that matched, keeping its casing', () => {
  assert.deepEqual(marks('Ridge Line', 'ridge'), [{ text: 'Ridge', hit: true }, { text: ' Line', hit: false }]);
  assert.deepEqual(marks('a ridge, a RIDGE', 'ridge'), [
    { text: 'a ', hit: false },
    { text: 'ridge', hit: true },
    { text: ', a ', hit: false },
    { text: 'RIDGE', hit: true },
  ]);
  assert.deepEqual(marks('no match', ''), [{ text: 'no match', hit: false }]);
  assert.deepEqual(marks('', 'x'), []);
});

test('the arrow keys wrap, and an empty list has nothing active', () => {
  assert.equal(step(0, 1, 3), 1);
  assert.equal(step(2, 1, 3), 0);
  assert.equal(step(0, -1, 3), 2);
  assert.equal(step(-1, 1, 3), 0);
  assert.equal(step(-1, -1, 3), 2);
  assert.equal(step(1, 1, 0), -1);
});

test('the shortcut is the platform modifier plus K, and only that', () => {
  assert.equal(modKey('MacIntel'), '⌘');
  assert.equal(modKey('iPhone'), '⌘');
  assert.equal(modKey('Win32'), 'Ctrl');
  const k = { key: 'k', metaKey: true, ctrlKey: false, altKey: false, shiftKey: false };
  assert.equal(isPaletteKey(k), true);
  assert.equal(isPaletteKey({ ...k, metaKey: false, ctrlKey: true, key: 'K' }), true);
  assert.equal(isPaletteKey({ ...k, metaKey: false }), false);       // bare k is the editor's pause
  assert.equal(isPaletteKey({ ...k, shiftKey: true }), false);
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { verdictOf, typingIn, moveCursor, nextAfter } from '../src/lib/verdict-keys.ts';

const key = (k, o = {}) => ({ key: k, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...o });

test('A approves, X rejects, the arrows move -- the up/down pair only on a column', () => {
  assert.equal(verdictOf(key('a')), 'approve');
  assert.equal(verdictOf(key('A')), 'approve');                       // Caps Lock sends "A" without Shift
  assert.equal(verdictOf(key('x')), 'reject');
  assert.equal(verdictOf(key('ArrowRight')), 'next');
  assert.equal(verdictOf(key('ArrowLeft')), 'prev');
  assert.equal(verdictOf(key('ArrowDown')), null);                    // the Queue leaves ↓ to scroll the page
  assert.equal(verdictOf(key('ArrowDown'), { vertical: true }), 'next');
  assert.equal(verdictOf(key('ArrowUp'), { vertical: true }), 'prev');
  assert.equal(verdictOf(key('s')), null);
  assert.equal(verdictOf(key('Enter')), null);                        // a focused button's own key, never ours
});

test('a modified, composed, held or already-handled key is never a verdict', () => {
  assert.equal(verdictOf(key('a', { metaKey: true })), null);         // ⌘A selects all
  assert.equal(verdictOf(key('k', { metaKey: true })), null);         // the palette's
  assert.equal(verdictOf(key('x', { ctrlKey: true })), null);
  assert.equal(verdictOf(key('a', { altKey: true })), null);
  assert.equal(verdictOf(key('A', { shiftKey: true })), null);
  assert.equal(verdictOf(key('ArrowRight', { shiftKey: true })), null);
  assert.equal(verdictOf(key('a', { isComposing: true })), null);
  assert.equal(verdictOf(key('a', { defaultPrevented: true })), null);
  assert.equal(verdictOf(key('x', { repeat: true })), null);           // a held X decides once
  assert.equal(verdictOf(key('ArrowRight', { repeat: true })), 'next'); // a held arrow keeps walking
});

test('a letter typed into a field is a letter', () => {
  assert.equal(typingIn({ tagName: 'INPUT' }), true);
  assert.equal(typingIn({ tagName: 'textarea' }), true);
  assert.equal(typingIn({ tagName: 'SELECT' }), true);
  assert.equal(typingIn({ tagName: 'DIV', isContentEditable: true }), true);
  assert.equal(typingIn({ tagName: 'BUTTON' }), false);
  assert.equal(typingIn({ tagName: 'ARTICLE' }), false);
  assert.equal(typingIn(null), false);
});

test('the cursor walks the cards that can take a verdict and stops at the ends', () => {
  const order = [10, 11, 12, 13];
  const open = (id) => id !== 12;                                     // 12 is rendering
  assert.equal(moveCursor(order, null, 1, open), 10);                 // no cursor: the first
  assert.equal(moveCursor(order, null, -1, open), 13);                // or the last, going back
  assert.equal(moveCursor(order, 10, 1, open), 11);
  assert.equal(moveCursor(order, 11, 1, open), 13);                   // over the one being rendered
  assert.equal(moveCursor(order, 13, 1, open), 13);                   // the end: no wrap
  assert.equal(moveCursor(order, 10, -1, open), 10);
  assert.equal(moveCursor(order, 12, -1, open), 11);                  // from a card that just went busy
  assert.equal(moveCursor(order, 99, 1, open), 10);                   // a cursor that left the list starts over
  assert.equal(moveCursor(order, null, 1, () => false), null);        // nothing left to decide
  assert.equal(moveCursor([], null, 1), null);
});

test('after a verdict the cursor goes on, else back, never onto the card just decided', () => {
  const order = [1, 2, 3, 4];
  assert.equal(nextAfter(order, 2), 3);
  assert.equal(nextAfter(order, 4), 3);                               // the last one: step back
  assert.equal(nextAfter(order, 2, (id) => id !== 3), 4);
  assert.equal(nextAfter(order, 3, (id) => id === 3), null);          // it was the only one
  assert.equal(nextAfter([7], 7), null);
  assert.equal(nextAfter(order, 9), 1);                               // not on the list: the first
});

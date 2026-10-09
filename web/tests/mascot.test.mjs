import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  LOOKS,
  CREATURES,
  MOODS,
  allImages,
  coloursOf,
  decodeMascot,
  encodeMascot,
  isMascotCode,
  looksOf,
  mascotSrc,
  moodFor,
  nameOf,
  sizeFor,
  smallerSrc,
  DEFAULT_AVATAR,
} from '../src/lib/mascot.ts';

test('the asset set is the 483 images that were rendered', () => {
  // 15 looks; the six that own a shared colour have 4 colours, the other nine 5; 7 moods each
  assert.equal(LOOKS.length, 15);
  const four = LOOKS.filter((l) => coloursOf(l.id).length === 4).map((l) => l.id).sort();
  assert.deepEqual(four, ['glim-clay', 'glim-felt', 'nimbus-felt', 'nimbus-knit', 'pip-orig', 'sprout-felt']);
  assert.equal(allImages().length, 483);
  assert.equal(new Set(allImages()).size, 483);
  assert.deepEqual([...MOODS], ['awake', 'listen', 'think', 'talk', 'made', 'oops', 'sleep']);
});

test('every creature has three looks, and the names never change', () => {
  assert.deepEqual(CREATURES.map((c) => c.name), ['Nimbus', 'Mote', 'Sprout', 'Glim', 'Pip']);
  for (const c of CREATURES) assert.equal(looksOf(c.id).length, 3, c.id);
});

test('a code fits the server avatar column and survives its cleaner', () => {
  // assistant_store.clean_avatar: drops whitespace, < > & " ' and cuts to 16
  for (const look of LOOKS)
    for (const c of coloursOf(look.id)) {
      const code = encodeMascot({ look: look.id, colour: c.id });
      assert.ok(code.length <= 16, code);
      assert.equal(code.replace(/[\s<>&"']/g, ''), code);
      assert.ok(isMascotCode(code), code);
      assert.deepEqual(decodeMascot(code), { look: look.id, colour: c.id });
    }
});

test('anything that is not a mascot code reads as Nimbus in lavender felt', () => {
  for (const old of ['🦊', 'glyph:aperture', '', null, undefined, 'm:zz.own', 'm:nf.xyz'])
    assert.deepEqual(decodeMascot(old), { look: 'nimbus-felt', colour: 'own' }, String(old));
  assert.equal(DEFAULT_AVATAR, 'm:nf.own');
  assert.equal(nameOf(decodeMascot('🦊')), 'Nimbus');
  assert.equal(nameOf(decodeMascot('m:pm.red')), 'Pip');
});

test('a colour a look does not come in falls back to its own', () => {
  // nimbus-felt IS lavender, so it is never offered lavender again
  assert.deepEqual(decodeMascot('m:nf.lav'), { look: 'nimbus-felt', colour: 'own' });
  assert.equal(encodeMascot({ look: 'nimbus-felt', colour: 'lavender' }), 'm:nf.own');
});

test('the image url names the look, colour, mood and size', () => {
  const src = mascotSrc({ look: 'sprout-velvet', colour: 'lightred' }, 'think', 320);
  assert.match(src, /\/320\/sprout-velvet-lightred-think\.webp$/);
  assert.equal(sizeFor(56), 128);
  assert.equal(sizeFor(96), 320);
  assert.equal(sizeFor(320), 640); // the floating creature
  assert.equal(smallerSrc(mascotSrc({ look: 'pip-orig', colour: 'own' }, 'awake', 640)), mascotSrc({ look: 'pip-orig', colour: 'own' }, 'awake', 320));
  assert.equal(smallerSrc(mascotSrc({ look: 'pip-orig', colour: 'own' }, 'awake', 320)), null);
});

test('states map to moods, and talking flaps between two frames', () => {
  assert.equal(moodFor('idle'), 'awake');
  assert.equal(moodFor('listening'), 'listen');
  assert.equal(moodFor('thinking'), 'think');
  assert.equal(moodFor('working'), 'think');
  assert.equal(moodFor('needs'), 'awake');
  assert.equal(moodFor('success'), 'made');
  assert.equal(moodFor('error'), 'oops');
  assert.equal(moodFor('sleeping'), 'sleep');
  assert.equal(moodFor('talking', true), 'talk');
  assert.equal(moodFor('talking', false), 'awake');
});

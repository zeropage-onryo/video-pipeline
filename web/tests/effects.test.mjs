import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  candidates, sourcesFor, unavailable, defaults, settle, optionLabel, valueLabel, missing, takesLine,
  fromPrice, requestOf, begin,
} from '../src/lib/effects.ts';

const KLING = {
  id: 'kling-effect', label: 'Kling effects', category: 'video_effect', blurb: 'templates',
  takes: 'image', output: 'video', sources: { min: 1, max: 2 }, prompt: 'none', credits: 68,
  options: {
    effect_scene: { values: ['heart_gesture', 'bloom_bloom'], default: null, required: true },
    duration: { values: ['5', '10'], default: '5', required: false },
  },
};
const EDIT = {
  id: 'nano-banana-edit', label: 'Nano Banana edit', category: 'image_edit', blurb: 'edit',
  takes: 'image', output: 'image', sources: { min: 1, max: 4 }, prompt: 'required', credits: 10,
  options: { aspect_ratio: { values: ['auto', '1:1'], default: 'auto', required: false } },
};
const SOUND = {
  id: 'add-sound', label: 'Add sound', category: 'finish', blurb: 'sound',
  takes: 'video', output: 'video', sources: { min: 1, max: 1 }, prompt: 'required', credits: null, options: {},
};

test('what an effect can act on: the attached images first, then results from the newest back', () => {
  const all = candidates(['/refs/a.jpg', '/refs/b.jpg'], [
    { image: 'https://r2/old.png' },
    { clip: 'https://r2/clip.mp4', asset: 'gen:7' },
    { clip: 'https://r2/unnamed.mp4' },                 // a clip with no id cannot be a source
    { image: 'https://r2/new.png', asset: 'gen:9' },
  ]);
  assert.deepEqual(all.map((c) => `${c.kind}:${c.ref}:${c.from}`), [
    'image:/refs/a.jpg:attached',
    'image:/refs/b.jpg:attached',
    'image:gen:9:the last still',
    'clip:gen:7:the last clip',
    'image:https://r2/old.png:an earlier still',
  ]);
  // a render is drawn by its address and named by its id
  assert.equal(all[2].thumb, 'https://r2/new.png');
});

test('an effect is bound to what is attached, else to the newest result that fits', () => {
  const all = candidates(['/refs/a.jpg', '/refs/b.jpg', '/refs/c.jpg'], [{ clip: 'x', asset: 'gen:7' }]);
  assert.deepEqual(sourcesFor(KLING, all).map((c) => c.ref), ['/refs/a.jpg', '/refs/b.jpg']);   // up to what it takes
  assert.deepEqual(sourcesFor(SOUND, all).map((c) => c.ref), ['gen:7']);
  const results = candidates([], [{ image: 'old' }, { image: 'new', asset: 'gen:9' }]);
  assert.deepEqual(sourcesFor(EDIT, results).map((c) => c.ref), ['gen:9']);                     // one, the newest
  assert.equal(unavailable(EDIT, results), '');
  assert.match(unavailable(SOUND, results), /Needs a clip/);
  assert.match(unavailable(EDIT, []), /Needs an image/);
  // an effect that takes two binds to the two newest; with one there, it says so
  const pair = { takes: 'image', sources: { min: 2, max: 2 } };
  assert.deepEqual(sourcesFor(pair, results).map((c) => c.ref), ['gen:9', 'old']);
  assert.match(unavailable(pair, candidates([], [{ image: 'only' }])), /Needs 2 images/);
});

test('options start at the table\'s defaults, and a proposal\'s are held to the table', () => {
  assert.deepEqual(defaults(KLING), { duration: '5' });                     // the required one is the person's to pick
  assert.deepEqual(settle(KLING, { effect_scene: 'bloom_bloom', duration: 10, colour: 'red' }),
    { duration: '10', effect_scene: 'bloom_bloom' });                       // legal values, as the table spells them
  assert.deepEqual(settle(KLING, { effect_scene: 'melt-it' }), { duration: '5' });
  assert.deepEqual(settle(KLING, null), { duration: '5' });
});

test('the card says what is still missing, the nearest thing first', () => {
  const start = begin(KLING, candidates(['/refs/a.jpg'], []), 'e1');
  assert.equal(missing(KLING, start), 'Pick a template');
  assert.equal(missing(KLING, { ...start, options: { ...start.options, effect_scene: 'bloom_bloom' } }), '');
  assert.equal(missing(KLING, { ...start, sources: [] }), 'Needs an image to work on');
  const edit = begin(EDIT, candidates(['/refs/a.jpg'], []), 'e2');
  assert.equal(missing(EDIT, edit), 'Say what to change');
  assert.equal(missing(EDIT, { ...edit, prompt: 'make it blue' }), '');
  const sound = begin(SOUND, candidates([], [{ clip: 'x', asset: 'gen:7' }]), 'e3');
  assert.equal(missing(SOUND, sound), 'Say what it should sound like');
  assert.equal(missing(SOUND, { ...sound, sources: [] }), 'Needs a clip to work on');
});

test('a new effect carries the brain\'s words only where the effect takes words', () => {
  const all = candidates(['/refs/a.jpg'], []);
  const edit = begin(EDIT, all, 'e1', { prompt: '  make the label blue ', options: { aspect_ratio: '1:1' } });
  assert.equal(edit.prompt, 'make the label blue');
  assert.deepEqual(edit.options, { aspect_ratio: '1:1' });
  assert.equal(begin(KLING, all, 'e2', { prompt: 'ignored' }).prompt, '');
  assert.deepEqual(requestOf({ ...edit, prompt: ' x ' }), {
    effect: 'nano-banana-edit', sources: ['/refs/a.jpg'], prompt: 'x', options: { aspect_ratio: '1:1' },
  });
});

test('names and values read as words, and a price is credits or says why it is not known', () => {
  assert.equal(optionLabel('effect_scene'), 'Template');
  assert.equal(optionLabel('camera_movement'), 'Camera move');
  assert.equal(optionLabel('some_new_option'), 'Some new option');
  assert.equal(valueLabel('effect_scene', 'bloom_bloom'), 'Bloom bloom');
  assert.equal(valueLabel('duration', '5'), '5s');
  assert.equal(valueLabel('upscale_factor', 2), '2x');
  assert.equal(valueLabel('upscale_factor', 1), 'Keep the size');
  assert.equal(valueLabel('target_fps', 60), '60 fps');
  assert.equal(valueLabel('subject_is_person', false), 'No');
  assert.equal(valueLabel('resolution', '1080p'), '1080p');
  assert.equal(takesLine(KLING), 'Up to 2 images in, a clip out');
  assert.equal(takesLine(SOUND), 'A clip in, a clip out');
  assert.equal(fromPrice(KLING, false), 'From 68 credits');
  assert.equal(fromPrice(KLING, true), '68 credits · not charged');
  assert.equal(fromPrice(SOUND, false), "Priced by the clip's length");
});

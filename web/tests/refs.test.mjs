import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseRef, sourcesFor, fileName, sourceLabel } from '../src/lib/refs.ts';

test('both stored shapes of an asset photo read the same (asset_shelf.parse_ref twin)', () => {
  const local = parseRef('/characters/michael/photo/a.jpg?thumb=1');
  const r2 = parseRef('https://pub-x.r2.dev/characters/michael/a.jpg');
  assert.deepEqual(local, { kind: 'character', plural: 'characters', slug: 'michael', filename: 'a.jpg' });
  assert.deepEqual(r2, local);
  assert.deepEqual(parseRef('/refs/abc.jpg'), { kind: 'refs', plural: 'refs', slug: '', filename: 'abc.jpg' });
});

test('a render URL, a climbing path and junk are not references', () => {
  for (const url of ['/renders/x.jpg', '/characters/../etc/passwd', '', null, 'data:image/png;base64,AA', 'https://x.test/a/b/c/d/e.jpg'])
    assert.equal(parseRef(url), null, String(url));
});

test('the local route is tried first, then the stored URL', () => {
  assert.deepEqual(sourcesFor('https://pub-x.r2.dev/props/bike/b.jpg', { thumb: true }),
    ['/props/bike/photo/b.jpg?thumb=1', '/props/bike/photo/b.jpg', 'https://pub-x.r2.dev/props/bike/b.jpg']);
  assert.deepEqual(sourcesFor('/refs/abc.jpg', { base: 'https://api.test' }), ['https://api.test/refs/abc.jpg']);
  assert.deepEqual(sourcesFor('https://cdn.test/renders/k.png'), ['https://cdn.test/renders/k.png']);
});

test('the caption says the file and the shelf, never an invented source', () => {
  assert.equal(fileName('https://pub-x.r2.dev/props/bike/IMG%201.jpg'), 'IMG 1.jpg');
  assert.equal(sourceLabel('/props/bike/photo/b.jpg'), 'ASSET BANK · PROP · bike');
  assert.equal(sourceLabel('/refs/abc.jpg'), 'REFERENCE BIN');
  assert.equal(sourceLabel('https://cdn.test/renders/k.png'), 'DRAWN BY THE PIPELINE');
});

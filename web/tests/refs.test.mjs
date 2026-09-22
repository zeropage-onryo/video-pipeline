import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseRef, sourcesFor, fileName, sourceLabel, sourced } from '../src/lib/refs.ts';

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

test("the server's own thumbnail goes first, and refs stay the master (BACKLOG #0)", () => {
  assert.deepEqual(
    sourcesFor('https://pub-x.r2.dev/props/bike/b.jpg', { thumb: true, small: 'https://pub-x.r2.dev/t/1/props/bike/b.jpg' }),
    ['https://pub-x.r2.dev/t/1/props/bike/b.jpg', '/props/bike/photo/b.jpg?thumb=1', '/props/bike/photo/b.jpg', 'https://pub-x.r2.dev/props/bike/b.jpg']);
  // a local thumbnail rides the API base like any local route, and is not listed twice
  assert.deepEqual(sourcesFor('/props/bike/photo/b.jpg', { thumb: true, base: 'https://api.test', small: '/props/bike/photo/b.jpg?thumb=1' }),
    ['https://api.test/props/bike/photo/b.jpg?thumb=1', 'https://api.test/props/bike/photo/b.jpg']);
  assert.deepEqual(sourcesFor('/refs/abc.jpg', { small: '' }), ['/refs/abc.jpg']);
});

test('the caption says the file and the shelf, never an invented source', () => {
  assert.equal(fileName('https://pub-x.r2.dev/props/bike/IMG%201.jpg'), 'IMG 1.jpg');
  assert.equal(sourceLabel('/props/bike/photo/b.jpg'), 'ASSET BANK · PROP · bike');
  assert.equal(sourceLabel('/refs/abc.jpg'), 'REFERENCE BIN');
  assert.equal(sourceLabel('https://cdn.test/renders/k.png'), 'DRAWN BY THE PIPELINE');
});

test('a scouted frame links its page; an upload and an unknown bin image say they have none', () => {
  const row = (over) => ({ url: '/refs/a.jpg', kind: 'refs', slug: '', filename: 'a.jpg', source_url: '', title: '', lane: '', ...over });
  assert.deepEqual(sourced(row({ source_url: 'https://www.ex.test/post/1', title: 'stairwell', lane: 'feeds' })),
    { url: '/refs/a.jpg', name: 'a.jpg', href: 'https://www.ex.test/post/1', source: 'FEEDS · ex.test · stairwell' });
  assert.equal(sourced(row({ lane: 'composer' })).source, 'YOUR UPLOAD · NO SOURCE PAGE');
  assert.equal(sourced(row({})).source, 'REFERENCE BIN · NO SOURCE ON FILE');
  // never a javascript: or relative "source" turned into a link
  assert.equal(sourced(row({ source_url: 'javascript:alert(1)', lane: 'agent' })).href, undefined);
  const asset = sourced({ url: '/props/bike/photo/b.jpg', kind: 'prop', slug: 'bike', filename: 'b.jpg', source_url: '', title: '', lane: '' });
  assert.equal(asset.source, 'ASSET BANK · PROP · bike');
});

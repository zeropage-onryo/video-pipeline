import { test } from 'node:test';
import assert from 'node:assert/strict';
import { seedScene, toLegacy, fromLegacy, groupRefs, wireElement } from '../src/lib/director-graph.ts';

const shot = {
  n: 2, prompt: 'finished prompt', written_prompt: 'old draft',
  refs: ['/characters/michael/photo/a.jpg', '/characters/michael/photo/b.jpg', '/locations/studio-bedroom/photo/r.jpg', 'https://cdn.test/bike.jpg'],
  reference_image: '/renders/frame.jpg', media_url: 'https://cdn.test/clip.mp4',
};

test('a scene seeds the full chain and one element card per asset', () => {
  const seeded = seedScene(shot, { enhanceSystem: 'TIGHTEN', names: { michael: 'Michael' } });
  const kinds = seeded.nodes.map(n => n.data.kind);
  assert.deepEqual(kinds.slice(0, 5), ['prompt', 'system', 'enhance', 'image', 'video']);
  // written_prompt wins: Run must never enhance an already-enhanced prompt
  assert.equal(seeded.nodes[0].data.text, 'old draft');
  assert.equal(seeded.nodes[1].data.text, 'TIGHTEN');
  const elements = seeded.nodes.filter(n => n.data.kind === 'element');
  assert.deepEqual(elements.map(e => e.data.label), ['Element · Michael', 'Location · Studio Bedroom', 'Reference · Scouted frames']);
  assert.deepEqual(elements[0].data.urls, ['/characters/michael/photo/a.jpg', '/characters/michael/photo/b.jpg']);
  // every element feeds all three billed cards on the refs port
  assert.equal(seeded.edges.filter(e => e.targetHandle === 'refs').length, 9);
  assert.equal(seeded.nodes.find(n => n.data.kind === 'video').data.url, 'https://cdn.test/clip.mp4');
});

test('groupRefs keys by asset slug and buckets uploads and the web', () => {
  const groups = groupRefs(['/refs/x.jpg', '/props/motorcycle/photo/1.jpg', '/refs/y.jpg', 'https://a/b.jpg']);
  assert.deepEqual(groups.map(g => [g.refKind, g.urls.length]), [['upload', 2], ['prop', 1], ['web', 1]]);
});

test('round trip keeps positions, the multi-wire refs port and outputs', () => {
  const original = seedScene(shot);
  original.nodes[0].position = { x: 124, y: 988 };
  const encoded = toLegacy(original.nodes, original.edges, {}, { conceptId: 42, shotN: 2 });
  const enhance = encoded.graph.nodes.find(n => n.type === 'zpf/enhance');
  const refs = enhance.inputs.find(i => i.name === 'refs');
  assert.equal(refs.type, 'images');
  assert.equal(refs.links.length, 3);          // three element cards, one port
  assert.equal(refs.link, refs.links[0]);      // the single-link readers see the first
  assert.deepEqual(enhance.properties.ref_urls, shot.refs);   // the wires ARE the reference list
  const element = encoded.graph.nodes.find(n => n.type === 'zpf/reference_set');
  assert.deepEqual(element.properties.urls, ['/characters/michael/photo/a.jpg', '/characters/michael/photo/b.jpg']);
  assert.equal(element.properties.kind, 'character');
  const loaded = fromLegacy(encoded.graph, encoded.states);
  assert.deepEqual(loaded.nodes[0].position, { x: 124, y: 988 });
  assert.equal(loaded.edges.length, original.edges.length);
  assert.equal(loaded.nodes.find(n => n.data.kind === 'image').data.url, '/renders/frame.jpg');
  assert.equal(loaded.nodes.filter(n => n.data.kind === 'element').length, 3);
});

test('a graph without element cards still rides the frozen refs', () => {
  const nodes = [
    { id: 'p', type: 'studio', position: { x: 0, y: 0 }, data: { kind: 'prompt', label: 'Prompt', text: 'x' } },
    { id: 'i', type: 'studio', position: { x: 1, y: 0 }, data: { kind: 'image', label: 'Nano', refs: ['/refs/a.jpg'] } },
  ];
  const edges = [{ id: 'e', source: 'p', target: 'i', targetHandle: 'prompt' }];
  const encoded = toLegacy(nodes, edges);
  assert.deepEqual(encoded.graph.nodes[1].properties.ref_urls, ['/refs/a.jpg']);
});

test('an element dropped on the canvas wires into every refs port', () => {
  const seeded = seedScene({ n: 1, prompt: 'x', refs: [] });
  const el = { id: 'el', type: 'studio', position: { x: 0, y: 0 }, data: { kind: 'element', label: 'Element · Cyclops', refKind: 'character', urls: ['/characters/cyclops/photo/1.jpg'] } };
  const wires = wireElement(el, seeded.nodes);
  assert.deepEqual(wires.map(w => w.target).sort(), ['scene-enhance', 'scene-image', 'scene-video']);
});

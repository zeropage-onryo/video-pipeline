import { test } from 'node:test';
import assert from 'node:assert/strict';
import { seedScene, toLegacy, fromLegacy } from '../src/lib/director-graph.ts';

test('scene seed includes actual prompt, every reference, and paid outputs', () => {
  const seeded = seedScene({ n: 2, prompt: 'finished prompt', written_prompt: 'old draft', refs: ['/refs/face.jpg', 'https://cdn.test/bike.jpg'], reference_image: '/renders/frame.jpg', media_url: 'https://cdn.test/clip.mp4' });
  assert.equal(seeded.nodes[0].data.text, 'finished prompt');
  assert.equal(seeded.nodes.filter(n => n.data.kind === 'reference').length, 2);
  assert.equal(seeded.nodes.find(n => n.data.kind === 'video').data.url, 'https://cdn.test/clip.mp4');
  assert.equal(seeded.edges.filter(e => e.targetHandle === 'reference').length, 3);
});
test('round trip preserves layouts, multiple reference wires, and outputs', () => {
  const original = seedScene({ n: 1, prompt: 'scene', refs: ['/refs/a.jpg', '/refs/b.jpg'], reference_image: '/renders/image.jpg' });
  original.nodes[0].position = {x: 124, y: 988};
  const encoded = toLegacy(original.nodes, original.edges, {}, {conceptId: 42, shotN: 1});
  const loaded = fromLegacy(encoded.graph, encoded.states);
  assert.deepEqual(loaded.nodes[0].position, {x: 124,y: 988});
  assert.equal(loaded.edges.length, original.edges.length);
  assert.equal(loaded.nodes.find(n => n.data.kind === 'image').data.url, '/renders/image.jpg');
  assert.equal(encoded.graph.nodes[1].type, 'zpf/nano_banana');
  assert.equal(encoded.graph.nodes[1].properties.concept_id,42);
  assert.deepEqual(encoded.graph.nodes[1].properties.ref_urls,['/refs/a.jpg','/refs/b.jpg']);
  for(const edge of encoded.graph.links) {
    const target=encoded.graph.nodes.find(n => n.id===edge[3]);
    assert.equal(target.inputs[edge[4]].link,edge[0]);
  }
});
test('legacy enhancement graph keeps instructions, cached text, input slots and properties', () => {
  const graph={nodes:[{id:10,type:'zpf/system_prompt',properties:{text:'Keep reference locks'},pos:[20,100]},{id:20,type:'zpf/user_prompt',properties:{text:'Original',concept_id:9},pos:[20,350]},{id:30,type:'zpf/enhance',properties:{auto_ground:true,ref_urls:['/refs/face.jpg']},inputs:[{name:'system',link:1},{name:'user',link:2}],pos:[500,100]}],links:[[1,10,0,30,0,'text'],[2,20,0,30,1,'text']]};
  const converted=fromLegacy(graph,{'30':{status:'done',kind:'text',output:'Enhanced, paid output'}});
  assert.equal(converted.nodes[2].data.text,'Enhanced, paid output');
  const saved=toLegacy(converted.nodes,converted.edges,graph);
  assert.equal(saved.graph.nodes[2].properties.auto_ground,true);
  assert.equal(saved.graph.nodes[2].inputs[0].name,'system');
  assert.equal(saved.graph.nodes[2].inputs[1].name,'user');
  assert.equal(saved.states['3'].output,'Enhanced, paid output');
});
test('unrecognized legacy nodes fail closed instead of deleting work', () => {
  assert.throws(()=>fromLegacy({nodes:[{id:1,type:'future/special'}],links:[]}),/legacy Director/);
});
test('pending job id survives scene graph save and reload', () => {
  const original=seedScene({n:1,prompt:'scene'});
  original.nodes[1].data.jobId=88;
  original.nodes[1].data.busy=true;
  const saved=toLegacy(original.nodes,original.edges);
  const restored=fromLegacy(saved.graph,saved.states);
  assert.equal(restored.nodes[1].data.jobId,88);
  assert.equal(restored.nodes[1].data.busy,true);
});

test('legacy edits invalidate React metadata instead of restoring deleted wires', () => {
  const original=seedScene({n:1,prompt:'scene',refs:['/refs/a.jpg']});
  const saved=toLegacy(original.nodes,original.edges);
  saved.graph.links=[];
  assert.equal(fromLegacy(saved.graph,saved.states).edges.length,0);
});
test('legacy image fallback remains available as a reference', () => {
  const loaded=fromLegacy({nodes:[{id:1,type:'zpf/nano_banana',properties:{image_url:'/refs/face.jpg'}}]});
  assert.deepEqual(loaded.nodes[0].data.refs,['/refs/face.jpg']);
});

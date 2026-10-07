import { test } from 'node:test';
import assert from 'node:assert/strict';
import { flowsTarget, pipelineTarget } from '../src/lib/legacy-routes.ts';

test('the Pipeline tab lands on the Projects board, keeping a named scene', () => {
  assert.equal(pipelineTarget({}), '/studio/projects');
  assert.equal(pipelineTarget({ concept: '375' }), '/studio/scene/375');
  assert.equal(pipelineTarget({ concept: '375; drop' }), '/studio/projects');
});

test('a Director link opens that scene at its shot, the draft, or the board', () => {
  assert.equal(flowsTarget({ concept: '42', shot: '2' }), '/studio/scene/42?shot=2');
  assert.equal(flowsTarget({ concept: '42' }), '/studio/scene/42');
  assert.equal(flowsTarget({ concept: '42', shot: 'x' }), '/studio/scene/42');
  assert.equal(flowsTarget({ draft: '1' }), '/studio/scene/draft');
  assert.equal(flowsTarget({ draft: '' }), '/studio/scene/draft');
  assert.equal(flowsTarget({}), '/studio/projects');
  assert.equal(flowsTarget({ concept: '../x' }), '/studio/projects');
});

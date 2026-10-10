import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  SKILL_TOOL, humanise, skillTitle, lookedOf, lookedLine, skillCommands, skillOfCommand,
} from '../src/lib/skills.ts';

const SHELF = [
  { name: 'character-sheet', title: 'Character sheet', summary: 'save a person as a character', output: 'image' },
  { name: 'multi-shot', title: 'Multi-shot scene', summary: 'a scene cut into timed shots', output: 'video' },
];

test('a skill is titled off the shelf, and off its name when the shelf has not loaded', () => {
  assert.equal(skillTitle('multi-shot', SHELF), 'Multi-shot scene');
  assert.equal(skillTitle(' Multi-Shot ', SHELF), 'Multi-shot scene');
  assert.equal(skillTitle('mood-board', []), 'Mood board');
  assert.equal(humanise('product_still'), 'Product still');
  assert.equal(humanise(''), '');
});

test('what an answer used: each tool once, a skill by its title, nothing that failed', () => {
  const runs = [
    { tool: SKILL_TOOL, args: { name: 'multi-shot' }, ok: true },
    { tool: 'board', args: {}, ok: true },
    { tool: 'board', args: { brand: 'x' }, ok: true },
    { tool: 'find_references', args: {}, ok: false },
    { tool: SKILL_TOOL, args: {}, ok: true },
  ];
  assert.deepEqual(lookedOf(runs, SHELF), ['skill:Multi-shot scene', 'board']);
  assert.deepEqual(lookedOf(undefined, SHELF), []);
  assert.deepEqual(lookedOf(null, SHELF), []);
});

test('the caption says the skill first, and is what it always was without one', () => {
  assert.equal(lookedLine(['board', 'stats']), 'looked at board, stats');
  assert.equal(lookedLine(['list_effects']), 'looked at the effects');
  assert.equal(lookedLine(['skill:Multi-shot scene']), 'used the Multi-shot scene skill');
  assert.equal(lookedLine(['skill:Mood board', 'find_references']),
    'used the Mood board skill · looked at find_references');
  assert.equal(lookedLine(['skill:Mood board', 'skill:Product still']),
    'used the Mood board + Product still skills');
  // a thread saved before skills had titles never shows the raw tool name
  assert.equal(lookedLine([SKILL_TOOL]), '');
  assert.equal(lookedLine(undefined), '');
});

test('the shelf becomes slash commands, and a command finds its skill back', () => {
  const commands = skillCommands(SHELF);
  assert.deepEqual(commands.map((c) => c.cmd), ['character-sheet', 'multi-shot']);
  assert.ok(commands.every((c) => c.group === 'skill' && c.id.startsWith('skill:') && c.hint));
  assert.equal(skillOfCommand('skill:multi-shot', SHELF)?.output, 'video');
  assert.equal(skillOfCommand('preset:orbit', SHELF), undefined);
  assert.equal(skillOfCommand('skill:nope', SHELF), undefined);
});

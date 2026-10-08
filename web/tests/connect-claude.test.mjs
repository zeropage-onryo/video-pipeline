import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CLAUDE_CONNECTORS_URL, MANUAL_STEPS, connectPlan, connectedLine, since } from '../src/lib/connect-claude.ts';

const URL = 'https://zeropage-studio.fly.dev/mcp';
const LISTING = 'https://claude.ai/directory/connectors/zeropage-studio';

test('no address from the server is off: nothing to copy, no steps', () => {
  assert.deepEqual(connectPlan(null), { mode: 'off' });
  assert.deepEqual(connectPlan({}), { mode: 'off' });
  assert.deepEqual(connectPlan({ mcp_url: null, claude_directory_url: LISTING }), { mode: 'off' });
});

test('an address with no listing is the manual steps', () => {
  assert.deepEqual(connectPlan({ mcp_url: URL, claude_directory_url: null }), { mode: 'manual', url: URL });
  assert.equal(MANUAL_STEPS.length, 3);
});

test('a listing collapses the steps to one button and keeps the address', () => {
  assert.deepEqual(connectPlan({ mcp_url: URL, claude_directory_url: LISTING }),
    { mode: 'directory', url: URL, listing: LISTING });
});

test('the connectors page is the one claude.ai documents', () => {
  assert.equal(CLAUDE_CONNECTORS_URL, 'https://claude.ai/customize/connectors');
});

const NOW = Date.parse('2026-10-08T12:00:00Z');
const ago = (minutes) => new Date(NOW - minutes * 60_000).toISOString();

test('since is coarse, and says nothing for a missing time', () => {
  assert.equal(since(ago(3), NOW), 'just now');
  assert.equal(since(ago(25), NOW), '25 minutes ago');
  assert.equal(since(ago(61), NOW), 'an hour ago');
  assert.equal(since(ago(60 * 5), NOW), '5 hours ago');
  assert.equal(since(ago(60 * 30), NOW), 'yesterday');
  assert.equal(since(ago(60 * 24 * 4), NOW), '4 days ago');
  assert.equal(since(null, NOW), '');
  assert.equal(since('not a date', NOW), '');
});

test('the status line names the client and the last use, and is null when not connected', () => {
  assert.equal(connectedLine(null, NOW), null);
  assert.equal(connectedLine({ connected: false, approved_at: null, last_used_at: null, client_name: null }, NOW), null);
  assert.equal(connectedLine({ connected: true, approved_at: ago(600), last_used_at: ago(120), client_name: 'Claude' }, NOW),
    'Connected through Claude · last used 2 hours ago');
  assert.equal(connectedLine({ connected: true, approved_at: ago(30), last_used_at: null, client_name: 'Claude' }, NOW),
    'Connected through Claude · allowed 30 minutes ago, not used yet');
  // a connection made before the studio kept track: used, never seen approved
  assert.equal(connectedLine({ connected: true, approved_at: null, last_used_at: ago(2), client_name: null }, NOW),
    'Connected · last used just now');
});

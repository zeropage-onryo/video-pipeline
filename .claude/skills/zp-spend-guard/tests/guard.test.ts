import { expect, test } from 'claude-code/testing'

const bash = { stdout: 'ran', stderr: '' }

const denial = (r: { deny?: string; isError?: true; text?: string }) =>
  r.deny ?? (r.isError ? r.text : undefined)

test('a *_SPEND_OK export is refused', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: bash }))
  const r = await $.tool.call({ tool: 'Bash', command: 'FAL_SPEND_OK=1 venv/bin/python -m src.trigger --spark x' })
  expect(denial(r)).toMatch(/spend-guard/)
})

test('ZEROPAGE_RENDER=1 and a live autopilot run are refused', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: bash }))
  for (const command of [
    'ZEROPAGE_RENDER=1 venv/bin/python -c "from src import orchestrator; orchestrator.run(\'x\')"',
    'venv/bin/python -m src.autopilot run --approve',
    'venv/bin/python -m ops.stripe_setup --fly --live',
  ]) {
    const r = await $.tool.call({ tool: 'Bash', command })
    expect(denial(r)).toMatch(/spend-guard/)
  }
})

test('the documented account-flag pattern and a plain pytest pass through', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: bash }))
  for (const command of [
    'set -a && source .env && set +a && venv/bin/python -m src.accounts credits zeropage --on',
    'venv/bin/python -m pytest tests/ -q',
    'venv/bin/python -m src.autopilot plan',
    'venv/bin/ruff check .',
  ]) {
    const r = await $.tool.call({ tool: 'Bash', command })
    expect(denial(r)).toBeUndefined()
  }
})

test('pytest with .env sourced is refused', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: bash }))
  const r = await $.tool.call({ tool: 'Bash', command: 'set -a && source .env && set +a && venv/bin/python -m pytest tests/ -q' })
  expect(denial(r)).toMatch(/LIVE DATABASE_URL/)
})

test('# spend-ok lets an asked-for spend through', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: bash }))
  const r = await $.tool.call({ tool: 'Bash', command: 'FAL_SPEND_OK=1 venv/bin/python -m src.trigger # spend-ok' })
  expect(denial(r)).toBeUndefined()
})

test('.env is protected from Edit and Write, .env.example is not', async ($, on) => {
  on('tool.call', { tool: 'Edit' }, () => ({ result: { filePath: 'x', oldString: '', newString: '', originalFile: '', structuredPatch: [], userModified: false, replaceAll: false } }))
  on('tool.call', { tool: 'Write' }, () => ({ result: { type: 'create', filePath: 'x', content: '', structuredPatch: [] } }))
  const edit = await $.tool.call({ tool: 'Edit', file_path: '/repo/.env', old_string: 'a', new_string: 'b' })
  expect(denial(edit)).toMatch(/spend-guard/)
  const local = await $.tool.call({ tool: 'Write', file_path: '/repo/.env.local', content: 'X=1' })
  expect(denial(local)).toMatch(/spend-guard/)
  const example = await $.tool.call({ tool: 'Edit', file_path: '/repo/.env.example', old_string: 'a', new_string: 'b' })
  expect(denial(example)).toBeUndefined()
})

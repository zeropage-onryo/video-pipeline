import type { EngineInterface, Register } from 'claude-code'

// What the transcripts kept asking by hand: "stop the local servers", "is ollama
// still running", and the session-start traps the handoffs warn about (a stale
// .git/index.lock from a Cowork VM, another session's uncommitted work, stale
// worktrees under .claude/worktrees/).

type Server = { label: string; port: string; kill: string[][] }

const SERVERS: readonly Server[] = [
  { label: 'api:8000', port: '8000', kill: [['pkill', '-f', 'uvicorn app.main']] },
  { label: 'web:3000', port: '3000', kill: [['pkill', '-f', 'next dev'], ['pkill', '-f', 'next-server']] },
  { label: 'ollama', port: '11434', kill: [['pkill', '-f', 'ollama serve'], ['pkill', '-x', 'Ollama']] },
]

// A Bash command that may have started or stopped one of them.
const TOUCHES = /uvicorn|next dev|npm run dev|run dev|ollama|pkill|\bkill\b|studio\.command|dev\.command|serve\.sh|start-studio/

async function run($: EngineInterface, argv: string[], cwd?: string) {
  try {
    return await $.process.run(argv, { timeoutMs: 10_000, ...(cwd ? { cwd } : {}) })
  } catch {
    return null
  }
}

async function listening($: EngineInterface, port: string): Promise<boolean | null> {
  const r = await run($, ['lsof', '-nP', `-iTCP:${port}`, '-sTCP:LISTEN'])
  if (r === null) return null // no lsof here (a cloud container): unknown, say nothing
  return r.exitCode === 0 && r.stdout.trim() !== ''
}

async function up($: EngineInterface): Promise<string[] | null> {
  const found: string[] = []
  for (const s of SERVERS) {
    const on = await listening($, s.port)
    if (on === null) return null
    if (on) found.push(s.label)
  }
  return found
}

async function refresh($: EngineInterface) {
  const found = await up($)
  if (found === null) return
  $.ui.status(found.length ? `local: ${found.join(' · ')}` : undefined)
}

async function checkRepo($: EngineInterface, cwd: string) {
  const notes: string[] = []
  const status = await run($, ['git', 'status', '--porcelain'], cwd)
  if (status && status.exitCode === 0) {
    const n = status.stdout.split('\n').filter(l => l.trim()).length
    if (n > 0) notes.push(`${n} uncommitted path${n === 1 ? '' : 's'} (another session's?)`)
  }
  const lock = await run($, ['test', '-e', '.git/index.lock'], cwd)
  if (lock && lock.exitCode === 0) notes.push('stale .git/index.lock -- rm it before any git command')
  const trees = await run($, ['git', 'worktree', 'list', '--porcelain'], cwd)
  if (trees && trees.exitCode === 0) {
    const stale = trees.stdout.split('\n').filter(l => l.startsWith('worktree ') && l.includes('.claude/worktrees/')).length
    if (stale > 0) notes.push(`${stale} worktree${stale === 1 ? '' : 's'} under .claude/worktrees/`)
  }
  if (notes.length) $.ui.toast(`zp-ops: ${notes.join(' · ')}`, { timeoutMs: 12_000 })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.command.register({
      name: 'servers',
      description: 'Local dev servers on :8000 / :3000 / ollama; `/servers stop` stops them',
      argumentHint: '[stop]',
    })
    if (e.isInteractive) {
      void checkRepo($, e.cwd)
      void refresh($)
    }
    return started
  })

  on('command.run', { command: 'servers' }, async ($, e) => {
    if (e.args.trim() === 'stop') {
      const before = await up($)
      for (const s of SERVERS) for (const argv of s.kill) await run($, argv)
      await refresh($)
      const after = await up($)
      const stopped = (before ?? []).filter(l => !(after ?? []).includes(l))
      return { text: stopped.length ? `Stopped: ${stopped.join(', ')}.` : 'Nothing was running.' }
    }
    const found = await up($)
    if (found === null) return { text: 'zp-ops: cannot check ports here (no lsof).' }
    await refresh($)
    return { text: found.length ? `Up: ${found.join(', ')}. \`/servers stop\` stops them.` : 'No local servers running.' }
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (TOUCHES.test(e.command)) void refresh($)
    return ran
  })
}

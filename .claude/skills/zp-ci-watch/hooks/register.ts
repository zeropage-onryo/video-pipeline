import type { EngineInterface, Register } from 'claude-code'

// Every push in the transcripts was followed by a wait for CI (6-7 minutes of
// tests) and a Fly deploy on main, and more than once by a `sleep 90` chain the
// harness refused. This watches `gh run list` for the pushed commit instead.

type Run = { name: string; status: string; conclusion: string | null; headSha: string }

const POLL_MS = 30_000
const GIVE_UP_MS = 25 * 60_000
const PUSH = /\bgit\s+push\b/
const MERGE = /\bgh\s+pr\s+merge\b/

const ok = (c: string | null) => c === 'success' || c === 'skipped' || c === 'neutral'
const mark = (r: Run) =>
  r.status !== 'completed' ? '…' : ok(r.conclusion) ? '✓' : '✗'

async function sh($: EngineInterface, argv: string[]): Promise<string | null> {
  try {
    const r = await $.process.run(argv, { timeoutMs: 20_000 })
    return r.exitCode === 0 ? r.stdout : null
  } catch {
    return null
  }
}

async function runsFor($: EngineInterface, branch: string, sha: string): Promise<Run[] | null> {
  const out = await sh($, [
    'gh', 'run', 'list', '--branch', branch, '--limit', '12',
    '--json', 'name,status,conclusion,headSha',
  ])
  if (out === null) return null
  try {
    const all = JSON.parse(out) as Run[]
    return all.filter(r => r.headSha === sha)
  } catch {
    return null
  }
}

function line(runs: Run[]): string {
  return runs.map(r => `${r.name} ${mark(r)}`).join(' · ')
}

let timer: { cancel: () => void } | null = null

function stop() {
  timer?.cancel()
  timer = null
}

async function watch($: EngineInterface, branchArg?: string) {
  stop()
  const branch = branchArg ?? (await sh($, ['git', 'rev-parse', '--abbrev-ref', 'HEAD']))?.trim()
  const sha =
    branchArg === undefined
      ? (await sh($, ['git', 'rev-parse', 'HEAD']))?.trim()
      : (await sh($, ['git', 'rev-parse', `origin/${branchArg}`]))?.trim()
  if (!branch || !sha) return
  if ((await sh($, ['gh', '--version'])) === null) return // no gh here: nothing to watch

  const startedAt = await $.clock.now()
  $.ui.status(`CI ${branch}: waiting for runs on ${sha.slice(0, 7)}`)

  timer = $.clock.every(POLL_MS, () => {
    void (async () => {
      const runs = await runsFor($, branch, sha)
      if (runs === null) {
        stop()
        $.ui.status(undefined)
        return
      }
      if (runs.length === 0) {
        if ((await $.clock.now()) - startedAt > GIVE_UP_MS) {
          stop()
          $.ui.status(undefined)
        }
        return
      }
      $.ui.status(`CI ${branch}: ${line(runs)}`)
      if (runs.every(r => r.status === 'completed')) {
        stop()
        const red = runs.filter(r => !ok(r.conclusion)).map(r => r.name)
        $.ui.toast(
          red.length === 0 ? `CI green on ${branch}` : `CI RED on ${branch}: ${red.join(', ')}`,
          { timeoutMs: 15_000 },
        )
      } else if ((await $.clock.now()) - startedAt > GIVE_UP_MS) {
        stop()
        $.ui.status(`CI ${branch}: still running after 25 min, stopped watching`)
      }
    })()
  })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'ci',
      description: 'GitHub Actions on this branch\'s HEAD, once; `/ci main` for main',
      argumentHint: '[branch]',
    })
    return next(e)
  })

  on('command.run', { command: 'ci' }, async ($, e) => {
    const branchArg = e.args.trim() || undefined
    const branch = branchArg ?? (await sh($, ['git', 'rev-parse', '--abbrev-ref', 'HEAD']))?.trim()
    const sha = (await sh($, ['git', 'rev-parse', branchArg ? `origin/${branchArg}` : 'HEAD']))?.trim()
    if (!branch || !sha) return { text: 'zp-ci-watch: not in a git checkout.' }
    const runs = await runsFor($, branch, sha)
    if (runs === null) return { text: 'zp-ci-watch: `gh run list` failed (is gh installed and signed in?).' }
    if (runs.length === 0) return { text: `No runs yet on ${branch} @ ${sha.slice(0, 7)}.` }
    return { text: `${branch} @ ${sha.slice(0, 7)}: ${line(runs)}` }
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError) return ran
    if (MERGE.test(e.command)) void watch($, 'main')
    else if (PUSH.test(e.command)) void watch($)
    return ran
  })
}

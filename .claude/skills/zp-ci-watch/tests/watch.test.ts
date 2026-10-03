import { expect, mock, test } from 'claude-code/testing'

const gh = (runs: object[]) => JSON.stringify(runs)

const out = (stdout: string, exitCode = 0) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

const typed = (command: string, args = '') => ({
  command,
  args,
  origin: { kind: 'composer' } as const,
  presentation: { isFullscreen: false, columns: 120 },
})

test('a git push starts polling gh for the pushed commit, and stops when every run completes', async ($, on) => {
  const clock = mock.clock(on)
  const calls: string[] = []
  let polls = 0
  on('process.run', ($, e) => {
    const argv = e.argv.join(' ')
    calls.push(argv)
    if (argv === 'git rev-parse --abbrev-ref HEAD') return out('claude/x\n')
    if (argv === 'git rev-parse HEAD') return out('abc123\n')
    if (argv === 'gh --version') return out('gh 2.0\n')
    if (argv.startsWith('gh run list')) {
      polls += 1
      const status = polls >= 2 ? 'completed' : 'in_progress'
      return out(
        gh([
          { name: 'CI', status, conclusion: status === 'completed' ? 'success' : null, headSha: 'abc123' },
          { name: 'CI', status: 'completed', conclusion: 'failure', headSha: 'older' },
        ]),
      )
    }
    return out('', 1)
  })
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: 'pushed', stderr: '' } }))

  await $.tool.call({ tool: 'Bash', command: 'git push -u origin claude/x' })
  await clock.settle()
  expect(calls).toContain('git rev-parse HEAD')

  await clock.advance(30_000)
  expect(polls).toBe(1)
  await clock.advance(30_000)
  expect(polls).toBe(2)
  await clock.advance(120_000)
  expect(polls).toBe(2) // stopped once the HEAD run completed
})

test('a command that is not a push starts nothing', async ($, on) => {
  const clock = mock.clock(on)
  const calls: string[] = []
  on('process.run', ($, e) => {
    calls.push(e.argv.join(' '))
    return out('', 1)
  })
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '' } }))
  await $.tool.call({ tool: 'Bash', command: 'git status' })
  await clock.advance(60_000)
  expect(calls).toEqual([])
})

test('/ci reports the runs on HEAD once', async ($, on) => {
  on('process.run', ($, e) => {
    const argv = e.argv.join(' ')
    if (argv === 'git rev-parse --abbrev-ref HEAD') return out('main\n')
    if (argv === 'git rev-parse HEAD') return out('def456\n')
    if (argv.startsWith('gh run list'))
      return out(gh([{ name: 'Fly Deploy', status: 'completed', conclusion: 'success', headSha: 'def456' }]))
    return out('', 1)
  })
  const { text } = await $.command.run(typed('ci'))
  expect(text).toMatch(/Fly Deploy ✓/)
})

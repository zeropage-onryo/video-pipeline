import { expect, test } from 'claude-code/testing'

const out = (stdout: string, exitCode = 0) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

const typed = (command: string, args = '') => ({
  command,
  args,
  origin: { kind: 'composer' } as const,
  presentation: { isFullscreen: false, columns: 120 },
})

test('/servers lists what is listening and /servers stop kills it', async ($, on) => {
  let apiUp = true
  const killed: string[] = []
  on('process.run', ($, e) => {
    const argv = e.argv.join(' ')
    if (argv.startsWith('lsof ')) {
      const isApi = argv.includes(':8000')
      return isApi && apiUp ? out('uvicorn 1 iphone\n') : out('', 1)
    }
    if (argv.startsWith('pkill ')) {
      killed.push(argv)
      if (argv.includes('uvicorn')) apiUp = false
      return out('')
    }
    return out('', 1)
  })
  const listed = await $.command.run(typed('servers'))
  expect(listed.text).toMatch(/Up: api:8000/)
  const stopped = await $.command.run(typed('servers', 'stop'))
  expect(stopped.text).toMatch(/Stopped: api:8000/)
  expect(killed.some(k => k.includes('uvicorn app.main'))).toBe(true)
})

test('without lsof the command says so instead of failing', async ($, on) => {
  on('process.run', () => {
    throw new Error('spawn lsof ENOENT')
  })
  const { text } = await $.command.run(typed('servers'))
  expect(text).toMatch(/cannot check ports/)
})

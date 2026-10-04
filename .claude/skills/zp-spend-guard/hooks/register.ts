import type { Register } from 'claude-code'

// Every switch in this repo that turns a dry run into money or a post. CLAUDE.md:
// "the click is the approval" -- a person presses Approve in the Queue, or exports
// a *_SPEND_OK on purpose. A session arming one of these in a Bash command is the
// exact "approval that's always on" the gates were written to prevent.
const ARMS: readonly [RegExp, string][] = [
  [/\b[A-Z0-9_]*_SPEND_OK=1\b/, 'arms a *_SPEND_OK render approval'],
  [/\bZEROPAGE_RENDER=1\b/, 'turns the graph render from a dry stub into real spend'],
  [/\bZEROPAGE_AUTOPILOT=1\b/, 'arms the L4 autopilot'],
  [/\bZEROPAGE_POST_OK=1\b/, 'arms posting'],
  [/\bsrc\.autopilot\s+run\b[^\n]*--approve/, 'runs the autopilot live'],
  [/\bsrc\.scheduling\s+run\b[^\n]*--live/, 'publishes the scheduled queue live'],
  [/\b(ops\.stripe_setup|ops\/stripe_setup\.py)\b[^\n]*--live/, 'switches Stripe to live mode'],
]

// 2026-09-28 "Stop local tests from reaching the live database": the pattern that
// did it was `set -a && source .env && set +a` followed by pytest in one line.
const LIVE_DB_TESTS = /source\s+\.env\b[\s\S]*\bpytest\b|\bpytest\b[\s\S]*source\s+\.env\b/

// .env, .env.local, .env.bak.* -- never .env.example, which is checked in.
const ENV_FILE = /(^|\/)\.env(\.(?!example$)[^/]*)?$/

// The override, for the one case the person DID ask for the spend this session:
// `# spend-ok` at the end of the command. The deny text says when it is allowed.
const OVERRIDE = /#\s*spend-ok\b/

export const register: Register = on => {
  on('tool.call', { tool: 'Bash' }, ($, e, next) => {
    const cmd = e.command
    if (OVERRIDE.test(cmd)) return next(e)

    const hit = ARMS.find(([re]) => re.test(cmd))
    if (hit) {
      $.ui.toast(`spend-guard refused a command that ${hit[1]}`)
      $.ui.status(`spend-guard: refused (${hit[1]})`)
      return {
        deny:
          `zp-spend-guard: this command ${hit[1]}. The click in the Queue is the approval; ` +
          `a session must not arm it. If Mike asked for exactly this spend in his own words ` +
          `this session, re-run with \`# spend-ok\` at the end of the command and say so.`,
      }
    }

    if (LIVE_DB_TESTS.test(cmd)) {
      $.ui.toast('spend-guard: pytest with .env sourced -- refused (live DATABASE_URL)')
      return {
        deny:
          'zp-spend-guard: `source .env` and `pytest` in one command points the test suite at the ' +
          'LIVE DATABASE_URL (2026-09-28, docs/RUNBOOK.md). Run the tests without sourcing .env.',
      }
    }

    return next(e)
  })

  const protectEnv = (file: string) =>
    ENV_FILE.test(file)
      ? {
          deny:
            `zp-spend-guard: ${file} holds the live keys and tokens and is written only by the ` +
            `scripts that back it up first (ops.ig_tokens, ops.stripe_setup). Edit .env.example, ` +
            `or tell Mike the exact line to change.`,
        }
      : null

  on('tool.call', { tool: 'Edit' }, ($, e, next) => protectEnv(e.file_path) ?? next(e))
  on('tool.call', { tool: 'Write' }, ($, e, next) => protectEnv(e.file_path) ?? next(e))
}

# Claude Code mods for this repo

Written 2026-10-03 from the 64 cloud sessions on the account (2026-08-04 to
2026-10-03) and the 378 commits on `main`. Three mods are built and live under
`.claude/skills/zp-*`; the rest are suggestions with the reason each one
earns its place.

## How the sessions actually go

- **One long brief opens a session, then the follow-ups are three words.** The
  opening message is a pasted handoff ("Read CLAUDE.md first... work in your own
  worktree... never touch Mike's main checkout"), and everything after it is
  `merge #73`, `go again`, `just commit and push it for me`, `open the pull
  request for me`, `stop the local servers`, `i think we're done here`. Four
  sessions came from the iPhone outright and several more are titled
  `iphone-*`. The follow-ups are commands; they should be slash commands.
- **Every push is followed by a wait.** The suite is 3063 tests in 7m42s, CI is
  6-7 minutes, and `main` deploys to Fly and Vercel on its own. More than once a
  session reached for `sleep 90` chains to find out, and the harness refused.
- **Spend is the thing that must never happen by accident.** The whole
  architecture is "the click is the approval" (`*_SPEND_OK`, `ZEROPAGE_RENDER`,
  the Queue's priced approve). The overnight briefs repeat "no renders, no
  generation, no paid calls" by hand every time.
- **Sessions trip over what the previous session left.** A stale
  `.git/index.lock` from a Cowork VM, another session's uncommitted work on the
  main checkout, worktrees under `.claude/worktrees/` nobody pruned
  (`docs/BRANCHES.md` was written because of exactly this), the 2026-09-28
  test run that reached the live database through a sourced `.env`.
- **Local servers get left running.** "is ollama and docker still running in
  the background", "stop ollama too", "stop the local servers" are their own
  sessions and turns.
- **Handoffs are documents.** `docs/tasks/HANDOFF-*.md` and
  `docs/tasks/task-*.md` are how work moves between Cowork, Claude Code and
  the phone. They have a stable shape (state right now / what was verified /
  what is next / Mike's calls).

## Built (2026-10-03)

Each is a plugin folder under `.claude/skills/` (manifest in `.claude-plugin/`,
hooks module in `hooks/`, prompt commands in `commands/`, tests in `tests/`).
`claude plugin validate <folder>` and `claude plugin test <folder>` are the
checks; all three pass on 2.1.288, and the spend guard was exercised end to end
in a headless run (`claude -p --plugin-dir .claude/skills/zp-spend-guard`), where
it refused `FAL_SPEND_OK=1 ...` with its message.

**Loading them.** The engine's reference says a plugin in the project's
`.claude/skills/<name>` loads on its own in an interactive session; that could
not be verified from the cloud container (a headless `claude -p` from the repo
root did not load them). The way that is verified to work is naming the folders
once, in `~/.claude/settings.json` on the Mac:

```json
{
  "env": {
    "CLAUDE_CODE_PLUGIN_DIRS": "/Users/iphone/Documents/PRODUCTION PIPLINE .GIT/.claude/skills/zp-spend-guard:/Users/iphone/Documents/PRODUCTION PIPLINE .GIT/.claude/skills/zp-ops:/Users/iphone/Documents/PRODUCTION PIPLINE .GIT/.claude/skills/zp-ci-watch"
  }
}
```

(or `claude --plugin-dir <folder>` per mod, for one session). An interactive
session watches the folders, so an edit to a `register.ts` reloads it in place.
`/help` lists `/ship`, `/merge`, `/wrap`, `/handoff`, `/servers` and `/ci` once
they are in.

### `zp-spend-guard` -- the gate a session cannot click

Refuses, before anything runs:

- a Bash command that arms `*_SPEND_OK=1`, `ZEROPAGE_RENDER=1`,
  `ZEROPAGE_AUTOPILOT=1`, `ZEROPAGE_POST_OK=1`, `src.autopilot run --approve`,
  `src.scheduling run --live`, or `ops.stripe_setup --live`;
- `source .env` and `pytest` in one command (the live-database run);
- an Edit or Write to `.env` / `.env.*` (never `.env.example`).

The refusal tells the model why and names the one override: `# spend-ok` at
the end of the command, for a spend Mike asked for in his own words this
session. The documented account-flag pattern (`set -a && source .env && set
+a && python -m src.accounts ...`) passes untouched.

### `zp-ops` -- the three-word asks, and the leftovers

Slash commands, each a prompt in the repo's own conventions:

| command | what it does |
|---|---|
| `/ship [subject]` | ruff + pytest, conventional commit, `push -u`, open the PR, reply in one line |
| `/merge [#]` | checks CI, merges with a merge commit, deletes the branch, says whether Fly or Vercel is deploying |
| `/wrap` | "we're done here": nothing unpushed, stop the dev servers, prune the worktree, one-paragraph reply |
| `/handoff <topic>` | writes `docs/tasks/HANDOFF-<topic>-<date>.md` in the house shape |
| `/servers [stop]` | what is listening on :8000 / :3000 / ollama; `stop` kills them |

And two things that run on their own: at session start a toast naming
uncommitted paths, a stale `.git/index.lock`, and worktrees under
`.claude/worktrees/`; and a status-line entry `local: api:8000 · web:3000`
while a dev server is up, refreshed after any Bash command that could have
started or stopped one. On a machine without `lsof` it says so and stays
quiet.

### `zp-ci-watch` -- the wait after a push

After a `git push` (or `gh pr merge`, which watches `main`), polls `gh run
list` for the pushed commit every 30 s, shows `CI claude/x: CI … · Fly Deploy
✓` in the status line, and toasts `CI green on ...` or `CI RED on ...: test`
when every run has finished. Gives up after 25 minutes. `/ci [branch]` asks
once. No `gh` on the machine means it does nothing.

## Suggested, not built

- **A `prompt.compose` trim for CLAUDE.md.** CLAUDE.md is ~62 KB and loads
  into every session, including a "stop ollama" one. A mod cannot shrink it
  honestly; the fix is editorial: move the dated history blocks into
  `docs/ARCHITECTURE.md` and keep CLAUDE.md to the rules and the commands.
  Listed here because it is the single largest per-session cost in the logs.
- **A "red on main" band.** When `gh run list --branch main` shows a failed
  run, draw one line above the prompt until it is green, so a branch is not
  cut off a broken trunk (2026-09-02's week of drift started that way).
- **A worktree-aware `/branch <name>`.** Creates `.claude/worktrees/<name>`
  off `origin/main`, the way every brief asks, and records it in
  `docs/BRANCHES.md`'s table.
- **A spend ledger in the status line.** `GET /api/costs` already answers
  today's spend against the caps; a status entry `today: $0.84 · fal 3/6`
  during a session that renders would make the daily cap visible before it
  is hit.
- **An iPhone posture.** The phone sessions are short and the replies long.
  A `prompt.submit` hook that appends "reply in under 60 words" when the
  origin is the bridge would match how those turns are read.

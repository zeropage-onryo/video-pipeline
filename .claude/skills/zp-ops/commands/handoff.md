---
description: Write docs/tasks/HANDOFF-<topic>-<date>.md for the next session (the Cowork -> Claude Code shape)
argument-hint: <topic>
---
Write a handoff for the next session, as `docs/tasks/HANDOFF-$ARGUMENTS-<today>.md`, in the shape of `docs/tasks/HANDOFF-stripe-2026-09-30.md`:

- **State right now** -- what is merged, what is uncommitted and in which files, what is configured and what is not, any trap waiting (a stale `.git/index.lock`, a branch that must not be merged, a flag that is off on purpose).
- **What was verified** -- by running what, with the real numbers.
- **What is next** -- numbered, each item one branch + one PR, with the exact commands and files, and the rules for the run (no renders, no paid calls, tests + ruff before every push).
- **Mike's calls** -- the decisions that are his, each as one question with the options.

Commit it on this branch. Reply with the file path and a one-line summary.

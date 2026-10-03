---
description: "We're done here": check nothing is unpushed, stop local servers, prune this session's worktree
---
Wrap this session up:

1. `git status` and `git log origin/<branch>..HEAD`: anything uncommitted or unpushed gets committed and pushed now, or named in the reply if it is not this task's to commit.
2. Stop the local dev servers if this session started them: uvicorn on :8000, `next dev` on :3000. Leave Postgres alone. Say what was stopped.
3. If this session works in a worktree under `.claude/worktrees/` and its branch is merged, remove the worktree and `git worktree prune`.
4. Reply with ONE short paragraph: what landed (PR/commit), what is left open, and the one thing Mike has to do himself, if any.

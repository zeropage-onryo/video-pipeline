---
description: Merge this branch's PR once CI is green, delete the branch, prune the worktree
argument-hint: [PR number]
---
Merge the PR for this branch ($ARGUMENTS when given), the way this repo does it (docs/BRANCHES.md):

1. Confirm CI is green on the PR's head (`gh pr checks`). Red CI is work, not a reason to merge; fix and push first.
2. Merge with a merge commit (not squash, not rebase: the history is all merge commits), then delete the remote branch.
3. If this checkout is a worktree under `.claude/worktrees/`, say so and stop there; otherwise `git checkout main && git pull`.
4. `main` deploys on its own: the Fly Deploy workflow for the API and Vercel for `web/`. Say which of the two the merged diff touched (anything under `app/` or `src/` is the API; anything under `web/` is Vercel) so Mike knows what to wait for.
5. Reply with ONE line: merged commit, branch deleted or not, and what is deploying.

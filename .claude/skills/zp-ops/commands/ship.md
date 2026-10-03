---
description: Lint, test, commit, push -u, open the PR; one-line report
argument-hint: [commit subject]
---
Ship the work on this branch, the way this repo does it:

1. Run `venv/bin/ruff check .` and `venv/bin/python -m pytest tests/ -q` (the suite takes about seven minutes; run it in the background and keep going with step 2's prep). If either fails, fix it first; never skip or quarantine a test.
2. Commit everything that belongs to this task with a conventional subject (`feat(scope): ...`, `fix(scope): ...`, the shape in `git log`), $ARGUMENTS as the subject when given. No model identifiers anywhere in the message.
3. `git push -u origin <branch>`; if the branch has no PR yet, open one against `main` with a body that says what changed and what was verified (tests, ruff, anything clicked).
4. Reply with ONE line: the PR URL, the commit hash, and whether the tests were green. Nothing else.

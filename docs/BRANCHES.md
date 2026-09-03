# Branches — the trunk is `main`, and what else is alive

Written 2026-09-02, when a week of work (34 commits: account tenancy, the
research node, both pilot dry runs, the tenancy-gap fixes, RAG provenance)
finally merged into `main` as `81d029f` and was pushed. Before that, ~24
`claude/*` branches had merged each other and sessions were branching off
whatever they happened to land on — which is how two independent pilot dry
runs happened on the same day. Update this file when a branch below is
merged or deleted.

## The policy from here

- **`main` is the trunk.** Branch from it, merge back into it, push it.
  `origin/main` is the backup; nothing else is pushed by default.
- **One branch per task, short-lived, merged by the session that opened it**
  (or by the next one, on purpose — see `docs/tasks/task-merge-to-main.md`
  for what a week of drift costs).
- **A branch that is kept unmerged has to be able to say what is on it in one
  line.** If it cannot, it is dead weight — delete it and say what dies.
- Worktrees under `.claude/worktrees/` are per-session scratch. Remove them
  when the session is done; `git worktree prune` afterwards.
- The repo is **public** (`github.com/zeropage-onryo/video-pipeline`). A push
  publishes. Nothing secret has ever been committed on any ref — only
  `.env.example` — and `.env*` is gitignored; keep it that way.

## Kept (2026-09-02)

| branch | why it is alive |
|---|---|
| `main` | the trunk, at the merge of `claude/pilot-merged` |
| `claude/pilot-dry-run` | the main checkout's branch; fully merged, but that checkout holds another session's uncommitted work (imagesearch/framebank/pinterest bank, prompt edits). Switch it to `main` once that is committed, then delete |
| `claude/pilot-merged` | fully merged; checked out in a locked cloud-bridge worktree (`data/_to_delete/merge`) that this machine cannot remove. Delete when that session is gone |
| `claude/devstudio-buttons-task-7e200f` | 3 commits (2026-08-31): honest Dev Studio counters, unpark the taught prompts, the pg17-on-5433 doc, a runway test fix. The Dev Studio buttons task, still in flight |
| `claude/render-queue-subscription` | 1 commit (2026-08-31): render the queue on credits already paid for — 392 lines, unreviewed |
| `claude/evals-removal-workflows-editor-538a10` | 3 commits (2026-08-25): Runway-parity canvas, Higgsfield Soul image node, close-up polish — 1.5k lines of canvas UI never merged; decide whether the Director canvas still wants it |
| `claude/director-canvas-dark-theme-2c3b4c` | 1 commit (2026-08-26): "standalone scenes replace the multi-shot concept" — 1.6k lines; the scenes idea shipped another way (`scenes-pick-on-concepts`), so this is probably superseded, but nobody has checked |
| `claude/loving-meninsky-28d27f` | 2 commits (2026-08-26): rehome scene briefs and inspiration accounts after `/concepts` — probably superseded by the Dev Studio consolidation; unchecked |
| `claude/dev-public-postures-d6ec0a` | 1 commit (2026-08-25): editable eval knobs, `/library` file upload, metrics row — both features exist on `main` now via other commits; likely fully superseded |
| `claude/antihero-concept-grounding-61ebda` | 2 commits (2026-08-24/25): ground Antihero concepts in references + assets, retire the `ensure_locations` gate |
| `claude/priceless-benz-c449b6` | 3 commits (2026-08-25): Antihero stage two — the shot list grounds in the `{assets}` block. Shares its base with the branch above; the shot-list stage was later deleted (2026-08-26), so most of this cannot land as-is |

## Merged (2026-09-03)

- `claude/task-idea-agent-gaps-1-2f4d2d` — the four idea-agent gaps
  (`docs/tasks/task-idea-agent-gaps.md`): `shoot` on the MCP surface,
  `generate` grounded on the spark's bin from either door, the card carrying
  `origin` + the graph's `gate`, and `archive` naming the counted vocabulary.
  Fast-forwarded into `main` as `b01dab2`. Delete the branch once its
  worktree is removed.

## Deleted (2026-09-02)

All merged into `main` unless noted; nothing on them is lost.

- `claude/account-tenancy`, `claude/scenes-pick-on-concepts`,
  `studio-composer-merge`, `claude/pilot-dry-run-438a7b` (the tenancy-gap
  work), `claude/dev-studio-consolidate-c5f554`,
  `claude/pipeline-concept-generate-director-b410c9`,
  `claude/recursing-cohen-0f89d8`, `claude/cranky-villani-12dd21`,
  `claude/suspicious-lehmann-6f27e0`, `claude/mystifying-shirley-fc5df3`,
  `claude/strange-swartz-918f93`, `claude/dev-public-postures-3463df` — merged.
- `build/spine` — the old trunk name, merged long ago; the local branch is
  gone, `origin/build/spine` was left as it was.
- `claude/pilot-dry-run-19d26c` — the *other* pilot dry run of 2026-09-02.
  Unmerged in git terms; its report was folded into `docs/PILOT_DRY_RUN.md`
  and its test fix is on `main` in a newer shape (`03b5fef`). Nothing dies.
- Ten worktrees under `.claude/worktrees/` — all on merged or superseded
  branches. The only uncommitted edits in any of them (`recursing-cohen`,
  four test files from 2026-08-24) were older shapes of tests `main` has
  since rewritten.

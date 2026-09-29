# Task: Assemble v0 — the first slice of the ZPF editor

Read first: `docs/CUT_EDITOR.md` (the full design), `CLAUDE.md`, `src/timeline.py`, `src/providers.py`, `src/ledger.py`.

## Scope (this task only — phase 1 of section 6 in CUT_EDITOR.md)
Turn a project's approved Queue clips into one finished MP4. No timeline UI yet.

1. `src/cut/doc.py` — the timeline document (section 5.1): integer frames at project fps, tracks V/A(role voice|music|sfx)/T(captions), clips reference media as `gen:<id>` / `asset:<id>` handles, never URLs (resolve through the existing parser in `reference_urls` / `media.py`).
2. `src/cut/ops.py` + `src/cut/validate.py` — pure functions doc → doc for `insert, ripple_delete, trim, split, move, set_gain, duck, add_caption_track, add_marker, add_transition`. `validate(doc)` rejects overlaps on a track, src_out past media length, unknown handles, duration mismatch. Heavy unit tests here — this module is the safety rail for the agent later.
3. `timelines` table (Supabase, via the existing db layer): `id, project_id, account_id, version, parent_id, doc jsonb, author, op_summary, created_at`. Insert-only; rollback moves a pointer. Tenant-scoped per `account_scoping` rules.
4. `src/cut/assemble.py` — builds a v1 doc from a concept's approved clips in `timeline.py` part order, optional music bed on A2 ducked under voice, captions track if there's VO.
5. `src/cut/render.py` — compiles a doc to one ffmpeg `filter_complex` (trim/setpts → scale/pad → xfade; audio atrim → volume → sidechaincompress → amix → loudnorm -14 LUFS; captions burned via ASS). Writes MP4 to R2 through `storage.py`. No generative spend, so no ledger hold.
6. Route + button: `POST /api/cut/assemble` and an **Export** button on the Queue card that returns the MP4 link.

## Rules
- Branch from `origin/main` as `feat/cut-assemble-v0`. The local checkout has uncommitted work on `fix/mcp-as-discovery` — don't touch or stash it; use a worktree.
- Don't trigger any paid render or generation to test. Test with short local fixture clips (make them with ffmpeg `testsrc`/`sine`).
- Run the suite the way CI does (see `docs/RUNBOOK.md` / test posture notes).
- Stop and report before merging. Summarize what shipped, what's stubbed, and the test output.

## Out of scope for now
Footage index, agent edit jobs, /studio/cut UI, OTIO export, dubbing — later phases in CUT_EDITOR.md.

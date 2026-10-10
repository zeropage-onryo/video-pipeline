# Connecting the studio to Claude

Three commands and one paste. Everything below runs on THIS Mac.

## 1. Install the MCP package into the venv

```bash
cd "/Users/iphone/Documents/PRODUCTION PIPLINE .GIT"
venv/bin/pip install "mcp>=2"
```

## 2. Check the server actually starts

```bash
venv/bin/python -m src.mcp_server
```

(`--engine` in the config is harmless: the studio surface below ignores it.)

It should print nothing and sit there — that is correct. A stdio server
talks down a pipe, so silence *is* the healthy state. `Ctrl+C` to stop.

If it exits with a traceback instead, that is the thing to fix before
going any further; the desktop app will show you nothing useful.

## 3. Register it with Claude Desktop

The blocks live in `ops/claude-desktop-mcp.json`: `zeropage` (the studio:
images, video, effects, projects) and `zeropage-board` (the pre-production
board, plus the same studio tools). They go into `mcpServers` in
`~/Library/Application Support/Claude/claude_desktop_config.json`.

**The edit only sticks while the app is quit.** Claude Desktop reads
`mcpServers` when it starts and rewrites that file from memory while it
runs, so a block written under a running app is gone the next time the app
saves (seen twice on 2026-10-10: once after seven seconds, once after under
three minutes). So, from the repo folder, in Terminal — not in the app's
own terminal, which quits with it:

```bash
open -a Terminal ops/register-claude-desktop.command
```

It waits for you to quit Claude Desktop **completely** (⌘Q — closing the
window is not enough, and it ends every running session), writes a backup
of the config, adds the `zeropage` block, leaves every other key alone and
opens Claude again. The studio's tools appear under the connector icon.
For `zeropage-board` as well, run it in Terminal yourself with the flag
(`open` passes none): `ops/register-claude-desktop.command --board`.

By hand it is the same order: quit first, then paste the block(s) into
`mcpServers` beside any servers already there, then reopen.

### If a server shows "Server disconnected" right after a start

Claude Desktop launches each local server twice within a few seconds
and keeps the second. Until 2026-10-10 the two copies could deadlock
each other's table setup in Postgres and one of them died -- about half
of all starts. The server now takes a lock around that setup, so the
copies take turns instead.

Taking turns is slow against the live database. Measured 2026-10-10 from
this Mac: one copy's table setup takes about 15 seconds, so the copy
Desktop keeps answers after about 30 (it waits for the dropped copy to
finish first). With `zeropage` alone that worked on every start tried.
With `--board` as well there are four copies in the queue, about a
minute in all, which has not been tried and is probably longer than
Desktop waits -- so add `zeropage-board` only when you need the board
tools, and if it shows "Server disconnected", that is the likely reason.

If it still happens, the reason is in
`~/Library/Logs/Claude/mcp-server-zeropage.log` (or
`mcp-server-zeropage-board.log`): the last traceback there is the thing
to fix, and a line starting `note:` says when the lock could not be taken.

## Why stdio and not a tunnel

The desktop app launches this process itself and talks to it over a
pipe. No port, no bearer token on the public internet, nothing to leave
running, and nothing to restart when a tunnel hostname changes. The
desktop app also proxies its local MCP servers up to cloud sessions, so
the board is reachable from a phone through the same connection — the
tunnel was only ever buying the part the desktop already does.

`START_SERVER.md` still documents the HTTP mount. That is for the case
stdio cannot serve: something that is NOT Claude Desktop reaching this
pipeline over a network — the studio app's own agent, say. The token for
it is already in `.env`; `ZEROPAGE_MCP=1` turns the mount on.

## What it can and cannot do

Since 2026-10-07 the server Claude Desktop launches is the **studio
surface**: images, video and effects made with Claude, and nothing on the
pre-production board. Every image, clip, effect and element sheet is two
calls -- the first returns a quote in credits (with your balance before
and after) and spends nothing; only after you say yes does Claude call
again with that quote's `quote_token`. The token is signed for exactly
that request and works once: a changed model, length, prompt or option is
refused, and a repeated call returns the first job instead of charging
again. Approving needs `QUOTE_SIGNING_SECRET` set in `.env` (generate one
with the command in `src/pricing.py`'s `SIGNING_COMMAND`); without it the
quotes still answer and nothing can be approved.

| tool | what it does |
|---|---|
| `image_models` / `video_models` | the models, their options and prices |
| `effects` | image edits, Kling / PixVerse template effects, camera moves, and clip finishing: upscale / frame rate, added sound, re-framing a clip to a new shape (`reframe`, `reframe-hq`), removing a clip's background (`remove-video-background`, `remove-video-background-pro`) -- options and price rules |
| `elements` | your characters, props and places, with the photo `ref`s a render can use |
| `renders` | your recent renders as `gen:<id>` |
| `images_for` | web reference images, as `candidate:<id>` |
| `prompt_craft` | the studio's prompt-writing guides, for Claude to apply |
| `projects` / `project` | your projects; open one to get its brief, look, scenes, the reference images they used, its renders and its latest chat |
| `project_chat` | page back through a project's chat history |
| `create_project` | start a project (it shows on the studio's projects board) |
| `save_chat` | keep this conversation with a project, so it is there when the project is reopened -- here or in the studio |
| `generate_image` / `generate_video` / `apply_effect` | quoted, then (after your yes) run as a job; the result lands on the Assets wall, and in a project when given its `project_id` |
| `job` | poll a running render |
| `import_file` | bring an image (jpg, png, webp) or a clip (mp4, mov) from your Downloads or Desktop folder into the studio, by its full path -- it comes back as an `asset:<id>` you can use as a reference, an effect source or a clip to join. Reads nothing outside those folders |
| `edit_clip` | change something in a clip by instruction ("make the jacket red"). Two approvals: first ONE frame is edited as a still for a few credits, and its quote shows what the whole clip would cost on each model; after you have seen the frame, the clip is edited (Kling O1 by default, FLUX.3 as the cheap option). The clip edit only accepts the frame made for that clip and that instruction |
| `assemble_clips` | join 2-20 of your clips (`gen:<id>`) into one video -- hard cuts or crossfades, an optional music bed (`renders` with `kind=audio` lists your uploaded audio). Spends no credits; the result is a new clip on the Assets wall and an editable cut in the editor. Clips of different shapes are refused unless you ask for letterboxing |
| `cancel_job` | stop a render, effect or sheet this connector started. Not yet sent, or still waiting in fal's queue: nothing charged. Already rendering: fal is asked to stop; if it finishes anyway it is kept and charged at the quoted price, otherwise nothing is charged. Finished: too late. A sheet already being drawn finishes |

The board tools below are on the **board surface**: the `zeropage-board`
entry in `ops/claude-desktop-mcp.json` (`--surface board --engine`), which
the idea-agent skill needs. The research agent launches its own copy of it.

Board surface, always on, free:

| tool | what it does |
|---|---|
| `board` | what is on the pre-production board |
| `idea` | one concept in full, scene prompt included, plus `origin` (which door wrote it) and `gate` (the graph's prompt-gate verdict; null for a Studio Create row, which is never scored) |
| `search` | find a concept by any words in it |
| `capture` | put a new idea on the board |
| `pick` / `archive` | the two decisions, recorded as labels — `archive` takes a `reason` (weak concept · no turn · no stake · off-brand · unshootable · seen it), the only record of WHY |
| `shoot` | record that a concept actually got made, by any means — studio, Higgsfield, a camera |
| `add_spark` | hand the nightly run a direction |
| `tonight` | what direction the 03:30 run would take |
| `sparks` | the scout's bank |
| `images` | the reference photos behind a spark, with sources |
| `stats` | pick rate, shoot rate, board counts |

Behind `--engine` (spends model credit — cents):

| tool | what it does |
|---|---|
| `research` | a scout crawl: bank scored sparks, download their images |
| `generate` | one LangGraph pass, ending PARKED in the Queue — grounded on the images banked behind its spark (`reference`, or Studio uploads against it); takes a spark or a `finding_id` |
| `job` | poll either of the above, or a job /ui started |

**Nothing here renders.** `generate` ends AT the spend gate: the graph's
`generate_render` is a dry stub unless `ZEROPAGE_RENDER=1`, and if that
flag is set `generate` refuses to run at all rather than being the thing
that trips a live render. Approving in the Queue, on this machine, is
still the only way a clip gets bought.

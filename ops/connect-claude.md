# Connecting the board to Claude

Three commands and one paste. Everything below runs on THIS Mac.

## 1. Install the MCP package into the venv

```bash
cd "/Users/iphone/Documents/PRODUCTION PIPLINE .GIT"
venv/bin/pip install "mcp>=2"
```

## 2. Check the server actually starts

```bash
venv/bin/python -m src.mcp_server --engine
```

It should print nothing and sit there — that is correct. A stdio server
talks down a pipe, so silence *is* the healthy state. `Ctrl+C` to stop.

If it exits with a traceback instead, that is the thing to fix before
going any further; the desktop app will show you nothing useful.

## 3. Register it with Claude Desktop

Claude Desktop → Settings → Developer → Edit Config. That opens
`~/Library/Application Support/Claude/claude_desktop_config.json`.

Paste the `zeropage` block from `ops/claude-desktop-mcp.json` into
`mcpServers`. If the file already has other servers, add `zeropage`
alongside them rather than replacing the object.

Quit Claude Desktop **completely** (⌘Q — closing the window is not
enough) and reopen it. The board's tools appear under the connector
icon.

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

Always on, free:

| tool | what it does |
|---|---|
| `board` | what is on the pre-production board |
| `idea` | one concept in full, scene prompt included, plus `origin` (which door wrote it) and `gate` (the graph's prompt-gate verdict; null for a Studio Create row, which is never scored) |
| `search` | find a concept by any words in it |
| `capture` | put a new idea on the board |
| `pick` / `archive` | the two decisions, recorded as labels |
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

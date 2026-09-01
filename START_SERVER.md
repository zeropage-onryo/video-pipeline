# Starting the pipeline server (Studio + Dev Studio)

Both pages live on the same local server — **one process, one port**. There is never a reason
to start two.

## The three files

Double-click any of these in Finder, or run them from Terminal.

| File | What it does |
|---|---|
| `studio.command` | Opens **Studio** (the product surface) at http://localhost:8000/ui |
| `dev.command` | Opens **Dev Studio** (stats, grading, RAG library, settings) at http://localhost:8000/studio |
| `restart.command` | Stops the running server and starts it clean |

`studio.command` and `dev.command` both start the server **only if it isn't already running**,
wait for it to answer, then open their page. So double-clicking the second one while the first
is up just opens a tab — two tabs, one server, which is the whole point.

The Terminal window that starts the server *is* the server. Ctrl+C stops it; closing the window
stops it. Leave it open while you work.

## When to use restart.command

`--reload` picks up most edits on its own. It does **not** cover:

- a change to something imported at start-up
- a database file swapped underneath the running process (this is what made a newly created
  prop invisible on 2026-08-28 — the server kept serving its cached view of the old file)
- anything where the page looks right but behaves like the old code

`restart.command` only ever kills a uvicorn serving this project. If something else is holding
port 8000 it refuses and tells you, rather than killing a process you didn't mean to.

## Doing it by hand

```bash
cd "/Users/iphone/Documents/PRODUCTION PIPLINE .GIT"
venv/bin/uvicorn app.main:app --reload --timeout-graceful-shutdown 3
```

Set `ZPF_PORT` to use a port other than 8000; the launchers respect it.

The shared logic lives in `ops/serve.sh` — the three `.command` files are four lines each on
top of it. `start-studio.command` is the older version of the same idea, with the project path
typed into it; `studio.command` finds its own folder instead, so renaming or moving the
directory doesn't break it.

## Note

These have to be run from your own machine. My tools run on your computer but in their own
sandbox, so I can start a server there for testing — I can't start one in *your* Terminal, and
a server I start isn't the one your browser reaches.

## The MCP surface (reaching the board from Claude)

> **Connecting to Claude Desktop does not need any of this.** The desktop app
> launches the server itself over a pipe — no port, no token on the internet, no
> tunnel. That is three commands in `ops/connect-claude.md`, and it is the path
> you want. Everything below is for the *other* caller: something that is NOT
> Claude Desktop reaching this pipeline over a network — the studio app's own
> agent, say.

`src/mcp_server.py` exposes the idea board as an MCP server, so Claude — or any MCP
client, including your own agent — can read the board, capture ideas, pick and archive
concepts, and bank sparks for the nightly run, from anywhere. It is an adapter over
`preprod` and `scout`: no second store, no new schema, `data/pipeline.db` stays the one
source of truth.

**Nothing on it renders.** Picking a concept puts it in front of the Queue, and approving
in the Queue is still what calls Runway, still on this machine. The engine tools
(`research`, `generate`) are off unless you turn them on, and `generate` refuses outright
while `ZEROPAGE_RENDER=1`.

### Turn it on

Add to `.env`:

```bash
ZEROPAGE_MCP=1
ZEROPAGE_MCP_TOKEN=<paste a generated token>   # required; no token = no mount
```

Generate the token with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

`ZEROPAGE_MCP=1` with no token is **refused, not served open** — it prints a note and the
mount never happens. That default is deliberate: the only reason to mount MCP is to reach
it from off this machine, which means a tunnel, which means the endpoint is on the public
internet the moment it works.

Restart (`restart.command`) — this is a start-up import, so `--reload` will not pick it up.
The server prints one line when it works:

```
MCP mounted at /mcp (bearer auth, engine tools off, hosts 127.0.0.1,...)
```

### Reaching it from outside

The endpoint is `http://127.0.0.1:8000/mcp`, which is local-only. To reach it from a phone
or a cloud session it needs a public HTTPS URL:

```bash
brew install cloudflared
cloudflared tunnel --url http://127.0.0.1:8000
```

That prints a `https://<random>.trycloudflare.com` URL. Your MCP endpoint is that URL plus
`/mcp`.

**One setting you will need with a quick tunnel.** The MCP SDK refuses any request whose
`Host` header it does not recognise (DNS-rebinding protection), and a quick tunnel's
hostname is different on every restart — so every call comes back `421 Invalid Host
header`, which reads like a broken server rather than a setting. Add:

```bash
ZEROPAGE_MCP_HOSTS=*
```

That is safe *here specifically* because the bearer token is checked before the MCP app is
ever entered, and rebinding protection exists to stop a browser reaching a localhost
server — a browser cannot supply the token. With a **named** tunnel the hostname is stable,
so list it instead: `ZEROPAGE_MCP_HOSTS=zeropage.example.com`.

### Connect it to Claude

Settings → Connectors → Add custom connector:

- URL: `https://<your-tunnel>.trycloudflare.com/mcp`
- Header: `Authorization: Bearer <your token>`

### The engine tools

```bash
ZEROPAGE_MCP_ENGINE=1
```

Adds two tools that cost model credit (cents, not render dollars):

- `research` — a full scout pass: crawls the lanes, banks scored sparks, downloads the
  reference images behind them into `data/refs`
- `generate` — one pass through the LangGraph content graph: ground, generate, evaluate,
  score the prompt, keyframe if it clears the gate, and **park the scene in the Queue**

Both run as background jobs through `app/jobs.py` and return a job id — poll with the `job`
tool. They show up in the Queue rail on `/ui` like any other job, and the registry is
in-process, so a restart clears it.

`generate` ends **at** the spend gate, never through it: the graph's `generate_render` is a
dry stub unless `ZEROPAGE_RENDER=1`, and if that flag is set `generate` refuses to run at
all rather than being the thing that trips a live render.

### Checking it works

```bash
curl -s https://<your-tunnel>.trycloudflare.com/mcp \
  -H "Authorization: Bearer $ZEROPAGE_MCP_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Without the header that returns `401`. With it, the tool list.

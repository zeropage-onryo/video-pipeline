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

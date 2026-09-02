#!/bin/bash
# Zero Page Films — restart the pipeline server.
#
# For when --reload isn't enough: a change to something imported at start-up
# (or a database swapped underneath a running process) needs a clean boot.
# Stops only OUR uvicorn on the port, waits for it to let go, starts fresh.
source "$(cd "$(dirname "$0")" && pwd)/ops/serve.sh"

pids="$(server_pids)"
if [ -n "$pids" ]; then
    echo "Stopping the running server (pid $(echo "$pids" | tr '\n' ' ' | sed 's/ $//')) ..."
    # TERM first so uvicorn shuts down cleanly and finishes its writes.
    kill $pids 2>/dev/null
    if ! wait_for_port_free 15; then
        echo "It didn't stop on its own — forcing."
        kill -9 $pids 2>/dev/null
        wait_for_port_free 5 || {
            echo "Port $PORT is still held by something. Check: lsof -i tcp:$PORT" >&2
            exit 1
        }
    fi
    echo "Stopped."
elif server_up; then
    echo "Something is answering on port $PORT but it isn't this project's" >&2
    echo "server. Leaving it alone — check: lsof -i tcp:$PORT" >&2
    exit 1
else
    echo "Nothing was running."
fi

start_server

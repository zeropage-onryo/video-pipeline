#!/bin/bash
# Shared launcher logic for studio.command / dev.command / restart.command.
#
# Both pages -- /ui and /studio -- are served by ONE uvicorn process on one
# port. So the rule every launcher follows is: if something is already
# answering on the port, do NOT start a second server, just open the page.
# A second uvicorn would either lose the port race or, worse, win it and
# leave you looking at a different process than the one you think.

PORT="${ZPF_PORT:-8000}"

# TWO names for one server, and the difference is load-bearing.
#
# BASE is what goes in the browser. It MUST be localhost: Google OAuth
# builds its redirect_uri from the request host (app/auth.py's
# url_for("google_callback")), and only http://localhost:8000/... is in
# the authorised list in the Google console. Open the same server on
# 127.0.0.1 and sign-in dies with a redirect_uri mismatch. They are also
# separate cookie origins, so a session on one is not a session on the
# other -- which looks exactly like "the second page won't stay open".
#
# PROBE is what curl asks. It stays numeric because uvicorn binds
# 127.0.0.1 by default, and "localhost" can resolve to ::1 first and
# make a perfectly healthy server look down.
BASE="http://localhost:${PORT}"
PROBE="http://127.0.0.1:${PORT}"

# The project is wherever this script's parent directory is -- not a path
# typed into the file. Moving or renaming the folder must not break the
# launchers, and it did break the old hard-coded one.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

server_up() {
    # Any answer at all means a server is there. NOT curl -f: a redirect to
    # the login page is a running server, and treating it as "down" is how
    # you end up starting a second one.
    curl -s -o /dev/null -m 2 "$PROBE/" 2>/dev/null
}

wait_for_server() {
    # $1 = seconds to wait (default 25). Cold start with --reload is a few
    # seconds; a slow import is more.
    local limit="${1:-25}" waited=0
    while [ "$waited" -lt "$limit" ]; do
        server_up && return 0
        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

wait_for_port_free() {
    local limit="${1:-15}" waited=0
    while [ "$waited" -lt "$limit" ]; do
        server_up || return 0
        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

server_pids() {
    # Only OUR server. lsof alone would hand back whatever holds the port,
    # and a launcher that kills an unknown process on a shared port number
    # is a launcher you cannot trust to double-click.
    local pid
    for pid in $(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null); do
        case "$(ps -o command= -p "$pid" 2>/dev/null)" in
            *uvicorn*|*app.main*) echo "$pid" ;;
        esac
    done
}

open_url() {
    # ZPF_OPEN exists so the logic above can be exercised off a Mac.
    if [ -n "$ZPF_OPEN" ]; then "$ZPF_OPEN" "$1"
    elif command -v open >/dev/null 2>&1; then open "$1"
    else echo "Open this in your browser: $1"
    fi
}

uvicorn_bin() {
    if [ -x "$PROJECT_DIR/venv/bin/uvicorn" ]; then
        echo "$PROJECT_DIR/venv/bin/uvicorn"
    elif command -v uvicorn >/dev/null 2>&1; then
        command -v uvicorn
    else
        return 1
    fi
}

start_server() {
    # Foreground on purpose: this Terminal window IS the server, which is
    # the mental model start-studio.command already set. Ctrl+C stops it,
    # closing the window stops it.
    local bin
    bin="$(uvicorn_bin)" || {
        echo "No uvicorn found. Expected $PROJECT_DIR/venv/bin/uvicorn" >&2
        echo "Create the venv, or run: pip install -r requirements.txt" >&2
        return 1
    }
    cd "$PROJECT_DIR" || return 1
    echo "Starting the pipeline server on $BASE ..."
    exec "$bin" app.main:app --reload --timeout-graceful-shutdown 3
}

# Open PAGE ($1) once the server answers, starting one first if nothing is
# there. The browser tab is opened from a background subshell so the server
# can hold the foreground.
serve_and_open() {
    local url="$BASE$1"
    if server_up; then
        echo "Server already running — opening $url"
        open_url "$url"
        return 0
    fi
    ( wait_for_server && open_url "$url" ) &
    start_server
}

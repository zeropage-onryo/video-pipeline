#!/bin/bash
cd "$(dirname "$0")"
LOG="data/_to_delete/server_restart2.log"
: > "$LOG"
{
  echo "=== restart $(date) ==="
  PIDS=$(lsof -ti tcp:8000)
  if [ -n "$PIDS" ]; then
    echo "killing pids on :8000: $PIDS"
    for p in $PIDS; do
      kill -9 "$p" 2>&1
    done
    sleep 2
  else
    echo "nothing was listening on :8000"
  fi
  # belt and suspenders: kill any leftover uvicorn workers for this app too
  pkill -9 -f "uvicorn app.main:app" 2>&1
  sleep 1
  echo "port check before relaunch: $(lsof -ti tcp:8000)"
  nohup venv/bin/uvicorn app.main:app --reload --timeout-graceful-shutdown 3 >> "$LOG" 2>&1 &
  disown
  sleep 8
  echo "relaunched, pid now: $(lsof -ti tcp:8000)"
} >> "$LOG" 2>&1

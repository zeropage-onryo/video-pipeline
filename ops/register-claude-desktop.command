#!/bin/bash
# Registers the studio MCP server with Claude Desktop, then reopens the app.
#
# Claude Desktop reads mcpServers when it starts and rewrites
# claude_desktop_config.json from memory while it runs, so an edit made
# under a running app is undone the next time the app saves (seen twice on
# 2026-10-10: the `zeropage` block was gone seven seconds after one write
# and under three minutes after another). The only edit that sticks is one
# made while the app is quit -- which is what this does, so it has to run
# OUTSIDE the app:
#
#   open -a Terminal ops/register-claude-desktop.command
#
# It waits for Claude Desktop to quit (Cmd+Q, which ends every running
# session), copies the `zeropage` block from ops/claude-desktop-mcp.json
# into mcpServers (a backup is written beside the config before any
# change, every other key is left alone), and opens Claude again. Safe to
# run twice.
#
#   --board     also register zeropage-board (the pre-production board)
#   --no-wait   refuse instead of waiting when the app is running
set -euo pipefail

OPS="$(cd "$(dirname "$0")" && pwd)"
TPL="$OPS/claude-desktop-mcp.json"
# CLAUDE_DESKTOP_CONFIG points this at another file (a copy, for trying it):
# no waiting on the app and no reopening it then.
LIVE="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
CFG="${CLAUDE_DESKTOP_CONFIG:-$LIVE}"

NAMES="zeropage"
WAIT=1
for arg in "$@"; do
  case "$arg" in
    --board) NAMES="zeropage zeropage-board" ;;
    --no-wait) WAIT=0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

# Not `grep -q`: it exits at the first match, ps dies of SIGPIPE, and under
# pipefail the pipeline then reads as "not running" (it did, on the first try).
running() { ps -axo comm= | grep "/Claude.app/Contents/MacOS/Claude$" >/dev/null; }

[ -f "$CFG" ] || { echo "No config at: $CFG"; exit 1; }
[ -f "$TPL" ] || { echo "No template at: $TPL"; exit 1; }

if [ "$CFG" = "$LIVE" ] && running; then
  if [ "$WAIT" = 0 ]; then
    echo "Claude Desktop is running. Quit it (Cmd+Q) and run this again. Nothing was changed."
    exit 1
  fi
  echo "Waiting for Claude Desktop to quit."
  echo "Press Cmd+Q in Claude when you are ready -- that ends every running session."
  echo "(Ctrl+C here cancels; nothing has been changed.)"
  while running; do sleep 1; done
  sleep 2          # let the app finish its own last write
fi

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found"; exit 1; }

# shellcheck disable=SC2086
"$PY" - "$CFG" "$TPL" $NAMES <<'PY'
import json
import os
import shutil
import sys
import tempfile
import time

cfg, tpl, names = sys.argv[1], sys.argv[2], sys.argv[3:]
doc = json.load(open(cfg))
blocks = json.load(open(tpl))["mcpServers"]
servers = doc.setdefault("mcpServers", {})
changed = False
for name in names:
    block = blocks[name]
    if not os.path.exists(block["command"]):
        sys.exit(f"{name}: {block['command']} does not exist -- build the venv first")
    if servers.get(name) == block:
        print(f"{name}: already registered")
        continue
    servers[name] = block
    changed = True
    print(f"{name}: registered ({block['command']} {' '.join(block['args'])})")
if changed:
    backup = f"{cfg}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while os.path.exists(backup):      # never over an earlier backup
        n += 1
        backup = f"{cfg}.bak-{time.strftime('%Y%m%d-%H%M%S')}-{n}"
    shutil.copy2(cfg, backup)
    print(f"backup: {backup}")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(cfg), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, os.stat(cfg).st_mode & 0o777)
    os.replace(tmp, cfg)
PY

if [ "$CFG" = "$LIVE" ]; then
  echo "Opening Claude..."
  open -a "Claude"
fi

#!/bin/bash
# Zero Page Films — Studio (the product surface).
# Double-click in Finder, or run from Terminal.
#
# Opens http://localhost:8000/ui, starting the server first if it isn't
# already running. Safe to double-click when dev.command is already up:
# it will not start a second server, it just opens the tab.
source "$(cd "$(dirname "$0")" && pwd)/ops/serve.sh"
serve_and_open "/ui"

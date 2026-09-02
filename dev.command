#!/bin/bash
# Zero Page Films — Dev Studio (stats, grading, RAG library, settings).
# Double-click in Finder, or run from Terminal.
#
# Opens http://localhost:8000/studio, starting the server first if it isn't
# already running. Same one process as studio.command — opening both is two
# tabs, never two servers.
source "$(cd "$(dirname "$0")" && pwd)/ops/serve.sh"
serve_and_open "/studio"

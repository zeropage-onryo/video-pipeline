#!/bin/bash
# Double-click me. Finishes the IG_GRAPH_TOKEN setup for the scout's
# instagram lane: exchanges the short-lived token for a 60-day one,
# installs it in .env, and verifies the lane can actually run.
cd "$(dirname "$0")" || exit 1
bash ops/ig_token.sh
echo
echo "Press return to close."
read -r _

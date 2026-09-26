#!/bin/bash
# Double-click me. Checks both Instagram tokens (read-only) and names the
# fix for any that needs one. For the other commands -- refresh, publish,
# research -- run `bash ops/ig_token.sh <command>` in Terminal.
cd "$(dirname "$0")" || exit 1
bash ops/ig_token.sh check
echo
echo "Press return to close."
read -r _

#!/bin/bash
# Double-click me. Attaches cast/prop photos to the concepts whose shots
# carry none -- the 2026-09-01 account-scoping bug left 15 of them
# ungrounded, including SHOOT-139 "The Red Key".
#
# Shows the report FIRST and writes nothing until you type WRITE.
cd "$(dirname "$0")" || exit 1

if [ ! -x venv/bin/python3 ]; then
  echo "FAIL: venv/bin/python3 not found — run this from the project root."
  echo; echo "Press return to close."; read -r _; exit 1
fi

echo "=============================================="
echo " DRY RUN — nothing is written yet"
echo "=============================================="
venv/bin/python3 -m ops.backfill_scene_refs
STATUS=$?
echo
if [ $STATUS -ne 0 ]; then
  echo "The report failed (exit $STATUS). Nothing was written."
  echo; echo "Press return to close."; read -r _; exit 1
fi

printf 'Type WRITE to apply this, anything else to cancel: '
read -r ANSWER
if [ "$ANSWER" != "WRITE" ]; then
  echo "Cancelled. Nothing was written."
  echo; echo "Press return to close."; read -r _; exit 0
fi

echo
echo "=============================================="
echo " APPLYING"
echo "=============================================="
venv/bin/python3 -m ops.backfill_scene_refs --write
echo
echo "If you saw 'database is locked', stop the studio server and run this again."
echo "Press return to close."
read -r _

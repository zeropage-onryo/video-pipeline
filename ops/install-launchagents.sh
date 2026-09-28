#!/bin/bash
# Install (or re-install) this Mac's one LaunchAgent: the Instagram token
# keeper (com.zeropage.igtoken, daily 10:00, refreshes once 30 days old).
#
# THE NIGHTLY WALK IS NOT SCHEDULED ANY MORE (2026-09-28, Mike's call):
# this script also unloads the two retired agents -- com.zeropage.
# morningprompts (the 22:00 walk) and com.zeropage.shadowrun (the 03:30
# run removed from the repo on 2026-09-14 but still installed here) -- and
# renames their plists to .disabled.<stamp>, never deletes them.
#
# WHY THIS EXISTS: ~/Library/LaunchAgents holds a COPY of the plist.
# Editing the copy in this repo changes nothing -- launchd keeps running
# whatever was installed, with whatever paths it had at install time.
#
#   ops/install-launchagents.sh          install / re-install and load
#   ops/install-launchagents.sh --check  say what is installed, change nothing
#
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LABEL="com.zeropage.igtoken"
SRC="$ROOT/$LABEL.plist"
DST="$AGENTS/$LABEL.plist"
RETIRED="com.zeropage.morningprompts com.zeropage.shadowrun"
LOGS="$HOME/Library/Logs/zeropage"

check() {
  echo "repo plist     : $SRC"
  echo "installed      : $DST"
  if [ -f "$DST" ]; then
    if diff -q "$SRC" "$DST" >/dev/null 2>&1; then
      echo "in sync        : yes"
    else
      echo "in sync        : NO -- the installed copy differs from this repo's"
    fi
  else
    echo "in sync        : not installed at all"
  fi
  echo "loaded         : $(launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 \
                            && echo yes || echo no)"
  launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null \
    | grep -E 'last exit code|state = ' | sed 's/^/                 /'
  for OLD in $RETIRED; do
    if [ -f "$AGENTS/$OLD.plist" ] || launchctl print "gui/$(id -u)/$OLD" >/dev/null 2>&1; then
      echo "RETIRED STILL  : $OLD is installed or loaded -- run this script to retire it"
    fi
  done
  [ -s "$LOGS/ig_token.out" ] && echo "last stdout    : $(tail -1 "$LOGS/ig_token.out")"
  [ -s "$LOGS/ig_token.err" ] && echo "last error     : $(tail -1 "$LOGS/ig_token.err")"
  return 0
}

if [ "${1:-}" = "--check" ]; then check; exit 0; fi

STAMP="$(date +%Y%m%d-%H%M%S)"
for OLD in $RETIRED; do
  launchctl bootout "gui/$(id -u)/$OLD" 2>/dev/null \
    || launchctl unload "$AGENTS/$OLD.plist" 2>/dev/null
  if [ -f "$AGENTS/$OLD.plist" ]; then
    mv "$AGENTS/$OLD.plist" "$AGENTS/$OLD.plist.disabled.$STAMP" \
      && echo "retired: $OLD (plist kept as $OLD.plist.disabled.$STAMP)"
  fi
done

mkdir -p "$AGENTS"
# launchd opens StandardOutPath/StandardErrorPath ITSELF, before exec, as
# launchd -- so they cannot live under ~/Documents (TCC-protected) no
# matter what the program is granted. ~/Library/Logs is not protected.
mkdir -p "$LOGS"
launchctl unload "$DST" 2>/dev/null
cp "$SRC" "$DST" || { echo "could not copy the plist to $AGENTS" >&2; exit 1; }
launchctl load "$DST" || { echo "launchctl load failed" >&2; exit 1; }
echo "installed and loaded: $LABEL"
echo
check
echo
cat <<'NOTE'
If the job logs "Operation not permitted": the program reads
ops/ig_token.sh under ~/Documents as itself, which needs Full Disk Access
on /bin/bash (System Settings -> Privacy & Security -> Full Disk Access).
The job also runs whatever branch the main checkout has checked out --
ops/ig_tokens.py `keep` must be on that branch.
NOTE

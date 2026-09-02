#!/bin/bash
# Install (or re-install) the nightly LaunchAgent.
#
# WHY THIS EXISTS: ~/Library/LaunchAgents holds a COPY of the plist.
# Editing the copy in this repo changes nothing — launchd keeps running
# whatever was installed, with whatever paths it had at install time.
# That is exactly how the job died: the folder was renamed from
# "Github Portfolio" and the installed plist kept pointing at the old
# name for a week without anyone noticing.
#
#   ops/install-launchagents.sh          install / re-install and load
#   ops/install-launchagents.sh --check  say what is installed, change nothing
#
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LABEL="com.zeropage.morningprompts"
SRC="$ROOT/$LABEL.plist"
DST="$AGENTS/$LABEL.plist"

check() {
  echo "repo plist     : $SRC"
  echo "installed      : $DST"
  if [ -f "$DST" ]; then
    if diff -q "$SRC" "$DST" >/dev/null 2>&1; then
      echo "in sync        : yes"
    else
      echo "in sync        : NO — the installed copy differs from this repo's"
      echo "installed path : $(grep -o '/Users/[^<]*run_morning_prompts.sh' "$DST" | head -1)"
    fi
  else
    echo "in sync        : not installed at all"
  fi
  echo "loaded         : $(launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 \
                            && echo yes || echo no)"
  launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null \
    | grep -E 'last exit code|state = ' | sed 's/^/                 /'
  echo
  local LOGS="$HOME/Library/Logs/zeropage"
  echo "agent stdout   : $LOGS/morning_prompts.out"
  echo "last run       : $(stat -f '%Sm' "$ROOT/data/morning_prompts.log" 2>/dev/null || echo 'never')"
  if [ -s "$LOGS/morning_prompts.out" ]; then
    echo "last stdout    : $(tail -1 "$LOGS/morning_prompts.out")"
  fi
  if [ -s "$LOGS/morning_prompts.err" ]; then
    echo "last error     : $(tail -1 "$LOGS/morning_prompts.err")"
  fi
}

if [ "${1:-}" = "--check" ]; then check; exit 0; fi

mkdir -p "$AGENTS"
# launchd opens StandardOutPath/StandardErrorPath ITSELF, before exec, as
# launchd -- so they cannot live under ~/Documents (TCC-protected) no
# matter what the program is granted. That is what EX_CONFIG with an
# empty log meant for eleven nights. ~/Library/Logs is not protected.
mkdir -p "$HOME/Library/Logs/zeropage"
launchctl unload "$DST" 2>/dev/null
cp "$SRC" "$DST" || { echo "could not copy the plist to $AGENTS" >&2; exit 1; }
launchctl load "$DST" || { echo "launchctl load failed" >&2; exit 1; }
echo "installed and loaded: $LABEL"
echo
check
echo
cat <<'NOTE'
Two separate macOS walls, and they need different fixes:

1. launchd opens StandardOutPath/StandardErrorPath itself, BEFORE exec,
   as launchd -- not as the program. Those paths cannot be under
   ~/Documents; granting the program Full Disk Access does nothing for
   them. Symptom: exit code 78 EX_CONFIG and not one byte written
   anywhere. They now point at ~/Library/Logs/zeropage/.
2. The program then reads the script under ~/Documents as itself.
   That one DOES need Full Disk Access on /bin/bash (System Settings ->
   Privacy & Security -> Full Disk Access -> + -> Cmd-Shift-G ->
   /bin/bash). Symptom: "Operation not permitted" in the error log.
NOTE

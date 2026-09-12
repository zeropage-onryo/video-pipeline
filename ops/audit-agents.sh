#!/bin/bash
# Find what runs the nightly walk, and disable the DUPLICATE — never the
# canonical one, never the 3:30 shadow run, and never by deleting: a plist
# is renamed to .disabled.<timestamp> and can be renamed back.
#
# Decision rule, so this cannot guess wrong:
#   * candidates = every plist that invokes run_morning_prompts.sh or src.nightly
#   * exactly one candidate -> disable NOTHING. The second walk then comes from
#     inside that entry (RunAtLoad, KeepAlive, two StartCalendarInterval dicts)
#     or from cron, and the report prints all of it for a human to read.
#   * more than one -> keep com.zeropage.morningprompts, disable the rest.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/data/agents-audit.txt"
AGENTS="$HOME/Library/LaunchAgents"
KEEP="com.zeropage.morningprompts"
READONLY=1   # 2026-09-08: audit proved there is no duplicate agent; the
             # duplicate start comes from launchd itself and is handled by
             # the lock + night marker in run_morning_prompts.sh.
STAMP="$(date +%Y%m%d-%H%M%S)"

{
  echo "=== BEFORE ==="
  echo "-- launchctl list --"
  launchctl list 2>/dev/null | grep -iE "zeropage|morning|prompt|shadow" || echo "(none)"
  echo

  CANDIDATES=()
  for DIR in "$AGENTS" /Library/LaunchAgents /Library/LaunchDaemons; do
    [ -d "$DIR" ] || continue
    echo "-- $DIR --"
    ls -la "$DIR" 2>/dev/null | grep -iE "zeropage|morning|prompt|shadow" || echo "(nothing matching by name)"
    for P in "$DIR"/*.plist; do
      [ -f "$P" ] || continue
      if grep -qiE "run_morning_prompts|src\.nightly" "$P" 2>/dev/null; then
        CANDIDATES+=("$P")
        echo "--- CANDIDATE: $P ---"
        /usr/libexec/PlistBuddy -c Print "$P" 2>/dev/null || cat "$P"
        echo "--- end ---"
      elif grep -qiE "src\.trigger|PRODUCTION PIPLINE|Github Portfolio" "$P" 2>/dev/null; then
        echo "--- related (not a walk, left alone): $P ---"
        /usr/libexec/PlistBuddy -c Print "$P" 2>/dev/null | grep -E "Label|Program|Hour|Minute|RunAtLoad|KeepAlive|StartInterval"
        echo "--- end ---"
      fi
    done
    echo
  done

  echo "-- crontab --"
  crontab -l 2>/dev/null || echo "(no crontab)"
  echo
  echo "-- launchd overrides / duplicate labels --"
  launchctl print "gui/$(id -u)/$KEEP" 2>/dev/null | grep -E "state|program|last exit|runs =" || echo "(label $KEEP not loaded)"
  echo

  echo "=== ACTION ==="
  echo "candidates that run the walk: ${#CANDIDATES[@]}"
  if [ "${READONLY:-0}" = "1" ] || [ "${#CANDIDATES[@]}" -le 1 ]; then
    echo "NOTHING DISABLED — only one entry runs the walk."
    echo "The second walk is coming from inside it or from cron; read the"
    echo "CANDIDATE block above for RunAtLoad / KeepAlive / a second"
    echo "StartCalendarInterval dict, and the crontab section."
  else
    for P in "${CANDIDATES[@]}"; do
      LABEL="$(basename "$P" .plist)"
      if [ "$LABEL" = "$KEEP" ]; then
        echo "KEEPING  $P"
        continue
      fi
      echo "DISABLING $P"
      launchctl unload "$P" 2>&1
      launchctl bootout "gui/$(id -u)/$LABEL" 2>&1
      if mv "$P" "$P.disabled.$STAMP"; then
        echo "  renamed -> $P.disabled.$STAMP"
        echo "  undo: mv it back, then launchctl load \"$P\""
      else
        echo "  COULD NOT RENAME (permissions?) — nothing changed for this one"
      fi
    done
  fi
  echo
  echo "=== AFTER ==="
  launchctl list 2>/dev/null | grep -iE "zeropage|morning|prompt|shadow" || echo "(none)"
  echo
  ls -la "$AGENTS" 2>/dev/null | grep -iE "zeropage|morning|prompt|shadow" || true
} > "$OUT" 2>&1
echo "wrote $OUT"

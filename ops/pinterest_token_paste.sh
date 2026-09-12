#!/bin/bash
# Companion to pinterest_token.sh for the case where Pinterest already
# handed you a ready-made access token straight from the app dashboard
# (their "Personal API access" trial tokens work this way -- no
# authorization-code exchange needed, just paste it in).
#
# Run this on YOUR OWN machine, in your own terminal:
#   bash ops/pinterest_token_paste.sh
# The token is read with a hidden prompt and never leaves this machine.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
ENV_FILE="$ROOT/.env"

echo
echo "Pinterest access token setup"
echo "-----------------------------"
printf "Paste the access token (input hidden): "
read -rs ACCESS_RAW; echo
echo

# Strip anything a copy-paste from a browser tends to smuggle in --
# leading/trailing spaces, a trailing newline, CR from a Windows-style
# clipboard, or accidental surrounding quotes.
ACCESS=$(printf '%s' "$ACCESS_RAW" | tr -d '\r\n' | sed -e 's/^[[:space:]"'"'"']*//' -e 's/[[:space:]"'"'"']*$//')

if [ -z "$ACCESS" ]; then
  echo "FAIL: nothing pasted."; exit 1
fi
echo "     got a token, length ${#ACCESS} chars (raw paste was ${#ACCESS_RAW})"
if [ "${#ACCESS}" != "${#ACCESS_RAW}" ]; then
  echo "     (trimmed stray whitespace/quotes off the raw paste)"
fi

echo "1/2  verifying the token against the boards endpoint..."
HTTP_CODE=$(curl -sS -o /tmp/pinterest_boards_resp.json -w "%{http_code}" -G "https://api.pinterest.com/v5/boards" \
  -H "Authorization: Bearer $ACCESS" \
  --data-urlencode "page_size=100")
BOARDS=$(cat /tmp/pinterest_boards_resp.json)

if [ "$HTTP_CODE" != "200" ]; then
  echo "     FAIL (HTTP $HTTP_CODE). Pinterest said:"
  python3 -m json.tool /tmp/pinterest_boards_resp.json 2>/dev/null || cat /tmp/pinterest_boards_resp.json
  echo
  echo "     If this still says authentication failed with a clean paste,"
  echo "     the likely causes are: the token was copied from the wrong"
  echo "     field (App ID/secret instead of the access token), it needs"
  echo "     'boards:read' in its scopes, or it already expired -- go back"
  echo "     to the app's page on developers.pinterest.com and regenerate it."
  rm -f /tmp/pinterest_boards_resp.json
  exit 1
fi
rm -f /tmp/pinterest_boards_resp.json
echo "     ok -- token is valid"

echo "2/2  writing PINTEREST_ACCESS_TOKEN into .env..."
touch "$ENV_FILE"
cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
python3 - "$ENV_FILE" "$ACCESS" <<'PY'
import sys
path, access = sys.argv[1:3]
wanted = {"PINTEREST_ACCESS_TOKEN": access}
lines = open(path).readlines()
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
    if key in wanted:
        out.append(f"{key}={wanted[key]}\n")
        seen.add(key)
    else:
        out.append(line)
for key, val in wanted.items():
    if key not in seen:
        out.append(f"{key}={val}\n")
open(path, "w").writelines(out)
PY
echo "     ok -- .env updated (previous copy kept as .env.bak.*)"

echo
echo "Your boards:"
echo "$BOARDS" | python3 -c 'import json, sys
d = json.load(sys.stdin)
rows = d.get("items") or []
if not rows:
    print("     No boards yet. Create one per brand on pinterest.com,")
    print("     pin reference images that match the look, then set")
    print("     PINTEREST_BOARD_ANTIHERO / PINTEREST_BOARD_ZEROPAGE in")
    print("     .env to each board'\''s exact name (or its id, printed here")
    print("     once it exists).")
else:
    for b in rows:
        print("  %-30s  id=%s  (%s pins)" % (b.get("name"), b.get("id"), b.get("pin_count")))
    print()
    print("Set PINTEREST_BOARD_ANTIHERO and PINTEREST_BOARD_ZEROPAGE in .env")
    print("to the name or id of whichever board is each brand'\''s reference board.")'

echo
echo "Note: a token generated straight from the Pinterest dashboard (rather"
echo "than the OAuth code flow) typically has no refresh token attached and"
echo "a shorter lifetime -- check the dashboard for how long it lasts, and"
echo "expect to regenerate/re-run this occasionally until the full OAuth"
echo "app is approved."

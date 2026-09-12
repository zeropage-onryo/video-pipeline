#!/bin/bash
# Finish the Pinterest reference lane: create the app (you), exchange for a
# token (this script), verify board access (this script).
#
# Mirrors ops/ig_token.sh's shape on purpose -- this repo already has one
# working pattern for "a credential that must never leave Mike's machine,"
# no reason to invent a second one. Everything here runs on your Mac; the
# app secret and every token stay in your local .env.
#
# Written 2026-09-08 -- src/scout.py's Pinterest lane (gather_pinterest)
# and src/imagesearch.py's pinterest() have been ready since today, dark
# for exactly one reason: nobody had run this yet.
#
# ONE THING ONLY YOU CAN DO FIRST: register an app.
#   1. developers.pinterest.com -> My apps -> Create app
#   2. Any name (e.g. "Zero Page Research"), any use case that lets you
#      request boards:read + pins:read.
#   3. Add a redirect URI. It does NOT need to be a live page -- Pinterest
#      puts the authorization code in the URL it redirects to regardless
#      of whether anything answers there, so something boring like
#      http://localhost:8080/callback works fine. Whatever you type here,
#      paste the EXACT same string when this script asks for it below.
#   4. Copy the app's Client ID and Client secret (App settings).
#
# Run this via: bash ops/pinterest_token.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
ENV_FILE="$ROOT/.env"

echo
echo "Pinterest reference lane setup"
echo "-------------------------------"
echo "Nothing you paste here leaves this machine."
echo

# --- inputs ---------------------------------------------------------------
printf "Client ID (Pinterest app -> App settings): "
read -r CLIENT_ID
printf "Client secret: "
read -rs CLIENT_SECRET; echo
printf "Redirect URI (exactly as registered, e.g. http://localhost:8080/callback): "
read -r REDIRECT_URI
echo

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ] || [ -z "$REDIRECT_URI" ]; then
  echo "FAIL: all three are required."; exit 1
fi

# --- 1. send you to approve, then read the code back ----------------------
SCOPE="boards:read,pins:read"
AUTH_URL="https://www.pinterest.com/oauth/?client_id=${CLIENT_ID}&redirect_uri=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$REDIRECT_URI")&response_type=code&scope=${SCOPE}"

echo "1/4  open this URL, log in as yourself, and approve it:"
echo
echo "     $AUTH_URL"
echo
echo "     Pinterest will redirect you to your redirect URI with"
echo "     ?code=... in the address bar -- the page itself can 404 or"
echo "     show nothing, the code is what matters. Copy everything after"
echo "     code= and before any following &."
echo
printf "Paste the code: "
read -r AUTH_CODE
echo

if [ -z "$AUTH_CODE" ]; then
  echo "FAIL: no code pasted."; exit 1
fi

# --- 2. exchange the code for tokens ---------------------------------------
echo "2/4  exchanging the code for an access token..."
BASIC=$(printf '%s:%s' "$CLIENT_ID" "$CLIENT_SECRET" | base64 | tr -d '\n')
RESP=$(curl -sS -X POST "https://api.pinterest.com/v5/oauth/token" \
  -H "Authorization: Basic $BASIC" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code=$AUTH_CODE" \
  --data-urlencode "redirect_uri=$REDIRECT_URI" \
  --data-urlencode "continuous_refresh=true")

ACCESS=$(printf '%s' "$RESP" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("access_token",""))
except Exception: print("")')

if [ -z "$ACCESS" ]; then
  echo "     FAIL. Pinterest said:"
  printf '%s\n' "$RESP" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$RESP"
  echo
  echo "     Common causes: the redirect URI doesn't match exactly what"
  echo "     you registered, or the code already expired (they're good for"
  echo "     about 10 minutes and single-use -- re-run this for a fresh one)."
  exit 1
fi
REFRESH=$(printf '%s' "$RESP" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("refresh_token",""))
except Exception: print("")')
EXPIRES_IN=$(printf '%s' "$RESP" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("expires_in",0))
except Exception: print(0)')
echo "     ok -- access token issued, good for $((EXPIRES_IN / 86400)) days"

# --- 3. write everything into .env -----------------------------------------
echo "3/4  writing into .env..."
touch "$ENV_FILE"
cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
EXPIRES_AT=$(( $(date +%s) + EXPIRES_IN ))
python3 - "$ENV_FILE" "$ACCESS" "$REFRESH" "$CLIENT_ID" "$CLIENT_SECRET" "$EXPIRES_AT" <<'PY'
import sys
path, access, refresh, cid, secret, expires_at = sys.argv[1:7]
wanted = {
    "PINTEREST_ACCESS_TOKEN": access,
    "PINTEREST_REFRESH_TOKEN": refresh,
    "PINTEREST_CLIENT_ID": cid,
    "PINTEREST_CLIENT_SECRET": secret,
    "PINTEREST_TOKEN_EXPIRES_AT": expires_at,
}
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
echo "     REMEMBER: this access token is good for $((EXPIRES_IN / 86400)) days,"
echo "     not 60 like the Instagram one -- PINTEREST_REFRESH_TOKEN is stored"
echo "     so re-running this script (or a future refresh helper) can renew"
echo "     it without another browser approval, but nothing refreshes it"
echo "     automatically yet. Put a reminder on your calendar, or ask Claude"
echo "     to schedule one, before day 30."

# --- 4. list boards so you can name PINTEREST_BOARD_<BRAND> ---------------
echo
echo "4/4  listing your boards..."
BOARDS=$(curl -sS -G "https://api.pinterest.com/v5/boards" \
  -H "Authorization: Bearer $ACCESS" \
  --data-urlencode "page_size=100")
printf '%s\n' "$BOARDS" | python3 -c 'import json, sys
d = json.load(sys.stdin)
if "error" in d or "code" in d:
    print("     FAIL:", d.get("message") or d)
    sys.exit(0)
rows = d.get("items") or []
if not rows:
    print("     No boards yet. Create one per brand on pinterest.com,")
    print("     pin reference images that match the look, then set")
    print("     PINTEREST_BOARD_ANTIHERO / PINTEREST_BOARD_ZEROPAGE in")
    print("     .env to each board'\''s exact name (or its id, printed here")
    print("     once it exists).")
else:
    print("     Your boards:")
    for b in rows:
        print("       %-30s  id=%s  (%s pins)" % (b.get("name"), b.get("id"), b.get("pin_count")))
    print()
    print("     Set PINTEREST_BOARD_ANTIHERO and PINTEREST_BOARD_ZEROPAGE in")
    print("     .env to the name or id of whichever board is each brand'\''s")
    print("     reference board.")'

echo
echo "Done. Once PINTEREST_BOARD_ANTIHERO / PINTEREST_BOARD_ZEROPAGE are set,"
echo "gather_pinterest starts contributing on the next scout run."

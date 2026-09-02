#!/bin/bash
# Finish the IG_GRAPH_TOKEN setup: exchange, install, verify.
#
# Everything here runs on Mike's Mac so the app secret and the token
# never leave it. Written 2026-09-01 -- the research lane (scout's
# instagram lane) has been dark since it was built because this
# credential was never issued.
#
# Run it via ig-token.command (double-click) or: bash ops/ig_token.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
ENV_FILE="$ROOT/.env"
APP_ID="1382270770525151"          # ZeroPageFilms, read off the app list
VERSION="v23.0"                     # matches src/instagram.py VERSION

echo
echo "IG_GRAPH_TOKEN setup — ZeroPageFilms ($APP_ID)"
echo "-----------------------------------------------"
echo "Nothing you paste here leaves this machine."
echo

# --- inputs ---------------------------------------------------------------
# -s on the secret so a shoulder-surfer / screen recording gets nothing.
printf "App secret (Meta app -> App settings -> Basic -> Show): "
read -rs APP_SECRET; echo
printf "Short-lived token from Graph API Explorer: "
read -rs SHORT_TOKEN; echo
echo

if [ -z "$APP_SECRET" ] || [ -z "$SHORT_TOKEN" ]; then
  echo "FAIL: both values are required."; exit 1
fi

# --- 1. exchange for the 60-day token -------------------------------------
echo "1/4  exchanging for a long-lived token..."
RESP=$(curl -sS -G "https://graph.facebook.com/$VERSION/oauth/access_token" \
  --data-urlencode "grant_type=fb_exchange_token" \
  --data-urlencode "client_id=$APP_ID" \
  --data-urlencode "client_secret=$APP_SECRET" \
  --data-urlencode "fb_exchange_token=$SHORT_TOKEN")

LONG=$(printf '%s' "$RESP" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("access_token",""))
except Exception: print("")')

if [ -z "$LONG" ]; then
  echo "     FAIL. Meta said:"
  printf '%s\n' "$RESP" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$RESP"
  echo
  echo "     Common causes: the app secret is wrong, or the short-lived"
  echo "     token already expired (they last about an hour -- generate a"
  echo "     fresh one in the Explorer and run this again)."
  exit 1
fi
EXPIRES=$(printf '%s' "$RESP" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("expires_in",""))
except Exception: print("")')
echo "     ok — long-lived token issued (expires_in=${EXPIRES:-unknown}s)"

# --- 2. install into .env -------------------------------------------------
echo "2/4  writing IG_GRAPH_TOKEN into .env..."
touch "$ENV_FILE"
cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
if grep -q '^IG_GRAPH_TOKEN=' "$ENV_FILE"; then
  python3 - "$ENV_FILE" "$LONG" <<'PY'
import sys
path, tok = sys.argv[1], sys.argv[2]
out = []
for line in open(path):
    out.append(f"IG_GRAPH_TOKEN={tok}\n" if line.startswith("IG_GRAPH_TOKEN=") else line)
open(path, "w").writelines(out)
PY
else
  printf 'IG_GRAPH_TOKEN=%s\n' "$LONG" >> "$ENV_FILE"
fi
echo "     ok — .env updated (previous copy kept as .env.bak.*)"

# --- 3. is the Instagram account actually linked to the Page? -------------
# This is the prerequisite Facebook Login adds and Instagram Login does
# not, and the one most likely to be missing.
echo "3/4  checking the Page -> Instagram link..."
PAGES=$(curl -sS -G "https://graph.facebook.com/$VERSION/me/accounts" \
  --data-urlencode "fields=name,id,instagram_business_account{id,username}" \
  --data-urlencode "access_token=$LONG")
printf '%s\n' "$PAGES" | python3 -c 'import json, sys
d = json.load(sys.stdin)
if "error" in d:
    print("     FAIL:", d["error"].get("message"))
    sys.exit(0)
rows = d.get("data") or []
if not rows:
    print("     no Pages on this account at all.")
    sys.exit(0)
linked = False
for p in rows:
    iba = p.get("instagram_business_account")
    if iba:
        linked = True
        print("     LINKED  %s -> @%s (IG id %s)"
              % (p.get("name"), iba.get("username"), iba.get("id")))
        print("     >>> if that id differs from IG_USER_ID in .env, "
              "set IG_BUSINESS_ID=%s" % iba.get("id"))
    else:
        print("     no IG   %s" % p.get("name"))
if not linked:
    print("")
    print("     >>> THIS IS THE BLOCKER. No Page has an Instagram professional")
    print("         account linked, so business_discovery cannot run at all.")
    print("         Fix: Instagram app -> Settings -> Accounts Centre, or the")
    print("         Page -> Linked accounts -> Instagram. Then re-run this.")'

# --- 4. the decisive probe ------------------------------------------------
# Does this token actually let us read ANOTHER account? That is what
# separates "10 minutes" from "App Review".
echo "4/4  probing business_discovery (reads another account)..."
IG_ID=$(grep -E '^IG_BUSINESS_ID=.+' "$ENV_FILE" | head -1 | cut -d= -f2-)
[ -z "$IG_ID" ] && IG_ID=$(grep -E '^IG_USER_ID=.+' "$ENV_FILE" | head -1 | cut -d= -f2-)
if [ -z "$IG_ID" ]; then
  echo "     skipped — no IG_USER_ID / IG_BUSINESS_ID in .env"
else
  PROBE=$(curl -sS -G "https://graph.facebook.com/$VERSION/$IG_ID" \
    --data-urlencode "fields=business_discovery.username(zeropagefilms){followers_count,media_count}" \
    --data-urlencode "access_token=$LONG")
  printf '%s\n' "$PROBE" | python3 -c 'import json,sys
d = json.load(sys.stdin)
if "error" in d:
    e = d["error"]
    print("     FAIL:", e.get("message"))
    print("     code:", e.get("code"), "subcode:", e.get("error_subcode"))
    print()
    print("     If this mentions permissions or Advanced Access, the lane")
    print("     needs App Review (business verification + demo). If it")
    print("     mentions the account is not a professional account or is")
    print("     not linked, fix step 3 first.")
else:
    bd = (d.get("business_discovery") or {})
    print("     OK — read another account:", bd)
    print()
    print("     The lane can run. Nothing further is needed.")'
fi

echo
echo "Done. Tell Claude the step numbers that passed or failed."

#!/bin/bash
# Production-only configuration guard, called by the Fly container entrypoint.
# It deliberately reports variable names only so deployment logs never expose
# credentials.
set -eu

missing=()
for name in \
    DATABASE_URL \
    RAG_DATABASE_URL \
    SUPABASE_URL \
    SUPABASE_ANON_KEY \
    SESSION_SECRET \
    ACCOUNT_KEYS_SECRET \
    SITE_URL
do
    if [ -z "${!name:-}" ]; then
        missing+=("$name")
    fi
done

if [ "${#missing[@]}" -ne 0 ]; then
    printf 'deployment configuration missing:' >&2
    printf ' %s' "${missing[@]}" >&2
    printf '\n' >&2
    exit 1
fi

case "$DATABASE_URL" in
    postgres://*|postgresql://*) ;;
    *) echo "DATABASE_URL must be a Postgres connection URL" >&2; exit 1 ;;
esac

case "$RAG_DATABASE_URL" in
    postgres://*|postgresql://*) ;;
    *) echo "RAG_DATABASE_URL must be a Postgres connection URL" >&2; exit 1 ;;
esac

case "$SUPABASE_URL" in
    https://*) ;;
    *) echo "SUPABASE_URL must use https://" >&2; exit 1 ;;
esac

case "$SITE_URL" in
    https://*) ;;
    *) echo "SITE_URL must be the public https:// origin" >&2; exit 1 ;;
esac

if [ "${DEV_TOOLS:-0}" = "1" ]; then
    echo "DEV_TOOLS=1 is refused on the public Fly deployment" >&2
    exit 1
fi

python - <<'PY'
import os
from cryptography.fernet import Fernet

try:
    Fernet(os.environ["ACCOUNT_KEYS_SECRET"].encode())
except Exception as exc:
    raise SystemExit("ACCOUNT_KEYS_SECRET is not a valid Fernet key") from exc
PY

if [ -z "${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}" ]; then
    echo "warning: no Gemini key is configured; generation will be unavailable" >&2
fi

echo "deployment configuration: ok"

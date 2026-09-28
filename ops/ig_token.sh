#!/bin/bash
# The two Instagram tokens, by hand. A thin door onto ops/ig_tokens.py,
# where the logic (and its tests) live:
#
#   bash ops/ig_token.sh              # check both, read-only (the default)
#   bash ops/ig_token.sh check --probe
#   bash ops/ig_token.sh refresh      # IG_ACCESS_TOKEN +60 days, into .env
#   bash ops/ig_token.sh publish      # install a re-issued IG_ACCESS_TOKEN
#   bash ops/ig_token.sh research --app-id <research app id>
#
# Getting a token into Fly WITHOUT printing it (never `fly secrets set
# NAME=<value>`: that puts the value in shell history). fly-export refuses a
# terminal, so the only thing that can read it is the pipe:
#
#   bash ops/ig_token.sh fly-export IG_ACCESS_TOKEN | fly secrets import -a zeropage-studio
#
# Exportable: IG_ACCESS_TOKEN (what instagram.access_token() serves, so the
# nightly refresh's stored replacement wins over .env), IG_GRAPH_TOKEN,
# IG_USER_ID, IG_BUSINESS_ID.
#
# Everything runs on this Mac; secrets are read without echo and no token
# is ever printed. Every .env write keeps a .env.bak.<stamp> copy.
#
# SCOPES (2026-09-26). This script never requested scopes itself -- they
# are chosen where the token is issued. Instagram Login (publishing,
# ZeroPageFilms): instagram_business_basic, instagram_business_content_publish,
# instagram_business_manage_insights. Facebook Login (research app):
# instagram_basic, pages_show_list, pages_read_engagement, business_management.
# The old instagram_basic / instagram_content_publish pair is Facebook-Login
# vocabulary and does not exist on Instagram Login.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
PY="$ROOT/venv/bin/python"
[ -x "$PY" ] || PY=python3
[ $# -eq 0 ] && set -- check
exec "$PY" -m ops.ig_tokens "$@"

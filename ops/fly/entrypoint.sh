#!/bin/bash
# cron does NOT inherit the container's environment (Fly secrets included) --
# it spawns jobs with a bare minimal env, which is exactly the kind of
# "looks healthy, isn't" failure launchd_tcc.md already burned a night on
# once, on the Mac. Dump the real environment to a file before cron ever
# runs, and have both cron jobs source it first, so the nightly walk sees
# GEMINI_API_KEY / DATABASE_URL / RAG_DATABASE_URL / ACCOUNT_KEYS_SECRET
# exactly as the web process does.
set -e

# Refuse a half-configured public machine before supervisor starts. This
# prints names only, never secret values.
/bin/bash /app/ops/fly/preflight.sh

printenv | sed "s/'/'\\\\''/g; s/^\\([A-Za-z_][A-Za-z0-9_]*\\)=\\(.*\\)/export \\1='\\2'/" \
    > /app/.env.runtime
chmod 600 /app/.env.runtime
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/zeropage.conf

#!/bin/bash
# The nightly walk, as a Fly Machine runs it. One job, one exit code.
#
# Two ways this is invoked, and it has to behave the same under both:
#   * a scheduled Machine  -- `fly machine run ... --schedule daily`, which
#     boots a fresh Machine, runs this, and destroys it;
#   * the cron process already in the image (Dockerfile /etc/cron.d/zeropage),
#     which sources /app/.env.runtime first because cron gets a bare env.
# Nothing here assumes which -- it reads the environment it is given and
# refuses to guess a missing one.
#
# NOT DEPLOYED BY THIS FILE. ops/fly/nightly.md is the recipe; this is only
# the command that recipe schedules.
set -uo pipefail

cd /app || { echo "$(date -u +%FT%TZ) nightly: /app missing" >&2; exit 1; }

# cron's environment is bare (see ops/fly/entrypoint.sh, which writes this
# file from the real process environment at boot). Harmless when a
# scheduled Machine already has the secrets: sourcing it is a no-op that
# re-exports the same values.
if [ -f /app/.env.runtime ]; then
    # shellcheck disable=SC1091
    . /app/.env.runtime
fi

# The one thing that must not be inherited from a dev box: this image is
# the public posture (ops/fly/preflight.sh refuses DEV_TOOLS=1).
: "${SCOUT_PER_BRAND:=8}"
: "${NIGHTLY_BUDGET_USD:=5.00}"
export SCOUT_PER_BRAND NIGHTLY_BUDGET_USD

echo "$(date -u +%FT%TZ) nightly: starting (budget=\$${NIGHTLY_BUDGET_USD}, scout=${SCOUT_PER_BRAND})"

# Steps 1-3 of run_morning_prompts.sh -- metrics, the idea-agent bank, the
# research agent, the crawl. Each is never-fatal on the Mac and stays that
# way here: `|| true` keeps a dead lane from cancelling the walk, which is
# the half of the night that produces concepts.
python -m src.refresh_metrics || echo "$(date -u +%FT%TZ) nightly: metrics refresh failed (continuing)"
for BRAND in antihero zeropage; do
    python -m src.research_agent --brand "$BRAND" \
        || echo "$(date -u +%FT%TZ) nightly: research agent failed for $BRAND (continuing)"
    python -m src.scout run --brand "$BRAND" --count "${SCOUT_BANK_PER_BRAND:-8}" \
        || echo "$(date -u +%FT%TZ) nightly: scout pass failed for $BRAND (continuing)"
done

# The walk. Exit 1 means the breaker tripped or the budget stopped it --
# `fly machine status` and the nightly_runs row both then say so, which is
# the whole point of running this under a scheduler nobody watches.
python -m src.nightly walk
status=$?
echo "$(date -u +%FT%TZ) nightly: finished with status ${status}"
exit "$status"

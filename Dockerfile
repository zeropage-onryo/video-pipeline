# Fly.io / Railway image for the always-on studio (backlog #14 phase 5).
# Runs the SAME app.main:app that studio.command runs locally, plus ONE
# scheduled job: the Instagram token keeper.
#
# THE NIGHTLY WALK IS GONE (2026-09-28, Mike's call). This image used to
# cron `run_morning_prompts.sh` at 22:00 -- and it never once ran here:
# that script's first line cds into the Mac's project folder, which does
# not exist in this image, so it exited 1 every night into /var/log, which
# a redeploy wipes. The concept walk, the research agent and the scout
# crawl are no longer scheduled anywhere (the Mac's LaunchAgent went the
# same day, and the Mac runs none at all now); `python -m src.nightly
# walk` still runs by hand.
#
# What stays is `ops.ig_tokens keep`, daily at 10:00 ET (TZ below): it
# makes no Meta call until the publishing token's last refresh is 30 days
# old, then refreshes it into data/ig_token.json on the volume -- the
# long-lived token dies at 60 days, and nothing else refreshes it now.
# Its log lives on the volume too, so a deploy does not erase it.
#
# The 03:30 shadowrun (`python -m src.trigger`) was REMOVED 2026-09-14. It
# was an eleventh generation run every night that took neither the
# data/.nightly.lock nor the night marker run_morning_prompts.sh sets, and
# counted against no budget -- so it could double-run beside the 22:00 walk
# and overspend NIGHTLY_BUDGET_USD without appearing in it. src/trigger.py
# stays as a manual one-off CLI; nothing schedules it.
#
# Explicitly NOT included: footage/ (149GB ProRes) and the photo-root
# asset shelf framebank reads from -- backlog #14 phase 5 calls this out
# as "a split, not a move." Those lanes stay on the Mac or get
# pre-ingested to R2 first; this image only runs the web app + the one
# scheduled jobs against Postgres (phase 4) / Supabase RAG.
FROM node:22-bookworm-slim AS model-runtime
RUN npm install --global @openai/codex@0.153.2

FROM python:3.11-slim
COPY --from=model-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=model-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
RUN codex --version

ENV TZ=America/New_York \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg (2026-09-26, Assemble v0 -- src/cut/render.py): the cut's render of
# record, and ffprobe for measuring clips. Debian's build carries libass, so
# captions burn in here even though a Homebrew ffmpeg on the Mac cannot.
RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
        ffmpeg \
        supervisor \
        libheif1 \
        curl \
        tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# psycopg[binary] and pillow-heif ship prebuilt wheels for this base image --
# no build-essential / libpq-dev needed, which is what keeps this image small.
RUN pip install -r requirements.txt

COPY . .
# footage/ and the local asset roots are NOT copied in production --
# .dockerignore excludes them. If a step here needs them it belongs on
# the Mac (phase 5's "split, not a move"), not in this image.

RUN echo "0 10 * * *  root  cd /app && . /app/.env.runtime && python -m ops.ig_tokens keep --days 30   >> /app/data/ig_token_keeper.log 2>&1" > /etc/cron.d/zeropage \
    && chmod 0644 /etc/cron.d/zeropage
# NOTE: /etc/cron.d/zeropage (with its "root" user column) is picked up
# automatically by the cron daemon -- do NOT also `crontab` it, that
# command expects the OTHER format (no user column) and installing both
# would either error at build time or run the job twice.

COPY ops/fly/supervisord.conf /etc/supervisor/conf.d/zeropage.conf

EXPOSE 8000

COPY ops/fly/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

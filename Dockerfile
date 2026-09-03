# Fly.io / Railway image for the always-on studio (backlog #14 phase 5).
# Runs the SAME app.main:app that studio.command runs locally, plus the
# two nightly jobs that today live in launchd plists (com.zeropage.
# morningprompts at 22:00 ET, ops/com.zeropage.shadowrun at 03:30 ET) --
# cron replaces launchd, one-for-one, same commands, same schedule, same
# timezone (TZ=America/New_York below, so DST is handled the same way a
# Mac handles it: by wall-clock time, not a fixed UTC offset).
#
# Explicitly NOT included: footage/ (149GB ProRes) and the photo-root
# asset shelf framebank reads from -- backlog #14 phase 5 calls this out
# as "a split, not a move." Those lanes stay on the Mac or get
# pre-ingested to R2 first; this image only runs the web app + the two
# scheduled jobs against Postgres (phase 4) / Supabase RAG.
FROM python:3.11-slim

ENV TZ=America/New_York \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
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

RUN mkdir -p /var/log/zeropage \
    && echo "0 22 * * *  root  cd /app && . /app/.env.runtime && /bin/bash run_morning_prompts.sh   >> /var/log/zeropage/morning_prompts.log 2>&1" > /etc/cron.d/zeropage \
    && echo "30 3 * * *  root  cd /app && . /app/.env.runtime && /usr/local/bin/python -m src.trigger >> /var/log/zeropage/shadowrun.log 2>&1"      >> /etc/cron.d/zeropage \
    && chmod 0644 /etc/cron.d/zeropage
# NOTE: /etc/cron.d/zeropage (with its "root" user column) is picked up
# automatically by the cron daemon -- do NOT also `crontab` it, that
# command expects the OTHER format (no user column) and installing both
# would either error at build time or double-run the nightly jobs.

COPY ops/fly/supervisord.conf /etc/supervisor/conf.d/zeropage.conf

EXPOSE 8000

COPY ops/fly/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

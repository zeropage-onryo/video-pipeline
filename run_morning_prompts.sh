#!/bin/bash
# Nightly shadow batch. One run per spark in prompts/sparks.txt, per brand,
# so the hold queue fills with VARIED concepts to grade instead of several
# copies of a single rotating spark. Everything stays in shadow: render and
# posting are stubbed, so no credits are spent -- these are holds to grade.
#
# Runs BOTH brand/channel pairs every night -- antihero/antihero and
# zeropage/zeropage -- so each brand's own engine (concept_zeropage.txt /
# concept_ideas_zeropage.txt for Zero Page vs. the default templates for
# Antihero, per shootgen.build_concept_prompt / build_ideas_prompt) actually
# gets exercised and each channel's credit gate (autonomy.evaluator_agreement)
# keeps filling. Previously this only ran antihero/antihero, so Zero Page's
# queue never refilled with genuinely Zero Page content.
# The project root, repathed 2026-08-29 when the folder was renamed from
# "Github Portfolio". The rename broke this silently: launchd ran the
# script, the cd failed, and a night with no runs looks exactly like a
# healthy night unless something says so -- which is why the log below
# gets a line either way.
ROOT="/Users/iphone/Documents/PRODUCTION PIPLINE .GIT"
if ! cd "$ROOT"; then
  echo "$(date -u +%FT%TZ) morning: project root missing: $ROOT" >&2
  exit 1
fi

# Smoke mode. `touch data/.smoke` and the next run proves the whole
# launchd path works -- the agent fired, macOS let bash read a script
# under ~/Documents, the cd landed, and the log is writable -- then
# stops before a single billed call. Without it the only way to test a
# LaunchAgent is to run the real batch, which is 16 runs of Gemini and
# most of a day's NANO_DAILY_CAP just to answer "did it start".
if [ -f data/.smoke ]; then
  echo "$(date -u +%FT%TZ) morning: SMOKE OK — launchd reached the script, cwd=$PWD"
  exit 0
fi
source venv/bin/activate
mkdir -p data

# 1) Pull the latest post analytics (YouTube + Instagram) and promote the
#    fresh top performers into the proven_results RAG shelf, so tonight's
#    concepts ground on what's actually working. Never fatal: a missing key
#    or a down RAG store is logged and the batch still generates.
python3 -m src.refresh_metrics >> data/morning_prompts.log 2>&1

# How many of each brand's nightly runs get a researched spark instead of a
# rotated one. Defined here because BOTH steps below read it -- the scout
# pass sizes its bank with it, and the run loop spends it.
SCOUT_PER_BRAND="${SCOUT_PER_BRAND:-3}"

# 2) The research scout. One pass per brand banks scored sparks crawled off
#    the web / YouTube / feeds (src/scout.py). Never fatal and never
#    retried: a failed crawl leaves an empty bank, --scout below finds
#    nothing above its floor, and every run falls back to the sparks.txt
#    rotation exactly as it did before this step existed.
for BRAND in antihero zeropage; do
  python3 -m src.scout run --brand "$BRAND" --count "$SCOUT_PER_BRAND" \
    >> data/morning_prompts.log 2>&1 || \
    echo "$(date -u +%FT%TZ) morning: scout pass failed for $BRAND (falling back to sparks.txt)" \
      >> data/morning_prompts.log
done

# 3) For each brand, walk the whole sparks list so consecutive holds get
# varied directions instead of one pick. Passing --spark explicitly
# overrides the trigger's day-of-year rotation. Blank lines and # comments
# in sparks.txt are skipped. --channel and --brand are passed together and
# matched here, same as always -- src.trigger's own CLI now defaults an
# omitted --brand to whatever --channel is (orchestrator.run() does the
# same), so this explicit pairing is belt-and-suspenders, not load-bearing
# the way it used to be. A manual one-off `src.trigger --channel zeropage`
# with no --brand used to silently generate full Antihero content (real
# cast/locations) filed under the Zero Page channel -- that's what produced
# hold_queue row 13 / concept 111 on 2026-08-14 -- and can no longer happen
# by omission; it now takes an explicit --brand that disagrees with
# --channel to get a mismatch on purpose.
#
# The run COUNT is deliberately unchanged. The first SCOUT_PER_BRAND runs of
# each brand's walk add --scout, which swaps in a researched spark from the
# bank; the rest use the file as always. Scouted runs REPLACE rotation runs
# rather than being appended because 8 sparks x 2 brands is already 16 runs
# against NANO_DAILY_CAP's 20, shared with every Director render -- appending
# would starve the canvas of keyframes to buy a few more concepts.
#
# Each scouted run still passes its rotation spark. That is the fallback the
# scout node reads when the bank is empty or everything in it sits under
# scout.SCORE_FLOOR: without it, a thin crawl night would degrade to three
# identical runs on the one day-of-year pick instead of three distinct ones.
SPARKS=()
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  SPARKS+=("$line")
done < prompts/sparks.txt

for PAIR in "antihero antihero" "zeropage zeropage"; do
  read -r CHANNEL BRAND <<< "$PAIR"
  i=0
  for spark in "${SPARKS[@]}"; do
    if [ "$i" -lt "$SCOUT_PER_BRAND" ]; then
      python3 -m src.trigger --channel "$CHANNEL" --brand "$BRAND" --scout \
        --spark "$spark" >> data/morning_prompts.log 2>&1
    else
      python3 -m src.trigger --channel "$CHANNEL" --brand "$BRAND" --spark "$spark" \
        >> data/morning_prompts.log 2>&1
    fi
    i=$((i + 1))
  done
done

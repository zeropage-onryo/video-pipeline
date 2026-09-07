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
#
# 3 -> 8 on 2026-09-01, which is every run in the walk. It was 3 while the
# researched half of a night could not be told apart from the rotated half:
# the graph took the spark and left the images in the bin, so a "researched"
# concept was a differently-worded prompt grounded on the same five asset-bank
# photos as every other one. With the bin now reaching the concept there is
# something to prefer, so the rotation stops being the majority and becomes
# what it was always described as -- the fallback.
#
# This does NOT add runs. The walk is still one per spark in sparks.txt, and
# a scouted run still carries its rotation spark, so a thin crawl night
# degrades to exactly the old behaviour rather than to three identical runs.
SCOUT_PER_BRAND="${SCOUT_PER_BRAND:-8}"

# How many sparks one crawl pass banks. It used to be SCOUT_PER_BRAND itself,
# which made "how many runs may use research" and "how much research exists"
# the same number -- so every banked spark had to be servable or a run fell
# back. They are separated because next_spark only serves findings at or above
# scout.SCORE_FLOOR and never serves one twice: banking a couple more than the
# night can spend is what absorbs a low-scoring pass, and the surplus keeps
# for tomorrow rather than being wasted.
SCOUT_BANK_PER_BRAND="${SCOUT_BANK_PER_BRAND:-8}"

# 2) The idea agent's plans. Claude researches directions and the images to
#    ground them and leaves them as JSON in data/idea_agent/; this banks them
#    seconds before the runs that read them, HERE rather than over the mount,
#    because this is where refbin.fetch has a network and pipeline.db is a
#    local file. Runs before the crawl so the bank is filled best-first: a
#    hand/agent spark scores HUMAN_SPARK_SCORE and outranks a crawled one.
#    No plan is a normal night, not an error -- most nights nobody ran the
#    agent, and step 3 plus the sparks.txt rotation carry it exactly as they
#    did before this step existed.
python3 -m ops.bank ingest data/idea_agent >> data/morning_prompts.log 2>&1 || \
  echo "$(date -u +%FT%TZ) morning: idea-agent plans failed to ingest (falling back to the crawl)" \
    >> data/morning_prompts.log

# Generated references (src/refgen.py, 2026-09-06): every banked spark gets
# one still rendered from its hook frame in the brand's look, Midjourney
# first. Midjourney keeps its own per-run approval gate; uncomment the
# export to let the NIGHT spend AceData credits (~$0.27/still, capped by
# REFGEN_DAILY_CAP, default 8). Without it the night renders on Gemini's
# image model (NANO), which needs no approval and no extra key.
# export MIDJOURNEY_SPEND_OK=1

# 2b) The research agent (src/research_agent.py) -- Claude/Gemini with the
#    board's own MCP tools, banking sparks WITH reference images picked from
#    images_for's closed set. Turned on 2026-09-05. It runs HERE, before the
#    crawl, and not only via --research on the runs below, because
#    research_agent.bank_is_full() skips when the bank already holds
#    RESEARCH_BANK_TARGET unused sparks -- and step 3 fills exactly that many.
#    With --research alone the node was a no-op every night it was ever
#    passed. Order is therefore: agent, then crawl tops up what is left, then
#    sparks.txt. Never fatal; once a day per brand (data/.research stamp).
for BRAND in antihero zeropage; do
  python3 -m src.research_agent --brand "$BRAND" \
    >> data/morning_prompts.log 2>&1 || \
    echo "$(date -u +%FT%TZ) morning: research agent failed for $BRAND (the crawl still runs)" \
      >> data/morning_prompts.log
done

# 3) The research scout. One pass per brand banks scored sparks crawled off
#    the web / YouTube / feeds (src/scout.py). Never fatal and never
#    retried: a failed crawl leaves an empty bank, --scout below finds
#    nothing above its floor, and every run falls back to the sparks.txt
#    rotation exactly as it did before this step existed.
for BRAND in antihero zeropage; do
  python3 -m src.scout run --brand "$BRAND" --count "$SCOUT_BANK_PER_BRAND" \
    >> data/morning_prompts.log 2>&1 || \
    echo "$(date -u +%FT%TZ) morning: scout pass failed for $BRAND (falling back to sparks.txt)" \
      >> data/morning_prompts.log
done

# 4) For each brand, walk the whole sparks list so consecutive holds get
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
# bank; the rest use the file as always -- and at the current default of 8
# there is no rest, so the file becomes purely the per-run fallback rather
# than a second source of directions. Scouted runs REPLACE rotation runs
# rather than being appended because 8 sparks x 2 brands is already 16 runs
# against NANO_DAILY_CAP's 20, shared with every Director render -- appending
# would starve the canvas of keyframes to buy a few more concepts.
#
# Each scouted run still passes its rotation spark. That is the fallback the
# scout node reads when the bank is empty or everything in it sits under
# scout.SCORE_FLOOR: without it, a thin crawl night would degrade to three
# identical runs on the one day-of-year pick instead of three distinct ones.
#
# `--research` implies `--scout` and adds the Claude agent in front of it, so
# the tiers are: what Claude banked, then what the crawl banked, then the
# rotation. Passing it to every run in the walk is safe and deliberate --
# research_agent stamps one paid attempt per brand per day and skips a bank
# that is already full, so runs two through eight cost a database read. With
# no ANTHROPIC_API_KEY the node reports that and the night is exactly the
# night it was before.
# THE WALK ITSELF IS PYTHON NOW (src/nightly.py, 2026-09-07). Everything
# above this line is unchanged; the bash loop that used to live here is
# not, because bash had no opinion about failure. One DNS miss to the
# Supabase pooler used to run the other fifteen sparks into the same dead
# socket; a depleted Gemini card was retried six times per call in all
# sixteen; a spent image cap produced sixteen identical "no keyframe"
# holds. The runner asks those questions ONCE (preflight), stops on a
# systemic failure while continuing past a content one (the breaker),
# stops at NIGHTLY_BUDGET_USD, drops keyframes rather than the night when
# the image cap is already gone, and writes a nightly_runs row so a night
# that never started can be told from a night that produced nothing.
#
# Same knobs: SCOUT_PER_BRAND is read from this environment (exported
# below so the runner sees the value this script resolved), the sparks
# still come from prompts/sparks.txt, and the pairing is still
# antihero/antihero + zeropage/zeropage.
export SCOUT_PER_BRAND
python3 -m src.nightly walk >> data/morning_prompts.log 2>&1

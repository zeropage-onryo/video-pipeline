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
cd "/Users/iphone/Documents/Github Portfolio" || exit 1
source venv/bin/activate
mkdir -p data

# 1) Pull the latest post analytics (YouTube + Instagram) and promote the
#    fresh top performers into the proven_results RAG shelf, so tonight's
#    concepts ground on what's actually working. Never fatal: a missing key
#    or a down RAG store is logged and the batch still generates.
python3 -m src.refresh_metrics >> data/morning_prompts.log 2>&1

# 2) For each brand, walk the whole sparks list so consecutive holds get
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
for PAIR in "antihero antihero" "zeropage zeropage"; do
  read -r CHANNEL BRAND <<< "$PAIR"
  while IFS= read -r spark || [ -n "$spark" ]; do
    case "$spark" in ''|\#*) continue ;; esac
    python3 -m src.trigger --channel "$CHANNEL" --brand "$BRAND" --spark "$spark" \
      >> data/morning_prompts.log 2>&1
  done < prompts/sparks.txt
done

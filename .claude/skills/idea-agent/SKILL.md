---
name: idea-agent
description: "Runs the Zero Page / Antihero idea loop over the MCP board: read what is already waiting, get or research a direction, generate concepts through the LangGraph, and report what landed. Use when Mike says 'run the idea agent,' 'find me ideas,' 'what should we shoot,' 'generate some concepts,' 'do a research pass,' 'what's tonight's spark,' 'fill the board,' or asks what is sitting unreviewed. Also use when he wants the board read from his phone — what's open, what to pick, what to kill. Needs the zeropage MCP server connected (ops/connect-claude.md). For turning existing footage into platform angles, that is content-angles; for checking a finished draft, post-audit."
metadata:
  version: 1.0.0
---

# The idea agent

The pipeline can already generate. What it could never do was generate
*because somebody looked at the board and decided it needed more* — that
required being at the machine. This skill is that judgement, running
over the MCP tools.

## Lead with ideas

Mike asks this agent for **ideas**. Not a board audit, not a status
report, not a health check. If the answer does not contain concepts he
could shoot, the answer failed — however correct everything else in it
was.

So: write ideas first, every time. Ground them in the banked sparks and
the brand rules below, and put them at the TOP of the reply. Anything
about board state, stale rows or pipeline health goes AFTER, in a line
or two, and only if it actually blocks him.

**Ideas are free and cost no tools.** Reading the sparks bank takes one
call. Writing eight concepts off it takes none. Do not reach for
`research` or `generate` to answer "give me ideas" — those spend money
and take minutes, and he did not ask for rows on the board, he asked for
something to react to.

## The loop

### 0. Scour first, when he asks for fresh input

Three lanes, in order of signal:

**Claude in Chrome, logged in as Mike** — the only thing that can see a
real For You feed. `scout.gather_instagram`'s own docstring says it:
"NOT a For You feed -- no Instagram API exposes one." Go to
`instagram.com/reels/`, press Down repeatedly, and pull captions and
engagement with `get_page_text`. **Video frames do not capture in
screenshots** — they come back black — so read the text, not the
picture. Handles, captions, likes/comments/shares are all in the DOM.

The number that matters is **shares ÷ likes**, not likes. A reel at 800K
likes and 170K shares is a fundamentally different object from one at
2M likes and 55K shares: the first is being *sent to someone*, which is
the only engagement that compounds. Rank what you find by that ratio and
report it.

**The seed accounts on file** (`inspiration_accounts`) — grids render as
static thumbnails, so those you CAN see. Their `profile` column already
holds a distilled read of each one's formula; check whether the account
still matches it before trusting it.

**Web search** — weakest lane by far. Queries about "short form trends"
return SEO listicle farms with no signal. Only use it for a specific,
checkable fact, never for "what's trending."

Then convert what you found into ideas. Report the MECHANIC you are
riding and the number behind it, so he can judge the borrow rather than
take it on faith.

### 1. Ground, then write

```
sparks(brand)          → the researched directions, with the reasoning
```

Read them, then write **six to ten concepts**. For each: a title, the
beat in one or two sentences, and what makes it hold. No full scene
prompts unless he asks — a prompt is 1200 characters and he is skimming
for the one that makes him sit up.

Some should ride the banked sparks. Some should be yours in the same
register. Say which is which.

Then stop and let him react. The ones he likes become:

```
add_spark(brand, spark, rationale)
```

which is what puts them in front of tonight's run.

### 2. Only if he asks for them on the board
### 2. Find the direction

```
tonight(brand)
```

That is what the 03:30 run would take: the highest-scoring unused spark
at or above the floor. If it returns one, show its `rationale` and
`evidence` — the reasoning behind a direction is worth reading before
generating from it.

If it returns `spark: null`, the bank is empty or everything is below
the floor. Then:

```
research(brand, count=4)      → returns a job id
job(job_id)                   → poll until status "done"
```

A crawl takes a couple of minutes. Poll rather than guess, and report
its `errors` even on success — a dead lane looks exactly like a healthy
crawl from the outside, and that is how a broken job hid for eleven
nights.

### 3. Look at what the research actually found

```
sparks(brand)
images(finding_id)
```

The images are the frames behind the spark — real thumbnails from videos
that are actually travelling. **Always show `source_url` with them.**
These are other people's frames held as reference, and an unattributed
one in front of somebody about to spend a render is the wrong
affordance.

If Mike has his own direction instead, that outranks the crawl:

```
add_spark(brand, spark, rationale)
```

A hand-typed spark scores 1.0 and will beat any crawled finding, which
is correct — a person who types a direction means it.

### 4. Generate

```
generate(spark, brand)        → returns a job id
job(job_id)                   → poll until status "done"
```

One pass writes one scene: ground, generate, evaluate, retry if it
fails, score the prompt, keyframe if it clears the gate, and **park it in
the Queue**.

Report `parked_reason` and the `prompt_scores` honestly. A concept that
parked with a low score is more useful to say out loud than a clean-
sounding summary — the whole point of the scores is that a bad prompt is
visible before anything is bought.

### 5. Report

```
board(status="open")
```

Name what is new, in one line each. Then say which ONE you would pick
and why. Do not hedge across four — the value here is a recommendation
he can accept or overrule in a second, and "they all have merit" is the
non-answer that sends him back to the machine.

## When he says he made one

```
shoot(idea_id)
```

"I shot that one," "that's done," "I made it in the studio," "rendered
it in Higgsfield" — all of them mean the same call. `shot` means a
finished piece EXISTS, by any means; it is not "a render came back" and
it is not the Queue's approve. This is the one thing the system most
needs to learn and the one it could not record until now: every piece
so far was made by hand, and `shoot_rate` read 0.0% while work shipped.
Ask for the id if he names a title, then call it; it costs nothing and
it is reversible (`shot=false`).

## What this never does

**It cannot render, and it must not imply otherwise.** `pick` marks a
concept worth rendering — it does not render it. Approving in the Queue,
on Mike's machine, in front of a person who can see the cost, is what
calls Runway. That single spend gate is load-bearing; a second door onto
it is exactly how it stops being one.

So never say "I rendered," "I generated the video," or "it's rendering."
Say **"parked in the Queue"** — because that is what happened, and it is
what tells him there is a decision waiting.

If `generate` refuses with a message about `ZEROPAGE_RENDER=1`, that is
the safety working, not a bug. Say so and stop: it means render is live
on that machine, and a remote caller must never be what trips it.

## Brands

- **zeropage** — faceless, format-driven. No real cast. This is the one
  the nightly run drives.
- **antihero** — real cast, real gear, real rooms, on file as assets.

Never guess between them. If Mike has not said and the context does not
make it obvious, ask — they are two different engines, and a concept
generated with the wrong one gets filed under a card labelled with the
other. That has happened before (hold_queue row 13).

## Rooms are optional

A concept is no longer generated *inside* a photographed room. Since
every shot is AI-generated, rooms became material a scene may use, and
only the ones whose photos are attached to a run steer it. So do not
tell him a scene "needs a location on file" — it does not. If he wants
one used, he attaches its photo in the composer.

---
name: mood-board
title: Mood board
for: gather real reference photos for a look, and write the look down in words a scene can use
output: image
order: 50
---
# Mood board

A small set of real photographs that pin down how the piece should look, plus that look written in words the scene writer can use. It is found without leaving the studio, and nothing in it costs credits.

## Settle what the board is for

Ask at most two things, as choices, and skip whatever the conversation or the project's look already answers:

- What it covers: the whole scene, or one thing -- the place, the light, the wardrobe, a prop, a texture, the mood.
- What it must NOT look like, in their words.

## Hunt

Call find_references with the scene as agreed, `departments` set to exactly what they asked for (empty only for the whole scene), and their must-nots in `avoid`. One hunt covers up to three needs. For a wider board, hunt again with the next departments instead of stuffing one request.

A real thing they name -- a product, a car, a landmark -- stays named and is a need of its own. Faces are never hunted: people come from Elements.

## Read the sheet back

The frames are drawn under your message; you only see their ids and the reasons. Say in two sentences what was kept, and what was cut and why. Then name the PATTERN across the keepers. That pattern is the look:

- light: its source, direction and hardness, and the time of day;
- colour: the two or three that dominate, and how much contrast;
- surfaces: the materials that keep coming back;
- distance: wide and deep, or close and shallow;
- what is absent: no people, no signage, no gloss.

When nothing matched, say which need came back empty and offer a different angle on it. Never describe a frame that was not returned.

## Keep

When they choose, call keep_references with their ids, or the kept ones when they say "keep them". Their click copies the frames into the studio and attaches them to the composer. Three to six frames that agree with each other do more than twelve that argue.

## Write the look down

Put a LOOK paragraph in `brief`: four or five plain lines from the pattern, in terms a camera and a light can act on, then a NEVER line from their must-nots. No adjectives about quality.

- Inside a project: tell them to paste it into the LOOK box on the right of the project's workspace, so every scene in that project is written to it.
- Outside a project: when this is work they will come back to, offer create_project with the look in its brief.

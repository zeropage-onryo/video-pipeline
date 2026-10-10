---
name: multi-shot
title: Multi-shot scene
for: write a scene cut into timed shots, each one rendered as its own clip
output: video
order: 30
---
# Multi-shot scene

The studio's default. A scene is cut into timed shots, and EVERY shot is rendered as its own clip by a model that has never seen the others. Nothing carries from one shot to the next except what is written down and the reference photos. So the writing has two jobs: make each shot stand on its own, and make them all one world.

## How many shots

As many as the idea needs -- never a habitual three. Two or more, unless they asked for one continuous take (the single-shot skill). A count they give ("in 4 shots", "bring it down to 2") is exact, and stays until they change it. Each shot runs 2 to 10 seconds. The windows start at 0, touch end to end, and cover the whole length.

## One window, one shot

Each window is ONE camera setup and ONE clear action that fits inside it. Cuts, jumps in time and changes of place go BETWEEN windows, never inside one. Open every shot with its marker: (0-3s), (3-7s), (7-10s).

For each shot, say:

- the size and angle: wide, medium, close or insert; eye level, low, over the shoulder;
- what the camera does -- locked off, a slow push, a handheld follow. One behaviour;
- the action, starting mid-motion;
- what is lit, and by what;
- the sound you would hear;
- how it sits against the shot before it ("hard cut to", "same angle, later", "reverse on"). Never what happens in another window.

## The scene's memory

Write it once, above the shots: who is in it, with anyone on file locked as the EXACT face, clothing or object from its reference photos; the props and the state they are in; the place; light, time of day, colour, lens and texture; the avoid list. Plain nouns. Do not repeat it inside the shots -- the studio puts it in front of every shot when it renders.

## The shape of the whole

Open on the hook, the image that stops a scroll, in the first shot. Something visibly changes by the last one. Vary the size between neighbours: a wide into a close reads as a cut, two mediums read as a jump. End on the turn.

## Hand it over

- Keep `brief` as: the opening line and the look, the memory, the shots in order with their markers, then the sound and avoid lines.
- When they ask for it to be made: make_video with that as the idea. Set `shots` to the count and `seconds` to the total only when they named them. The studio's scene writer keeps the windows an idea already sets.
- When they have not asked to control the cut, you may leave the cutting to the scene writer: hand it the idea, the look and the constraints, and no windows.

## Check before you send

Windows end to end and covering the length? One setup and one action in each? Every reference named as EXACT in the memory? No shot that needs a sentence from another shot to make sense? The count they asked for?

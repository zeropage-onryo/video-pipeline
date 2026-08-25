# Multi-shot sequences via Extend Video chaining

Builds on `references/models/seedance25/cheat-codes.md` technique #6 (Extend Video
continuity) and #8 (references). Use this file when the request is for more than one
connected shot in a continuing sequence — not a single isolated clip — and pair it with
whichever model's own `prompting.md` for per-model syntax; this file covers sequence-level
structure only.

## When to use this

A chase, a walk-and-talk, an establishing shot into an action beat, an arrival — anything
where shot 2 needs to pick up physically where shot 1 left off, or where several distinct
camera angles need to read as coverage of the same continuous moment rather than
unrelated clips.

## Timestamped shot breakdown

Once a shot has more than one beat, or a beat needs to land at a precise moment (a corner
apex, an exit, a stop), write the breakdown as timestamps instead of one paragraph:

```
SHOT: [sequel/prequel/coverage], [N] seconds [relationship to source clip, if any].
- 0:00–0:0X — [setup beat]
- 0:0X–0:0Y — [hero beat, if there is one — named as such, given more duration than
  the setup/landing around it]
- 0:0Y–0:0Z — [landing beat]
```

## Chaining a sequence from one source clip

A full sequence doesn't need to be one shot — it can be built by chaining Extend Video
calls outward from a single source clip:

- **Prequel** — Extend Video before the source clip's first frame, ending matched exactly
  to that frame's lean/speed/lighting/camera position.
- **Sequel** — Extend Video after the source clip's last frame, starting matched to that
  frame's state.
- **Coverage** (new angle, not a continuation) — a separate generation covering the same
  moment from a different camera position. This is not an Extend Video call — pull
  continuity from the source clip's frames in text (per cheat-codes.md #8), don't attach
  the source frame as an image seed, since that anchors the model to the source's actual
  camera position instead of the new angle being asked for.

Each prequel/sequel still needs cheat-codes.md #6's frame-by-frame continuity discipline —
anchor to the exact state of whichever end of the chain is currently being extended, not a
generic restatement of the subject.

## Camera matches motion, with exactly one exception

While the subject is moving, the camera moves with it: matched-speed tracking, banking
into a lean the way the subject banks, easing from tracking into a static hold exactly as
the subject decelerates to a stop. State this explicitly in the prompt. The one sanctioned
exception is a reveal move (pull-back, crane-up) *after* the subject has fully stopped —
with nothing left to match, that's the one moment an independent camera move earns its
place. Name it as the one exception, so the model doesn't take it as license to drift the
camera elsewhere in the shot too.

## Framing a stop as success, not failure

When a beat is supposed to end in deceleration or stillness, say so directly:

> This stop is the intended ending, not a failure state.

Otherwise a model optimizing toward "the subject looks active" can second-guess an
intentional slow-down.

## Escalation-constraint phrasing

For any constraint where "some amount of X" isn't enough, phrase it as a
must-read-as-this-not-that contrast instead of a bare adjective:

> The lean must read as a real, committed cornering lean — not a gentle drift or a wide,
> flat arc. Tires visibly gripping, weight clearly shifted into the turn.

A bare adjective ("fast," "dramatic," "committed") is the first thing a model waters down
under its own risk-aversion; a positive/negative contrast gives it a bar to clear.

## Worked example: a six-shot chase sequence from one source clip

A motorcycle tunnel-chase sequence, built entirely from one ~5-second source clip (rider
mid-tunnel, already at speed, low three-quarter tracking camera):

1. **Source clip** — given, not generated.
2. **Launch (prequel)** — Extend Video prequel: bike stationary, engine idling, headlight
   snaps on, hard launch, ending matched exactly to the source clip's opening state.
3. **Coverage angle** — a behind-the-shoulder chase-cam angle on the same mid-tunnel
   moment; continuity pulled from the source clip's frames in text, no image seed, since
   this is a different camera covering the same moment, not the same take continuing.
4. **Exit (sequel)** — Extend Video sequel off the source clip's last frame, timestamped
   exit at a specific second, grade shifting as the environment changes.
5. **Coverage angle** — a low, static, locked-off whip-past on the same tunnel stretch,
   same continuity discipline as step 3.
6. **Arrival (sequel, timestamped, with a reveal)** — Extend Video sequel off the exit
   clip's last frame: a cornering lean given its own hero-beat duration, camera banking to
   match the lean, easing to a static hold as the subject stops, then one pull-back-and-
   crane-up reveal after the stop to close the sequence wide.

What made it work as a *sequence* rather than six disconnected clips: every sequel/prequel
anchored to the exact frame-state of whichever clip it extended, every coverage shot
pulled continuity from the source's frames instead of an AI-generated stand-in image, and
the one camera-independence move (the final reveal) was held back until there was nothing
left to match motion to.

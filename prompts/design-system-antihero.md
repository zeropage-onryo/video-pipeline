# Antihero design system — carousel covers & slides

Derived from `prompts/brands.txt` (the `[antihero]` block), not from a fresh
Pinterest search — Michael's personal brand already has a locked visual
language from the video pipeline; this just translates it into the
color / font / layout format carousels need (per the "design system + design
MD file" pattern from the Duncan Rogoff video, and the 3-color / 2-font /
1-layout rule from the Alex video).

This is for **Antihero** carousels — Michael-as-subject content (the
stylized-self carousel is this brand, not Zero Page). If a carousel is for
Zero Page Films instead (product/trend/client content, no recurring
on-screen person), swap the accent per `brands.txt`'s zeropage block and
drop the character-first layout notes below.

---

## Colors — 3, fixed roles

Background and primary are locked. Accent is a **swappable single slot** —
the brand doc explicitly offers two options (deep red or hot purple), so
this system keeps both as named modes. Pick one mode per carousel, never
mix both in the same post — that's still "3 colors," just with a choice on
which third one.

| Role | Hex | Why |
|---|---|---|
| **Background** | `#0B0B0D` | Near-black, matches "crushed shadows and deep blacks" from the brand doc — not pure `#000` so it holds detail/grain instead of clipping. |
| **Primary (ink/text)** | `#EDE7DD` | Warm bone/off-white — reads as "warm practical light" against the cool black, not a cold pure white. |
| **Accent — Mode: Red** (default) | `#A31221` | Deep red — matches the racing jacket (white/black/red) already established in your LinkedIn banner and reference photos. |
| **Accent — Mode: Purple** | `#5A1A6B` | Hot purple — the brand doc's alternate option. Use for grid variety (e.g. alternating red-mode and purple-mode posts per the grid-consistency rule) or for a specific carousel that wants a different mood. |

Used sparingly either way: kicker labels, page numbers, the swipe arrow,
one highlighted word max per slide. When briefing an image tool or writing
the HTML for a slide, just state which mode — everything else in this doc
stays identical.

## Fonts — 2, fixed jobs

| Role | Font | Job |
|---|---|---|
| **Display** (hook/headline) | **Bebas Neue** (Google Fonts, free) | Tall, condensed, all-caps — movie-poster/title-card energy that matches "neo-noir," "quietly menacing." This is the font that stops the scroll. |
| **Body** (everything else) | **Inter** (Google Fonts, free) | Neutral, clean, no personality of its own — captions, kickers if not using accent color, footer text, page numbers. |

Never a third font. If body text needs emphasis, use the accent color or
weight (Inter has a real bold), not a new typeface.

## Layout — 1 template, reused every time

**Cover slide (slide 1 — the one that earns the click):**

```
┌─────────────────────────────┐
│ ANTIHERO            1/7     │  ← kicker (Inter, small, tracked caps,
│                              │     accent color) — top-left brand mark,
│                              │     top-right page counter
│        [full-bleed           │
│         portrait/photo,      │
│         subject right or     │
│         center third,        │
│         dark + high-contrast │
│         per brand grade]     │
│                              │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │  ← bottom-up black→transparent scrim,
│ HEADLINE IN BEBAS NEUE       │     bottom ~40% of frame, for legibility
│ bottom-left, large, primary  │
│ color, all caps                                    ↘  │  ← swipe arrow,
└─────────────────────────────┘     accent color, bottom-right
```

**Body/value slides (2 through n-1):** same header zone (kicker top-left,
page counter top-right, same background treatment) so the grid reads as
one continuous piece — content zone centered with generous margin,
footer handle (`@zeropagefilms` or however you're branding Antihero on
each platform) small and centered at the very bottom.

**Last slide (CTA):** same template, headline swapped for the ask, no
page counter (signals "end").

Aspect ratio: 4:5 (1080×1350) — Instagram/LinkedIn carousel standard, matches
what all three source videos used.

---

## How to use this

Feed this whole file (or just the tables) to whichever image tool
generates the cover — Higgsfield Soul ID once that's connected, or as
itemized change instructions to any model. The body slides can be built
directly from the color/font/layout tables in HTML/Claude Code, no image
model needed, per the hybrid workflow in `task-carousel-generation.md`.

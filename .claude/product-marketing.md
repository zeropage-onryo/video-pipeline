# Product Marketing Context — Zero Page AI Studio

> Keystone file. Every marketing skill in the bundle reads this FIRST, before asking you
> anything. Keep it accurate and it stops the skills from re-interrogating you each run.
> Lives at `.claude/product-marketing.md`.
>
> **Status: V2 — corrected to the current project.** `[DECISION NEEDED]` marks the calls that
> are genuinely yours to make (audience, product-vs-agency, pricing). Everything else is fact,
> pulled from the actual build.

**Document version:** 0.2
**Last updated:** 2026-08-04

---

## 1. Product Overview
- **One-line:** Zero Page AI Studio — a grounded AI film studio that turns your real rooms and
  footage into concepts, shot lists, and one AI-generated shot per edit, with every proposal
  checked in code against what actually exists.
- **What it does:** A dark, cinematic web app (FastAPI + Jinja) over a Python pipeline.
  *Pre-production:* photograph a space → Gemini vision describes its geometry/light/constraints →
  generate concepts and ideas grounded in those real rooms → swipe a deck to shortlist → a ≤6-shot
  plan with exactly one paste-ready AI-video prompt (Veo / Kling / Runway).
  *Post-production:* ingest footage (ffprobe + Whisper + vision → a manifest) → story pitches →
  validated cut lists (real filenames, real in/out points). A PostgreSQL + pgvector reference
  library grounds generation in your taste. The pipeline ends at a validated cut list you execute
  by hand.
- **Category / shelf:** AI video pre-production / AI filmmaking tool — sits near Runway, Google
  Flow, LTX, Descript, but positioned as the *grounded, opinionated finisher* rather than a
  generic clip generator.
- **Product type:** `[DECISION NEEDED]` self-serve web tool, done-for-you agency, or both. (The
  current build is a self-serve tool.)
- **Business model & pricing:** `[DECISION NEEDED — see the pricing skill]`. Candidates:
  usage/generation-based, tiered subscription, or agency retainer + tool.

## 2. Target Audience
- **Who:** `[DECISION NEEDED — pick the primary]` (a) solo filmmakers/editors who want cinematic
  output fast, or (b) creators/brands who need video but can't afford full production.
- **Primary use case:** Go from the real rooms and footage you actually have to a shootable,
  on-aesthetic plan (and cut) without a full crew or edit bay.
- **Jobs to be done:** "Decide what to shoot with what I have." · "Keep everything on one
  consistent look." · "Cut it down without hiring an editor."

## 3. Problems & Pain Points
- **Core challenge:** Deciding what to shoot, and editing to a consistent house style, is slow,
  expensive, and skill-gated. Generic AI tools produce output with no coherent aesthetic and call
  for shots and rooms you can't actually deliver.
- **Why current solutions fall short:** Generators invent a world and shots you don't have;
  template editors look templated; a crew + colorist is expensive and slow.
- **What it costs them:** Time, money, and a body of work that doesn't hold together across pieces.

## 4. Differentiation / Positioning
- **The wedge:** Grounded, not generative-by-default. *"The model proposes; code enforces."* A
  concept set in a room you haven't photographed is rejected; an edit is validated against real
  filenames and durations; exactly one AI shot per edit. Aesthetic consistency comes from the
  RAG-grounded corpus plus locked grade / tone / pacing.
- **Proof / credibility:** Founder is an actor / editor / colorist shooting on Blackmagic 6K, with
  a noir, high-contrast sensibility (The Batman, Enemy). The tool encodes a real filmmaker's
  judgment, not a generic model.
- **Against Flow / Runway specifically:** They generate a world; this grounds in yours and
  finishes it. They're style-agnostic; this is opinionated.

## 5. Voice & Aesthetic
- **Brand look:** Near-black (`#0B0B0D`), crimson accent (`#E23B2E`), Bebas Neue display over IBM
  Plex Mono labels and Inter body, film grain. Gritty noir, high contrast.
- **Copy voice:** Direct, unvarnished, technical, filmmaker-to-filmmaker. No hype, no motivational
  filler, no emoji, no overclaiming.
- **What to avoid:** Generic "empower your creativity" AI-tool copy. Breathless marketing-speak.

## 6. Two-Audience Note (personal brand)
Zero Page Films (moto / film / craft — the product) and the AI-engineering personal brand are
SEPARATE audiences. Marketing skills default to the *product* audience unless told otherwise. For
the AI-eng brand, say so explicitly — different platform mechanics, different voice.

---

## Changelog
- **0.2 (2026-08-04):** Rewritten to the current project — the AI Studio reframing, real rooms →
  ideas → shoot, footage-as-library, "code enforces" positioning, and the actual design tokens.
  Removed the stale Resolve-timeline / beat-sync description. Strategic fields (audience,
  product-vs-agency, pricing) left flagged as decisions.
- **0.1 (2026-08-04):** Initial draft, pre-filled from context. Unconfirmed.

# Runway-style dark theme — Director node canvas restyle

## Context for Claude Code

The Director node canvas already exists and is functionally complete:
`app/static/zpf/workflows.js` (rendering + interaction) running on the vendored
`app/static/zpf/vendor/litegraph.js`, wired up by `app/workflow_runner.py` and
`src/workflows.py`. **Do not change the execution logic, node graph model, or
the run/save wiring.** This is a pure visual + copy restyle: colors, typography,
node card layout, comment-box styling, connector/port styling, and the
node-search palette. Reference screenshot is Runway's Workflows tool
(`app/video-tools/.../ai-tools/workflows/...`), which is NOT built on
LiteGraph — it's a custom canvas UI, most likely React Flow under the hood.
We are reskinning our existing LiteGraph canvas to *look* like it, not porting
to a different graph engine.

Attached reference image shows a 4-node "Prompt enhancement" workflow. Match
this layout and theme for our "Prompt enhancement" template (the one already
seeded per the Director brief: User Prompt → Ground → Enhance → Generate).

---

## 1. Color tokens

Define these as CSS custom properties (or the equivalent constants in
`workflows.js`'s draw/theme setup) so the whole canvas reads from one palette:

| Token | Hex | Used for |
|---|---|---|
| `--canvas-bg` | `#0a0a0a` | Full canvas background |
| `--canvas-dot` | `#1f1f1f` | Dot-grid pattern dots |
| `--node-bg` | `#18181b` | Node card body |
| `--node-border` | `#2a2a2e` | Default node card border |
| `--node-border-hover` | `#3a3a40` | Node card border on hover/selection |
| `--node-header-icon-bg` | `#27272a` | Small icon chip inside node header (sparkle icon) |
| `--text-primary` | `#f4f4f5` | Node titles, primary labels |
| `--text-secondary` | `#8a8a92` | Placeholder text ("Output will appear here"), subtitles |
| `--accent-purple` | `#a78bfa` | Comment/annotation box — "instruction" type |
| `--accent-green` | `#4ade80` | Comment/annotation box — "process" type; also active output port + edge color |
| `--accent-red` | `#f87171` | Comment/annotation box — "output/result" type |
| `--accent-blue` | `#60a5fa` | Unconnected input port ring |
| `--button-primary-bg` | `#f4f4f5` | "Run"/"Run all"/"Publish" solid buttons (white/light on dark canvas) |
| `--button-primary-text` | `#0a0a0a` | Text on solid white buttons |
| `--button-ghost-bg` | `#1c1c1f` | "Run" button on individual nodes (dim, disabled-looking until connected) |
| `--divider` | `#26262a` | Hairline separators (top bar, node header/body split) |

Background: solid `--canvas-bg` with a subtle repeating **dot grid** —
1px dots, `--canvas-dot`, spaced ~24px apart. No gradient, no vignette.

---

## 2. Top bar

Fixed header, full width, `--canvas-bg` background, bottom border
`1px solid var(--divider)`, height ~56px, horizontal padding ~20px.

Left to right:
1. Back chevron (`‹`) icon button
2. Lock icon + "Private" label (muted `--text-secondary`)
3. `/` separator
4. Workflow title, bold, `--text-primary` — editable in place (e.g. "Prompt enhancement")
5. Overflow `...` icon button
6. *(flex spacer)*
7. "Last saved about N hours ago" — `--text-secondary`, small size
8. Icon button: share/export
9. Icon button: document/notes
10. Solid button "Publish" — dark filled pill matching canvas (`--node-bg` bg, `--text-primary` text, subtle border)
11. Solid button "Run all" with an info `ⓘ` glyph — **this one is the bright/white pill**: `--button-primary-bg` background, `--button-primary-text` text, rounded-full
12. Icon button: help/question circle
13. Icon button: overflow `...`

## 3. Left floating rail

Vertical pill-shaped toolbar, fixed to the left edge, vertically centered-ish
(starts a bit below the top bar), `--node-bg` background, rounded corners
(~16px), subtle border, stacked icon buttons top to bottom:

1. `+` — white circular button, slightly larger than the others, sits *above*
   the rail as its own floating white circle (this is what opens the node
   search palette)
2. Grid/layout icon (has a small blue notification dot on it)
3. Folder icon
4. Tag icon

Icons are ~20px, muted `--text-secondary`, spaced ~16px apart vertically.

## 4. Node search palette (the "+" overlay)

This is the panel currently open in the reference screenshot. Modal-ish, but
not centered — anchored near the left rail, floating over the canvas:

- Container: `--node-bg` background, rounded-2xl (~16px), border
  `1px solid var(--node-border)`, drop shadow, width ~720px, max-height ~700px
- **Search bar** at top: search icon + "Search by name or type" placeholder,
  full-width input, no visible border (just a bottom hairline under the whole
  search row), generous padding (~16px)
- **Left column** inside the panel (own vertical list, ~180px wide, no
  border, just text items with generous vertical padding): category tabs —
  "New nodes", "Video", "Image", "Audio", "Text" — active tab ("Image" in
  the screenshot) gets a white/light left accent bar and bright text; inactive
  tabs are `--text-secondary`
- **Right column**: scrollable list of node/model entries, each row:
  - 40px rounded-square icon/logo on the left (brand-colored gradient chip)
  - Title (bold, `--text-primary`) + subtitle (`--text-secondary`, smaller) stacked
  - Chevron `>` on the far right
  - Row height ~64px, hover state = subtle `--node-border` background wash
  - Example rows to replicate structurally (exact copy doesn't matter, keep
    the icon+title+subtitle+chevron pattern): "Image / Image", "Grok Imagine
    Image 2.0 (Image) / Text/Image to Image", "GPT Image 2 / Text/Image to
    Image", "Gen-4 / Text/Image to Image"
- **Footer row** pinned to bottom of the panel, hairline top border: label
  "Keep open to add multiple nodes" (`--text-secondary`) + a toggle switch
  (off = dark track, on = white track/knob) right-aligned

## 5. Comment / annotation boxes

Small floating rounded-rectangle labels that sit **above** a node to describe
what it does — these are NOT connected by edges to anything, they're free
captions positioned near the node they annotate. Each one:

- Padding ~10px 14px, rounded-lg (~10px), background `--node-bg` at ~90%
  opacity, **border color = the accent for its category** (2px solid):
  - Purple border → instructional text, e.g. *"Instructions for how [to
    write the prompt]"* — sits above the first/input node
  - Green border → process description, e.g. *"Enhances your prompt with
    vivid details"* — sits above the enhancement node
  - Red border → output description, e.g. *"Generates an image from the
    enhanced prompt"* — sits above the final generation node
- Text: `--text-primary`, small (~13px), line-height ~1.4, max-width ~180px so
  it wraps to 2–3 lines
- No connector line to these — purely positional captions, offset ~40–60px
  above their associated node

## 6. Node cards (the actual functional nodes)

Two node types visible, same card chrome:

**Card chrome (both types):**
- Width ~320px, `--node-bg` background, `1px solid var(--node-border)`,
  rounded-xl (~14px)
- **Header row** (padding ~14px 16px, bottom hairline `--divider`):
  small sparkle/model icon chip (24px, `--node-header-icon-bg` rounded
  square) + model name (`--text-primary`, semibold, ~14px) on the left;
  on the right, a small settings/sliders icon + a `...` overflow icon
  (both `--text-secondary`, ~16px)
- **Body**: large content area, min-height ~260px, centered placeholder text
  "Output will appear here" in `--text-secondary` when empty — this is a
  preview/output well, not an input field
- **Footer row**: right-aligned "Run" button — pill shape, small
  info `ⓘ` icon inline, `--button-ghost-bg` background, `--text-secondary`
  text (reads as inactive/secondary compared to the white "Run all" in the
  top bar)

**Node 1 — "Gemini 2.5 Flash"** (the enhance step): as above.
**Node 2 — "Nano Banana Pro"** (the generate step): identical chrome, empty
checkerboard/transparent-pattern placeholder in the body instead of text
(signals image output specifically) — use a subtle diagonal checkerboard
pattern in `--node-border`-toned squares to suggest "transparent/no image yet".

There is also a **collapsed/smaller node** visible bottom-left of the
screenshot (partially behind the palette) — a plain text-input style node
with just a text area and a "0 characters" counter bottom-right, resize
handle in the corner. This is the raw prompt-input node feeding into
"Gemini 2.5 Flash". Style it as a stripped-down version of the same card
chrome: no header icon row, just a large borderless textarea on `--node-bg`,
placeholder `--text-secondary`, character counter bottom-right corner.

## 7. Connectors / ports

- Ports are small circles (~8px diameter) sitting directly on the node
  card's left/right edge, not inline in a labeled row
- **Connected** output → input: solid line, color = `--accent-green`,
  slight bezier curve between the two ports, port dots filled solid green
- **Unconnected** ports: hollow circle outline, `--accent-blue` for
  inputs not yet wired, sit visible on the card edge even with nothing
  plugged in (this is different from our current style if ports are
  currently hidden when empty — make them always visible, just
  hollow/dim when unconnected)
- Multiple output ports can stack vertically on the same right edge
  (see "Gemini 2.5 Flash" in the reference — two green ports + one hollow
  blue port stacked on its right side)

## 8. Typography

- UI font: system sans-serif stack (`-apple-system, "Segoe UI", Inter,
  sans-serif`) — nothing decorative, this is a utility tool
- Sizes: top bar title ~15px semibold; node titles ~14px semibold; body/
  placeholder text ~13px regular; comment-box captions ~13px regular;
  palette row titles ~14px medium, subtitles ~12px regular, all on the
  `--text-secondary`/`--text-primary` pairing above
- No italics, no serif anywhere

## 9. What to leave alone

- Node graph data model, save/load, run/execute logic — unchanged
- The actual prompt text / model wiring for the seeded "Prompt enhancement"
  template — unchanged unless copy needs to shift to match the 3 caption
  strings above
- Any non-Director parts of the ZPF Studio skin (`/ui` Studio, Assets,
  Pipeline, Analytics, Queue views) — this restyle is scoped to the
  Director canvas only

## 10. Suggested implementation order

1. Extract current hardcoded colors in `workflows.js` / litegraph theme
   config into the token table above (CSS vars or a JS theme object)
2. Restyle node card chrome (header/body/footer, rounded corners, port
   visibility rules)
3. Add the comment/annotation box primitive (positioned caption, no edge)
   and place the 3 for the Prompt-enhancement template
4. Restyle the node search palette (two-column layout, search bar, footer
   toggle) if it isn't already close
5. Restyle the top bar and left rail chrome
6. Verify against `tests/test_workflows.py` — this pass should not need
   any test changes since behavior is unchanged, only rendering; if any
   test asserts on rendered class names/colors, update those expectations
   only

# invideo Editor — reference captures (T0, 2026-09-30)

These were captured in Mike's invideo account at ai.invideo.io, through Home → **Timeline Editor (Free)** → *Create a blank timeline*, in a new project called "ZPF editor reference (T0)". The only media were two of our own generated test-pattern clips. No Agent prompt was sent and nothing was generated or exported, so no credits were spent.

Every capture is 1549×784. The editor runs inside an embedded frame, so its controls were read from the screen, not from the page's markup.

| File | What it shows |
|---|---|
| `00-start-from-scratch.jpg` | The "Start from scratch" door: "Built for power and precision (cut, mix, color grade)", "Multiplayer", "Agentic (works with Agent Two)". |
| `01-project-notebook.jpg` | A project opens on a **Notebook**. Its tabs are Context / Notebook / Editor / Export, with timeline cards, a "Project crew" agents rail on the right, and a generate prompt at the bottom. |
| `02-editor-empty.jpg` | **The NLE, empty**: Source + Monitor viewers, the Inspector (showing timeline format with nothing selected), a bin panel bottom-left, a vertical tool column, Main Timeline, and an audio meter. The top bar holds the pages (Edit / Audio / Color / Preview / Structure), an agent picker, and a `main` branch selector. |
| `03-agent-panel.jpg` | **The agent panel** slides in on the far left ("Create a new agent") and pushes the whole editor right. |
| `04-import-media.jpg` | The Import media dialog: a Sequences / Import tab, a drop zone with the accepted formats, a folder upload, and per-file progress. |
| `05-clip-on-timeline-mismatch-warning.jpg` | A clip inserted from the Source viewer lands on V1 with linked audio on A1. A "Clip Mismatch Warning" offers to change the timeline to match the clip. Track headers are V3/V2/V1 and A1/A2/A3, with lock, eye or M/S, and source-patch boxes. |
| `06-clip-selected-inspector.jpg` | **Clip selected → Inspector**: LINKED badge; Transform (Fill/Fit, Zoom, Position, Anchor, Rotation, each with a keyframe diamond); Crop (four sides, Softness, Roundness); Playback (Speed, Ripple timeline, Reverse, Duration). |
| `07-transitions-tab.jpg` | The bin's Transitions tab: 72 transitions in groups (Fades: Cut, Dissolve, Fade, Smooth Cut; Wipes: …) and a search box. |
| `08-color-page.jpg` | **Color page**: Monitor, clip strip, Lift/Gamma/Gain/Global wheels, a Waveform scope, and a grading panel (Grades, Qualifier, Mask, Basic Correction, Color Control, Temperature and Tint, Vignette, Tone Curve). |
| `09-audio-page.jpg` | **Audio page**: audio-only timeline and a track mixer. Its strips are A1 **Voice**, A2 **Sfx**, A3 **Music**, plus Timeline and Main buses, each with FX, routing, pan and fader. The Inspector shows Volume/Pan (keyframable) and Fade curves. |
| `10-export-dialog.jpg` | **Export**: H.264 MP4 / Audio only / Still frame / Editable project, with Range, Resolution, Frame rate, Quality, and a Loudness target of **−14 LUFS**. |
| `11-keyboard-shortcuts.jpg` | The `?` sheet: a keyboard map with presets and a searchable command list. Space play/pause, Home/End, ←/→ step, Shift+←/→ jump 1 s, ⌘/ loop. |

## Checking our `/studio/cut` (T2) against it

**Where we already agree**
- The agent sits in a panel on the far left.
- Clips land as picture on V with linked sound on A, and the two move together.
- Sound is organised into the same three roles: voice / sfx / music.
- Export aims at −14 LUFS.
- The transport keys match (Space, Home/End, arrows, Shift+arrows).
- Versions sit behind a branch-like history: their `main` and checkpoints, our History and restore.
- A canvas mismatch is an explicit decision in both: their warning, our `set_canvas`.

**Where they go further, in rough priority**
1. **Two viewers.** A Source viewer (trim a clip before it goes in, plus Transcript and Metadata tabs) beside the timeline Monitor. We have one viewer, and trimming happens only on the timeline.
2. **A clip Inspector built on keyframes:** Transform, Crop, Speed and Reverse, each keyframable. Ours has source in/out, gain, a transition and duck. (Keyframe lanes are out of scope in `CUT_EDITOR_UI.md`.)
3. **Pages.** Edit / Audio / Color / Preview / Structure are whole layouts, not tabs. Our single layout keeps a Color seat that is shown but disabled.
4. **A real mixer:** per-track and bus faders, FX and routing. We have mute and solo on track headers, plus the three role levels.
5. **Transitions:** 72 of them against our one (`xfade`).
6. **The bin sits under the viewers, with more tabs** (Timelines, Edit Index, Markers, Effects, Fonts, LUTs). Ours is a left-panel tab shared with the agent.
7. **Export targets:** audio only, a still, and an editable project.

**Where we deliberately differ**
- **The look:** ZPF tokens, not invideo's grey (D1).
- **The tool strip is horizontal** above the timeline, not their vertical column.
- **Every edit is a server op and a version.** invideo's model can't be seen from the outside.

The reference project is still in Mike's invideo account and can be deleted from its Projects list.

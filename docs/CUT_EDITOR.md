# invideo Editor — deconstruction, and how ZPF builds the same thing (2026-09-26)

Mike: "invideo has an in-house AI video editing system. do a complete deconstruction of what they use and see how we can implement the exact same thing."

**Sources, and how sure each part is.**
- **Stated by invideo:** their launch post (1 Sep 2026), the /make/agentic-video-editor page, and the help-center article.
- **Read from their client code:** the public JS bundles on ai.invideo.io, plus a signed-in look at the home screen in Mike's Chrome.
- **Inferred:** anything marked *(inferred)*.
- **Not seen:** the NLE itself. It opens only after you send a prompt to Agent Two Lite, which can spend credits, so I stopped there. I can open it with Mike's OK.

---

## 1. What it is

**invideo Editor** launched on **Sep 1, 2026**. It is a browser NLE (non-linear editor, like Premiere) with an AI "assistant editor" built in.

- **The manual editor is free.** Credits are charged only when an agent does a job. That is the business model: the free editor gets people in, and the agents are what they pay for.
- **Three ways in** (confirmed on Mike's home screen): *Start from scratch* (a blank timeline), *Create a first cut* (upload footage plus a script), and *Use my Premiere Pro / DaVinci Resolve project* (import).
- **The composer has two modes, Agent and Editor.** They sit on the same prompt box, and the Editor mode opens the timeline as a modal (`timelineEditorModalStore`) on top of the Agent Two project.

## 2. The agent layer: 8 jobs, each a playbook

On the product page the "agents" are eight jobs, one per phase of editing:

| Agent | What it does (their words) | How it's almost certainly built *(inferred)* |
|---|---|---|
| **Assembly** | picks takes, cuts filler, makes the base cut; flags script lines nobody shot | Transcribes with word timestamps, lines the script up against the transcript, has a judge pick the best take per line, and writes the result as clips on the timeline |
| **Multicam** | syncs angles by audio and switches to whoever is speaking; one camera is the audio anchor | Cross-correlates the audio to find each angle's offset, uses speaker diarization to know who talks when, and cuts to the angle mapped to that speaker |
| **Search** | finds people, actions, objects, camera angles and emotions in the footage | Splits footage into shots, has a vision LLM log each shot, and embeds those logs so they can be searched alongside the transcript |
| **Cleanup** | removes silences and filler words, adds chapter markers | Silence detection on the audio, filler words from the transcript, and an LLM that writes chapters from the transcript |
| **Restructure** | reorders scenes, changes the pace, cuts to a set length | An LLM ranks segments, then it chooses the best set that fits the target length |
| **Grade** | correction, shot matching, looks | Per-clip color statistics used to match shots, plus LUTs (color lookup files) for looks |
| **Sound** | dialogue cleanup, ducking, the mix | Denoise, a loudness target, and music that drops automatically under voice |
| **Versions** | cutdowns, dubs, platform formats | Restructure run to shorter targets; dubbing with lip-sync; reframing for other aspect ratios |

Four more capabilities are listed separately:

- **Reference match:** "point the agents at the reference, and its pacing, structure, and style land on your footage."
- **Beat sync:** "mark the first few beats and the agents carry the pattern through."
- **B-roll:** generates missing shots, or searches iStock, Shutterstock and Storyblocks from inside the project.
- **Review comments:** the agent responds to frame-accurate review comments.

**The key claim is that the assistant "watches the footage before it cuts."** That is the moat. The agent never edits pixels. It reads an index of the footage (transcript, speakers, shots and what's in them), then writes edits into a timeline document as ordinary clips and cuts that the user can keep editing by hand.

This matches what we already know of their architecture (see `invideo_scene_construction_2026-09-18.md`): each workflow is a **markdown playbook** handed to the agent, the brain is Claude, Gemini or GPT in Lite/Pro/Ultra tiers, and there are 231 "sub-agents" (mostly generation models).

## 3. What their client code shows

Everything here was read from public bundles on ai.invideo.io today.

- **Agents write validated JSON, never free code.** The `protocol` chunk is a sandboxed runtime called `stage@1`, used for motion graphics and 3D (entities, cameras, lenses, constraints). A composition declares typed `inputs` (`number | boolean | text | color | enum | vec2 | vec3`, with min, max and options). Animation is keyframe `lanes`: integer `frame`, `step | linear | smooth` interpolation, and `linear | in | out | in_out` easing or a custom 4-number bezier. Every path is checked against a whitelist, `__proto__` is refused, duplicates are refused, and constraint cycles are refused. Assets must be flat `assets/name.ext` files whose extension matches their kind. **The takeaway: an agent's edit is a document that goes through a strict validator before anything renders.** Their NLE timeline almost certainly follows the same rule *(inferred)*.
- **Time is integer frames.** `frameCount = round(duration × fps)`. There are no floating-point seconds anywhere in the edit model.
- **The renderer runs in an isolated frame and reports back.** It posts `ready`, `loaded {frameCount}`, `frame`, `paused`, `error {phase: load|render, code: asset-url-expired|asset-load-failed}` and `captured {ImageBitmap}`. So preview renders in the browser, and a captured frame is sent back as a bitmap (used for thumbnails, and possibly so the agent can look at its own output *(inferred)*).
- **Other stack details:**
  - three.js (with its LUT shader code) and `detect-gpu`. They benchmark your GPU to decide how much to render locally.
  - Phoenix channels (Elixir) for realtime.
  - hls.js for streaming playback.
  - TipTap for the composer and React Flow for the canvas.
  - An internal "AI Playground" at playground.invideo.io for prompt versioning and tracing each LLM session, with token usage logged per prompt.
- **The GraphQL types include:** `projectTimelines`, `ProjectTimelineExport` (with feedback, views, description, bookmarks and a public slug; that is the review-link system), `DubbingSession` / `DubbingPrompt`, `CaptionPreset`, and a per-project credit limit (`SetProjectCreditLimit`).
- **What stays hidden:** the NLE's own code and its AI models load only once the editor opens. Web search, transcription and the vision models all run server-side, so none of it is visible from the client.

## 4. The pro tools: what they are, and what they're worth to us

| Feature | What it is | Worth copying for ZPF? |
|---|---|---|
| Multitrack, frame-accurate timeline: linked selection, snapping, markers, trim, ripple, retime | Table stakes for any NLE | **Yes, but minimal.** Tracks, clips, trim, split, move, markers. |
| Keyframes with custom bezier on transform, crop, opacity and effect parameters | The `stage@1` lane model | **Later.** Push-ins and Ken Burns are enough at first. |
| DAW with Voice/Music/SFX buses, dB faders and loudness metering | Pro audio | **Three fixed roles** (voice, music, sfx) with a gain per clip and an auto-mix. No bus UI. |
| Grading: wheels, curves, qualifiers, LUTs, waveform scope | A pro grading suite | **LUT looks plus automatic shot matching.** Skip wheels, curves and qualifiers. |
| Versions with branching and rollback, and session replay | Git for timelines | **Yes.** It costs almost nothing if every edit makes a new version. |
| Live collaboration with presence | Realtime co-editing | **No**, not until there are teams. |
| Review links with frame-accurate comments, and the agent answering them | The client-review loop | **Yes**, in a later phase. It fits the agency buyer in `positioning.md`. |
| Export to Premiere, FCP and Resolve, and import from Premiere and Resolve | Interchange formats | **Yes.** OpenTimelineIO does most of it. |
| 200+ generation models | Breadth | **No.** We already route through `providers` and `fal`. |

## 5. How ZPF builds the same thing

It is the same architecture, but built on the pieces we already run. The rule copied from invideo: **the agent edits a typed, validated timeline document, never pixels, and it reasons from an index of the footage, not from raw video.**

```
upload / approved Queue clips
   └─► INDEX  (per media file, once)
         ffprobe → proxy (720p H.264, 1s GOP) + filmstrip + waveform peaks
         transcript with word timestamps + speakers
         shot boundaries → vision log per shot (who, action, object, emotion, shot size, angle)
         embeddings → pgvector on Supabase (the RAG store we already have)
   └─► TIMELINE DOC  (versioned JSON: every edit makes a new version with a parent)
   └─► AGENT  (the Guide brain + edit tools + a playbook per job)
         tools read the index, then emit ops → validator → new version → diff card → user keeps it or rolls back
   └─► RENDER  (ffmpeg on a Fly worker: timeline → filter_complex → MP4, WAV, stills)
   └─► EXPORT  (OTIO → FCPXML / xmeml for FCP, Premiere, Resolve)
```

### 5.1 The timeline document (the most important decision)

It is OTIO-shaped (OpenTimelineIO, the standard interchange format), so export is a straight conversion. Time is in integer frames at the project fps, exactly like theirs.

```jsonc
{ "fps": 30, "size": [1080,1920], "duration": 900,
  "tracks": [
    {"id":"V1","kind":"video","clips":[
      {"id":"c1","media":"gen:812","src_in":0,"src_out":150,"at":0,"speed":1,
       "lanes":[{"path":"transform.scale","keys":[{"frame":0,"value":1},{"frame":150,"value":1.08,"ease":"out"}]}],
       "grade":{"lut":"noir_01","match_to":null},"transition_in":{"kind":"xfade","frames":8}}]},
    {"id":"A1","kind":"audio","role":"voice","clips":[…]},
    {"id":"A2","kind":"audio","role":"music","clips":[…],"duck_under":"voice"},
    {"id":"T1","kind":"caption","style":"preset:bold_center","cues":[…]}],
  "markers":[{"frame":450,"label":"Chapter 2"}] }
```

- **Storage:** a `timelines` table with `id, project_id, account_id, version, parent_id, doc jsonb, author (user|agent), op_summary, created_at`. Nothing is ever updated in place.
  - Rollback moves a pointer back to an older version.
  - A branch is simply two children of the same parent.
  - Session replay is walking the version chain.
  - This follows the `director_canvas.md` rule that expensive work is never thrown away.
- **Media references** use `gen:<id>` / `asset:<id>` handles, never URLs. That applies the rules from `reference_urls.md` and the `@slug` idea.
- **Tenancy:** the table is scoped to the tenant through `Depends`, following `account_scoping.md`.

### 5.2 Ops and the validator (our version of `stage@1`)

The agent can only emit these ops:

`insert, ripple_delete, lift, trim, split, move, swap_take, set_speed, set_lane_key, apply_look, match_grade, set_gain, duck, add_caption_track, add_marker, add_transition, reframe`

- Each op is a pure function from one document to the next.
- `validate(doc)` rejects bad edits:
  - overlapping clips on the same track
  - `src_out` past the length of the media
  - unknown media handles
  - lane values outside their range
  - a discrete lane that isn't set to `step`
  - a duration mismatch
- A rejected op goes back to the agent with the reason, and the agent retries **once**.
- **This one module (`src/cut/ops.py` + `validate.py`) is what makes the agent trustworthy**, the same way id-only references made `image_sourcing` trustworthy.

### 5.3 The index: "watches the footage"

| Piece | Tool | Notes |
|---|---|---|
| Probe, proxy, filmstrip, waveform | ffmpeg / ffprobe (already on Mike's Mac and easy to add on Fly) | Proxies make both preview and agent reads cheap. |
| Transcript with word times and speakers | **WhisperX** (self-hosted, free) or the Deepgram / AssemblyAI API | An API is simpler on Fly; WhisperX is cheaper at volume. |
| Shot boundaries | PySceneDetect | CPU only and fast. |
| Per-shot visual log | **Gemini video understanding** (the Gemini client already exists) on each shot's proxy | Asks for: people, action, objects, emotion, shot size, angle, and quality flags (blur, flub, bad focus). |
| Search | pgvector hybrid search over transcript and shot logs | Reuses the RAG setup on Supabase. |

This goes in a `media_moments` table: `media_id, start_f, end_f, kind (word|segment|shot), speaker, text, tags jsonb, embedding`.

### 5.4 The eight jobs, as ZPF playbooks

Each one is `prompts/cut/<job>.md` plus a few deterministic helpers. The LLM decides and the helpers do the arithmetic.

1. **Assembly.**
   - Line up the script and transcript with fuzzy matching and embeddings.
   - When a line has several takes, `story_judge`-style scoring on the take's clip picks the best delivery.
   - Script lines with no match come back as "unshot lines".
   - For ZPF's own generated work, "assembly" means putting approved Queue clips in timeline order with the `timeline.py` parts. **That is step 8 (Cut) of the guided spec, and it is the cheapest first win.**
2. **Multicam.** Find each angle's offset by cross-correlating its audio against the anchor camera (numpy/scipy FFT). Use diarization to know who speaks when, map each speaker to an angle, and set a minimum shot length so it doesn't flicker.
3. **Cleanup.** ffmpeg `silencedetect` plus filler words from the word timestamps become `ripple_delete` ops. The LLM writes chapter markers from the transcript.
4. **Restructure / cut to length.** The LLM scores segments for importance and hook value, a knapsack picks the set that fits the target length, and the LLM orders them.
5. **Grade.** Looks are a small `.cube` LUT library applied with ffmpeg `lut3d`. Shot matching compares mean and variance in Lab color per clip against a hero frame, and the result becomes `colorbalance` / `eq` parameters.
6. **Sound.** Voice goes through `loudnorm` to -14 LUFS (a standard social-video loudness level), with `afftdn` denoise or the ElevenLabs voice isolator. Music ducks under voice with `sidechaincompress`.
7. **Versions.**
   - Cutdowns are Restructure run at 15s, 30s and 60s.
   - Formats use face-tracked crop, or AI expand (Higgsfield `reframe` / `outpaint`, already connected).
   - Dubs use the ElevenLabs dubbing API plus **fal `sync-lipsync` v2/v3** for lip-sync. It rides the existing `fal.py` adapter.
8. **Search.** A tool the other seven call, and one the user can call from the pill: "find the shot where he laughs."

Three extras:

- **Reference match.** Run scene detection on the reference video to get its shot lengths (the pacing curve), have Gemini describe its structure, and pass both to Restructure as constraints.
- **Beat sync.** librosa beat tracking snaps cut points to the nearest beat.
- **B-roll.** Our existing generation door (credits, with a hold). Stock comes from free Pexels/Pixabay first. iStock/Shutterstock are paid APIs, so they come later.

### 5.5 Render and preview

- **The render of record is ffmpeg on the server.** The timeline compiles to one `filter_complex` (trim/setpts → scale/pad → lut3d → overlay/xfade → ASS captions; audio: atrim → volume → sidechaincompress → amix → loudnorm). It runs as a job on a Fly worker, uses `ledger` holds only for generative steps, and costs no license fees.
- **Browser preview** plays the proxies in sequence with the playhead driving `<video>` elements, plus a canvas for overlays and captions. **It is not frame-exact, and it doesn't need to be.** The export is exact.
- **Remotion** is an option only for motion-graphics templates. Its free license covers teams of 3 or fewer; a SaaS rendering for users falls under their paid "Automators" plan ($0.01 per render, $100/month minimum). **Don't make it the core renderer.**
- **Export:** MP4, WAV, stills, and `.otio`, converted to FCPXML (otio-fcpx-xml-adapter) and xmeml (otio-fcp-adapter) for Premiere and Resolve. The same adapters handle **import**, which is invideo's third way in.
  - Known issue: Resolve has historically been picky about OTIO's FCP XML. **Test against a real Resolve before promising it.**

### 5.6 UI: without changing the studio's look

- A new **/studio/cut** page:
  - a preview on top;
  - a track stack below (V1 and V2, A1 voice, A2 music, T1 captions);
  - a filmstrip on each clip and waveforms on the audio tracks;
  - a playhead;
  - these tools only: blade, trim, drag, delete, and undo (which is the version pointer).
- **The assistant pill is the agent** (spec of 09-26). On /studio/cut, the pill's card shows the job chips (First cut · Clean up · Cut to 30s · Grade · Mix · Versions). Every agent edit arrives as a **diff card** ("Removed 14 silences, −0:38 · Keep / Undo"). Your click is the approval, the same rule as spend.

## 6. Build order

1. **Assemble v0, the step 8 in the guided spec.** Timeline doc, ops and validator, and an ffmpeg render. It auto-assembles a project's approved Queue clips in `timeline.py` order, with a music bed, auto-duck, loudnorm and burned-in captions. There is no UI yet, just an Export button on the Queue. **It turns ZPF from "clips" into "a finished video", and it's the smallest piece that proves the architecture.**
2. **The index:** proxies, transcripts, shots and shot logs, plus pgvector search. Ship Search as a pill tool.
3. **Agent jobs on the doc:** Cleanup, Restructure / cut to length and Versions (cutdowns and 9:16), with a diff card and rollback.
   - *Server half as built (2026-09-28):* `POST /api/cut/projects/{id}/agent` (a job: reply + a validated proposal or none), `.../agent/keep` (one `agent` version), `.../cleanup` and `.../captions` (no model, off the index's word timings), `.../index` (this cut's unindexed media). Every edit is a proposal the person Keeps or Undoes; nothing is saved without the click. See CLAUDE.md's `src/cut/` notes.
4. **The /studio/cut timeline UI**, minimal.
   - *Server half as built (2026-09-28):* `cut_projects` (scratch `cut:<uuid>` or a concept's `concept:<id>`), `POST /api/cut/projects/{id}/ops` with a `base_id` optimistic lock, undo/redo on the head pointer, a media bin of renders + uploads (video, stills, audio), per-file proxies / filmstrips / waveforms (`src/cut/preview.py`), and export of any version. New ops: `lift`, `set_canvas`, `set_cue`, `delete_cue`, `set_caption_style`. See CLAUDE.md's `src/cut/` notes.
5. **Assembly from uploaded footage** plus a script (the "first cut" door), Multicam, Grade and Sound.
6. **OTIO export and import**, dubbing with lip-sync, review links with frame comments, and Reference match and Beat sync.

## 7. Honest notes

- **"The exact same thing" is a company-sized product.** A DAW with buses, a grading suite with qualifiers, bezier keyframe UI and live co-editing are each weeks of front-end work, and none of them is why people pay. **What people pay for is the agent that watches the footage and makes real, editable cuts.** Steps 1–3 copy that exactly. The pro-tool surface is where to stay small.
- **Our edge carries over:** judges that check work before you see it (`story_judge`, `refcheck`) and taste memory. **Add a check step to every agent edit:** render the changed region to a proxy, have Gemini look at the frames, and reject jump cuts, black frames or clipped words before the diff card appears. There's no sign invideo does this.
- **ZPF's own content is generated, not shot.** So the first user of this editor is the Queue (assembling approved clips), not a camera dump. Multicam and take selection matter only once outside users upload real footage, which is the `positioning.md` direction.
- **Costs to track in `costs.py`:** transcription per minute, Gemini video tokens per shot log (use proxies and a low frame rate), lip-sync per second. **Manual editing stays free**, the same bet invideo made.

Sources: invideo.io/news/introducing-invideo-editor · invideo.io/make/agentic-video-editor · help.invideo.io/en/articles/16819946 · ai.invideo.io public bundles (`protocol.C08frBus.js`, `graphql-types.VLZhrY_I.js`, `main.D_8UubYJ.js`, `vendor*.js`) · remotion.dev/docs/license/faq · github.com/OpenTimelineIO/otio-fcpx-xml-adapter · github.com/OpenTimelineIO/otio-fcp-adapter · fal.ai/models/fal-ai/sync-lipsync

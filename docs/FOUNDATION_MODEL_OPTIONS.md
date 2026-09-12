# Foundational model options — September 2026

Mike's ask tonight was "look into building a foundational model using a site that does it."
Direct answer first: no site does that, and no individual does either. Training a video
foundation model from scratch — the thing Wan, LTX, Kling, Veo and Hunyuan are — costs an
estimated hundreds of GPU-years on datasets of tens of millions of clips, run by teams of
dozens. Nobody sells that as a self-serve product because nobody profitably could.

What "a site that does it" actually gets you, and what's realistic for a one-person studio, is
**your own weights on an open base**: take a released model (Wan 2.2/2.5, LTX-2/2.5, or
HunyuanVideo 1.5), train a LoRA adapter on your own footage and photos, and run the merged
weights on rented GPUs from your own pipeline. That stops being aggregation — Runway,
Higgsfield and Veo never let you touch their weights — and it directly attacks the identity-drift
problem the aggregator path already failed at. This doc evaluates that path.

## 1. Hosted training services (upload clips → get weights back)

| Service | Base models | Dataset ask | Cost / run | Wall time | Weights downloadable? | Python API |
|---|---|---|---|---|---|---|
| **fal.ai — Wan 2.2 Trainer** | Wan 2.2 T2V/I2V (14B) | Images + video clips mixed; video = multi-frame examples, no published minimum clip count | $0.004/step, 100-step minimum (~$4/1000 steps) | Not published | `.safetensors` LoRA — fal's model page frames it as a portable adapter loaded on the base model | Yes, documented API/schema |
| **fal.ai — LTX 2.3 Trainer v2** | LTX-2.3 (LTX-2 family) | At least 10 files; video clips need ≥89 frames (~3.7s @ 24fps) or auto-resample; `.txt` caption per file, optional | $0.0024/step → $4.80 for 2,000 steps; failed jobs are free | Not published | Yes — `.safetensors` + JSON config, explicitly meant to be loaded alongside the base model at inference | Yes |
| **fal.ai — Hunyuan Video LoRA Trainer** | HunyuanVideo 1.5 | Same family shape as above (image/video mix) | Priced the same per-step model as the other fal trainers (page didn't publish a distinct rate at check time) | Not published | Portable LoRA file, same pattern as the other two | Yes |
| **Replicate — custom training** | Flux/SDXL confirmed; video (Wan/Hunyuan) via community-pushed trainers, not first-party | Varies by trainer, typically 10–30 images/clips | Billed as GPU-seconds of the training hardware, no flat number published for video LoRA specifically | Varies | Yes — trained weights are yours, downloadable, and Replicate explicitly supports pushing/serving your own fine-tune | Yes, first-class SDK |
| **RunPod — DIY templates (diffusion-pipe, musubi-tuner, ai-toolkit)** | Wan, Hunyuan, Flux, SDXL — whatever the script supports | You control it entirely — clip count, resolution, captions | Pure GPU rental time, see §3 (no markup) | Hours, on your own rented GPU | 100% yours, no third-party ever holds them | No API — it's a rented box you SSH into and run a script |
| **Modal** | Whatever you deploy (example repos for Wan/Hunyuan LoRA training exist) | You control it | Modal's own compute pricing (serverless GPU-seconds); no video-specific flat rate found | Varies | Yours entirely — you own the container | Yes, Python-native by design (this is Modal's whole pitch) |
| **Civitai on-site trainer** | SDXL/Illustrious confirmed; video model training is more limited on their trainer as of this check | Upload images, optional AI auto-captioning | Paid in "Buzz" (on-site currency), not USD directly | Minutes–hours | Yes, LoRA downloads to your account | No — web UI only |
| **Higgsfield Soul (already tried)** | Higgsfield's proprietary Soul pipeline | ~photos/short clips of a subject | Included in Higgsfield credits/subscription | Fast | **No** — Soul is a closed reference id inside Higgsfield, not exportable weights | No — internal reference id only, not portable |
| **Scenario, Krea, Astria, Weights.gg** | Mostly image LoRA (SDXL/Flux); video training support is thin-to-absent across these as of this check | Varies | Varies, generally credit-based | Varies | Astria and Weights.gg both advertise downloadable weights for image LoRAs; video is not their strength | Astria has an API; Krea/Scenario vary |
| **Runway custom models / References / Act-Two** | Proprietary, closed | References are per-generation, not a trained asset | Included in Runway credits | N/A | **No** — nothing downloadable, this is steering a closed model, not training one | Yes, but only for generation, not weight export |
| **Luma, Kling, Vidu "custom character"** | Proprietary, closed | Reference images/clips per character | Included in subscription/credits | N/A | **No** | Generation APIs exist; no weight export |

**The one line that matters:** every "site that does it" which produces a *portable* asset
(fal, Replicate, RunPod/Modal DIY) trains a **LoRA adapter**, not a new foundation model — a
small file (tens to low-hundreds of MB) that steers an already-trained base model toward your
face, your garage, your look. That's the correct scope for one person's dataset. Anything that
promises more (Higgsfield Soul, Runway, Luma, Kling) either doesn't hand you the weights or
isn't training anything portable at all — it's a closed reference slot.

Sources: [Wan-2.2 LoRA Trainer — fal.ai](https://fal.ai/models/fal-ai/wan-22-trainer/t2v-a14b), [LTX 2.3 Trainer (V2) — fal.ai](https://fal.ai/models/fal-ai/ltx23-trainer-v2/i2v), [Hunyuan Video LoRA Trainer — fal.ai](https://fal.ai/models/fal-ai/hunyuan-video-lora-training), [Working with LoRAs — Replicate docs](https://replicate.com/docs/guides/extend/working-with-loras), [Civitai on-site LoRA trainer guide](https://education.civitai.com/using-civitai-the-on-site-lora-trainer/), [Guide to Buzz — Civitai](https://education.civitai.com/civitais-guide-to-on-site-currency-buzz-%E2%9A%A1/)

## 2. Hosted inference for the resulting weights

No provider publishes a clean "$X per 5s 720p clip with a custom LoRA attached" figure as of
this check — video inference pricing across fal/Replicate/RunPod/Modal/Baseten/together.ai is
overwhelmingly quoted per-second-of-GPU-time or per-second-of-output-video for their *own*
hosted checkpoints, not for a BYO LoRA specifically. What's confirmed:

- **fal.ai** already runs Wan/LTX/Hunyuan as first-party endpoints and its trainer pages are
  built to feed straight back into fal's own inference (`.safetensors` LoRA loaded alongside
  the base model at inference) — this is the most turnkey train→serve loop of the group, and
  it's what your provider adapter should target first.
- **Replicate** supports pushing a custom fine-tune to your own model page and serving it
  through the same API shape as any other Replicate model — same SDK pattern your `runway.py`/
  `veo.py`/`higgsfield.py` adapters already use.
- **RunPod serverless** bills per-second on the same GPU price list as its pods (H100 serverless
  quoted around $4.79/hr-equivalent), and cold starts on a custom container are the known weak
  point — a nightly unattended job needs either a "keep-warm" min-instance setting (costs idle
  GPU time) or must tolerate a 30–90s cold-start tax per run, which is fine for an overnight
  batch and bad for anything expecting sub-10s turnaround.
- **Modal** is the most Python-native of the group (functions decorated and deployed directly;
  no separate "API" concept to learn) and is built for exactly this custom-container pattern,
  but likewise has no published flat per-clip figure for video.
- **Baseten / together.ai** are strong for LLM and image-model serving; neither surfaced
  confirmed video-model-specific per-clip pricing in this pass — treat them as a later option
  once volume justifies dedicated deployment, not a first pick.

Reliability for an unattended nightly job favors **fal or Replicate** over raw RunPod/Modal
serverless: both give a stable hosted API with retry semantics your adapter can treat like
Runway or Higgsfield today (submit → poll → download), whereas RunPod/Modal put you in charge
of the serving container's uptime and cold-start behavior yourself.

Sources: [LTX 2.3 Trainer (V2) — fal.ai](https://fal.ai/models/fal-ai/ltx23-trainer-v2/i2v), [Working with LoRAs — Replicate docs](https://replicate.com/docs/guides/extend/working-with-loras), [Runpod H100 Pricing 2026 — Spheron](https://www.spheron.network/blog/runpod-h100-pricing-2026/), [Modal Pricing Guide — checkthat.ai](https://checkthat.ai/brands/modal/pricing)

## 3. Buy vs. rent

**Buying an RTX 5090 in September 2026 is a bad idea right now.** GDDR7 memory pricing (>80% of
the card's bill of materials) spiked through 2026 as AI datacenters absorbed global memory
supply; street price is running **~$4,700–$5,100** against a $1,999 launch MSRP — roughly 2.3–2.5x.
A used 4090 is the saner buy-side option if you want local hardware at all, though this research
pass didn't turn up a clean current used-4090 figure — budget mid-$1,000s based on the same
memory-shortage pressure pushing used prices up across the board.

**Renting an H100** runs **$1.99–$3.49/hr** on RunPod depending on tier (Community/spot vs.
Secure/on-demand, PCIe vs. SXM vs. NVL), with the broader market spanning **$1.49–$6.98/hr**
across 15+ providers. An RTX 4090 rents for **$0.74/hr** and an RTX 5090 for **$0.99/hr** on
RunPod — both cheap enough that renting a consumer-class card for LoRA training (which doesn't
need H100-class throughput) is close to free at your volume.

**Break-even math.** A 5090 at ~$4,900 bought outright, amortized against a 4090 rental at
$0.74/hr: that's ~6,600 rental-hours before owning pays off, before counting power, the
opportunity cost of $4,900 up front, or the card being obsolete/replaced before you get there.
At 30–100 clips/day, each 5s clip taking roughly 1–3 minutes of GPU time to render at 720p on
consumer hardware, that's **1.5–5 GPU-hours/day** — meaning even continuous rental costs
**~$1–$15/day** on a 4090/5090 rental, or **$30–$450/month**. You would need to sustain that
volume for **15–22 months** before an owned 5090 pencils out, and that's before LoRA *training*
runs (which are one-off, cheap, and don't justify owning hardware at all) are factored in.
**Verdict: rent.** Buying only makes sense past sustained triple-digit clips/day for months, or
if GPU prices come back down from the current memory-driven spike.

Sources: [Gaming GPU Prices 2026: RTX 5090 Tops $5,000 — Tech Insider](https://tech-insider.org/gpu-prices-2026/), [H100 Rental Prices Compared — IntuitionLabs](https://intuitionlabs.ai/articles/h100-rental-prices-cloud-comparison), [RunPod Pricing](https://www.runpod.io/pricing), [H100 PCIe GPU Rental — RunPod](https://www.runpod.io/gpu-models/h100-pcie)

## 4. Recommendation

**Primary path: fal.ai, training LoRAs on Wan 2.2 (or 2.5 once its trainer matures) and LTX-2.**
fal is the only provider in this survey with a clean train→own-weights→serve loop, published
per-step pricing, a documented Python API, and first-party inference for the exact base models
you'd train on. **Fallback: RunPod with diffusion-pipe/musubi-tuner**, self-run, when you want
zero per-step markup or need a training config fal's trainer doesn't expose (e.g. non-default
LoRA rank, multi-concept training).

**Week one.** Cut ~15–20 clips per LoRA from the 70 minutes of ProRes (not all 70 minutes —
pick your cleanest, most on-look 3–5 second segments; more clips of consistent quality beats
more raw minutes), each clip 3–6 seconds to clear LTX's ~3.7s floor and fal's practical range.
Caption every clip with a one-line, consistent-vocabulary description (subject, action, one
style word) — fal's trainers accept auto-captioning but a hand-written line trains faster and
truer than an auto-caption guessing at "moto garage" imagery. Run the 7-photo face set as a
separate, smaller image LoRA first (image LoRAs train faster and cheaper, and identity is
exactly where Higgsfield's Soul already failed you — validate the fix on the cheap modality
before spending on video).

**Expected cost, first three LoRAs (identity, garage look, one imagined world):** at fal's
published rates ($0.004/step Wan, $0.0024/step LTX), a 1,500–2,500-step run per LoRA lands
around **$6–$10 each**, so **all three together: roughly $20–$35** in training spend. Add
inference testing (a few dozen validation clips at fal's per-second video rates, likely
**$10–$30** total) and you're looking at **under $75 all-in** to have three working, portable
LoRAs — cheap enough that "try it and see" is the right posture, not a budget decision.

**Which adapter to write first: `fal.py`.** It's the only option here that satisfies the repo's
`providers.REQUIRED` contract cleanly: `generate_video` (submit → poll → download, identical
shape to `higgsfield.py`'s `_submit_and_wait`), `generate_candidates` (N attempts, a
`generations` row per attempt, never-raises — copy `higgsfield.generate_candidates` almost
verbatim), `estimate_cost` (fal publishes real per-second/per-step prices, so this can be a real
invoice instead of `higgsfield.py`'s admitted guess), `spend_approved`/`has_key` (same env-var
gate pattern), and `generations_today` (same `generative.used_today` call). Once `fal.py`
conforms and is added to `VIDEO_PROVIDERS`, the LoRA-trained clip becomes just another
`choose_provider()` candidate — the aggregator becomes one option among several instead of the
whole system.

## 5. Risks

- **Identity drift on push-ins** is not a hypothetical for this project — it already happened.
  The repo's own `higgsfield.py` documents it directly: the trained Higgsfield Soul "Mike
  Antihero v2" came back as a different actor (thick mustache, pompadour) and was pulled from
  the default path in favor of grounding on real photos per-shot instead of a trained identity
  reference. A self-trained LoRA is not automatically immune — camera push-ins stress
  identity coherence on every video model, trained or not — but a LoRA you own can be
  re-trained, rank-adjusted, or blended with per-shot reference images in a way a closed
  Soul id cannot. Test push-in shots specifically before trusting an identity LoRA on camera
  motion, not just static framing.
- **Commercial-use license terms differ meaningfully by base model.** Wan 2.2 ships under
  Apache 2.0 — unrestricted commercial use. LTX-2 is free for commercial use only under $10M
  ARR, with a separate enterprise license above that (irrelevant at your scale, but note it if
  the studio ever scales). HunyuanVideo 1.5 ships under the Tencent Hunyuan Community
  License — a Llama-style community license; this pass could not confirm whether it carries
  the common large-org MAU/revenue trigger some Tencent/Meta community licenses use, so read
  the actual LICENSE file in the repo before committing to Hunyuan as a base.
- **Face/likeness terms of service on hosted trainers** are a second, separate risk from the
  base-model license: uploading your own face photos to a third-party trainer (fal, Replicate,
  Civitai) puts that biometric data under *their* ToS and retention policy, not the open
  model's license. Read each platform's data-retention and biometric-data clauses specifically
  before uploading the 7-photo face set — this is exactly the kind of thing Higgsfield's
  closed Soul pipeline obscured (you never saw what they trained on, or what stayed on their
  servers).
- **Data retention on uploaded footage** is unconfirmed for most of these services in this
  pass — fal's trainer pages describe the training job mechanics but not a retention/deletion
  policy for source clips. Before uploading the moto/garage ProRes footage anywhere, check
  each platform's stated retention window and, where possible, delete source files from their
  storage after the LoRA trains — the LoRA file itself is the only thing you need to keep.

Sources: [Lightricks Open-Sources LTX-2 — GlobeNewswire](https://www.globenewswire.com/news-release/2026/01/06/3213304/0/en/lightricks-open-sources-ltx-2-the-first-production-ready-audio-and-video-generation-model-with-truly-open-weights.html), [tencent/HunyuanVideo-1.5 — Hugging Face](https://huggingface.co/tencent/HunyuanVideo-1.5), [Wan-Video/Wan2.2 — GitHub](https://github.com/Wan-Video/Wan2.2), `/home/claude/zp/src/higgsfield.py` (internal record of the Soul identity-drift finding, 2026-09-06)

---

*Compiled September 7, 2026. Every figure above is dated to this check — video-model pricing
and licensing move fast; re-verify before a real spend decision, especially anything marked
"not published" here.*

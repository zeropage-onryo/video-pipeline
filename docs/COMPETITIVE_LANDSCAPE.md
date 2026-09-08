# Competitive Landscape — AI Video Pre-Production
Research date: **7 September 2026**. Every claim carries a source URL. Primary sources (vendor pricing/docs) are used wherever reachable; secondary sources are flagged inline as `[secondary]`.

---

## 0. The one-paragraph version

The render is commoditised. Custom style/LoRA training is commoditised. What is *not* solved by anyone is the front half — generating concepts worth rendering, grounded in a specific customer's reference library and their own performance history. The money in this market right now is in **volume for marketers**, not in film. Higgsfield hit ~$700M annualised revenue in July 2026 with 85% of usage being marketing work; Runway, the "film" brand, is at a fraction of that and lost $155M EBITDA in 2024. Meanwhile OpenAI killed Sora outright, and Icon — the best-funded "AI admaker" — quietly became a human agency. Position accordingly.

---

## 1. LTX Studio (Lightricks) — the closest named comparable

### What the product actually does
LTX Studio bills itself as "the all-in-one creative studio for AI video production" and covers a genuinely end-to-end path: text/image/video/script-to-video generation; **dynamic storyboarding and an AI Storyboard Generator**; a **timeline editor** for post; sound design; shot-level editing; camera-movement direction and keyframe motion guidance; visual reference inputs and preset styles; and consistency systems for **characters, objects, locations and elements** across scenes. It also ships packaged verticals — Music Video Maker, Movie Trailer Generator, Ad Generator, **Pitch Deck Generator**, Cartoon Video Maker. It orchestrates its own LTX-2 model alongside VEO 3.1, FLUX.2 Pro, Z-Image and Kling. Target audience is stated as three groups: creative teams/filmmakers, marketing and advertising professionals, and in-house brand studios. ([ltx.io/studio](https://ltx.io/studio))

**Read that feature list against your repo.** LTX Studio already has the storyboard→shot→consistency→timeline→export chain. It is a *superset* of your render half plus the editing/assembly step you lack. What it does **not** have, on its own description, is a research/scout agent, a taste-history model, or any performance feedback loop. Its "ideation" is a storyboard generator fed by a user's prompt — it does not go find story directions for you.

### Pricing and credit model (primary source, 7 Sep 2026)
From [ltx.io/studio/pricing](https://ltx.io/studio/pricing):

| Tier | Monthly | Annual | Credits/mo | Seats | Notable gates |
|---|---|---|---|---|---|
| Free | $0 | — | 800 one-time | 1 | LTX-2.5, audio-to-video; **personal use only** |
| Lite | $15 | $12 ($144/yr) | 8,000 | 1 | upscales, editing tools, no watermark |
| Standard | $35 | $28 ($336/yr) | 28,000 | 1 | Nano Banana 2, FLUX.2 Pro, Kling, **AI Storyboards**, Pitch Decks, commercial licence |
| Pro | $125 | $100 ($1,200/yr) | 110,000 | 3 collaborators/project | Veo 3.1, max quality, credit top-ups |
| Enterprise | custom | — | custom | unlimited | **custom model training**, centralised brand management, SSO, AM, SLA |

Two things matter here. First, **storyboarding is paywalled at $35** — the pre-production feature is a mid-tier upsell, not the core. Second, **custom model training is Enterprise-only**, which is a meaningfully worse deal than Scenario or Leonardo (see §4) and is an opening.

### Relationship to LTX-2 / LTX-2.5
Lightricks open-sourced LTX-2 in January 2026 — native 4K at 50fps, synchronised audio+video, clips to 10s, multi-input conditioning (text, image, audio, depth, reference video), multi-keyframe conditioning, 3D camera logic, **LoRA fine-tuning**, and claimed up to 50% lower compute cost than competitors, runnable on consumer GPUs. ([ltx.io newsroom](https://ltx.io/newsroom/ltx-2-is-now-open-source-full-model-weights-released), [Hugging Face](https://huggingface.co/Lightricks/LTX-2), [GlobeNewswire](https://www.globenewswire.com/news-release/2026/01/06/3213304/0/en/lightricks-open-sources-ltx-2-the-first-production-ready-audio-and-video-generation-model-with-truly-open-weights.html)) LTX-2.5 followed in ~August 2026 as an open-weights "video world model" [secondary: [DataNorth](https://datanorth.ai/news/ltx-releases-ltx-2-5-open-weights-video-world-model)].

The strategy is legible: **give away the model, sell the studio.** That is the mirror image of your position — you own no model and orchestrate others. Lightricks is betting the app layer is defensible and the model isn't. He should note that Lightricks agrees with him about where value sits, which is validating and threatening at once.

### The soft underbelly: LTX Studio's reputation is bad
Trustpilot: **1.5/5 across 75 reviews**. Recurring, dated complaints: unauthorised/hard-to-refund annual billing ("billed via PayPal for a full annual subscription, well over $500", 25 Feb 2026); output quality ("90% of what came out within 41 minutes was useless", 10 Feb 2026); constantly-changing UI ("Ui is really bad! i canot find where to upload a video", 20 Mar 2026); and **credit burn on failed generations** ("just burning up credits and getting totally different results", 6 Feb 2026; "$140 just trying to produce a basic 10 sec video", 1 Mar 2026). ([Trustpilot](https://www.trustpilot.com/review/ltx.studio))

Trustpilot skews negative by nature — but the *specificity and consistency* of the credit-burn and billing complaints is a real signal, and it is the single most actionable competitive intelligence in this document. See §5.

---

## 2. The other film/production platform players

**Layer key:** MO = model owner · CT = creative tool · WO = workflow orchestrator

| Player | Layer | Pricing shape (primary unless noted) |
|---|---|---|
| **Runway** | MO + CT + services | Free $0 (125 one-time credits); Standard $12/mo annual ($15 monthly), 625 cr; Pro $28 ($35), 2,250 cr, **1 Brand Kit, 1 voice clone, Runway MCP**; Max $76 ($95), 9,500 cr, up to 3 Brand Kits, ProRes/HDR, credit rollover. ([runway.com/pricing](https://runway.com/pricing)) |
| **Higgsfield** | CT/WO on others' models | Starter ~$15/mo, 200 credits; Plus/Business/Ultra up to 3,000+ credits [secondary: [Scopeful](https://www.scopeful.org/tools/higgsfield)] |
| **Luma** | MO → **now "Luma Agents"** | Plus $30/mo ($25 annual), 10,000 cr; Pro $90 ($75), 40,000 cr; Ultra $300 ($250), 150,000 cr; Team/Enterprise custom with **custom fine-tuning**. Credits expire monthly, no rollover. ([lumalabs.ai](https://lumalabs.ai/dream-machine/pricing)) |
| **Kling** | MO | Standard $10/mo, 660 cr; Pro $37, 3,000; Premier $92, 8,000; Ultra $180, 26,000. 1080p+audio = 12 credits/sec. **Failed generations still consume credits on web (not API).** [secondary: [eesel](https://www.eesel.ai/blog/kling-ai-pricing)] |
| **Sora / OpenAI** | **DEAD** | Web and app **discontinued 26 April 2026**; **API discontinued 24 September 2026**. ([OpenAI Help Center](https://help.openai.com/en/articles/20001152-what-to-know-about-the-sora-discontinuation)) |
| **Freepik** | CT aggregator | Bundles stock + multi-model AI generation; pricing page redirects vary by region — re-check directly |
| **Flora** | CT (node canvas) | Raised **$42M from Redpoint**, Jan 2026 ([TechCrunch](https://techcrunch.com/2026/01/27/node-based-design-tool-flora-raises-42m-from-redpoint-ventures/)) |
| **Weavy** | **ACQUIRED** | Bought by **Figma**, now **Figma Weave**, ~$200M [secondary on price: [LinkedIn](https://www.linkedin.com/posts/thomassmale_figma-just-acquired-ai-startup-weavy-for-activity-7390066297792782336-obFp)]. ([Figma blog](https://www.figma.com/blog/welcome-weavy-to-figma/)) |

### Two structural reads

**Sora's death is the headline.** OpenAI killed a product that hit 1M downloads faster than ChatGPT. Reasons per Axios: compute cost, a **45% download decline by January 2026**, and the collapse of a Disney deal (200+ characters, a planned $1B investment, no funds ever transferred). ([Axios](https://www.axios.com/2026/03/24/openai-discontinue-sora-video-app), [TechCrunch](https://techcrunch.com/2026/03/24/openais-sora-was-the-creepiest-app-on-your-phone-now-its-shutting-down/), [the-decoder](https://the-decoder.com/openai-sets-two-stage-sora-shutdown-with-app-closing-april-2026-and-api-following-in-september/)) **Consumer novelty video generation is not a business.** Retention, not generation quality, is what kills these products. This directly validates a multi-provider adapter architecture: anyone who hard-wired Sora is rewriting right now, and he should make sure his adapter layer has no Sora dependency past 24 Sep 2026 — that is *this month*.

**Runway is moving away from being a video tool.** Its Series D/E framing is "towards a new media ecosystem with **world simulators**" ([General Atlantic](https://www.generalatlantic.com/media-article/runway-series-d-funding-towards-a-new-media-ecosystem-with-world-simulators/), [Runway news](https://runwayml.com/news/runway-series-d-funding)). Meanwhile **Runway Studios** is a genuine production company — Hundred Film Fund, Gen:48, Creative Dialogues, Telescope Magazine — hiring screenwriters, animators, VFX artists and business-affairs staff ([runway.com/studios](https://runway.com/studios)). Runway is becoming a model lab plus a studio, and de-emphasising the mid-market tool. **That vacates exactly the indie-filmmaker tool space he is building into.**

---

## 3. The volume/ad-engine category — a different business

| Player | Price | Automates | Idea generation? |
|---|---|---|---|
| **Creatify** | Starter $39/mo (100 cr); Pro $99 (300 cr); Enterprise custom | Batch Mode variants, AI Script Writer, avatars | **Yes, genuinely** — "AI Performance Agent" for Meta/Google/TikTok/AppLovin + **Competitor Ad Tracker across 10M+ Meta ads** ([creatify.ai/pricing](https://www.creatify.ai/pricing)) |
| **Arcads** | ~$110/mo Starter, ~$220 Creator, ~$11/video [secondary: [FluxNote](https://fluxnote.io/guides/arcads-pricing-2026)] | Script → AI actor UGC ad | Script assist; execution-led |
| **Icon** | **$1,000/mo** for 6 ads, or $399/ad | **Humans.** "We find creators, ship products, curate formats, write scripts, coach creators, & edit videos" | No — human creative directors ([icon.com/pricing](https://icon.com/pricing)) |
| **HeyGen** | Free; Creator $29 (600 cr); Pro $49 (1,000 cr); Business $149 (1,500 cr, +$20/seat); Enterprise custom | Avatars, translation, brand kit | Execution only ([heygen.com/pricing](https://www.heygen.com/pricing)) |
| **Opus Clip** | Free (60 cr); Starter $15 (150 cr); Pro $29 ($14.50 annual, 3,600 cr/yr); Business custom | Clipping, captions, reframe, **Auto Hook**, speech cleanup | Partial — **virality score** (Pro+), AI Copilot topic search, real-time trend analysis ([opus.pro/pricing](https://www.opus.pro/pricing)) |
| **Captions / AdCreative** | Seat+credit hybrids | Talking-head editing / static ad variants | Mostly execution |

### The Icon story is the most important item in this document
Icon raised from Founders Fund and execs at OpenAI, Pika and Cognition, and **spent $12M on the icon.com domain** in April 2025. It launched as "The First AI Admaker" ([founder's announcement](https://x.com/kennandavison/status/1886836061378372064)). By 2026 it had quietly become the human agency it promised to replace, selling "38 Human UGC ads (100% real / not AI)" at $399 each — its site today reads "**The Human Admaker**". Reported user complaints: slow, unusable, clunky, "emotionless and repetitive" AI voice, and unauthorised billing after free trials. [secondary, and clearly editorial in tone — treat the narrative as directional, but the pivot itself is verifiable from icon.com's own live pages: [CTOL](https://www.ctol.digital/news/icon-com-12m-domain-human-ads-ai-startup-collapse-investors-2026/) vs [icon.com/pricing](https://icon.com/pricing)]

The diagnosis given — application-layer AI startups on standardised foundation models lack proprietary data, embedded workflow, or network effects — is **exactly the risk on his product**, and exactly the argument for his taste-history and performance-feedback loop being the actual product rather than a nice-to-have. The reference library and taste history *are* the proprietary data. Everything else he has is rentable.

---

## 4. Bring-your-own-model / LoRA / brand look — is it a differentiator?

**No. It is table stakes in 2026, and it is cheap.**

- **Leonardo** — custom "Personal AI Models" from **$12/mo** (Essential: 10 trainings/mo; Premium $30: 20; Ultimate $60: 50), plus Elements for style. Train on 10–20 images. ([leonardo.ai/pricing](https://leonardo.ai/pricing/))
- **Scenario** — "Train custom models" at **Pro $45/mo** (5,000 cr); Max $75 adds custom *editing* model training and 25 users. 10–30 images for a style, 5–15 for a character; **Multi-LoRA merging** of styles and subjects. ([scenario.com/pricing](https://www.scenario.com/pricing))
- **Astria** — **$1.50 per fine-tune**, $0.10/prompt, $0.50/model/month storage. ([astria.ai/pricing](https://www.astria.ai/pricing))
- **fal** — Flux LoRA Fast Training plus serverless GPU ($1.89/hr H100 → $8.50/hr B300); video APIs per-second. ([fal.ai/pricing](https://fal.ai/pricing))
- **Runway** — Brand Kits (1 at Pro $28, up to 3 at Max $76) and custom voice clones. ([runway.com/pricing](https://runway.com/pricing))
- **HeyGen** — custom avatars from the free tier; 5+ at Business, 10+ at Enterprise. ([heygen.com/pricing](https://www.heygen.com/pricing))
- **LTX Studio** — custom model training **Enterprise only**. ([ltx.io/studio/pricing](https://ltx.io/studio/pricing))
- **Luma** — custom fine-tuning **Enterprise only**. ([lumalabs.ai](https://lumalabs.ai/dream-machine/pricing))
- **LTX-2 / LTX-2.5** — LoRA fine-tuning built into the open weights, free. ([ltx.io](https://ltx.io/newsroom/ltx-2-is-now-open-source-full-model-weights-released))

**Verdict.** Astria's $1.50 fine-tune is the price floor and it is essentially zero. Do not build "train your own look" as a headline differentiator — it is a checkbox you need for parity, and one you can rent from fal or Astria rather than build. The differentiator is not *that* you can hold a custom look; it is that you **know which look to apply to which idea**, from taste history. Note the split, though: the platforms that treat custom training as Enterprise-only (LTX, Luma) leave the indie/solo tier underserved, which is a real if narrow wedge.

---

## 5. What nobody is doing well

**Nobody serious is doing the idea half.** Surveying the named pre-production field — Boords, Katalist, FinalBit, Filmustage, Studiovity, Cuebric, MITO, Largo.ai — the tools split cleanly into *storyboarding from an existing script*, *breakdown/scheduling/budgeting from an existing script*, and *concept art from an existing prompt*. Largo.ai analyses scripts for audience and revenue potential, which is the closest to analytics, but it grades a finished script rather than generating directions. ([Unite.AI](https://www.unite.ai/best-ai-pre-production-tools-for-filmmakers/)) **Every one of them assumes the idea already exists.** That is the gap, and it is where his research/scout agents and taste-history live.

**The only real competitors on "ideas from performance data" are in advertising, not film.** Creatify's AI Performance Agent plus a 10M-ad competitor tracker is genuinely a closed loop from performance back into creative ([creatify.ai/pricing](https://www.creatify.ai/pricing)); Opus Clip's virality score and trend analysis is a weaker version ([opus.pro/pricing](https://www.opus.pro/pricing)). Neither is grounded in *the customer's own reference library or taste*, only in aggregate platform data. **His per-account taste history is the thing neither has.**

**Evidenced complaints across the field, all of which are product openings:**
1. **Credit burn on failures.** LTX users report burning credits on unusable output ([Trustpilot](https://www.trustpilot.com/review/ltx.studio)); Kling charges credits for failed generations on the web UI but not the API [secondary: [eesel](https://www.eesel.ai/blog/kling-ai-pricing)]. **His LLM-judge-before-render step and human approval Queue are directly the fix for this, and he is not marketing it as such.** "You approve before you spend" is a sharper pitch than anything on his current feature list.
2. **Billing hostility.** Unauthorised annual charges and refused refunds are the top LTX complaint and appear in Icon's complaints too. A transparent per-account render cap — which he already built — is a trust feature, not just an ops feature.
3. **Credit expiry.** Luma and Kling both expire credits monthly with no rollover ([Luma](https://lumalabs.ai/dream-machine/pricing)); Runway only offers 1-month rollover at Max ([Runway](https://runway.com/pricing)).
4. **Churn/novelty collapse.** Sora's 45% download drop and shutdown is the extreme case ([Axios](https://www.axios.com/2026/03/24/openai-discontinue-sora-video-app)). Generation alone does not retain. A slate that gets better at *your* taste over time is a retention mechanic; a render button is not.

**Honest counter-note:** his own stated weakness — no editing/assembly, never published anything — is real and is the thing LTX Studio has and he doesn't. A slate of approved clips that cannot become a cut is a demo, not a product.

---

## 6. Business model reality

**Shape of the market.** Nearly everyone has converged on: free trial → ~$12–15 solo → ~$28–49 prosumer → ~$75–150 "pro/agency" → custom enterprise, all denominated in credits, with seats appearing only at the top. Solo entry clusters tightly at $10–15 (Kling $10, LTX Lite $15, Higgsfield Starter $15, Opus Starter $15, Runway Standard $12–15, Leonardo Essential $12). Agency tier clusters at $75–150 (LTX Pro $125, Runway Max $76–95, HeyGen Business $149, Creatify Pro $99, Luma Pro $90). **Anything he prices outside those bands needs a reason.**

Note the ad-engine premium: Arcads at ~$110–220/mo and Icon at $399–1,000 per unit of output sit far above the film tools, because marketers price against media spend and CAC, while filmmakers price against a hobby budget. **The same pipeline sold to a performance marketer is worth roughly 5–10× what it is worth sold to an indie filmmaker.**

**Who is actually making money.**
- **Higgsfield: ~$700M annualised as of July 2026**, up from ~$200M at end-2025, targeting $1B run-rate by end-2026; $5.4B valuation on only **$138M total raised**; **85% of usage is marketing, 80% commercial work**; enterprise accounts spend $200K+/yr. ([Sacra](https://sacra.com/c/higgsfield/), corroborated by [TechTimes](https://www.techtimes.com/articles/319394/20260630/ai-video-startup-higgsfield-hits-500m-revenue-eyes-5b-funding-round.htm) and [36Kr](https://eu.36kr.com/en/p/3650517574312323))
- **Runway: ~$90M ARR June 2025**, forecast $265–300M by end-2025; ~$1.05B raised; $5.3B post-money after a $315M Series E in Feb 2026; **$155M EBITDA loss in 2024** on cloud-compute and training. ([Sacra](https://sacra.com/c/runway/), [Dealroom](https://app.dealroom.co/news/feed/runway-raises-315m-hits-40m-arr-as-it-pivots-from-ai-video-to-world-models))
- **OpenAI:** shut Sora down rather than keep paying for it.
- **Icon:** best-funded AI admaker, now selling human labour.

**The pattern is unambiguous.** Higgsfield raised 7× less than Runway and earns more, because it sells volume to marketers and rents its models instead of training them. Owning a model is a capital sink; orchestrating models and selling into a budget that already exists is the profitable position. **His architecture — no owned model, BYOK, multi-provider adapters — is on the correct side of that line.** His *market* (film/indie) is on the wrong side of it. If he wants revenue rather than a portfolio piece, the pre-production engine pointed at brand/performance-marketing slates is where the money demonstrably is; pointed at indie filmmakers it is where the acclaim is.

---

## 7. Re-check before betting

Flagged as genuinely volatile:

- **Sora API dies 24 September 2026 — seventeen days from now.** Verify no adapter or dependency touches it. ([OpenAI](https://help.openai.com/en/articles/20001152-what-to-know-about-the-sora-discontinuation))
- **Higgsfield changed pricing 3 times in 90 days**, and its "Unlimited" tiers carry undisclosed fair-use caps [secondary: [Scopeful](https://www.scopeful.org/tools/higgsfield)]. He should pull live pricing from the vendor rather than hardcoding cost tables. Its revenue figures are secondary/private-market estimates and range $500M–$700M depending on source and date — treat as directional, not precise.
- **Runway's direction of travel** (world simulators, Studios as a production company) could mean it exits or doubles down on the mid-market tool; the Gen-4.5 releases suggest it hasn't abandoned it [secondary: [MarketScreener](https://in.marketscreener.com/news/runway-outperforms-google-and-openai-with-its-new-gen-4-5-video-model-ce7d51d8dd81f526)].
- **Figma Weave** is new and Figma's distribution is enormous; node-canvas orchestration may get bundled into a tool every agency already pays for. Watch this. ([Figma](https://www.figma.com/blog/welcome-weavy-to-figma/))
- **LTX-2.5 capabilities and LTX Studio's tiering** both moved within the last 60 days. Re-fetch the pricing page before any competitive claim.
- **Arcads and Kling pricing here are secondary-sourced.** Both pricing pages resisted direct fetch; verify before quoting.
- **Luma has rebranded to "Luma Agents"** — the agentic framing is spreading, and "agent" pricing (Pro = "4x usage with the Luma Agents") is becoming a pricing axis of its own. ([lumalabs.ai](https://lumalabs.ai/dream-machine/pricing))

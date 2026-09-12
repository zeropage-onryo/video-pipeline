# Product positioning — where (and whether) this is defensible

*Compiled 2026-09-07. Every claim carries a source URL. Note: the brief referenced
`docs/STUDIO_REVIEW_2026-09-07.md`, which does not exist in this repo. Substituted
CLAUDE.md's "Where the project stands", `docs/BACKLOG.md` §10 (BYOK), and
`docs/FOUNDATION_MODEL_OPTIONS.md`.*

## The blunt version

The idea engine is the wrong wedge. It is the most interesting thing you built and the
least sellable thing you built, and Amazon now gives an equivalent away free inside
Creative Studio — brainstorm, storyboards, scene-level scripts, multi-scene video with
music and VO, "at no extra cost" to Amazon Ads users
([eMarketer](https://www.emarketer.com/content/amazon-unveils-agentic-ai-make-ad-creation-faster-cheaper?jid=237856)).
Meta and Google are doing the same from their side; Zuckerberg's stated goal is that a
business "approach with their objective and budget and let tech companies take over the job"
([eMarketer](https://www.emarketer.com/content/ai-driven-creative-tools-expand-fast-challenging-traditional-agency-model)).
Ideation is the layer the platforms are commoditizing first, because it is cheap text
generation and it pulls ad spend toward them.

Meanwhile the thing you deliberately cut — assembly, captions, audio, the edit — is the
thing every survey says is still mandatory human work: 90% of marketers say editing
AI-generated content is essential and 99% say brand personality must show through
([Animoto 2026 State of Video, via BusinessWire](https://www.businesswire.com/news/home/20260121875037/en/83-of-Consumers-Can-Spot-AI-Videos-36-Say-It-Lowers-Brand-Trust-According-to-Animotos-New-Report)).
You have built the half that is being given away and skipped the half that is still paid for.

That is the headline. The rest is what to do about it.

## 1. What buyers actually complain about

Separate the two complaint classes cleanly, because only one is yours to win.

**Render quality — not winnable.** Runway sits at 1.2/5 across 321 Trustpilot reviews, and
the volume of it is credits, refunds and failed generations: "every attempt costs a
significant number of credits", refunds refused because credits were consumed, "generates
poor-quality videos, so you have to retry many times"
([Trustpilot](https://ca.trustpilot.com/review/runwayml.com)). You cannot fix model output.
You can fix the *economics of retries*, which is a different product (see §5).

**Workflow / consistency / assembly — winnable, and crowded.** LTX Studio reviewers report
exactly the failure your system also has: "very difficult to achieve consistent quality
outcomes… especially when trying to create 20-second videos that maintain the same
characters", the model "changes the face of the character", storyboarding "skips or gets
details wrong", retake "doesn't really generate change", and credit cost is invisible before
you click ([G2](https://www.g2.com/products/ltx-studio/reviews?page=7&qs=pros-and-cons)).
Opus Clip reviewers report "clip generation out of context", "poor personalization",
generic output unless you template your branding, and that clips "need some editing"
([Capterra](https://www.capterra.com/p/10006559/Opus-Clip/reviews)).
On the UGC-ad side, neither Arcads nor Creatify connects to Meta Ads Manager or TikTok Ads
for automated upload; script quality is inconsistent and "actor fatigue" is real as the same
AI faces recur across brands
([Wireflow](https://www.wireflow.ai/blog/arcads-vs-creatify)).

Read that list against your repo. Identity drift on push-ins is documented as already having
happened to you (`docs/FOUNDATION_MODEL_OPTIONS.md` §5, Higgsfield Soul returned a different
actor). Cost opacity is a thing you *have* solved — per-account caps, `estimate_cost`, the
cost tracker — and nobody else has. Publishing adapters are a thing you *have* built and the
UGC incumbents haven't. Those two are real, checkable gaps in the market. The ideation gap is not.

## 2. Does anyone want the AI to have the ideas?

Yes, partially — and that is worse for you than a clean no.

63% of marketers already use AI to generate ideas, 53.8% to break creative blocks, 55.2% for
scriptwriting; 84% use AI in video creation at all
([Animoto/BusinessWire](https://www.businesswire.com/news/home/20260121875037/en/83-of-Consumers-Can-Spot-AI-Videos-36-Say-It-Lowers-Brand-Trust-According-to-Animotos-New-Report)).
So the behaviour is adopted — but it is adopted *inside ChatGPT and inside the ad platforms*,
free, at the top of a funnel. Nobody is short of ideas. Idea supply is the cheapest thing in
this whole stack, which is precisely why it is not a business.

And the ceiling is hard: 99% insist brand personality must show through, 36% of consumers say
an AI-generated video lowers their perception of a brand, 83% say they've watched videos they
suspected were AI ([same report](https://www.businesswire.com/news/home/20260121875037/en/83-of-Consumers-Can-Spot-AI-Videos-36-Say-It-Lowers-Brand-Trust-According-to-Animotos-New-Report)).
54% of Gen Z prefer zero AI involvement in creative work, and 31% of consumers say AI in ads
makes them less likely to pick a brand
([eMarketer](https://www.emarketer.com/content/consumers-rejecting-ai-generated-creator-content)).

Translation: buyers will let AI *propose*. They will not let it *decide*, and they will not
pay much for proposing. Your approval Queue is correctly designed for that reality. Your
judges (`taste_judge`, `uncanny_judge`) are the genuinely differentiated asset — not because
they generate, but because they *reject*. "On-brand gate" is a defensible product category
that already has enterprise money in it (Adobe Brand Intelligence exists as an enterprise
brand-compliance product, [Adobe](https://business.adobe.com/products/brand-intelligence.html)).
Nothing comparable exists at the solo/SMB tier.

## 3. Who the realistic buyer is

- **Solo creators** — largest population, worst economics. They churn, they have no budget,
  and they already get ideation free. The Trustpilot/Capterra rage above is largely this
  cohort. Skip.
- **Small brands doing organic social** — a real volume problem and no tool, but they buy
  *outcomes*, not pre-production. They will not operate a Queue.
- **Performance-marketing agencies / high-volume advertisers** — the only segment with all
  three of budget, genuine variant-volume pain, and tools that visibly don't finish the job.
  US digital video ad spend is forecast at $81.9B in 2026; buyers expect ~40% of video ads to
  be AI-created by 2026; ~90% of advertisers use or plan to use genAI for video creative
  ([Adwave, citing IAB](https://adwave.com/resources/ai-video-ad-statistics-2026)).
  Marketers are moving from 5–10% of creative budget on AI tools toward 20–30%
  ([Luma](https://lumalabs.ai/news/reshaping-creative-production)).
- **In-house content teams** — have budget, but large enterprises already capture 60% of the
  AI video creation market ([Luma](https://lumalabs.ai/news/reshaping-creative-production))
  and are being courted directly by Adobe/Meta/Amazon. A solo founder cannot sell here.

**Verdict: small performance agencies and DTC in-house growth teams, 2–20 people.** They are
also the most exposed segment — 83% of US marketing leaders would cut agency spend if content
creation were fully automated; 73% of teams using AI agents already have
([eMarketer](https://www.emarketer.com/content/ai-driven-creative-tools-expand-fast-challenging-traditional-agency-model)).
That churn is your opening: agencies buying tools to stay cheaper than the platform.

## 4. BYOK

BYOK is a developer-tool pattern, not a creative-tool pattern. The BYOK directory's own
categories are chatbots, developer tools, productivity, and privacy — its stated motivations
are cost transparency, data privacy, and model flexibility, appealing "primarily to developers
and privacy-conscious professionals rather than casual users"
([BYOKList](https://byoklist.com/)). Every comparable creative tool bundles credits: Arcads
~$110–$410/mo per-video on subscription, Creatify $19–$597/mo with expiring monthly credits
([Wireflow](https://www.wireflow.ai/blog/arcads-vs-creatify)); LTX and Runway are credit-metered
and the complaint is that credits are *opaque*, not that they exist
([G2](https://www.g2.com/products/ltx-studio/reviews?page=7&qs=pros-and-cons),
[Trustpilot](https://ca.trustpilot.com/review/runwayml.com)).

Your own BACKLOG §10 already found the fatal onboarding detail: three of four providers are
bare bearer keys with no OAuth, a Runway key is organization-scoped and unrevocable from your
side, and Midjourney has no API at all so you resell your own access. "Paste your
org-wide unscoped API key into a one-person startup's database" is not an onboarding flow a
paying agency completes.

**Verdict:** keep BYOK as an enterprise/power-user *option* — it is built, it costs nothing to
leave in, and it is a genuine differentiator for anyone burned by credit opacity. Do not make
it the default shape. Default should be bundled credits at your marked-up cost, with the one
thing every competitor fails at: **showing the price before the click**. That single UI
affordance is a named, repeated complaint about LTX and Runway and you already have
`estimate_cost` and the cost tracker to deliver it.

## 5. The wedge

You have zero published output. Nothing below matters until that changes, because the entire
credibility of a taste engine is the tape it produced.

**Sequence, concretely:**

1. **Weeks 1–3 — publish.** Ten posts from your own pipeline, on your own accounts, with
   metrics recorded. This is already named in CLAUDE.md as the highest-value next step and it
   is still the highest-value next step. Without it `promote_winners` honestly reports nothing
   and you have no proof.
2. **Weeks 2–4 — close the assembly gap.** ffmpeg concat, captions, audio bed. Not because it
   is interesting, but because 90% of marketers say editing is essential
   ([Animoto](https://www.businesswire.com/news/home/20260121875037/en/83-of-Consumers-Can-Spot-AI-Videos-36-Say-It-Lowers-Brand-Trust-According-to-Animotos-New-Report))
   and because a pre-production tool that hands back a prompt is a tool that ends in someone
   else's Resolve project. Your generate→judge→queue→publish chain is unusually complete;
   the missing 15% is what makes it a product rather than a demo.
3. **Weeks 4–8 — sell the narrow thing, to five agencies.** Not "AI pre-production studio."
   The pitch is: *"you run 40 creative variants a month, half get killed in review for being
   off-brand or uncanny — we score every variant against your brand and your past winners
   before you spend render credit, and show you the bill before you click."* That is the
   craft/uncanny/taste judge stack plus the cost tracker plus the Queue. The generator becomes
   an input, not the pitch.
4. **Proof required before charging:** your own posted metrics (step 1), plus one agency's
   before/after on render spend per approved asset. Nothing else convinces this buyer.

**Price:** $200–500/mo per seat with bundled credits. Below $100 you are selling to the churn
cohort in §3; above $1k you are selling to people Adobe already calls on.

## 6. Risks, honestly

- **The layer above the model is being absorbed by the platforms, now.** Amazon ships
  ideation→storyboard→video free; Meta ships Advantage+ image-to-video and brand-consistent
  automation; Google ships Nano Banana Pro
  ([eMarketer](https://www.emarketer.com/content/ai-driven-creative-tools-expand-fast-challenging-traditional-agency-model)).
  Any feature that lives *between* a brief and a render is on their roadmap by default.
- **Incumbents are moving into your exact position.** Higgsfield's 2026 story is explicitly
  storyboarding, character consistency, camera control and multi-model access in one workspace
  — framed for "creators, agencies, and filmmakers"
  ([mean.ceo](https://blog.mean.ceo/higgsfield-news-august-2026/)). That is your architecture,
  shipped by a funded team, and you are an adapter on top of them.
- **Price collapse.** AI production is already cited at 70–90% cheaper than traditional
  ([Adwave](https://adwave.com/resources/ai-video-ad-statistics-2026)); margins on a
  pass-through render layer compress toward zero.
- **Consumer backlash is a demand ceiling, not just a vibe.** 36% brand-trust penalty, 31%
  purchase penalty, 54% of Gen Z wanting no AI in creative work
  ([Animoto](https://www.businesswire.com/news/home/20260121875037/en/83-of-Consumers-Can-Spot-AI-Videos-36-Say-It-Lowers-Brand-Trust-According-to-Animotos-New-Report),
  [eMarketer](https://www.emarketer.com/content/consumers-rejecting-ai-generated-creator-content)).

**What makes you structurally safe:** per-account accumulated taste and performance data that
gets better with use and cannot be copied out; the LoRA path in
`docs/FOUNDATION_MODEL_OPTIONS.md` (owned portable weights are the one asset Runway/Higgsfield
structurally cannot offer, since they never hand over weights); and multi-model routing that
makes you indifferent to which provider wins.

**What makes you unsafe:** being a thin orchestration layer over three closed APIs whose
vendors are shipping your feature list. Today you are the unsafe version. The judges, the
owned weights, and published proof are the three things that move you.

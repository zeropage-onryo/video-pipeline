# ZPF Marketing Skills — Curated Bundle

Pulled from Corey Haines's [marketingskills](https://github.com/coreyhaines31/marketingskills)
(49 skills), trimmed to the ~13 that actually fit an AI video product + agency you're building
up. The rest was SaaS growth machinery that would pollute your agent's skill routing and collide
with skills you already run.

## The keystone: `product-marketing.md`
Every skill here reads a shared context file FIRST so it doesn't re-interrogate you each run.
That's the same pattern as your `context` skill. I pre-drafted `product-marketing.md` — **fill it
in before using anything else.** On install it goes to `.agents/product-marketing.md` (or
`.claude/product-marketing.md`) inside whatever project you're working in.

---

## What's in `skills/`

**Tier 0 — foundation (do this first)**
- `product-marketing` — generates/maintains the shared context file. Run it once to lock positioning.

**Tier 1 — the site (install now, useful the moment you build the Flow-style front end)**
- `site-architecture` — what pages the tool site needs, nav, URL structure. Pre-build work.
- `copywriting` — hero, landing, feature, pricing page copy. Points at your positioning file.
- `copy-editing` — tightens existing copy, kills the AI-tool-cliché voice.
- `cro` — conversion optimization on the pages once they exist.
- `seo-audit` — technical/on-page SEO health check.
- `ai-seo` — **highest-value one for you.** Getting Zero Page Films cited in ChatGPT/Perplexity/
  Claude answers. Serves the product AND your AI-eng brand.
- `schema` — structured data so both Google and AI engines parse the site.
- `programmatic-seo` — generate landing pages at scale ("AI video editing for [use case]").
  This is the one that pairs directly with "I want to automate it."

**Tier 2 — build the business up (install when you're launching / monetizing)**
- `offers` — how you package the product/service so it converts (agency angle).
- `pricing` — tiers, freemium, usage metric for a self-serve tool (product angle).
- `launch` — waitlist → beta → public launch sequence. Product Hunt etc.
- `marketing-psychology` — the persuasion primitives under all of the above.

## What's in `_mine-for-frameworks/` (do NOT install these)
`social`, `content-strategy`, `video` — these collide with your existing `content-angles`,
`post-audit`, and two-audience social strategy, and they assume B2B SaaS. Don't wire them into
your agent. Open the `references/` folders, steal the frameworks worth stealing, fold them into
the skills you already tuned. Kept here as raw material only.

## What I cut (and won't miss)
revops, prospecting, cold-email, sms, paywalls, churn-prevention, onboarding, signup,
sales-enablement, aso, directory-submissions, co-marketing, referrals, community-marketing,
influencer-marketing, marketing-loops, ads, ad-creative, ab-testing, analytics, attribution,
customer-research, competitors, competitor-profiling, lead-magnets, public-relations,
marketing-ideas, marketing-council, free-tools, image, onboarding, popups, sales-enablement.
Mostly SaaS-team or paid-media machinery. If a specific one becomes relevant later, pull just
that one from the original repo — don't bulk-install.

---

## Install (Claude Code)

Copy this bundle's `skills/` into your project's skill dir:

```bash
# from inside the project (the Flow-site repo, or a dedicated marketing project)
mkdir -p .claude/skills
cp -r zpf-marketing-skills/skills/* .claude/skills/
cp zpf-marketing-skills/product-marketing.md .agents/product-marketing.md  # keystone
```

Or pull the same subset straight from source if you'd rather track updates:

```bash
npx skills add coreyhaines31/marketingskills -a claude-code \
  --skill product-marketing site-architecture copywriting copy-editing cro \
  seo-audit ai-seo schema programmatic-seo offers pricing launch marketing-psychology
```

The `-a claude-code` flag matters — without it the installer defaults to `.agents/skills/`,
which Claude Code doesn't read.

---

## "I want to automate it" — the honest version

These skills are agent-invoked *knowledge*, not cron jobs. They don't self-run. Automation means
your existing EA agent + scheduler calls them on a cadence, with `product-marketing.md` as context.
Real wiring that fits what you already have:

1. **Weekly programmatic-SEO batch.** A scheduled task that invokes `programmatic-seo` to draft N
   new landing pages for the Flow site against a keyword/use-case list you maintain — same shape as
   your weekly-brief run, output to a review queue, you approve before publish. This is the biggest
   automation lever here.
2. **AI-SEO monitor.** Periodic `ai-seo` pass: is Zero Page Films getting cited in AI answers, and
   what content gap explains gaps. Feeds your content pipeline.
3. **Site audit on a schedule.** `seo-audit` + `schema` run monthly against the live site, propose
   fixes, you triage — mirrors your `inbox-sweep` propose-then-approve pattern.
4. **Positioning as the single source of truth.** Keep `product-marketing.md` current the way you
   keep your `context` file current; every automated marketing run reads it, so you never re-explain
   the product to a scheduled job.

What you should NOT automate to auto-publish: copy, offers, pricing, launch. Those are judgment
calls — generate drafts on a schedule, approve by hand. Same guardrail as the rest of your system.

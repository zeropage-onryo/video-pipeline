# Zero Page AI Studio — Site Plan (v2 · growth-focused)

Architecture · AI-SEO · Schema · the simplified studio. Built with the `site-architecture`,
`ai-seo`, `schema`, and `launch` skills, reading `.claude/product-marketing.md`.

> **What changed from v1:** Pricing is **deferred** — the near-term goal is *growth* (reach +
> AI citations + signups), not monetization. And the **Studio is simplified** to a Google
> Flow–style workspace: a media canvas plus a conversational assistant that runs the pipeline
> under the hood, instead of clicking through separate stage screens.

---

## 1. Focus & goals — growth, not pricing

The near-term job is to get in front of people and into AI answers, and to convert that attention
into **early-access signups**, not purchases. Pricing and monetization come *after* there are users
and usage data.

1. **Reach** — programmatic + AI-SEO so "grounded AI pre-production / [use case]" surfaces you.
2. **Credibility** — the work, the founder POV, the field notes.
3. **Capture** — a waitlist / early-access, not a checkout.

*Pricing page and monetization: deferred. Revisit with the `pricing` skill once there's demand —
it's not in the near-term build.*

---

## 2. Page hierarchy (growth surface public; app noindex)

```
Home (/)                                  ← the landing you have
├── How it works (/how-it-works)          ← real rooms → ideas → shoot, under the hood
├── Features (/features)
│   ├── Grounded ideas (/features/grounded-ideas)
│   ├── Storyboarding (/features/storyboarding)
│   ├── AI shot (/features/ai-shot)
│   └── Validated cut list (/features/validated-cut-list)
├── For (/for)                            ← use-case pages = the programmatic-SEO growth engine
│   ├── Solo filmmakers (/for/solo-filmmakers)
│   ├── Build & moto creators (/for/build-creators)
│   └── Product brands (/for/product-brands)
├── Field notes (/blog)                   ← citation + reach surface
│   └── /blog/[slug]
├── Work (/work)                          ← proof the aesthetic is real
├── Join / early access (/join)           ← the conversion target (waitlist), replaces pricing for now
├── About (/about)                        ← founder / taste / credibility
└── Studio (/studio) [app · noindex]      ← ONE workspace, pipeline under the hood (see §6)
```

No `/pricing` yet — the CTA everywhere points at **`/join`** (early access), not a checkout.

---

## 3. Navigation & URLs

- **Primary nav:** How it works · Features · For · Field notes · Work · **[Join]** / **[Enter the studio]**.
- **Footer:** the above + About, legal, social (which double as schema `sameAs`).
- **Breadcrumbs** on every L2+ page (`/features/*`, `/for/*`, `/blog/*`).
- **Internal linking:** each Feature ↔ its matching `/for` use-case ↔ one Field-note, so the cluster
  reads as authoritative to Google and AI crawlers.
- **URL rules:** lowercase, hyphenated, no trailing slash, stable slugs (they become citation targets).

---

## 4. AI-SEO — the growth engine

**The ladder:** retrieved → cited → mentioned → **recommended**. Your pages earn *cited* and
*mentioned* by being useful; *recommended* comes from offsite consensus (reviews, forums, video), so
keep shipping real work and getting talked about.

**Machine-readable files (cheap, high-leverage):**
- **`/llms.txt`** — a markdown index of key pages so LLMs find the canonical version of each topic.
- **An OKF-style knowledge bundle** — cross-linked markdown mirroring your core concepts (what
  grounded pre-production is, how the pipeline works, the comparison to generators).
- *(`/pricing.md` deferred with pricing.)*

**Crawlability:** allow the AI bots (`GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended`) in
`robots.txt` — for a product that wants to be recommended in AI answers, blocking them forfeits it.

**On-page patterns (Features · `/for` · blog):** a definition block up top, a comparison table
(Zero Page vs generative video), self-contained answer paragraphs, concrete specs ("≤6 shots",
"one AI shot per edit", "13–17s runtime enforced in code"), and an attributable founder quote.

**Biggest lever:** `/for/[use-case]` at scale via the `programmatic-seo` skill — a template + a
use-case/keyword list you maintain, output to a review queue you approve.

---

## 5. Schema (JSON-LD, one `@graph` per page)

| Page | Schema types |
|------|--------------|
| Home (`/`) | `Organization` + `WebSite` + `SoftwareApplication` |
| How it works | `WebPage` + `BreadcrumbList` |
| Feature (`/features/*`) | `SoftwareApplication` (or `WebPage`) + `BreadcrumbList` |
| Use case (`/for/*`) | `WebPage` + `FAQPage` + `BreadcrumbList` |
| Field notes (`/blog/*`) | `BlogPosting` + `BreadcrumbList` |
| Work | `CreativeWork` (per piece) + `BreadcrumbList` |
| Join | `WebPage` (no Offer schema — no pricing yet) |

**Homepage `@graph` starter** — note `offers` is set to a free/early-access beta, not a price:

```json
{
  "@context": "https://schema.org",
  "@graph": [
    { "@type": "Organization", "@id": "https://[domain]/#org",
      "name": "Zero Page AI Studio", "url": "https://[domain]/",
      "logo": "https://[domain]/logo.png",
      "sameAs": ["https://youtube.com/@[handle]", "https://instagram.com/[handle]"] },
    { "@type": "WebSite", "@id": "https://[domain]/#site",
      "url": "https://[domain]/", "name": "Zero Page AI Studio",
      "publisher": { "@id": "https://[domain]/#org" } },
    { "@type": "SoftwareApplication",
      "name": "Zero Page AI Studio",
      "applicationCategory": "MultimediaApplication", "operatingSystem": "Web",
      "description": "A grounded AI film studio: real rooms in, concepts, shot lists, and one AI shot per edit — every proposal checked in code against what actually exists.",
      "offers": { "@type": "Offer", "price": "0", "priceCurrency": "USD", "description": "Early access / free beta" } }
  ]
}
```

JSON-LD only; mark up only what's on the page; ISO-8601 dates; validate at
`search.google.com/test/rich-results` before deploy.

---

## 6. The Studio, simplified — everything under the hood (like Flow)

Flow's workspace is three zones: a left **media / scenes / tools** rail, a center **canvas**
("start creating or drop media"), and a right **conversational assistant** ("what would you like to
do?") that actually drives the work. Adopt that shape and hide the pipeline machinery.

**One screen (`/studio`), not seven.** Today the app spreads across `/concepts`, `/locations`,
`/studio/ideas`, `/library`, `/dashboard`, `/analytics`. Collapse the *navigation* into a single
workspace; the routes stay as the **engine**, the user just stops driving them by hand.

- **Left rail** (the Flow analog):
  - **All Media** — your footage + generated frames / storyboards.
  - **Rooms** — your photographed spaces (Flow's "Characters / Scenes" analog; this is the grounding).
  - **Tools** — the explicit pipeline steps, for when you want manual control.
- **Center canvas** — "Start creating or drop media." Rooms, idea cards, storyboards, and the AI
  shot all appear here as you go.
- **Right assistant** — *"What do you want to make?"* with suggestion chips
  (**Deal ideas from my rooms** · **Storyboard this** · **Draft the AI shot** · **Cut it**) and a
  prompt box. You state intent; it orchestrates `shootgen` (ideas / concept), `locations`,
  `promptgen` (AI shot), and `editgen` (cut) **behind the scenes** and drops results on the canvas.
- **The human gate stays, but goes inline.** Keeping/tossing ideas happens on the canvas (the swipe
  deck), approving a plan happens in place — no stage-screen navigation. The "pick" that
  `shortlist_rate` measures is still recorded; it's just not a separate page anymore.
- **noindex** — this is the product surface, reached through `/join`, not indexed content.

Net effect: the same grounded pipeline and the same "code enforces" guarantees, but the user
experiences one assistant-driven canvas instead of a seven-screen cockpit.

---

## 7. Build order (growth-first)

1. **Homepage `@graph` schema + `/llms.txt`** on the landing you already have. *(Fast win.)*
2. **`/join` early-access capture** (`launch` skill: waitlist → beta → public). This is the
   conversion now, in place of pricing.
3. **How it works + the 4 Feature pages** — definition blocks, the comparison table, schema.
   `copywriting` for drafts, `copy-editing` to de-cliché.
4. **`/for/[use-case]` at scale** via `programmatic-seo` — the main growth lever.
5. **Field notes blog** (`BlogPosting`) — the ongoing citation surface.
6. **Simplify the Studio** to the §6 workspace — a parallel product track.

*(Pricing intentionally absent — deferred until there's demand.)*

---

## 8. Decisions still open

- **Primary audience** (filmmakers vs brands) — still worth locking; it tilts the `/for` pages and
  the hero copy.
- *(Product-vs-agency and pricing are deferred with monetization — not blocking growth work.)*

Lock the audience in `product-marketing.md` and the Feature / `/for` copy inherits the answer.

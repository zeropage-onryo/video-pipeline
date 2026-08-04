"""
The machine-readable growth surface: robots.txt, llms.txt, sitemap.xml,
and the homepage JSON-LD graph.

Every function here is pure -- it takes the site's base URL and returns a
string. That's deliberate: these files are the one part of the app whose
*exact bytes* matter to a crawler, so they're testable without a server,
and a change to the wording is a diff in a test rather than something you
only notice when a bot stops citing you.

The public surface is small on purpose (one page today). The list below
is the single place to add a page when there is one -- robots, the
sitemap, and llms.txt all read from it, so they can't drift apart.
"""
import json
import os
from datetime import date
from typing import Optional

# The canonical origin. No trailing slash. Local by default so a fresh
# clone serves something coherent; set SITE_URL in .env before the site
# is public or every canonical tag and schema @id points at localhost.
DEFAULT_SITE_URL = "http://127.0.0.1:8000"

PRODUCT_NAME = "Zero Page AI Studio"
TAGLINE = (
    "A grounded AI film studio: real rooms in, concepts, shot lists, and one AI "
    "shot per edit — every proposal checked in code against what actually exists."
)

# path -> (title, one-line description for llms.txt, sitemap priority)
PUBLIC_PAGES = [
    ("/", PRODUCT_NAME, TAGLINE, "1.0"),
]

# The workspace and the pipeline screens behind it. Reachable, useful, and
# nobody's search result -- they're the product, not content.
PRIVATE_PREFIXES = [
    "/studio", "/dashboard", "/concepts", "/locations", "/pitches",
    "/analytics", "/library", "/videos", "/metrics",
]

# Crawlers that feed AI answers. Named explicitly rather than left to the
# `User-agent: *` default: a product that wants to be recommended inside
# AI answers has nothing to gain from blocking the crawlers that build
# them, and being explicit means a future tightening is a visible edit.
AI_CRAWLERS = [
    "GPTBot",           # OpenAI, training + browsing
    "OAI-SearchBot",    # OpenAI, ChatGPT search
    "ChatGPT-User",     # OpenAI, user-initiated fetch
    "ClaudeBot",        # Anthropic
    "Claude-User",      # Anthropic, user-initiated fetch
    "PerplexityBot",    # Perplexity
    "Perplexity-User",  # Perplexity, user-initiated fetch
    "Google-Extended",  # Google, Gemini/AI Overviews grounding
    "Applebot-Extended",
    "meta-externalagent",
    "Bingbot",
    "cohere-ai",
]


def site_url() -> str:
    """The configured origin, without a trailing slash."""
    return (os.environ.get("SITE_URL") or DEFAULT_SITE_URL).rstrip("/")


def absolute(path: str, base: Optional[str] = None) -> str:
    base = (base or site_url()).rstrip("/")
    return base + path if path != "/" else base + "/"


def robots_txt(base: Optional[str] = None) -> str:
    """
    Open the public page to everything, keep the app out of the index,
    and point every crawler at the sitemap.
    """
    base = base or site_url()
    lines = ["# Zero Page AI Studio", ""]

    disallow = [f"Disallow: {p}" for p in PRIVATE_PREFIXES]

    lines += ["User-agent: *", "Allow: /", *disallow, ""]
    for bot in AI_CRAWLERS:
        lines += [f"User-agent: {bot}", "Allow: /", *disallow, ""]

    lines += [f"Sitemap: {absolute('/sitemap.xml', base)}", ""]
    return "\n".join(lines)


def sitemap_xml(base: Optional[str] = None, lastmod: Optional[str] = None) -> str:
    base = base or site_url()
    lastmod = lastmod or date.today().isoformat()
    urls = "".join(
        "\n  <url>"
        f"\n    <loc>{absolute(path, base)}</loc>"
        f"\n    <lastmod>{lastmod}</lastmod>"
        f"\n    <priority>{priority}</priority>"
        "\n  </url>"
        for path, _title, _desc, priority in PUBLIC_PAGES
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}\n</urlset>\n"
    )


def llms_txt(base: Optional[str] = None) -> str:
    """
    A markdown index for language models: what the product is, what the
    words mean, and the canonical URL for each page. The concept
    definitions are the point -- an LLM asked "what is grounded
    pre-production" can answer from this file, and that answer is where a
    citation comes from.
    """
    base = base or site_url()
    pages = "\n".join(
        f"- [{title}]({absolute(path, base)}): {desc}"
        for path, title, desc, _priority in PUBLIC_PAGES
    )
    return f"""# {PRODUCT_NAME}

> {TAGLINE}

{PRODUCT_NAME} is an AI pre-production and edit-planning tool for filmmakers.
It is deliberately not a video generator. The model proposes; code enforces.

## What "grounded" means here

Generative video tools invent the world: the rooms, the light, the whole
scene come out of the model, and keeping them consistent across shots is
the central problem. This inverts that. You photograph the spaces you
actually have; vision models describe each one's geometry, light sources,
textures, and constraints; and every generated concept is validated
against that list. A concept set in a room you have not photographed is
rejected in code, not warned about.

The same rule applies one stage later. An edit is built from an ingested
footage manifest, so every cut references a real filename with in/out
points inside that clip's real duration.

## The pipeline

1. **Rooms** — photograph a space; a vision model records what it can and
   cannot shoot.
2. **Ideas** — a cheap slate of concepts generated from those rooms in one
   call, so they vary against each other.
3. **The pick** — a human keeps a few. That choice is the label the system
   measures prompt changes against.
4. **Shot list** — the kept ideas get a plan of at most 6 shots.
5. **The AI shot** — exactly one generated clip per edit, for the moment
   real footage cannot cover. Paste-ready for Veo, Kling, or Runway.
6. **Cut list** — after the shoot, footage is ingested and a validated
   edit spec is produced: real filenames, real in/out points, runtime
   enforced at 13–17 seconds.

## Specifications

- At most 6 shots per concept, enforced in code.
- Exactly one AI-generated shot per edit.
- Runtime validated to 13–17 seconds for short-form.
- Every shot's location must be a space that exists in the database.
- Every cut's filename must exist in the footage manifest.
- Retrieval-grounded ideation over a PostgreSQL + pgvector reference
  library, so generated work inherits a house style rather than a
  model's default taste.

## Compared to generative video tools

| | Generative video (Runway, Flow, Sora) | {PRODUCT_NAME} |
|---|---|---|
| Source of truth | The model | Your photographed rooms and shot footage |
| Generated shots | Every shot | Exactly one per edit |
| Main failure mode | Inconsistency between shots | Refuses to plan what you cannot shoot |
| Output | Clips | A shot list, and a validated cut list you execute |

## Pages

{pages}

## Attribution

Built by Michael Massaad, an actor, editor, and colorist shooting
Blackmagic 6K, as the pre-production tool for Zero Page Films. The
aesthetic constraints in the system are a working filmmaker's, not a
model's defaults.
"""


def homepage_schema(base: Optional[str] = None) -> dict:
    """
    The homepage @graph: who publishes this, what site it is, and what the
    software does. Only things actually on the page are marked up, and
    there is no Offer -- nothing is for sale yet, and inventing a price in
    schema is the kind of thing that costs you a rich result.
    """
    base = base or site_url()
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{base}/#org",
                "name": PRODUCT_NAME,
                "url": f"{base}/",
                "description": TAGLINE,
                "founder": {"@type": "Person", "name": "Michael Massaad"},
            },
            {
                "@type": "WebSite",
                "@id": f"{base}/#site",
                "url": f"{base}/",
                "name": PRODUCT_NAME,
                "publisher": {"@id": f"{base}/#org"},
                "inLanguage": "en",
            },
            {
                "@type": "SoftwareApplication",
                "@id": f"{base}/#app",
                "name": PRODUCT_NAME,
                "url": f"{base}/",
                "applicationCategory": "MultimediaApplication",
                "operatingSystem": "Web",
                "description": TAGLINE,
                "publisher": {"@id": f"{base}/#org"},
                "featureList": [
                    "Vision-described shooting locations",
                    "Concept ideation grounded in real spaces",
                    "Shot lists capped at six shots",
                    "One AI-generated shot per edit",
                    "Cut lists validated against a footage manifest",
                    "Retrieval-grounded reference library",
                ],
            },
        ],
    }


def homepage_schema_json(base: Optional[str] = None) -> str:
    return json.dumps(homepage_schema(base), indent=2, ensure_ascii=False)

"""
The research scout: crawls the internet for tonight's spark instead of
rotating a static list.

Before this, every autonomous run's direction came from
`prompts/sparks.txt` -- eight hand-written lines, rotated by day of year
(`trigger.pick_spark`). That is deterministic and free, and it is also
the reason the queue kept filling with variations on the same eight
ideas: nothing in the pipeline had ever looked outside the repo. The
scout is the missing input side. It reads the world, then hands the
graph one line.

FOUR LANES, each best-effort and independently skippable:

  web       Gemini grounded with the google_search tool. The broad
            culture/trend lane, and the only one that needs no key
            beyond GEMINI_API_KEY, which every other stage already uses.
  shorts    YouTube Data API search.list via youtube.search_videos --
            real titles against real view counts, so format signal is
            grounded in numbers rather than vibes. Costs 100 units of a
            free 10,000/day quota per query.
  feeds     RSS/Atom feeds (and Reddit .json where it will answer)
            named in prompts/scout_sources.txt. No key, no new
            dependency -- stdlib xml.etree, and `requests`, which
            storage and instagram already pull in.
  instagram Business Discovery on the handles already in inspiration.py,
            plus hashtag top_media. NOT a For You feed -- no Instagram
            API exposes one (see gather_instagram). Needs its own
            Facebook-Login credential, IG_GRAPH_TOKEN, and stays dark
            without it.
  creators  inspiration.combined_grounding(brand) -- the distilled
            formulas of the accounts already on file. Not a crawl; the
            in-repo lane that keeps the scout anchored to what this
            filmmaker has actually decided is good.

WHY A DIGEST STEP EXISTS. The crawl is wide and the socket it feeds is
one line: `{spark}` in prompts/scene_brief_prompt.txt, sitting beside a
CRAG reference block that `orchestrator.ground_rag` has already filled.
Passing raw crawl text through would drown the brief in trend-speak and
produce concepts about the internet rather than about a room. So no
gathered text ever reaches shootgen. Everything is compressed by ONE
Gemini call into scored candidate sparks -- a direction, a rationale,
and a checkable evidence line -- and only the winning direction is
generated from. The rationale and evidence are stored, not injected,
so a human can audit why a night went the way it did without that
reasoning steering the camera.

THE GATES, in the order they run:
  1. avoid_guidance (winners.py)   folded into the digest prompt, so
     patterns already marked "didn't work" can't come back as discoveries.
  2. recent sparks                 the last NOVELTY_DAYS of banked
     findings go into the prompt as a do-not-repeat list, and any
     candidate that still collides on `_spark_key` is dropped in code.
     Prompts request, code enforces -- the standing rule in this repo.
  3. SCORE_FLOOR                   a candidate under the floor is banked
     but never auto-served, so a thin crawl night degrades to
     sparks.txt rather than spending on a weak idea.

THE BIN. A pass also banks the IMAGES behind it -- YouTube thumbnails
(the frame a creator chose for a video that is actually travelling) and
feed lead images -- normalised into `data/refs` through src/refbin.py.
That destination is the whole design: a scouted image comes out as an
ordinary `/refs/<sha>.jpg`, the same URL a photo dragged onto the Create
composer gets, so it resolves through `_resolve_asset_photo`, attaches
as an `image_ref`, and lands on the shot with no new route, no new
resolver and no special case anywhere downstream. Each row keeps its
`source_url`, because these are other people's frames held as mood
reference and a tile nobody can trace is the wrong thing to put in
front of someone about to render from it.

The bin is keyed by PASS, not by candidate: the crawl is one act of
research and the sparks are readings of it, so pinning an image to one
candidate would invent a link the digest never made.

TWO SURFACES, one bank. `/api/scout/spark` hands the Create composer a
spark plus its bin (app/static/zpf/studio.js fills the idea box and
pre-attaches the images); `orchestrator.scout` claims one for the
nightly graph. Neither one stamps a finding on the way out -- the claim
happens when a run actually writes something, so loading a spark and
changing your mind does not burn it.

BANKED, NOT CONSUMED IN PLACE. Findings land in `scout_findings` and are
claimed one at a time with `next_spark()` / `mark_used()`. Two reasons:
a crashed run doesn't lose the night's research, and the 16-run nightly
batch (2 brands x the spark list, see run_morning_prompts.sh) can't fire
the same discovered spark twice.

BRAND-SCOPED throughout, same three values and the same reasoning as
inspiration.py: "antihero" | "zeropage" | "both". Antihero's moto/noir
sources must not seed Zero Page's faceless ideation.

    venv/bin/python -m src.scout run --brand zeropage --count 4
    venv/bin/python -m src.scout list --brand zeropage
    venv/bin/python -m src.scout next --brand zeropage

Verified live 2026-08-31: 20 usable signals across the lanes produced 3
scored sparks and 6 binned reference images. Two lane bugs only a real
run could have shown -- YouTube's keyword index returns NOTHING for the
sentence-shaped queries the grounded lane wants (hence two query sets),
and Reddit answers 403 to .json and 429 to .rss from a datacenter IP
(hence RSS defaults in prompts/scout_sources.txt).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

from . import db, inspiration, refbin, winners
from .gemini_utils import strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
SOURCES_PATH = PROMPTS_DIR / "scout_sources.txt"
DIGEST_PROMPT_PATH = PROMPTS_DIR / "scout_digest_prompt.txt"

BRANDS = inspiration.BRANDS

# A candidate below this is banked for the record but never auto-served:
# `next_spark` skips it, and the caller falls back to sparks.txt. A thin
# crawl night should cost nothing, not produce a weak scene.
SCORE_FLOOR = 0.55
# How far back novelty looks. Two weeks is roughly the point where a
# repeated direction reads as a series rather than as the generator
# being stuck -- and it is comfortably longer than the 8-line sparks.txt
# rotation it replaces.
NOVELTY_DAYS = 14
# Per-lane caps. The digest call is the only expensive one here, and its
# cost is the SIZE of the signal block, so each lane is trimmed before
# the model ever sees it rather than after.
MAX_PER_LANE = 8
NET_TIMEOUT = 12
# The composer accepts 6 references per generation (MAX_ATTACH in
# app/static/zpf/studio.js), so a bin bigger than that is a bin whose
# tail can never be used. Banking fewer, better images also keeps the
# fetch inside one nightly step.
MAX_BIN_IMAGES = 6

# Every network call in this module is wrapped and returns [] on
# failure. Stated once here rather than re-argued at each site: the
# scout is an enhancement over a working static rotation, so no lane
# may ever be able to fail a night. `errors` on the result dict is how
# a silent lane still says something -- a crawl that quietly returns
# nothing looks exactly like a healthy one otherwise, which is the same
# failure mode that hid the dead launchd job for eleven nights.

SCHEMA = """
CREATE TABLE IF NOT EXISTS scout_findings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    brand      TEXT NOT NULL,
    spark      TEXT NOT NULL,
    spark_key  TEXT NOT NULL,
    rationale  TEXT,
    evidence   TEXT,
    sources    TEXT,
    score      REAL,
    lanes      TEXT,
    used_at    TEXT,
    run_id     TEXT,
    pass_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_scout_brand_used
    ON scout_findings (brand, used_at);

-- The research bin: the IMAGES behind a pass, already normalised into
-- data/refs and addressed by the same /refs/<sha>.jpg URL a composer
-- upload gets. That shape is the whole point -- it means a scouted
-- image resolves through _resolve_asset_photo, rides into a generation
-- as an image_ref, and is stored on the shot exactly like a photo
-- dragged onto the composer by hand. No new route, no new resolver.
--
-- Keyed by pass, not by finding: the crawl is one act of research and
-- the candidate sparks are readings OF it, so pinning an image to one
-- candidate would be inventing a link the digest never made.
CREATE TABLE IF NOT EXISTS scout_bin (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    pass_id    TEXT NOT NULL,
    brand      TEXT NOT NULL,
    url        TEXT NOT NULL,
    source_url TEXT,
    title      TEXT,
    lane       TEXT,
    metric     TEXT
);
CREATE INDEX IF NOT EXISTS idx_scout_bin_pass ON scout_bin (pass_id);
"""

# What each brand's engine is actually looking for. Kept in code rather
# than the sources file because these steer the *grounded search* query
# and the digest's framing, not a list of URLs to fetch.
# The two crawling lanes want DIFFERENT query shapes, which is worth
# stating because using one set for both is how this was first built and
# it produced a dead lane: YouTube's search.list is a keyword index, and
# handed "faceless short-form video formats getting traction this week"
# it returned zero results (verified 2026-08-31), while the grounded web
# search wants exactly that kind of sentence. Short keywords for the
# index, natural language for the model.
# Aimed at CRAFT, not at the content business. The first pass asked what
# was "getting traction" and "trending", and got back exactly that: an
# industry talking about monetisation, policy changes and gear launches.
# Real signal, wrong altitude -- you cannot shoot a monetisation update.
# These ask what images and staging are landing, which is the thing a
# spark can actually be made of.
WEB_QUERIES = {
    "antihero": [
        "what night photography and moody motorcycle imagery is resonating "
        "right now, and what makes those images work",
        "small human rituals and gestures people are responding to in "
        "short film and photography this month",
    ],
    "zeropage": [
        "what unsettling or uncanny imagery is landing right now in short "
        "film, and what staging makes it work",
        "quiet domestic-interior imagery and small strange details people "
        "are responding to this month",
    ],
}
# Ordered by RELEVANCE, not view count. Sorting a broad keyword by views
# over a 30-day window returns whatever went globally viral that month --
# the first run of this came back with an Encanto clip and a football
# meme against "ai video shorts" -- which is noise, not format signal.
SHORTS_QUERIES = {
    "antihero": ["motorcycle night cinematic short", "garage detail macro moody"],
    # NOT "faceless channel format" -- that returns videos ABOUT running a
    # faceless channel (monetisation, policy, how-to), which is the
    # business, not the look. These ask for the look itself.
    "zeropage": ["liminal empty room short film", "unsettling quiet interior short"],
}
BRAND_NOTES = {
    "antihero": ("Moto/noir personal brand. A real person, real machine, real "
                 "rooms. Low-key night grade. The machine is a recurring "
                 "character, not a subject."),
    "zeropage": ("Faceless, format-driven, uncanny. No recognisable person. "
                 "The format itself is the hook."),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init(path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS will not add a column to a table
        # that already exists -- a database from before the bin needs
        # pass_id added explicitly (same pattern as inspiration.init).
        existing = {r[1] for r in conn.execute("PRAGMA table_info(scout_findings)")}
        if "pass_id" not in existing:
            conn.execute("ALTER TABLE scout_findings ADD COLUMN pass_id TEXT")


def _spark_key(spark: str) -> str:
    """Normalised form used for novelty, so "The Last Check Before
    Leaving" and "the last check before leaving." collide. Deliberately
    crude -- lowercase, strip punctuation, drop the small words that
    carry no direction -- because the alternative (an embedding
    similarity call) makes novelty cost money and makes tests need a
    model."""
    words = re.findall(r"[a-z0-9]+", (spark or "").lower())
    stop = {"a", "an", "the", "of", "in", "on", "at", "to", "and", "is", "it",
            "that", "this", "with", "for"}
    return " ".join(w for w in words if w not in stop)


# --- lane 1: grounded web search ------------------------------------------

def gather_web(brand: str, client, model: str, queries=None) -> list[dict]:
    """Gemini with the google_search tool: real results with citations,
    on the key every other stage already uses, so this lane adds no new
    credential to keep alive.

    `client` is passed in rather than built here for the same reason it
    is everywhere else in this repo -- a test patches nothing and simply
    hands over a fake."""
    signals: list[dict] = []
    for query in (queries or WEB_QUERIES.get(brand) or WEB_QUERIES["zeropage"]):
        try:
            from google.genai import types
            resp = client.models.generate_content(
                model=model,
                contents=(
                    f"{query}. Answer with 5 short bullet lines, each naming ONE "
                    "specific concrete thing happening right now -- a format, a "
                    "visual move, a subject people are responding to. No preamble."
                ),
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]),
            )
            text = (getattr(resp, "text", "") or "").strip()
            urls = _grounding_urls(resp)
            for line in [_plain(ln) for ln in text.splitlines() if ln.strip()][:5]:
                if not line:
                    continue
                signals.append({"lane": "web", "detail": line,
                                "url": urls[0] if urls else "", "metric": ""})
        except Exception as e:
            signals.append({"lane": "web", "error": f"{type(e).__name__}: {e}"})
    return signals[:MAX_PER_LANE + 2]


def _plain(line: str) -> str:
    """A model bullet, stripped to its sentence. The grounded lane
    answers in markdown -- leading dashes, ** emphasis, trailing colons
    -- and passing that through means the digest reads syntax as
    content and the spark comes back wearing asterisks."""
    line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", line or "")
    line = re.sub(r"\*{1,3}|__|`", "", line)
    return line.strip().strip(":").strip()


def _grounding_urls(resp) -> list[str]:
    """The citation URLs off a grounded response, or [] from any shape
    that doesn't carry them. Every layer here is optional in the SDK's
    schema, so this walks defensively rather than trusting the path."""
    try:
        out = []
        for cand in (getattr(resp, "candidates", None) or []):
            meta = getattr(cand, "grounding_metadata", None)
            for chunk in (getattr(meta, "grounding_chunks", None) or []):
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", None)
                if uri:
                    out.append(uri)
        return out
    except Exception:
        return []


# --- lane 2: youtube shorts ------------------------------------------------

def gather_shorts(brand: str, api_key=None) -> list[dict]:
    """Real titles against real view counts. Format signal that can be
    checked, not inferred."""
    from . import youtube
    key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return [{"lane": "shorts", "error": "no YOUTUBE_API_KEY"}]
    signals: list[dict] = []
    for query in (SHORTS_QUERIES.get(brand) or [])[:2]:
        result = youtube.search_videos(query, key, limit=MAX_PER_LANE // 2,
                                       order="relevance")
        if not result.get("ok"):
            signals.append({"lane": "shorts", "error": result.get("error", "search failed")})
            continue
        for v in result["videos"]:
            views = v.get("views")
            # YouTube returns titles HTML-escaped (&#39;, &amp;). Left
            # as-is they reach the digest as literal entities and come
            # back inside a spark.
            signals.append({
                "lane": "shorts",
                "detail": html.unescape(v.get("title", "") or ""),
                "url": v.get("url", ""),
                "image": v.get("thumbnail", ""),
                "metric": f"{views:,} views" if isinstance(views, int) else "",
            })
    return signals


# --- lane 3: feeds (no key) ------------------------------------------------

def load_sources(path: Path = SOURCES_PATH, brand: Optional[str] = None) -> list[str]:
    """`<brand> <url>` lines, filtered to the brand asking plus "both".
    Missing file -> [], same contract as trigger.load_sparks."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        tag, url = parts[0].strip().lower(), parts[1].strip()
        if brand and tag not in (brand, "both"):
            continue
        out.append(url)
    return out


def gather_feeds(brand: str, sources=None) -> list[dict]:
    signals: list[dict] = []
    for url in (sources if sources is not None else load_sources(brand=brand)):
        try:
            headers = {"User-Agent": "zeropage-scout/1.0 (research; contact via repo)"}
            resp = requests.get(url, headers=headers, timeout=NET_TIMEOUT)
            resp.raise_for_status()
            items = (_parse_reddit(resp.text) if ".json" in url
                     else _parse_feed(resp.text))
            signals.extend(items[:4])
        except Exception as e:
            signals.append({"lane": "feeds", "error": f"{url}: {type(e).__name__}"})
    return signals[:MAX_PER_LANE + 4]


def _parse_reddit(body: str) -> list[dict]:
    data = json.loads(body)
    out = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = (post.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "lane": "feeds",
            "detail": title,
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "image": _reddit_image(post),
            "metric": f"{post.get('ups', 0)} upvotes",
        })
    return out


def _reddit_image(post: dict) -> str:
    """The post's own preview image, or "" -- never the `thumbnail`
    field, which is often the literal string "self"/"default"/"nsfw"
    rather than a URL, and is 140px wide when it is one.

    Reddit HTML-escapes the ampersands in preview URLs (they are signed
    with query parameters), so a raw copy 403s. Unescaping is what makes
    the fetch work at all."""
    try:
        images = ((post.get("preview") or {}).get("images") or [])
        source = (images[0].get("source") or {}).get("url") if images else ""
        if source:
            return source.replace("&amp;", "&")
    except Exception:
        pass
    thumb = post.get("thumbnail") or ""
    return thumb if thumb.startswith("http") else ""


def _parse_feed(body: str) -> list[dict]:
    """RSS and Atom with one walk, via stdlib. Namespaces are stripped
    by matching on the local tag name -- the alternative is carrying a
    namespace map that every feed disagrees about."""
    root = ET.fromstring(body)
    out = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
            continue
        title = link = image = ""
        for child in el:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "title":
                title = (child.text or "").strip()
            elif tag == "link":
                link = (child.text or child.attrib.get("href") or "").strip()
            elif tag in ("thumbnail", "content") and child.attrib.get("url"):
                image = image or child.attrib["url"]        # media:thumbnail
            elif tag in ("content", "encoded", "description") and child.text:
                image = image or _first_img(child.text)
        if title:
            out.append({"lane": "feeds", "detail": html.unescape(title), "url": link,
                        "image": image, "metric": ""})
    return out


def _first_img(html: str) -> str:
    """The first <img src> in an entry body. Feeds put the article's
    lead image there and nowhere machine-readable, so this is the only
    way most of them contribute anything to the bin."""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)', html or "")
    return match.group(1) if match else ""


# --- lane 5: Instagram, what is actually performing ------------------------

# Hashtags the top_media half reads. Kept short and stable ON PURPOSE:
# Meta's cap is 30 NEW tags per rolling 7 days (the id lookup is what
# counts, and instagram.hashtag_id caches ids forever), so a fixed small
# set costs its budget once and then runs free. Churning this list is
# what would starve the lane.
INSTAGRAM_TAGS = {
    "antihero": ["motorcyclephotography", "nightphotography", "moodygrams"],
    "zeropage": ["experimentalfilm", "liminalspaces", "analoghorror"],
}


def gather_instagram(brand: str, path=db.DB_PATH, limit_per_source: int = 4) -> list[dict]:
    """Two reads, one lane.

    `business_discovery` on the handles already in inspiration.py -- the
    creators Mike chose -- and `hashtag_top_media` on a small fixed tag
    set. Neither is a For You feed: no Instagram API exposes one (probed
    against his own token 2026-08-31; explore/reels/trending/discover all
    answer "nonexisting field"), and the alternative is scraping a
    logged-in session, which is against Meta's terms and risks the very
    account this pipeline posts to.

    What these two give instead is arguably the better input for
    ideation: not what an algorithm decided to show HIM, but what is
    demonstrably landing -- posts with their like and comment counts,
    and Meta's own "top" ranking for a tag.

    Dark until IG_GRAPH_TOKEN exists, and it says so once rather than
    once per handle: a lane that needs a credential should report the
    missing credential, not eight copies of the same failure.
    """
    from . import instagram
    ok, reason = instagram.research_ready()
    if not ok:
        return [{"lane": "instagram", "error": reason}]

    signals: list[dict] = []

    handles = []
    try:
        handles = [a["handle"] for a in inspiration.list_accounts(path=path)
                   if a.get("brand") in (brand, "both")]
    except Exception as e:
        signals.append({"lane": "instagram", "error": f"handles unavailable: {e}"})

    for handle in handles[:6]:
        result = instagram.business_discovery(handle, limit=limit_per_source)
        if not result.get("ok"):
            signals.append({"lane": "instagram",
                            "error": f"@{handle}: {result.get('error', 'unavailable')}"})
            continue
        for post in result["posts"]:
            signals.append(_ig_signal(post, source=f"@{handle}"))

    for tag in (INSTAGRAM_TAGS.get(brand) or [])[:3]:
        result = instagram.hashtag_top_media(tag, limit=limit_per_source, path=path)
        if not result.get("ok"):
            signals.append({"lane": "instagram",
                            "error": f"#{tag}: {result.get('error', 'unavailable')}"})
            continue
        for post in result["media"]:
            signals.append(_ig_signal(post, source=f"#{tag}"))

    return [s for s in signals if s.get("error") or s.get("detail")][:MAX_PER_LANE + 6]


def _ig_signal(post: dict, source: str) -> dict:
    """One post as a signal. The caption is the detail -- trimmed hard,
    because an Instagram caption runs to paragraphs of hashtags and the
    digest is paying for every one of them.

    `media_url` is a signed CDN link that expires, which is fine: the
    bin fetches it during this pass and stores its own copy. The
    permalink is what gets kept as the source, and for a hashtag post it
    is the ONLY attribution available -- Meta strips `username` from
    hashtag media."""
    caption = " ".join((post.get("caption") or "").split())
    caption = re.sub(r"(?:\s*#\w+)+\s*$", "", caption).strip()
    likes = post.get("like_count")
    comments = post.get("comments_count")
    metric = " · ".join(bit for bit in (
        f"{likes:,} likes" if isinstance(likes, int) else "",
        f"{comments:,} comments" if isinstance(comments, int) else "") if bit)
    image = post.get("media_url") if post.get("media_type") in ("IMAGE", "CAROUSEL_ALBUM") \
        else (post.get("thumbnail_url") or "")
    return {"lane": "instagram",
            "detail": f"{source}: {caption[:180]}" if caption else f"{source}: (no caption)",
            "url": post.get("permalink", ""),
            "image": image or "",
            "metric": metric}


# --- lane 4: the accounts already on file ----------------------------------

def gather_creators(brand: str, path=db.DB_PATH) -> list[dict]:
    """Not a crawl -- the formulas already decided to be good. Included
    as a lane so the digest weighs discovery against the brand's own
    taste in one call, rather than finding something novel and
    off-brand and having the concept evaluator reject it three stages
    later."""
    try:
        block = inspiration.combined_grounding(brand=brand, path=path)
    except Exception as e:
        return [{"lane": "creators", "error": f"{type(e).__name__}: {e}"}]
    if not block:
        return []
    return [{"lane": "creators", "detail": line.lstrip("- ").strip(), "url": "", "metric": ""}
            for line in block.splitlines()[1:] if line.strip()]


# --- the digest ------------------------------------------------------------

def format_signals(signals: list[dict]) -> str:
    lines = []
    for s in signals:
        if s.get("error") or not s.get("detail"):
            continue
        bits = [f"[{s['lane']}]", s["detail"]]
        if s.get("metric"):
            bits.append(f"({s['metric']})")
        if s.get("url"):
            bits.append(f"<{s['url']}>")
        lines.append(" ".join(bits))
    return "\n".join(lines)


def recent_sparks(brand: str, days: int = NOVELTY_DAYS, path=db.DB_PATH) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with db.connect(path) as conn:
            rows = conn.execute(
                "SELECT spark FROM scout_findings WHERE brand = ? AND created_at >= ? "
                "ORDER BY created_at DESC", (brand, since)).fetchall()
        return [r["spark"] for r in rows]
    except Exception:
        return []


def build_digest_prompt(brand: str, signals: list[dict], count: int,
                        avoid: str = "", recent=None) -> str:
    template = DIGEST_PROMPT_PATH.read_text()
    recent = recent or []
    return (template
            .replace("{brand}", brand)
            .replace("{brand_note}", BRAND_NOTES.get(brand, ""))
            .replace("{count}", str(count))
            .replace("{avoid}", avoid or "")
            .replace("{recent}", "\n".join(f"- {s}" for s in recent) or "(nothing yet)")
            .replace("{signals}", format_signals(signals) or "(the crawl came back empty)"))


def parse_digest_response(text: str) -> list[dict]:
    """Tolerant of the usual model output shapes -- fenced JSON, a bare
    list, a stray leading word. Returns [] rather than raising: a
    malformed digest is a night that falls back to sparks.txt, not a
    night that crashes."""
    try:
        data = json.loads(strip_fences(text or ""))
    except Exception:
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except Exception:
            return []
    candidates = data.get("candidates", data) if isinstance(data, dict) else data
    if not isinstance(candidates, list):
        return []
    out = []
    for c in candidates:
        if not isinstance(c, dict) or not (c.get("spark") or "").strip():
            continue
        try:
            score = float(c.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        out.append({
            "spark": c["spark"].strip(),
            "rationale": (c.get("rationale") or "").strip(),
            "evidence": (c.get("evidence") or "").strip(),
            "sources": [s for s in (c.get("sources") or []) if isinstance(s, str)],
            "score": max(0.0, min(1.0, score)),
        })
    return out


def digest(brand: str, signals: list[dict], client, model: str, count: int = 4,
           path=db.DB_PATH) -> list[dict]:
    """One call, wide in and narrow out. The gates the prompt is asked
    to respect are re-checked in code by `scout()` -- the prompt is the
    request, not the enforcement."""
    prompt = build_digest_prompt(
        brand, signals, count,
        avoid=winners.avoid_guidance(path=path),
        recent=recent_sparks(brand, path=path))
    resp = client.models.generate_content(model=model, contents=prompt)
    return parse_digest_response(getattr(resp, "text", "") or "")


# --- the bank --------------------------------------------------------------

def record(brand: str, candidate: dict, lanes="", pass_id="", path=db.DB_PATH) -> int:
    init(path)
    with db.connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO scout_findings (created_at, brand, spark, spark_key, "
            "rationale, evidence, sources, score, lanes, pass_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), brand, candidate["spark"], _spark_key(candidate["spark"]),
             candidate.get("rationale", ""), candidate.get("evidence", ""),
             json.dumps(candidate.get("sources", [])),
             candidate.get("score", 0.0), lanes, pass_id))
        return cur.lastrowid


# --- the research bin ------------------------------------------------------

def stash_images(brand: str, pass_id: str, signals: list[dict],
                 limit: int = MAX_BIN_IMAGES, path=db.DB_PATH,
                 fetch=None) -> list[dict]:
    """Pull the images behind this pass into data/refs and bank them.

    What lands here is the visual evidence, not decoration: a YouTube
    thumbnail is the frame the creator chose for a video that is
    actually travelling, and a Reddit preview is the image a post
    earned its upvotes with. That is the same argument the digest makes
    in words, in a form the Create composer can attach.

    Every image keeps its `source_url`. A reference with no provenance
    is one nobody can check, and these came off other people's posts --
    the surface that shows them has to be able to say where each one is
    from.

    De-duped by the URL the bin returns, which is content-addressed
    (refbin.save), so the same thumbnail found on two nights is one
    file and one row per pass. Never raises: an unreachable image is a
    missing picture, not a failed research pass.
    """
    fetch = fetch or refbin.fetch
    init(path)
    stored: list[dict] = []
    seen: set[str] = set()
    for s in signals:
        if len(stored) >= limit:
            break
        remote = (s.get("image") or "").strip()
        if not remote:
            continue
        local = fetch(remote)
        if not local or local in seen:
            continue
        seen.add(local)
        row = {"url": local, "source_url": s.get("url", ""),
               "title": s.get("detail", ""), "lane": s.get("lane", ""),
               "metric": s.get("metric", "")}
        try:
            with db.connect(path) as conn:
                cur = conn.execute(
                    "INSERT INTO scout_bin (created_at, pass_id, brand, url, "
                    "source_url, title, lane, metric) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (_now(), pass_id, brand, row["url"], row["source_url"],
                     row["title"], row["lane"], row["metric"]))
                row["id"] = cur.lastrowid
        except Exception:
            continue
        stored.append(row)
    return stored


def bin_for_pass(pass_id: str, path=db.DB_PATH) -> list[dict]:
    if not pass_id:
        return []
    try:
        init(path)
        with db.connect(path) as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM scout_bin WHERE pass_id = ? ORDER BY id", (pass_id,))]
    except Exception:
        return []


def get_finding(finding_id: int, path=db.DB_PATH) -> Optional[dict]:
    try:
        with db.connect(path) as conn:
            row = conn.execute("SELECT * FROM scout_findings WHERE id = ?",
                               (finding_id,)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def claims(finding_id: int, idea: str, path=db.DB_PATH) -> bool:
    """Is `idea` still the spark this finding proposed?

    The Create composer decides whether to send a finding id, and a
    client-side flag is exactly the thing that goes stale: load a
    researched spark, type your own idea over it, press Create, and a
    sticky id claims a spark that never wrote anything -- silently, out
    of a bank whose whole purpose is that research is not lost. So the
    server checks rather than trusts. Mike's own ideas are a separate
    path from the scout's, and this is the line between them.

    Compared on `_spark_key`, the same normalisation novelty uses: a
    capitalisation or punctuation difference is still the scout's
    direction, a reworded one is his. Ties break toward NOT claiming --
    an unclaimed spark gets offered again, which is mild; a claimed one
    that produced nothing is research quietly thrown away.
    """
    finding = get_finding(finding_id, path=path)
    if not finding:
        return False
    return _spark_key(finding.get("spark") or "") == _spark_key(idea or "")


def bin_for_finding(finding_id: int, path=db.DB_PATH) -> list[dict]:
    """The images from the research pass this spark was read out of --
    what the Create composer pre-attaches when the spark is loaded."""
    try:
        with db.connect(path) as conn:
            row = conn.execute("SELECT pass_id FROM scout_findings WHERE id = ?",
                               (finding_id,)).fetchone()
    except Exception:
        return []
    return bin_for_pass(row["pass_id"] if row else "", path=path)


def list_findings(brand=None, unused_only=False, limit=50, path=db.DB_PATH) -> list[dict]:
    try:
        init(path)
        sql = "SELECT * FROM scout_findings WHERE 1=1"
        args: list = []
        if brand:
            sql += " AND brand = ?"
            args.append(brand)
        if unused_only:
            sql += " AND used_at IS NULL"
        sql += " ORDER BY score DESC, created_at DESC LIMIT ?"
        args.append(limit)
        with db.connect(path) as conn:
            return [dict(r) for r in conn.execute(sql, args)]
    except Exception:
        return []


def next_spark(brand: str, path=db.DB_PATH, floor: float = SCORE_FLOOR) -> Optional[dict]:
    """The highest-scoring unused finding at or above the floor, or None
    -- which is the caller's signal to fall back to sparks.txt. Does not
    claim it; `mark_used` does, once the run it seeded actually exists."""
    for row in list_findings(brand=brand, unused_only=True, path=path):
        if (row.get("score") or 0.0) >= floor:
            return row
    return None


def mark_used(finding_id: int, run_id: str = "", path=db.DB_PATH) -> None:
    try:
        with db.connect(path) as conn:
            conn.execute(
                "UPDATE scout_findings SET used_at = ?, run_id = ? WHERE id = ?",
                (_now(), run_id, finding_id))
    except Exception:
        pass        # a claimed-twice spark is a worse outcome than a lost stamp,
                    # but neither is worth failing a run that already generated


# --- the pass --------------------------------------------------------------

def scout(brand: str = "zeropage", count: int = 4, *, client=None, model=None,
          lanes=("web", "shorts", "feeds", "instagram", "creators"),
          path=db.DB_PATH) -> dict:
    """One full research pass. Returns
    {"ok", "findings": [...], "errors": [...], "signals": <int>}.

    `ok` is False only when nothing could be banked -- every other
    degradation (a dead lane, a thin crawl, a candidate rejected for
    novelty) shows up in `errors` and still leaves a usable night."""
    if brand not in BRANDS:
        raise ValueError(f"brand must be one of {BRANDS}, got {brand!r}")
    init(path)
    pass_id = uuid.uuid4().hex

    from . import shootgen
    model = model or os.environ.get("GEMINI_MODEL", shootgen.MODEL)
    if client is None:
        from google import genai
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY")
                              or os.environ.get("GOOGLE_API_KEY"))

    signals: list[dict] = []
    if "web" in lanes:
        signals += gather_web(brand, client, model)
    if "shorts" in lanes:
        signals += gather_shorts(brand)
    if "feeds" in lanes:
        signals += gather_feeds(brand)
    if "instagram" in lanes:
        signals += gather_instagram(brand, path=path)
    if "creators" in lanes:
        signals += gather_creators(brand, path=path)

    errors = [s["error"] for s in signals if s.get("error")]
    usable = [s for s in signals if s.get("detail")]
    if not usable:
        return {"ok": False, "findings": [], "signals": 0, "pass_id": pass_id,
                "bin": [], "errors": errors or ["every lane came back empty"]}

    try:
        candidates = digest(brand, usable, client, model, count=count, path=path)
    except Exception as e:
        return {"ok": False, "findings": [], "signals": len(usable),
                "pass_id": pass_id, "bin": [],
                "errors": errors + [f"digest failed: {type(e).__name__}: {e}"]}

    # Novelty, enforced in code. The prompt was given the recent list and
    # asked to avoid it; this is what makes that true.
    seen = {_spark_key(s) for s in recent_sparks(brand, path=path)}
    stored = []
    for c in candidates:
        key = _spark_key(c["spark"])
        if not key or key in seen:
            errors.append(f"dropped as a repeat: {c['spark']!r}")
            continue
        seen.add(key)
        c["id"] = record(brand, c, lanes=",".join(lanes), pass_id=pass_id, path=path)
        stored.append(c)

    if not stored:
        return {"ok": False, "findings": [], "signals": len(usable),
                "pass_id": pass_id, "bin": [],
                "errors": errors + ["every candidate was a repeat"]}

    # The bin is filled AFTER the digest, and only once something was
    # banked. Fetching images for a pass that produced no usable spark
    # would be writing files nothing can ever reference.
    bin_rows = stash_images(brand, pass_id, usable, path=path)
    if not bin_rows:
        errors.append("no reference images in this crawl")

    return {"ok": True, "findings": stored, "signals": len(usable),
            "pass_id": pass_id, "bin": bin_rows, "errors": errors}


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Research scout: find tonight's spark.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="one research pass; banks scored sparks")
    p_run.add_argument("--brand", choices=BRANDS, default="zeropage")
    p_run.add_argument("--count", type=int, default=4)
    p_run.add_argument("--lanes", default="web,shorts,feeds,instagram,creators",
                       help="comma-separated subset to run")

    p_list = sub.add_parser("list", help="show banked findings")
    p_list.add_argument("--brand", choices=BRANDS, default=None)
    p_list.add_argument("--unused", action="store_true")

    p_next = sub.add_parser("next", help="print the next servable spark, or nothing")
    p_next.add_argument("--brand", choices=BRANDS, default="zeropage")

    args = parser.parse_args(argv)

    if args.command == "run":
        result = scout(args.brand, args.count,
                       lanes=tuple(x.strip() for x in args.lanes.split(",") if x.strip()))
        for e in result["errors"]:
            print(f"  note: {e}", file=sys.stderr)
        if not result["ok"]:
            print("scout: nothing banked — the night falls back to sparks.txt",
                  file=sys.stderr)
            return 1
        print(f"scout: {len(result['findings'])} spark(s) from {result['signals']} "
              f"signals · {len(result['bin'])} reference image(s) binned")
        for f in result["findings"]:
            print(f"  [{f['score']:.2f}] {f['spark']}\n        {f['rationale']}")
        for b in result["bin"]:
            print(f"  img {b['url']}  <- {b['source_url']}")
    elif args.command == "list":
        rows = list_findings(brand=args.brand, unused_only=args.unused)
        if not rows:
            print("nothing banked yet")
        for r in rows:
            mark = "used" if r.get("used_at") else "open"
            print(f"[{r['score']:.2f}] {r['brand']:9s} {mark:4s} {r['spark']}")
            if r.get("evidence"):
                print(f"           {r['evidence']}")
    elif args.command == "next":
        row = next_spark(args.brand)
        if row:
            print(row["spark"])
        else:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

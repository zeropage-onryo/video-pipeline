#!/usr/bin/env python3
"""
src/imagesearch.py -- reference candidates the agent PICKS, never types.

    find_images(query)  ->  [{id, caption, source, credit}, ...]
                                   |
                            reference(finding_id, candidate_id)
                                   |
                            refbin.fetch(the url WE stored)  ->  the bin

THE BUG THIS MODULE IS THE ANSWER TO (2026-09-02). The research agent
was asked to bank reference images and had no way to look at any, so it
wrote URLs from memory. Stock CDNs serve *a* photo for almost any
plausible URL, so all eleven fetches "succeeded" -- and banked a sunny
tree captioned "bark texture", a branded Harley product shot on the
faceless brand, and six Unsplash source pages that return 404. Every
guard in the chain passed: refbin checked size, host and format;
bank_reference required a source_url and stored it without ever
resolving it.

No prompt fixes that, because the model is not lying -- it is recalling.
The fix is structural: **the candidate carries the URL, and the model
only ever handles an id.** `find_images` writes real results into
`image_candidates` and returns ids and captions with NO url field to
copy; `reference` takes an id and banks the row the server itself wrote.
An invented id resolves to nothing and says so. There is no path left
through which a made-up address reaches the bin.

ONE KIND OF MATERIAL: images pulled off the internet for the spark.

- **stock** -- Unsplash and Pexels, through their real search endpoints.
  The same two sources the agent was hallucinating, except the results
  exist, the ids are real and the attribution is theirs rather than
  invented. This is the only lane Zero Page has: `shootgen.CAST_BRANDS`
  keeps the cast off a faceless brand by design, so for Zero Page
  research images are not one grounding source among several, they are
  the whole budget.

Every network call degrades to an empty list. A lane with no key is
missing, not broken -- `sources()` says which are live so a caller can
tell "nothing matched" from "nothing was configured", which is the
distinction the empty scout bin hid for two days.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from . import db

TIMEOUT = 10
SCHEMA = """
CREATE TABLE IF NOT EXISTS image_candidates (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    query      TEXT,
    source     TEXT NOT NULL,
    image_url  TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title      TEXT,
    credit     TEXT
);
"""


def init(dsn=None) -> None:
    with db.connect(dsn) as conn:
        conn.execute(SCHEMA)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _cid(source: str, image_url: str) -> str:
    """Content-addressed on the URL, so serving the same photo twice in
    one pass yields one row and one id."""
    return f"{source[:3]}-{hashlib.sha1(image_url.encode()).hexdigest()[:12]}"


def _on(var: str, default: str = "1") -> bool:
    return (os.environ.get(var, default) or "").strip().lower() not in ("", "0", "no", "off", "false")


def sources() -> dict:
    """Which lanes can run. "Not configured" is a normal state and has
    to be visible: an empty result with no explanation is what let an
    empty bin look like a working crawl for two days.

    2026-09-05: Mike's call -- references are IMAGES PULLED OFF THE
    INTERNET for the spark. 2026-09-09: the operator-footage lane that
    sat behind FRAMES_LANE was removed outright rather than left dark,
    so every lane here is a web lane. Openverse needs no key and is on
    unless OPENVERSE_LANE=0; Google image search and Reddit light up
    when their keys exist.
    """
    return {
        "openverse": _on("OPENVERSE_LANE", "1"),
        "google": bool(os.environ.get("GOOGLE_CSE_ID")
                       and (os.environ.get("GOOGLE_CSE_KEY") or os.environ.get("GEMINI_API_KEY"))),
        "reddit": bool(os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")),
        "pinterest": bool(os.environ.get("PINTEREST_ACCESS_TOKEN")),
        "unsplash": bool(os.environ.get("UNSPLASH_ACCESS_KEY")),
        "pexels": bool(os.environ.get("PEXELS_API_KEY")),
    }


def any_web(live: Optional[dict] = None) -> bool:
    live = live or sources()
    return any(live.get(k) for k in ("pinterest", "openverse", "google", "reddit", "unsplash", "pexels"))


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _looks_like_image(url: str) -> bool:
    base = (url or "").split("?", 1)[0].lower()
    return base.endswith(IMAGE_SUFFIXES)


def openverse(query: str, limit: int = 6) -> list[dict]:
    """Openverse (openverse.org): a search index over openly licensed
    images from Flickr, Wikimedia, museums and the like. No key, real
    search, every hit carries the page it came from and its creator.
    The floor lane: with nothing else configured the agent still gets
    real photographs off the internet instead of nothing."""
    if not _on("OPENVERSE_LANE", "1"):
        return []
    try:
        data = _get_json("https://api.openverse.org/v1/images/",
                         {"User-Agent": "zeropage-scout/0.1"},
                         {"q": query, "page_size": max(1, min(limit * 2, 20)),
                          "mature": "false"})
    except Exception:
        return []
    out = []
    for r in (data.get("results") or []):
        image, page = r.get("url") or "", r.get("foreign_landing_url") or ""
        if not image or not page or not _looks_like_image(image):
            continue
        who = (r.get("creator") or "").strip()
        src = (r.get("source") or "openverse").strip()
        out.append({"source": "openverse", "image_url": image, "source_url": page,
                    "title": (r.get("title") or "").strip(),
                    "credit": f"{who} on {src}" if who else src,
                    "license": r.get("license") or ""})
        if len(out) >= limit:
            break
    return out


def google_images(query: str, limit: int = 6) -> list[dict]:
    """Google Programmable Search, image mode -- the whole internet by
    query. Needs a Programmable Search Engine id (GOOGLE_CSE_ID, with
    "search the entire web" + image search on) and an API key with the
    Custom Search JSON API enabled (GOOGLE_CSE_KEY, else GEMINI_API_KEY
    if that key's project has the API on). 100 queries/day free.
    Attribution is the page the image sits on; these are other people's
    frames and the bin says so on every tile."""
    cx = os.environ.get("GOOGLE_CSE_ID")
    key = os.environ.get("GOOGLE_CSE_KEY") or os.environ.get("GEMINI_API_KEY")
    if not (cx and key):
        return []
    try:
        data = _get_json("https://www.googleapis.com/customsearch/v1", {},
                         {"key": key, "cx": cx, "q": query, "searchType": "image",
                          "num": max(1, min(limit, 10)), "safe": "active",
                          "imgType": "photo", "imgSize": "large"})
    except Exception:
        return []
    out = []
    for it in (data.get("items") or []):
        image = it.get("link") or ""
        page = (it.get("image") or {}).get("contextLink") or ""
        if not image or not page:
            continue
        out.append({"source": "google", "image_url": image, "source_url": page,
                    "title": (it.get("title") or "").strip(),
                    "credit": (it.get("displayLink") or "").strip()})
    return out


# --- Pinterest: the boards HE curates ----------------------------------
# Pinterest exposes no public pin search, so the honest lane is his own
# boards: he pins what he likes while scrolling, and this reads those
# boards through the v5 API and matches pin text against the spark. His
# taste becomes the bank without a scraper. Token: a Pinterest developer
# app with boards:read + pins:read; board per brand by name or id.
PINTEREST_API = "https://api.pinterest.com/v5"
_pin_cache: dict = {}


def _pinterest_headers() -> dict:
    tok = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _pinterest_board_id(brand: str) -> str:
    want = (os.environ.get(f"PINTEREST_BOARD_{(brand or '').upper()}") or "").strip()
    if not want:
        return ""
    if want.isdigit():
        return want
    bookmark, seen = None, 0
    while seen < 10:
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark
        data = _get_json(f"{PINTEREST_API}/boards", _pinterest_headers(), params)
        for b in (data.get("items") or []):
            if (b.get("name") or "").strip().lower() == want.lower():
                return str(b.get("id") or "")
        bookmark = data.get("bookmark")
        seen += 1
        if not bookmark:
            break
    return ""


def _pinterest_pins(brand: str) -> list[dict]:
    """Every pin on the brand's board, cached for the process (one run
    is minutes; the board changes when he pins)."""
    import time
    hit = _pin_cache.get(brand)
    if hit and hit["exp"] > time.time():
        return hit["pins"]
    board = _pinterest_board_id(brand)
    if not board:
        return []
    pins, bookmark, pages = [], None, 0
    while pages < 10:
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark
        data = _get_json(f"{PINTEREST_API}/boards/{board}/pins", _pinterest_headers(), params)
        pins += (data.get("items") or [])
        bookmark = data.get("bookmark")
        pages += 1
        if not bookmark:
            break
    _pin_cache[brand] = {"pins": pins, "exp": time.time() + 900}
    return pins


def _pin_image(pin: dict) -> str:
    media = pin.get("media") or {}
    images = media.get("images") or {}
    for key in ("1200x", "originals", "600x", "400x300"):
        if images.get(key, {}).get("url"):
            return images[key]["url"]
    for v in images.values():
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
    return ""


def pinterest(query: str, brand: Optional[str] = None, limit: int = 6) -> list[dict]:
    """Pins from the brand's own board, ranked by token overlap between
    the query and the pin's title / description / alt text. Never raises."""
    if not os.environ.get("PINTEREST_ACCESS_TOKEN"):
        return []
    import re
    words = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    if not words:
        return []
    try:
        pins = _pinterest_pins(brand or "")
    except Exception:
        return []
    scored = []
    for pin in pins:
        text = " ".join(str(pin.get(k) or "") for k in ("title", "description", "alt_text"))
        hits = len(words & set(re.findall(r"[a-z0-9]+", text.lower())))
        image = _pin_image(pin)
        if hits and image:
            scored.append((hits, pin, image))
    scored.sort(key=lambda t: -t[0])
    board = os.environ.get(f"PINTEREST_BOARD_{(brand or '').upper()}") or "board"
    out = []
    for _h, pin, image in scored[:limit]:
        pid = str(pin.get("id") or "")
        out.append({"source": "pinterest", "image_url": image,
                    "source_url": (pin.get("link") or f"https://www.pinterest.com/pin/{pid}/"),
                    "title": (pin.get("title") or pin.get("alt_text") or "").strip(),
                    "credit": f"pinned by you ({board})"})
    return out


# Where the worlds Mike wants already live, as images people posted.
# Per brand so a Zero Page query never grounds on a rider sub and vice
# versa; the search is restricted to each sub in turn.
REDDIT_SUBS = {
    "antihero": ["Cyberpunk", "motorcycles", "ImaginaryCityscapes", "outrun",
                 "NightPhotography", "moviestills"],
    "zeropage": ["LiminalSpace", "Cyberpunk", "ImaginaryMonsters", "AnalogHorror",
                 "ImaginaryCityscapes", "creepy", "moviestills"],
}
_reddit_token: dict = {}


def _reddit_bearer() -> str:
    """client_credentials on a Reddit "script" app; cached for its hour.
    Reddit answers 403 to unauthenticated datacenter clients (see
    prompts/scout_sources.txt); OAuth is what makes this lane real."""
    import time
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and sec):
        return ""
    if _reddit_token.get("exp", 0) > time.time() + 60:
        return _reddit_token["tok"]
    import requests
    resp = requests.post("https://www.reddit.com/api/v1/access_token",
                         auth=(cid, sec), data={"grant_type": "client_credentials"},
                         headers={"User-Agent": "zeropage-scout/0.1"}, timeout=TIMEOUT)
    resp.raise_for_status()
    tok = resp.json()
    _reddit_token.update(tok=tok["access_token"], exp=time.time() + int(tok.get("expires_in", 3600)))
    return _reddit_token["tok"]


def reddit(query: str, brand: Optional[str] = None, limit: int = 6) -> list[dict]:
    """Top image posts matching the query in the brand's subs. The image
    is the post's own preview source (people's own frames, not thumbnails
    of articles), the page is the post, the credit is the poster."""
    import html as _html
    try:
        tok = _reddit_bearer()
    except Exception:
        return []
    if not tok:
        return []
    subs = REDDIT_SUBS.get(brand or "", REDDIT_SUBS["zeropage"])
    out, seen = [], set()
    for sub in subs:
        if len(out) >= limit:
            break
        try:
            data = _get_json(f"https://oauth.reddit.com/r/{sub}/search",
                             {"Authorization": f"bearer {tok}",
                              "User-Agent": "zeropage-scout/0.1"},
                             {"q": query, "restrict_sr": 1, "sort": "top", "t": "year",
                              "limit": 10, "type": "link"})
        except Exception:
            continue
        for child in ((data.get("data") or {}).get("children") or []):
            d = child.get("data") or {}
            if d.get("over_18") or d.get("is_video"):
                continue
            image = ""
            try:
                image = d["preview"]["images"][0]["source"]["url"]
            except (KeyError, IndexError, TypeError):
                if _looks_like_image(d.get("url") or ""):
                    image = d["url"]
            image = _html.unescape(image or "")
            if not image or image in seen:
                continue
            seen.add(image)
            out.append({"source": "reddit", "image_url": image,
                        "source_url": "https://www.reddit.com" + (d.get("permalink") or ""),
                        "title": (d.get("title") or "").strip(),
                        "credit": f"u/{d.get('author', '?')} on r/{sub}"})
            if len(out) >= limit:
                break
    return out


def _get_json(url: str, headers: dict, params: dict):
    import requests
    resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def unsplash(query: str, limit: int = 6) -> list[dict]:
    """Real search, real ids, real attribution.

    `source_url` is the photo's html page and `credit` the photographer,
    because Unsplash's API terms require attribution and because an
    unattributed reference in front of a spend is the wrong affordance
    whatever the licence says.
    """
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        return []
    try:
        data = _get_json("https://api.unsplash.com/search/photos",
                         {"Authorization": f"Client-ID {key}",
                          "Accept-Version": "v1"},
                         {"query": query, "per_page": max(1, min(limit, 30)),
                          "content_filter": "high"})
    except Exception:
        return []
    out = []
    for p in (data.get("results") or []):
        urls, links = p.get("urls") or {}, p.get("links") or {}
        image = urls.get("regular") or urls.get("full") or urls.get("small")
        page = links.get("html")
        if not image or not page:
            continue
        who = ((p.get("user") or {}).get("name") or "").strip()
        out.append({"source": "unsplash", "image_url": image, "source_url": page,
                    "title": (p.get("alt_description") or p.get("description")
                              or "").strip(),
                    "credit": f"{who} on Unsplash" if who else "Unsplash"})
    return out


def pexels(query: str, limit: int = 6) -> list[dict]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    try:
        data = _get_json("https://api.pexels.com/v1/search",
                         {"Authorization": key},
                         {"query": query, "per_page": max(1, min(limit, 80))})
    except Exception:
        return []
    out = []
    for p in (data.get("photos") or []):
        src = p.get("src") or {}
        image = src.get("large") or src.get("original") or src.get("medium")
        page = p.get("url")
        if not image or not page:
            continue
        who = (p.get("photographer") or "").strip()
        out.append({"source": "pexels", "image_url": image, "source_url": page,
                    "title": (p.get("alt") or "").strip(),
                    "credit": f"{who} on Pexels" if who else "Pexels"})
    return out


def remember(candidates: list[dict], query: str = "", dsn=None) -> list[dict]:
    """Store what we served, so an id can be redeemed later.

    This is the hinge of the whole design. The model is handed ids; the
    URLs stay here. Persisted rather than held in memory because each
    MCP tool call is its own request -- an id that only lived in the
    process that served it would be unredeemable by the next call.
    """
    init(dsn)
    out = []
    with db.connect(dsn) as conn:
        for c in candidates:
            cid = _cid(c["source"], c["image_url"])
            conn.execute(
                "INSERT INTO image_candidates (id, created_at, query, source, "
                "image_url, source_url, title, credit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(id) DO UPDATE SET query=excluded.query",
                (cid, _now(), query, c["source"], c["image_url"],
                 c["source_url"], c.get("title") or "", c.get("credit") or ""))
            out.append({**c, "id": cid})
    return out


def get(candidate_id: str, dsn=None) -> Optional[dict]:
    """Redeem an id. None for anything we did not serve -- which is what
    an invented id looks like, and the caller must be able to say so."""
    try:
        init(dsn)
        with db.connect(dsn) as conn:
            row = conn.execute("SELECT * FROM image_candidates WHERE id = %s",
                               (str(candidate_id or "").strip(),)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


# How the lanes split per brand. Both brands run the same two, and the
# dict is kept rather than inlined because per-brand weighting is the
# thing most likely to come back.
# 2026-09-05, Mike: "I don't want it connected to footage, just images
# pulled off the internet through ideas/sparks." 2026-09-09, Mike: the
# operator-footage lane is gone from the studio entirely -- not opt-in,
# not dark, removed. Do not reintroduce a lane that reads local video.
BRAND_LANES = {"antihero": ("web", "stock"), "zeropage": ("web", "stock")}


def lanes_for(brand: Optional[str]) -> tuple:
    return BRAND_LANES.get(brand or "", ("web", "stock"))


def _interleave(*lists: list) -> list:
    out, i = [], 0
    while any(i < len(each) for each in lists):
        for each in lists:
            if i < len(each):
                out.append(each[i])
        i += 1
    return out


def search(query: str, brand: Optional[str] = None, limit: int = 6,
           dsn=None) -> list[dict]:
    """Candidates for one query, stored and returned with ids.

    Never raises. Returns [] when no lane is configured or nothing
    matched; `sources()` is how a caller tells those two apart.
    """
    query = " ".join((query or "").split())
    if not query:
        return []
    lanes = lanes_for(brand)
    found: list[dict] = []
    if "web" in lanes:
        # Reddit first (people's own frames of exactly these worlds),
        # then the whole web, then the open index; interleaved so no one
        # lane fills a short list.
        # His own board first (curated by hand), then Reddit (people's
        # own frames of these worlds), the whole web, the open index.
        found = pinterest(query, brand, limit) + found
        found += _interleave(reddit(query, brand, limit),
                             google_images(query, limit),
                             openverse(query, limit))
    if "stock" in lanes:
        # Interleaved rather than concatenated: whichever lane answers
        # first would otherwise fill a short list on its own.
        a, b = unsplash(query, limit), pexels(query, limit)
        found += [x for pair in zip(a, b) for x in pair]
        found += a[len(b):] + b[len(a):]
    seen, unique = set(), []
    for c in found:
        if c["image_url"] in seen:
            continue
        seen.add(c["image_url"])
        unique.append(c)
    return remember(unique[:max(1, limit)], query=query, dsn=dsn)

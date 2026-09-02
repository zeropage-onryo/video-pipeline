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

TWO LANES, WEIGHTED BY BRAND, because the material is not interchangeable:

- **frames** -- src/framebank.py, his own 70 minutes of ProRes. Owned,
  licence-free, his camera and his rooms. All of it is garage and
  motorcycle work, so it carries ANTIHERO and does nothing for Zero Page.
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


def init(path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _cid(source: str, image_url: str) -> str:
    """Content-addressed on the URL, so serving the same photo twice in
    one pass yields one row and one id."""
    return f"{source[:3]}-{hashlib.sha1(image_url.encode()).hexdigest()[:12]}"


def sources() -> dict:
    """Which lanes can run. "Not configured" is a normal state and has
    to be visible: an empty result with no explanation is what let an
    empty bin look like a working crawl for two days."""
    return {
        "frames": True,                       # local, always available
        "unsplash": bool(os.environ.get("UNSPLASH_ACCESS_KEY")),
        "pexels": bool(os.environ.get("PEXELS_API_KEY")),
    }


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


def _frames(query: str, brand: Optional[str], limit: int, path) -> list[dict]:
    from . import framebank
    out = []
    for f in framebank.search(query, brand=brand, limit=limit, path=path):
        # A local frame's "url" is its path on disk; refbin never fetches
        # it over the network -- see mcp_server.bank_reference, which
        # reads the file directly for this source.
        out.append({"source": "frames", "image_url": f["path"],
                    "source_url": f"footage/{f['clip']}@{f['t_sec']:g}s",
                    "title": f.get("caption") or f"{f['clip']} at {f['t_sec']:g}s",
                    "credit": "own footage"})
    return out


def remember(candidates: list[dict], query: str = "", path=db.DB_PATH) -> list[dict]:
    """Store what we served, so an id can be redeemed later.

    This is the hinge of the whole design. The model is handed ids; the
    URLs stay here. Persisted rather than held in memory because each
    MCP tool call is its own request -- an id that only lived in the
    process that served it would be unredeemable by the next call.
    """
    init(path)
    out = []
    with db.connect(path) as conn:
        for c in candidates:
            cid = _cid(c["source"], c["image_url"])
            conn.execute(
                "INSERT INTO image_candidates (id, created_at, query, source, "
                "image_url, source_url, title, credit) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET query=excluded.query",
                (cid, _now(), query, c["source"], c["image_url"],
                 c["source_url"], c.get("title") or "", c.get("credit") or ""))
            out.append({**c, "id": cid})
    return out


def get(candidate_id: str, path=db.DB_PATH) -> Optional[dict]:
    """Redeem an id. None for anything we did not serve -- which is what
    an invented id looks like, and the caller must be able to say so."""
    try:
        init(path)
        with db.connect(path) as conn:
            row = conn.execute("SELECT * FROM image_candidates WHERE id = ?",
                               (str(candidate_id or "").strip(),)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


# How the two lanes split per brand. Antihero has owned footage that IS
# its world; Zero Page has none and lives on the outside lanes.
BRAND_LANES = {"antihero": ("frames", "stock"), "zeropage": ("stock",)}


def search(query: str, brand: Optional[str] = None, limit: int = 6,
           path=db.DB_PATH) -> list[dict]:
    """Candidates for one query, stored and returned with ids.

    Never raises. Returns [] when no lane is configured or nothing
    matched; `sources()` is how a caller tells those two apart.
    """
    query = " ".join((query or "").split())
    if not query:
        return []
    lanes = BRAND_LANES.get(brand or "", ("frames", "stock"))
    found: list[dict] = []
    if "frames" in lanes:
        found += _frames(query, brand, limit, path)
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
    return remember(unique[:max(1, limit)], query=query, path=path)

"""
Parses a YouTube video id out of a stored URL. Three shapes -- a
standard watch URL, the youtu.be short link, and a /shorts/ URL --
each with its own way to trip up a naive regex once real query params
show up. Uses urllib.parse rather than a single regex over the whole
string, so query params are handled properly regardless of order or
what else rides along with them.

No fetcher here yet -- this is the parser only.
"""
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTU_BE_HOSTS = {"youtu.be"}


def parse_video_id(url):
    """The video id from a youtube.com/watch, youtu.be, or /shorts/ URL,
    or None if it isn't one of those shapes."""
    if not url:
        return None

    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host in YOUTU_BE_HOSTS:
        video_id = parsed.path.lstrip("/")
        return video_id or None

    if host in YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v")
            return values[0] if values else None
        if parsed.path.startswith("/shorts/"):
            video_id = parsed.path[len("/shorts/"):]
            return video_id or None

    return None

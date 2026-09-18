"""
Where a piece of media LIVES in the bucket, and the URL it is fetched by.

`src/storage.py` is the boto3 layer -- it puts bytes at a key and knows
nothing about what they are. `asset_shelf.parse_ref` is the one parser
for a REFERENCE url. This module is the third thing neither of those is:
the map from "a photo/clip this pipeline knows about" to "the key it
lives under" and "the URL a browser, or Runway, should fetch it by".

It exists because that map stopped being a single f-string the moment
media became multi-tenant. Three things changed at once and all three
have to move together, which is exactly the situation that produced the
2026-09-08 outage when only one of them did:

  1. KEYS CARRY THE TENANT.  The old scheme was flat and global --
     `characters/<slug>/<file>`, `refs/<sha>.jpg`, `clips/<file>`. Two
     accounts with a character named `michael` wrote the same key, and
     the second upload silently replaced the first one's face. Flat keys
     also make per-account accounting, quota and deletion impossible:
     nothing in the key says whose bytes those are. New keys are
     `m/<account_id>/<tail>` for the master and `t/<account_id>/<tail>`
     for the 480px derivative, with the same `<tail>` in both.

     The two top-level prefixes are deliberate and are not cosmetic:
     a lifecycle rule in R2 matches on a prefix, so masters can age into
     Infrequent Access while thumbnails -- the things actually read on
     every card -- stay in Standard. Nest the thumbs under `m/` and that
     rule cannot be written without also demoting them.

  2. THE STORED STRING IS A NAME, NOT A URL.  Every reference bug this
     repo has paid for came from storing a URL: a local route that was
     true only on the machine holding the folder (2026-09-08), and now a
     signed URL that would be true only for the next hour. So what goes
     ON a row is the site-relative logical ref it always was --
     `/characters/<slug>/photo/<file>`, `/refs/<sha>.jpg` -- and the
     fetchable URL is minted HERE, on read, by whichever machine is
     doing the reading. That is the same fix 09-08 made (a string true
     on every machine) arrived at from the other side, and it is the
     only shape that survives an expiring URL.

  3. ACCESS IS GRANTED, NOT ASSUMED.  A public bucket with guessable
     keys means every account's unreleased footage is one URL guess from
     anyone. Under `signed` mode the bucket is private and `url_for`
     mints a presigned GET.

`ZEROPAGE_MEDIA` is the one switch, and it is a LADDER -- each rung is a
superset of the one below, and every rung is reversible by setting the
variable back:

  legacy  (default)  old flat keys, public URLs. Byte-for-byte today's
                     behaviour, so this module landing changes nothing
                     until somebody decides otherwise.
  tenant             `m/<account>/...` keys, public URLs. Safe only once
                     ops/migrate_media_keys.py has copied the existing
                     objects across -- it reports before it writes.
  signed             the same keys, presigned URLs, bucket private.

Unconfigured R2 is still the default everywhere: with no `R2_*` vars
every function here falls back to the local route exactly as before, so
a laptop that never turns R2 on keeps working. That contract is older
than this module (ops/r2-setup.md, "5. What changed in code") and is the
one thing not to break.
"""
from __future__ import annotations

import os
from typing import Optional

MASTER_PREFIX = "m"
THUMB_PREFIX = "t"

MODES = ("legacy", "tenant", "signed")

# The top-level key roots this pipeline writes. A tail is only built
# from one of these -- see _render_tail on why it is a whitelist.
OWNED_ROOTS = ("renders", "clips", "images", "references", "refs",
               "characters", "props", "locations", "soul-training")

# The bin is SHARED, and that is a decision rather than an oversight
# (2026-09-15, Mike's call). `/refs/<sha>.jpg` is deliberately the same
# shape whether a composer uploaded it or the scout crawled it -- see
# CLAUDE.md, "they come out the far end identical" -- and `scout_bin` is
# a shared table with no account column at all. So at read time nothing
# can tell an owned bin image from a shared one, and a key scheme that
# needed to would have to guess.
#
# What that costs, stated plainly: a bin image is protected by an
# unguessable content-hash key (and, under `signed`, a signature), not
# by a tenant fence. Faces, renders, soul-training stills and asset
# photos are all fully per-account, which is where the privacy weight
# actually sits. The alternative -- copying the whole bank under every
# account -- grows with accounts x bank size, which is the wrong shape
# for the multi-user future this whole change is for.
SHARED_ROOTS = ("refs",)
SHARED_SCOPE = "shared"

# How long a minted signature is good for, and the window over which the
# SAME string is handed out.
#
# A presigned URL is unique per signing moment, so minting a fresh one
# per page render would give every tile a URL the browser has never seen
# -- a cache miss on all twelve photos of a Queue card, every time the
# card is drawn, which is the opposite of what the thumbnail work below
# is for. So a signature is memoised per (key, window): every mint
# inside the same hour returns an identical string, which the browser
# and the Cloudflare cache in front of a custom domain can both reuse.
# The TTL is twice the window so a URL minted in the window's last
# second is still valid for an hour afterwards.
SIGN_WINDOW_SECONDS = 3600
SIGN_TTL_SECONDS = 2 * SIGN_WINDOW_SECONDS

# The derivative's long edge. 480 is what app/main.py's local
# `thumbnail_for` has always produced, kept identical so a card looks
# the same whether the bytes came off disk or out of the bucket.
THUMB_EDGE = 480


def mode() -> str:
    """Which rung of the ladder we are on. Anything unrecognised reads
    as `legacy`: a typo in an env var must not silently make media
    private, it must leave the system where it was."""
    raw = (os.environ.get("ZEROPAGE_MEDIA") or "legacy").strip().lower()
    return raw if raw in MODES else "legacy"


def tenant_keys() -> bool:
    return mode() in ("tenant", "signed")


def signing() -> bool:
    return mode() == "signed"


def tail_for(url: str) -> Optional[str]:
    """The part of a key that identifies the object, with no tenant and
    no prefix: `refs/<sha>.jpg`, `characters/<slug>/<file>`,
    `clips/<file>`. None for anything this pipeline does not own -- a
    foreign URL off a crawl, a data: URI, a path that climbs.

    References are read by `asset_shelf.parse_ref`, which is THE parser
    for them and stays so. Renders are not references and parse_ref has
    never known them; their shape is owned here, beside `render_key`,
    which is the only thing that writes it.
    """
    from . import asset_shelf

    ref = asset_shelf.parse_ref(url)
    if ref:
        if ref["kind"] == "refs":
            return f"refs/{ref['filename']}"
        return f"{ref['plural']}/{ref['slug']}/{ref['filename']}"
    return _render_tail(url)


def _render_tail(url: str) -> Optional[str]:
    """The tail of anything this pipeline writes that is NOT a reference
    photo: `renders/<provider>/<file>`, `images/<file>`,
    `references/<file>`, `refs/higgsfield/<sha>.<ext>`.

    Generated clips and stills ride on `media_url`, not on `refs`, so
    they never went through parse_ref -- but under `signed` they need
    minting for exactly the same reason a photo does. The roots are a
    WHITELIST rather than "anything with a slash": these strings come
    off stored rows and crawls, and a tail built from a URL this
    pipeline never wrote would be a key pointing at nothing, minted
    confidently.
    """
    from urllib.parse import urlparse

    raw = (url or "").split("?")[0].strip()
    if not raw or raw.startswith("data:"):
        return None
    if "://" in raw:
        raw = urlparse(raw).path
    parts = [p for p in raw.strip("/").split("/") if p]
    if any(p in (".", "..") for p in parts):
        return None
    # already in the new scheme: m/<account>/<tail> or t/<account>/<tail>
    if len(parts) > 2 and parts[0] in (MASTER_PREFIX, THUMB_PREFIX):
        parts = parts[2:]
    if len(parts) >= 2 and parts[0] in OWNED_ROOTS:
        return "/".join(parts)
    return None


def legacy_key(url: str) -> Optional[str]:
    """The flat, global key this object lived under before tenancy. Kept
    because those objects are still there and are never deleted -- the
    migration COPIES, so a row written before the flip and a bucket
    listing from before it both still resolve."""
    return tail_for(url)


def master_key(url: str, account_id: Optional[int]) -> Optional[str]:
    """The key the full-size bytes live under.

    Falls back to the flat legacy key when tenant keys are off OR when
    there is no account to scope by. The second half matters: the
    nightly graph and a handful of CLI paths run with account_id None,
    and a key of `m/None/...` would be a new global namespace with a
    misleading name in it -- worse than the flat one it replaced.
    """
    tail = tail_for(url)
    if not tail:
        return None
    return object_key(tail, account_id)


def thumb_key(url: str, account_id: Optional[int]) -> Optional[str]:
    """The key the 480px derivative lives under -- the same tail under
    `t/`. Thumbnails are per-tenant for the same reason masters are, and
    in their own prefix so a lifecycle rule can leave them alone."""
    tail = tail_for(url)
    if not tail:
        return None
    return thumb_key_for_tail(tail, account_id)


def scope_for(tail: str, account_id: Optional[int]) -> Optional[str]:
    """Which namespace a tail belongs in: `shared`, an account id, or
    None for the flat legacy key. One place, so the writer and the
    reader cannot disagree about where an object lives -- which is the
    entire class of bug this module exists to end."""
    if not tenant_keys():
        return None
    if (tail or "").split("/")[0] in SHARED_ROOTS:
        return SHARED_SCOPE
    return None if account_id is None else str(account_id)


def object_key(tail: str, account_id: Optional[int]) -> str:
    """Where a newly written object goes, given the tail its writer
    already knows. THE one writer-side key builder -- every mirror and
    every render upload goes through it, so the scheme cannot be half
    applied the way the flat one was.

    Unchanged from the flat key while the ladder is on `legacy`, and
    unchanged for a caller with no account (the nightly graph, the
    CLIs): `m/None/...` would be a new global namespace wearing a
    misleading name, which is worse than the honest flat one.
    """
    scope = scope_for(tail, account_id)
    if scope is None:
        return tail
    return f"{MASTER_PREFIX}/{scope}/{tail}"


def thumb_key_for_tail(tail: str, account_id: Optional[int]) -> str:
    """The derivative's key for a tail a writer already has. Same tail,
    `t/` instead of `m/` -- see the module docstring for why the split
    is top-level and not a folder inside the master prefix."""
    scope = scope_for(tail, account_id) or SHARED_SCOPE
    return f"{THUMB_PREFIX}/{scope}/{tail}"


def mirror(source, tail: str, account_id: Optional[int] = None,
           content_type: str = "image/jpeg", *, derive: bool = True) -> Optional[str]:
    """Push one newly written file up, with its derivative. Best-effort.

    THE mirror. `refbin.mirror_to_r2` and `app/api._mirror_photos_to_r2`
    were two implementations of this with two key schemes between them,
    which is how a photo could be handed out under a URL whose object
    was never uploaded. One owner now, so a new writer gets the tenant
    prefix and the thumbnail without having to remember either.

    Never raises and never blocks a save: an unconfigured or unreachable
    R2 leaves the local file exactly as it was, which is what every
    local-only setup has always had. A failed DERIVATIVE never fails the
    master either -- a card falling back to `?thumb=1` is a slow tile,
    while a lost master is a lost reference.
    """
    import sys
    from pathlib import Path

    from . import storage

    try:
        if not storage.configured():
            return None
    except Exception:                                   # noqa: BLE001
        return None

    data = None
    try:
        if isinstance(source, (str, Path)):
            path = Path(source)
            url = storage.upload_file(path, key=object_key(tail, account_id),
                                      content_type=content_type)
            if derive:
                data = path.read_bytes()
        else:
            data = bytes(source)
            url = storage.upload_bytes(data, object_key(tail, account_id),
                                       content_type=content_type)
    except Exception as e:                              # noqa: BLE001
        print(f"note: R2 mirror failed for {tail}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return None

    if derive and data is not None and content_type.startswith("image/"):
        try:
            small = thumb_bytes(data)
            if small:
                storage.upload_bytes(small, thumb_key_for_tail(tail, account_id),
                                     content_type="image/jpeg")
        except Exception as e:                          # noqa: BLE001
            print(f"note: thumbnail failed for {tail}: {type(e).__name__}: {e}",
                  file=sys.stderr)
    return url


def url_for(url: str, account_id: Optional[int] = None) -> str:
    """The full-size URL to hand a browser, a renderer, or a fetch.

    THE read-time mint. Takes whatever is stored on the row -- a
    site-relative logical ref, a legacy absolute R2 URL, a foreign URL
    off a crawl -- and returns the string that is true right now, on
    this machine, in this mode.

    Never raises and never returns nothing: anything unrecognised comes
    back exactly as it arrived. A reference is an enhancement and a
    foreign URL is somebody else's business; neither is a reason to fail
    the run that was using it.
    """
    from . import storage

    try:
        if not storage.configured():
            return url                 # local route, exactly as before
        key = master_key(url, account_id)
        if not key:
            return url
        if signing():
            signed = storage.signed_url_for_key(key)
            if signed:
                return signed
        return storage.url_for_key(key) or url
    except Exception:                                   # noqa: BLE001
        return url


def thumb_url_for(url: str, account_id: Optional[int] = None) -> Optional[str]:
    """The 480px URL for the same object, or None when there cannot be
    one (R2 off, or a foreign URL we never made a derivative of).

    None rather than the full-size URL on purpose. The caller decides
    what to do without one -- app/api.py falls back to `?thumb=1`, the
    local handler that has always done this off disk -- and a caller
    that silently got the master back instead would draw a card of
    4.6MB tiles while looking exactly like it was working.

    NOT interchangeable with `url_for`. `refs[0]` is the frame Runway
    anchors a clip on, and anchoring on a thumbnail is a quiet downgrade
    of exactly the kind this reference layer keeps being bitten by --
    which is why the thumbnails travel as their own list and never as a
    cheaper element of the same one.
    """
    from . import storage

    try:
        if not storage.configured():
            return None
        key = thumb_key(url, account_id)
        if not key:
            return None
        if signing():
            return storage.signed_url_for_key(key)
        return storage.url_for_key(key)
    except Exception:                                   # noqa: BLE001
        return None


def thumb_bytes(data: bytes) -> Optional[bytes]:
    """Master image bytes -> 480px JPEG bytes, or None if unreadable.

    Delegates the decode to `refbin.to_jpeg`, which is the one place
    that knows EXIF transpose has to run BEFORE convert("RGB") and that
    HEIC needs pillow-heif registered. Half this asset bank comes off an
    iPhone; a derivative built by a second, simpler decoder would come
    out sideways for exactly those photos and nowhere else, which is the
    2026-08-28 bug rebuilt in a new place.
    """
    import io

    from . import refbin

    upright = refbin.to_jpeg(data)
    if upright is None:
        return None
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(upright))
        image.thumbnail((THUMB_EDGE, THUMB_EDGE))
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=82)
        return buf.getvalue()
    except Exception:                                   # noqa: BLE001
        return None

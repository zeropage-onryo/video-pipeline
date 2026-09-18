"""
Cloudflare R2: upload a rendered clip and get back a public URL.

The missing half of the post path. autopilot.build_plan() has always
read `shot["media_url"]` (see autopilot.py) but nothing ever wrote it --
the one real post so far went out because a clip was pushed through the
R2 dashboard by hand and the URL pasted in somewhere. This module is
that step, scripted: same "thin API wrappers that raise, public
orchestrators that never do" contract as instagram.py/youtube.py.

R2 speaks the S3 API, so boto3 talks to it with a custom endpoint_url
and region_name="auto" -- no Cloudflare-specific SDK needed.

Unconfigured is the default, same as autopilot: no R2_* env vars means
upload_file() raises immediately, and publish_shot_media() (which never
raises) reports that as a normal, loggable failure rather than posting
silently going nowhere.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def account_id() -> Optional[str]:
    return os.environ.get("R2_ACCOUNT_ID")


def access_key_id() -> Optional[str]:
    return os.environ.get("R2_ACCESS_KEY_ID")


def secret_access_key() -> Optional[str]:
    return os.environ.get("R2_SECRET_ACCESS_KEY")


def bucket() -> Optional[str]:
    return os.environ.get("R2_BUCKET")


def public_base_url() -> Optional[str]:
    """The public domain the bucket is served from -- either R2's own
    pub-<hash>.r2.dev dev domain or a custom domain you attached to the
    bucket in the Cloudflare dashboard. Trailing slash stripped so key
    joining below never double-slashes.

    2026-09-08: a pasted value once landed in .env (and the matching Fly
    secret) with a stray control byte and trailing space baked into the
    middle of the hostname -- config still "set" by every check here,
    but every URL built from it was silently unreachable, and it took a
    live curl to notice. Every non-printable byte is stripped before
    anything else touches this value, so a bad paste fails loudly (a
    visibly wrong URL, or R2 rejecting the request) instead of quietly
    producing broken links no one looks at until a user reports it."""
    url = os.environ.get("R2_PUBLIC_BASE_URL")
    if not url:
        return None
    cleaned = "".join(ch for ch in url if ch.isprintable()).strip()
    return cleaned.rstrip("/") if cleaned else None


def configured() -> bool:
    """All five R2_* vars present -- the same all-or-nothing check
    upload_file() does, exposed so callers can skip the attempt (and
    the traceback) entirely when storage isn't set up yet."""
    return bool(
        account_id() and access_key_id() and secret_access_key()
        and bucket() and public_base_url()
    )


# One client per credential set. Building a boto3 client costs ~50ms of
# session and endpoint resolution, which is invisible on the one upload
# a render does and is most of the wall clock on a migration making
# hundreds of copies. botocore's low-level clients are documented
# thread-safe, so the pass can run its copies on a pool.
#
# Keyed on the account and access key (never the secret), so changing
# the environment -- which is what the test suite does between cases --
# yields a different client rather than a stale one.
_CLIENT_CACHE: dict = {}


def _client():
    """Thin wrapper: raises immediately if R2_ACCOUNT_ID (or the boto3
    dependency) is missing, rather than failing confusingly inside a
    boto3 call with a wrong endpoint."""
    acct = account_id()
    if not acct:
        raise RuntimeError("R2_ACCOUNT_ID not set -- storage needs it")
    key_id, secret = access_key_id(), secret_access_key()
    if not (key_id and secret):
        raise RuntimeError("R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY not set")
    try:
        import boto3
    except ImportError as e:
        raise RuntimeError(
            "boto3 not installed -- add it to requirements.txt (R2 speaks "
            "the S3 API; boto3 is the client, no Cloudflare-specific SDK)"
        ) from e
    cached = _CLIENT_CACHE.get((acct, key_id))
    if cached is not None:
        return cached
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="auto",
    )
    _CLIENT_CACHE[(acct, key_id)] = client
    return client


def url_for_key(key: str) -> Optional[str]:
    """The public URL for a key already known to be in the bucket, with
    no upload and no network call -- just string-building off
    `public_base_url()`. Returns None if R2 isn't configured, so a
    caller can fall back to the local route in one line rather than
    wrapping this in its own configured() check every time. Used by
    asset_shelf.photo_url() for reference photos that were pushed up by
    the upload handlers or a backfill script, not by this call."""
    if not configured():
        return None
    return f"{public_base_url()}/{key}"


def key_exists(key: str) -> bool:
    """Is this key actually in the bucket? False when R2 is off or the
    head fails for any reason.

    Used by the one-off that rewrites stored references to their R2
    URLs: a rewrite is only an improvement if the bytes are up there,
    and "the URL is built from a template" is not evidence that they
    are. Never raises -- a caller deciding whether to rewrite a row
    should leave it alone on doubt, not crash mid-pass.
    """
    if not configured():
        return False
    try:
        _client().head_object(Bucket=bucket(), Key=key)
        return True
    except Exception:                                   # noqa: BLE001
        return False


def upload_file(local_path: Path | str, key: Optional[str] = None,
                 content_type: Optional[str] = None) -> str:
    """
    Push one local file to the configured R2 bucket and return its
    public URL. Raises on any failure -- missing config, missing file,
    or a failed put -- this is the thin wrapper half of the contract;
    publish_shot_media() below is the orchestrator that catches it.

    key defaults to "clips/<filename>"; pass one explicitly to control
    where it lands (e.g. to avoid colliding filenames across concepts).
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"no file at {local_path}")

    # Build the client first -- it's the check for account id/access
    # key/secret, and should fail with that specific reason before the
    # separate bucket/base-url check below, rather than whichever of the
    # five happens to get checked first.
    client = _client()

    bkt, base_url = bucket(), public_base_url()
    if not (bkt and base_url):
        raise RuntimeError(
            "R2_BUCKET / R2_PUBLIC_BASE_URL not set -- storage needs both "
            "(the bucket name, and the public domain it's served from)"
        )

    key = key or f"clips/{local_path.name}"
    extra_args = {"ContentType": content_type} if content_type else None
    client.upload_file(str(local_path), bkt, key, ExtraArgs=extra_args)
    return f"{base_url}/{key}"


def publish_shot_media(concept_id: int, shot_n, local_path: Path | str,
                        content_type: Optional[str] = None,
                        db_path=None,
                        account_id: Optional[int] = None,
) -> dict:
    """
    The safe orchestrator: upload a rendered clip and write the
    resulting public URL onto the matching shot's media_url, so
    autopilot.build_plan() picks it up on its next pass without anyone
    hand-pasting a URL again. Never raises -- same "result dict, not an
    exception" contract as instagram.execute_post_action -- because this
    is meant to run right after a generation gets marked kept, and a
    storage hiccup there shouldn't take the caller down with it.

    Call this instead of the manual Cloudflare-dashboard-and-paste
    workflow; that workflow worked once and isn't repeatable by design.
    """
    from . import preprod

    kwargs = {"dsn": db_path} if db_path is not None else {}
    try:
        url = upload_file(local_path, content_type=content_type)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        preprod.set_shot_media_url(concept_id, shot_n, url, **kwargs, account_id=account_id)
    except Exception as e:
        # Uploaded fine, but the DB write failed -- surface the URL
        # anyway so it's not lost, since re-uploading is wasted work.
        return {"ok": False, "error": f"uploaded but failed to record: {e}", "url": url}

    return {"ok": True, "url": url}


# ---------------------------------------------------------------------
# Signed reads, server-side copies, and the bulk helpers the media
# migration needs. Everything below raises on failure like the wrappers
# above -- the never-raising edges live in src/media.py and ops/.
# ---------------------------------------------------------------------

# (key, window) -> signed url. See media.SIGN_WINDOW_SECONDS for why a
# signature is reused rather than minted fresh: a unique URL per page
# render is a guaranteed browser cache miss on every tile of every card.
# Bounded so a long-lived server cannot grow one entry per object ever
# seen; the window rolls hourly and the map is dropped with it.
_SIGNED_CACHE: dict = {}
_SIGNED_CACHE_MAX = 4096


def signed_url_for_key(key: str, ttl: Optional[int] = None) -> Optional[str]:
    """A presigned GET for one key, or None if R2 isn't configured.

    Presigning is local HMAC -- no network call, no round trip to
    Cloudflare -- so this is cheap enough to run per tile. What it is
    NOT is edge-cached: a presigned URL has to address the S3 API
    endpoint (`<account>.r2.cloudflarestorage.com`), because an R2
    custom domain serves the PUBLIC bucket path and does not accept a
    SigV4 query signature. So `signed` mode trades the Cloudflare cache
    in front of the custom domain for real per-tenant access control.
    The memoised window below is what keeps the BROWSER cache, which is
    the one that matters on a phone drawing twelve tiles.

    (If origin bandwidth ever shows up in the bill, the way to get both
    is a Worker on the custom domain validating a token against an R2
    binding -- infrastructure, not Python, and deliberately not built
    until there is a number saying it is needed.)
    """
    import time

    from . import media

    if not configured():
        return None
    ttl = ttl or media.SIGN_TTL_SECONDS
    window = int(time.time()) // media.SIGN_WINDOW_SECONDS
    cached = _SIGNED_CACHE.get((key, window))
    if cached:
        return cached
    try:
        url = _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket(), "Key": key},
            ExpiresIn=ttl,
        )
    except Exception:                                   # noqa: BLE001
        return None
    if len(_SIGNED_CACHE) > _SIGNED_CACHE_MAX:
        _SIGNED_CACHE.clear()
    _SIGNED_CACHE[(key, window)] = url
    return url


def upload_bytes(data: bytes, key: str, content_type: Optional[str] = None) -> str:
    """Put bytes at a key and return the public URL -- `upload_file`
    without the temp file. The derivative path makes its thumbnail in
    memory and has nothing on disk to hand over."""
    client = _client()
    bkt, base_url = bucket(), public_base_url()
    if not (bkt and base_url):
        raise RuntimeError(
            "R2_BUCKET / R2_PUBLIC_BASE_URL not set -- storage needs both")
    extra = {"ContentType": content_type} if content_type else {}
    client.put_object(Bucket=bkt, Key=key, Body=data, **extra)
    return f"{base_url}/{key}"


def copy_key(source_key: str, dest_key: str) -> None:
    """Server-side copy, source left exactly where it was.

    The media migration moves ~every object in the bucket into the
    tenant scheme. Downloading and re-uploading each one would be the
    same bytes over the wire twice for no reason, and on a laptop it
    would be the difference between minutes and an afternoon. COPY is
    also why the migration is re-runnable and why nothing is lost if it
    is interrupted: the old key is still there, still serving, until
    somebody deliberately removes it.
    """
    bkt = bucket()
    if not bkt:
        raise RuntimeError("R2_BUCKET not set -- storage needs it")
    _client().copy_object(Bucket=bkt, Key=dest_key,
                          CopySource={"Bucket": bkt, "Key": source_key})


def list_keys(prefix: str = "") -> list:
    """Every key under a prefix, paginated. Raises like its neighbours;
    the ops scripts above it are the ones that report instead."""
    bkt = bucket()
    if not bkt:
        raise RuntimeError("R2_BUCKET not set -- storage needs it")
    client = _client()
    keys, token = [], None
    while True:
        kwargs = {"Bucket": bkt, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return keys
        token = page.get("NextContinuationToken")


def get_lifecycle() -> Optional[dict]:
    """The bucket's current lifecycle configuration, or None when there
    is none set. Raises only on a broken client -- an empty rule set is
    an answer, not a failure."""
    bkt = bucket()
    if not bkt:
        raise RuntimeError("R2_BUCKET not set -- storage needs it")
    try:
        return _client().get_bucket_lifecycle_configuration(Bucket=bkt)
    except Exception:                                   # noqa: BLE001
        return None


def put_lifecycle(rules: list) -> None:
    """Replace the bucket's lifecycle rules. Thin and raising, like its
    neighbours; ops/media_lifecycle.py is what reports."""
    bkt = bucket()
    if not bkt:
        raise RuntimeError("R2_BUCKET not set -- storage needs it")
    _client().put_bucket_lifecycle_configuration(
        Bucket=bkt, LifecycleConfiguration={"Rules": rules})

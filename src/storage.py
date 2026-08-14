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
    joining below never double-slashes."""
    url = os.environ.get("R2_PUBLIC_BASE_URL")
    return url.rstrip("/") if url else None


def configured() -> bool:
    """All five R2_* vars present -- the same all-or-nothing check
    upload_file() does, exposed so callers can skip the attempt (and
    the traceback) entirely when storage isn't set up yet."""
    return bool(
        account_id() and access_key_id() and secret_access_key()
        and bucket() and public_base_url()
    )


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
    return boto3.client(
        "s3",
        endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="auto",
    )


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
                        db_path=None) -> dict:
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

    kwargs = {"path": db_path} if db_path is not None else {}
    try:
        url = upload_file(local_path, content_type=content_type)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        preprod.set_shot_media_url(concept_id, shot_n, url, **kwargs)
    except Exception as e:
        # Uploaded fine, but the DB write failed -- surface the URL
        # anyway so it's not lost, since re-uploading is wasted work.
        return {"ok": False, "error": f"uploaded but failed to record: {e}", "url": url}

    return {"ok": True, "url": url}

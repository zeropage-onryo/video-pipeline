"""
src/media.py: the key scheme, the read-time mint, and the ladder that
carries the system between them.

Nothing here reaches the network -- conftest's guard would say so
loudly -- so every boto3 call is monkeypatched at storage._client().

The assertions worth keeping are the ones about DEGRADING: an unknown
mode reads as legacy, a foreign URL comes back untouched, a missing
derivative is None rather than a full-size URL wearing a thumbnail's
name. Each of those is a way this layer could fail quietly, which is
the only way it has ever failed.
"""
import io

import pytest
from PIL import Image

from src import asset_shelf, media, storage


@pytest.fixture
def configured_env(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key123")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret123")
    monkeypatch.setenv("R2_BUCKET", "zpf-clips")
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://pub-abc123.r2.dev/")


@pytest.fixture
def unconfigured_env(monkeypatch):
    for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "R2_PUBLIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def clear_signature_cache():
    storage._SIGNED_CACHE.clear()
    yield
    storage._SIGNED_CACHE.clear()


class _FakeS3Client:
    def __init__(self):
        self.uploaded = []
        self.put = []
        self.copied = []
        self.signed = 0

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.uploaded.append((str(filename), bucket, key, ExtraArgs))

    def put_object(self, Bucket=None, Key=None, Body=None, **kw):
        self.put.append((Bucket, Key, len(Body or b""), kw.get("ContentType")))

    def copy_object(self, Bucket=None, Key=None, CopySource=None):
        self.copied.append((CopySource["Key"], Key))

    def generate_presigned_url(self, op, Params=None, ExpiresIn=None):
        self.signed += 1
        return (f"https://acct123.r2.cloudflarestorage.com/{Params['Key']}"
                f"?X-Amz-Signature=sig{self.signed}&X-Amz-Expires={ExpiresIn}")


@pytest.fixture
def fake_s3(monkeypatch):
    client = _FakeS3Client()
    monkeypatch.setattr(storage, "_client", lambda: client)
    return client


def _jpeg(width=1200, height=800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (90, 20, 20)).save(buf, "JPEG")
    return buf.getvalue()


# ---------- the ladder ----------

def test_the_default_rung_is_legacy(monkeypatch):
    monkeypatch.delenv("ZEROPAGE_MEDIA", raising=False)
    assert media.mode() == "legacy"
    assert media.tenant_keys() is False
    assert media.signing() is False


def test_an_unrecognised_mode_reads_as_legacy(monkeypatch):
    """A typo must leave the system where it was. The failure this
    guards is the other direction: a misspelt value that turned out to
    mean `signed` would make every stored URL stop resolving at once."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tennant")
    assert media.mode() == "legacy"


def test_signing_implies_tenant_keys(monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "signed")
    assert media.tenant_keys() is True
    assert media.signing() is True


# ---------- tails: what this pipeline owns ----------

@pytest.mark.parametrize("url,expected", [
    ("/refs/abc123.jpg", "refs/abc123.jpg"),
    ("/characters/michael/photo/IMG_1.jpg", "characters/michael/IMG_1.jpg"),
    ("https://pub-x.r2.dev/characters/michael/IMG_1.jpg",
     "characters/michael/IMG_1.jpg"),
    ("https://pub-x.r2.dev/renders/runway/clip.mp4", "renders/runway/clip.mp4"),
    ("https://pub-x.r2.dev/refs/higgsfield/deadbeef.png",
     "refs/higgsfield/deadbeef.png"),
    ("/locations/bar/photo/wide.jpg", "locations/bar/wide.jpg"),
])
def test_tail_for_reads_every_shape_this_pipeline_writes(url, expected):
    assert media.tail_for(url) == expected


@pytest.mark.parametrize("url", [
    "https://i.pinimg.com/somebody-elses.jpg",
    "data:image/jpeg;base64,AAAA",
    "/../../etc/passwd",
    "",
    "/unknown-root/file.jpg",
])
def test_a_url_this_pipeline_does_not_own_has_no_tail(url):
    """None, not a guess. A tail built from a foreign URL would be a key
    pointing at nothing, minted confidently -- the exact shape of the
    empty-tile bug, with a signature on it."""
    assert media.tail_for(url) is None


def test_re_keying_a_new_scheme_url_does_not_nest(monkeypatch):
    """`m/7/refs/a.jpg` -> `refs/a.jpg` -> `m/7/refs/a.jpg`. The
    migration is re-runnable, and canonicalising twice has to be a
    no-op, not `m/7/m/7/...`."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    once = media.object_key(media.tail_for("/characters/mike/photo/a.jpg"), 7)
    twice = media.object_key(media.tail_for(f"https://cdn.x/{once}"), 7)
    assert once == twice == "m/7/characters/mike/a.jpg"


# ---------- keys ----------

def test_legacy_keys_are_the_flat_ones(monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "legacy")
    assert media.object_key("refs/a.jpg", 7) == "refs/a.jpg"
    assert media.object_key("characters/mike/a.jpg", 7) == "characters/mike/a.jpg"


def test_tenant_keys_carry_the_account(monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    assert media.object_key("characters/mike/a.jpg", 12) == "m/12/characters/mike/a.jpg"
    assert media.object_key("renders/nano/x.png", 7) == "m/7/renders/nano/x.png"
    assert media.object_key("soul-training/20260914/IMG_1.JPG", 7) == (
        "m/7/soul-training/20260914/IMG_1.JPG")


def test_the_bin_is_shared_and_does_not_carry_an_account(monkeypatch):
    """2026-09-15, Mike's call. `/refs/<sha>.jpg` is deliberately the
    same shape whether a composer uploaded it or the scout crawled it,
    and `scout_bin` has no account column at all -- so at read time
    nothing can tell an owned bin image from a shared one. Routing it by
    account would mean guessing, and a guess here is a tile that 404s
    for one studio and resolves for another."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    assert media.object_key("refs/a.jpg", 7) == "m/shared/refs/a.jpg"
    assert media.object_key("refs/a.jpg", 2) == "m/shared/refs/a.jpg"
    assert media.object_key("refs/higgsfield/deadbeef.png", 7) == (
        "m/shared/refs/higgsfield/deadbeef.png")


def test_the_bin_being_shared_does_not_leak_into_the_fenced_kinds(monkeypatch):
    """The fence is where the privacy weight sits: faces, renders,
    soul-training stills and asset photos stay per-account."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    for tail in ("characters/michael/IMG_1.jpg", "renders/runway/clip.mp4",
                 "soul-training/20260914/IMG_1.JPG", "props/jacket/a.jpg"):
        assert media.object_key(tail, 1) != media.object_key(tail, 2)


def test_two_accounts_no_longer_collide(monkeypatch):
    """The bug the prefix exists for: both accounts have a character
    called `michael`, both upload `IMG_1.jpg`, and under the flat scheme
    the second upload replaced the first one's face."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    tail = "characters/michael/IMG_1.jpg"
    assert media.object_key(tail, 1) != media.object_key(tail, 2)


def test_no_account_keeps_the_flat_key_rather_than_inventing_one(monkeypatch):
    """The nightly graph and the CLIs run with no account. `m/None/...`
    would be a new global namespace with a misleading name in it."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    assert media.object_key("renders/nano/x.png", None) == "renders/nano/x.png"


def test_thumbs_live_under_their_own_top_level_prefix(monkeypatch):
    """Not a folder inside the master prefix: a lifecycle rule matches
    on a prefix, and masters have to age into Infrequent Access without
    demoting the thumbnails, which are what every card reads."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    tail = "characters/mike/a.jpg"
    assert media.object_key(tail, 7).startswith("m/")
    assert media.thumb_key_for_tail(tail, 7) == "t/7/characters/mike/a.jpg"


# ---------- the read-time mint ----------

def test_with_no_r2_a_url_comes_back_untouched(unconfigured_env):
    """The oldest contract in this layer (ops/r2-setup.md): a laptop
    that never turns R2 on keeps working on local routes."""
    assert media.url_for("/refs/a.jpg", 7) == "/refs/a.jpg"
    assert media.thumb_url_for("/refs/a.jpg", 7) is None


def test_a_foreign_url_is_returned_as_it_arrived(configured_env, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    foreign = "https://i.pinimg.com/somebody-elses.jpg"
    assert media.url_for(foreign, 7) == foreign


def test_tenant_mode_mints_the_public_url_for_the_tenant_key(
        configured_env, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    assert media.url_for("/characters/mike/photo/a.jpg", 7) == (
        "https://pub-abc123.r2.dev/m/7/characters/mike/a.jpg")


def test_signed_mode_mints_a_signature(configured_env, fake_s3, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "signed")
    url = media.url_for("/characters/mike/photo/a.jpg", 7)
    assert "X-Amz-Signature" in url
    assert "m/7/characters/mike/a.jpg" in url


def test_a_signature_is_reused_inside_its_window(configured_env, fake_s3,
                                                 monkeypatch):
    """Minting a fresh signature per render would give every tile a URL
    the browser has never seen -- a guaranteed cache miss on all twelve
    photos of a card, every time it is drawn."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "signed")
    first = media.url_for("/refs/a.jpg", 7)
    second = media.url_for("/refs/a.jpg", 7)
    assert first == second
    assert fake_s3.signed == 1


def test_two_accounts_get_different_signed_urls(configured_env, fake_s3,
                                                monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "signed")
    assert (media.url_for("/characters/mike/photo/a.jpg", 1)
            != media.url_for("/characters/mike/photo/a.jpg", 2))


def test_a_signing_failure_falls_back_rather_than_raising(
        configured_env, monkeypatch):
    """A reference is an enhancement. A bucket that refuses to sign
    gives a card a tile that may 404; it must not take the page down."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "signed")

    class _Broken:
        def generate_presigned_url(self, *a, **kw):
            raise RuntimeError("no credentials")

    monkeypatch.setattr(storage, "_client", lambda: _Broken())
    assert media.url_for("/characters/mike/photo/a.jpg", 7).endswith(
        "/m/7/characters/mike/a.jpg")


# ---------- what gets STORED ----------

def test_legacy_stores_the_public_url_as_it_always_did(configured_env,
                                                      monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "legacy")
    stored = asset_shelf.storable_ref("/characters/michael/photo/IMG_1.jpg")
    assert stored == "https://pub-abc123.r2.dev/characters/michael/IMG_1.jpg"


def test_tenant_stores_the_logical_name_instead(configured_env, monkeypatch):
    """A URL that carries an account and an expiry cannot be the thing
    written onto a row and read back months later."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    stored = asset_shelf.storable_ref(
        "https://pub-abc123.r2.dev/characters/michael/IMG_1.jpg")
    assert stored == "/characters/michael/photo/IMG_1.jpg"


def test_a_row_written_on_either_rung_still_mints(configured_env, monkeypatch):
    """The reason the ladder is safe to climb, and to climb back down."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    for stored in ("/characters/michael/photo/IMG_1.jpg",
                   "https://pub-abc123.r2.dev/characters/michael/IMG_1.jpg"):
        assert media.url_for(stored, 7) == (
            "https://pub-abc123.r2.dev/m/7/characters/michael/IMG_1.jpg")


# ---------- derivatives ----------

def test_thumb_bytes_fits_the_long_edge():
    small = media.thumb_bytes(_jpeg(1200, 800))
    assert small is not None
    assert max(Image.open(io.BytesIO(small)).size) <= media.THUMB_EDGE


def test_thumb_bytes_is_much_smaller_than_the_master():
    master = _jpeg(2400, 1600)
    assert len(media.thumb_bytes(master)) < len(master) / 2


def test_thumb_bytes_returns_none_for_something_that_is_not_an_image():
    assert media.thumb_bytes(b"not an image") is None


def test_mirror_uploads_the_master_and_the_derivative(configured_env, fake_s3,
                                                      tmp_path, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    photo = tmp_path / "IMG_1.jpg"
    photo.write_bytes(_jpeg())
    media.mirror(photo, "characters/mike/IMG_1.jpg", 7)
    assert fake_s3.uploaded[0][2] == "m/7/characters/mike/IMG_1.jpg"
    assert fake_s3.put[0][1] == "t/7/characters/mike/IMG_1.jpg"


def test_a_failed_derivative_never_costs_the_master(configured_env, fake_s3,
                                                    tmp_path, monkeypatch):
    """A card falling back to `?thumb=1` is a slow tile. A lost master is
    a lost reference."""
    monkeypatch.setenv("ZEROPAGE_MEDIA", "tenant")
    monkeypatch.setattr(media, "thumb_bytes", lambda data: None)
    photo = tmp_path / "IMG_1.jpg"
    photo.write_bytes(_jpeg())
    url = media.mirror(photo, "characters/mike/IMG_1.jpg", 7)
    assert url.endswith("/m/7/characters/mike/IMG_1.jpg")
    assert fake_s3.put == []


def test_mirror_never_raises_when_r2_is_unreachable(configured_env, tmp_path,
                                                    monkeypatch):
    def _boom():
        raise RuntimeError("bucket on fire")

    monkeypatch.setattr(storage, "_client", _boom)
    photo = tmp_path / "IMG_1.jpg"
    photo.write_bytes(_jpeg())
    assert media.mirror(photo, "characters/mike/IMG_1.jpg", 7) is None


def test_mirror_does_nothing_at_all_with_no_r2(unconfigured_env, tmp_path):
    photo = tmp_path / "IMG_1.jpg"
    photo.write_bytes(_jpeg())
    assert media.mirror(photo, "characters/mike/IMG_1.jpg", 7) is None

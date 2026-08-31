"""
storage.py: upload_file's config/failure contract, and
publish_shot_media's "never raises, writes media_url on success"
orchestration. No test here ever reaches the network -- conftest's
no_network fixture would fail loudly if one tried -- so every boto3
call is monkeypatched out at storage._client().
"""
import pytest

from src import preprod, storage
from src.db import init_db


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    preprod.init(path)
    return path


@pytest.fixture
def configured_env(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key123")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret123")
    monkeypatch.setenv("R2_BUCKET", "zpf-clips")
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://pub-abc123.r2.dev/")


class _FakeS3Client:
    """Records what upload_file() would have sent, touches no network."""

    def __init__(self):
        self.calls = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.calls.append((filename, bucket, key, ExtraArgs))


# ---------- configuration ----------

def test_configured_is_false_with_no_env(monkeypatch):
    for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "R2_PUBLIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    assert storage.configured() is False


def test_configured_is_true_with_all_five_vars(configured_env):
    assert storage.configured() is True


def test_public_base_url_strips_trailing_slash(configured_env):
    assert storage.public_base_url() == "https://pub-abc123.r2.dev"


# ---------- upload_file: the raising thin wrapper ----------

def test_upload_file_raises_for_missing_local_file(configured_env, tmp_path):
    with pytest.raises(FileNotFoundError):
        storage.upload_file(tmp_path / "nope.mp4")


def test_upload_file_raises_without_account_id(monkeypatch, tmp_path):
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake video bytes")
    with pytest.raises(RuntimeError, match="R2_ACCOUNT_ID"):
        storage.upload_file(clip)


def test_upload_file_raises_without_bucket_or_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key123")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret123")
    monkeypatch.delenv("R2_BUCKET", raising=False)
    monkeypatch.delenv("R2_PUBLIC_BASE_URL", raising=False)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake video bytes")
    with pytest.raises(RuntimeError, match="R2_BUCKET"):
        storage.upload_file(clip)


def test_upload_file_returns_the_public_url(configured_env, tmp_path, monkeypatch):
    fake = _FakeS3Client()
    monkeypatch.setattr(storage, "_client", lambda: fake)
    clip = tmp_path / "gold-drip.mp4"
    clip.write_bytes(b"fake video bytes")

    url = storage.upload_file(clip)

    assert url == "https://pub-abc123.r2.dev/clips/gold-drip.mp4"
    assert fake.calls == [(str(clip), "zpf-clips", "clips/gold-drip.mp4", None)]


def test_upload_file_accepts_an_explicit_key(configured_env, tmp_path, monkeypatch):
    fake = _FakeS3Client()
    monkeypatch.setattr(storage, "_client", lambda: fake)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")

    url = storage.upload_file(clip, key="concept-9/take-3.mp4", content_type="video/mp4")

    assert url == "https://pub-abc123.r2.dev/concept-9/take-3.mp4"
    assert fake.calls[0][2] == "concept-9/take-3.mp4"
    assert fake.calls[0][3] == {"ContentType": "video/mp4"}


# ---------- publish_shot_media: the non-raising orchestrator ----------

def test_publish_shot_media_writes_media_url_onto_matching_shot(
    configured_env, tmp_db, tmp_path, monkeypatch
):
    fake = _FakeS3Client()
    monkeypatch.setattr(storage, "_client", lambda: fake)
    shots = [
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "seedance", "prompt": "p"},
    ]
    concept_id = preprod.save_concept(
        {"title": "Gold Drip", "shots": shots}, brand="antihero", path=tmp_db
    )
    clip = tmp_path / "gold-drip.mp4"
    clip.write_bytes(b"x")

    result = storage.publish_shot_media(concept_id, 1, clip, db_path=tmp_db)

    assert result == {"ok": True, "url": "https://pub-abc123.r2.dev/clips/gold-drip.mp4"}
    concept = preprod.get_concept(concept_id, path=tmp_db, account_id=None)
    assert concept["shots"][0]["media_url"] == "https://pub-abc123.r2.dev/clips/gold-drip.mp4"


def test_publish_shot_media_never_raises_on_upload_failure(tmp_db, tmp_path, monkeypatch):
    for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "R2_PUBLIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    concept_id = preprod.save_concept(
        {"title": "T", "shots": [{"n": 1, "source": "AI"}]}, brand="antihero", path=tmp_db
    )
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")

    result = storage.publish_shot_media(concept_id, 1, clip, db_path=tmp_db)

    assert result["ok"] is False
    assert "R2_ACCOUNT_ID" in result["error"]


def test_publish_shot_media_never_raises_on_unknown_shot(configured_env, tmp_db, tmp_path, monkeypatch):
    fake = _FakeS3Client()
    monkeypatch.setattr(storage, "_client", lambda: fake)
    concept_id = preprod.save_concept(
        {"title": "T", "shots": [{"n": 1, "source": "AI"}]}, brand="antihero", path=tmp_db
    )
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")

    result = storage.publish_shot_media(concept_id, 99, clip, db_path=tmp_db)

    assert result["ok"] is False
    assert "uploaded but failed to record" in result["error"]
    assert result["url"] == "https://pub-abc123.r2.dev/clips/clip.mp4"


# ---------- preprod.set_shot_media_url directly ----------

def test_set_shot_media_url_raises_for_unknown_concept(tmp_db):
    with pytest.raises(ValueError, match="no concept"):
        preprod.set_shot_media_url(999, 1, "https://example.com/x.mp4", path=tmp_db)


def test_set_shot_media_url_raises_for_unknown_shot(tmp_db):
    concept_id = preprod.save_concept(
        {"title": "T", "shots": [{"n": 1, "source": "AI"}]}, brand="antihero", path=tmp_db
    )
    with pytest.raises(ValueError, match="no shot"):
        preprod.set_shot_media_url(concept_id, 7, "https://example.com/x.mp4", path=tmp_db)


def test_set_shot_media_url_requires_a_url(tmp_db):
    concept_id = preprod.save_concept(
        {"title": "T", "shots": [{"n": 1, "source": "AI"}]}, brand="antihero", path=tmp_db
    )
    with pytest.raises(ValueError, match="media_url is required"):
        preprod.set_shot_media_url(concept_id, 1, "  ", path=tmp_db)


def test_set_shot_media_url_leaves_other_shots_untouched(tmp_db):
    shots = [
        {"n": 1, "source": "AI", "prompt": "a"},
        {"n": 2, "source": "AI", "prompt": "b"},
    ]
    concept_id = preprod.save_concept(
        {"title": "T", "shots": shots}, brand="antihero", path=tmp_db
    )
    preprod.set_shot_media_url(concept_id, 2, "https://example.com/b.mp4", path=tmp_db)
    concept = preprod.get_concept(concept_id, path=tmp_db, account_id=None)
    assert "media_url" not in concept["shots"][0]
    assert concept["shots"][1]["media_url"] == "https://example.com/b.mp4"

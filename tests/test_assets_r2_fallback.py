"""
The asset catalogue reads the bucket when the photo folder is absent.

2026-09-15: GET /api/assets on the deployed API answered photos: [] and
poster: null for every character, location and prop, so the React
studio's composer and Elements page could attach none of them. The
folders are gitignored AND dockerignored; the bytes were in R2 all
along. These tests stand in a fake bucket listing at storage.list_keys
-- no boto3 call is ever made (conftest's network guard would fail it)
-- and check the four things the fallback promises: photos appear from
the bucket when the folder is missing, disk wins when it is there, the
listing is one call per prefix per process, and an unconfigured R2
degrades to an empty list.
"""
import pytest
from fastapi.testclient import TestClient

from app import api as api_mod
from app.main import app
from src import asset_shelf, autonomy, entities, evalstore, preprod, storage

client = TestClient(app)

BASE = "https://pub-abc123.r2.dev"


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    from app import auth
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "antihero", "display_name": "ANTIHERO"})


@pytest.fixture(autouse=True)
def fresh_listing_cache():
    storage.forget_listings()
    yield
    storage.forget_listings()


@pytest.fixture
def tmp_db(pg, monkeypatch):
    preprod.init(pg)
    entities.init(pg)
    autonomy.init(pg)
    evalstore.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


@pytest.fixture
def no_photo_folders(tmp_path, monkeypatch):
    """The deployed posture: the three photo roots point at directories
    that do not exist, on both the API's and the shelf's copies."""
    dirs = {}
    for plural, kind in asset_shelf.URL_ROOTS.items():
        dirs[kind] = tmp_path / plural
    monkeypatch.setattr(api_mod, "LOCATIONS_DIR", dirs["location"])
    monkeypatch.setattr(api_mod, "CHARACTERS_DIR", dirs["character"])
    monkeypatch.setattr(api_mod, "PROPS_DIR", dirs["prop"])
    monkeypatch.setattr(asset_shelf, "PHOTO_DIRS", dirs)
    return dirs


@pytest.fixture
def r2_on(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key123")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret123")
    monkeypatch.setenv("R2_BUCKET", "zpf-clips")
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", BASE + "/")


BUCKET = {
    "characters/": [
        "characters/michael/IMG_2.jpg",
        "characters/michael/IMG_1.jpg",
        "characters/michael/notes.txt",            # not a photo
        "characters/michael/old/IMG_0.jpg",        # nested: not a photo of his
        "characters/cyclops/face.png",
    ],
    "locations/": [
        "locations/living-room/plate.jpg",
    ],
    "props/": [
        "props/motorcycle/side.HEIC",
    ],
}


@pytest.fixture
def fake_bucket(monkeypatch):
    calls = []

    def list_keys(prefix):
        calls.append(prefix)
        return list(BUCKET.get(prefix, []))

    monkeypatch.setattr(storage, "list_keys", list_keys)
    return calls


def _seed(dsn):
    preprod.add_location("living-room", {"space": "a room"}, dsn=dsn, account_id=None)
    entities.add_character(name="Michael", role="rider", dsn=dsn, account_id=None)
    entities.add_character(name="Cyclops", role="monster", dsn=dsn, account_id=None)
    entities.add_prop(name="Motorcycle", category="vehicle", dsn=dsn, account_id=None)


def test_assets_read_the_bucket_when_the_folder_is_absent(
        tmp_db, no_photo_folders, r2_on, fake_bucket):
    _seed(tmp_db)
    items = {i["name"]: i for i in client.get("/api/assets").json()["items"]}

    assert items["Michael"]["photos"] == [
        f"{BASE}/characters/michael/IMG_1.jpg",
        f"{BASE}/characters/michael/IMG_2.jpg",
    ]
    assert items["Michael"]["poster"] == f"{BASE}/characters/michael/IMG_1.jpg"
    assert items["Cyclops"]["photos"] == [f"{BASE}/characters/cyclops/face.png"]
    assert items["living-room"]["photos"] == [f"{BASE}/locations/living-room/plate.jpg"]
    assert items["living-room"]["poster"] == f"{BASE}/locations/living-room/plate.jpg"
    assert items["Motorcycle"]["photos"] == [f"{BASE}/props/motorcycle/side.HEIC"]
    # every URL is the canonical, public one -- what canonical_url would
    # hand a shot, so the composer's pick lands on the row unchanged
    for item in items.values():
        for url in item["photos"]:
            assert asset_shelf.canonical_url(url) == url


def test_the_bucket_is_listed_once_per_prefix_not_once_per_asset(
        tmp_db, no_photo_folders, r2_on, fake_bucket):
    _seed(tmp_db)
    client.get("/api/assets")
    client.get("/api/assets")
    client.get("/api/assets/character-1")
    assert sorted(fake_bucket) == ["characters/", "locations/", "props/"]


def test_unconfigured_r2_degrades_to_no_photos(tmp_db, no_photo_folders, fake_bucket):
    _seed(tmp_db)
    items = client.get("/api/assets").json()["items"]
    assert all(i["photos"] == [] and i["poster"] is None for i in items)
    assert fake_bucket == []


def test_disk_still_wins_over_the_bucket(tmp_db, no_photo_folders, r2_on, fake_bucket):
    _seed(tmp_db)
    folder = no_photo_folders["character"] / "michael"
    folder.mkdir(parents=True)
    (folder / "local.jpg").write_bytes(b"jpeg bytes")
    items = {i["name"]: i for i in client.get("/api/assets").json()["items"]}
    assert items["Michael"]["photos"] == [f"{BASE}/characters/michael/local.jpg"]
    # the asset with a folder never consulted the bucket for itself, but
    # the others (no folder) still did
    assert items["Cyclops"]["photos"] == [f"{BASE}/characters/cyclops/face.png"]


def test_the_graphs_catalogue_reads_the_same_listing(
        tmp_db, no_photo_folders, r2_on, fake_bucket):
    _seed(tmp_db)
    by_name = {i["name"]: i for i in asset_shelf.catalogue(tmp_db, account_id=None)}
    assert by_name["Michael"]["photos"] == [
        f"{BASE}/characters/michael/IMG_1.jpg",
        f"{BASE}/characters/michael/IMG_2.jpg",
    ]


def test_a_failed_listing_never_raises_and_is_not_retried_per_asset(
        tmp_db, no_photo_folders, r2_on, monkeypatch):
    _seed(tmp_db)
    calls = []

    def broken(prefix):
        calls.append(prefix)
        raise RuntimeError("cloudflare is down")

    monkeypatch.setattr(storage, "list_keys", broken)
    items = client.get("/api/assets").json()["items"]
    assert all(i["photos"] == [] for i in items)
    assert sorted(calls) == ["characters/", "locations/", "props/"]


def test_an_upload_from_this_process_joins_the_cached_listing(
        r2_on, fake_bucket, monkeypatch, tmp_path):
    class FakeS3:
        def upload_file(self, filename, bucket, key, ExtraArgs=None):
            pass

    monkeypatch.setattr(storage, "_client", lambda: FakeS3())
    assert asset_shelf.r2_photo_urls("character", "cyclops") == [
        f"{BASE}/characters/cyclops/face.png"]
    photo = tmp_path / "new.jpg"
    photo.write_bytes(b"jpeg bytes")
    storage.upload_file(photo, key="characters/cyclops/new.jpg")
    assert asset_shelf.r2_photo_urls("character", "cyclops") == [
        f"{BASE}/characters/cyclops/face.png",
        f"{BASE}/characters/cyclops/new.jpg",
    ]
    assert fake_bucket == ["characters/"]

"""Reference images the agent PICKS instead of types.

On 2026-09-02 the research agent banked eleven references by writing
stock URLs from memory. The CDNs served a photo for every guess, so a
sunny tree was banked as "bark texture", a branded Harley product shot
landed on the faceless brand, and six of the Unsplash source pages
return 404 — while refbin's size/host/format guards all passed and
`bank_reference` stored an attribution nobody ever resolved.

These cover the structural answer: the candidate holds the URL, the
model holds an id, and an id nobody issued buys nothing.
"""

import json

import pytest

from src import framebank, imagesearch, mcp_server, preprod, refbin, scout

JPEG = b"\xff\xd8\xff" + b"pretend jpeg"


def real_jpeg() -> bytes:
    """An actual decodable JPEG. The local-frame path runs refbin's real
    normalisation rather than a patched fetch, so a fake header is not
    enough — it silently returns None and the frame never banks."""
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (48, 32), (40, 44, 52)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def tmp_db(pg, tmp_path, monkeypatch):
    path = pg
    preprod.init(path)
    scout.init(path)
    imagesearch.init(path)
    framebank.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    monkeypatch.setattr(refbin, "REFS_DIR", tmp_path / "refs")
    monkeypatch.setattr(framebank, "FRAMES_DIR", tmp_path / "frames")
    return path


@pytest.fixture
def a_spark(tmp_db):
    return mcp_server.bank_spark("zeropage", "the door that stays shut",
                                 dsn=tmp_db)["id"]


@pytest.fixture
def stock(monkeypatch):
    """A configured Unsplash lane with two real-shaped results."""
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "k")
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.setattr(imagesearch, "unsplash", lambda q, limit=6: [
        {"source": "unsplash", "image_url": "https://images.example/a.jpg",
         "source_url": "https://unsplash.example/photos/real-a",
         "title": "cold light on wet tile", "credit": "A N on Unsplash"},
        {"source": "unsplash", "image_url": "https://images.example/b.jpg",
         "source_url": "https://unsplash.example/photos/real-b",
         "title": "an empty corridor", "credit": "B N on Unsplash"},
    ])
    monkeypatch.setattr(mcp_server, "_reachable", lambda url: True)


# ---------- the omitted field is the feature ----------

def test_the_search_hands_back_ids_and_no_urls(tmp_db, stock):
    out = mcp_server.find_images("cold light on wet tile", brand="zeropage",
                                 dsn=tmp_db)

    assert out["count"] == 2
    for img in out["images"]:
        assert img["id"] and img["shows"] and img["credit"]
        # nothing here for a model to copy, mistype or half-remember
        assert not any("url" in k.lower() for k in img)
        assert "http" not in json.dumps(img)


def test_an_id_nobody_issued_buys_nothing(tmp_db, a_spark, stock):
    """What a guess looks like now. It must be refused rather than
    falling through to a fetch of whatever the string happens to be."""
    with pytest.raises(ValueError, match="cannot be composed"):
        mcp_search_bank(tmp_db, a_spark, "uns-deadbeefdead")


def mcp_search_bank(path, finding_id, candidate_id):
    return mcp_server.bank_reference(finding_id, candidate_id=candidate_id,
                                     dsn=path)


def test_the_url_banked_is_the_one_the_server_stored(tmp_db, a_spark, stock,
                                                     monkeypatch):
    """The caller cannot smuggle a different image in beside a valid id."""
    fetched = []
    monkeypatch.setattr(refbin, "fetch",
                        lambda url: fetched.append(url) or refbin.save(JPEG))

    found = mcp_server.find_images("wet tile", brand="zeropage", dsn=tmp_db)
    cid = found["images"][0]["id"]
    out = mcp_server.bank_reference(a_spark, candidate_id=cid,
                                    image_url="https://evil.example/other.jpg",
                                    source_url="https://evil.example/page",
                                    dsn=tmp_db)

    assert out["ok"]
    assert fetched == ["https://images.example/a.jpg"]
    banked = scout.bin_for_finding(a_spark, dsn=tmp_db)
    assert banked[0]["source_url"] == "https://unsplash.example/photos/real-a"


def test_attribution_comes_from_the_candidate_not_the_caller(tmp_db, a_spark,
                                                             stock, monkeypatch):
    monkeypatch.setattr(refbin, "fetch", lambda url: refbin.save(JPEG))
    found = mcp_server.find_images("corridor", brand="zeropage", dsn=tmp_db)
    cid = found["images"][1]["id"]

    mcp_server.bank_reference(a_spark, candidate_id=cid, dsn=tmp_db)

    row = scout.bin_for_finding(a_spark, dsn=tmp_db)[0]
    assert row["source_url"] == "https://unsplash.example/photos/real-b"
    assert row["title"] == "an empty corridor"


# ---------- the raw-URL path, which is for people ----------

def test_a_source_page_that_404s_is_refused(tmp_db, a_spark, monkeypatch):
    """Six of the eleven bad references cited pages that do not exist,
    and nothing had ever resolved one."""
    monkeypatch.setattr(mcp_server, "_reachable", lambda url: False)
    monkeypatch.setattr(refbin, "fetch", lambda url: refbin.save(JPEG))

    with pytest.raises(ValueError, match="does not resolve"):
        mcp_server.bank_reference(a_spark, image_url="https://cdn.example/x.jpg",
                                  source_url="https://unsplash.example/gone",
                                  dsn=tmp_db)


def test_a_redeemed_id_skips_the_reachability_check(tmp_db, a_spark, stock,
                                                    monkeypatch):
    """We served that URL; re-verifying it would spend a round trip to
    doubt our own row, and a flaky network would then lose the image."""
    monkeypatch.setattr(mcp_server, "_reachable",
                        lambda url: pytest.fail("checked a URL we issued"))
    monkeypatch.setattr(refbin, "fetch", lambda url: refbin.save(JPEG))
    found = mcp_server.find_images("tile", brand="zeropage", dsn=tmp_db)

    assert mcp_server.bank_reference(a_spark,
                                     candidate_id=found["images"][0]["id"],
                                     dsn=tmp_db)["ok"]


def test_reachability_fails_open_on_a_flaky_network(monkeypatch):
    """The job is catching fabrication, not policing the web. A timeout
    is not evidence a page is fake; a 404 is."""
    import requests

    def boom(*a, **k):
        raise requests.exceptions.ConnectTimeout("no route")
    monkeypatch.setattr(requests, "head", boom)
    assert mcp_server._reachable("https://example.com/x") is True


def test_neither_a_candidate_nor_a_url_is_a_caller_error(tmp_db, a_spark):
    with pytest.raises(ValueError, match="candidate_id"):
        mcp_server.bank_reference(a_spark, dsn=tmp_db)


# ---------- "nothing configured" is not "nothing matched" ----------

def test_an_unconfigured_lane_says_so(tmp_db, monkeypatch):
    """The distinction the empty scout bin hid for two days."""
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)

    out = mcp_server.find_images("anything", brand="zeropage", dsn=tmp_db)

    assert out["count"] == 0
    assert "no image source is configured" in out["note"]
    assert out["sources"] == {"frames": True, "unsplash": False, "pexels": False}


def test_a_configured_lane_that_matched_nothing_says_something_else(tmp_db,
                                                                    monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "k")
    monkeypatch.setattr(imagesearch, "unsplash", lambda q, limit=6: [])
    monkeypatch.setattr(imagesearch, "pexels", lambda q, limit=6: [])

    out = mcp_server.find_images("nothing at all", brand="zeropage", dsn=tmp_db)
    assert out["count"] == 0 and "nothing matched" in out["note"]


# ---------- his own footage, and which brand may have it ----------

def a_frame(tmp_db, tmp_path, caption, tags, clip="A037_C001.mov", t=30.0):
    d = tmp_path / "frames"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{framebank.frame_id(clip, t)}.jpg"
    f.write_bytes(real_jpeg())
    framebank.record({"id": framebank.frame_id(clip, t), "clip": clip,
                      "t_sec": t, "path": str(f), "caption": caption,
                      "tags": tags}, brand="antihero", dsn=tmp_db)
    return f


def test_zero_page_never_reaches_his_garage_footage(tmp_db, tmp_path,
                                                    monkeypatch):
    """All 37 clips are motorcycle build. Zero Page is faceless and its
    cast never attaches either, so stock is its whole grounding budget —
    serving it a garage frame would be worse than serving it nothing."""
    a_frame(tmp_db, tmp_path, "gloved hands on a bike engine", ["garage", "hands"])
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)

    assert imagesearch.search("hands", brand="zeropage", dsn=tmp_db) == []
    assert imagesearch.search("hands", brand="antihero", dsn=tmp_db)


def test_a_frame_is_read_off_disk_not_fetched(tmp_db, tmp_path, monkeypatch,
                                              a_spark):
    """His own footage never leaves the machine: there is no URL to
    fetch and no host to guard."""
    a_frame(tmp_db, tmp_path, "gloved hands on a tiled floor", ["tile", "hands"])
    monkeypatch.setattr(refbin, "fetch",
                        lambda url: pytest.fail("fetched a local frame"))
    monkeypatch.setattr(mcp_server, "_reachable", lambda url: True)

    found = mcp_server.find_images("hands on tile", brand="antihero", dsn=tmp_db)
    assert found["images"][0]["source"] == "frames"
    out = mcp_server.bank_reference(a_spark,
                                    candidate_id=found["images"][0]["id"],
                                    dsn=tmp_db)

    assert out["ok"] and out["url"].startswith("/refs/")
    assert scout.bin_for_finding(a_spark, dsn=tmp_db)[0]["source_url"].startswith(
        "footage/")


def test_an_unusable_frame_stays_in_the_bank_and_out_of_the_results(tmp_db,
                                                                    tmp_path):
    """Kept so the next build does not re-cut it; hidden so it never
    eats a reference slot."""
    a_frame(tmp_db, tmp_path, "a hand over the lens, pure blur",
            ["unusable", "blur"], clip="A037_C002.mov")
    a_frame(tmp_db, tmp_path, "a hand on a blurred engine", ["hands", "blur"],
            clip="A037_C003.mov")

    hits = framebank.search("blur hand", brand="antihero", dsn=tmp_db)
    assert len(hits) == 1 and "unusable" not in hits[0]["tags"]


def test_rebuilding_updates_a_frame_rather_than_duplicating_it(tmp_db, tmp_path):
    a_frame(tmp_db, tmp_path, "first guess", ["tile"])
    a_frame(tmp_db, tmp_path, "a better caption", ["tile", "overhead"])

    hits = framebank.search("tile", brand="antihero", dsn=tmp_db)
    assert len(hits) == 1 and hits[0]["caption"] == "a better caption"


def test_sampling_skips_the_hand_still_on_the_camera(tmp_db):
    assert framebank.sample_times(225) == [30, 60, 90, 120, 150, 180, 210]
    assert framebank.sample_times(1.08) == [0.5]     # a one-second take
    assert framebank.sample_times(0) == []

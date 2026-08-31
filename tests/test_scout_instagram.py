"""
The Instagram research lane: Business Discovery + hashtag top_media.

THERE IS NO FYP API. Mike asked for one; probing his own live token
(2026-08-31) returned "Tried accessing nonexisting field" for explore,
reels, trending, recommended_media and discover, and Meta has never
exposed the Explore/For-You surface to any API. The only way to read
that feed is scraping a logged-in session, which breaks Meta's terms and
risks the account this whole pipeline publishes to. So the lane reads
what is *performing* instead: posts with their like/comment counts from
handles he chose, and Meta's own "top" ranking for a tag.

The thing most worth pinning here is the HASHTAG BUDGET. Meta allows 30
unique hashtags per rolling 7 days, counted on the id lookup, and going
over does not raise anything interesting -- the lane just stops
returning posts. The id cache is what makes the lane sustainable, so
these tests cover the cache far harder than the happy path.
"""
import pytest

from src import db, inspiration, instagram, scout


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    db.init_db(path)
    scout.init(path)
    instagram.init(path)
    inspiration.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def no_ig_credentials(monkeypatch):
    """Default to unconfigured; tests that want the lane live say so."""
    for name in ("IG_GRAPH_TOKEN", "FB_GRAPH_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def _configured(monkeypatch):
    monkeypatch.setenv("IG_GRAPH_TOKEN", "test-graph-token")
    monkeypatch.setenv("IG_USER_ID", "17841400000000000")


# ---------- the credential boundary ----------

def test_the_lane_is_dark_without_a_facebook_login_token(tmp_db):
    """Dark, not broken -- and it must name the missing credential."""
    [signal] = scout.gather_instagram("zeropage", path=tmp_db)
    assert signal["lane"] == "instagram"
    assert "IG_GRAPH_TOKEN" in signal["error"]


def test_it_never_borrows_the_publishing_token(tmp_db, monkeypatch):
    """The publishing token is an Instagram-Login token on a different
    host; graph.facebook.com cannot even parse it. Falling back to it
    would turn a missing-credential state into what looks like an
    outage."""
    monkeypatch.setenv("IG_ACCESS_TOKEN", "an-instagram-login-token")
    monkeypatch.delenv("IG_GRAPH_TOKEN", raising=False)
    assert instagram.graph_token() is None
    ok, reason = instagram.research_ready()
    assert not ok and "IG_GRAPH_TOKEN" in reason


def test_business_discovery_without_credentials_does_not_raise():
    result = instagram.business_discovery("someone")
    assert result["ok"] is False and result["posts"] == []


# ---------- the hashtag budget, which is the real constraint ----------

def test_a_cached_tag_costs_no_budget(tmp_db, monkeypatch):
    _configured(monkeypatch)
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        raise AssertionError("a cached tag must not hit the API")

    with db.connect(tmp_db) as conn:
        conn.execute("INSERT INTO ig_hashtag_ids (tag, hashtag_id, looked_up_at) "
                     "VALUES ('moodygrams', '17843', '2026-08-01T00:00:00+00:00')")
    monkeypatch.setattr(instagram.requests, "get", fake_get)

    result = instagram.hashtag_id("#MoodyGrams", path=tmp_db)
    assert result["ok"] and result["id"] == "17843" and result["cached"]
    assert calls == []


def test_a_new_tag_is_looked_up_once_and_then_cached(tmp_db, monkeypatch):
    _configured(monkeypatch)
    calls = []

    class Resp:
        @staticmethod
        def json():
            return {"data": [{"id": "999"}]}

    def fake_get(url, **kw):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(instagram.requests, "get", fake_get)

    first = instagram.hashtag_id("newtag", path=tmp_db)
    second = instagram.hashtag_id("newtag", path=tmp_db)

    assert first["ok"] and not first["cached"]
    assert second["ok"] and second["cached"]
    assert len(calls) == 1              # the second one spent nothing


def test_the_budget_refuses_before_meta_does(tmp_db, monkeypatch):
    """Refusing locally means the log carries the real reason instead of
    a generic API error -- and it does not waste the call."""
    _configured(monkeypatch)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with db.connect(tmp_db) as conn:
        for i in range(instagram.HASHTAG_WINDOW_MAX):
            conn.execute("INSERT INTO ig_hashtag_ids (tag, hashtag_id, looked_up_at) "
                         "VALUES (?, ?, ?)", (f"tag{i}", str(i), now))

    def boom(*a, **k):
        raise AssertionError("must not call Meta when the window is spent")

    monkeypatch.setattr(instagram.requests, "get", boom)

    result = instagram.hashtag_id("onemoretag", path=tmp_db)
    assert not result["ok"]
    assert "budget spent" in result["error"]


def test_tags_outside_the_window_do_not_count_against_it(tmp_db, monkeypatch):
    _configured(monkeypatch)
    with db.connect(tmp_db) as conn:
        for i in range(instagram.HASHTAG_WINDOW_MAX):
            conn.execute("INSERT INTO ig_hashtag_ids (tag, hashtag_id, looked_up_at) "
                         "VALUES (?, ?, ?)", (f"old{i}", str(i), "2020-01-01T00:00:00+00:00"))

    class Resp:
        @staticmethod
        def json():
            return {"data": [{"id": "777"}]}

    monkeypatch.setattr(instagram.requests, "get", lambda *a, **k: Resp())
    assert instagram.hashtag_id("freshtag", path=tmp_db)["ok"]


def test_the_shipped_tag_lists_fit_inside_one_window():
    """Both brands' tags are looked up once, ever. If this list grows
    past the cap the lane starves in its second week."""
    total = sum(len(v) for v in scout.INSTAGRAM_TAGS.values())
    assert total <= instagram.HASHTAG_WINDOW_MAX


# ---------- turning a post into a signal ----------

def test_a_post_becomes_a_signal_with_its_permalink_and_counts():
    signal = scout._ig_signal({
        "caption": "shot this at 3am in the garage  #moto #night #ducati",
        "like_count": 4210, "comments_count": 88, "media_type": "IMAGE",
        "media_url": "https://cdn/a.jpg",
        "permalink": "https://instagram.com/p/abc"}, source="@layed_black")

    assert "shot this at 3am in the garage" in signal["detail"]
    assert "#moto" not in signal["detail"]      # trailing hashtag block trimmed
    assert signal["url"] == "https://instagram.com/p/abc"
    assert signal["image"] == "https://cdn/a.jpg"
    assert "4,210 likes" in signal["metric"] and "88 comments" in signal["metric"]


def test_a_video_post_uses_its_thumbnail_for_the_bin():
    signal = scout._ig_signal({
        "caption": "a reel", "media_type": "VIDEO",
        "media_url": "https://cdn/a.mp4",
        "thumbnail_url": "https://cdn/thumb.jpg",
        "permalink": "https://instagram.com/reel/x"}, source="#moodygrams")
    assert signal["image"] == "https://cdn/thumb.jpg"


def test_a_hashtag_post_is_still_attributable_by_permalink():
    """Meta strips `username` from hashtag media, so the permalink is
    the only attribution there is -- and the bin keeps it."""
    signal = scout._ig_signal({
        "caption": "x", "media_type": "IMAGE", "media_url": "https://cdn/a.jpg",
        "permalink": "https://instagram.com/p/zzz"}, source="#analoghorror")
    assert signal["url"] == "https://instagram.com/p/zzz"
    assert signal["detail"].startswith("#analoghorror:")


def test_a_caption_that_is_only_hashtags_still_yields_a_signal():
    signal = scout._ig_signal({"caption": "#moto #night", "media_type": "IMAGE",
                               "permalink": "https://instagram.com/p/q"},
                              source="@x")
    assert signal["detail"]


# ---------- the lane inside a pass ----------

def test_a_dead_handle_is_reported_and_the_others_still_read(tmp_db, monkeypatch):
    _configured(monkeypatch)
    inspiration.add("good_one", "", "a profile", brand="zeropage", path=tmp_db)
    inspiration.add("private_one", "", "a profile", brand="zeropage", path=tmp_db)

    def fake_bd(handle, limit=6, token=None, user_id=None):
        if handle == "private_one":
            return {"ok": False, "posts": [], "error": "not a professional account"}
        return {"ok": True, "handle": handle, "posts": [
            {"caption": "a real post", "like_count": 10, "media_type": "IMAGE",
             "media_url": "https://cdn/a.jpg", "permalink": "https://ig/p/1"}]}

    monkeypatch.setattr(instagram, "business_discovery", fake_bd)
    monkeypatch.setattr(instagram, "hashtag_top_media",
                        lambda tag, **k: {"ok": False, "media": [], "error": "no budget"})

    signals = scout.gather_instagram("zeropage", path=tmp_db)
    details = [s for s in signals if s.get("detail")]
    errors = [s for s in signals if s.get("error")]

    assert any("a real post" in s["detail"] for s in details)
    assert any("private_one" in e["error"] for e in errors)


def test_the_lane_is_brand_scoped(tmp_db, monkeypatch):
    """ANTIHERO's moto handles must not seed Zero Page ideation, same
    rule inspiration.py has always held."""
    _configured(monkeypatch)
    inspiration.add("moto_guy", "", "p", brand="antihero", path=tmp_db)
    inspiration.add("faceless_guy", "", "p", brand="zeropage", path=tmp_db)
    seen = []
    monkeypatch.setattr(instagram, "business_discovery",
                        lambda handle, **k: seen.append(handle) or
                        {"ok": True, "posts": [], "handle": handle})
    monkeypatch.setattr(instagram, "hashtag_top_media",
                        lambda tag, **k: {"ok": True, "media": [], "error": ""})

    scout.gather_instagram("zeropage", path=tmp_db)
    assert "faceless_guy" in seen and "moto_guy" not in seen


def test_instagram_is_in_the_default_lane_set():
    import inspect
    default = inspect.signature(scout.scout).parameters["lanes"].default
    assert "instagram" in default

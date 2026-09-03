"""
Tests for src/scout.py -- the research agent that crawls for a spark.

Hermetic by construction: conftest's no_network fixture blocks every
socket, so any lane that quietly starts making a real call fails loudly
here rather than showing up as a slow suite and a surprise bill.

The bias in these tests is toward the DEGRADATION paths. The happy path
is one JSON parse; the thing that actually matters is that a dead lane,
a malformed digest, an empty bank or a repeated idea each cost the
night nothing more than a fallback to prompts/sparks.txt -- because the
static rotation this replaces never failed, and a research step that
can fail a night is a downgrade.
"""
import json

import pytest

from src import db, orchestrator, scout, winners


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    db.init_db(path)
    scout.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.candidates = []


class FakeModels:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def generate_content(self, model=None, contents=None, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return FakeResponse(self._text)


class FakeClient:
    def __init__(self, text=""):
        self.models = FakeModels(text)


DIGEST_JSON = json.dumps({"candidates": [
    {"spark": "the last check before leaving", "rationale": "night rituals are landing",
     "evidence": "three of the top feed posts this week were pre-ride rituals",
     "sources": ["https://example.com/a"], "score": 0.82},
    {"spark": "a routine performed wrong", "rationale": "mistake-as-hook format",
     "evidence": "highest-view short in the sample opens on an error",
     "sources": ["https://youtube.com/watch?v=x"], "score": 0.71},
]})


# ---------- novelty keys ----------

def test_spark_key_normalises_case_punctuation_and_small_words():
    assert scout._spark_key("The Last Check, Before Leaving.") == \
           scout._spark_key("last check before leaving")


def test_spark_key_keeps_genuinely_different_directions_apart():
    assert scout._spark_key("a routine performed wrong") != \
           scout._spark_key("the last check before leaving")


def test_spark_key_of_junk_is_empty_so_it_can_be_rejected():
    assert scout._spark_key("  ... the a of  ") == ""


# ---------- sources file ----------

def test_load_sources_filters_to_brand_plus_both(tmp_path):
    f = tmp_path / "sources.txt"
    f.write_text("# comment\n\n"
                 "both      https://both.example/f.json\n"
                 "zeropage  https://zp.example/f.json\n"
                 "antihero  https://ah.example/f.json\n")
    assert scout.load_sources(f, brand="zeropage") == [
        "https://both.example/f.json", "https://zp.example/f.json"]
    assert scout.load_sources(f, brand="antihero") == [
        "https://both.example/f.json", "https://ah.example/f.json"]


def test_load_sources_missing_file_is_empty_not_fatal(tmp_path):
    assert scout.load_sources(tmp_path / "nope.txt", brand="zeropage") == []


def test_repo_sources_file_is_parseable_and_brand_scoped():
    """The shipped file must actually split -- a malformed line would make
    a lane silently contribute nothing, which reads as a quiet night."""
    assert scout.load_sources(brand="zeropage")
    assert scout.load_sources(brand="antihero")
    zp = set(scout.load_sources(brand="zeropage"))
    ah = set(scout.load_sources(brand="antihero"))
    assert zp != ah, "the two brands must not crawl an identical source list"


# ---------- feed parsing ----------

def test_parse_reddit_pulls_title_permalink_and_score():
    body = json.dumps({"data": {"children": [
        {"data": {"title": "shot this at 3am", "permalink": "/r/x/1/", "ups": 412}},
        {"data": {"title": "", "permalink": "/r/x/2/", "ups": 9}},   # dropped
    ]}})
    [item] = scout._parse_reddit(body)
    assert item["detail"] == "shot this at 3am"
    assert item["url"].endswith("/r/x/1/")
    assert "412" in item["metric"]


def test_parse_feed_handles_rss_and_atom_without_a_namespace_map():
    rss = """<rss><channel>
      <item><title>RSS one</title><link>https://a.example/1</link></item>
    </channel></rss>"""
    atom = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Atom one</title><link href="https://b.example/1"/></entry>
    </feed>"""
    assert scout._parse_feed(rss)[0]["detail"] == "RSS one"
    atom_item = scout._parse_feed(atom)[0]
    assert atom_item["detail"] == "Atom one"
    assert atom_item["url"] == "https://b.example/1"


def test_gather_feeds_records_a_dead_source_as_an_error_not_a_crash(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(scout.requests, "get", boom)

    signals = scout.gather_feeds("zeropage", sources=["https://dead.example/f.json"])
    assert signals and all(s.get("error") for s in signals)


# ---------- the digest ----------

def test_parse_digest_accepts_a_fenced_response():
    out = scout.parse_digest_response("```json\n" + DIGEST_JSON + "\n```")
    assert [c["spark"] for c in out] == ["the last check before leaving",
                                         "a routine performed wrong"]
    assert out[0]["score"] == pytest.approx(0.82)


def test_parse_digest_of_garbage_is_empty_not_an_exception():
    assert scout.parse_digest_response("I could not find anything today, sorry!") == []
    assert scout.parse_digest_response("") == []


def test_parse_digest_clamps_a_score_outside_the_range():
    out = scout.parse_digest_response(json.dumps(
        {"candidates": [{"spark": "x y z", "score": 7.5},
                        {"spark": "p q r", "score": "not a number"}]}))
    assert out[0]["score"] == 1.0
    assert out[1]["score"] == 0.0


def test_digest_prompt_carries_the_avoid_list_and_the_recent_sparks(tmp_db):
    winners.init(tmp_db)
    winners.add("runway", "some prompt", note="slow-motion openers flopped",
                verdict="didnt_work", path=tmp_db)
    scout.record("zeropage", {"spark": "an old idea", "score": 0.9}, path=tmp_db)

    prompt = scout.build_digest_prompt(
        "zeropage", [{"lane": "web", "detail": "something found"}], 3,
        avoid=winners.avoid_guidance(path=tmp_db),
        recent=scout.recent_sparks("zeropage", path=tmp_db))

    assert "slow-motion openers flopped" in prompt
    assert "an old idea" in prompt
    assert "something found" in prompt
    assert "{signals}" not in prompt and "{brand}" not in prompt


def test_format_signals_omits_lanes_that_only_reported_an_error():
    text = scout.format_signals([
        {"lane": "web", "error": "boom"},
        {"lane": "shorts", "detail": "a title", "metric": "9 views", "url": "u"},
    ])
    assert "boom" not in text
    assert "a title" in text and "9 views" in text


# ---------- the pass ----------

def test_scout_banks_scored_candidates(tmp_db, monkeypatch):
    monkeypatch.setattr(scout, "gather_web", lambda *a, **k: [
        {"lane": "web", "detail": "night rituals everywhere"}])
    client = FakeClient(DIGEST_JSON)

    result = scout.scout("zeropage", 2, client=client, model="fake",
                         lanes=("web",), path=tmp_db)

    assert result["ok"]
    assert [f["spark"] for f in result["findings"]] == [
        "the last check before leaving", "a routine performed wrong"]
    assert len(scout.list_findings(brand="zeropage", path=tmp_db)) == 2


def test_scout_drops_a_candidate_that_repeats_a_recent_spark(tmp_db, monkeypatch):
    scout.record("zeropage", {"spark": "The Last Check Before Leaving!", "score": 0.9},
                 path=tmp_db)
    monkeypatch.setattr(scout, "gather_web", lambda *a, **k: [
        {"lane": "web", "detail": "x"}])

    result = scout.scout("zeropage", 2, client=FakeClient(DIGEST_JSON), model="fake",
                         lanes=("web",), path=tmp_db)

    sparks = [f["spark"] for f in result["findings"]]
    assert sparks == ["a routine performed wrong"]
    assert any("repeat" in e for e in result["errors"])


def test_scout_with_every_lane_dead_reports_not_ok_and_banks_nothing(tmp_db, monkeypatch):
    monkeypatch.setattr(scout, "gather_web", lambda *a, **k: [
        {"lane": "web", "error": "no key"}])

    result = scout.scout("zeropage", 2, client=FakeClient(DIGEST_JSON), model="fake",
                         lanes=("web",), path=tmp_db)

    assert result["ok"] is False
    assert scout.list_findings(path=tmp_db) == []


def test_scout_survives_a_digest_that_raises(tmp_db, monkeypatch):
    monkeypatch.setattr(scout, "gather_web", lambda *a, **k: [
        {"lane": "web", "detail": "x"}])

    class Exploding(FakeClient):
        def __init__(self):
            super().__init__("")
            self.models.generate_content = self._boom

        def _boom(self, **k):
            raise RuntimeError("gemini fell over")

    result = scout.scout("zeropage", 2, client=Exploding(), model="fake",
                         lanes=("web",), path=tmp_db)
    assert result["ok"] is False
    assert any("digest failed" in e for e in result["errors"])


def test_scout_rejects_an_unknown_brand(tmp_db):
    with pytest.raises(ValueError):
        scout.scout("someone-elses-brand", path=tmp_db)


def test_scout_keeps_the_brands_apart(tmp_db, monkeypatch):
    monkeypatch.setattr(scout, "gather_web", lambda *a, **k: [
        {"lane": "web", "detail": "x"}])
    scout.scout("zeropage", 2, client=FakeClient(DIGEST_JSON), model="fake",
                lanes=("web",), path=tmp_db)

    assert scout.list_findings(brand="antihero", path=tmp_db) == []
    assert len(scout.list_findings(brand="zeropage", path=tmp_db)) == 2


# ---------- the bank ----------

def test_next_spark_takes_the_highest_scorer_and_skips_the_floor(tmp_db):
    scout.record("zeropage", {"spark": "a weak one", "score": 0.2}, path=tmp_db)
    scout.record("zeropage", {"spark": "a strong one", "score": 0.9}, path=tmp_db)
    scout.record("zeropage", {"spark": "a middling one", "score": 0.6}, path=tmp_db)

    assert scout.next_spark("zeropage", path=tmp_db)["spark"] == "a strong one"


def test_next_spark_is_none_when_everything_is_under_the_floor(tmp_db):
    scout.record("zeropage", {"spark": "a weak one", "score": 0.1}, path=tmp_db)
    assert scout.next_spark("zeropage", path=tmp_db) is None


def test_mark_used_stops_a_spark_being_served_twice(tmp_db):
    first = scout.record("zeropage", {"spark": "a strong one", "score": 0.9}, path=tmp_db)
    scout.record("zeropage", {"spark": "the runner up", "score": 0.8}, path=tmp_db)

    scout.mark_used(first, run_id="abc123", path=tmp_db)

    assert scout.next_spark("zeropage", path=tmp_db)["spark"] == "the runner up"
    [row] = [r for r in scout.list_findings(path=tmp_db) if r["id"] == first]
    assert row["run_id"] == "abc123" and row["used_at"]


def test_list_findings_on_a_missing_table_is_empty_not_fatal(tmp_path):
    assert scout.list_findings(path=tmp_path / "nothing-here.db") == []


# ---------- the graph node ----------

def test_node_is_a_noop_when_scouting_was_not_asked_for(tmp_db):
    scout.record("zeropage", {"spark": "a crawled idea", "score": 0.9}, path=tmp_db)
    assert orchestrator.scout({"brand": "zeropage", "spark": "a hand-typed one"}) == {}


def test_node_swaps_in_the_scouted_spark_when_asked(tmp_db):
    scout.record("zeropage", {"spark": "a crawled idea", "rationale": "because",
                              "score": 0.9}, path=tmp_db)

    out = orchestrator.scout({"brand": "zeropage", "spark": "the rotation",
                              "scout": True})

    assert out["spark"] == "a crawled idea"
    assert out["goal"] == "a crawled idea"
    assert out["scout_rationale"] == "because"
    assert out["scout_finding_id"]


def test_node_falls_back_to_the_rotation_when_the_bank_is_thin(tmp_db):
    scout.record("zeropage", {"spark": "too weak to spend on", "score": 0.1},
                 path=tmp_db)
    assert orchestrator.scout({"brand": "zeropage", "spark": "the rotation",
                               "scout": True}) == {}


def test_node_falls_back_when_the_bank_itself_is_unreachable(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(scout, "next_spark", boom)

    assert orchestrator.scout({"brand": "zeropage", "spark": "the rotation",
                               "scout": True}) == {}


def test_planner_claims_the_finding_against_the_run_it_minted(tmp_db):
    from src import autonomy
    autonomy.init(tmp_db)
    finding_id = scout.record("zeropage", {"spark": "a crawled idea", "score": 0.9},
                              path=tmp_db)

    out = orchestrator.planner({"channel": "zeropage", "scout_finding_id": finding_id})

    [row] = [r for r in scout.list_findings(path=tmp_db) if r["id"] == finding_id]
    assert row["run_id"] == out["run_id"]
    assert scout.next_spark("zeropage", path=tmp_db) is None


# ---------- the research bin ----------

def test_stash_images_banks_each_image_with_its_source(tmp_db):
    signals = [
        {"lane": "instagram", "detail": "a night ride", "url": "https://ig/p/1",
         "image": "https://img/1.jpg", "metric": "1,000 likes"},
        {"lane": "instagram", "detail": "a garage post", "url": "https://ig/p/2",
         "image": "https://img/2.jpg", "metric": ""},
        {"lane": "web", "detail": "no image on this one"},
    ]
    fetched = {}

    def fake_fetch(url):
        fetched[url] = f"/refs/{len(fetched)}.jpg"
        return fetched[url]

    rows = scout.stash_images("zeropage", "pass-1", signals, path=tmp_db,
                              fetch=fake_fetch)

    assert [r["url"] for r in rows] == ["/refs/0.jpg", "/refs/1.jpg"]
    assert rows[0]["source_url"] == "https://ig/p/1"
    assert rows[1]["lane"] == "instagram"
    assert scout.bin_for_pass("pass-1", path=tmp_db)


def test_stash_images_dedupes_the_same_picture_found_twice(tmp_db):
    signals = [{"lane": "instagram", "detail": "a", "image": "https://img/1.jpg"},
               {"lane": "instagram", "detail": "b", "image": "https://img/copy.jpg"}]
    # content-addressed storage returns the same URL for identical bytes
    rows = scout.stash_images("zeropage", "pass-1", signals, path=tmp_db,
                              fetch=lambda url: "/refs/same.jpg")
    assert len(rows) == 1


def test_stash_images_skips_what_it_cannot_fetch(tmp_db):
    signals = [{"lane": "instagram", "detail": "a", "image": "https://img/broken.jpg"}]
    rows = scout.stash_images("zeropage", "pass-1", signals, path=tmp_db,
                              fetch=lambda url: None)
    assert rows == []
    assert scout.bin_for_pass("pass-1", path=tmp_db) == []


def test_stash_images_stops_at_the_composer_limit(tmp_db):
    signals = [{"lane": "instagram", "detail": str(i), "image": f"https://img/{i}.jpg"}
               for i in range(20)]
    rows = scout.stash_images("zeropage", "pass-1", signals, path=tmp_db,
                              fetch=lambda url: f"/refs/{url[-6:]}")
    assert len(rows) == scout.MAX_BIN_IMAGES <= 6


def test_bin_for_finding_returns_the_pass_it_was_read_out_of(tmp_db, monkeypatch):
    monkeypatch.setattr(scout, "gather_web", lambda *a, **k: [
        {"lane": "instagram", "detail": "x", "image": "https://img/1.jpg"}])
    monkeypatch.setattr(scout.refbin, "fetch", lambda url: "/refs/one.jpg")

    result = scout.scout("zeropage", 2, client=FakeClient(DIGEST_JSON), model="fake",
                         lanes=("web",), path=tmp_db)

    # both candidates came out of ONE crawl, so both see the same bin
    for finding in result["findings"]:
        assert [b["url"] for b in scout.bin_for_finding(finding["id"], path=tmp_db)] \
            == ["/refs/one.jpg"]


def test_a_pass_that_banks_nothing_does_not_fetch_images(tmp_db, monkeypatch):
    """Files nothing can reference are just litter in data/refs."""
    monkeypatch.setattr(scout, "gather_web", lambda *a, **k: [
        {"lane": "web", "detail": "x", "image": "https://img/1.jpg"}])
    calls = []
    monkeypatch.setattr(scout.refbin, "fetch",
                        lambda url: calls.append(url) or "/refs/one.jpg")

    scout.scout("zeropage", 2, client=FakeClient("not json at all"), model="fake",
                lanes=("web",), path=tmp_db)
    assert calls == []


def test_bin_for_a_pass_that_does_not_exist_is_empty(tmp_db):
    assert scout.bin_for_pass("no-such-pass", path=tmp_db) == []
    assert scout.bin_for_finding(9999, path=tmp_db) == []


# ---------- reddit image extraction ----------

def test_reddit_preview_url_is_unescaped_so_the_signed_fetch_works():
    post = {"preview": {"images": [{"source": {
        "url": "https://preview.redd.it/a.jpg?width=640&amp;s=abc"}}]}}
    assert scout._reddit_image(post) == "https://preview.redd.it/a.jpg?width=640&s=abc"


def test_reddit_placeholder_thumbnails_are_not_treated_as_urls():
    for placeholder in ("self", "default", "nsfw", "spoiler", ""):
        assert scout._reddit_image({"thumbnail": placeholder}) == ""


def test_reddit_falls_back_to_a_real_thumbnail_url():
    assert scout._reddit_image({"thumbnail": "https://b.thumbs.redditmedia.com/x.jpg"}) \
        == "https://b.thumbs.redditmedia.com/x.jpg"


# ---------- what the digest must NOT do ----------

def test_the_digest_does_not_ask_for_a_room():
    """Backed out 2026-08-31 after Mike caught it. The scout's main
    consumer is the nightly graph, whose generator is
    shootgen.build_scene_brief_prompt -- and that template's whole
    placeholder set is {brand} {cast} {example} {references} {spark}.
    There is no {locations}. A spark pinned to "living-room" imposes a
    constraint nothing downstream can honour, and on the Create path
    (scenes_prompt.txt, which DOES have {locations}) the generator
    fetches the rooms itself, so pre-committing to one only removes the
    variety location_variety_note exists to manage.

    Measured on identical signals: dropping the rooms block made the
    sparks better, not worse ("a dinner plate set for three" vs "shaking
    hands holding one rusted key" on a balcony). The improvement in that
    prompt came from the translation rule and the forbidden-subject
    list, both of which stay."""
    template = scout.DIGEST_PROMPT_PATH.read_text()
    assert "{locations}" not in template
    assert '"room"' not in template


def test_the_scene_brief_generator_really_has_no_locations_slot():
    """The fact the test above depends on. If this ever fails, the
    generator learned about rooms and the decision is worth revisiting."""
    from src import shootgen
    template = (shootgen.PROMPTS_DIR / "scene_brief_prompt.txt").read_text()
    assert "{locations}" not in template


def test_the_digest_keeps_the_translation_rule_and_the_ban_list():
    """What actually fixed the drift: signals are where an idea comes
    FROM, not what the scene is ABOUT."""
    template = scout.DIGEST_PROMPT_PATH.read_text()
    assert "not what the scene is" in template.replace("\n", " ")
    for banned in ("screens", "monetisation", "algorithms"):
        assert banned in template


# ---------- what may enter the bin ----------

def test_youtube_thumbnails_never_enter_the_bin(tmp_db):
    """The first real bin (2026-08-31) came back as three YouTube
    monetisation-guru thumbnails -- "MONETIZED $5,000", a Studio revenue
    graph, a man screaming over "$203,523.43". Those would have been
    pre-attached to a Zero Page scene, and refs[0] is the frame Runway
    anchors the clip on. A thumbnail is a marketing asset engineered as
    face + text + UI screenshot; its SHAPE is wrong for the job whatever
    the query returns, so the lane contributes text only."""
    signals = [
        {"lane": "shorts", "detail": "a title", "image": "https://i.ytimg.com/x.jpg",
         "url": "https://youtube.com/watch?v=1"},
        {"lane": "feeds", "detail": "an article", "image": "https://blog/lead.jpg",
         "url": "https://blog/post"},
    ]
    rows = scout.stash_images("zeropage", "p", signals, path=tmp_db,
                              fetch=lambda u: f"/refs/{u[-9:]}")
    assert [r["lane"] for r in rows] == []      # neither lane may bank a picture


def test_only_instagram_may_bank_a_picture(tmp_db):
    """Every other lane's images were opened and looked at (2026-08-31):
    YouTube gives clickbait thumbnails, feeds give product shots and
    copyrighted film stills. On Instagram the image IS the post -- the
    creator's own frame rather than an illustration of an article about
    one -- which is the only case where banking it blind is defensible."""
    signals = [
        {"lane": "shorts", "detail": "t", "image": "https://i.ytimg.com/a.jpg"},
        {"lane": "feeds", "detail": "t", "image": "https://blog/lead.jpg"},
        {"lane": "web", "detail": "t", "image": "https://x/y.jpg"},
        {"lane": "instagram", "detail": "t", "image": "https://cdn.ig/p.jpg",
         "url": "https://instagram.com/p/abc"},
    ]
    rows = scout.stash_images("zeropage", "p", signals, path=tmp_db,
                              fetch=lambda u: "/refs/ok.jpg")
    assert [r["lane"] for r in rows] == ["instagram"]


def test_an_empty_bin_is_the_correct_answer_not_a_failure(tmp_db):
    """No reference beats a wrong one: refs[0] is the frame Runway
    anchors the clip on."""
    rows = scout.stash_images("zeropage", "p", [
        {"lane": "feeds", "detail": "t", "image": "https://blog/lead.jpg"}],
        path=tmp_db, fetch=lambda u: "/refs/ok.jpg")
    assert rows == []
    assert scout.bin_for_pass("p", path=tmp_db) == []


def test_the_shorts_lane_still_carries_its_text_signal(monkeypatch):
    """Dropping the image must not cost the titles and view counts --
    that is the half of this lane that earns its place."""
    from src import youtube
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(youtube, "search_videos", lambda q, key, **kw: {
        "ok": True, "videos": [{"title": "a night ride", "views": 12345,
                                "url": "https://youtube.com/watch?v=1",
                                "thumbnail": "https://i.ytimg.com/x.jpg"}]})
    [signal] = [s for s in scout.gather_shorts("zeropage") if s.get("detail")][:1]
    assert signal["detail"] == "a night ride"
    assert "12,345 views" in signal["metric"]
    assert not signal.get("image")


def test_a_new_lane_must_opt_in_before_its_images_are_banked(tmp_db):
    """Fail closed: an unknown lane's pictures are not banked until
    someone has looked at what they actually are."""
    rows = scout.stash_images("zeropage", "p", [
        {"lane": "some_new_lane", "detail": "x", "image": "https://x/y.jpg"}],
        path=tmp_db, fetch=lambda u: "/refs/a.jpg")
    assert rows == []


# ---------- the bin, written from either door ----------

def test_bank_urls_writes_only_refs_under_the_findings_pass(tmp_db):
    fid = scout.record("zeropage", {"spark": "one glove", "score": 0.9}, path=tmp_db)
    rows = scout.bank_urls(fid, ["/refs/a.jpg?thumb=1", "/locations/shop/photo/x.jpg",
                                 "/refs/a.jpg", "/refs/b.jpg"],
                           lane="composer", path=tmp_db)
    assert [r["url"] for r in rows] == ["/refs/a.jpg", "/refs/b.jpg"]
    assert {r["lane"] for r in rows} == {"composer"}
    banked = scout.bin_for_finding(fid, path=tmp_db)
    assert [b["url"] for b in banked] == ["/refs/a.jpg", "/refs/b.jpg"]
    assert scout.get_finding(fid, path=tmp_db)["pass_id"] == f"agent-{fid}"


def test_bank_urls_keeps_a_crawls_pass_and_never_raises(tmp_db):
    fid = scout.record("zeropage", {"spark": "one glove", "score": 0.9},
                       pass_id="crawl-7", path=tmp_db)
    scout.bank_urls(fid, ["/refs/a.jpg"], lane="composer", path=tmp_db)
    assert scout.get_finding(fid, path=tmp_db)["pass_id"] == "crawl-7"
    assert scout.bank_urls(999999, ["/refs/a.jpg"], lane="composer", path=tmp_db) == []


def test_find_by_spark_matches_on_the_claim_key_and_prefers_the_unused(tmp_db):
    used = scout.record("zeropage", {"spark": "one glove", "score": 0.9}, path=tmp_db)
    scout.mark_used(used, run_id="r1", path=tmp_db)
    fresh = scout.record("zeropage", {"spark": "One Glove!", "score": 0.9}, path=tmp_db)
    assert scout.find_by_spark("zeropage", "one glove", path=tmp_db)["id"] == fresh
    assert scout.find_by_spark("antihero", "one glove", path=tmp_db) is None
    assert scout.find_by_spark("zeropage", "two gloves", path=tmp_db) is None
    assert scout.find_by_spark("zeropage", "", path=tmp_db) is None

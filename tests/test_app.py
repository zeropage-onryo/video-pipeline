"""
Tests for app/main.py's routes. Template-only rendering is exempt from
strict TDD; form parsing and the routes that write data are not.
"""
from datetime import date, timedelta
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app import seo
from app.main import (
    app,
    benchmark_class,
    parse_metrics_form,
    parse_video_form,
)
from src import db, preprod

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_real_rag_store(monkeypatch):
    """
    libpq connects below the Python socket module, so conftest's network
    guard can't stop a route from reaching a REAL local Postgres (one is
    running on this machine now). Default every app test to 'store
    unreachable'; tests that want the store patch these again themselves.
    """
    def refused(db_url=None):
        raise ConnectionError("no rag store in tests")

    monkeypatch.setattr(app_main.rag, "connect", refused)
    # The generate routes retrieve grounding references before calling
    # the model. Stub that at the edge helper rather than relying on the
    # connect guard above, so a route test can never depend on how far
    # down the retrieval path it gets.
    monkeypatch.setattr(app_main.shootgen, "reference_block", lambda **k: "")


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    db.init_db(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture
def tmp_preprod_db(tmp_db):
    """tmp_db plus the pre-production tables -- the same set the app's
    lifespan creates (preprod + the characters/props entities)."""
    from src import entities, inspiration
    preprod.init(tmp_db)
    entities.init(tmp_db)
    inspiration.init(tmp_db)
    return tmp_db


def test_root_serves_the_landing_page_not_the_workspace(tmp_db):
    """`/` is the marketing front door and the only indexed page; the
    workspace is /studio."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Pitch runs" not in response.text      # not the workspace canvas
    assert "/studio" in response.text             # the landing's call to action


def test_studio_returns_200(tmp_preprod_db):
    response = client.get("/studio")
    assert response.status_code == 200


def test_studio_is_the_zp_home(tmp_preprod_db):
    """/studio is the Zero Page home: the composer posts into the
    assistant, and the shared rail is present with Home active."""
    response = client.get("/studio")
    assert "What do you want to create?" in response.text
    assert 'action="/studio/assist"' in response.text
    assert 'class="rail"' in response.text


def test_dashboard_redirects_to_the_studio(tmp_preprod_db):
    """It was the front door for months; a dead bookmark is a bug."""
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/studio"


# ---------- parse_video_form ----------

def test_parse_video_form_required_fields_only():
    parsed = parse_video_form({
        "title": "  My Video  ", "platform": "youtube", "posted_at": "2026-01-01",
    })
    assert parsed == {
        "title": "My Video", "platform": "youtube", "posted_at": "2026-01-01",
        "url": None, "timeline": None, "topic": None, "hook_type": None,
        "idea_id": None,
    }


def test_parse_video_form_optional_fields_populated():
    parsed = parse_video_form({
        "title": "T", "platform": "tiktok", "posted_at": "2026-01-01",
        "url": "https://x", "timeline": "Story 2", "topic": "workshop",
        "hook_type": "text-hook", "idea_id": "5",
    })
    assert parsed["url"] == "https://x"
    assert parsed["timeline"] == "Story 2"
    assert parsed["idea_id"] == 5


def test_parse_video_form_blank_optionals_become_none():
    parsed = parse_video_form({
        "title": "T", "platform": "tiktok", "posted_at": "2026-01-01",
        "url": "   ", "idea_id": "",
    })
    assert parsed["url"] is None
    assert parsed["idea_id"] is None


# ---------- POST /videos/new ----------

def test_videos_new_get_returns_200(tmp_db):
    response = client.get("/videos/new")
    assert response.status_code == 200


def test_post_videos_new_creates_a_video(tmp_db):
    response = client.post("/videos/new", data={
        "title": "Test Video", "platform": "youtube", "posted_at": "2026-01-01",
    }, follow_redirects=False)
    assert response.status_code in (302, 303, 307)

    # the landing owns `/` now, so a save must land on the workspace
    # rather than bouncing the user out to the marketing page
    assert response.headers["location"] == "/studio"

    videos = db.list_videos(path=tmp_db)
    assert len(videos) == 1
    assert videos[0]["title"] == "Test Video"
    assert videos[0]["platform"] == "youtube"


def test_post_videos_new_rejects_bad_platform(tmp_db):
    response = client.post("/videos/new", data={
        "title": "Test Video", "platform": "myspace", "posted_at": "2026-01-01",
    })
    assert response.status_code == 400
    assert db.list_videos(path=tmp_db) == []


# ---------- parse_metrics_form ----------

def test_parse_metrics_form_only_includes_typed_fields():
    form = {"views_1": "100", "likes_1": "", "views_2": ""}
    assert parse_metrics_form(form, [1, 2]) == {1: {"views": 100}}


def test_parse_metrics_form_multiple_fields_per_video():
    form = {"views_1": "100", "likes_1": "5", "comments_1": "2"}
    assert parse_metrics_form(form, [1]) == {1: {"views": 100, "likes": 5, "comments": 2}}


def test_parse_metrics_form_video_with_nothing_typed_is_absent():
    assert parse_metrics_form({}, [1, 2, 3]) == {}


# ---------- /metrics/new ----------

def test_metrics_new_get_returns_200(tmp_db):
    response = client.get("/metrics/new")
    assert response.status_code == 200


def test_post_metrics_new_records_snapshot_and_redirects(tmp_db):
    vid = db.add_video("Test", "youtube", "2026-01-01", path=tmp_db)
    response = client.post(
        "/metrics/new", data={f"views_{vid}": "82"}, follow_redirects=False,
    )
    assert response.status_code in (302, 303, 307)
    assert "updated=1" in response.headers["location"]

    history = db.get_video_history(vid, path=tmp_db)
    assert history[-1]["views"] == 82


def test_post_metrics_new_skips_videos_with_nothing_typed(tmp_db):
    v1 = db.add_video("A", "youtube", "2026-01-01", path=tmp_db)
    v2 = db.add_video("B", "youtube", "2026-01-01", path=tmp_db)
    response = client.post(
        "/metrics/new", data={f"views_{v1}": "50"}, follow_redirects=False,
    )
    assert "updated=1" in response.headers["location"]
    assert db.get_video_history(v2, path=tmp_db) == []


def test_metrics_new_shows_updated_count(tmp_db):
    response = client.get("/metrics/new?updated=3")
    assert "3" in response.text


# ---------- benchmark_class ----------

def test_benchmark_class_above_median_is_good():
    assert benchmark_class(100, 50) == "good"


def test_benchmark_class_below_median_is_bad():
    assert benchmark_class(10, 50) == "bad"


def test_benchmark_class_equal_median_is_neutral():
    assert benchmark_class(50, 50) == ""


def test_benchmark_class_missing_data_is_neutral():
    assert benchmark_class(None, 50) == ""
    assert benchmark_class(50, None) == ""


# ---------- the performance data behind the home ----------
# The ZP home doesn't render the strip; the numbers live in
# performance_rows / db.benchmark, pinned directly so the analytics
# discipline (same window for ranking and colouring) survives any skin.

def test_performance_rows_colours_against_the_same_window(tmp_preprod_db):
    v1 = db.add_video("Winner", "youtube", "2026-01-01", path=tmp_preprod_db)
    v2 = db.add_video("Loser", "youtube", "2026-01-01", path=tmp_preprod_db)
    db.record_metrics(v1, views=1000, captured_at="2026-01-08", path=tmp_preprod_db)
    db.record_metrics(v2, views=10, captured_at="2026-01-08", path=tmp_preprod_db)

    result = app_main.performance_rows(posted_within="all")
    classes = {r["title"]: r["css_class"] for r in result["rows"]}
    assert classes["Winner"] == "good"
    assert classes["Loser"] == "bad"


def test_performance_rows_respects_the_posted_window(tmp_preprod_db):
    old_date = (date.today() - timedelta(days=400)).isoformat()
    old_measured = (date.today() - timedelta(days=393)).isoformat()
    v_old = db.add_video("Old", "youtube", old_date, path=tmp_preprod_db)
    db.record_metrics(v_old, views=99999, captured_at=old_measured, path=tmp_preprod_db)

    titles = [r["title"] for r in app_main.performance_rows()["rows"]]
    assert "Old" not in titles          # default window: last 6 months
    titles_all = [r["title"] for r in app_main.performance_rows(posted_within="all")["rows"]]
    assert "Old" in titles_all


# ---------- /videos/{id} ----------

def test_video_detail_404s_for_missing_video(tmp_db):
    response = client.get("/videos/999")
    assert response.status_code == 404


def test_video_detail_shows_metadata(tmp_db):
    vid = db.add_video("Night Run", "youtube", "2025-09-29",
                       url="https://x", path=tmp_db)
    response = client.get(f"/videos/{vid}")
    assert response.status_code == 200
    assert "Night Run" in response.text
    assert "youtube" in response.text


def test_video_detail_shows_snapshot_history(tmp_db):
    vid = db.add_video("Night Run", "youtube", "2025-09-29", path=tmp_db)
    db.record_metrics(vid, views=82, captured_at="2026-07-29", path=tmp_db)
    response = client.get(f"/videos/{vid}")
    assert "82" in response.text


def test_video_detail_no_originating_pitch(tmp_db):
    vid = db.add_video("Night Run", "youtube", "2025-09-29", path=tmp_db)
    response = client.get(f"/videos/{vid}")
    assert "Not linked to a pitch" in response.text


def test_video_detail_shows_originating_pitch_when_linked(tmp_db):
    run_id = db.save_pitch_run(
        [{"number": n, "title": f"S{n}", "logline": f"L{n}.", "story_note": "n"} for n in range(1, 11)],
        path=tmp_db,
    )
    with db.connect(tmp_db) as conn:
        idea_id = conn.execute(
            "SELECT id FROM ideas WHERE run_id = ? AND number = 2", (run_id,)
        ).fetchone()[0]
    vid = db.add_video("S2 video", "tiktok", "2026-01-01", idea_id=idea_id, path=tmp_db)

    response = client.get(f"/videos/{vid}")
    assert "S2" in response.text
    assert "L2." in response.text


# ---------- /metrics/refresh/{video_id} and the refresh button ----------

def test_post_metrics_refresh_records_a_snapshot(tmp_db, monkeypatch):
    vid = db.add_video("Night Run", "youtube", "2025-09-29",
                       url="https://www.youtube.com/watch?v=abc12345678", path=tmp_db)
    monkeypatch.setattr(
        app_main.youtube, "fetch_video_stats",
        lambda video_id, api_key: {"views": 82, "likes": 5, "comments": 1},
    )
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    response = client.post(f"/metrics/refresh/{vid}", follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    assert "message=" in response.headers["location"]
    history = db.get_video_history(vid, path=tmp_db)
    assert history[-1]["views"] == 82


def test_post_metrics_refresh_404s_for_missing_video(tmp_db):
    response = client.post("/metrics/refresh/999")
    assert response.status_code == 404


def test_post_metrics_refresh_reports_failure_without_breaking(tmp_db, monkeypatch):
    vid = db.add_video("Night Run", "youtube", "2025-09-29",
                       url="https://www.youtube.com/watch?v=abc12345678", path=tmp_db)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    response = client.post(f"/metrics/refresh/{vid}", follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    assert db.get_video_history(vid, path=tmp_db) == []


def test_metrics_new_shows_refresh_message(tmp_db):
    response = client.get("/metrics/new?message=Refreshed+Night+Run")
    assert "Refreshed Night Run" in response.text


def test_metrics_new_shows_refresh_button_for_youtube(tmp_db):
    db.add_video("Night Run", "youtube", "2025-09-29",
                 url="https://www.youtube.com/watch?v=abc", path=tmp_db)
    response = client.get("/metrics/new")
    assert "Refresh" in response.text


def test_metrics_new_no_refresh_button_for_non_youtube(tmp_db):
    db.add_video("Some TikTok video", "tiktok", "2025-09-29", path=tmp_db)
    response = client.get("/metrics/new")
    # the page prose mentions Refresh; what must be absent is the button itself
    assert 'form="refresh-' not in response.text


# ---------- /videos/import/youtube ----------

def test_videos_new_shows_import_form(tmp_db):
    response = client.get("/videos/new")
    assert "Import" in response.text
    assert "handle" in response.text


def test_post_import_adds_videos_and_redirects(tmp_db, monkeypatch):
    monkeypatch.setattr(
        app_main.youtube, "import_channel_videos",
        lambda handle, api_key=None, db_path=None: {"ok": True, "added": 9},
    )

    response = client.post("/videos/import/youtube", data={"handle": "@someone"},
                           follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    assert "message=" in response.headers["location"]
    # the message is only visible on the workspace, not the landing
    assert response.headers["location"].startswith("/studio?")


def test_post_import_reports_failure_without_breaking(tmp_db, monkeypatch):
    monkeypatch.setattr(
        app_main.youtube, "import_channel_videos",
        lambda handle, api_key=None, db_path=None: {
            "ok": False, "error": "API key not valid", "added": 0,
        },
    )

    response = client.post("/videos/import/youtube", data={"handle": "@someone"},
                           follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    assert db.list_videos(path=tmp_db) == []


def test_post_import_requires_a_handle(tmp_db):
    response = client.post("/videos/import/youtube", data={"handle": "  "})
    assert response.status_code == 400


# ---------- /locations ----------

SAMPLE_SPACE = {
    "space": "narrow hallway with a door at the end",
    "light_sources": ["overhead practical"],
    "textures": ["scuffed paint"],
    "angles": ["low from the doorway"],
    "constraints": "tight, no wide lens",
}

CONCEPT_SHOTS = [
    {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "hallway",
     "desc": "low angle, he steps into frame", "light": "overhead practical"},
]


def test_locations_page_empty_state(tmp_preprod_db):
    response = client.get("/locations")
    assert response.status_code == 200
    assert "No locations yet" in response.text


def test_locations_page_lists_described_spaces(tmp_preprod_db):
    preprod.add_location("hallway", SAMPLE_SPACE, photo_count=3, path=tmp_preprod_db)
    response = client.get("/locations")
    assert "hallway" in response.text
    assert "narrow hallway" in response.text
    assert "overhead practical" in response.text


# ---------- /concepts ----------

def test_concepts_page_empty_state(tmp_preprod_db):
    response = client.get("/concepts")
    assert response.status_code == 200
    assert "No concepts yet" in response.text


def test_concepts_page_lists_concepts_with_shots(tmp_preprod_db):
    preprod.save_concept(
        {"title": "The Waiting", "hook": "a hand on the handle", "shots": CONCEPT_SHOTS},
        brand="antihero", path=tmp_preprod_db,
    )
    response = client.get("/concepts")
    # case-insensitive: the design uppercases titles, which isn't the
    # thing this test is about
    assert "the waiting" in response.text.lower()
    assert "a hand on the handle" in response.text
    assert "he steps into frame" in response.text


def test_concepts_page_shows_shoot_rate(tmp_preprod_db):
    ids = [
        preprod.save_concept({"title": f"C{n}", "shots": CONCEPT_SHOTS},
                             brand="antihero", path=tmp_preprod_db)
        for n in range(4)
    ]
    preprod.mark_shot(ids[0], path=tmp_preprod_db)
    response = client.get("/concepts")
    assert "Shot 1/4" in response.text


def test_post_mark_concept_shot_toggles_and_redirects(tmp_preprod_db):
    concept_id = preprod.save_concept(
        {"title": "The Waiting", "shots": CONCEPT_SHOTS}, brand="antihero", path=tmp_preprod_db,
    )
    response = client.post(f"/concepts/{concept_id}/shot", follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    assert preprod.get_concept(concept_id, path=tmp_preprod_db)["shot_done"] == 1

    client.post(f"/concepts/{concept_id}/shot", follow_redirects=False)
    assert preprod.get_concept(concept_id, path=tmp_preprod_db)["shot_done"] == 0


def test_post_mark_concept_shot_404s_for_missing_concept(tmp_preprod_db):
    assert client.post("/concepts/999/shot").status_code == 404


def test_post_generate_concept_creates_ideas(tmp_preprod_db, monkeypatch):
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    monkeypatch.setattr(
        app_main.shootgen, "generate_concept_ideas",
        lambda **kw: {"concept_ids": [1], "ideas": [{"title": "X"}]},
    )
    response = client.post("/concepts/generate",
                           data={"brand": "antihero", "spark": "a door", "mode": "ideas"},
                           follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "message=" in response.headers["location"]


def test_post_generate_concept_reports_failure_without_breaking(tmp_preprod_db, monkeypatch):
    def boom(**kw):
        raise ValueError("no locations described yet")

    monkeypatch.setattr(app_main.shootgen, "generate_concept_ideas", boom)
    response = client.post("/concepts/generate",
                           data={"brand": "antihero", "mode": "ideas"},
                           follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "message=" in response.headers["location"]


# ---------- two-stage concepts in the UI ----------

def test_post_generate_makes_ideas_not_one_concept(tmp_preprod_db, monkeypatch):
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    monkeypatch.setattr(
        app_main.shootgen, "generate_concept_ideas",
        lambda **kw: {"concept_ids": [1, 2, 3], "ideas": [{"title": "A"}] * 3},
    )
    response = client.post("/concepts/generate",
                           data={"brand": "antihero", "mode": "ideas"},
                           follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "message=" in response.headers["location"]


def test_post_shotlist_plans_a_chosen_idea(tmp_preprod_db, monkeypatch):
    concept_id = preprod.save_concept({"title": "Void Signal"}, brand="antihero",
                                      path=tmp_preprod_db)
    monkeypatch.setattr(
        app_main.shootgen, "generate_shot_list",
        lambda cid, **kw: {"concept_id": cid, "plan": {}, "warnings": []},
    )
    response = client.post(f"/concepts/{concept_id}/shotlist", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "message=" in response.headers["location"]


def test_post_shotlist_404s_for_missing_concept(tmp_preprod_db):
    assert client.post("/concepts/999/shotlist").status_code == 404


def test_post_shotlist_reports_failure_without_breaking(tmp_preprod_db, monkeypatch):
    concept_id = preprod.save_concept({"title": "T"}, brand="antihero", path=tmp_preprod_db)

    def boom(cid, **kw):
        raise Exception("model unavailable")

    monkeypatch.setattr(app_main.shootgen, "generate_shot_list", boom)
    response = client.post(f"/concepts/{concept_id}/shotlist", follow_redirects=False)
    assert response.status_code in (302, 303, 307)


def test_concepts_page_shows_shortlist_rate(tmp_preprod_db):
    ids = preprod.save_concept_ideas(
        [{"title": f"Idea {n}"} for n in range(4)], brand="antihero", path=tmp_preprod_db,
    )
    preprod.update_concept_shots(ids[0], {"shots": CONCEPT_SHOTS}, path=tmp_preprod_db)
    response = client.get("/concepts")
    assert "Planned 1/4" in response.text


def test_concepts_page_offers_shotlist_button_for_an_idea(tmp_preprod_db):
    preprod.save_concept({"title": "Void Signal"}, brand="antihero", path=tmp_preprod_db)
    response = client.get("/concepts")
    assert "Plan the shoot" in response.text


def test_concepts_page_no_shotlist_button_once_planned(tmp_preprod_db):
    concept_id = preprod.save_concept({"title": "Void Signal"}, brand="antihero",
                                      path=tmp_preprod_db)
    preprod.update_concept_shots(concept_id, {"shots": CONCEPT_SHOTS}, path=tmp_preprod_db)
    response = client.get("/concepts")
    assert "Plan the shoot" not in response.text


# ---------- navigation ----------
# Every screen was built and verified in isolation by typing its URL,
# which is exactly how a site ends up with no way to get between pages.
# Navigation is the shared rail now: every railed page must carry every
# rail destination, and the pages the rail doesn't list must still be
# reachable from somewhere (asserted below), or they quietly die.
#
# `/` is deliberately not in here: it's the marketing landing, served
# outside the app shell, so it carries no rail.

RAILED_PAGES = ["/studio", "/concepts", "/locations", "/characters", "/props",
                "/analytics", "/library"]
RAIL_DESTINATIONS = ["/studio", "/concepts", "/locations", "/characters",
                     "/props", "/library", "/analytics"]


@pytest.mark.parametrize("page", RAILED_PAGES)
def test_every_railed_page_carries_the_whole_rail(page, tmp_preprod_db):
    response = client.get(page)
    assert response.status_code == 200
    assert 'class="rail"' in response.text
    for target in RAIL_DESTINATIONS:
        assert f'href="{target}"' in response.text, f"{page} has no link to {target}"


def test_pages_off_the_rail_are_still_reachable(tmp_preprod_db):
    """/videos/new and /holds aren't rail items; they must be linked from
    somewhere on the railed surface or they become dead URLs."""
    assert 'href="/videos/new"' in client.get("/analytics").text
    assert 'href="/holds"' in client.get("/studio").text        # the pills


# ---------- /holds: the shadow-mode grading queue ----------

@pytest.fixture
def tmp_autonomy_db(tmp_preprod_db):
    from src import autonomy
    autonomy.init(tmp_preprod_db)
    return tmp_preprod_db


def test_holds_page_empty_state(tmp_autonomy_db):
    response = client.get("/holds")
    assert response.status_code == 200
    assert "Queue is clear" in response.text


def test_holds_page_shows_a_held_run_with_its_concept(tmp_autonomy_db):
    from src import autonomy
    concept_id = preprod.save_concept(
        {"title": "Terminal Ritual", "hook": "an eye, unblinking"},
        brand="antihero", path=tmp_autonomy_db,
    )
    autonomy.to_hold("zeropage", "shadow — grading only", concept_id=concept_id,
                     payload={"prompts": [{"tool": "KLING", "prompt": "the handle turns"}]},
                     path=tmp_autonomy_db)

    # /holds is brand-scoped now (BACKLOG #7): view as the hold's brand.
    client.cookies.set("brand", "zeropage")
    response = client.get("/holds")
    client.cookies.clear()
    assert "Terminal Ritual" in response.text
    assert "shadow — grading only" in response.text
    assert "the handle turns" in response.text
    assert "Would have posted it" in response.text


def test_resolving_a_hold_feeds_the_agreement_number(tmp_autonomy_db):
    from src import autonomy
    hold_id = autonomy.to_hold("zeropage", "shadow", path=tmp_autonomy_db)

    response = client.post(f"/holds/{hold_id}/resolve", data={"status": "approved"},
                           follow_redirects=False)
    assert response.status_code == 303

    assert autonomy.list_hold(status="held", path=tmp_autonomy_db) == []
    assert autonomy.evaluator_agreement(path=tmp_autonomy_db)["agreement"] == 1.0
    # and the page shows the number
    assert "100%" in client.get("/holds").text


def test_resolving_with_a_bad_status_is_a_400(tmp_autonomy_db):
    from src import autonomy
    hold_id = autonomy.to_hold("zeropage", "shadow", path=tmp_autonomy_db)
    response = client.post(f"/holds/{hold_id}/resolve", data={"status": "maybe"})
    assert response.status_code == 400


def test_promoting_a_channel_from_the_page(tmp_autonomy_db):
    from src import autonomy
    response = client.post("/channels/zeropage/autonomy", data={"autonomy": "queue"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert autonomy.get_channel("zeropage", path=tmp_autonomy_db)["autonomy"] == "queue"

    assert client.post("/channels/zeropage/autonomy",
                       data={"autonomy": "yolo"}).status_code == 400
    assert client.post("/channels/nope/autonomy",
                       data={"autonomy": "auto"}).status_code == 404


def test_kill_toggle_round_trip(tmp_autonomy_db, monkeypatch):
    from src import autonomy
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    client.post("/kill", follow_redirects=False)
    assert autonomy.killed(path=tmp_autonomy_db) is True
    assert "Kill switch is ON" in client.get("/holds").text

    client.post("/kill", follow_redirects=False)
    assert autonomy.killed(path=tmp_autonomy_db) is False


def test_grading_a_hold_writes_the_prompt_verdict_too(tmp_autonomy_db):
    """One tap grades both trust numbers: the run's hold row AND the
    credit gate's prompt_scores rows for that run."""
    from src import autonomy
    autonomy.log_prompt_scores("runX", [
        {"prompt": "p", "score": 9, "pass": True, "reason": "", "dims": {}}],
        path=tmp_autonomy_db)
    hold_id = autonomy.to_hold("zeropage", "shadow", payload={"run_id": "runX"},
                               path=tmp_autonomy_db)

    client.post(f"/holds/{hold_id}/resolve", data={"status": "rejected"},
                follow_redirects=False)

    gate = autonomy.prompt_gate_agreement(path=tmp_autonomy_db)
    assert gate["graded"] == 1
    assert gate["passed_but_rejected"] == 1   # the expensive-error counter moved


def test_note_form_writes_a_pending_correction(tmp_autonomy_db):
    from src import autonomy
    response = client.post("/holds/note", data={"note": "less neon, more silence"},
                           follow_redirects=False)
    assert response.status_code == 303
    [pending] = autonomy.pending_corrections(path=tmp_autonomy_db)
    assert pending["note"] == "less neon, more silence"

    client.post("/holds/note", data={"note": "  "}, follow_redirects=False)
    assert len(autonomy.pending_corrections(path=tmp_autonomy_db)) == 1  # blanks dropped


def test_video_detail_still_has_its_nav(tmp_preprod_db):
    vid = db.add_video("Night Run", "youtube", "2025-09-29", path=tmp_preprod_db)
    response = client.get(f"/videos/{vid}")
    assert 'href="/analytics"' in response.text


# ---------- photo upload ----------
# The pipeline gap: without this, photos only get in by dropping files
# into locations/<name>/ and running the CLI.

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_post_location_upload_saves_photos_and_describes(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.setattr(
        app_main.locations, "describe_location",
        lambda client, name, photos: {"space": f"{name} described from {len(photos)}"},
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    response = client.post(
        "/locations/upload",
        data={"name": "garage"},
        files=[("photos", ("a.png", TINY_PNG, "image/png")),
               ("photos", ("b.png", TINY_PNG, "image/png"))],
        follow_redirects=False,
    )

    assert response.status_code in (302, 303, 307)
    saved = preprod.get_location_by_name("garage", path=tmp_preprod_db)
    assert saved is not None
    assert saved["photo_count"] == 2
    assert "described from 2" in saved["description"]["space"]
    assert (tmp_path / "locations" / "garage" / "a.png").exists()


def test_post_location_upload_requires_a_name(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    response = client.post(
        "/locations/upload",
        data={"name": "   "},
        files=[("photos", ("a.png", TINY_PNG, "image/png"))],
    )
    assert response.status_code == 400


def test_post_location_upload_requires_a_photo(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    response = client.post("/locations/upload", data={"name": "garage"})
    assert response.status_code == 400


def test_post_location_upload_reports_failure_without_breaking(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")

    def boom(client, name, photos):
        raise Exception("vision unavailable")

    monkeypatch.setattr(app_main.locations, "describe_location", boom)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    response = client.post(
        "/locations/upload",
        data={"name": "garage"},
        files=[("photos", ("a.png", TINY_PNG, "image/png"))],
        follow_redirects=False,
    )
    assert response.status_code in (302, 303, 307)
    assert preprod.get_location_by_name("garage", path=tmp_preprod_db) is None


def test_post_location_upload_sanitises_the_space_name(tmp_preprod_db, tmp_path, monkeypatch):
    """A name becomes a directory, so it can't escape the locations dir."""
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.setattr(
        app_main.locations, "describe_location",
        lambda client, name, photos: {"space": "x"},
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    client.post(
        "/locations/upload",
        data={"name": "../../etc/evil"},
        files=[("photos", ("a.png", TINY_PNG, "image/png"))],
        follow_redirects=False,
    )
    assert not (tmp_path / "etc").exists()
    assert not (tmp_path.parent / "etc").exists()


# ---------- serving location photos ----------

def test_location_photo_is_served(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    space = tmp_path / "locations" / "garage"
    space.mkdir(parents=True)
    (space / "a.png").write_bytes(TINY_PNG)

    response = client.get("/locations/garage/photo/a.png")
    assert response.status_code == 200
    assert response.content == TINY_PNG


def test_location_photo_404s_when_missing(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    assert client.get("/locations/garage/photo/nope.png").status_code == 404


def test_location_photo_refuses_to_escape_the_locations_dir(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    (tmp_path / "locations").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("not yours")

    for attempt in ["/locations/garage/photo/..%2F..%2Fsecret.txt",
                    "/locations/..%2F..%2Fetc/photo/passwd"]:
        assert client.get(attempt).status_code in (400, 404)


def test_location_photos_listed_on_the_page(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    space = tmp_path / "locations" / "garage"
    space.mkdir(parents=True)
    (space / "a.png").write_bytes(TINY_PNG)
    (space / "b.png").write_bytes(TINY_PNG)
    preprod.add_location("garage", SAMPLE_SPACE, photo_count=2, path=tmp_preprod_db)

    response = client.get("/locations")
    assert "/locations/garage/photo/a.png" in response.text
    assert "/locations/garage/photo/b.png" in response.text


# ---------- generate: full concept vs ideas ----------

def test_post_generate_returns_a_full_concept_by_default(tmp_preprod_db, monkeypatch):
    """The main button behaves like the original generator: one
    complete concept, shot list included, in one go."""
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    called = {}

    def fake(**kw):
        called["full"] = True
        return {"concept_id": 1, "concept": {"title": "Void Signal"}, "warnings": []}

    monkeypatch.setattr(app_main.shootgen, "generate_concept", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    response = client.post("/concepts/generate", data={"brand": "antihero"},
                           follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert called.get("full") is True


def test_generate_passes_only_the_picked_cast(tmp_preprod_db, monkeypatch):
    """The picker: checked characters/props become the {cast} block; the
    unchecked stay out of it."""
    from src import entities
    entities.init(tmp_preprod_db)
    mike = entities.add_character("Mike — on camera", role="protagonist",
                                  path=tmp_preprod_db)
    entities.add_character("Guest — bartender", path=tmp_preprod_db)
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    seen = {}

    def fake(**kw):
        seen["cast"] = kw.get("cast")
        return {"concept_id": 1, "concept": {"title": "X"}, "warnings": []}

    monkeypatch.setattr(app_main.shootgen, "generate_concept", fake)

    client.post("/concepts/generate",
                data={"brand": "antihero", "characters": str(mike)},
                follow_redirects=False)

    assert "Mike — on camera" in seen["cast"]
    assert "Guest — bartender" not in seen["cast"]


def test_generate_with_nothing_picked_keeps_the_old_behavior(tmp_preprod_db, monkeypatch):
    """No picks -> cast=None -> generate_concept's own 'everything on
    file' default, exactly as before the picker existed."""
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    seen = {}

    def fake(**kw):
        seen["cast"] = kw.get("cast")
        return {"concept_id": 1, "concept": {"title": "X"}, "warnings": []}

    monkeypatch.setattr(app_main.shootgen, "generate_concept", fake)

    client.post("/concepts/generate", data={"brand": "antihero"},
                follow_redirects=False)

    assert seen["cast"] is None


def test_concepts_page_shows_the_picker_when_cast_exists(tmp_preprod_db):
    from src import entities
    entities.init(tmp_preprod_db)
    entities.add_character("Mike — on camera", path=tmp_preprod_db)
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)

    response = client.get("/concepts")
    assert 'name="characters"' in response.text
    assert "Mike — on camera" in response.text


def test_post_generate_ideas_when_asked(tmp_preprod_db, monkeypatch):
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    called = {}

    def fake(**kw):
        called["ideas"] = True
        return {"concept_ids": [1, 2], "ideas": [{"title": "A"}, {"title": "B"}]}

    monkeypatch.setattr(app_main.shootgen, "generate_concept_ideas", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    response = client.post("/concepts/generate", data={"brand": "antihero", "mode": "ideas"},
                           follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert called.get("ideas") is True


# ---------- thumbnails ----------

def _real_jpeg(width=1200, height=900):
    from io import BytesIO

    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (width, height), (40, 40, 48)).save(buf, format="JPEG")
    return buf.getvalue()


def test_thumbnail_is_much_smaller_than_the_original(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.setattr(app_main, "THUMB_DIR", tmp_path / "thumbs")
    space = tmp_path / "locations" / "garage"
    space.mkdir(parents=True)
    original = _real_jpeg()
    (space / "big.jpg").write_bytes(original)

    response = client.get("/locations/garage/photo/big.jpg?thumb=1")
    assert response.status_code == 200
    assert len(response.content) < len(original) / 4


def test_full_size_is_still_available(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.setattr(app_main, "THUMB_DIR", tmp_path / "thumbs")
    space = tmp_path / "locations" / "garage"
    space.mkdir(parents=True)
    original = _real_jpeg()
    (space / "big.jpg").write_bytes(original)

    assert len(client.get("/locations/garage/photo/big.jpg").content) == len(original)


def test_thumbnail_falls_back_to_the_original_if_it_cannot_be_made(tmp_preprod_db, tmp_path, monkeypatch):
    """A file Pillow can't read should still render, not 500."""
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.setattr(app_main, "THUMB_DIR", tmp_path / "thumbs")
    space = tmp_path / "locations" / "garage"
    space.mkdir(parents=True)
    (space / "broken.jpg").write_bytes(b"not actually a jpeg")

    assert client.get("/locations/garage/photo/broken.jpg?thumb=1").status_code == 200


def test_page_asks_for_thumbnails(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    space = tmp_path / "locations" / "garage"
    space.mkdir(parents=True)
    (space / "a.jpg").write_bytes(_real_jpeg())
    preprod.add_location("garage", SAMPLE_SPACE, photo_count=1, path=tmp_preprod_db)

    assert "?thumb=1" in client.get("/locations").text


# ---------- one screen: photos, settings, generate, results ----------

def test_locations_page_has_the_upload_form(tmp_preprod_db):
    """The new skin moved the upload into /locations' add dialog; the
    concepts screen is generation-only now."""
    response = client.get("/locations")
    assert 'action="/locations/upload"' in response.text
    assert 'enctype="multipart/form-data"' in response.text


def test_locations_page_shows_space_thumbnails(tmp_preprod_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "LOCATIONS_DIR", tmp_path / "locations")
    space = tmp_path / "locations" / "garage"
    space.mkdir(parents=True)
    (space / "a.jpg").write_bytes(_real_jpeg())
    preprod.add_location("garage", SAMPLE_SPACE, photo_count=1, path=tmp_preprod_db)

    response = client.get("/locations")
    assert "/locations/garage/photo/a.jpg?thumb=1" in response.text


def test_concepts_page_has_a_pov_toggle(tmp_preprod_db):
    preprod.add_location("garage", SAMPLE_SPACE, path=tmp_preprod_db)
    response = client.get("/concepts")
    assert 'name="use_pov"' in response.text


def test_generate_honours_pov_off(tmp_preprod_db, monkeypatch):
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    seen = {}

    def fake(**kw):
        seen["use_pov"] = kw.get("use_pov")
        return {"concept_id": 1, "concept": {"title": "X"}, "warnings": []}

    monkeypatch.setattr(app_main.shootgen, "generate_concept", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    client.post("/concepts/generate", data={"brand": "antihero"}, follow_redirects=False)
    assert seen["use_pov"] is False, "unchecked box must mean the camera is off"

    client.post("/concepts/generate", data={"brand": "antihero", "use_pov": "on"},
                follow_redirects=False)
    assert seen["use_pov"] is True


def test_concept_warnings_are_visible_on_the_page(tmp_preprod_db):
    """Stored isn't enough -- you have to be able to see it."""
    preprod.save_concept(
        {"title": "Void Signal", "shots": CONCEPT_SHOTS}, brand="antihero",
        warnings=["shot 1: location 'rooftop helipad' is not a described space"],
        path=tmp_preprod_db,
    )
    response = client.get("/concepts")
    assert "rooftop helipad" in response.text


def test_studio_renders_with_videos_logged_but_unmeasured(tmp_preprod_db):
    """The old empty-state distinction lived in the strip the ZP home
    no longer renders; what must survive is that the page renders with
    data in every state and the video is correctly absent at 7 days."""
    vid = db.add_video("Night Run", "youtube", "2025-09-29", path=tmp_preprod_db)
    db.record_metrics(vid, views=82, captured_at="2026-07-29", path=tmp_preprod_db)

    response = client.get("/studio?posted_within=all&at_days=7")
    assert response.status_code == 200
    assert app_main.performance_rows(posted_within="all")["rows"] == []


def test_generate_ideas_records_the_pov_choice(tmp_preprod_db, monkeypatch):
    """
    The camera choice is made at idea time but needed at shot-list time,
    so it has to be stored on the concept rather than re-defaulted.
    """
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    seen = {}
    monkeypatch.setattr(
        app_main.shootgen, "generate_concept_ideas",
        lambda **kw: seen.update(use_pov=kw.get("use_pov")) or
        {"concept_ids": [1], "ideas": [{"title": "Idea"}]},
    )
    client.post("/concepts/generate", data={"brand": "antihero", "mode": "ideas"},
                follow_redirects=False)   # checkbox absent -> POV off
    assert seen["use_pov"] is False


# ---------- /analytics ----------

def test_analytics_page_renders_with_tiles_and_bars(tmp_db):
    v1 = db.add_video("Big", "youtube", "2026-01-01", path=tmp_db)
    v2 = db.add_video("Small", "youtube", "2026-01-02", path=tmp_db)
    db.record_metrics(v1, views=1000, likes=10, captured_at="2026-01-08", path=tmp_db)
    db.record_metrics(v2, views=250, likes=5, captured_at="2026-01-08", path=tmp_db)

    response = client.get("/analytics")
    assert response.status_code == 200
    assert "1,250" in response.text            # total views tile
    assert 'class="fill"' in response.text     # the reskinned bar
    assert 'width:100.0%' in response.text     # Big is the max
    assert 'width:25.0%' in response.text      # Small scaled against it


# ---------- /library ----------

class LibraryFakeConn:
    """Just enough psycopg surface for the library routes."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        conn = self

        class _Cursor:
            rowcount = len(conn.rows)

            def fetchall(self):
                return conn.rows

        return _Cursor()

    def commit(self):
        pass

    def close(self):
        self.closed = True


def test_library_page_lists_sources(monkeypatch):
    conn = LibraryFakeConn(rows=[("brief.txt", "personal_brand", None, 1, "2026-07-31")])
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    response = client.get("/library")
    assert response.status_code == 200
    assert "brief.txt" in response.text
    assert "personal_brand" in response.text
    assert conn.closed        # no route may leak a connection


def test_library_page_degrades_when_store_is_down():
    # autouse fixture already makes connect() raise
    response = client.get("/library")
    assert response.status_code == 200
    assert "unavailable" in response.text.lower()


def test_library_search_renders_scored_results(monkeypatch):
    # sources list empty; the query itself is patched separately below.
    # make_client must be patched too -- unpatched it only succeeds on a
    # machine that happens to have GEMINI_API_KEY, which is how this test
    # passed locally and failed in CI.
    conn = LibraryFakeConn(rows=[])
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    monkeypatch.setattr(app_main.rag, "make_client", lambda: object())
    monkeypatch.setattr(app_main.rag, "query",
                        lambda text, client, conn, k=5, domain=None, project=None:
                        [{"source": "notes.md", "chunk": "one image, one turn",
                          "domain": "cinematography", "project": None,
                          "source_ref": None, "score": 0.8}])
    response = client.get("/library?q=structure")
    assert response.status_code == 200
    assert "one image, one turn" in response.text
    assert "0.8" in response.text


def test_library_ingest_posts_to_the_store(monkeypatch):
    conn = LibraryFakeConn()
    recorded = {}
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    monkeypatch.setattr(app_main.rag, "init_store", lambda c: None)
    monkeypatch.setattr(app_main.rag, "make_client", lambda: object())

    def fake_ingest(records, client, c):
        recorded.update(records[0])
        return 3

    monkeypatch.setattr(app_main.rag, "ingest_records", fake_ingest)
    response = client.post("/library/ingest",
                           data={"source": "my-notes", "domain": "cinematography",
                                 "text": "night exteriors want practicals"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "3" in response.headers["location"]      # "stored 3 chunks" message
    assert recorded["source"] == "my-notes"
    assert recorded["domain"] == "cinematography"


def test_library_ingest_requires_the_domain_tag():
    response = client.post("/library/ingest",
                           data={"source": "x", "domain": "", "text": "words"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "domain" in response.headers["location"].lower()


def test_library_delete_removes_one_source(monkeypatch):
    conn = LibraryFakeConn(rows=[("gone",)])
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    response = client.post("/library/delete",
                           data={"source": "old-notes.txt"}, follow_redirects=False)
    assert response.status_code == 303
    deletes = [p for s, p in conn.executed if s.startswith("DELETE")]
    assert ("old-notes.txt",) in deletes


def test_clean_title_strips_hashtags():
    assert app_main.clean_title("Blonde boy #hairstyle #haircolor") == "Blonde boy"
    assert app_main.clean_title("Ducati Engine Cleaning #ducati") == "Ducati Engine Cleaning"
    assert app_main.clean_title("Night Run") == "Night Run"


def test_clean_title_keeps_a_title_that_is_only_hashtags():
    # stripping everything would leave a blank row; the raw title is
    # better than no title
    assert app_main.clean_title("#shorts #fyp") == "#shorts #fyp"


def test_analytics_page_shows_cleaned_titles(tmp_db):
    vid = db.add_video("Margarita Recipe #cocktail #margarita #fyp",
                       "youtube", "2026-01-01", path=tmp_db)
    db.record_metrics(vid, views=100, captured_at="2026-01-08", path=tmp_db)
    response = client.get("/analytics")
    assert "Margarita Recipe" in response.text
    assert "#cocktail" not in response.text


def test_metrics_new_still_works_as_an_alias(tmp_db):
    response = client.get("/metrics/new?updated=3")
    assert response.status_code == 200
    assert "3" in response.text


def test_post_metrics_redirects_to_analytics(tmp_db):
    vid = db.add_video("T", "youtube", "2026-01-01", path=tmp_db)
    response = client.post("/metrics/new", data={f"views_{vid}": "5"},
                           follow_redirects=False)
    assert "/analytics?updated=1" in response.headers["location"]


# ---------- the machine-readable growth surface ----------
# These files exist for crawlers, so nothing in the app renders them and
# a regression is invisible until citations stop. Assert the bytes.

def test_robots_allows_the_ai_crawlers_by_name():
    response = client.get("/robots.txt")
    assert response.status_code == 200
    for bot in ("GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended"):
        assert f"User-agent: {bot}" in response.text


def test_robots_keeps_the_app_out_of_the_index():
    response = client.get("/robots.txt")
    assert "Disallow: /studio" in response.text
    assert "Disallow: /analytics" in response.text
    assert "Sitemap:" in response.text


def test_llms_txt_is_served_as_markdown_with_the_capabilities():
    """The concrete capabilities are the citable part -- a model asked
    what this does should answer with specifics, not adjectives."""
    response = client.get("/llms.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# Zero Page AI Studio" in response.text
    assert "real and AI shots" in response.text
    assert "Seedance" in response.text          # the platform breadth claim
    assert "learns from what performs" in response.text.lower() or \
        "analytics" in response.text


def test_sitemap_lists_the_public_page_only():
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "<urlset" in response.text
    assert "/studio" not in response.text


def test_landing_carries_the_jsonld_graph():
    response = client.get("/")
    assert 'application/ld+json' in response.text
    assert '"@type": "SoftwareApplication"' in response.text
    assert '"@type": "Organization"' in response.text


def test_landing_has_a_canonical_and_a_description():
    response = client.get("/")
    assert 'rel="canonical"' in response.text
    assert 'name="description"' in response.text


def test_app_pages_are_noindex(tmp_preprod_db):
    """The workspace is the product, not content. Indexing it splits the
    ranking signal off the one page that should carry it."""
    for page in ("/studio", "/concepts", "/analytics", "/library"):
        assert "noindex" in client.get(page).text, page


def test_schema_uses_the_configured_site_url(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://example.test/")
    graph = seo.homepage_schema()
    assert graph["@graph"][0]["@id"] == "https://example.test/#org"
    assert "https://example.test/sitemap.xml" in seo.robots_txt()


# ---------- the assistant ----------

def test_route_intent_prefers_an_explicit_chip():
    assert app_main.route_intent("cut it now", explicit="ideas") == "ideas"


def test_route_intent_reads_free_text():
    assert app_main.route_intent("plan that one") == "plan"
    assert app_main.route_intent("storyboard this") == "plan"
    assert app_main.route_intent("add a room") == "room"
    assert app_main.route_intent("give me a full concept for the garage") == "concept"


def test_route_intent_falls_back_to_one_concept():
    """An unparseable ask must not spend a generation on the wrong
    stage; concept is what "describe an idea, hit generate" means --
    one fully-formed result for exactly what was typed, not a batch to
    sift through."""
    assert app_main.route_intent("") == "concept"
    assert app_main.route_intent("something about a wrench") == "concept"


def test_assistant_generates_one_concept_from_typed_text(tmp_preprod_db, monkeypatch):
    preprod.add_location("garage", {"space": "garage"}, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())

    seen = {}

    def fake_concept(**kwargs):
        seen.update(kwargs)
        return {"concept_id": 1, "concept": {"title": "Gearing Up"}, "warnings": []}

    monkeypatch.setattr(app_main.shootgen, "generate_concept", fake_concept)
    response = client.post("/studio/assist", data={"text": "gearing up ritual"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert seen["spark"] == "gearing up ritual"
    assert 'Generated "Gearing Up"' in unquote(response.headers["location"])


def test_assistant_deals_ideas_when_explicitly_asked(tmp_preprod_db, monkeypatch):
    """The batch stage is still reachable -- either the chip's explicit
    intent or plural phrasing ("ideas", "options", "slate") -- it's just
    no longer where an unmarked ask lands by default."""
    preprod.add_location("garage", {"space": "garage"}, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())

    seen = {}

    def fake_ideas(**kwargs):
        seen.update(kwargs)
        return {"ideas": [{"title": "A"}, {"title": "B"}]}

    monkeypatch.setattr(app_main.shootgen, "generate_concept_ideas", fake_ideas)
    response = client.post(
        "/studio/assist",
        data={"text": "gearing up ritual", "intent": "ideas"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert seen["spark"] == "gearing up ritual"
    assert "Dealt 2 ideas" in unquote(response.headers["location"])


def test_assistant_folds_ingredients_and_platforms_into_the_spark(tmp_preprod_db, monkeypatch):
    """Tray chips genuinely steer the generation: their labels ride into
    the spark, which reaches both the RAG query and the prompt."""
    preprod.add_location("garage", {"space": "garage"}, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())

    seen = {}

    def fake_ideas(**kwargs):
        seen.update(kwargs)
        return {"ideas": [{"title": "A"}]}

    monkeypatch.setattr(app_main.shootgen, "generate_concept_ideas", fake_ideas)
    client.post("/studio/assist", data={
        "text": "night ritual",
        "intent": "ideas",
        "ingredients": "room: garage, clip: A037_C004.mov",
        "platforms": "VEO, WAN",
    }, follow_redirects=False)
    assert "night ritual" in seen["spark"]
    assert "Ground on: room: garage, clip: A037_C004.mov" in seen["spark"]
    assert "Preferred AI platforms: VEO, WAN" in seen["spark"]


def test_assistant_ingredients_alone_still_make_a_spark(tmp_preprod_db, monkeypatch):
    """Chips selected with an empty text box are still a real spark --
    not None with the grounding silently dropped."""
    preprod.add_location("garage", {"space": "garage"}, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())

    seen = {}

    def fake_ideas(**kwargs):
        seen.update(kwargs)
        return {"ideas": [{"title": "A"}]}

    monkeypatch.setattr(app_main.shootgen, "generate_concept_ideas", fake_ideas)
    client.post("/studio/assist", data={"intent": "ideas", "ingredients": "room: garage"},
                follow_redirects=False)
    assert seen["spark"] == "Ground on: room: garage"


def test_assistant_plans_the_most_recent_unplanned_idea(tmp_preprod_db, monkeypatch):
    preprod.add_location("garage", {"space": "garage"}, path=tmp_preprod_db)
    preprod.save_concept_ideas(
        [{"title": "Older", "hook": "h", "logline": "l"},
         {"title": "Newer", "hook": "h", "logline": "l"}],
        brand="antihero", path=tmp_preprod_db,
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())

    planned = {}

    def fake_shot_list(concept_id, **kwargs):
        planned["id"] = concept_id
        return {"warnings": []}

    monkeypatch.setattr(app_main.shootgen, "generate_shot_list", fake_shot_list)
    response = client.post("/studio/assist", data={"intent": "plan"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "Planned" in unquote(response.headers["location"])
    assert planned["id"] is not None


def test_assistant_reports_a_failed_generation_without_breaking(tmp_preprod_db, monkeypatch):
    preprod.add_location("garage", {"space": "garage"}, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())

    def boom(**kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(app_main.shootgen, "generate_concept", boom)
    response = client.post("/studio/assist", data={"text": "anything"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "Could not generate" in unquote(response.headers["location"])
    assert client.get("/studio").status_code == 200


def test_assistant_without_an_api_key_says_so(tmp_preprod_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    response = client.post("/studio/assist", data={"text": "ideas please"},
                           follow_redirects=False)
    assert "GEMINI_API_KEY" in response.headers["location"]


# ---------- inline actions land back on the canvas ----------

def test_mark_shot_from_the_studio_returns_to_the_studio(tmp_preprod_db):
    preprod.add_location("garage", {"space": "garage"}, path=tmp_preprod_db)
    cid = preprod.save_concept(
        {"title": "T", "hook": "h", "logline": "l", "shots": []},
        brand="antihero", path=tmp_preprod_db,
    )
    response = client.post(f"/concepts/{cid}/shot", data={"next": "/studio"},
                           follow_redirects=False)
    assert response.headers["location"] == "/studio"


def test_mark_shot_without_next_still_returns_to_concepts(tmp_preprod_db):
    preprod.add_location("garage", {"space": "garage"}, path=tmp_preprod_db)
    cid = preprod.save_concept(
        {"title": "T", "hook": "h", "logline": "l", "shots": []},
        brand="antihero", path=tmp_preprod_db,
    )
    response = client.post(f"/concepts/{cid}/shot", follow_redirects=False)
    assert response.headers["location"] == "/concepts"


def test_next_refuses_to_leave_the_site(tmp_preprod_db):
    """`next` on a form is an open redirect waiting to happen."""
    assert app_main.safe_next("https://evil.test", "/concepts") == "/concepts"
    assert app_main.safe_next("//evil.test", "/concepts") == "/concepts"
    assert app_main.safe_next("/studio", "/concepts") == "/studio"


# ---------- platform dispatch on metrics refresh ----------

def test_post_metrics_refresh_dispatches_instagram(tmp_db, monkeypatch):
    """An Instagram row refreshes through instagram.py, the same shape
    YouTube already has -- one dispatch on the stored platform."""
    vid = db.add_video("Reel", "instagram", "2026-08-01",
                       url="ig://17912345678901234", path=tmp_db)

    seen = {}

    def fake_refresh(video, token=None, db_path=None):
        seen.update({"video_id": video["id"], "token": token})
        return {"ok": True, "views": 77, "likes": 1, "comments": 0,
                "saves": 0, "shares": 0}

    monkeypatch.setattr(app_main.instagram, "refresh_metrics_for_video", fake_refresh)
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    response = client.post(f"/metrics/refresh/{vid}", follow_redirects=False)
    assert response.status_code == 303
    assert seen["video_id"] == vid
    assert seen["token"] == "tok"
    assert "77" in unquote(response.headers["location"])


def test_metrics_page_offers_refresh_for_instagram(tmp_db):
    db.add_video("Reel", "instagram", "2026-08-01", path=tmp_db)
    response = client.get("/metrics/new")
    assert 'form="refresh-' in response.text


def test_studio_workflow_library_shows_real_rows(tmp_preprod_db):
    """The home's Workflow tabs read the DB, not the design mockup: a
    row added to any of the three tables appears by name."""
    from src import entities
    entities.init(tmp_preprod_db)
    preprod.add_location("garage", {"space": "a low-ceilinged garage"},
                         photo_count=2, path=tmp_preprod_db)
    entities.add_character("Mike — on camera", role="protagonist",
                           path=tmp_preprod_db)
    entities.add_prop("Ducati Panigale V2", category="vehicle",
                      path=tmp_preprod_db)

    response = client.get("/studio")
    assert "garage" in response.text
    assert "Mike — on camera" in response.text
    assert "Ducati Panigale V2" in response.text
    assert "DESCRIBED" in response.text          # the described-room badge
    assert "The Garage" not in response.text     # mockup content is gone


def test_studio_home_renders_empty_without_mock_content(tmp_preprod_db):
    """A fresh clone shows the add-cards and placeholder frames, not the
    design mockup's invented rooms and props."""
    from src import entities
    entities.init(tmp_preprod_db)
    response = client.get("/studio")
    assert response.status_code == 200
    assert "＋ New character" in response.text
    assert "Juno Bar" not in response.text
    assert "Blackmagic 6K" not in response.text

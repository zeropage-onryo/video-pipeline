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


@pytest.fixture
def tmp_dev_db(tmp_preprod_db):
    """tmp_preprod_db plus what the Dev Studio tabs read: the autonomy
    tables (Stats/Settings) and the eval store (Grade/Dataset)."""
    from src import autonomy, evalstore, settings
    autonomy.init(tmp_preprod_db)
    evalstore.init(tmp_preprod_db)
    settings.init(tmp_preprod_db)
    return tmp_preprod_db


def test_root_serves_the_landing_page_not_the_workspace(tmp_db):
    """`/` is the marketing front door and the only indexed page; the
    workspace is /studio."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Pitch runs" not in response.text      # not the workspace canvas
    assert "/studio" in response.text             # the landing's call to action


def test_studio_returns_200(tmp_dev_db):
    response = client.get("/studio")
    assert response.status_code == 200


def test_studio_is_the_dev_studio_shell(tmp_dev_db):
    """/studio is the one consolidated dev page now: a tab bar over
    Stats / Grade / RAG Library / Settings / Dataset, on the legacy
    rail. Strictly stats + system improvement -- no composer."""
    response = client.get("/studio")
    assert "Dev Studio" in response.text
    for tab in ("stats", "grade", "library", "settings", "dataset"):
        assert f"/studio?tab={tab}" in response.text, tab
    assert 'class="rail"' in response.text
    assert 'action="/studio/assist"' not in response.text


def test_stats_tab_shows_the_five_pipeline_metrics(tmp_dev_db):
    """The five numbers that used to live on /ui's Concept tab render
    here now, server-side, next to the retrieval-eval instruments."""
    text = client.get("/studio?tab=stats").text
    for label in ("Shortlist rate", "Shoot rate", "Evaluator agreement",
                  "Gate agreement", "First-try pass"):
        assert label in text, label
    assert "evals_dev.js" in text
    assert "GOLDEN SET" in text


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


def test_asset_pages_redirect_to_ui():
    """Asset building lives on /ui's Assets view now; the old console
    URLs land there rather than 404ing or rendering stale content."""
    for page in ("/assets", "/locations", "/characters", "/props"):
        response = client.get(page, follow_redirects=False)
        assert response.status_code == 308, page
        assert response.headers["location"] == "/ui", page


# ---------- /concepts (redirect) + the Grade tab ----------

def test_concepts_url_redirects_to_the_grade_tab():
    response = client.get("/concepts", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/studio?tab=grade"


def test_concepts_redirect_forwards_the_message():
    """Every legacy `next=/concepts` POST route still lands its message
    somewhere visible."""
    response = client.get("/concepts?message=Recorded", follow_redirects=False)
    assert response.headers["location"] == "/studio?tab=grade&message=Recorded"


def test_grade_tab_shows_a_drawn_concept(tmp_dev_db):
    cid = preprod.save_concept(
        {"title": "The Waiting", "hook": "a hand on the handle", "shots": CONCEPT_SHOTS},
        brand="antihero", path=tmp_dev_db,
    )
    text = client.get(f"/studio?tab=grade&mode=shot&concept_id={cid}").text
    assert "The Waiting" in text
    assert "a hand on the handle" in text
    assert "TEACH THIS IDEA" in text
    assert "Grade taste + perf" in text


def test_stats_tab_shows_shoot_rate(tmp_dev_db):
    ids = [
        preprod.save_concept({"title": f"C{n}", "shots": CONCEPT_SHOTS},
                             brand="antihero", path=tmp_dev_db)
        for n in range(4)
    ]
    preprod.mark_shot(ids[0], path=tmp_dev_db)
    response = client.get("/studio?tab=stats")
    assert "Shoot rate · 1/4" in response.text


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


def test_stats_tab_shows_shortlist_rate(tmp_dev_db):
    ids = preprod.save_concept_ideas(
        [{"title": f"Idea {n}"} for n in range(4)], brand="antihero", path=tmp_dev_db,
    )
    preprod.update_concept_shots(ids[0], {"shots": CONCEPT_SHOTS}, path=tmp_dev_db)
    response = client.get("/studio?tab=stats")
    assert "Shortlist rate · 1/4" in response.text


# ---------- navigation ----------
# Every screen was built and verified in isolation by typing its URL,
# which is exactly how a site ends up with no way to get between pages.
# Navigation is the shared rail now: every railed page must carry every
# rail destination, and the pages the rail doesn't list must still be
# reachable from somewhere (asserted below), or they quietly die.
#
# `/` is deliberately not in here: it's the marketing landing, served
# outside the app shell, so it carries no rail.

RAILED_PAGES = ["/studio", "/analytics", "/winners"]
RAIL_DESTINATIONS = ["/studio", "/ui", "/analytics", "/winners"]


@pytest.mark.parametrize("page", RAILED_PAGES)
def test_every_railed_page_carries_the_whole_rail(page, tmp_dev_db):
    response = client.get(page)
    assert response.status_code == 200
    assert 'class="rail"' in response.text
    for target in RAIL_DESTINATIONS:
        assert f'href="{target}"' in response.text, f"{page} has no link to {target}"


def test_pages_off_the_rail_are_still_reachable(tmp_dev_db):
    """/videos/new isn't a rail item; it must be linked from somewhere
    on the railed surface or it becomes a dead URL."""
    assert 'href="/videos/new"' in client.get("/analytics").text


# ---------- /holds: retired page; the controls live elsewhere ----------
# Grading (approve/reject/post) is /ui's Pipeline view via /api/holds;
# the channel/kill/note controls are the Dev Studio's Settings tab.

@pytest.fixture
def tmp_autonomy_db(tmp_preprod_db):
    from src import autonomy, settings
    autonomy.init(tmp_preprod_db)
    settings.init(tmp_preprod_db)
    return tmp_preprod_db


def test_holds_page_redirects_to_ui():
    response = client.get("/holds", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/ui"


def test_settings_tab_carries_the_autonomy_controls(tmp_autonomy_db):
    text = client.get("/studio?tab=settings").text
    assert 'action="/kill"' in text
    assert 'action="/holds/note"' in text
    assert 'action="/channels/zeropage/autonomy"' in text
    assert 'action="/channels/antihero/autonomy"' in text


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
    response = client.post("/kill", follow_redirects=False)
    assert response.headers["location"].startswith("/studio?tab=settings")
    assert autonomy.killed(path=tmp_autonomy_db) is True
    assert "Kill switch is ON" in client.get("/studio?tab=settings").text

    client.post("/kill", follow_redirects=False)
    assert autonomy.killed(path=tmp_autonomy_db) is False


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
# Creation moved to the always-on /api/assets/* routes (tested in
# test_api.py); what stays here is the photo-serving surface.

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


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




# ---------- one screen: photos, settings, generate, results ----------







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




def test_studio_renders_with_videos_logged_but_unmeasured(tmp_dev_db):
    """The old empty-state distinction lived in the strip the ZP home
    no longer renders; what must survive is that the page renders with
    data in every state and the video is correctly absent at 7 days."""
    vid = db.add_video("Night Run", "youtube", "2025-09-29", path=tmp_dev_db)
    db.record_metrics(vid, views=82, captured_at="2026-07-29", path=tmp_dev_db)

    response = client.get("/studio")
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


def test_library_url_redirects_into_the_tab():
    response = client.get("/library?q=light&domain=cinematography", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/studio?tab=library&q=light&domain=cinematography"


def test_library_tab_lists_sources(monkeypatch):
    conn = LibraryFakeConn(rows=[("brief.txt", "personal_brand", None, 1, "2026-07-31")])
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    response = client.get("/studio?tab=library")
    assert response.status_code == 200
    assert "brief.txt" in response.text
    assert "personal_brand" in response.text
    assert conn.closed        # no route may leak a connection


def test_library_tab_always_offers_the_assets_shelf(monkeypatch):
    """Entity uploads ingest under "assets"; the search filter offers
    the shelf even before the first asset lands on it."""
    conn = LibraryFakeConn(rows=[])
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    assert 'value="assets"' in client.get("/studio?tab=library").text


def test_library_tab_degrades_when_store_is_down():
    # autouse fixture already makes connect() raise
    response = client.get("/studio?tab=library")
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
    response = client.get("/studio?tab=library&q=structure")
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


# ---------- /references/pick -- the opt-in asset-grounding picker ----------

def test_references_pick_lists_sources_split_by_auto_vs_asset(tmp_preprod_db, monkeypatch):
    # tmp_preprod_db matters: the route also lists characters/props, and
    # without the redirected DB it reads the dev machine's real
    # data/pipeline.db -- green here, broken on a clean clone.
    conn = LibraryFakeConn(rows=[
        ("brief.txt", "personal_brand", None, 1, "2026-07-31"),
        ("short-form-video.md", "marketing", None, 1, "2026-07-31"),
    ])
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    response = client.get("/references/pick")
    assert response.status_code == 200
    assert "brief.txt" in response.text
    assert "short-form-video.md" in response.text
    assert "YOUR ASSETS" in response.text
    assert "ALREADY AUTOMATIC" in response.text
    assert conn.closed


def test_references_pick_degrades_when_store_is_down(tmp_preprod_db):
    # autouse fixture already makes connect() raise; tmp_preprod_db keeps
    # the cast/props lookup off the dev machine's real data/pipeline.db
    response = client.get("/references/pick")
    assert response.status_code == 200
    assert "unavailable" in response.text.lower()


def test_references_pick_upload_posts_to_the_store(monkeypatch):
    conn = LibraryFakeConn()
    recorded = {}
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    monkeypatch.setattr(app_main.rag, "init_store", lambda c: None)
    monkeypatch.setattr(app_main.rag, "make_client", lambda: object())

    def fake_ingest(records, client, c):
        recorded.update(records[0])
        return 2

    monkeypatch.setattr(app_main.rag, "ingest_records", fake_ingest)
    response = client.post(
        "/references/pick/upload",
        data={"domain": "personal_brand"},
        files={"file": ("brief.txt", b"cool calm inspiring", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "brief.txt" in response.headers["location"]
    assert recorded["source"] == "brief.txt"
    assert recorded["domain"] == "personal_brand"
    assert recorded["text"] == "cool calm inspiring"


def test_references_pick_upload_requires_a_domain():
    response = client.post(
        "/references/pick/upload",
        files={"file": ("brief.txt", b"text", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "required" in response.headers["location"].lower()


def test_references_pick_upload_requires_a_file():
    response = client.post(
        "/references/pick/upload",
        data={"domain": "personal_brand"},
        files={"file": ("", b"", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "required" in response.headers["location"].lower()


# ---------- picked_references threads through to reference_block ----------





def test_concepts_generate_threads_picked_references_into_reference_block(tmp_preprod_db, monkeypatch):
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    seen = {}

    def fake_reference_block(**kw):
        seen.update(kw)
        return ""

    monkeypatch.setattr(app_main.shootgen, "reference_block", fake_reference_block)
    monkeypatch.setattr(app_main.shootgen, "generate_concept",
                        lambda **kw: {"concept_id": 1, "concept": {"title": "X"}, "warnings": []})

    client.post("/concepts/generate",
                data={"brand": "antihero", "picked_references": ["brief.txt"]},
                follow_redirects=False)

    assert seen["picked_sources"] == ["brief.txt"]


def test_concepts_generate_with_nothing_picked_passes_none(tmp_preprod_db, monkeypatch):
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    seen = {}

    def fake_reference_block(**kw):
        seen.update(kw)
        return ""

    monkeypatch.setattr(app_main.shootgen, "reference_block", fake_reference_block)
    monkeypatch.setattr(app_main.shootgen, "generate_concept",
                        lambda **kw: {"concept_id": 1, "concept": {"title": "X"}, "warnings": []})

    client.post("/concepts/generate", data={"brand": "antihero"}, follow_redirects=False)

    assert seen["picked_sources"] is None


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


def test_app_pages_are_noindex(tmp_dev_db):
    """The workspace is the product, not content. Indexing it splits the
    ranking signal off the one page that should carry it."""
    for page in ("/studio", "/analytics", "/winners"):
        assert "noindex" in client.get(page).text, page


def test_schema_uses_the_configured_site_url(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://example.test/")
    graph = seo.homepage_schema()
    assert graph["@graph"][0]["@id"] == "https://example.test/#org"
    assert "https://example.test/sitemap.xml" in seo.robots_txt()


# ---------- the assistant ----------





















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






# ---------- reference captures + Director-ready prompts ----------

def _planned_concept(path):
    return preprod.save_concept(
        {"title": "The Waiting", "hook": "a hand on the handle",
         "logline": "He waits.",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
                    "location": "hallway", "desc": "the handle turns",
                    "light": "spill", "prompt": "a handle turning in the dark"}]},
        brand="antihero", path=path)


def test_attach_reference_by_url_lands_on_the_shot(tmp_preprod_db):
    cid = _planned_concept(tmp_preprod_db)
    response = client.post(
        f"/concepts/{cid}/shots/1/reference",
        data={"reference_url": "https://cdn.example/take.jpg", "next": "/concepts"},
        follow_redirects=False)
    assert response.status_code == 303
    shots = preprod.get_concept(cid, path=tmp_preprod_db)["shots"]
    assert shots[0]["reference_image"] == "https://cdn.example/take.jpg"


def test_clear_reference_detaches_it(tmp_preprod_db):
    cid = _planned_concept(tmp_preprod_db)
    preprod.set_shot_reference_image(cid, 1, "https://cdn.example/take.jpg",
                                     path=tmp_preprod_db)
    client.post(f"/concepts/{cid}/shots/1/reference",
                data={"remove": "1"}, follow_redirects=False)
    shots = preprod.get_concept(cid, path=tmp_preprod_db)["shots"]
    assert "reference_image" not in shots[0]


def test_attach_reference_to_a_missing_shot_redirects_with_the_reason(tmp_preprod_db):
    cid = _planned_concept(tmp_preprod_db)
    response = client.post(
        f"/concepts/{cid}/shots/9/reference",
        data={"reference_url": "https://cdn.example/take.jpg"},
        follow_redirects=False)
    # degrade, don't 500: the message rides the redirect
    assert response.status_code == 303
    assert "no%20shot" in response.headers["location"].replace("+", "%20")




# ---------- the Dev Studio: settings tab ----------

def test_settings_tab_lists_the_three_tunables(tmp_dev_db):
    text = client.get("/studio?tab=settings").text
    for key in ("prompt_gate_min", "grade_threshold", "eval_k"):
        assert f'name="{key}"' in text, key


def test_settings_post_saves_and_takes_effect(tmp_dev_db):
    from src import settings
    response = client.post("/studio/settings",
                           data={"prompt_gate_min": "9", "grade_threshold": "0.7",
                                 "eval_k": "8"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/studio?tab=settings")
    assert settings.get("prompt_gate_min", path=tmp_dev_db) == 9
    assert settings.get("grade_threshold", path=tmp_dev_db) == 0.7
    assert settings.get("eval_k", path=tmp_dev_db) == 8


def test_settings_post_rejects_out_of_range_without_saving(tmp_dev_db):
    from src import settings
    response = client.post("/studio/settings", data={"prompt_gate_min": "42"},
                           follow_redirects=False)
    assert "between" in unquote(response.headers["location"])
    assert settings.get("prompt_gate_min", path=tmp_dev_db) == 7


# ---------- the Dev Studio: the Grade queue ----------

def _drain_golden(path):
    from src import evalstore
    for g in evalstore.list_golden(path=path):
        evalstore.delete_golden(g["id"], path=path)


def test_grade_draw_shot_picks_only_ungraded_concepts(tmp_dev_db):
    graded = preprod.save_concept({"title": "Graded"}, brand="antihero",
                                  path=tmp_dev_db)
    preprod.save_judge_score(graded, {"overall": 8, "taste_fit": 8,
                                      "performance": 8, "reasons": []},
                             path=tmp_dev_db)
    ungraded = preprod.save_concept({"title": "Fresh meat"}, brand="antihero",
                                    path=tmp_dev_db)
    response = client.get("/grade/draw?mode=shot", follow_redirects=False)
    assert response.status_code == 303
    assert f"concept_id={ungraded}" in response.headers["location"]
    assert "mode=shot" in response.headers["location"]


def test_grade_draw_golden_picks_a_golden_query(tmp_dev_db):
    from src import evalstore
    _drain_golden(tmp_dev_db)
    gid = evalstore.add_golden("night lighting", ["notes.md"], path=tmp_dev_db)
    response = client.get("/grade/draw?mode=golden", follow_redirects=False)
    assert f"golden_id={gid}" in response.headers["location"]


def test_grade_draw_with_nothing_to_grade_says_so(tmp_dev_db):
    _drain_golden(tmp_dev_db)
    response = client.get("/grade/draw?mode=any", follow_redirects=False)
    location = unquote(response.headers["location"])
    assert location.startswith("/studio?tab=grade")
    assert "Nothing to grade" in location


def test_grade_tab_surfaces_concept_warnings(tmp_dev_db):
    cid = preprod.save_concept(
        {"title": "W", "shots": CONCEPT_SHOTS}, brand="antihero",
        warnings=["shot 1: location 'rooftop helipad' is not a described space"],
        path=tmp_dev_db)
    assert "rooftop helipad" in client.get(
        f"/studio?tab=grade&mode=shot&concept_id={cid}").text


def test_grade_fresh_generates_without_saving_a_concept(tmp_dev_db, monkeypatch):
    """The throwaway mode: one idea via the same generator, shown for
    grading, and NOT persisted as a shoot_concepts row."""
    import src.gemini_utils as gemini_utils
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())
    monkeypatch.setattr(
        gemini_utils, "generate_with_retry",
        lambda client_, model, prompt: '{"ideas": [{"title": "Throwaway", "hook": "H", "logline": "L"}]}')

    response = client.post("/grade/fresh", data={"spark": "night ritual"},
                           follow_redirects=False)
    assert response.status_code == 303
    location = unquote(response.headers["location"])
    assert "mode=fresh" in location and "Throwaway" in location
    assert preprod.list_concepts(path=tmp_dev_db) == []   # nothing saved

    # the redirect renders the item for grading
    follow = client.get(response.headers["location"]).text
    assert "Throwaway" in follow
    assert "never saved" in follow.lower()


def test_grade_fresh_without_a_key_says_so(tmp_dev_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    response = client.post("/grade/fresh", follow_redirects=False)
    assert "GEMINI_API_KEY" in response.headers["location"]


def test_grade_fresh_verdict_teaches_winners(tmp_dev_db):
    from src import winners
    winners.init(tmp_dev_db)
    response = client.post("/grade/fresh/verdict",
                           data={"text": "Throwaway idea", "verdict": "worked"},
                           follow_redirects=False)
    assert response.status_code == 303
    [row] = winners.list_all(path=tmp_dev_db)
    assert row["video_ref"] == "fresh-grade"
    assert row["prompt"] == "Throwaway idea"
    assert preprod.list_concepts(path=tmp_dev_db) == []


def test_grade_golden_mark_adds_and_removes_a_label(tmp_dev_db):
    from src import evalstore
    gid = evalstore.add_golden("night lighting", ["a.md"], path=tmp_dev_db)
    client.post(f"/grade/golden/{gid}/mark",
                data={"source": "b.md", "action": "add"}, follow_redirects=False)
    golden = {g["id"]: g for g in evalstore.list_golden(path=tmp_dev_db)}
    assert set(golden[gid]["relevant"]) == {"a.md", "b.md"}

    client.post(f"/grade/golden/{gid}/mark",
                data={"source": "b.md", "action": "remove"}, follow_redirects=False)
    golden = {g["id"]: g for g in evalstore.list_golden(path=tmp_dev_db)}
    assert golden[gid]["relevant"] == ["a.md"]

    # removing the last label is refused -- a golden query with no
    # relevant source scores nothing
    response = client.post(f"/grade/golden/{gid}/mark",
                           data={"source": "a.md", "action": "remove"},
                           follow_redirects=False)
    assert "relevant" in unquote(response.headers["location"])
    golden = {g["id"]: g for g in evalstore.list_golden(path=tmp_dev_db)}
    assert golden[gid]["relevant"] == ["a.md"]


def test_grade_golden_delete_removes_and_draws_next(tmp_dev_db):
    from src import evalstore
    _drain_golden(tmp_dev_db)
    gid = evalstore.add_golden("gone soon", ["x.md"], path=tmp_dev_db)
    response = client.post(f"/grade/golden/{gid}/delete", follow_redirects=False)
    assert response.headers["location"].startswith("/grade/draw?mode=golden")
    assert evalstore.list_golden(path=tmp_dev_db) == []


# ---------- the Dev Studio: dataset export ----------

def test_dataset_export_golden_json_and_csv(tmp_dev_db):
    from src import evalstore
    _drain_golden(tmp_dev_db)
    evalstore.add_golden("night lighting", ["notes.md"], path=tmp_dev_db)

    as_json = client.get("/dataset/export?what=golden&fmt=json")
    assert as_json.status_code == 200
    assert as_json.headers["content-type"].startswith("application/json")
    assert "attachment" in as_json.headers["content-disposition"]
    assert "night lighting" in as_json.text

    as_csv = client.get("/dataset/export?what=golden&fmt=csv")
    assert as_csv.headers["content-type"].startswith("text/csv")
    assert "night lighting" in as_csv.text
    assert as_csv.text.splitlines()[0].startswith("id,")


def test_dataset_export_runs_and_rejects_garbage(tmp_dev_db):
    from src import evalstore
    evalstore.save_run("r1", {"k": 5, "n": 2, "hit_rate": 0.5, "mrr": 0.4,
                              "per_query": []}, p50_ms=12, path=tmp_dev_db)
    as_csv = client.get("/dataset/export?what=runs&fmt=csv")
    assert "r1" in as_csv.text
    assert client.get("/dataset/export?what=bogus&fmt=json").status_code == 400


def test_dataset_tab_lists_golden_and_runs(tmp_dev_db):
    from src import evalstore
    evalstore.add_golden("tab query", ["notes.md"], path=tmp_dev_db)
    evalstore.save_run("tab run", {"k": 5, "n": 1, "hit_rate": 1.0, "mrr": 1.0,
                                   "per_query": []}, path=tmp_dev_db)
    text = client.get("/studio?tab=dataset").text
    assert "tab query" in text
    assert "tab run" in text
    assert "/dataset/export?what=golden" in text
    assert "/dataset/export?what=runs" in text


# ---------- the Dev Studio: library file upload ----------

def test_library_ingest_accepts_a_file_upload(monkeypatch):
    conn = LibraryFakeConn()
    recorded = {}
    monkeypatch.setattr(app_main.rag, "connect", lambda db_url=None: conn)
    monkeypatch.setattr(app_main.rag, "init_store", lambda c: None)
    monkeypatch.setattr(app_main.rag, "make_client", lambda: object())

    def fake_ingest(records, client_, c):
        recorded.update(records[0])
        return 2

    monkeypatch.setattr(app_main.rag, "ingest_records", fake_ingest)
    response = client.post(
        "/library/ingest",
        data={"domain": "cinematography"},
        files={"file": ("night-notes.txt", b"night exteriors want practicals",
                        "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/studio?tab=library")
    assert recorded["source"] == "night-notes.txt"   # filename becomes the source
    assert recorded["text"] == "night exteriors want practicals"
    assert recorded["domain"] == "cinematography"


def test_library_ingest_file_with_no_text_is_a_message_not_a_500(monkeypatch):
    response = client.post(
        "/library/ingest",
        data={"domain": "cinematography"},
        files={"file": ("empty.txt", b"   ", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "no readable text" in unquote(response.headers["location"])

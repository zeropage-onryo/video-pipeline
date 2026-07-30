"""
Tests for app/main.py's routes. Template-only rendering is exempt from
strict TDD; form parsing and the routes that write data are not.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import (
    app,
    benchmark_class,
    group_pitches_by_run,
    parse_metrics_form,
    parse_video_form,
)
from src import db, preprod

client = TestClient(app)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    db.init_db(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture
def tmp_preprod_db(tmp_db):
    """tmp_db plus the pre-production tables."""
    preprod.init(tmp_db)
    return tmp_db


def test_dashboard_returns_200(tmp_db):
    response = client.get("/")
    assert response.status_code == 200


def test_dashboard_shows_counts(tmp_db):
    response = client.get("/")
    assert "Pitch runs" in response.text
    assert "Ideas" in response.text


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


# ---------- full dashboard ----------

def test_dashboard_empty_state_links_to_add_video(tmp_db):
    response = client.get("/")
    assert "No videos yet" in response.text
    assert "/videos/new" in response.text


def test_dashboard_colours_rows_by_benchmark(tmp_db):
    v1 = db.add_video("Winner", "youtube", "2026-01-01", path=tmp_db)
    v2 = db.add_video("Loser", "youtube", "2026-01-01", path=tmp_db)
    db.record_metrics(v1, views=1000, captured_at="2026-01-08", path=tmp_db)
    db.record_metrics(v2, views=10, captured_at="2026-01-08", path=tmp_db)

    response = client.get("/?posted_within=all")
    assert response.status_code == 200
    assert "Winner" in response.text and "Loser" in response.text
    assert 'class="good"' in response.text
    assert 'class="bad"' in response.text


def test_dashboard_benchmark_uses_same_window_as_top_performers(tmp_db):
    old_date = (date.today() - timedelta(days=400)).isoformat()
    old_measured = (date.today() - timedelta(days=393)).isoformat()
    v_old = db.add_video("Old", "youtube", old_date, path=tmp_db)
    db.record_metrics(v_old, views=99999, captured_at=old_measured, path=tmp_db)

    response = client.get("/")  # default: posted in the last 6 months
    assert "Old" not in response.text

    response_all = client.get("/?posted_within=all")
    assert "Old" in response_all.text


def test_dashboard_shows_pick_rate(tmp_db):
    run_id = db.save_pitch_run(
        [{"number": n, "title": f"S{n}", "logline": "l", "story_note": "n"} for n in range(1, 11)],
        path=tmp_db,
    )
    db.mark_selected_by_number(run_id, [1, 2, 3], path=tmp_db)

    response = client.get("/")
    assert "3" in response.text


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


# ---------- group_pitches_by_run ----------

def test_group_pitches_by_run_groups_and_preserves_order():
    # Shape matches what get_labelled_pitches() actually returns -- run_id,
    # run_created_at, model, prompt_hash always present (SQL-aliased columns).
    pitches = [
        {"run_id": 2, "run_created_at": "t2", "model": "m", "prompt_hash": "h", "number": 1, "title": "A"},
        {"run_id": 2, "run_created_at": "t2", "model": "m", "prompt_hash": "h", "number": 2, "title": "B"},
        {"run_id": 1, "run_created_at": "t1", "model": "m", "prompt_hash": "h", "number": 1, "title": "C"},
    ]
    runs = group_pitches_by_run(pitches)
    assert [r["run_id"] for r in runs] == [2, 1]
    assert len(runs[0]["pitches"]) == 2
    assert len(runs[1]["pitches"]) == 1


def test_group_pitches_by_run_empty_is_safe():
    assert group_pitches_by_run([]) == []


# ---------- /pitches ----------

PITCH_BATCH = [
    {"number": n, "title": f"Story {n}", "logline": f"Line {n}.", "story_note": f"Note {n}."}
    for n in range(1, 11)
]


def test_pitches_page_returns_200(tmp_db):
    response = client.get("/pitches")
    assert response.status_code == 200


def test_pitches_page_empty_state(tmp_db):
    response = client.get("/pitches")
    assert "No reviewed pitch runs yet" in response.text


def test_pitches_page_shows_run_and_marks_picked(tmp_db):
    run_id = db.save_pitch_run(PITCH_BATCH, prompt_template="v1", path=tmp_db)
    db.mark_selected_by_number(run_id, [2, 5, 9], path=tmp_db)

    response = client.get("/pitches")
    assert "Story 2" in response.text
    assert "Story 3" in response.text  # unpicked pitches still shown
    assert "picked" in response.text.lower()


def test_pitches_page_shows_pick_rate_per_prompt(tmp_db):
    run_id = db.save_pitch_run(PITCH_BATCH, prompt_template="v1", path=tmp_db)
    db.mark_selected_by_number(run_id, [2, 5, 9], path=tmp_db)

    response = client.get("/pitches")
    assert "30.0%" in response.text


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
    assert "Refresh" not in response.text


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
    assert "The Waiting" in response.text
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
    assert "1 of 4" in response.text


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


def test_post_generate_concept_creates_one(tmp_preprod_db, monkeypatch):
    preprod.add_location("hallway", SAMPLE_SPACE, path=tmp_preprod_db)
    monkeypatch.setattr(
        app_main.shootgen, "generate_concept",
        lambda **kw: {"concept_id": 1, "concept": {"title": "X"}, "warnings": []},
    )
    response = client.post("/concepts/generate", data={"brand": "antihero", "spark": "a door"},
                           follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "message=" in response.headers["location"]


def test_post_generate_concept_reports_failure_without_breaking(tmp_preprod_db, monkeypatch):
    def boom(**kw):
        raise ValueError("no locations described yet")

    monkeypatch.setattr(app_main.shootgen, "generate_concept", boom)
    response = client.post("/concepts/generate", data={"brand": "antihero"},
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
    response = client.post("/concepts/generate", data={"brand": "antihero"},
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
    assert "1 of 4" in response.text


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

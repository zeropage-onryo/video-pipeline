"""
Surfacing the taste + performance judge in the UI (BACKLOG #5): scores are
stored on the concept and a grade button scores on demand. The LLM call is
mocked; storage, the route, and the ungraded-only batch run for real.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from src import autonomy, db, entities, inspiration, preprod, winners

client = TestClient(app)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    autonomy.init(path)
    winners.init(path)
    inspiration.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def _concept(title="A concept"):
    return {"title": title, "hook": "h", "logline": "l", "shots": []}


def test_save_judge_score_persists_on_the_concept(tmp_db):
    cid = preprod.save_concept(_concept(), "antihero", path=tmp_db, account_id=None)
    preprod.save_judge_score(
        cid, {"overall": 8, "taste_fit": 9, "performance": 7, "reasons": ["r1", "r2"]},
        path=tmp_db, account_id=None)
    c = preprod.get_concept(cid, path=tmp_db, account_id=None)
    assert c["judge_overall"] == 8 and c["judge_taste"] == 9 and c["judge_perf"] == 7
    assert "r1" in c["judge_reason"]


def test_grade_route_scores_and_stores(tmp_db, monkeypatch):
    cid = preprod.save_concept(_concept(), "antihero", path=tmp_db, account_id=None)
    monkeypatch.setattr(
        app_main.taste_judge, "score_concept",
        lambda concept, **k: {"overall": 8.0, "taste_fit": 9.0, "performance": 7.0,
                              "reasons": ["echoes The Last Check"], "graded": True})
    r = client.post(f"/concepts/{cid}/grade", follow_redirects=False)
    assert r.status_code == 303 and "/studio?tab=grade" in r.headers["location"]
    assert preprod.get_concept(cid, path=tmp_db, account_id=None)["judge_overall"] == 8.0


def test_grade_all_scores_only_ungraded(tmp_db, monkeypatch):
    c1 = preprod.save_concept(_concept("one"), "antihero", path=tmp_db, account_id=None)
    c2 = preprod.save_concept(_concept("two"), "antihero", path=tmp_db, account_id=None)
    preprod.save_judge_score(
        c1, {"overall": 5, "taste_fit": 5, "performance": 5, "reasons": []}, path=tmp_db, account_id=None)
    calls = []

    def fake(concept, **k):
        calls.append(concept["id"])
        return {"overall": 6.0, "taste_fit": 6.0, "performance": 6.0,
                "reasons": [], "graded": True}

    monkeypatch.setattr(app_main.taste_judge, "score_concept", fake)
    client.post("/concepts/grade-all", follow_redirects=False)
    assert calls == [c2]   # the already-graded one is skipped


def test_pass_archives_with_a_reason_and_never_deletes(tmp_db):
    """Discard used to hard-delete from this page (replaced 2026-08-31).

    That put the destruction of the only negative signal this pipeline
    collects on the one page built to collect it -- see set_archived:
    "deleting the ones you passed over would make the rate 100% forever
    and unfalsifiable." The row must survive, and the reason must land.
    """
    cid = preprod.save_concept(_concept("passed on"), "antihero", path=tmp_db,
                               account_id=None)
    r = client.post(f"/concepts/{cid}/pass", data={"reason": "boring"},
                    follow_redirects=False)
    assert r.status_code == 303 and "/studio?tab=grade" in r.headers["location"]

    row = preprod.get_concept(cid, path=tmp_db, account_id=None)
    assert row is not None, "passing on a concept deleted it"
    assert row["archived"] is True
    assert row["archive_reason"] == "boring"


def test_a_passed_concept_still_counts_against_pick_rate(tmp_db):
    """The whole reason archiving beats deleting: the row keeps counting
    as generated-and-not-picked, so the rate stays falsifiable."""
    cid = preprod.save_concept(_concept("passed on"), "antihero", path=tmp_db,
                               account_id=None)
    before = preprod.pick_rate(path=tmp_db, account_id=None)["generated"]
    client.post(f"/concepts/{cid}/pass", data={"reason": "off-brand"},
                follow_redirects=False)
    assert preprod.pick_rate(path=tmp_db, account_id=None)["generated"] == before


def test_reasons_are_tallied_for_the_grade_tab(tmp_db):
    """A queue with no visible result is a chore. The tally is the payoff
    -- and the first idea-level signal the pipeline has ever had."""
    for reason in ("boring", "boring", "off-brand"):
        cid = preprod.save_concept(_concept(f"x{reason}"), "antihero",
                                   path=tmp_db, account_id=None)
        client.post(f"/concepts/{cid}/pass", data={"reason": reason},
                    follow_redirects=False)
    counts = preprod.reason_counts(path=tmp_db, account_id=None)
    assert counts[0] == {"reason": "boring", "n": 2}
    assert {"reason": "off-brand", "n": 1} in counts


def test_pass_without_a_reason_still_archives(tmp_db):
    """A reason is the point, but never a gate -- an archive that fails
    because someone did not pick a word is an archive that does not
    happen, and the row stays on the board forever."""
    cid = preprod.save_concept(_concept("no reason"), "antihero", path=tmp_db,
                               account_id=None)
    client.post(f"/concepts/{cid}/pass", follow_redirects=False)
    row = preprod.get_concept(cid, path=tmp_db, account_id=None)
    assert row["archived"] is True and row["archive_reason"] == ""


def test_discard_all_clears_only_the_active_brand(tmp_db):
    a = preprod.save_concept(_concept("keep? no"), "antihero", path=tmp_db, account_id=None)
    z = preprod.save_concept(_concept("other brand"), "zeropage", path=tmp_db, account_id=None)
    client.cookies.set("brand", "antihero")
    r = client.post("/concepts/discard-all", follow_redirects=False)
    client.cookies.clear()
    assert r.status_code == 303
    assert preprod.get_concept(a, path=tmp_db, account_id=None) is None       # active brand wiped
    assert preprod.get_concept(z, path=tmp_db, account_id=None) is not None   # other brand untouched


def test_concepts_are_brand_scoped_in_the_api(tmp_db, monkeypatch):
    """The concepts list is /ui's Pipeline view now; brand scoping rides
    the API's ?brand filter (the old /concepts page is a redirect)."""
    from app import auth
    stub = {"id": 1, "email": "t@example.com", "display_name": "T"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    preprod.save_concept(_concept("AH ONLY ONE"), "antihero", path=tmp_db, account_id=None)
    preprod.save_concept(_concept("ZP ONLY ONE"), "zeropage", path=tmp_db, account_id=None)
    titles = [c["title"] for c in
              client.get("/api/pipeline/concepts?brand=zeropage").json()["items"]]
    assert "ZP ONLY ONE" in titles
    assert "AH ONLY ONE" not in titles


def test_posted_outcomes_reads_the_latest_snapshot(tmp_db):
    """The join that closes the audience loop (2026-08-31).

    `videos.idea_id` pointed at the LEGACY pitch pipeline's table and was
    never once written, so a posted video could not be traced back to the
    concept that made it — whatever the audience taught was structurally
    unable to reach the generator.

    `metrics` is a growth curve on purpose (db.py: "a video has 8k views
    on day one and 40k on day thirty"), so the join must read the LATEST
    snapshot per video. Averaging would throw the curve away.
    """
    import sqlite3

    cid = preprod.save_concept(_concept("posted"), "zeropage", path=tmp_db,
                               account_id=None)
    assert preprod.posted_outcomes(path=tmp_db, account_id=None) == []

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.execute("INSERT INTO videos (concept_id, title, platform, posted_at, brand) "
                     "VALUES (?,?,?,?,?)", (cid, "posted", "instagram", "2026-09-01", "zeropage"))
        vid = conn.execute("SELECT id FROM videos").fetchone()[0]
        for day, shares in (("2026-09-01", 10), ("2026-09-08", 170)):
            conn.execute("INSERT INTO metrics (video_id, captured_at, views, likes, "
                         "comments, saves, shares) VALUES (?,?,?,?,?,?,?)",
                         (vid, day, 9000, 800, 40, 150, shares))

    [row] = preprod.posted_outcomes(path=tmp_db, account_id=None)
    assert row["concept_id"] == cid
    assert row["shares"] == 170, "read the first snapshot, not the latest"

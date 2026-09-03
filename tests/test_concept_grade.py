"""
Surfacing the taste + performance judge in the UI (BACKLOG #5): scores are
stored on the concept and a grade button scores on demand. The LLM call is
mocked; storage, the route, and the ungraded-only batch run for real.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from src import autonomy, db, entities, evalstore, inspiration, preprod, winners

client = TestClient(app)


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    entities.init(path)
    autonomy.init(path)
    winners.init(path)
    inspiration.init(path)
    # the Grade tab counts the golden set alongside the ungraded pool,
    # so rendering it needs evalstore's tables too
    evalstore.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def _concept(title="A concept"):
    return {"title": title, "hook": "h", "logline": "l", "shots": []}


def test_save_judge_score_persists_on_the_concept(tmp_db):
    cid = preprod.save_concept(_concept(), "antihero", dsn=tmp_db, account_id=None)
    preprod.save_judge_score(
        cid, {"overall": 8, "taste_fit": 9, "performance": 7, "reasons": ["r1", "r2"]},
        dsn=tmp_db, account_id=None)
    c = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    assert c["judge_overall"] == 8 and c["judge_taste"] == 9 and c["judge_perf"] == 7
    assert "r1" in c["judge_reason"]


def test_grade_route_scores_and_stores(tmp_db, monkeypatch):
    cid = preprod.save_concept(_concept(), "antihero", dsn=tmp_db, account_id=None)
    monkeypatch.setattr(
        app_main.taste_judge, "score_concept",
        lambda concept, **k: {"overall": 8.0, "taste_fit": 9.0, "performance": 7.0,
                              "reasons": ["echoes The Last Check"], "graded": True})
    r = client.post(f"/concepts/{cid}/grade", follow_redirects=False)
    assert r.status_code == 303 and "/studio?tab=grade" in r.headers["location"]
    assert preprod.get_concept(cid, dsn=tmp_db, account_id=None)["judge_overall"] == 8.0


def test_grade_all_scores_only_ungraded(tmp_db, monkeypatch):
    c1 = preprod.save_concept(_concept("one"), "antihero", dsn=tmp_db, account_id=None)
    c2 = preprod.save_concept(_concept("two"), "antihero", dsn=tmp_db, account_id=None)
    preprod.save_judge_score(
        c1, {"overall": 5, "taste_fit": 5, "performance": 5, "reasons": []}, dsn=tmp_db, account_id=None)
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
    cid = preprod.save_concept(_concept("passed on"), "antihero", dsn=tmp_db,
                               account_id=None)
    r = client.post(f"/concepts/{cid}/pass", data={"reason": "boring"},
                    follow_redirects=False)
    assert r.status_code == 303 and "/studio?tab=grade" in r.headers["location"]

    row = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    assert row is not None, "passing on a concept deleted it"
    assert row["archived"] is True
    assert row["archive_reason"] == "boring"


def test_a_passed_concept_still_counts_against_pick_rate(tmp_db):
    """The whole reason archiving beats deleting: the row keeps counting
    as generated-and-not-picked, so the rate stays falsifiable."""
    cid = preprod.save_concept(_concept("passed on"), "antihero", dsn=tmp_db,
                               account_id=None)
    before = preprod.pick_rate(dsn=tmp_db, account_id=None)["generated"]
    client.post(f"/concepts/{cid}/pass", data={"reason": "off-brand"},
                follow_redirects=False)
    assert preprod.pick_rate(dsn=tmp_db, account_id=None)["generated"] == before


def test_reasons_are_tallied_for_the_grade_tab(tmp_db):
    """A queue with no visible result is a chore. The tally is the payoff
    -- and the first idea-level signal the pipeline has ever had."""
    for reason in ("boring", "boring", "off-brand"):
        cid = preprod.save_concept(_concept(f"x{reason}"), "antihero",
                                   dsn=tmp_db, account_id=None)
        client.post(f"/concepts/{cid}/pass", data={"reason": reason},
                    follow_redirects=False)
    counts = preprod.reason_counts(dsn=tmp_db, account_id=None)
    assert counts[0] == {"reason": "boring", "n": 2}
    assert {"reason": "off-brand", "n": 1} in counts


def test_pass_without_a_reason_still_archives(tmp_db):
    """A reason is the point, but never a gate -- an archive that fails
    because someone did not pick a word is an archive that does not
    happen, and the row stays on the board forever."""
    cid = preprod.save_concept(_concept("no reason"), "antihero", dsn=tmp_db,
                               account_id=None)
    client.post(f"/concepts/{cid}/pass", follow_redirects=False)
    row = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    assert row["archived"] is True and row["archive_reason"] == ""


def test_discard_all_clears_only_the_active_brand(tmp_db):
    a = preprod.save_concept(_concept("keep? no"), "antihero", dsn=tmp_db, account_id=None)
    z = preprod.save_concept(_concept("other brand"), "zeropage", dsn=tmp_db, account_id=None)
    client.cookies.set("brand", "antihero")
    r = client.post("/concepts/discard-all", follow_redirects=False)
    client.cookies.clear()
    assert r.status_code == 303
    assert preprod.get_concept(a, dsn=tmp_db, account_id=None) is None       # active brand wiped
    assert preprod.get_concept(z, dsn=tmp_db, account_id=None) is not None   # other brand untouched


def test_concepts_are_brand_scoped_in_the_api(tmp_db, monkeypatch):
    """The concepts list is /ui's Pipeline view now; brand scoping rides
    the API's ?brand filter (the old /concepts page is a redirect)."""
    from app import auth
    stub = {"id": 1, "email": "t@example.com", "display_name": "T"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    preprod.save_concept(_concept("AH ONLY ONE"), "antihero", dsn=tmp_db, account_id=None)
    preprod.save_concept(_concept("ZP ONLY ONE"), "zeropage", dsn=tmp_db, account_id=None)
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
    cid = preprod.save_concept(_concept("posted"), "zeropage", dsn=tmp_db,
                               account_id=None)
    assert preprod.posted_outcomes(dsn=tmp_db, account_id=None) == []

    with db.connect(tmp_db) as conn:
        conn.execute("INSERT INTO videos (concept_id, title, platform, posted_at, brand) "
                     "VALUES (%s,%s,%s,%s,%s)", (cid, "posted", "instagram", "2026-09-01", "zeropage"))
        vid = conn.execute("SELECT id FROM videos").fetchone()[0]
        for day, shares in (("2026-09-01", 10), ("2026-09-08", 170)):
            conn.execute("INSERT INTO metrics (video_id, captured_at, views, likes, "
                         "comments, saves, shares) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                         (vid, day, 9000, 800, 40, 150, shares))

    [row] = preprod.posted_outcomes(dsn=tmp_db, account_id=None)
    assert row["concept_id"] == cid
    assert row["shares"] == 170, "read the first snapshot, not the latest"


# --- the ungraded queue, listed --------------------------------------------
# The draw is random. A count alone ("12 waiting") says nothing about what
# is in the pool, so the Grade tab lists it (2026-09-02). Same filter the
# draw uses -- judge_overall IS NULL -- so the list and the count on the
# button can never disagree.

def test_ungraded_rows_list_the_whole_pool_newest_first(tmp_db):
    a = preprod.save_concept(_concept("first written"), "antihero", dsn=tmp_db, account_id=None)
    b = preprod.save_concept(_concept("second written"), "antihero", dsn=tmp_db, account_id=None)
    rows = app_main._ungraded_rows(None)
    assert [r["id"] for r in rows] == [b, a]
    assert rows[0]["n"] == f"SHOOT-{b:02d}" and rows[0]["title"] == "second written"


def test_a_graded_concept_leaves_the_list(tmp_db):
    graded = preprod.save_concept(_concept("scored"), "antihero", dsn=tmp_db, account_id=None)
    waiting = preprod.save_concept(_concept("not scored"), "antihero", dsn=tmp_db, account_id=None)
    preprod.save_judge_score(
        graded, {"overall": 7, "taste_fit": 7, "performance": 7, "reasons": []},
        dsn=tmp_db, account_id=None)
    assert [r["id"] for r in app_main._ungraded_rows(None)] == [waiting]


def test_passing_takes_a_concept_out_of_the_queue(tmp_db):
    """The bug this pool exists to not have: `set_archived` leaves
    judge_overall NULL, so before 2026-09-02 a concept passed on from
    this tab stayed in the queue and could be drawn again forever."""
    cid = preprod.save_concept(_concept("passed on"), "antihero", dsn=tmp_db, account_id=None)
    kept = preprod.save_concept(_concept("still open"), "antihero", dsn=tmp_db, account_id=None)
    client.post(f"/concepts/{cid}/pass", data={"reason": "boring"}, follow_redirects=False)
    assert [r["id"] for r in app_main._ungraded_rows(None)] == [kept]


def test_the_draw_cannot_deal_a_passed_concept(tmp_db):
    """The list and the draw must share one definition of the pool, or
    the draw deals rows the list never showed."""
    cid = preprod.save_concept(_concept("passed on"), "antihero", dsn=tmp_db, account_id=None)
    client.post(f"/concepts/{cid}/pass", data={"reason": "boring"}, follow_redirects=False)
    r = client.get("/grade/draw?mode=shot", follow_redirects=False)
    assert f"concept_id={cid}" not in r.headers["location"]
    assert "message=" in r.headers["location"]   # nothing left to draw


def test_grade_all_never_bills_for_a_passed_concept(tmp_db, monkeypatch):
    """Passing is a decision. Spending a billed judge call to score
    something already rejected is money for an answer nobody wants."""
    passed = preprod.save_concept(_concept("passed on"), "antihero", dsn=tmp_db, account_id=None)
    open_ = preprod.save_concept(_concept("still open"), "antihero", dsn=tmp_db, account_id=None)
    client.post(f"/concepts/{passed}/pass", data={"reason": "boring"}, follow_redirects=False)
    calls = []

    def fake(concept, **k):
        calls.append(concept["id"])
        return {"overall": 6.0, "taste_fit": 6.0, "performance": 6.0,
                "reasons": [], "graded": True}

    monkeypatch.setattr(app_main.taste_judge, "score_concept", fake)
    client.post("/concepts/grade-all", follow_redirects=False)
    assert calls == [open_]


def test_the_list_and_the_draw_button_count_agree(tmp_db):
    for i in range(3):
        preprod.save_concept(_concept(f"c{i}"), "antihero", dsn=tmp_db, account_id=None)
    ctx = app_main._grade_context(None, None, None, None, None)
    assert ctx["ungraded_count"] == len(ctx["ungraded"]) == 3


def test_the_grade_tab_renders_a_row_per_ungraded_concept(tmp_db):
    cid = preprod.save_concept(_concept("on the queue"), "antihero", dsn=tmp_db, account_id=None)
    body = client.get("/studio?tab=grade").text
    assert "UNGRADED QUEUE" in body
    assert "on the queue" in body
    assert f"/studio?tab=grade&amp;mode=shot&amp;concept_id={cid}" in body


def test_the_drawn_concept_is_marked_in_the_list(tmp_db):
    cid = preprod.save_concept(_concept("drawn"), "antihero", dsn=tmp_db, account_id=None)
    body = client.get(f"/studio?tab=grade&mode=shot&concept_id={cid}").text
    assert 'class="uq here"' in body


# --- the Graded tab ---------------------------------------------------------
# A concept leaves the queue two ways: passed on, or graded. Passing was
# always visible in the reason tally; a score used to just make the
# concept vanish from the draw. The scores are the data now (2026-09-02).

def test_graded_concepts_are_listed_best_first(tmp_db):
    low = preprod.save_concept(_concept("a five"), "antihero", dsn=tmp_db, account_id=None)
    high = preprod.save_concept(_concept("a nine"), "antihero", dsn=tmp_db, account_id=None)
    preprod.save_judge_score(low, {"overall": 5, "taste_fit": 5, "performance": 5,
                                   "reasons": ["thin"]}, dsn=tmp_db, account_id=None)
    preprod.save_judge_score(high, {"overall": 9, "taste_fit": 9, "performance": 8,
                                    "reasons": ["a real scene"]}, dsn=tmp_db, account_id=None)
    rows = app_main._graded_rows(None)
    assert [r["id"] for r in rows] == [high, low]
    assert rows[0]["good"] is True and rows[1]["good"] is False   # the 7+ mark
    assert rows[0]["taste"] == 9 and rows[0]["perf"] == 8


def test_an_ungraded_concept_is_not_on_the_graded_tab(tmp_db):
    preprod.save_concept(_concept("waiting"), "antihero", dsn=tmp_db, account_id=None)
    assert app_main._graded_rows(None) == []


def test_a_graded_concept_leaves_the_queue_for_the_graded_tab(tmp_db):
    """The two lists partition the concepts: nothing is on both, and
    grading is what moves a row across."""
    cid = preprod.save_concept(_concept("scored"), "antihero", dsn=tmp_db, account_id=None)
    assert [r["id"] for r in app_main._ungraded_rows(None)] == [cid]
    preprod.save_judge_score(cid, {"overall": 8, "taste_fit": 8, "performance": 8,
                                   "reasons": []}, dsn=tmp_db, account_id=None)
    assert app_main._ungraded_rows(None) == []
    assert [r["id"] for r in app_main._graded_rows(None)] == [cid]


def test_the_graded_tab_renders_the_score_and_links_back_to_grading(tmp_db):
    cid = preprod.save_concept(_concept("scored"), "antihero", dsn=tmp_db, account_id=None)
    preprod.save_judge_score(cid, {"overall": 9, "taste_fit": 9, "performance": 8,
                                   "reasons": ["a real scene"]}, dsn=tmp_db, account_id=None)
    body = client.get("/studio?tab=graded").text
    assert "GRADED CONCEPTS" in body
    assert "a real scene" in body            # the judge's reason, on the row
    assert 'class="uq scored strong"' in body
    assert f"/studio?tab=grade&amp;mode=shot&amp;concept_id={cid}" in body


def test_the_graded_tab_says_so_when_nothing_is_scored(tmp_db):
    preprod.save_concept(_concept("waiting"), "antihero", dsn=tmp_db, account_id=None)
    body = client.get("/studio?tab=graded").text
    assert "NOTHING SCORED YET" in body

"""
Surfacing the taste + performance judge in the UI (BACKLOG #5): scores are
stored on the concept and a grade button scores on demand. The LLM call is
mocked; storage, the route, and the ungraded-only batch run for real.
"""
from urllib.parse import unquote

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


def _concept(title="A concept", prompt="Handheld, 35mm, a garage at dawn"):
    return {"title": title, "hook": "h", "logline": "l",
            "shots": [{"n": 1, "type": "scene", "tool": "runway", "prompt": prompt}]}


def _rule_on(concept_id, verdict="approve", shot_n=1, text="the prompt as written"):
    """Your verdict on a concept's scene -- what moves it out of the queue.
    Records only; nothing is taught until the scoring pass."""
    return client.post(f"/concepts/{concept_id}/shots/{shot_n}/verdict",
                       data={"verdict": verdict, "text": text, "tool": "runway"},
                       follow_redirects=False)


def _fake_judge(monkeypatch, overall=8.0):
    """Swap the one billed call for a recorder of who got scored."""
    calls = []

    def fake(concept, **k):
        calls.append(concept["id"])
        return {"overall": overall, "taste_fit": overall, "performance": overall,
                "reasons": ["fake judge"], "graded": True}

    monkeypatch.setattr(app_main.taste_judge, "score_concept", fake)
    return calls


def _rag_up(monkeypatch, ok=True):
    """The RAG store, present or down. Ingest is best-effort by contract,
    so 'down' is a state the loop has to survive, not an error case.

    The double stamps `ingested` exactly as the real ingest_to_rag does --
    that flag is what the state machine reads, so a fake that skipped it
    would pass while the loop never retired anything.
    """
    def fake(entry_id, dsn=None):
        if not ok:
            return {"ok": False, "error": "store unavailable"}
        with app_main.db.connect(dsn) as conn:
            conn.execute("UPDATE winning_prompts SET ingested = 1 WHERE id = %s",
                         (entry_id,))
        return {"ok": True, "chunks": 1}

    monkeypatch.setattr(app_main.winners, "ingest_to_rag", fake)


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


def test_grade_all_scores_only_what_carries_a_verdict(tmp_db, monkeypatch):
    """grade-all is the Graded tab's pass now (2026-09-02): it scores what
    YOU ruled on, not everything that exists. A concept still in the queue
    has not been decided about, and scoring it would be a billed opinion
    nobody asked for."""
    ruled = preprod.save_concept(_concept("ruled on"), "antihero", dsn=tmp_db, account_id=None)
    untouched = preprod.save_concept(_concept("still queued"), "antihero",
                                     dsn=tmp_db, account_id=None)
    _rule_on(ruled)
    calls = _fake_judge(monkeypatch)
    client.post("/concepts/grade-all", follow_redirects=False)
    assert calls == [ruled]
    assert untouched not in calls


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


def test_a_score_alone_does_not_take_a_concept_out_of_the_queue(tmp_db):
    """YOUR verdict is what moves a concept, not the judge's (2026-09-02).
    A score with no verdict behind it is an opinion nobody acted on, and
    the concept is still waiting on you."""
    scored = preprod.save_concept(_concept("scored"), "antihero", dsn=tmp_db, account_id=None)
    preprod.save_judge_score(
        scored, {"overall": 7, "taste_fit": 7, "performance": 7, "reasons": []},
        dsn=tmp_db, account_id=None)
    assert [r["id"] for r in app_main._ungraded_rows(None)] == [scored]


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


def test_the_list_and_the_draw_button_count_agree(tmp_db):
    for i in range(3):
        preprod.save_concept(_concept(f"c{i}"), "antihero", dsn=tmp_db, account_id=None)
    ctx = app_main._grade_context(None, None, None, None, None)
    assert ctx["ungraded_count"] == len(ctx["ungraded"]) == 3


def test_the_grade_tab_renders_a_row_per_ungraded_concept(tmp_db):
    cid = preprod.save_concept(_concept("on the queue"), "antihero", dsn=tmp_db, account_id=None)
    body = client.get("/studio?tab=grade").text
    assert "UNGRADED · WAITING ON YOU" in body
    assert "on the queue" in body
    assert f"/studio?tab=grade&amp;mode=shot&amp;concept_id={cid}" in body


def test_the_drawn_concept_is_marked_in_the_list(tmp_db):
    cid = preprod.save_concept(_concept("drawn"), "antihero", dsn=tmp_db, account_id=None)
    body = client.get(f"/studio?tab=grade&mode=shot&concept_id={cid}").text
    assert 'class="uq here"' in body


# --- the loop: queue -> your verdict -> the scoring pass -> gone ------------
# Mike's design, 2026-09-02. A concept has three states and is in exactly
# one: waiting on you, waiting on the pass, or retired into RAG. The tests
# below are the state machine, including the one failure it must not have
# (a concept that vanishes having taught nothing).

def test_your_verdict_moves_a_concept_out_of_the_queue(tmp_db):
    cid = preprod.save_concept(_concept("ruled on"), "antihero", dsn=tmp_db, account_id=None)
    assert [r["id"] for r in app_main._ungraded_rows(None)] == [cid]
    _rule_on(cid)
    assert app_main._ungraded_rows(None) == []
    assert [r["id"] for r in app_main._graded_rows(None)] == [cid]


def test_a_verdict_records_but_does_not_teach(tmp_db, monkeypatch):
    """The window that makes two steps worth having: until the pass runs,
    nothing has reached the shelves, so a verdict is still recallable."""
    ingested = []
    monkeypatch.setattr(app_main.winners, "ingest_to_rag",
                        lambda entry_id, **k: ingested.append(entry_id) or {"ok": True})
    cid = preprod.save_concept(_concept("ruled on"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(cid)
    assert ingested == [], "the verdict taught RAG before the scoring pass"
    rows = app_main.winners.recorded(f"concept-{cid}-shot-1", dsn=tmp_db)
    assert len(rows) == 1 and rows[0]["ingested"] == 0


def test_the_pass_teaches_scores_and_retires(tmp_db, monkeypatch):
    cid = preprod.save_concept(_concept("ruled on"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(cid)
    _rag_up(monkeypatch)
    calls = _fake_judge(monkeypatch)
    client.post("/concepts/grade-all", follow_redirects=False)
    assert calls == [cid]
    states = app_main._concept_states(None)
    assert [c["id"] for c in states["taught"]] == [cid]
    assert states["queue"] == [] and states["graded"] == []


def test_a_retired_concept_is_on_neither_list(tmp_db, monkeypatch):
    """'Goes away on the surface' -- the whole point. The lesson is in RAG."""
    cid = preprod.save_concept(_concept("done with"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(cid)
    _rag_up(monkeypatch)
    _fake_judge(monkeypatch)
    client.post("/concepts/grade-all", follow_redirects=False)
    assert app_main._ungraded_rows(None) == []
    assert app_main._graded_rows(None) == []
    body = client.get("/studio?tab=graded").text
    assert "NOTHING WAITING" in body and "1 retired into RAG" in body


def test_a_concept_that_cannot_reach_rag_is_not_retired(tmp_db, monkeypatch):
    """The one unacceptable outcome: a concept that disappears having
    taught nothing. Ingest is best-effort, so a store that is down must
    leave the concept on the tab with its verdict intact."""
    cid = preprod.save_concept(_concept("store is down"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(cid)
    _rag_up(monkeypatch, ok=False)
    _fake_judge(monkeypatch)
    r = client.post("/concepts/grade-all", follow_redirects=False)
    assert [c["id"] for c in app_main._concept_states(None)["taught"]] == []
    assert [row["id"] for row in app_main._graded_rows(None)] == [cid]
    assert "could not reach the RAG store" in unquote(r.headers["location"])
    # and the verdict survived to be taught on the next attempt
    assert len(app_main.winners.pending(f"concept-{cid}-shot-1", dsn=tmp_db)) == 1


def test_pressing_the_button_again_finishes_a_failed_ingest(tmp_db, monkeypatch):
    """It is scored already, so the retry must cost nothing -- ingest only."""
    cid = preprod.save_concept(_concept("retry me"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(cid)
    _rag_up(monkeypatch, ok=False)
    _fake_judge(monkeypatch)
    client.post("/concepts/grade-all", follow_redirects=False)

    _rag_up(monkeypatch, ok=True)
    calls = _fake_judge(monkeypatch)
    client.post("/concepts/grade-all", follow_redirects=False)
    assert calls == [], "the retry re-billed for a concept already scored"
    assert [c["id"] for c in app_main._concept_states(None)["taught"]] == [cid]


def test_passing_on_the_grade_tab_withdraws_an_untaught_verdict(tmp_db, monkeypatch):
    """The two pass surfaces are opposites on purpose (2026-09-02). The
    board's X RULES as it archives. "Pass · reason" here means "not even
    worth teaching" -- the three verdicts are right beside it if it is --
    so it takes back a verdict that has not taught anything yet, and the
    concept must not sit on the Teach tab waiting to teach a prompt you
    just passed on."""
    passed = preprod.save_concept(_concept("passed on"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(passed)
    assert [r["id"] for r in app_main._graded_rows(None)] == [passed]

    client.post(f"/concepts/{passed}/pass", data={"reason": "boring"}, follow_redirects=False)
    assert app_main._graded_rows(None) == []
    assert app_main.winners.recorded(f"concept-{passed}-shot-1", dsn=tmp_db) == []

    _rag_up(monkeypatch)
    calls = _fake_judge(monkeypatch)
    client.post("/concepts/grade-all", follow_redirects=False)
    assert calls == []


def test_an_ingested_lesson_survives_a_later_pass(tmp_db, monkeypatch):
    """Withdrawing only ever touches what has not been taught. Once a
    prompt is on the shelves, passing on the concept is not an unteach."""
    cid = preprod.save_concept(_concept("taught then passed"), "antihero",
                               dsn=tmp_db, account_id=None)
    _rule_on(cid)
    _rag_up(monkeypatch)
    _fake_judge(monkeypatch)
    client.post("/concepts/grade-all", follow_redirects=False)

    client.post(f"/concepts/{cid}/pass", data={"reason": "boring"}, follow_redirects=False)
    rows = app_main.winners.recorded(f"concept-{cid}-shot-1", dsn=tmp_db)
    assert len(rows) == 1 and rows[0]["ingested"] == 1


def test_the_graded_tab_shows_the_verdict_and_that_nothing_is_taught_yet(tmp_db):
    cid = preprod.save_concept(_concept("ruled on"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(cid, verdict="deny")
    body = client.get("/studio?tab=graded").text
    assert "YOUR VERDICT RECORDED" in body
    assert "DENIED" in body
    assert "awaiting score" in body
    assert "Score &amp; teach all 1 · billed" in body
    assert f"/studio?tab=grade&amp;mode=shot&amp;concept_id={cid}" in body


def test_a_teach_reads_as_taught_not_as_one_of_its_halves(tmp_db):
    """'Teach it' writes a linked pair -- your fix on the winning shelf and
    the model's on the avoid shelf. Showing that row as DENIED because one
    half is a denial would misreport what you did."""
    cid = preprod.save_concept(_concept("taught"), "antihero", dsn=tmp_db, account_id=None)
    client.post(f"/concepts/{cid}/shots/1/verdict",
                data={"verdict": "teach", "text": "the model's version",
                      "replacement": "my version", "tool": "runway"},
                follow_redirects=False)
    assert app_main._graded_rows(None)[0]["verdict"] == "TAUGHT"


def test_the_grade_tab_points_at_what_is_waiting_to_be_taught(tmp_db):
    cid = preprod.save_concept(_concept("ruled on"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(cid)
    body = client.get("/studio?tab=grade").text
    assert "1 waiting in Teach" in body


def test_the_pass_says_so_when_there_is_nothing_to_do(tmp_db, monkeypatch):
    calls = _fake_judge(monkeypatch)
    r = client.post("/concepts/grade-all", follow_redirects=False)
    assert calls == []
    assert "Nothing waiting" in unquote(r.headers["location"])


def test_board_taste_is_shown_beside_the_button_that_reads_it(tmp_db):
    """The board's ✓/✗ weight the judge's score, and the judge runs on the
    Teach tab's pass -- so the count of what it is reading belongs there,
    not beside a queue that bills nothing (moved 2026-09-02)."""
    picked = preprod.save_concept(_concept("picked"), "antihero", dsn=tmp_db, account_id=None)
    preprod.set_picked(picked, True, dsn=tmp_db, account_id=None)
    ruled = preprod.save_concept(_concept("ruled on"), "antihero", dsn=tmp_db, account_id=None)
    _rule_on(ruled)

    teach = client.get("/studio?tab=graded").text
    assert "Board taste the judge will read" in teach
    assert "weight the score and never" in teach       # the counts-only rule
    assert "also file a verdict that does" in teach     # and what does reach them

    grade = client.get("/studio?tab=grade").text
    assert "Board taste" not in grade


def test_the_judge_reads_this_tenants_board_not_the_unowned_pool(tmp_db, monkeypatch):
    """Rule 1 of account scoping, applied to a helper instead of a route.

    `score_concept` takes no account_id and `gather_signals` defaults it
    to None -- the unowned pool -- so calling it bare scored every concept
    against an EMPTY board while the Teach tab's own line said the judge
    was reading N picked and N passed. Green tests were no evidence:
    conftest overrides the tenant to None, which is exactly the value the
    bug produced.
    """
    from src import accounts
    accounts.upsert_account("zeropage", "Zero Page Films", "#8b5cf6", dsn=tmp_db)
    owned = preprod.save_concept(_concept("owned + picked"), "antihero",
                                 dsn=tmp_db, account_id=1)
    preprod.set_picked(owned, True, dsn=tmp_db, account_id=1)
    ruled = preprod.save_concept(_concept("to score"), "antihero", dsn=tmp_db, account_id=1)
    _rule_on(ruled)

    seen = {}

    def fake(concept, signals=None, **k):
        seen["liked"] = len(signals["liked"])
        return {"overall": 8.0, "taste_fit": 8.0, "performance": 8.0,
                "reasons": [], "graded": True}

    monkeypatch.setattr(app_main.taste_judge, "score_concept", fake)
    _rag_up(monkeypatch)

    from app import auth
    app.dependency_overrides[auth.dev_account_id] = lambda: 1
    try:
        client.post("/concepts/grade-all", follow_redirects=False)
    finally:
        app.dependency_overrides.pop(auth.dev_account_id, None)

    assert seen.get("liked") == 1, (
        "the judge scored against the unowned pool, not this tenant's board")

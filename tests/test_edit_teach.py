"""
A hand edit of a scene prompt teaches the RAG shelves -- for ONE account
that has been turned on, and nobody else (src/edit_teach.py, 2026-09-18,
Mike's call).

What these pin down:

- the gate is `accounts.prompt_edits_teach`, FALSE for everyone until
  `python -m src.accounts edits-teach <slug> --on`; the unowned pool and
  every error are a no;
- an account that is OFF edits exactly as before: nothing recorded, and
  no new key on the shot;
- an account that is ON gets a PENDING draft -> fix pair on the board's
  own ref, the model's draft on the avoid side, the edit on the winning
  side, and the concept lands on the Teach tab marked as edited;
- the draft is REMEMBERED: a second edit still pairs the original draft
  with the latest text (one pending pair per shot, latest wins), and a
  model rewrite (persist_prompt, refine) forgets it;
- the replacement rules extend `_board_verdict`'s: a pending board tap
  is replaced by the pair, a board tap AFTER the edit leaves the pair
  alone, a Grade-tab verdict is never touched;
- a Direct note files (before -> revision) with the note in the row.

Hermetic: no model is called; Direct is stubbed at `director.direct_scene`,
which is the function the route calls (the network guard would object
otherwise).
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import api, auth, jobs
from app import main as app_main
from app.main import app
from src import accounts, edit_teach, entities, generative, preprod, scene_chain, winners, workflows

client = TestClient(app)

DRAFT = "macro of the tank badge, the model's draft"
FIX = "macro of the tank badge, slow push in, my rewrite"


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    entities.init(path)
    workflows.init(path)
    generative.init(path)
    accounts.init(path)
    winners.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


@pytest.fixture(autouse=True)
def fresh_jobs():
    jobs.clear_all_for_tests()
    yield
    jobs.clear_all_for_tests()


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    # a pick draws a still in the background; not in here
    monkeypatch.setenv("ZEROPAGE_KEYFRAME_ON_PICK", "0")
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "zeropage", "display_name": "ZERO PAGE"})


def an_account(path, slug="zeropage", *, teaches: bool):
    account_id = accounts.upsert_account(slug, slug.title(), dsn=path)
    if teaches:
        accounts.set_prompt_edits_teach(slug, True, dsn=path)
    return account_id


def acting_as(account_id):
    for target in (app, app_main.app):
        target.dependency_overrides[auth.current_account_id] = lambda: account_id
        target.dependency_overrides[auth.dev_account_id] = lambda: account_id


def a_scene(path, account_id, prompt=DRAFT, **shot):
    base = {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
            "desc": "tank badge", "prompt": prompt, "refs": ["/props/tank/photo/1.jpg"]}
    base.update(shot)
    return preprod.save_concept(
        {"title": "Night ride", "hook": "the hook", "logline": "the log", "shots": [base]},
        brand="zeropage", spark="spark", dsn=path, account_id=account_id)


def edit(cid, text, n=1):
    return client.post(f"/api/concepts/{cid}/shots/{n}/prompt", json={"prompt": text})


def shot_of(path, cid, account_id, n=1):
    concept = preprod.get_concept(cid, dsn=path, account_id=account_id)
    return next(s for s in concept["shots"] if s.get("n") == n)


def rows_for(path, cid, n=1):
    return winners.recorded(f"concept-{cid}-shot-{n}", dsn=path)


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


# ---------- the gate ----------

def test_off_for_everyone_until_turned_on_by_hand(tmp_db):
    account_id = an_account(tmp_db, teaches=False)
    assert edit_teach.allowed(account_id, dsn=tmp_db) is False
    assert accounts.prompt_edits_teachers(dsn=tmp_db) == []
    result = accounts.set_prompt_edits_teach("zeropage", True, dsn=tmp_db)
    assert result == {"slug": "zeropage", "account_id": account_id,
                      "was": False, "now": True, "changed": True}
    assert edit_teach.allowed(account_id, dsn=tmp_db) is True
    assert accounts.prompt_edits_teachers(dsn=tmp_db) == [
        {"account_id": account_id, "slug": "zeropage"}]
    # idempotent, and it says so
    assert accounts.set_prompt_edits_teach("zeropage", True, dsn=tmp_db)["changed"] is False
    accounts.set_prompt_edits_teach("zeropage", False, dsn=tmp_db)
    assert edit_teach.allowed(account_id, dsn=tmp_db) is False


def test_the_gate_fails_closed(tmp_db):
    an_account(tmp_db, teaches=True)
    assert edit_teach.allowed(None, dsn=tmp_db) is False          # the unowned pool
    assert edit_teach.allowed("nope", dsn=tmp_db) is False
    assert edit_teach.allowed(9999, dsn=tmp_db) is False          # no such account
    assert edit_teach.allowed(1, dsn="postgresql://nobody@127.0.0.1:1/none") is False
    with pytest.raises(ValueError):
        accounts.set_prompt_edits_teach("nobody", True, dsn=tmp_db)


def test_the_manual_lane_flag_is_a_different_column(tmp_db):
    """Turning one gate on must not open the other -- they answer
    different questions about an account."""
    account_id = an_account(tmp_db, teaches=True)
    from src import manual_lane
    assert manual_lane.manual_lane_allowed(account_id, dsn=tmp_db) is False
    accounts.set_manual_lane_operator("zeropage", True, dsn=tmp_db)
    accounts.set_prompt_edits_teach("zeropage", False, dsn=tmp_db)
    assert manual_lane.manual_lane_allowed(account_id, dsn=tmp_db) is True
    assert edit_teach.allowed(account_id, dsn=tmp_db) is False


# ---------- an account that is off: nothing changes ----------

def test_an_account_that_is_off_edits_exactly_as_before(tmp_db):
    account_id = an_account(tmp_db, teaches=False)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    res = edit(cid, FIX)
    assert res.status_code == 200
    assert res.json()["taught"] is False
    shot = shot_of(tmp_db, cid, account_id)
    assert shot["prompt"] == FIX
    assert edit_teach.DRAFT_KEY not in shot           # no new key on their rows
    assert rows_for(tmp_db, cid) == []
    assert app_main._concept_states(account_id)["graded"] == []


def test_the_unowned_pool_never_teaches(tmp_db):
    an_account(tmp_db, teaches=True)
    cid = a_scene(tmp_db, None)          # conftest's default override: None
    assert edit(cid, FIX).json()["taught"] is False
    assert rows_for(tmp_db, cid) == []


# ---------- an account that is on: the pair ----------

def test_an_edit_files_the_drafts_beside_the_fix_as_a_pending_pair(tmp_db):
    account_id = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    res = edit(cid, FIX)
    assert res.status_code == 200 and res.json()["taught"] is True

    rows = rows_for(tmp_db, cid)
    assert len(rows) == 2
    failed = next(r for r in rows if r["verdict"] == "didnt_work")
    worked = next(r for r in rows if r["verdict"] == "worked")
    assert failed["prompt"] == DRAFT and worked["prompt"] == FIX
    assert failed["pair_id"] == worked["id"] and worked["pair_id"] == failed["id"]
    assert {r["note"] for r in rows} == {edit_teach.EDIT_NOTE}
    assert all(not r["ingested"] for r in rows)       # pending: nothing on a shelf yet
    assert failed["tool"].lower() == "runway"

    # the shot remembers the draft, and still renders the fix
    shot = shot_of(tmp_db, cid, account_id)
    assert shot["prompt"] == FIX
    assert shot[edit_teach.DRAFT_KEY] == DRAFT

    # ... and the concept is on the Teach tab, saying which door
    graded = app_main._graded_rows(account_id)
    assert [g["id"] for g in graded] == [cid]
    assert graded[0]["edited"] is True
    assert graded[0]["verdict"] == "TAUGHT"


def test_the_same_text_teaches_nothing(tmp_db):
    account_id = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    assert edit(cid, DRAFT).json()["taught"] is False
    assert edit(cid, "  " + DRAFT + "\n").json()["taught"] is False
    assert rows_for(tmp_db, cid) == []
    assert edit_teach.DRAFT_KEY not in shot_of(tmp_db, cid, account_id)


def test_a_second_edit_still_pairs_the_original_draft_with_the_latest_text(tmp_db):
    account_id = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    edit(cid, FIX)
    edit(cid, FIX + ", and hold on the badge")
    rows = rows_for(tmp_db, cid)
    assert len(rows) == 2                              # one pending pair, not two
    assert next(r for r in rows if r["verdict"] == "didnt_work")["prompt"] == DRAFT
    assert next(r for r in rows if r["verdict"] == "worked")["prompt"] == FIX + ", and hold on the badge"
    # editing back to the draft: there is no fix to teach, and the pair
    # that claimed one is withdrawn rather than left standing
    assert edit(cid, DRAFT).json()["taught"] is False
    assert rows_for(tmp_db, cid) == []
    assert shot_of(tmp_db, cid, account_id)["prompt"] == DRAFT


def test_a_model_rewrite_forgets_the_draft(tmp_db):
    account_id = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    edit(cid, FIX)
    assert shot_of(tmp_db, cid, account_id)[edit_teach.DRAFT_KEY] == DRAFT
    # the canvas's enhance / the graph's refine land through persist_prompt
    assert scene_chain.persist_prompt(cid, 1, "the polished version", db_path=tmp_db,
                                      account_id=account_id) is True
    shot = shot_of(tmp_db, cid, account_id)
    assert edit_teach.DRAFT_KEY not in shot
    # the next hand edit snapshots the polished text as the draft
    edit(cid, "my rewrite of the polish")
    assert shot_of(tmp_db, cid, account_id)[edit_teach.DRAFT_KEY] == "the polished version"
    failed = next(r for r in rows_for(tmp_db, cid) if r["verdict"] == "didnt_work")
    assert failed["prompt"] == "the polished version"


# ---------- replacement rules, beside the board's ----------

def test_a_pending_board_pick_is_replaced_by_the_pair(tmp_db):
    account_id = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    client.post(f"/api/concepts/{cid}/pick", json={"picked": True})
    assert [r["note"] for r in rows_for(tmp_db, cid)] == [api.BOARD_PICK_NOTE]
    edit(cid, FIX)
    rows = rows_for(tmp_db, cid)
    assert len(rows) == 2 and {r["note"] for r in rows} == {edit_teach.EDIT_NOTE}
    # the pick itself is untouched -- the label pick_rate reads
    assert preprod.get_concept(cid, dsn=tmp_db, account_id=account_id)["picked_at"]


def test_a_board_tap_after_the_edit_leaves_the_pair_alone(tmp_db):
    account_id = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    edit(cid, FIX)
    res = client.post(f"/api/concepts/{cid}/pick", json={"picked": True})
    assert res.json()["ruled"] is False
    rows = rows_for(tmp_db, cid)
    assert len(rows) == 2 and {r["note"] for r in rows} == {edit_teach.EDIT_NOTE}
    # un-picking withdraws board verdicts only; a considered edit stays
    client.post(f"/api/concepts/{cid}/pick", json={"picked": False})
    assert len(rows_for(tmp_db, cid)) == 2


def test_a_grade_tab_verdict_is_never_overwritten(tmp_db):
    account_id = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    winners.record_and_learn("runway", DRAFT, note="considered on the Grade tab",
                             video_ref=f"concept-{cid}-shot-1", verdict="worked",
                             dsn=tmp_db, ingest=False)
    assert edit(cid, FIX).json()["taught"] is False
    rows = rows_for(tmp_db, cid)
    assert len(rows) == 1 and rows[0]["note"] == "considered on the Grade tab"
    assert shot_of(tmp_db, cid, account_id)["prompt"] == FIX     # the edit still lands


def test_an_ingested_lesson_is_never_touched(tmp_db, monkeypatch):
    account_id = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    ref = f"concept-{cid}-shot-1"
    entry = winners.add("runway", DRAFT, note=api.BOARD_PICK_NOTE, video_ref=ref,
                        verdict="worked", dsn=tmp_db)
    from src import db
    with db.connect(tmp_db) as conn:
        conn.execute("UPDATE winning_prompts SET ingested = 1 WHERE id = %s", (entry,))
    assert edit(cid, FIX).json()["taught"] is False
    assert [r["id"] for r in rows_for(tmp_db, cid)] == [entry]


# ---------- Direct notes ----------

def test_a_direct_note_files_before_and_after_with_the_note(tmp_db, monkeypatch):
    account_id = acting = an_account(tmp_db, teaches=True)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from src import director

    def fake_direct(concept_id, note, gemini_client=None, model=None, db_path=None,
                    account_id=None):
        # the route must hand the tenant through, or an owned row is "no concept"
        assert account_id == acting, account_id
        concept = preprod.get_concept(concept_id, dsn=db_path, account_id=account_id)
        shots = [dict(s) for s in concept["shots"]]
        shots[0]["prompt"] = "the revision, darker"
        preprod.update_concept_shots(concept_id, {"shots": shots}, dsn=db_path,
                                     account_id=account_id)
        return {"ok": True, "summary": "revised shot(s) 1", "warnings": [], "error": None}

    monkeypatch.setattr(director, "direct_scene", fake_direct)
    res = client.post(f"/api/concepts/{cid}/direct", json={"note": "make it darker"})
    assert res.status_code == 200, res.text
    job = wait_for_job(res.json()["job_id"])
    assert job["status"] == "done", (job.get("error"), job.get("detail"))
    assert "1 pair(s)" in job["detail"]

    rows = rows_for(tmp_db, cid)
    assert len(rows) == 2
    assert next(r for r in rows if r["verdict"] == "didnt_work")["prompt"] == DRAFT
    assert next(r for r in rows if r["verdict"] == "worked")["prompt"] == "the revision, darker"
    assert {r["note"] for r in rows} == {"directed: make it darker"}
    # the revision is the model's: no remembered draft on the shot
    assert edit_teach.DRAFT_KEY not in shot_of(tmp_db, cid, account_id)
    assert app_main._graded_rows(account_id)[0]["edited"] is True


def test_a_direct_note_for_an_account_that_is_off_teaches_nothing(tmp_db, monkeypatch):
    account_id = an_account(tmp_db, teaches=False)
    acting_as(account_id)
    cid = a_scene(tmp_db, account_id)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from src import director

    def fake_direct(concept_id, note, gemini_client=None, model=None, db_path=None,
                    account_id=None):
        concept = preprod.get_concept(concept_id, dsn=db_path, account_id=account_id)
        shots = [dict(s) for s in concept["shots"]]
        shots[0]["prompt"] = "the revision"
        preprod.update_concept_shots(concept_id, {"shots": shots}, dsn=db_path,
                                     account_id=account_id)
        return {"ok": True, "summary": "revised shot(s) 1", "warnings": [], "error": None}

    monkeypatch.setattr(director, "direct_scene", fake_direct)
    job = wait_for_job(client.post(f"/api/concepts/{cid}/direct",
                                   json={"note": "darker"}).json()["job_id"])
    assert job["status"] == "done", job
    assert rows_for(tmp_db, cid) == []
    assert edit_teach.DRAFT_KEY not in shot_of(tmp_db, cid, account_id)


# ---------- the deferred ingest carries the tenant label ----------

def test_ingest_pending_passes_the_project_through(tmp_db, monkeypatch):
    seen = {}

    def fake_ingest(entry_id, dsn=None, project=None):
        seen[entry_id] = project
        return {"ok": True, "chunks": 1}

    monkeypatch.setattr(winners, "ingest_to_rag", fake_ingest)
    winners.add("runway", DRAFT, note="x", video_ref="concept-1-shot-1",
                verdict="worked", dsn=tmp_db)
    result = winners.ingest_pending("concept-1-shot-1", dsn=tmp_db, project="zeropage")
    assert result["ok"] and result["ingested"] == 1
    assert set(seen.values()) == {"zeropage"}

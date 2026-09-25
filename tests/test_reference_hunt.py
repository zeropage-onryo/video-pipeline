"""The hunt (2026-09-24): needs -> search -> a look at every frame ->
bank. The rule under test that matters most is the one `illustrate` does
NOT have: a frame nobody could look at is not banked."""
import pytest

from src import reference_hunt, scout


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Every database touch is stubbed; this suite is about the order of
    the steps and what each refusal does, not about storage."""
    monkeypatch.setattr(scout, "get_finding",
                        lambda fid, dsn=None: {"id": fid, "brand": "zeropage",
                                               "spark": "A nurse counts doors in a flooded corridor."})
    monkeypatch.setattr(scout, "bin_for_finding", lambda fid, dsn=None: [])


def _plan(*roles, planner="model"):
    def plan(text, **kw):
        return {"ok": True, "planner": planner,
                "needs": [{"role": r, "query": f"{r} query", "want": "", "specified": False,
                           "source": "web"} for r in roles]}
    return plan


def _candidates(n, prefix="c"):
    return [{"id": f"{prefix}{i}", "image_url": f"https://x/{prefix}{i}.jpg",
             "source_url": f"https://x/p{i}"} for i in range(1, n + 1)]


def _screen(keep=1, checked=True, note=""):
    def screen(candidates, need=None, **kw):
        keepers = [{**c, "kept_for": "a caption"} for c in candidates[:keep]]
        return {"ok": bool(keepers), "checked": checked, "keepers": keepers,
                "rejected": candidates[keep:], "note": note or "screened"}
    return screen


def _bank(calls):
    def bank(finding, candidate, dsn=None):
        calls.append(candidate)
        return {"ok": True, "banked": len(calls)}
    return bank


def test_a_hunt_runs_one_search_per_need_and_banks_what_survived():
    banked, searches = [], []

    def search(query, brand=None, limit=None, dsn=None):
        searches.append((query, brand, limit))
        return _candidates(4)

    result = reference_hunt.hunt(7, plan=_plan("place", "light"), search=search,
                                 screen=_screen(keep=2), bank=_bank(banked))
    assert result["ok"] and result["banked"] == 4 and result["checked"]
    assert [q for q, _, _ in searches] == ["place query", "light query"]
    assert {b for _, b, _ in searches} == {"zeropage"}
    assert all(c["lane"] == "hunt" for c in banked)
    assert [n["banked"] for n in result["needs"]] == [2, 2]
    assert "2 of 2 need(s) covered" in result["note"]


def test_a_frame_nobody_could_look_at_is_not_banked():
    """The whole point. `illustrate` banks on a dark day; a hunt does not."""
    banked = []
    result = reference_hunt.hunt(
        7, plan=_plan("place"), search=lambda *a, **k: _candidates(3),
        screen=_screen(keep=2, checked=False, note="no model client"),
        bank=_bank(banked))
    assert banked == []
    assert result["ok"] is False and result["checked"] is False
    assert result["banked"] == 0
    assert "not looked at" in result["needs"][0]["note"]
    assert "1 not looked at" in result["note"]


def test_require_check_off_is_the_old_behaviour_and_has_to_be_asked_for():
    banked = []
    result = reference_hunt.hunt(
        7, plan=_plan("place"), search=lambda *a, **k: _candidates(3),
        screen=_screen(keep=1, checked=False), bank=_bank(banked),
        require_check=False)
    assert len(banked) == 1 and result["banked"] == 1
    assert result["checked"] is False      # still reported honestly


def test_one_need_cannot_eat_the_whole_bin():
    banked = []
    result = reference_hunt.hunt(
        7, plan=_plan("place", "light"), search=lambda *a, **k: _candidates(6),
        screen=_screen(keep=6), bank=_bank(banked))
    assert [n["banked"] for n in result["needs"]] == [reference_hunt.KEEP_PER_NEED] * 2


def test_the_bin_cap_stops_the_hunt_and_says_so():
    banked = []
    result = reference_hunt.hunt(
        7, plan=_plan("place", "light", "prop"), search=lambda *a, **k: _candidates(4),
        screen=_screen(keep=2), bank=_bank(banked), cap=3)
    assert result["banked"] == 3 and len(banked) == 3
    assert result["needs"][-1]["note"] in {"bin full", ""}


def test_a_full_bin_is_left_alone(monkeypatch):
    monkeypatch.setattr(scout, "bin_for_finding",
                        lambda fid, dsn=None: [{"url": f"/refs/{i}.jpg"} for i in range(6)])
    called = []
    result = reference_hunt.hunt(7, plan=lambda *a, **k: called.append(1),
                                 search=lambda *a, **k: [], screen=_screen(),
                                 bank=_bank([]))
    assert called == [] and result["banked"] == 0
    assert "already holds" in result["note"]


def test_a_dark_lane_and_an_empty_result_are_reported_not_retried():
    searches = []

    def search(query, brand=None, limit=None, dsn=None):
        searches.append(query)
        return []

    result = reference_hunt.hunt(7, plan=_plan("place"), search=search,
                                 screen=_screen(), bank=_bank([]))
    assert searches == ["place query"]          # one round, never two
    assert result["ok"] is False
    assert "no lane configured" in result["needs"][0]["note"]


def test_only_web_needs_are_hunted_a_face_is_the_element_banks_job():
    def plan(text, **kw):
        return {"ok": True, "planner": "model", "needs": [
            {"role": "face", "query": "a face", "source": "elements", "specified": False},
            {"role": "place", "query": "place query", "source": "web", "specified": False}]}

    searches = []
    reference_hunt.hunt(7, plan=plan,
                        search=lambda q, *a, **k: searches.append(q) or _candidates(2),
                        screen=_screen(keep=1), bank=_bank([]))
    assert searches == ["place query"]


def test_open_questions_are_hunted_before_the_answered_ones():
    def plan(text, **kw):
        return {"ok": True, "planner": "model", "needs": [
            {"role": "place", "query": "answered", "source": "web", "specified": True},
            {"role": "light", "query": "open", "source": "web", "specified": False}]}

    searches = []
    reference_hunt.hunt(7, plan=plan,
                        search=lambda q, *a, **k: searches.append(q) or _candidates(1),
                        screen=_screen(keep=1), bank=_bank([]))
    assert searches == ["open", "answered"]


def test_a_missing_finding_is_an_answer_not_a_raise(monkeypatch):
    monkeypatch.setattr(scout, "get_finding", lambda fid, dsn=None: None)
    result = reference_hunt.hunt(404, plan=_plan("place"), search=lambda *a, **k: [],
                                 screen=_screen(), bank=_bank([]))
    assert result["ok"] is False and result["note"] == "no finding 404"


def test_the_split_planner_still_produces_a_hunt():
    banked = []
    result = reference_hunt.hunt(
        7, plan=_plan("mood", planner="split"), search=lambda *a, **k: _candidates(2),
        screen=_screen(keep=1), bank=_bank(banked))
    assert result["planner"] == "split" and result["banked"] == 1


def test_hunt_bare_reports_what_is_still_unservable(monkeypatch):
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    monkeypatch.setattr(scout, "list_findings",
                        lambda brand=None, unused_only=False, limit=0, dsn=None: rows)
    monkeypatch.setattr(scout, "bin_for_finding",
                        lambda fid, dsn=None: [{"url": "x"}] if fid == 3 else [])
    results = {1: {"banked": 2, "note": ""}, 2: {"banked": 0, "note": "no lane configured"}}
    monkeypatch.setattr(reference_hunt, "hunt", lambda fid, **kw: results[fid])
    notes = []
    out = reference_hunt.hunt_bare("zeropage", log=notes.append)
    assert out == {"checked": 2, "hunted": 1, "bare": 1}
    assert notes == ["hunt: spark 2 left bare — no lane configured"]

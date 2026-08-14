"""
The taste + performance judge: gather_signals is pure (no network), and
score_concept never raises -- no history, no key, or a bad model reply all
degrade to a neutral score. The live LLM call is mocked via
generate_with_retry; only gathering, ranking, and the degrade paths run.
"""
import json

from src import autonomy, db, preprod, taste_judge, winners


def _concept(title, hook="a hook", logline="a line"):
    return {"title": title, "hook": hook, "logline": logline, "duration": "12s", "shots": []}


def _seed(path):
    db.init_db(path)
    preprod.init(path)
    autonomy.init(path)
    winners.init(path)
    liked_id = preprod.save_concept(_concept("The Last Check", "keys snatched"), "antihero", path=path)
    disliked_id = preprod.save_concept(_concept("Boring Wait", "a slow pan"), "antihero", path=path)
    h1 = autonomy.to_hold("antihero", "r", concept_id=liked_id, path=path)
    h2 = autonomy.to_hold("antihero", "r", concept_id=disliked_id, path=path)
    autonomy.resolve_hold(h1, "approved", path=path)
    autonomy.resolve_hold(h2, "rejected", path=path)
    winners.add("runway", "a great prompt", note="clean render", verdict="worked", path=path)
    return path


def test_gather_signals_reads_graded_history(tmp_path):
    path = _seed(tmp_path / "t.db")
    sig = taste_judge.gather_signals(db_path=path)
    assert any(c["title"] == "The Last Check" for c in sig["liked"])
    assert any(c["title"] == "Boring Wait" for c in sig["disliked"])
    assert sig["winners"] and not sig["avoid"]
    assert taste_judge.has_history(sig)


def test_no_history_is_neutral_and_never_calls_the_model(tmp_path):
    path = tmp_path / "empty.db"
    for init in (db.init_db, preprod.init, autonomy.init, winners.init):
        init(path)
    sig = taste_judge.gather_signals(db_path=path)
    assert not taste_judge.has_history(sig)
    out = taste_judge.score_concept(_concept("X"), signals=sig, gemini_client=object(), db_path=path)
    assert out["graded"] is False
    assert out["overall"] == taste_judge.NEUTRAL


def test_score_concept_parses_model_json(tmp_path, monkeypatch):
    path = _seed(tmp_path / "t.db")
    sig = taste_judge.gather_signals(db_path=path)
    monkeypatch.setattr(
        taste_judge, "generate_with_retry",
        lambda *a, **k: '{"taste_fit": 9, "performance": 7, "overall": 8, "reasons": ["echoes The Last Check"]}')
    out = taste_judge.score_concept(_concept("New"), signals=sig, gemini_client=object(), db_path=path)
    assert out["graded"] and out["taste_fit"] == 9.0 and out["overall"] == 8.0
    assert out["reasons"] == ["echoes The Last Check"]


def test_score_concept_never_raises_on_bad_reply(tmp_path, monkeypatch):
    path = _seed(tmp_path / "t.db")
    sig = taste_judge.gather_signals(db_path=path)
    monkeypatch.setattr(taste_judge, "generate_with_retry", lambda *a, **k: "not json at all")
    out = taste_judge.score_concept(_concept("New"), signals=sig, gemini_client=object(), db_path=path)
    assert out["graded"] is False
    assert out["overall"] == taste_judge.NEUTRAL


def test_rank_orders_best_first(tmp_path, monkeypatch):
    path = _seed(tmp_path / "t.db")
    sig = taste_judge.gather_signals(db_path=path)
    scores = {"A": 3, "B": 9, "C": 6}

    def fake(client, model, prompt):
        for title, s in scores.items():
            if f"Title: {title}\n" in prompt:
                return json.dumps({"taste_fit": s, "performance": s, "overall": s, "reasons": []})
        return json.dumps({"overall": 5})

    monkeypatch.setattr(taste_judge, "generate_with_retry", fake)
    ranked = taste_judge.rank([_concept("A"), _concept("B"), _concept("C")],
                              signals=sig, gemini_client=object(), db_path=path)
    assert [c["title"] for c in ranked] == ["B", "C", "A"]

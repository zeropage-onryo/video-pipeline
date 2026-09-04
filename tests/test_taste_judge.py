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
    liked_id = preprod.save_concept(_concept("The Last Check", "keys snatched"), "antihero", dsn=path, account_id=None)
    disliked_id = preprod.save_concept(_concept("Boring Wait", "a slow pan"), "antihero", dsn=path, account_id=None)
    h1 = autonomy.to_hold("antihero", "r", concept_id=liked_id, dsn=path, account_id=None)
    h2 = autonomy.to_hold("antihero", "r", concept_id=disliked_id, dsn=path, account_id=None)
    autonomy.resolve_hold(h1, "approved", dsn=path, account_id=None)
    autonomy.resolve_hold(h2, "rejected", dsn=path, account_id=None)
    winners.add("runway", "a great prompt", note="clean render", verdict="worked", dsn=path)
    return path


def test_gather_signals_reads_graded_history(pg):
    path = _seed(pg)
    sig = taste_judge.gather_signals(db_path=path)
    assert any(c["title"] == "The Last Check" for c in sig["liked"])
    assert any(c["title"] == "Boring Wait" for c in sig["disliked"])
    assert sig["winners"] and not sig["avoid"]
    assert taste_judge.has_history(sig)


def test_the_board_buttons_are_the_taste_signal(pg):
    """The Pipeline check and X reach the judge (2026-09-02).

    Before this, `picked_at` fed one displayed number and `archived_at`
    fed a tally, and the judge's liked/disliked read only the hold
    queue -- which the board never writes. So the surface he actually
    clicks taught the judge nothing, and a fully worked board still
    scored neutral."""
    path = pg
    for init in (db.init_db, preprod.init, autonomy.init, winners.init):
        init(path)
    picked = preprod.save_concept(_concept("Cold Open", "a bolt turns"),
                                  "antihero", dsn=path, account_id=None)
    passed = preprod.save_concept(_concept("Slow Pan", "nothing happens"),
                                  "antihero", dsn=path, account_id=None)
    preprod.set_picked(picked, dsn=path, account_id=None)
    preprod.set_archived(passed, dsn=path, account_id=None)

    sig = taste_judge.gather_signals(db_path=path)
    assert [c["title"] for c in sig["liked"]] == ["Cold Open"]
    assert [c["title"] for c in sig["disliked"]] == ["Slow Pan"]
    assert taste_judge.has_history(sig)
    # and it reaches the model as evidence, not just the dict
    prompt = taste_judge.build_prompt(_concept("New"), sig)
    assert "Cold Open" in prompt and "Slow Pan" in prompt


def test_a_picked_concept_archived_later_is_still_a_like(pg):
    """Picking, rendering and then clearing the card off the board is
    not a rejection -- he wanted that one made. Counting it as a dislike
    would teach the judge the opposite of what happened."""
    path = pg
    for init in (db.init_db, preprod.init, autonomy.init, winners.init):
        init(path)
    cid = preprod.save_concept(_concept("Made It", "he rides"), "antihero",
                               dsn=path, account_id=None)
    preprod.set_picked(cid, dsn=path, account_id=None)
    preprod.set_archived(cid, dsn=path, account_id=None)

    sig = taste_judge.gather_signals(db_path=path)
    assert [c["title"] for c in sig["liked"]] == ["Made It"]
    assert sig["disliked"] == []


def test_one_concept_picked_and_held_is_shown_to_the_judge_once(pg):
    """The same concept can carry a board pick and an approved hold.
    Twice in the evidence list is a thumb on a scale the judge cannot
    see."""
    path = _seed(pg)
    liked = [c for c in preprod.list_concepts(dsn=path, account_id=None)
             if c["title"] == "The Last Check"][0]
    preprod.set_picked(liked["id"], dsn=path, account_id=None)

    sig = taste_judge.gather_signals(db_path=path)
    assert [c["title"] for c in sig["liked"]].count("The Last Check") == 1


def test_no_history_is_neutral_and_never_calls_the_model(pg):
    path = pg
    for init in (db.init_db, preprod.init, autonomy.init, winners.init):
        init(path)
    sig = taste_judge.gather_signals(db_path=path)
    assert not taste_judge.has_history(sig)
    out = taste_judge.score_concept(_concept("X"), signals=sig, gemini_client=object(), db_path=path)
    assert out["graded"] is False
    assert out["overall"] == taste_judge.NEUTRAL


def test_score_concept_parses_model_json(pg, monkeypatch):
    path = _seed(pg)
    sig = taste_judge.gather_signals(db_path=path)
    monkeypatch.setattr(
        taste_judge, "generate_with_retry",
        lambda *a, **k: '{"taste_fit": 9, "performance": 7, "overall": 8, "reasons": ["echoes The Last Check"]}')
    out = taste_judge.score_concept(_concept("New"), signals=sig, gemini_client=object(), db_path=path)
    assert out["graded"] and out["taste_fit"] == 9.0 and out["overall"] == 8.0
    assert out["reasons"] == ["echoes The Last Check"]


def test_score_concept_never_raises_on_bad_reply(pg, monkeypatch):
    path = _seed(pg)
    sig = taste_judge.gather_signals(db_path=path)
    monkeypatch.setattr(taste_judge, "generate_with_retry", lambda *a, **k: "not json at all")
    out = taste_judge.score_concept(_concept("New"), signals=sig, gemini_client=object(), db_path=path)
    assert out["graded"] is False
    assert out["overall"] == taste_judge.NEUTRAL


def test_rank_orders_best_first(pg, monkeypatch):
    path = _seed(pg)
    sig = taste_judge.gather_signals(db_path=path)
    scores = {"A": 3, "B": 9, "C": 6}

    def fake(client, model, prompt, **_):
        for title, s in scores.items():
            if f"Title: {title}\n" in prompt:
                return json.dumps({"taste_fit": s, "performance": s, "overall": s, "reasons": []})
        return json.dumps({"overall": 5})

    monkeypatch.setattr(taste_judge, "generate_with_retry", fake)
    ranked = taste_judge.rank([_concept("A"), _concept("B"), _concept("C")],
                              signals=sig, gemini_client=object(), db_path=path)
    assert [c["title"] for c in ranked] == ["B", "C", "A"]

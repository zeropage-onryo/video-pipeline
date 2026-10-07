"""The one-off concept wipe (ops/wipe_concepts.py, 2026-10-07).

Each test names the line it guards. Nothing here calls a model: the
pending-lesson ingest is injected.
"""
import json

import pytest

from ops import wipe_concepts as wipe
from src import accounts, autonomy, db, preprod, render_assets, winners, workflows


@pytest.fixture
def store(pg, monkeypatch, tmp_path):
    preprod.init(pg)
    autonomy.init(pg)
    workflows.init(pg)
    winners.init(pg)
    render_assets.init(pg)
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 0, "error": None})
    seeded = accounts.seed("mike@example.com", dsn=pg)
    return {"dsn": pg, "account": seeded["accounts"][0], "tmp": tmp_path}


def scene(dsn, account, title, **shot):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "LTX", "desc": "d",
                    "prompt": "p", "refs": ["/refs/a.jpg"], **shot}]},
        brand="zeropage", prompt_template="T", dsn=dsn, account_id=account)


def _setup(s):
    dsn, acct = s["dsn"], s["account"]
    ids = {
        "plain": scene(dsn, acct, "plain"),
        "plain2": scene(dsn, acct, "plain with a canvas and a hold"),
        "rendered": scene(dsn, acct, "rendered", media_url="https://r2/clip.mp4"),
        "part": scene(dsn, acct, "one part rendered",
                      timeline={"parts": [{"n": 1, "media_url": "https://r2/p1.mp4"}]}),
        "picked": scene(dsn, acct, "picked"),
        "parked": scene(dsn, acct, "parked", parked_at="2026-10-01T00:00:00"),
        "parked_gone": scene(dsn, acct, "parked, then archived", parked_at="2026-10-01T00:00:00"),
        "asset": scene(dsn, acct, "has a generated asset"),
        "kept": scene(dsn, acct, "kept by id"),
    }
    preprod.set_picked(ids["picked"], True, dsn=dsn, account_id=acct)
    # archived after it was parked: no longer in the Queue, so not kept
    preprod.set_archived(ids["parked_gone"], True, dsn=dsn, account_id=acct)
    render_assets.record(generation_id=1, tool="fal", model="ltx", media_kind="image", prompt="p",
                         media_url="https://r2/still.png", concept_id=ids["asset"], dsn=dsn,
                         account_id=acct)
    with db.connect(dsn) as conn:
        conn.execute("INSERT INTO hold_queue (created_at, channel, concept_id, account_id) "
                     "VALUES ('2026-10-01', 'zeropage', %s, %s)", (ids["plain2"], acct))
    workflows.save_shot_graph(ids["plain2"], 1, {"nodes": []}, dsn=dsn, account_id=acct)
    winners.record_pair("ltx", "draft", "edit", note="edited by hand",
                        video_ref=f"concept-{ids['plain']}-shot-1", dsn=dsn, ingest=False)
    return ids


# guards: scan's keep rules and its read-only report
def test_the_report_keeps_what_must_survive_and_changes_nothing(store):
    ids = _setup(store)
    plan = wipe.scan(store["dsn"], account_id=store["account"], keep_ids=(ids["kept"],))
    assert sorted(plan["delete"]) == sorted([ids["plain"], ids["plain2"], ids["parked_gone"]])
    assert plan["keep"][ids["rendered"]] == ["rendered"]
    assert plan["keep"][ids["part"]] == ["rendered"]
    assert plan["keep"][ids["picked"]] == ["picked"]
    assert plan["keep"][ids["parked"]] == ["waiting in the Queue"]
    assert ids["parked_gone"] not in plan["keep"]
    assert plan["keep"][ids["asset"]] == ["points from a generated asset"]
    assert plan["keep"][ids["kept"]] == ["kept by id"]
    assert plan["dependents"]["hold_queue"] == 1
    assert plan["dependents"]["workflows"] == 1
    assert plan["pending_pairs"] == [f"concept-{ids['plain']}-shot-1"]
    assert plan["unknown_columns"] == []
    assert len(preprod.list_concepts(limit=100, dsn=store["dsn"], account_id=store["account"])) == 9


# guards: wipe -- lessons first, backup and rates, one transaction, re-runnable
def test_the_write_ingests_backs_up_deletes_and_is_rerunnable(store):
    ids = _setup(store)
    dsn, acct = store["dsn"], store["account"]
    taught = []
    plan = wipe.scan(dsn, account_id=acct, keep_ids=(ids["kept"],))
    result = wipe.wipe(dsn, account_id=acct, plan=plan,
                       ingest=lambda ref: taught.append(ref) or {"ok": True},
                       backup_dir=store["tmp"] / "backups", stats_dir=store["tmp"] / "stats")
    assert taught == [f"concept-{ids['plain']}-shot-1"]
    assert result["deleted"] == {"shoot_concepts": 3, "hold_queue": 1, "workflows": 1}
    left = {c["id"] for c in preprod.list_concepts(limit=100, dsn=dsn, account_id=acct)}
    assert left == set(ids.values()) - {ids["plain"], ids["plain2"], ids["parked_gone"]}
    backup = json.loads(open(result["backup"]).read())
    assert sorted(backup["deleting"]) == sorted([ids["plain"], ids["plain2"], ids["parked_gone"]])
    assert len(backup["shoot_concepts"]) == 9 and len(backup["hold_queue"]) == 1
    assert "pick_rate" in json.loads(open(result["stats"]).read())
    # the asset row and its file name are untouched
    assert len(render_assets.list_all(dsn=dsn, account_id=acct)) == 1
    # a second run finds nothing to do
    again = wipe.scan(dsn, account_id=acct, keep_ids=(ids["kept"],))
    assert again["delete"] == []
    assert wipe.wipe(dsn, account_id=acct, plan=again)["deleted"] == {}


# guards: a lesson that will not ingest stops the write before any delete
def test_a_lesson_that_will_not_ingest_deletes_nothing(store):
    ids = _setup(store)
    plan = wipe.scan(store["dsn"], account_id=store["account"], keep_ids=(ids["kept"],))
    with pytest.raises(RuntimeError, match="would not ingest"):
        wipe.wipe(store["dsn"], account_id=store["account"], plan=plan,
                  ingest=lambda ref: {"ok": False},
                  backup_dir=store["tmp"] / "b", stats_dir=store["tmp"] / "s")
    assert len(preprod.list_concepts(limit=100, dsn=store["dsn"], account_id=store["account"])) == 9


# guards: an unknown column naming a concept refuses the write
def test_a_column_nobody_decided_refuses_the_write(store):
    ids = _setup(store)
    with db.connect(store["dsn"]) as conn:
        conn.execute("CREATE TABLE later_feature (id BIGINT, concept_id BIGINT, account_id BIGINT)")
    plan = wipe.scan(store["dsn"], account_id=store["account"], keep_ids=(ids["kept"],))
    assert plan["unknown_columns"] == ["later_feature.concept_id"]
    with pytest.raises(RuntimeError, match="later_feature.concept_id"):
        wipe.wipe(store["dsn"], account_id=store["account"], plan=plan,
                  ingest=lambda ref: {"ok": True})


# guards: a count that differs from the report rolls everything back
def test_a_count_that_differs_from_the_report_rolls_back(store):
    ids = _setup(store)
    plan = wipe.scan(store["dsn"], account_id=store["account"], keep_ids=(ids["kept"],))
    plan["dependents"]["hold_queue"] = 7          # the report said something else
    with pytest.raises(RuntimeError, match="rolled back"):
        wipe.wipe(store["dsn"], account_id=store["account"], plan=plan,
                  ingest=lambda ref: {"ok": True},
                  backup_dir=store["tmp"] / "b", stats_dir=store["tmp"] / "s")
    assert len(preprod.list_concepts(limit=100, dsn=store["dsn"], account_id=store["account"])) == 9


# guards: only the named account, and never a guessed database
def test_another_accounts_concepts_are_never_touched(store, monkeypatch, capsys):
    ids = _setup(store)
    other = accounts.upsert_account("other", "Other", dsn=store["dsn"])
    theirs = scene(store["dsn"], other, "someone else's plain scene")
    plan = wipe.scan(store["dsn"], account_id=store["account"], keep_ids=(ids["kept"],))
    assert theirs not in plan["delete"] and theirs not in plan["keep"]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert wipe.main(["--account", "zeropage"]) == 2
    assert "never guesses" in capsys.readouterr().err

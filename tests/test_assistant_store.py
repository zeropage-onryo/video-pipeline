"""
The assistant pill's memory (2026-09-29, src/assistant_store.py): the
persona, the open project, and the Keep clicks against the checker.

What each test guards:
- a persona is cleaned the way the brain cleans it before it reaches a prompt
- a project survives: the thread and the step come back as saved, bounded
- "New project" archives rather than deletes, and the next save starts fresh
- one account never sees another's persona, project or verdicts
- a verdict is recorded only for an id a hunt actually served, and
  agreement() counts the disagreements in both directions
- the write routes refuse a request without the Guide's header, and the
  read route answers for the caller's account only
"""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import assistant_store, imagesearch


@pytest.fixture
def store(pg, monkeypatch):
    # account_id carries a real foreign key: the accounts must exist
    # (seed_two makes zeropage = 1, antihero = 2)
    from conftest import seed_two
    seed_two("pill@example.test", dsn=pg)
    assistant_store.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


def _turns(n):
    out = []
    for i in range(n):
        out += [{"role": "user", "content": f"ask {i}"},
                {"role": "assistant", "content": f"answer {i}"}]
    return out


# --- the persona -------------------------------------------------------------

def test_a_persona_is_cleaned_like_the_prompt_sees_it(store):
    saved = assistant_store.save_persona("N<o>va!!", "🦊<b>", "sarcastic",
                                         account_id=1, dsn=store)
    assert saved == {"name": "Nova", "avatar": "🦊b", "tone": "direct"}
    got = assistant_store.get_persona(account_id=1, dsn=store)
    assert {k: got[k] for k in ("name", "avatar", "tone")} == saved


def test_saving_a_persona_twice_keeps_one_row(store):
    assistant_store.save_persona("Nova", "🦊", "direct", account_id=1, dsn=store)
    assistant_store.save_persona("Rae", "🤖", "hype", account_id=1, dsn=store)
    assert assistant_store.get_persona(account_id=1, dsn=store)["name"] == "Rae"


# --- the project --------------------------------------------------------------

def test_a_project_comes_back_as_it_was_saved(store):
    assert assistant_store.open_project(account_id=1, dsn=store) is None
    saved = assistant_store.save_project(_turns(2), "story", account_id=1, dsn=store)
    assert saved["title"] == "ask 0"                       # the first thing asked
    got = assistant_store.open_project(account_id=1, dsn=store)
    assert got["id"] == saved["id"] and got["stage"] == "story"
    assert [t["content"] for t in got["turns"]] == ["ask 0", "answer 0", "ask 1", "answer 1"]


def test_a_long_thread_keeps_its_newest_turns(store):
    assistant_store.save_project(_turns(40), "brief", account_id=1, dsn=store)
    turns = assistant_store.open_project(account_id=1, dsn=store)["turns"]
    assert len(turns) == assistant_store.MAX_TURNS
    assert turns[-1]["content"] == "answer 39"


def test_an_unknown_stage_is_not_stored(store):
    assistant_store.save_project(_turns(1), "render everything", account_id=1, dsn=store)
    assert assistant_store.open_project(account_id=1, dsn=store)["stage"] == ""


def test_new_project_archives_and_the_next_save_starts_fresh(store):
    first = assistant_store.save_project(_turns(1), "story", account_id=1, dsn=store)
    assistant_store.new_project(account_id=1, dsn=store)
    assert assistant_store.open_project(account_id=1, dsn=store) is None
    second = assistant_store.save_project([{"role": "user", "content": "a watch ad"}],
                                          "", account_id=1, dsn=store)
    assert second["id"] != first["id"] and second["title"] == "a watch ad"
    from src import db
    with db.connect(store) as conn:
        kept = conn.execute("SELECT COUNT(*) AS n FROM assistant_projects "
                            "WHERE account_id = %s", (1,)).fetchone()["n"]
    assert kept == 2                                        # archived, never deleted


def test_accounts_never_see_each_others_memory(store):
    assistant_store.save_persona("Nova", "🦊", "direct", account_id=1, dsn=store)
    assistant_store.save_project(_turns(1), "story", account_id=1, dsn=store)
    assert assistant_store.get_persona(account_id=2, dsn=store) is None
    assert assistant_store.open_project(account_id=2, dsn=store) is None
    assistant_store.save_project([{"role": "user", "content": "mine"}], "",
                                 account_id=2, dsn=store)
    assert assistant_store.open_project(account_id=1, dsn=store)["title"] == "ask 0"


# --- Keep against the checker --------------------------------------------------

@pytest.fixture
def served(monkeypatch):
    ids = {"ope-a", "ope-b", "ope-c"}
    monkeypatch.setattr(imagesearch, "get",
                        lambda cid, dsn=None: {"id": cid} if cid in ids else None)
    return ids


def test_verdicts_record_served_ids_and_agreement_counts_both_ways(store, served):
    frames = [
        {"id": "ope-a", "checker_kept": True, "person_kept": True, "role": "light"},
        {"id": "ope-b", "checker_kept": False, "person_kept": True, "why": "flat light"},
        {"id": "ope-c", "checker_kept": True, "person_kept": False},
        {"id": "invented-1", "checker_kept": True, "person_kept": True},   # never served
    ]
    assert assistant_store.record_verdicts(frames, account_id=1, dsn=store) == 3
    assert assistant_store.agreement(account_id=1, dsn=store) == {
        "n": 3, "agree": 1, "kept_anyway": 1, "left_out": 1, "rate": 0.333}
    assert assistant_store.agreement(account_id=2, dsn=store)["rate"] is None


# --- the routes ----------------------------------------------------------------

@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "pill-user"})
    app.dependency_overrides[auth.current_account_id] = lambda: 2
    yield TestClient(app)
    app.dependency_overrides[auth.current_account_id] = lambda: None


GUARD = {"X-ZPF-Model-Connection": "1"}


def test_the_routes_round_trip_the_callers_memory(client, served):
    assert client.get("/api/assistant").json() == {"persona": None, "project": None}
    r = client.put("/api/assistant/persona", headers=GUARD,
                   json={"name": "Nova", "avatar": "🦊", "tone": "friendly"})
    assert r.status_code == 200 and r.json()["persona"]["tone"] == "friendly"
    r = client.put("/api/assistant/project", headers=GUARD,
                   json={"turns": _turns(1), "stage": "references"})
    assert r.status_code == 200 and "turns" not in r.json()["project"]
    got = client.get("/api/assistant").json()
    assert got["persona"]["name"] == "Nova"
    assert got["project"]["stage"] == "references" and len(got["project"]["turns"]) == 2
    r = client.post("/api/assistant/reference-verdicts", headers=GUARD,
                    json={"frames": [{"id": "ope-a", "checker_kept": False, "person_kept": True}]})
    assert r.json()["recorded"] == 1 and r.json()["agreement"]["kept_anyway"] == 1
    assert client.post("/api/assistant/project/new", headers=GUARD).status_code == 200
    assert client.get("/api/assistant").json()["project"] is None


def test_the_writes_refuse_a_request_without_the_guide_header(client):
    for method, path, body in (("put", "/api/assistant/persona", {"name": "x"}),
                               ("put", "/api/assistant/project", {"turns": []}),
                               ("post", "/api/assistant/project/new", {}),
                               ("post", "/api/assistant/reference-verdicts", {"frames": []})):
        r = getattr(client, method)(path, json=body)
        assert r.status_code == 403, (path, r.status_code)


def test_a_malformed_project_is_refused(client):
    r = client.put("/api/assistant/project", headers=GUARD, json={"turns": "not a list"})
    assert r.status_code == 400

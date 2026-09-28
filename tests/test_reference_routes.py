"""The reference hunt's two routes (2026-09-25).

The hunt BANKS NOTHING -- its job output is the contact sheet -- and
keeping is a separate click that takes candidate ids and nothing else.
Everything below is patched at the function the route actually calls;
no model, no lane and no database is touched.
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import api as api_mod
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    from app import auth
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(auth, "current_account",
                        lambda request, user=None: {"slug": "zeropage",
                                                    "display_name": "ZERO PAGE"})


@pytest.fixture(autouse=True)
def a_spark_and_a_key(monkeypatch):
    monkeypatch.setattr(api_mod, "_gemini_key", lambda *a, **k: "key")
    monkeypatch.setattr(api_mod.scout, "get_finding",
                        lambda fid, dsn=None: {"id": fid, "brand": "zeropage",
                                               "spark": "A nurse counts doors."}
                        if fid == 7 else None)
    monkeypatch.setattr(api_mod.scout, "bin_for_finding", lambda fid, dsn=None: [])


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


SHEET = {
    "ok": True, "banked": 0, "proposed": 1, "checked": True, "planner": "model",
    "note": "1 of 2 need(s) covered, 0 image(s) banked",
    "needs": [], "sheet": [{"role": "place", "query": "wet corridor",
                            "keepers": [{"id": "c1", "kept_for": "the water line"}],
                            "rejected": [{"id": "c2", "why": "watermark — not a clean frame"}]}],
}


def test_the_hunt_returns_a_sheet_and_banks_nothing(monkeypatch):
    banked = []
    monkeypatch.setattr(api_mod.reference_hunt, "propose",
                        lambda fid, **kw: dict(SHEET, finding=fid))
    monkeypatch.setattr(api_mod.scout, "bank_candidate",
                        lambda *a, **k: banked.append(a) or {"ok": True})
    job_id = client.post("/api/references/7/hunt").json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert banked == []
    output = json.loads(job["output"])
    assert output["banked"] == 0 and output["proposed"] == 1
    assert output["sheet"][0]["keepers"][0]["id"] == "c1"
    assert "watermark" in output["sheet"][0]["rejected"][0]["why"]


def test_the_hunt_refuses_without_a_key(monkeypatch):
    monkeypatch.setattr(api_mod, "_gemini_key", lambda *a, **k: None)
    assert client.post("/api/references/7/hunt").status_code == 503


def test_an_unknown_spark_is_a_404_on_both_routes():
    assert client.post("/api/references/999/hunt").status_code == 404
    assert client.post("/api/references/999/keep",
                       json={"candidate_ids": ["c1"]}).status_code == 404


def test_keeping_banks_only_ids_this_install_served(monkeypatch):
    served = {"c1": {"id": "c1", "image_url": "https://x/1.jpg",
                     "source_url": "https://x/p1", "source": "reddit"}}
    monkeypatch.setattr(api_mod.imagesearch, "get",
                        lambda cid, dsn=None: served.get(cid))
    banked = []

    def bank(finding, candidate, dsn=None):
        banked.append(candidate)
        return {"ok": True}

    monkeypatch.setattr(api_mod.scout, "bank_candidate", bank)
    body = {"candidate_ids": ["c1", "made-up-id"]}
    result = client.post("/api/references/7/keep", json=body).json()
    assert result["banked"] == 1
    assert [c["id"] for c in banked] == ["c1"]
    assert banked[0]["lane"] == "hunt"
    assert result["refused"][0]["id"] == "made-up-id"
    assert "cannot be composed" in result["refused"][0]["error"]


def test_a_refusal_from_the_bank_is_reported_not_counted(monkeypatch):
    monkeypatch.setattr(api_mod.imagesearch, "get",
                        lambda cid, dsn=None: {"id": cid, "image_url": "u", "source_url": "s"})
    monkeypatch.setattr(api_mod.scout, "bank_candidate",
                        lambda *a, **k: {"ok": False, "error": "not a readable image"})
    result = client.post("/api/references/7/keep",
                         json={"candidate_ids": ["c1"]}).json()
    assert result["banked"] == 0
    assert result["refused"][0]["error"] == "not a readable image"


def test_keeping_cannot_exceed_the_bin_cap(monkeypatch):
    from src import scout as scout_mod
    monkeypatch.setattr(api_mod.imagesearch, "get",
                        lambda cid, dsn=None: {"id": cid, "image_url": "u", "source_url": "s"})
    seen = []
    monkeypatch.setattr(api_mod.scout, "bank_candidate",
                        lambda f, c, dsn=None: seen.append(c) or {"ok": True})
    ids = [f"c{i}" for i in range(scout_mod.MAX_BIN_IMAGES + 4)]
    result = client.post("/api/references/7/keep", json={"candidate_ids": ids}).json()
    assert len(seen) == scout_mod.MAX_BIN_IMAGES
    assert result["banked"] == scout_mod.MAX_BIN_IMAGES


def test_keeping_nothing_is_a_200_that_banks_nothing(monkeypatch):
    monkeypatch.setattr(api_mod.scout, "bank_candidate",
                        lambda *a, **k: pytest.fail("nothing should be banked"))
    result = client.post("/api/references/7/keep", json={"candidate_ids": []}).json()
    assert result == {"banked": 0, "refused": [], "bin": []}

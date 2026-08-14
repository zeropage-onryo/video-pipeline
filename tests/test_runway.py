"""
Tests for src/runway.py -- the Runway connector.

Fully hermetic: the SDK is a fake client object, _download is patched
(conftest blocks the network anyway), and no test may reach Runway (it
would bill real API credits). The generations table runs against a
throwaway DB. The spend gate (RUNWAY_SPEND_OK) is the extra surface
veo.py doesn't have: approval is opt-in per test, refusal is the
default -- same as production.
"""
from types import SimpleNamespace

import pytest

from src import db, generative, runway


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    generative.init(path)
    return path


@pytest.fixture
def approved(monkeypatch):
    monkeypatch.setenv(runway.SPEND_ENV, "1")


@pytest.fixture
def fake_download(monkeypatch):
    downloaded = []

    def _fake(url, out_path):
        downloaded.append(url)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 2048)   # big enough to pass the size QC

    monkeypatch.setattr(runway, "_download", _fake)
    return downloaded


class FakeClient:
    """create() hands back a task handle whose wait_for_task_output()
    returns the finished task -- the SDK's own polling contract."""

    def __init__(self, outputs=("https://fake.runway/clip.mp4",)):
        self.calls = []
        self._outputs = list(outputs)
        self.image_to_video = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        task = SimpleNamespace(output=self._outputs)
        return SimpleNamespace(wait_for_task_output=lambda: task)


# ---------- the spend gate ----------

def test_unapproved_video_raises_and_points_at_the_app(tmp_path, monkeypatch):
    monkeypatch.delenv(runway.SPEND_ENV, raising=False)
    with pytest.raises(RuntimeError, match="Runway app"):
        runway.generate_video("x", tmp_path / "c.mp4", client=FakeClient())


def test_unapproved_candidates_refuse_before_touching_anything(tmp_db, tmp_path,
                                                               monkeypatch, fake_download):
    monkeypatch.delenv(runway.SPEND_ENV, raising=False)
    client = FakeClient()
    result = runway.generate_candidates("x", tmp_path / "out", n=2,
                                        db_path=tmp_db, client=client)
    assert result["ok"] is False
    assert "not approved" in result["error"]
    assert runway.SPEND_ENV in result["error"]        # says how to approve
    assert "$" in result["error"]                     # and what it would cost
    assert client.calls == []                         # the SDK was never called
    assert fake_download == []
    with generative.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0


# ---------- generate_video: the thin wrapper ----------

def test_generate_video_downloads_the_output(tmp_path, approved, fake_download):
    client = FakeClient()
    out = runway.generate_video("a drawer closing", tmp_path / "clip.mp4", client=client)
    assert out.is_file()
    assert fake_download == ["https://fake.runway/clip.mp4"]
    call = client.calls[0]
    assert call["prompt_text"] == "a drawer closing"
    assert call["ratio"] == "720:1280"                # 9:16 by default
    assert "prompt_image" not in call                 # text-to-video omits it


def test_generate_video_empty_output_raises(tmp_path, approved, fake_download):
    client = FakeClient(outputs=())
    with pytest.raises(RuntimeError, match="no output"):
        runway.generate_video("x", tmp_path / "c.mp4", client=client)


# ---------- generate_candidates: the never-raises edge ----------

def test_candidates_land_and_every_attempt_is_logged(tmp_db, tmp_path,
                                                     approved, fake_download):
    client = FakeClient()
    result = runway.generate_candidates("a drawer closing", tmp_path / "out",
                                        n=2, db_path=tmp_db, client=client)
    assert result["ok"] is True
    assert len(result["candidates"]) == 2
    with generative.connect(tmp_db) as conn:
        rows = conn.execute(
            "SELECT tool, attempt FROM generations ORDER BY attempt").fetchall()
    assert [(r["tool"], r["attempt"]) for r in rows] == [("runway", 1), ("runway", 2)]
    assert runway.generations_today(db_path=tmp_db) == 2
    assert result["error"] is None


def test_candidates_never_raises_on_a_dead_sdk(tmp_db, tmp_path, approved, monkeypatch):
    monkeypatch.setenv("RUNWAYML_API_SECRET", "SECRET123")

    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("sdk exploded SECRET123")

    result = runway.generate_candidates("x", tmp_path / "out", n=1,
                                        db_path=tmp_db, client=Boom())
    assert result["ok"] is False
    assert "SECRET123" not in (result["error"] or "")   # redacted


def test_daily_cap_blocks_before_any_call(tmp_db, tmp_path, approved,
                                          fake_download, monkeypatch):
    monkeypatch.setattr(runway, "DAILY_CAP", 1)
    client = FakeClient()
    first = runway.generate_candidates("x", tmp_path / "a", n=1,
                                       db_path=tmp_db, client=client)
    assert first["ok"] is True

    second = runway.generate_candidates("x", tmp_path / "b", n=1,
                                        db_path=tmp_db, client=client)
    assert second["ok"] is False
    assert "daily cap" in second["error"]
    assert len(client.calls) == 1            # the second batch never called the SDK


def test_partial_failure_keeps_what_landed(tmp_db, tmp_path, approved, fake_download):
    client = FakeClient()
    real_create = client._create
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return real_create(**kwargs)

    client.image_to_video = SimpleNamespace(create=flaky)

    result = runway.generate_candidates("x", tmp_path / "out", n=2,
                                        db_path=tmp_db, client=client)
    assert result["ok"] is True              # partial success is success
    assert len(result["candidates"]) == 1
    assert "candidate 1" in result["error"]


def test_estimate_cost_prices_by_model_and_duration():
    # gen4_turbo: 5 credits/s * $0.01 -- a 5s clip is $0.25
    assert runway.estimate_cost(1, model="gen4_turbo", duration=5) == 0.25
    assert runway.estimate_cost(2, model="gen4.5", duration=10) == 2.40
    # an unknown model prices at the most expensive known rate, never free
    assert runway.estimate_cost(1, model="mystery", duration=5) == 0.60

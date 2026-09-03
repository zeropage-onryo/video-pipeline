"""
Tests for src/veo.py -- the Veo connector.

Fully hermetic: the SDK is a fake client object, conftest blocks the
network, and no test may reach Veo (it would bill real money). The
generations table runs against a throwaway DB.
"""
from types import SimpleNamespace

import pytest

from src import generative, veo


@pytest.fixture
def tmp_db(pg):
    path = pg
    generative.init(path)
    return path


class FakeVideoFile:
    def __init__(self):
        self.saved_to = None

    def save(self, out_path):
        self.saved_to = out_path
        with open(out_path, "wb") as f:
            f.write(b"\x00" * 2048)   # big enough to pass the size QC


class FakeClient:
    """Submit returns a not-done operation; the poll finishes it."""

    def __init__(self, polls_needed=1, videos=1):
        self.polls = 0
        self.polls_needed = polls_needed
        self.downloaded = []
        video_files = [SimpleNamespace(video=FakeVideoFile()) for _ in range(videos)]
        self._op = SimpleNamespace(
            done=False, response=SimpleNamespace(generated_videos=video_files))
        self.models = SimpleNamespace(generate_videos=self._generate)
        self.operations = SimpleNamespace(get=self._get)
        self.files = SimpleNamespace(download=lambda file: self.downloaded.append(file))

    def _generate(self, model, prompt, config, **kw):
        self.last = {"model": model, "prompt": prompt, "config": config}
        return self._op

    def _get(self, operation):
        self.polls += 1
        if self.polls >= self.polls_needed:
            operation.done = True
        return operation


@pytest.fixture(autouse=True)
def spend_ok(monkeypatch):
    """Every test below approves the spend, runway's pattern: the gate
    has its own tests at the bottom, and none of these is about it."""
    monkeypatch.setenv(veo.SPEND_ENV, "1")


# ---------- generate_video: the thin wrapper ----------

def test_generate_video_polls_until_done_and_saves(tmp_path):
    client = FakeClient(polls_needed=2)
    out = veo.generate_video("a drawer closing", tmp_path / "clip.mp4",
                             client=client, poll_delay=0)
    assert out.is_file()
    assert client.polls == 2
    assert client.last["prompt"] == "a drawer closing"
    assert client.last["config"].aspect_ratio == "9:16"


def test_generate_video_times_out_rather_than_polling_forever(tmp_path):
    client = FakeClient(polls_needed=10**9)
    with pytest.raises(TimeoutError):
        veo.generate_video("x", tmp_path / "c.mp4", client=client,
                           poll_delay=0, timeout_s=0)


def test_generate_video_empty_response_raises(tmp_path):
    client = FakeClient(videos=0)
    with pytest.raises(RuntimeError, match="no video"):
        veo.generate_video("x", tmp_path / "c.mp4", client=client, poll_delay=0)


# ---------- generate_candidates: the never-raises edge ----------

def test_candidates_land_and_every_attempt_is_logged(tmp_db, tmp_path):
    client = FakeClient()
    result = veo.generate_candidates("a drawer closing", tmp_path / "out",
                                     n=2, db_path=tmp_db, client=client, poll_delay=0)
    assert result["ok"] is True
    assert len(result["candidates"]) == 2
    # every attempt is a generations row -- the log attempts_to_keeper
    # and the scoreboard read once a keeper is picked
    with generative.connect(tmp_db) as conn:
        rows = conn.execute(
            "SELECT tool, attempt, output_path FROM generations ORDER BY attempt"
        ).fetchall()
    assert [(r["tool"], r["attempt"]) for r in rows] == [("veo", 1), ("veo", 2)]
    assert veo.generations_today(db_path=tmp_db) == 2
    assert result["error"] is None


def test_candidates_never_raises_on_a_dead_sdk(tmp_db, tmp_path):
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("sdk exploded key=SECRET123")

    result = veo.generate_candidates("x", tmp_path / "out", n=1,
                                     db_path=tmp_db, client=Boom())
    assert result["ok"] is False
    assert "SECRET123" not in (result["error"] or "")   # redacted


def test_daily_cap_blocks_before_any_call(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(veo, "DAILY_CAP", 1)
    client = FakeClient()
    first = veo.generate_candidates("x", tmp_path / "a", n=1,
                                    db_path=tmp_db, client=client, poll_delay=0)
    assert first["ok"] is True

    second = veo.generate_candidates("x", tmp_path / "b", n=1,
                                     db_path=tmp_db, client=client, poll_delay=0)
    assert second["ok"] is False
    assert "daily cap" in second["error"]
    assert len(client.downloaded) == 1       # the second batch never called the SDK


def test_partial_failure_keeps_what_landed(tmp_db, tmp_path):
    calls = {"n": 0}
    client = FakeClient()
    real_generate = client.models.generate_videos

    def flaky(model, prompt, config, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        client._op.done = False   # reset for the second candidate
        return real_generate(model=model, prompt=prompt, config=config, **kw)

    client.models = SimpleNamespace(generate_videos=flaky)

    result = veo.generate_candidates("x", tmp_path / "out", n=2,
                                     db_path=tmp_db, client=client, poll_delay=0)
    assert result["ok"] is True              # partial success is success
    assert len(result["candidates"]) == 1
    assert "candidate 1" in result["error"]


def test_estimate_cost_scales(tmp_db):
    assert veo.estimate_cost(3) == round(3 * veo.COST_PER_CLIP_USD, 2)

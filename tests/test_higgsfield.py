"""
Tests for src/higgsfield.py -- the Higgsfield Cloud connector, STILLS ONLY
since 2026-09-26 (fal became the only video renderer; the video path and
its tests went with it -- docs/tasks/task-fal-only.md).

Fully hermetic: the HTTP round-trip is a fake injected via the `http`
parameter (conftest blocks the network anyway), downloads are patched,
and the generations table runs against a throwaway DB. The spend gate
(HIGGSFIELD_SPEND_OK): approval is opt-in per test, refusal is the default
-- same as production.
"""
import pytest

from src import generative, higgsfield


@pytest.fixture
def tmp_db(pg):
    path = pg
    generative.init(path)
    return path


@pytest.fixture
def approved(monkeypatch):
    monkeypatch.setenv(higgsfield.SPEND_ENV, "1")


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_API_KEY_ID", "kid")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_SECRET", "ksecret")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(higgsfield, "POLL_SECONDS", 0)


@pytest.fixture
def fake_download(monkeypatch):
    downloaded = []

    def _fake(url, out_path):
        downloaded.append(url)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 2048)

    monkeypatch.setattr(higgsfield, "_download", _fake)
    return downloaded


STATUS_URL = "https://api.higgsfield.ai/requests/r1/status"


class FakeHttp:
    """Submit returns the queued job; polling the status_url returns the
    documented lifecycle -- a terminal status carrying the output."""

    def __init__(self, statuses=("completed",),
                 output="https://cdn.higgsfield.ai/out/still.jpg",
                 key="images"):
        self.calls = []
        self._statuses = list(statuses)
        self._output = output
        self._key = key

    def __call__(self, url, payload=None):
        self.calls.append((url, payload))
        if payload is not None:
            return {"status": "queued", "request_id": "r1",
                    "status_url": STATUS_URL,
                    "cancel_url": "https://api.higgsfield.ai/requests/r1/cancel"}
        status = (self._statuses.pop(0) if len(self._statuses) > 1
                  else self._statuses[0])
        state = {"status": status, "request_id": "r1",
                 "status_url": STATUS_URL,
                 "cancel_url": "https://api.higgsfield.ai/requests/r1/cancel"}
        if status in higgsfield.DONE_STATUSES:
            state[self._key] = [{"url": self._output}]
        return state


# ---------- the deadline, which must be the one actually in force ----------

def test_the_timeout_env_var_still_works_after_the_module_is_imported(
        tmp_path, approved, keys, monkeypatch):
    """THE BUG THIS PINS. `_submit_and_wait` carried
    `timeout_s: int = TIMEOUT_SECONDS`, and a default argument binds at
    IMPORT: setting HIGGSFIELD_TIMEOUT_S afterwards silently did nothing
    and a test that patched the constant patched a name the poll loop no
    longer read. The operator shortens the timeout, the loop hangs for
    the old one, and nothing anywhere says so.

    Set to zero, the very first poll is past the deadline -- so this
    test either raises immediately or hangs for ten minutes, which is
    exactly the difference it is here to detect.
    """
    monkeypatch.setenv("HIGGSFIELD_TIMEOUT_S", "0")
    http = FakeHttp(statuses=("queued",))
    with pytest.raises(RuntimeError, match="still queued after 0s"):
        higgsfield.generate_image("x", tmp_path / "a.jpg", http=http)
    assert higgsfield.timeout_seconds() == 0


def test_the_shipped_default_stands_when_the_environment_says_nothing(
        monkeypatch):
    monkeypatch.delenv("HIGGSFIELD_TIMEOUT_S", raising=False)
    assert higgsfield.timeout_seconds() == higgsfield.TIMEOUT_SECONDS
    monkeypatch.setattr(higgsfield, "TIMEOUT_SECONDS", 7)
    assert higgsfield.timeout_seconds() == 7, "the constant is still patchable"


def test_a_junk_timeout_falls_back_rather_than_refusing_to_render(monkeypatch):
    """A deadline is not worth failing a render over: `soon` is not a
    number, and 600 seconds is a better answer than a stack trace."""
    monkeypatch.setenv("HIGGSFIELD_TIMEOUT_S", "soon")
    assert higgsfield.timeout_seconds() == higgsfield.TIMEOUT_SECONDS


def test_an_explicit_timeout_argument_still_wins(tmp_path, approved, keys,
                                                 monkeypatch):
    """The env var is the fallback, not an override -- a caller that
    passes a deadline gets the one it asked for."""
    monkeypatch.setenv("HIGGSFIELD_TIMEOUT_S", "9999")
    http = FakeHttp(statuses=("queued",))
    with pytest.raises(RuntimeError, match="still queued after 0s"):
        higgsfield._submit_and_wait("/v1/text2video", {}, http=http, timeout_s=0)


# ---------- the thin wrapper (Soul stills) ----------


def test_a_failed_job_says_why(tmp_path, approved, keys):
    http = FakeHttp(statuses=("nsfw",))
    with pytest.raises(RuntimeError, match="nsfw"):
        higgsfield.generate_image("x", tmp_path / "a.jpg", http=http)


def test_a_finished_job_with_no_output_url_is_an_error_not_a_zero_byte_file(
        tmp_path, approved, keys, fake_download):
    """A terminal status carrying nothing downloadable must fail loudly.
    The alternative -- a 0-byte file -- costs the credit AND hides the
    reason."""

    class Empty:
        def __call__(self, url, payload=None):
            if payload is not None:
                return {"status": "queued", "status_url": STATUS_URL,
                        "cancel_url": "https://api.higgsfield.ai/requests/r1/cancel"}
            return {"status": "completed", "status_url": STATUS_URL,
                    "cancel_url": "https://api.higgsfield.ai/requests/r1/cancel"}

    with pytest.raises(RuntimeError, match="no image URL"):
        higgsfield.generate_image("x", tmp_path / "a.jpg", http=Empty())
    assert fake_download == []


def test_the_control_urls_are_never_mistaken_for_the_output():
    """status_url and cancel_url are http strings in every payload --
    downloading one yields JSON that passes as a file."""
    state = {"status": "completed", "status_url": STATUS_URL,
             "cancel_url": "https://api.higgsfield.ai/requests/r1/cancel"}
    assert higgsfield._output_url(state, {STATUS_URL, state["cancel_url"]}) is None


def test_documented_image_shape_is_read(tmp_path, approved, keys, fake_download):
    http = FakeHttp(statuses=("completed",), key="images",
                    output="https://cdn.higgsfield.ai/out/still.jpg")
    higgsfield.generate_image("editorial portrait", tmp_path / "a.jpg", http=http)
    assert fake_download == ["https://cdn.higgsfield.ai/out/still.jpg"]
    assert http.calls[0][0] == higgsfield.HOST + higgsfield.SOUL_PATH


# ---------- the walls that count ----------


def test_the_credentials_never_reach_an_error_string(keys):
    text = higgsfield._safe_error(RuntimeError("bad Key kid:ksecret rejected"))
    assert "ksecret" not in text and "kid" not in text


# ---------- Cloudflare ----------

def test_requests_carry_a_browser_user_agent(keys, monkeypatch):
    """api.higgsfield.ai is behind Cloudflare, which 403s urllib's default
    "Python-urllib/3.x" signature before Higgsfield ever sees the call --
    an auth failure that is not one. Verified live 2026-08-31."""
    seen = {}

    class FakeResponse:
        def read(self):
            return b'{"status": "queued"}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return FakeResponse()

    monkeypatch.setattr(higgsfield.urllib.request, "urlopen", fake_urlopen)
    higgsfield._request("https://api.higgsfield.ai/x", {"prompt": "p"})
    ua = seen["headers"].get("User-agent".lower(), "")
    assert ua and "python-urllib" not in ua.lower()
    assert seen["headers"]["authorization"].startswith("Key ")


def test_unapproved_still_raises_and_costs_no_call(tmp_path, keys, monkeypatch):
    monkeypatch.delenv(higgsfield.SPEND_ENV, raising=False)
    http = FakeHttp()
    with pytest.raises(RuntimeError, match="not approved"):
        higgsfield.generate_image("x", tmp_path / "a.jpg", http=http)
    assert http.calls == []


def test_the_video_path_is_gone():
    """fal is the only video renderer since 2026-09-26. Nothing here may
    grow a clip path back without going through providers.REQUIRED."""
    for name in ("generate_video", "generate_candidates", "generate_for_shot",
                 "generate_from_prompt", "VIDEO_MODELS"):
        assert not hasattr(higgsfield, name), name

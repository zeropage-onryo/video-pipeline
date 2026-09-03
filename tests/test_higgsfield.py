"""
Tests for src/higgsfield.py -- the Higgsfield Cloud connector.

Fully hermetic: the HTTP round-trip is a fake injected via the `http`
parameter (conftest blocks the network anyway), downloads are patched,
and the generations table runs against a throwaway DB. The spend gate
(HIGGSFIELD_SPEND_OK) mirrors runway.py's: approval is opt-in per test,
refusal is the default -- same as production.

What these actually guard:
- the two walls (per-run approval, daily cap) hold on every entry point,
  and refusing costs zero API calls;
- build_body only ever sends fields the chosen endpoint declares -- the
  reason a model registry exists rather than one hardcoded payload;
- the connector satisfies orchestrator.generate_render's interface, so
  a HIGGSFIELD shot stops parking as "no adapter wired";
- a reference that could not be made fetchable is recorded as ABSENT,
  never claimed.
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
                 output="https://cdn.higgsfield.ai/out/clip.mp4",
                 key="videos"):
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


# ---------- the request body: the registry is the point ----------

def test_body_carries_only_fields_the_endpoint_declares():
    """kling takes no aspect_ratio/resolution. Sending them anyway is
    how a render dies on a 422 after the queue wait."""
    path, body = higgsfield.build_body("a shot", model="kling2.5")
    assert path == "/kling-video/v2.5-turbo/pro/text-to-video"
    assert set(body) <= {"prompt", "duration", "cfg_scale", "negative_prompt"}
    assert "aspect_ratio" not in body and "resolution" not in body


def test_house_negatives_reach_the_model_that_has_a_field_for_them():
    _, body = higgsfield.build_body("a shot", model="kling2.5",
                                    negative_prompt="no logos")
    assert body["negative_prompt"] == "no logos"


def test_duration_is_clamped_into_the_models_own_range():
    _, kling = higgsfield.build_body("x", model="kling2.5", duration=99)
    assert kling["duration"] == 10
    _, short = higgsfield.build_body("x", model="kling2.5", duration=1)
    assert short["duration"] == 5


def test_a_reference_routes_to_the_image_to_video_path():
    path, body = higgsfield.build_body("x", model="kling2.5",
                                       image_url="https://cdn/i.png")
    assert path.endswith("/image-to-video")
    assert body["image_url"] == "https://cdn/i.png"
    text_path, text_body = higgsfield.build_body("x", model="kling2.5")
    assert text_path.endswith("/text-to-video")
    assert "image_url" not in text_body


def test_kling_gets_no_aspect_ratio_so_vertical_must_come_from_a_keyframe():
    """kling declares no aspect_ratio field. Sending 9:16 anyway would be
    a lie the house format depends on -- the vertical frame has to come
    from the keyframe through image-to-video."""
    _, body = higgsfield.build_body("x", model="kling2.5")
    assert "aspect_ratio" not in body


def test_unknown_model_raises_before_any_call():
    with pytest.raises(ValueError, match="model must be one of"):
        higgsfield.build_body("x", model="sora")


# ---------- the spend gate ----------

def test_unapproved_video_raises_and_points_at_the_app(tmp_path, keys, monkeypatch):
    monkeypatch.delenv(higgsfield.SPEND_ENV, raising=False)
    http = FakeHttp()
    with pytest.raises(RuntimeError, match="Higgsfield app"):
        higgsfield.generate_video("x", tmp_path / "a.mp4", http=http)
    assert http.calls == []                       # the API was never touched


def test_unapproved_edge_refuses_and_logs_nothing(tmp_db, keys, monkeypatch):
    monkeypatch.delenv(higgsfield.SPEND_ENV, raising=False)
    result = higgsfield.generate_from_prompt("x", db_path=tmp_db)
    assert result["ok"] is False
    assert higgsfield.SPEND_ENV in result["error"]
    with generative.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0


def test_candidates_refuse_without_approval_and_price_the_run(tmp_db, keys,
                                                              monkeypatch, tmp_path):
    monkeypatch.delenv(higgsfield.SPEND_ENV, raising=False)
    result = higgsfield.generate_candidates("x", tmp_path, n=2, db_path=tmp_db)
    assert result["ok"] is False and result["candidates"] == []
    assert "$" in result["error"]                 # the dollars are named up front


def test_missing_key_is_a_result_not_an_exception(tmp_db, monkeypatch, tmp_path):
    for name in ("HIGGSFIELD_API_KEY_ID", "HIGGSFIELD_API_KEY_SECRET",
                 "HF_API_KEY_ID", "HF_API_KEY_SECRET"):
        monkeypatch.delenv(name, raising=False)
    result = higgsfield.generate_candidates("x", tmp_path, n=1, db_path=tmp_db)
    assert result["ok"] is False
    assert "not configured" in result["error"]


# ---------- the thin wrapper ----------

def test_generate_video_submits_polls_and_downloads(tmp_path, approved, keys,
                                                    fake_download):
    http = FakeHttp(statuses=("queued", "in_progress", "completed"))
    out = higgsfield.generate_video("a close shot", tmp_path / "a.mp4",
                                    model="kling2.5", http=http)
    assert out.is_file()
    assert fake_download == ["https://cdn.higgsfield.ai/out/clip.mp4"]
    submit_url, submit_body = http.calls[0]
    assert submit_url == higgsfield.HOST + "/kling-video/v2.5-turbo/pro/text-to-video"
    assert submit_body["prompt"] == "a close shot"
    assert http.calls[1][0] == STATUS_URL          # polled what submit returned


def test_a_failed_job_says_why(tmp_path, approved, keys):
    http = FakeHttp(statuses=("nsfw",))
    with pytest.raises(RuntimeError, match="nsfw"):
        higgsfield.generate_video("x", tmp_path / "a.mp4", http=http)


def test_a_finished_job_with_no_output_url_is_an_error_not_a_zero_byte_file(
        tmp_path, approved, keys, fake_download):
    """A terminal status carrying nothing downloadable must fail loudly.
    The alternative -- a 0-byte .mp4 that qc_clip later rejects -- costs
    the credit AND hides the reason."""

    class Empty:
        def __call__(self, url, payload=None):
            if payload is not None:
                return {"status": "queued", "status_url": STATUS_URL,
                        "cancel_url": "https://api.higgsfield.ai/requests/r1/cancel"}
            return {"status": "completed", "status_url": STATUS_URL,
                    "cancel_url": "https://api.higgsfield.ai/requests/r1/cancel"}

    with pytest.raises(RuntimeError, match="no output URL"):
        higgsfield.generate_video("x", tmp_path / "a.mp4", http=Empty())
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

def test_daily_cap_is_counted_from_the_generations_table(tmp_db, approved, keys,
                                                         monkeypatch, tmp_path):
    monkeypatch.setattr(higgsfield, "DAILY_CAP", 1)
    monkeypatch.setattr(higgsfield, "_download",
                        lambda url, out: (out.parent.mkdir(parents=True, exist_ok=True),
                                          out.write_bytes(b"\x00" * 2048)))
    first = higgsfield.generate_candidates("x", tmp_path / "a", n=1,
                                           db_path=tmp_db, http=FakeHttp())
    assert first["ok"] is True
    assert higgsfield.generations_today(db_path=tmp_db) == 1
    second = higgsfield.generate_candidates("x", tmp_path / "b", n=1,
                                            db_path=tmp_db, http=FakeHttp())
    assert second["ok"] is False and "daily cap" in second["error"]


def test_every_attempt_is_logged_as_higgsfield(tmp_db, approved, keys,
                                               fake_download, tmp_path):
    higgsfield.generate_candidates("x", tmp_path / "a", n=1, db_path=tmp_db,
                                   http=FakeHttp())
    with generative.connect(tmp_db) as conn:
        tools = [r[0] for r in conn.execute("SELECT tool FROM generations")]
    assert tools == ["higgsfield"]


def test_a_dead_candidate_does_not_take_the_run_down(tmp_db, approved, keys,
                                                     tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(higgsfield, "generate_video", boom)
    result = higgsfield.generate_candidates("x", tmp_path, n=1, db_path=tmp_db)
    assert result["ok"] is False
    assert "upstream 500" in result["error"]


def test_the_credentials_never_reach_an_error_string(keys):
    text = higgsfield._safe_error(RuntimeError("bad Key kid:ksecret rejected"))
    assert "ksecret" not in text and "kid" not in text


# ---------- the orchestrator contract ----------

def test_connector_matches_the_interface_the_nightly_graph_calls():
    """orchestrator.generate_render looks a module up by tool name and
    calls generate_candidates(prompt, out_dir, n=, db_path=). If this
    drifts from runway's, a HIGGSFIELD shot parks again."""
    import inspect

    from src import runway
    ours = inspect.signature(higgsfield.generate_candidates).parameters
    theirs = inspect.signature(runway.generate_candidates).parameters
    assert {"prompt", "out_dir", "n", "shot_id", "db_path"} <= set(ours)
    assert {"prompt", "out_dir", "n"} <= set(theirs) <= set(theirs)


def test_higgsfield_is_wired_into_the_nightly_graph():
    import inspect

    from src import orchestrator
    source = inspect.getsource(orchestrator.generate_render)
    assert '"HIGGSFIELD": higgsfield' in source


def test_the_registry_covers_every_tool_zeropage_actually_plans_for():
    from src.shootgen import ZEROPAGE_AI_TOOLS
    assert "HIGGSFIELD" in ZEROPAGE_AI_TOOLS


# ---------- references: a URL or nothing, never a lie ----------

def test_a_public_url_passes_straight_through():
    assert higgsfield.as_image_url("https://cdn/i.png") == "https://cdn/i.png"


def test_a_data_uri_is_refused_because_their_server_must_fetch_it():
    """Runway takes an inline data: URI; Higgsfield takes image_url, a
    URL it fetches. Passing a data URI would spend a credit on a
    reference that never arrives."""
    assert higgsfield.as_image_url("data:image/png;base64,AAAA") is None


def test_a_local_keyframe_without_storage_is_dropped_not_faked(monkeypatch):
    from src import storage
    monkeypatch.setattr(storage, "configured", lambda: False)
    assert higgsfield.as_image_url(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64) is None


def test_the_generation_row_records_the_anchor_that_was_actually_sent(
        tmp_db, approved, keys, fake_download, monkeypatch):
    import json

    from src import storage
    monkeypatch.setattr(storage, "configured", lambda: False)
    result = higgsfield.generate_from_prompt(
        "x", reference_image=b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        db_path=tmp_db, http=FakeHttp())
    assert result["ok"] is True
    with generative.connect(tmp_db) as conn:
        params = conn.execute("SELECT params_json FROM generations").fetchone()[0]
    assert json.loads(params)["prompt_image"] is False


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


# ---------- availability, probed live 2026-08-31 ----------

def test_the_default_model_is_one_the_account_can_actually_reach():
    """DEFAULT_MODEL was seedance-pro until a live probe showed seedance
    and veo return 404 model_not_found on this key. A default that 404s
    means every render fails on the first call."""
    assert higgsfield.DEFAULT_MODEL in higgsfield.AVAILABLE_MODELS


def test_an_unreachable_model_refuses_before_the_round_trip():
    for model in ("seedance-pro", "seedance-lite", "veo3.1", "veo3.1-fast"):
        with pytest.raises(ValueError, match="model_not_found"):
            higgsfield.build_body("x", model=model)


def test_only_kling_is_currently_reachable():
    assert set(higgsfield.AVAILABLE_MODELS) == {"kling2.5", "kling2.1"}

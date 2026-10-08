"""
Tests for src/fal.py -- the fal.ai queue connector, and the four dormant
platforms it wakes.

Fully hermetic: the HTTP round-trip is a fake injected through the `http`
seam (conftest blocks the network anyway), downloads are patched, and the
generations table runs against a throwaway Postgres. The spend gate
(FAL_SPEND_OK) mirrors runway/higgsfield's: approval is opt-in per test,
refusal is the default -- same as production.

What these actually guard:
- the whole documented lifecycle, IN_QUEUE -> IN_PROGRESS -> COMPLETED ->
  fetch the response_url -> download, including the SECOND request fal
  needs that higgsfield does not;
- **failure with no failure status**. fal documents three states and none
  of them means "failed", so a dead job surfaces as an HTTP error or an
  error payload on a COMPLETED response. Both are tested, because a
  poller written against a FAILED string would pass every happy-path test
  and hang or lie on the only case that matters;
- a job that never terminates hits the deadline and RAISES rather than
  holding the night open;
- the key never reaches an error string, and it is only ever the
  operator's (per-account keys were removed 2026-09-26);
- both walls (cap, spend approval) refuse before a single HTTP call;
- a KLING / LTX / WAN / SEEDANCE / VEO shot renders and logs a row under
  its own tool name with a key_source, instead of parking as "no adapter
  wired" -- and a retired RUNWAY / HIGGSFIELD shot renders on fal's default.
"""
import json

import pytest

from src import db, fal, generative, preprod


@pytest.fixture
def tmp_db(pg):
    generative.init(pg)
    return pg


@pytest.fixture
def approved(monkeypatch):
    monkeypatch.setenv(fal.SPEND_ENV, "1")


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "fal-secret-key")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(fal, "POLL_SECONDS", 0)


@pytest.fixture
def fake_download(monkeypatch):
    downloaded = []

    def _fake(url, out_path):
        downloaded.append(url)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 2048)

    monkeypatch.setattr(fal, "_download", _fake)
    return downloaded


STATUS_URL = "https://queue.fal.run/fal-ai/x/requests/r1/status"
RESPONSE_URL = "https://queue.fal.run/fal-ai/x/requests/r1"
CANCEL_URL = "https://queue.fal.run/fal-ai/x/requests/r1/cancel"


class FakeHttp:
    """Submit returns the queue receipt; the status_url walks the three
    documented states; the response_url returns the model payload."""

    def __init__(self, statuses=("COMPLETED",),
                 output="https://v3.fal.media/files/out/clip.mp4",
                 result=None, status_error=None):
        self.calls = []
        self._statuses = list(statuses)
        self._output = output
        self._result = result
        self._status_error = status_error

    def _receipt(self, status):
        return {"status": status, "request_id": "r1",
                "status_url": STATUS_URL, "response_url": RESPONSE_URL,
                "cancel_url": CANCEL_URL}

    def __call__(self, url, payload=None):
        self.calls.append((url, payload))
        if payload is not None:
            return {**self._receipt(fal.STATUS_QUEUED), "queue_position": 3}
        if url == STATUS_URL:
            status = (self._statuses.pop(0) if len(self._statuses) > 1
                      else self._statuses[0])
            state = self._receipt(status)
            if self._status_error:
                state.update(self._status_error)
            return state
        if self._result is not None:
            return self._result
        return {"video": {"url": self._output}}

    @property
    def status_polls(self):
        return [u for u, p in self.calls if p is None and u == STATUS_URL]


# ---------- the dated model table ----------

def test_every_model_entry_is_dated_and_sourced():
    """shot.py's camera maps carry a dated verification comment; so does
    this table, and a machine can check that the fields are there even if
    it cannot check that the price is still right."""
    for name, spec in fal.VIDEO_MODELS.items():
        assert spec["checked"], f"{name} has no checked date"
        assert spec["source"].startswith("https://fal.ai/"), name
        assert spec["prices"], name
        assert spec["default_resolution"] in spec["prices"], name
        assert spec["platform"] in fal.PLATFORM_MODELS, name


def test_estimate_cost_matches_the_table():
    """Per-second, times duration, times n. If the table is re-dated with
    new numbers this test is what says the estimate followed."""
    # LTX-2.3 renders 6/8/10s only, so a 5s ask is priced as the 6s it gets
    assert fal.estimate_cost(1, model="ltx2.3", duration=5) == 0.36
    assert fal.estimate_cost(1, model="ltx2.3", duration=6) == 0.36
    assert fal.estimate_cost(2, model="ltx2.3", duration=6) == 0.72
    assert fal.estimate_cost(1, model="ltx2.3", duration=10) == 0.60
    assert fal.estimate_cost(1, model="ltx2.3", duration=6,
                             resolution="2160p") == 1.44
    assert fal.estimate_cost(1, model="kling3-turbo-pro", duration=5) == 0.70
    assert fal.estimate_cost(1, model="wan3", duration=5) == 0.50
    assert fal.estimate_cost(1, model="seedance2-fast", duration=5) == 1.2095
    assert fal.estimate_cost(1, model="veo3.1", duration=8) == 3.20


def test_resolution_is_a_pricing_input_and_an_unknown_one_refuses():
    """Seedance 2.0 bills $0.3034/s at 720p and $0.682/s at 1080p on fal
    (2026-09-26). A 10s 1080p clip must never be priced at the 720p rate --
    and a tier the model has no rate for is refused, not defaulted."""
    at_720 = fal.estimate_cost(1, model="seedance2", duration=10, resolution="720p")
    at_1080 = fal.estimate_cost(1, model="seedance2", duration=10, resolution="1080p")
    assert (at_720, at_1080) == (3.034, 6.82)
    with pytest.raises(ValueError, match="no '4k' rate"):
        fal.estimate_cost(1, model="seedance2", duration=10, resolution="4k")
    # a model with no resolution field has one rate whatever is asked
    assert fal.price_per_second("kling3-turbo-pro", "720p") == 0.14


def test_a_price_can_be_overridden_by_env(monkeypatch):
    """The catalogue reprices; a repriced model must not need a code
    change to stop lying to the confirm dialog."""
    monkeypatch.setenv("FAL_PRICE_LTX2_3", "0.10")
    prices = fal._price_env("ltx2.3", {"1080p": 0.06, "2160p": 0.24})
    assert prices == {"1080p": 0.10, "2160p": 0.10}


def test_the_default_model_is_the_cheapest_one_in_the_table():
    """The default render is the cheapest clip there is -- what a card
    opens on and an empty approve spends."""
    cheapest = min(fal.MODELS, key=lambda m: fal.estimate_cost(1, model=m))
    assert fal.DEFAULT_MODEL == cheapest


# ---------- the request body ----------

def test_body_carries_only_fields_the_endpoint_declares():
    model_id, body = fal.build_body("a shot", model="kling3-turbo-pro",
                                    negative_prompt="no CGI")
    assert model_id == "fal-ai/kling-video/v3/turbo/pro/text-to-video"
    # the i2v schema carries neither negative_prompt nor cfg_scale
    assert set(body) == {"prompt", "duration", "aspect_ratio"}
    assert "resolution" not in body       # kling declares none


def test_duration_is_clamped_into_the_models_own_range():
    """Kling v3 turbo pro takes 3-15s, as a string enum."""
    _, long = fal.build_body("x", model="kling3-turbo-pro", duration=99)
    assert long["duration"] == "15"
    _, short = fal.build_body("x", model="kling3-turbo-pro", duration=1)
    assert short["duration"] == "3"


def test_an_enum_duration_is_fitted_up_and_sent_in_the_models_own_shape():
    """LTX-2.3 takes 6/8/10 (integers -- verified live 2026-09-26), Veo 3.1
    "4s"/"6s"/"8s", Wan a plain integer. An off-enum value is a refused request after a queue wait."""
    # an integer on the wire: "6" was refused live (422 literal_error)
    assert fal.build_body("x", model="ltx2.3", duration=5)[1]["duration"] == 6
    assert fal.build_body("x", model="ltx2.3", duration=7)[1]["duration"] == 8
    assert fal.build_body("x", model="ltx2.3", duration=30)[1]["duration"] == 10
    assert fal.build_body("x", model="veo3.1", duration=5)[1]["duration"] == "6s"
    assert fal.build_body("x", model="wan3", duration=5)[1]["duration"] == 5
    assert fal.fit_duration("ltx2.3", 3) == 6


def test_a_reference_routes_to_the_image_to_video_id_in_the_models_own_field():
    model_id, body = fal.build_body("x", model="wan3",
                                    image_url="https://cdn/i.png")
    assert model_id == "alibaba/wan-3.0/image-to-video"
    assert body["start_image_url"] == "https://cdn/i.png"   # Wan 3.0's name for it
    assert "image_url" not in body
    model_id, body = fal.build_body("x", model="ltx2.3", image_url="https://cdn/i.png")
    assert model_id == "fal-ai/ltx-2.3/image-to-video"
    assert body["image_url"] == "https://cdn/i.png"


def test_veo_is_a_fal_model_now():
    model_id, body = fal.build_body("x", model="veo3.1", image_url="https://cdn/i.png")
    assert model_id == "fal-ai/veo3.1/image-to-video"
    assert fal.build_body("x", model="veo3.1")[0] == "fal-ai/veo3.1"
    assert fal.PLATFORM_MODELS["veo"] == "veo3.1"


def test_aspect_ratio_is_sent_on_text_to_video_only():
    """Handed a 9:16 keyframe, every one of these models takes the frame
    from the image; a conflicting ratio beside it is either ignored or
    obeyed, and obeyed means a letterboxed clip nobody asked for."""
    _, t2v = fal.build_body("x", model="kling3-turbo-pro")
    assert t2v["aspect_ratio"] == "9:16"
    _, i2v = fal.build_body("x", model="kling3-turbo-pro",
                            image_url="https://cdn/i.png")
    assert "aspect_ratio" not in i2v


def test_unknown_model_raises_before_any_call():
    with pytest.raises(ValueError, match="model must be one of"):
        fal.build_body("x", model="sora")


# ---------- the spend gate and the cap: both refuse before HTTP ----------

def test_unapproved_video_raises_and_costs_no_round_trip(tmp_path, keys, monkeypatch):
    monkeypatch.delenv(fal.SPEND_ENV, raising=False)
    http = FakeHttp()
    with pytest.raises(RuntimeError, match="spend not approved"):
        fal.generate_video("x", tmp_path / "a.mp4", http=http)
    assert http.calls == []


def test_candidates_refuse_without_approval_and_price_the_run(
        tmp_db, keys, monkeypatch, tmp_path):
    monkeypatch.delenv(fal.SPEND_ENV, raising=False)
    http = FakeHttp()
    result = fal.generate_candidates("x", tmp_path, n=2, db_path=tmp_db, http=http)
    assert result["ok"] is False and result["candidates"] == []
    assert "$" in result["error"]              # the dollars are named up front
    assert http.calls == []


def test_missing_key_is_a_result_not_an_exception(tmp_db, monkeypatch, tmp_path):
    for name in ("FAL_KEY", "FAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    http = FakeHttp()
    result = fal.generate_candidates("x", tmp_path, n=1, db_path=tmp_db, http=http)
    assert result["ok"] is False
    assert "not configured" in result["error"]
    assert http.calls == []


def test_the_cap_refuses_before_a_single_http_call(tmp_db, approved, keys,
                                                   monkeypatch, tmp_path):
    """The wall is the DB's, not this process's -- and it has to be hit
    BEFORE the queue is touched or the credit is already committed."""
    monkeypatch.setattr(fal, "generations_today",
                        lambda *a, **k: fal.DAILY_CAP)
    http = FakeHttp()
    result = fal.generate_candidates("x", tmp_path, n=1, db_path=tmp_db, http=http)
    assert result["ok"] is False
    assert "daily cap" in result["error"]
    assert http.calls == []


def test_the_cap_counts_every_platform_fal_renders_for(tmp_db, approved, keys):
    """A row is logged under the platform (kling / ltx / ...), never under
    "fal", so a cap that read one label would count zero forever while the
    money went out."""
    from src.shot import Shot
    shot_id = generative.add_shot(Shot(subject="x", action="y"),
                                  dsn=tmp_db, account_id=None)
    for tool in ("kling", "wan"):
        generative.record_generation(shot_id, tool, "p", output_path="/tmp/a.mp4",
                                     dsn=tmp_db, account_id=None)
    assert fal.generations_today(db_path=tmp_db) == 2


# ---------- the wire ----------

def test_submit_polls_through_the_queue_and_downloads(tmp_path, approved, keys,
                                                      fake_download):
    http = FakeHttp(statuses=(fal.STATUS_QUEUED, fal.STATUS_RUNNING,
                              fal.STATUS_DONE))
    out = fal.generate_video("a close shot", tmp_path / "a.mp4",
                             model="kling3-turbo-pro", http=http)
    assert out.is_file()
    assert fake_download == ["https://v3.fal.media/files/out/clip.mp4"]

    submit_url, submit_body = http.calls[0]
    assert submit_url == (fal.HOST +
                          "/fal-ai/kling-video/v3/turbo/pro/text-to-video")
    assert submit_body["prompt"] == "a close shot"
    assert len(http.status_polls) == 3                 # queued, running, done
    assert http.calls[-1][0] == RESPONSE_URL           # the SECOND request


def test_the_result_is_a_separate_request_from_the_terminal_status(
        tmp_path, approved, keys, fake_download):
    """The one real shape difference from higgsfield: fal's COMPLETED
    status payload is a receipt, and the video lives behind response_url.
    Reading the output off the status payload would find nothing."""
    http = FakeHttp()
    fal.generate_video("x", tmp_path / "a.mp4", http=http)
    urls = [u for u, p in http.calls if p is None]
    assert urls == [STATUS_URL, RESPONSE_URL]


def test_an_http_error_at_submit_surfaces_and_nothing_is_polled(tmp_path,
                                                                approved, keys):
    import urllib.error

    calls = []

    def http(url, payload=None):
        calls.append(url)
        raise urllib.error.HTTPError(url, 422, "Unprocessable Entity", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        fal.generate_video("x", tmp_path / "a.mp4", http=http)
    assert len(calls) == 1


def test_a_failure_arrives_as_an_error_payload_on_a_completed_response(
        tmp_path, approved, keys):
    """THE contract fact worth a test of its own: fal documents no FAILED
    status. A dead job answers COMPLETED and carries `error` /
    `error_type`, so code that waits for a failure string waits forever
    and then reports a missing output URL for a job that actually failed
    with a reason."""
    http = FakeHttp(result={"error": "content policy violation",
                            "error_type": "ContentPolicy"})
    with pytest.raises(RuntimeError, match="content policy violation"):
        fal.generate_video("x", tmp_path / "a.mp4", http=http)


def test_an_error_on_the_status_poll_is_caught_too(tmp_path, approved, keys):
    http = FakeHttp(status_error={"error": "runner crashed"})
    with pytest.raises(RuntimeError, match="runner crashed"):
        fal.generate_video("x", tmp_path / "a.mp4", http=http)


def test_a_poll_that_never_terminates_raises_instead_of_hanging(
        tmp_path, approved, keys, monkeypatch):
    """There is no failure status to rescue this; the clock is the only
    wall, so it has to be a real one."""
    http = FakeHttp(statuses=(fal.STATUS_RUNNING,))
    monkeypatch.setattr(fal, "TIMEOUT_SECONDS", 0)
    with pytest.raises(RuntimeError, match="still IN_PROGRESS after"):
        fal.generate_video("x", tmp_path / "a.mp4", http=http)
    assert len(http.status_polls) >= 1


def test_an_unknown_status_keeps_waiting_rather_than_claiming_success(
        tmp_path, approved, keys, monkeypatch):
    """A fourth state is 'something we do not understand yet', not 'done'
    -- treating it as done fetches a result that is not there."""
    http = FakeHttp(statuses=("SOMETHING_NEW",))
    monkeypatch.setattr(fal, "TIMEOUT_SECONDS", 0)
    with pytest.raises(RuntimeError, match="still SOMETHING_NEW"):
        fal.generate_video("x", tmp_path / "a.mp4", http=http)
    assert RESPONSE_URL not in [u for u, _ in http.calls]


def test_a_completed_job_with_no_output_url_is_an_error_not_a_zero_byte_file(
        tmp_path, approved, keys, fake_download):
    http = FakeHttp(result={"seed": 12, "timings": {"inference": 4.2}})
    with pytest.raises(RuntimeError, match="no output URL"):
        fal.generate_video("x", tmp_path / "a.mp4", http=http)
    assert fake_download == []


def test_the_queue_urls_are_never_mistaken_for_the_output():
    """Every fal payload carries status/response/cancel URLs. A walk that
    took the first http string would 'succeed' by downloading JSON."""
    payload = {"status_url": STATUS_URL, "cancel_url": CANCEL_URL,
               "video": {"url": "https://v3.fal.media/out.mp4"}}
    assert fal._output_url(payload, {STATUS_URL, RESPONSE_URL, CANCEL_URL}) == \
        "https://v3.fal.media/out.mp4"


# ---------- redaction ----------

def test_the_env_key_never_reaches_an_error_string(keys):
    text = fal._safe_error(RuntimeError("401 for Key fal-secret-key"))
    assert "fal-secret-key" not in text


def test_only_the_operators_key_is_ever_used(monkeypatch):
    """Per-account keys were removed on 2026-09-26: whatever account asks,
    the credential is FAL_KEY from the environment."""
    monkeypatch.setenv("FAL_KEY", "operator-key")
    assert fal._credential(None) == "operator-key"
    assert fal._credential(12345) == "operator-key"
    monkeypatch.delenv("FAL_KEY")
    monkeypatch.delenv("FAL_API_KEY", raising=False)
    assert fal.has_key(12345) is False


# ---------- the logging edge ----------

def test_every_attempt_is_logged_under_the_platform_that_rendered_it(
        tmp_db, approved, keys, fake_download, tmp_path):
    http = FakeHttp()
    result = fal.generate_candidates("a shot", tmp_path, n=2, db_path=tmp_db,
                                     model="kling3-turbo-pro", http=http)
    assert result["ok"] is True and len(result["candidates"]) == 2
    with generative.connect(tmp_db) as conn:
        tools = [r[0] for r in conn.execute(
            "SELECT tool FROM generations ORDER BY id").fetchall()]
    assert tools == ["kling", "kling"]


def test_the_row_records_the_key_source(tmp_db, approved, keys, fake_download,
                                        tmp_path):
    """The ledger has to tell a render billed to the operator's key from
    one the customer already paid for on their own."""
    import json

    fal.generate_candidates("a shot", tmp_path, n=1, db_path=tmp_db,
                            model="ltx2.3", http=FakeHttp())
    with generative.connect(tmp_db) as conn:
        params = conn.execute(
            "SELECT params_json FROM generations ORDER BY id").fetchone()[0]
    assert json.loads(params)["key_source"] == fal.KEY_SOURCE


def test_a_dead_candidate_does_not_take_the_run_down(tmp_db, approved, keys,
                                                     fake_download, tmp_path):
    calls = {"n": 0}
    ok = FakeHttp()

    def flaky(url, payload=None):
        if payload is not None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("upstream 500")
        return ok(url, payload)

    result = fal.generate_candidates("x", tmp_path, n=2, db_path=tmp_db,
                                     http=flaky)
    assert result["ok"] is True
    assert len(result["candidates"]) == 1
    assert "upstream 500" in result["error"]


# ---------- the registry and the four dormant platforms ----------

def test_fal_conforms_to_the_provider_contract():
    from src import providers
    assert providers.conforms(fal) == []
    assert providers.VIDEO_PROVIDERS["fal"] is fal


def test_a_platform_connector_conforms_too():
    """orchestrator holds bindings, not the module, for the four platform
    names -- so a router handed one must behave like a module."""
    from src import providers
    assert providers.conforms(fal.connector("kling")) == []


def test_fal_is_the_whole_default_order():
    from src import providers
    assert providers.DEFAULT_ORDER == ("fal",)


def test_the_four_dormant_platforms_are_wired_into_the_nightly_graph():
    """The whole point. Every one of these had a prompt renderer in
    shot.PLATFORMS and no execution adapter, so a shot planned for it came
    back "no adapter wired" every single night."""
    import inspect

    from src import orchestrator
    source = inspect.getsource(orchestrator.generate_render)
    assert "fal.connector(name) for name in fal.PLATFORM_MODELS" in source
    assert set(fal.PLATFORM_MODELS) >= {"kling", "ltx", "wan", "seedance", "veo"}


def test_every_fal_platform_is_a_real_shot_platform():
    from src.shot import PLATFORMS
    for platform in fal.PLATFORM_MODELS:
        assert platform in PLATFORMS


@pytest.mark.parametrize("tool", ["KLING", "LTX", "WAN", "SEEDANCE", "VEO"])
def test_a_shot_on_a_dormant_platform_now_actually_renders(
        tool, tmp_db, approved, keys, fake_download, monkeypatch):
    """End to end through orchestrator.generate_render: the shot renders,
    the clip comes back ok, and the generations row names the platform."""
    import json

    from src import orchestrator

    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    monkeypatch.setattr(fal, "_request",
                        lambda *a, **k: pytest.fail("real HTTP"))
    http = FakeHttp()
    real = fal.generate_candidates

    def patched(prompt, out_dir, n=3, **kw):
        kw["http"] = http
        kw["db_path"] = tmp_db
        return real(prompt, out_dir, n, **kw)

    monkeypatch.setattr(fal, "generate_candidates", patched)

    state = orchestrator.generate_render(
        {"prompts": [{"tool": tool, "prompt": "a long enough prompt to render"}],
         "concept_id": 1})
    clip = state["clips"][0]
    assert clip["ok"] is True, clip.get("error")
    assert clip["tool"] == tool                    # shootgen's choice stands

    with generative.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT tool, params_json FROM generations ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row[0] == tool.lower()
    params = json.loads(row[1])
    assert params["provider"] == "fal"
    assert params["model"] == fal.PLATFORM_MODELS[tool.lower()]
    assert params["key_source"] == fal.KEY_SOURCE


def test_shootgens_tool_choice_is_still_authoritative(tmp_db, approved, keys,
                                                      fake_download, monkeypatch):
    """The registry only steps in on FAILURE (generate_render's own
    docstring). A KLING shot that renders must stay a KLING clip, not be
    relabelled with whatever choose_provider would have picked."""
    from src import orchestrator, providers

    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    monkeypatch.setattr(providers, "choose_provider",
                        lambda *a, **k: pytest.fail("failover ran on a success"))
    http = FakeHttp()
    real = fal.generate_candidates
    monkeypatch.setattr(
        fal, "generate_candidates",
        lambda prompt, out_dir, n=3, **kw: real(prompt, out_dir, n,
                                                **{**kw, "http": http,
                                                   "db_path": tmp_db}))
    state = orchestrator.generate_render(
        {"prompts": [{"tool": "KLING", "prompt": "a prompt"}], "concept_id": 2})
    assert state["clips"][0]["tool"] == "KLING"
    assert "failover_from" not in state["clips"][0]


def test_a_failed_fal_shot_does_not_fail_over_to_fal_again(monkeypatch, tmp_path):
    """The four platform names are all provider "fal". Excluding only the
    tool name would let the failover retry the same vendor through a
    different door."""
    from src import orchestrator, providers

    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    monkeypatch.setattr(
        fal, "generate_candidates",
        lambda *a, **k: {"ok": False, "candidates": [], "error": "boom"})
    seen = {}

    def spy(account_id=None, *, exclude=(), db_path=None):
        seen["exclude"] = exclude
        return None

    monkeypatch.setattr(providers, "choose_provider", spy)
    orchestrator.generate_render(
        {"prompts": [{"tool": "WAN", "prompt": "a prompt"}], "concept_id": 3})
    assert "fal" in seen["exclude"] and "wan" in seen["exclude"]


# ---------- images ----------

def test_images_are_priced_and_logged_apart_from_clips(tmp_db, approved, keys,
                                                       fake_download):
    """FLUX rides the same queue, key and gates, but it must never land in
    the video scoreboards or move the video cap."""
    http = FakeHttp(result={"images": [{"url": "https://v3.fal.media/i.png"}]})
    result = fal.generate_image_from_prompt("a still", db_path=tmp_db, http=http)
    assert result["ok"] is True, result["error"]
    with generative.connect(tmp_db) as conn:
        tool = conn.execute("SELECT tool FROM generations").fetchone()[0]
    assert tool == fal.IMAGE_LOG_TOOL == "fal"
    assert fal.generations_today(db_path=tmp_db) == 0      # the VIDEO cap is untouched
    assert fal.estimate_image_cost(1) == 0.04


def test_an_image_needs_the_same_spend_approval(tmp_path, keys, monkeypatch):
    monkeypatch.delenv(fal.SPEND_ENV, raising=False)
    http = FakeHttp()
    with pytest.raises(RuntimeError, match="spend not approved"):
        fal.generate_image("x", tmp_path / "a.png", http=http)
    assert http.calls == []


@pytest.mark.parametrize("tool", ["RUNWAY", "HIGGSFIELD"])
def test_a_shot_planned_for_a_retired_tool_renders_on_the_fal_default(
        tool, tmp_db, approved, keys, fake_download, monkeypatch):
    """A row written before 2026-09-26 may still say RUNWAY or HIGGSFIELD.
    The graph reads it as fal's default at render time -- it neither parks
    the shot nor rewrites the row."""
    import json

    from src import orchestrator

    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    http = FakeHttp()
    real = fal.generate_candidates

    def patched(prompt, out_dir, n=3, **kw):
        kw["http"] = http
        kw["db_path"] = tmp_db
        return real(prompt, out_dir, n, **kw)

    monkeypatch.setattr(fal, "generate_candidates", patched)
    state = orchestrator.generate_render(
        {"prompts": [{"tool": tool, "prompt": "a long enough prompt to render"}],
         "concept_id": 1})
    assert state["clips"][0]["ok"] is True, state["clips"][0].get("error")
    with generative.connect(tmp_db) as conn:
        params = json.loads(conn.execute(
            "SELECT params_json FROM generations ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert params["model"] == fal.DEFAULT_MODEL


# ---------- references: a URL or nothing, never a lie (from higgsfield) ----------

def test_a_public_url_passes_straight_through():
    assert fal.as_image_url("https://cdn/i.png") == "https://cdn/i.png"


def test_a_data_uri_is_refused_because_their_server_must_fetch_it():
    """fal takes an image URL it fetches. Passing a data URI would spend a
    credit on a reference that never arrives."""
    assert fal.as_image_url("data:image/png;base64,AAAA") is None


def test_a_local_keyframe_without_storage_is_dropped_not_faked(monkeypatch):
    from src import storage
    monkeypatch.setattr(storage, "configured", lambda: False)
    assert fal.as_image_url(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64) is None


def test_the_generation_row_records_the_anchor_that_was_actually_sent(
        tmp_db, approved, keys, fake_download, monkeypatch):
    import json

    from src import storage
    monkeypatch.setattr(storage, "configured", lambda: False)
    result = fal.generate_from_prompt(
        "x", reference_image=b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        db_path=tmp_db, http=FakeHttp(), approved=True)
    assert result["ok"] is True, result
    with generative.connect(tmp_db) as conn:
        params = conn.execute("SELECT params_json FROM generations").fetchone()[0]
    assert json.loads(params)["prompt_image"] is False


def test_an_http_error_carries_fals_reason(monkeypatch):
    """The first live render failed as a bare "HTTP Error 422". fal puts
    the reason in the body; the error has to carry it to the card and row."""
    import io
    import urllib.error
    import urllib.request

    monkeypatch.setenv("FAL_KEY", "fal-secret-key")
    body = b'{"detail":[{"loc":["body","duration"],"msg":"Input should be 6, 8 or 10"}]}'

    def refuse(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 422, "Unprocessable Entity", {},
                                     io.BytesIO(body))
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(RuntimeError) as err:
        fal._request("https://queue.fal.run/x")
    assert "422" in str(err.value) and "Input should be 6, 8 or 10" in str(err.value)
    assert "fal-secret-key" not in fal._safe_error(err.value)


# ---------- the image models (2026-10-04) ----------
# The composer picks a model off fal.IMAGE_MODELS; each is priced on its
# own terms, takes the frame in its own shape, and is handed references
# only when it has an edit endpoint.

def test_every_image_model_is_dated_sourced_and_priced():
    for name, spec in fal.IMAGE_MODELS.items():
        assert spec["label"] and spec["note"] and spec["endpoint"], name
        assert spec["checked"] and spec["source"].startswith("https://fal.ai/models/"), name
        priced = sum(k in spec for k in ("usd_per_image", "usd_per_megapixel", "usd_by_size"))
        assert priced == 1, name
        assert spec["size"] in ("wh", "aspect", "enum", "named"), name
        assert fal.image_usd(name) > 0
    opts = fal.image_options()
    assert [o["id"] for o in opts] == list(fal.IMAGE_MODELS)
    assert all(o["usd"] == fal.image_usd(o["id"]) for o in opts)


def test_image_usd_prices_megapixels_rounded_up_and_per_image_models_flat():
    assert fal.image_usd("flux-pro1.1", "1:1") == 0.04          # 1024x1024 = 1MP
    assert all(fal.image_usd("flux-pro1.1", a) == 0.04 for a in fal.IMAGE_SIZES)  # every frame ~1MP
    assert fal.megapixels(1024, 1024) == 1 and fal.megapixels(1025, 1024) == 2
    assert fal.megapixels(2048, 2048) == 4
    assert fal.image_usd("seedream4.5", "21:9") == fal.image_usd("seedream4.5", "1:1")
    # FLUX.2 Pro (verified 2026-10-04): $0.03 for the first output megapixel,
    # $0.015 per further megapixel of input and output -- a reference counts
    # as an input megapixel; a per-image model ignores references
    assert fal.image_usd("flux2-pro", "1:1") == 0.03
    assert fal.image_usd("flux2-pro", "1:1", references=2) == 0.06
    assert fal.image_usd("seedream4.5", "1:1", references=2) == 0.04
    assert fal.image_usd("flux-pro1.1", "1:1", references=2) == 0.04   # no edit: refs never sent
    with pytest.raises(ValueError):
        fal.image_usd("dall-e")


def test_references_go_to_the_edit_endpoint_only_where_one_exists():
    refs = ["https://r2.example/a.jpg", "/refs/local.jpg", "https://r2.example/b.jpg"]
    endpoint, body, used = fal.image_request("flux2-pro", "a can", aspect="4:5",
                                             reference_urls=refs)
    assert endpoint == fal.IMAGE_MODELS["flux2-pro"]["edit"]
    assert body["image_urls"] == ["https://r2.example/a.jpg", "https://r2.example/b.jpg"]
    assert used == 2 and body["image_size"] == {"width": 912, "height": 1136}
    # a text-only model draws from the prompt and says so with used == 0
    endpoint, body, used = fal.image_request("flux-pro1.1", "a can", aspect="4:5",
                                             reference_urls=refs)
    assert endpoint == "fal-ai/flux-pro/v1.1" and "image_urls" not in body and used == 0
    assert (body["width"], body["height"]) == (912, 1136)
    # the two other frame shapes
    assert fal.image_request("nano-banana-pro", "x", aspect="9:16")[1]["aspect_ratio"] == "9:16"
    assert fal.image_request("ideogram4.5", "x", aspect="16:9")[1]["image_size"] == "landscape_16_9"
    assert fal.image_request("ideogram4.5", "x", aspect="7:5")[1]["image_size"] == "square_hd"
    assert fal.image_request("ideogram4.5", "x")[1]["quality"] == "medium"   # not high, ~4x the price
    # Seedream 4.5 (2026-10-08) refuses under ~3.7MP: the frame goes out doubled
    assert fal.image_request("seedream4.5", "x", aspect="4:5")[1]["image_size"] == {"width": 1824, "height": 2272}
    for a in fal.IMAGE_SIZES:
        w, h = fal.image_request("seedream4.5", "x", aspect=a)[1]["image_size"].values()
        assert 2560 * 1440 <= w * h <= 4096 * 4096 and max(w, h) <= 4096
    # GPT Image 2 (2026-10-04): named sizes by orientation, quality sent
    # explicitly (fal's default is high at ~4x), up to 16 references, priced
    # per size at medium
    endpoint, body, used = fal.image_request("gpt-image-2", "a can", aspect="4:5",
                                             reference_urls=[f"https://r2.example/{i}.jpg" for i in range(20)])
    assert endpoint == "openai/gpt-image-2/edit" and used == 16
    assert body["image_size"] == "1024x1536" and body["quality"] == "medium"
    assert fal.image_request("gpt-image-2", "x", aspect="16:9")[1]["image_size"] == "1536x1024"
    assert fal.image_request("gpt-image-2", "x", aspect="1:1")[1]["image_size"] == "1024x1024"
    assert fal.image_usd("gpt-image-2", "1:1") == 0.053
    assert fal.image_usd("gpt-image-2", "9:16") == 0.042
    assert fal.image_usd("gpt-image-2", "9:16", references=5) == 0.042   # per image, refs free


def test_a_composer_still_is_charged_held_settled_and_banked(tmp_db, approved, keys,
                                                              fake_download, monkeypatch):
    from src import accounts, ledger, pricing, render_assets
    preprod.init(tmp_db)
    accounts.seed("mike@example.com", dsn=tmp_db)
    ledger.init(tmp_db)
    with db.connect(tmp_db) as conn:
        account_id = int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])
    ledger.grant(account_id, 1000, "purchase", dsn=tmp_db)
    http = FakeHttp(result={"images": [{"url": "https://v3.fal.media/i.png"}]})
    result = fal.generate_image_from_prompt(
        "a can on steel", db_path=tmp_db, http=http, model="seedream4.5", aspect="4:5",
        reference_urls=["https://r2.example/can.jpg"], account_id=account_id)
    assert result["ok"] is True, result["error"]
    assert result["references"] == 1
    url, body = http.calls[0]
    assert url.endswith(fal.IMAGE_MODELS["seedream4.5"]["edit"])
    assert body["image_urls"] == ["https://r2.example/can.jpg"]
    expected = pricing.credits_for(pricing.usd_micros(fal.image_usd("seedream4.5", "4:5", references=1)))
    assert result["credits"] == expected
    spent = -sum(e["delta"] for e in ledger.entries(account_id, tmp_db) if e["kind"] != "grant")
    assert spent == expected
    assert ledger.outstanding(account_id, tmp_db) == 0
    with generative.connect(tmp_db) as conn:
        row = conn.execute("SELECT tool, cost_usd, params_json FROM generations").fetchone()
    assert row["tool"] == "fal"
    assert float(row["cost_usd"]) == fal.image_usd("seedream4.5", "4:5")
    params = json.loads(row["params_json"])
    assert params["model"] == "seedream4.5" and params["references"] == 1
    assert params["aspect"] == "4:5" and "ledger_ref" in params
    wall = render_assets.list_all(tmp_db, account_id=account_id)
    assert [a["model"] for a in wall] == ["seedream4.5"]


def test_a_failed_fal_still_releases_its_hold(tmp_db, approved, keys, monkeypatch):
    from src import accounts, ledger
    preprod.init(tmp_db)
    accounts.seed("mike@example.com", dsn=tmp_db)
    ledger.init(tmp_db)
    with db.connect(tmp_db) as conn:
        account_id = int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])
    ledger.grant(account_id, 1000, "purchase", dsn=tmp_db)
    http = FakeHttp(status_error={"error": "boom", "error_type": "ValidationError"})
    result = fal.generate_image_from_prompt("a can", db_path=tmp_db, http=http,
                                            model="flux2-pro", account_id=account_id)
    assert result["ok"] is False and "boom" in result["error"]
    assert ledger.outstanding(account_id, tmp_db) == 0
    assert ledger.available(account_id, tmp_db) == 1000


def test_an_unknown_image_model_is_refused_before_any_call(tmp_db, approved, keys):
    http = FakeHttp()
    result = fal.generate_image_from_prompt("a can", db_path=tmp_db, http=http, model="dall-e")
    assert result["ok"] is False and "image model" in result["error"]
    assert http.calls == []

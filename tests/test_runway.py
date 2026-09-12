"""
Tests for src/runway.py -- the Runway connector.

Fully hermetic: the SDK is a fake client object, _download is patched
(conftest blocks the network anyway), and no test may reach Runway (it
would bill real API credits). The generations table runs against a
throwaway DB. The spend gate (RUNWAY_SPEND_OK) is the extra surface
veo.py doesn't have: approval is opt-in per test, refusal is the
default -- same as production.
"""
import json
from types import SimpleNamespace

import pytest

from src import generative, runway


@pytest.fixture
def tmp_db(pg):
    path = pg
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
    # an unknown model prices at the most expensive known rate, never free.
    # That ceiling moved from gen4.5 to Seedance 1080p when the reference
    # lane was registered (2026-09-12) -- the point of the rule is that an
    # unrecognised model errs HIGH on the button a person approves with,
    # so the number tracks the dearest rate this module knows, not a
    # constant that happened to be the dearest once.
    assert runway.estimate_cost(1, model="mystery", duration=5) == 3.40


def test_seedance_prices_by_resolution_not_by_model_name():
    """docs.dev.runwayml.com/guides/pricing, 2026-09-12: seedance2_5 bills
    20/30/68 credits per second at 480p/720p/1080p. A flat per-model rate
    would quote a 1080p render at under half its real price on the button
    a person approves it with."""
    assert runway.estimate_cost(1, model="seedance2_5", duration=5,
                                ratio="720:1280") == 1.50
    assert runway.estimate_cost(1, model="seedance2_5", duration=5,
                                ratio="1080:1920") == 3.40
    # the short side is what names the tier, whichever way the frame is up
    assert (runway.estimate_cost(1, model="seedance2_5", duration=5, ratio="1280:720")
            == runway.estimate_cost(1, model="seedance2_5", duration=5, ratio="720:1280"))
    # and an 80-credit floor on any single generation, so a 2s clip is not
    # priced at 2 * the rate
    assert runway.estimate_cost(1, model="seedance2_5", duration=2,
                                ratio="720:1280") == 0.80
    # an unknown model still prices at the most expensive rate known --
    # which is now Seedance's, not gen4.5's
    assert runway.estimate_cost(1, model="mystery", duration=5) == 3.40


# ---------- the reference lane ----------

def test_gen4_models_cannot_carry_references_at_all():
    """Not a gap in this module: the SDK types both gen4 models'
    promptImage entries as position:'first' with no reference field, so
    attaching references to one is a call that cannot be made. It raises
    at the boundary rather than dropping them and rendering anyway."""
    assert runway.takes_references("seedance2_5") is True
    assert runway.takes_references("gen4_turbo") is False
    assert runway.takes_references("gen4.5") is False
    with pytest.raises(ValueError, match="cannot take reference images"):
        runway.build_prompt_image("https://cdn/k.png", ["https://cdn/1.jpg"],
                                  model="gen4_turbo")


def test_no_references_sends_the_string_form_untouched():
    """The keyframe path has to stay byte-for-byte what it was, down to
    the type: every gen4 render in this repo sends a bare string."""
    assert runway.build_prompt_image("https://cdn/k.png", None,
                                     model="gen4_turbo") == "https://cdn/k.png"
    assert runway.build_prompt_image("https://cdn/k.png", [],
                                     model="seedance2_5") == "https://cdn/k.png"
    assert runway.build_prompt_image(None, None, model="gen4_turbo") is None


def test_reference_mode_omits_position_and_demotes_the_anchor():
    """"Use position first/last for keyframe mode, or omit position for
    reference images. The two modes cannot be mixed." So not one entry
    may carry a position -- and the anchor is not thrown away, it leads
    the list: it is still the only image composed for THIS shot."""
    payload = runway.build_prompt_image(
        "https://cdn/k.png", ["https://cdn/1.jpg", "https://cdn/2.jpg"],
        model="seedance2_5")
    assert payload == [{"uri": "https://cdn/k.png"},
                       {"uri": "https://cdn/1.jpg"},
                       {"uri": "https://cdn/2.jpg"}]
    assert not any("position" in entry for entry in payload)


def test_an_anchor_that_is_also_a_ref_is_sent_once():
    payload = runway.build_prompt_image(
        "https://cdn/1.jpg", ["https://cdn/1.jpg", "https://cdn/2.jpg"],
        model="seedance2_5")
    assert [e["uri"] for e in payload] == ["https://cdn/1.jpg", "https://cdn/2.jpg"]


def test_reference_mode_is_decided_by_position_in_the_scene():
    """A single-shot scene and the first part of a timeline render on
    their references; part 2 and after keep the keyframe, because
    _keyframe_timeline draws each part's still from the previous one and
    that chain is the only thing holding the look still across shots."""
    assert runway.reference_mode(None) is True
    assert runway.reference_mode(1) is True
    assert runway.reference_mode(2) is False
    assert runway.reference_mode(9) is False


def test_reference_uris_are_empty_wherever_they_would_not_be_sent():
    """The count goes into the generations row, so it has to mean what it
    says: zero on a gen4 render and zero in keyframe mode, both of which
    are cases where the photos reach the clip through the keyframe's
    pixels instead."""
    target = {"refs": ["https://cdn/1.jpg", "https://cdn/2.jpg"],
              "reference_image": "https://cdn/k.png"}
    assert len(runway.reference_uris(target, 1, "seedance2_5")) == 2
    assert runway.reference_uris(target, 2, "seedance2_5") == []
    assert runway.reference_uris(target, 1, "gen4_turbo") == []
    assert runway.reference_uris({"refs": []}, None, "seedance2_5") == []


def test_a_ref_that_will_not_resolve_is_dropped_not_fatal():
    """as_prompt_image's rule, unchanged: an unresolvable reference is
    left out and the row records the smaller count, rather than the
    render failing or a broken URI being sent."""
    target = {"refs": ["https://cdn/1.jpg", "/refs/nowhere.jpg"]}
    assert runway.reference_uris(target, None, "seedance2_5") == ["https://cdn/1.jpg"]


def test_seedance_takes_the_platform_vertical_and_a_far_bigger_prompt():
    """720:1280 is in BOTH ratio lists, which is what lets a render move
    to the reference lane without changing the frame anything downstream
    was cut for. And the 1000-character refusal that drops a director's
    Avoid list does not apply here."""
    from src import render_specs
    assert render_specs.RATIO_9_16 in render_specs.SEEDANCE_2_5_RATIOS
    assert render_specs.RATIO_9_16 in render_specs.RUNWAY_RATIOS
    assert runway.prompt_limit("seedance2_5") == 15000
    runway.check_prompt_length("x" * 1400, "seedance2_5")      # no raise
    with pytest.raises(ValueError):
        runway.check_prompt_length("x" * 1400, "gen4_turbo")


# ---------- generate_for_shot: the scene board's one-click render ----------

@pytest.fixture
def scene_db(tmp_db):
    from src import preprod
    preprod.init(tmp_db)
    return tmp_db


def seed_scene(path, reference=""):
    from src import preprod
    shot = {"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
            "tool": "RUNWAY", "prompt": "low key garage, single bulb"}
    if reference:
        shot["reference_image"] = reference
    return preprod.save_concept(
        {"title": "Vault", "shots": [shot]}, brand="antihero", dsn=path, account_id=None)


def seed_scene_with_refs(path, refs, reference=""):
    from src import preprod
    shot = {"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
            "tool": "RUNWAY", "prompt": "low key garage, single bulb",
            "refs": list(refs)}
    if reference:
        shot["reference_image"] = reference
    return preprod.save_concept(
        {"title": "Vault", "shots": [shot]}, brand="antihero", dsn=path, account_id=None)


def test_for_shot_carries_the_refs_into_the_render_on_the_reference_lane(
        scene_db, approved, fake_download, monkeypatch, tmp_path):
    """The whole point of the lane: on a single-shot scene the stored
    reference photos reach the video model itself, not only the keyframe
    that was drawn from them. No entry carries a position, the keyframe
    leads the list, and the row says how many rode along."""
    import src.storage as storage
    from src import generative as gen
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "configured", lambda: False)
    concept_id = seed_scene_with_refs(
        scene_db, ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"],
        reference="https://cdn.example/key.png")
    client = FakeClient()

    result = runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client,
                                      model="seedance2_5", duration=5)
    assert result["ok"], result["error"]
    sent = client.calls[0]
    assert sent["prompt_image"] == [{"uri": "https://cdn.example/key.png"},
                                    {"uri": "https://cdn.example/a.jpg"},
                                    {"uri": "https://cdn.example/b.jpg"}]
    with gen.connect(scene_db) as conn:
        row = conn.execute(
            "SELECT params_json FROM generations ORDER BY id DESC LIMIT 1").fetchone()
    params = json.loads(row["params_json"])
    assert params["references"] == 2
    assert params["reference_mode"] is True


def test_for_shot_on_a_gen4_model_renders_anchored_and_says_references_zero(
        scene_db, approved, fake_download, monkeypatch, tmp_path):
    """The same scene on gen4_turbo must still render -- refusing would
    stop a queue over an enhancement -- but the row has to record that the
    photos did NOT ride along, so a clip that ignored them is explainable
    from the log instead of from the output."""
    import src.storage as storage
    from src import generative as gen
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "configured", lambda: False)
    concept_id = seed_scene_with_refs(
        scene_db, ["https://cdn.example/a.jpg"],
        reference="https://cdn.example/key.png")
    client = FakeClient()

    result = runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client,
                                      model="gen4_turbo", duration=5)
    assert result["ok"], result["error"]
    assert client.calls[0]["prompt_image"] == "https://cdn.example/key.png"
    with gen.connect(scene_db) as conn:
        row = conn.execute(
            "SELECT params_json FROM generations ORDER BY id DESC LIMIT 1").fetchone()
    params = json.loads(row["params_json"])
    assert params["references"] == 0
    assert params["reference_mode"] is False


def test_for_shot_respects_the_spend_gate(scene_db, monkeypatch, tmp_path):
    monkeypatch.delenv(runway.SPEND_ENV, raising=False)
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    concept_id = seed_scene(scene_db)
    result = runway.generate_for_shot(concept_id, 1, db_path=scene_db,
                                      client=FakeClient())
    assert result["ok"] is False
    assert "Runway app" in result["error"]     # points at the free path
    with generative.connect(scene_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0


def test_for_shot_renders_logs_and_attaches(scene_db, approved, fake_download,
                                            monkeypatch, tmp_path):
    import src.storage as storage
    from src import preprod
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "configured", lambda: False)
    concept_id = seed_scene(scene_db)
    client = FakeClient()

    result = runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client)
    assert result["ok"], result["error"]
    # the motion directive leads (timeline.for_render -- every renderer here
    # is image-to-video, so the prompt's job is the change, not the scene),
    # and the shot's own prompt follows it unaltered
    from src import timeline as tl_mod
    assert client.calls[0]["prompt_text"] == (
        tl_mod.MOTION_DIRECTIVE + "\n\nlow key garage, single bulb")
    assert "prompt_image" not in client.calls[0]     # no reference -> text-to-video
    # served from /renders, logged, and attached to the shot
    assert result["media_url"].startswith("/renders/runway/")
    concept = preprod.get_concept(concept_id, dsn=scene_db, account_id=None)
    assert concept["shots"][0]["media_url"] == result["media_url"]
    assert runway.generations_today(db_path=scene_db) == 1


def test_for_shot_anchors_on_the_reference_image(scene_db, approved, fake_download,
                                                 monkeypatch, tmp_path):
    import src.storage as storage
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "configured", lambda: False)
    concept_id = seed_scene(scene_db, reference="https://cdn.example/plate.jpg")
    client = FakeClient()
    result = runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client)
    assert result["ok"], result["error"]
    assert client.calls[0]["prompt_image"] == "https://cdn.example/plate.jpg"


def test_for_shot_anchors_on_a_local_keyframe_as_bytes(scene_db, approved,
                                                       fake_download, monkeypatch,
                                                       tmp_path):
    """The bug this closes: a Nano keyframe is /renders/nano/x.png until
    R2 is configured, and the old code took reference_image only when it
    started with http -- so the keyframe silently anchored nothing while
    the Queue card said it did, and the credit was spent on the lie."""
    import src.storage as storage
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "configured", lambda: False)
    renders = tmp_path / "data-renders"
    (renders / "nano").mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\n" + b"keyframe-bytes"
    (renders / "nano" / "wf-1.png").write_bytes(png)
    monkeypatch.setattr(runway, "RENDERS_ROOT", renders)

    concept_id = seed_scene(scene_db, reference="/renders/nano/wf-1.png")
    client = FakeClient()
    result = runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client)
    assert result["ok"], result["error"]
    sent = client.calls[0]["prompt_image"]
    # inline, and typed off the magic number -- Nano writes PNG, and the
    # old bytes path hardcoded image/jpeg
    assert sent.startswith("data:image/png;base64,")


def test_for_shot_resolves_a_picked_asset_photo(scene_db, approved, fake_download,
                                                monkeypatch, tmp_path):
    """A site-relative asset photo is resolved by the caller's own
    resolver (the web app passes _resolve_asset_photo); without one it
    is dropped rather than pretended about."""
    import src.storage as storage
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "configured", lambda: False)
    photo = tmp_path / "michael.jpg"
    photo.write_bytes(b"\xff\xd8" + b"jacket")
    concept_id = seed_scene(scene_db, reference="/characters/michael/photo/1.jpg")

    client = FakeClient()
    assert runway.generate_for_shot(concept_id, 1, db_path=scene_db,
                                    client=client)["ok"]
    assert "prompt_image" not in client.calls[0]        # no resolver -> dropped

    client = FakeClient()
    assert runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client,
                                    resolve_photo=lambda url: photo)["ok"]
    assert client.calls[0]["prompt_image"].startswith("data:image/jpeg;base64,")


def test_as_prompt_image_refuses_a_path_escaping_the_render_root(monkeypatch, tmp_path):
    renders = tmp_path / "renders"
    renders.mkdir()
    (tmp_path / "secret.png").write_bytes(b"\x89PNG\r\n\x1a\nno")
    monkeypatch.setattr(runway, "RENDERS_ROOT", renders)
    assert runway.as_prompt_image("/renders/../secret.png") is None


def test_for_shot_missing_pieces_are_results(scene_db, approved, monkeypatch, tmp_path):
    from src import preprod
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    assert "no concept" in runway.generate_for_shot(
        999, 1, db_path=scene_db, client=FakeClient())["error"]
    concept_id = preprod.save_concept(
        {"title": "Cam only",
         "shots": [{"n": 1, "type": "CHARACTER", "source": "CAMERA",
                    "cam": "BMPCC", "location": "garage"}]},
        brand="antihero", dsn=scene_db, account_id=None)
    assert "no shot 9" in runway.generate_for_shot(
        concept_id, 9, db_path=scene_db, client=FakeClient())["error"]
    assert "no AI prompt" in runway.generate_for_shot(
        concept_id, 1, db_path=scene_db, client=FakeClient())["error"]


def test_for_shot_cap_blocks_before_any_call(scene_db, approved, monkeypatch, tmp_path):
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(runway, "DAILY_CAP", 0)
    concept_id = seed_scene(scene_db)
    client = FakeClient()
    result = runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client)
    assert result["ok"] is False
    assert "daily cap" in result["error"]
    assert client.calls == []


# --- the prompt has to survive the trip out ---------------------------------
# Two things sat between a finished director's prompt and a Runway
# render, and both refused the whole job rather than degrading:
# moderation reading an asset NAME as third-party IP, and a promptText
# cap a 1400-character prompt was 46% over (2026-08-29).

def test_a_prompt_over_the_cap_refuses_before_spending(approved):
    long_prompt = "x" * 1001
    with pytest.raises(ValueError) as excinfo:
        runway.generate_video(long_prompt, "/tmp/never.mp4",
                              client=object())
    message = str(excinfo.value)
    assert "1001" in message and "1000" in message
    assert "cut 1" in message
    assert "Avoid list" in message          # says WHERE to cut, not just that


def test_the_cap_is_measured_in_utf16_like_the_api_counts_it():
    """An emoji is two UTF-16 units. A len() check passes a prompt the
    API then rejects, which is the failure this exists to prevent."""
    assert runway.prompt_limit("gen4_turbo") == 1000
    runway.check_prompt_length("a" * 1000, "gen4_turbo")     # exactly at it
    with pytest.raises(ValueError):
        runway.check_prompt_length("🎬" * 501, "gen4_turbo")  # 1002 units


def test_a_prompt_at_the_cap_is_let_through(approved, tmp_db, fake_download,
                                            monkeypatch):
    seen = {}

    class FakeTask:
        output = ["https://cdn.test/clip.mp4"]

    class FakeCreate:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(wait_for_task_output=lambda: FakeTask())

    monkeypatch.setattr(runway, "_make_client",
                        lambda *a, **k: SimpleNamespace(image_to_video=FakeCreate()))
    runway.generate_video("y" * 1000, "/tmp/ok.mp4", db_path=tmp_db)
    assert seen["prompt_text"] == "y" * 1000


@pytest.fixture
def asset_db(tmp_db):
    """tmp_db has the generations tables; the alias lookup reads the
    asset bank, which is a different module's schema."""
    from src import entities
    entities.init(tmp_db)
    return tmp_db


def test_a_flagged_asset_name_is_swapped_for_its_alias(asset_db):
    """Runway's moderation reads the NAME: "Cyclops" is a Marvel
    character to a classifier however Homeric yours is, and the whole
    prompt is refused. The keyframe carries the look, so describing the
    thing costs nothing."""
    import json

    from src import entities
    entities.add_character(
        "Cyclops", description=json.dumps({"render_alias": "one-eyed humanoid"}),
        dsn=asset_db, account_id=None)
    out = runway.safe_prompt("A Cyclops polishes a spoon. The cyclops sighs.",
                             db_path=asset_db)
    assert "yclops" not in out
    assert out == "A one-eyed humanoid polishes a spoon. The one-eyed humanoid sighs."


def test_an_asset_without_an_alias_is_left_alone(asset_db):
    """Explicit per asset, never guessed -- swapping every name for its
    description would blow the 1000-character budget on one sentence."""
    import json

    from src import entities
    entities.add_character("Michael", description=json.dumps({"look": "a man"}),
                           dsn=asset_db, account_id=None)
    assert runway.safe_prompt("Michael rides", db_path=asset_db) == "Michael rides"


def test_the_swap_happens_before_the_length_check(asset_db, approved,
                                                 monkeypatch):
    """An alias changes the length, so what we measure has to be what we
    send -- a name that shortens under substitution must not be refused
    for a length it no longer has."""
    import json

    from src import entities
    entities.add_character(
        "Cyclops", description=json.dumps({"render_alias": "x"}), dsn=asset_db, account_id=None)
    prompt = "Cyclops " * 130          # 1040 chars, 260 once swapped
    assert len(prompt) > 1000
    seen = {}

    class FakeTask:
        output = ["https://cdn.test/clip.mp4"]

    monkeypatch.setattr(
        runway, "_make_client",
        lambda *a, **k: SimpleNamespace(image_to_video=SimpleNamespace(
            create=lambda **kw: seen.update(kw) or SimpleNamespace(
                wait_for_task_output=lambda: FakeTask()))))
    monkeypatch.setattr(runway, "_download", lambda url, path: None)
    runway.generate_video(prompt, "/tmp/ok.mp4", db_path=asset_db)
    assert "Cyclops" not in seen["prompt_text"]
    assert len(seen["prompt_text"]) <= 1000


# ---------- BYOK: whose key paid for this ----------

@pytest.fixture
def byok(pg, monkeypatch):
    """One account with its own stored Runway secret, and a DIFFERENT
    operator secret in the environment. Whichever of the two turns up in
    a client, an error string or a generations row is the answer to
    "whose card is this render on".

    DATABASE_URL is set because a credential is a property of the
    INSTALLATION's database, not of whatever db_path a render was handed
    -- account_keys.key_for(dsn=None) is what _make_client calls.
    """
    from cryptography.fernet import Fernet

    from src import account_keys, accounts, db

    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("ACCOUNT_KEYS_SECRET", Fernet.generate_key().decode())
    monkeypatch.setenv("RUNWAYML_API_SECRET", "OPERATOR-SECRET")
    generative.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        owner = conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"]
    account_keys.set_key(owner, "runway", "TENANT-SECRET", dsn=pg)
    return {"dsn": pg, "account_id": owner}


@pytest.fixture
def sdk_keys(monkeypatch):
    """Every api_key the runwayml SDK was constructed with, in order."""
    used = []

    def fake_sdk(api_key=None, **kwargs):
        used.append(api_key)
        return FakeClient()

    monkeypatch.setattr("runwayml.RunwayML", fake_sdk)
    return used


def _params(byok, generation_id):
    """The stored params of one generation, read as its owner -- so the
    row being the caller's own is part of what this asserts."""
    import json

    from src import db

    with db.connect(byok["dsn"]) as conn:
        row = conn.execute(
            "SELECT params_json FROM generations WHERE id = %s AND account_id = %s",
            (generation_id, byok["account_id"]),
        ).fetchone()
    return json.loads(row["params_json"])


def test_a_byok_account_renders_on_its_own_key_not_the_operators(
    byok, approved, fake_download, sdk_keys,
):
    """generate_from_prompt called generate_video WITHOUT account_id, so
    _make_client resolved RUNWAYML_API_SECRET from the environment --
    the operator's key -- while the generations row it then wrote said
    the render was the customer's. The bill and the record disagreed."""
    result = runway.generate_from_prompt("a prompt", db_path=byok["dsn"],
                                         account_id=byok["account_id"])

    assert result["ok"] is True, result["error"]
    assert sdk_keys == ["TENANT-SECRET"], (
        f"the render went on {sdk_keys!r} -- the operator's key paid for a "
        "customer's clip")


def test_a_stored_secret_never_reaches_an_error_string(byok):
    """_safe_error only ever knew about the environment, so a BYOK
    customer's own secret passed straight through into a string that
    reaches a Queue card and a generations row."""
    text = runway._safe_error(RuntimeError("401 rejecting key TENANT-SECRET"),
                              byok["account_id"])
    assert "TENANT-SECRET" not in text
    assert "<RUNWAYML_API_SECRET>" in text


def test_the_generations_row_records_whose_key_paid_for_it(
    byok, approved, fake_download, sdk_keys,
):
    """The prepaid ledger must not debit credits for a render the
    customer already paid the provider for directly, and `key_for` alone
    cannot tell those apart after the fact. The row says which it was."""
    from src import account_keys

    own = runway.generate_from_prompt("a prompt", db_path=byok["dsn"],
                                      account_id=byok["account_id"])
    assert _params(byok, own["generation_id"])["key_source"] == "account"

    account_keys.clear_key(byok["account_id"], "runway", dsn=byok["dsn"])
    ours = runway.generate_from_prompt("a prompt", db_path=byok["dsn"],
                                       account_id=byok["account_id"])
    assert _params(byok, ours["generation_id"])["key_source"] == "env"
    assert sdk_keys == ["TENANT-SECRET", "OPERATOR-SECRET"]


def test_for_shot_renders_one_part_of_a_timed_scene(scene_db, approved, fake_download,
                                                    monkeypatch, tmp_path):
    """2026-09-10: `part=n` renders ONE shot of a timed scene through the
    same walls -- the scene's continuity then that shot's prompt, anchored
    on THAT shot's still, attached to that part and not to the scene."""
    import src.storage as storage
    from src import preprod, timeline
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "configured", lambda: False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    shot = {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
            "refs": ["/refs/a.jpg"],
            "prompt": ("Grounded noir. (0-3s) Close on the key turning. "
                       "(3-8s) Hard cut to the alley, he looks up.")}
    concept_id = preprod.save_concept({"title": "Key", "shots": [shot]},
                                      brand="antihero", dsn=scene_db, account_id=None)
    timeline.ensure(concept_id, db_path=scene_db)            # the plain split
    timeline.attach_part(concept_id, 1, 2, "reference_image",
                         "https://cdn.example/still2.png", db_path=scene_db)
    client = FakeClient()

    result = runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client,
                                      part=2, duration=5)
    assert result["ok"], result["error"]
    sent = client.calls[0]
    # the motion directive leads (timeline.for_render), then the scene's
    # memory, then this shot -- both still there, just no longer first
    from src import timeline as tl_mod
    assert sent["prompt_text"].startswith(tl_mod.MOTION_DIRECTIVE)
    assert "CONTINUITY" in sent["prompt_text"]
    assert "SHOT 2 OF 2 (3-8s, 5s): Hard cut to the alley" in sent["prompt_text"]
    assert sent["prompt_image"] == "https://cdn.example/still2.png"
    assert "-p2-" in result["path"]
    stored = preprod.get_concept(concept_id, dsn=scene_db, account_id=None)["shots"][0]
    assert stored["timeline"]["parts"][1]["media_url"] == result["media_url"]
    assert not stored.get("media_url")        # shot 1 has no clip yet
    assert runway.generate_for_shot(concept_id, 1, db_path=scene_db, client=client,
                                    part=7)["ok"] is False

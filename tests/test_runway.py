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
        {"title": "Vault", "shots": [shot]}, brand="antihero", path=path)


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
    assert client.calls[0]["prompt_text"] == "low key garage, single bulb"
    assert "prompt_image" not in client.calls[0]     # no reference -> text-to-video
    # served from /renders, logged, and attached to the shot
    assert result["media_url"].startswith("/renders/runway/")
    concept = preprod.get_concept(concept_id, path=scene_db)
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
        brand="antihero", path=scene_db)
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
                        lambda: SimpleNamespace(image_to_video=FakeCreate()))
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
        path=asset_db)
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
                           path=asset_db)
    assert runway.safe_prompt("Michael rides", db_path=asset_db) == "Michael rides"


def test_the_swap_happens_before_the_length_check(asset_db, approved,
                                                 monkeypatch):
    """An alias changes the length, so what we measure has to be what we
    send -- a name that shortens under substitution must not be refused
    for a length it no longer has."""
    import json

    from src import entities
    entities.add_character(
        "Cyclops", description=json.dumps({"render_alias": "x"}), path=asset_db)
    prompt = "Cyclops " * 130          # 1040 chars, 260 once swapped
    assert len(prompt) > 1000
    seen = {}

    class FakeTask:
        output = ["https://cdn.test/clip.mp4"]

    monkeypatch.setattr(
        runway, "_make_client",
        lambda: SimpleNamespace(image_to_video=SimpleNamespace(
            create=lambda **kw: seen.update(kw) or SimpleNamespace(
                wait_for_task_output=lambda: FakeTask()))))
    monkeypatch.setattr(runway, "_download", lambda url, path: None)
    runway.generate_video(prompt, "/tmp/ok.mp4", db_path=asset_db)
    assert "Cyclops" not in seen["prompt_text"]
    assert len(seen["prompt_text"]) <= 1000

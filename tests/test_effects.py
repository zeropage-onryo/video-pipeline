"""src/effects.py -- the third spending door (2026-10-07): an existing
image or clip changed by a fal endpoint, held and settled like a still.

The MCP side (quote, approval, id resolution, refusals) is covered in
tests/test_mcp_server.py; this file covers the table and the spend."""
from __future__ import annotations

import pytest

from src import effects, fal, generative
from tests.test_fal import FakeHttp  # the queue double


@pytest.fixture
def tmp_db(pg):
    generative.init(pg)
    return pg


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "fal-secret-key")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(fal, "POLL_SECONDS", 0)


@pytest.fixture
def fake_download(monkeypatch):
    def _fake(url, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(fal, "_download", _fake)


@pytest.fixture
def local_publish():
    return lambda path, ctype, account_id=None: f"/renders/fal/{path.name}"


def test_every_row_is_dated_and_complete():
    for name, row in effects.EFFECTS.items():
        assert row["category"] in effects.CATEGORIES, name
        assert row["takes"] in ("image", "video") and row["output"] in ("image", "video")
        assert row["prompt"] in ("required", "optional", "none")
        assert row["source"].startswith("https://fal.ai/models/"), name
        lo, hi = row["sources"]
        assert 1 <= lo <= hi
        assert row.get("probe", False) == (row["takes"] == "video"), name


def test_the_enums_are_the_schemas_not_a_summary():
    assert len(effects.KLING_EFFECTS) == 98 and "bullet_time_360" in effects.KLING_EFFECTS
    assert len(effects.PIXVERSE_EFFECTS) == 154 and "Liquid Metal" in effects.PIXVERSE_EFFECTS
    assert len(effects.CAMERA_MOVES) == 20 and "whip_pan" in effects.CAMERA_MOVES


@pytest.mark.parametrize("effect, opts, probe, usd", [
    ("nano-banana-edit", {}, None, 0.039),
    ("remove-background", {}, None, 0.018),
    ("kling-effect", {"effect_scene": "zoom_out", "duration": "5"}, None, 0.28),
    ("pixverse-effect", {"effect": "Kiss", "resolution": "1080p", "duration": "5"}, None, 0.40),
    ("camera-move", {"camera_movement": "whip_pan", "resolution": "360p", "duration": "5"},
     None, 0.15),
    ("upscale", {"upscale_factor": 2}, {"seconds": 5, "height": 360, "fps": 24}, 0.05),
    ("upscale", {"upscale_factor": 2}, {"seconds": 5, "height": 540, "fps": 24}, 0.1),
    ("upscale", {"upscale_factor": 1, "target_fps": 60},
     {"seconds": 5, "height": 720, "fps": 24}, 0.1),
    ("add-sound", {}, {"seconds": 4.2, "height": 720, "fps": 24}, 0.005),
])
def test_prices(effect, opts, probe, usd):
    assert effects.quote_usd(effect, opts, probe) == usd


def test_a_clip_effect_is_never_priced_without_measuring_it():
    with pytest.raises(ValueError, match="probe"):
        effects.quote_usd("upscale", {"upscale_factor": 2})


def test_an_unmeasurable_clip_is_refused(tmp_path):
    with pytest.raises(ValueError, match="could not measure"):
        effects.probe_video(tmp_path / "missing.mp4")


def test_wire_shapes_follow_each_schema():
    _, body = effects.build_body("flux-kontext-pro", ["a"], "swap the can", {})
    assert body["image_url"] == "a" and body["num_images"] == 1
    _, body = effects.build_body("nano-banana-edit", ["a", "b"], "p", {"aspect_ratio": "auto"})
    assert body["image_urls"] == ["a", "b"]
    _, body = effects.build_body("remove-background", ["a"], "", {})
    assert body == {"image_url": "a"}
    _, body = effects.build_body("upscale", ["v"], "", {"upscale_factor": 2})
    assert body == {"video_url": "v", "upscale_factor": 2, "H264_output": True}


def test_an_effect_holds_its_price_logs_and_banks(tmp_db, keys, fake_download,
                                                  local_publish, monkeypatch):
    from src import render_assets
    http = FakeHttp(result={"video": {"url": "https://v3.fal.media/fx.mp4"}})
    taken, banked = [], []
    real = fal.charging.Charge.take

    def spy(self):
        taken.append((self.provider, self.estimate_usd, self.source))
        return real(self)

    monkeypatch.setattr(fal.charging.Charge, "take", spy)
    monkeypatch.setattr(render_assets, "record_best_effort",
                        lambda **kw: banked.append(kw) or {"id": 77})
    res = effects.run("kling-effect", ["https://r2/a.jpg"], "",
                      {"effect_scene": "zoom_out", "duration": "5"}, usd=0.28,
                      sources=["gen:4"], db_path=tmp_db, http=http,
                      publish=local_publish)
    assert res["ok"] is True, res["error"]
    assert res["asset_id"] == 77 and res["media_kind"] == "video"
    assert res["media_url"].endswith(".mp4")
    submit_url, body = http.calls[0]
    assert submit_url.endswith("/fal-ai/kling-video/v1.6/standard/effects")
    assert body["input_image_urls"] == ["https://r2/a.jpg"]
    assert taken == [("fal", 0.28, "mcp")]
    assert banked[0]["media_kind"] == "video" and banked[0]["model"] == "kling-effect"
    with generative.connect(tmp_db) as conn:
        tool, cost = conn.execute("SELECT tool, cost_usd FROM generations").fetchone()
    assert tool == "fal" and float(cost) == 0.28


def test_a_failed_effect_releases_its_hold(tmp_db, keys, monkeypatch):
    released = []
    monkeypatch.setattr(fal.charging.Charge, "release",
                        lambda self, why: released.append(why))

    def boom(*a, **k):
        raise RuntimeError("fal job failed: content policy")

    monkeypatch.setattr(fal, "_submit_and_wait", boom)
    res = effects.run("remove-background", ["https://r2/a.jpg"], "", {}, usd=0.018,
                      db_path=tmp_db)
    assert res["ok"] is False and "content policy" in res["error"]
    assert released and released[0].startswith("fal effect")


def test_no_key_never_submits(tmp_db, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)
    http = FakeHttp()
    res = effects.run("remove-background", ["u"], "", {}, usd=0.018, db_path=tmp_db, http=http)
    assert res["ok"] is False and "FAL_KEY" in res["error"] and http.calls == []


def test_an_effect_counts_against_the_image_wall_not_a_clips(tmp_db, keys, monkeypatch):
    """An effect is logged under the image tool name, so the wall it hits
    is the stills' count -- never a clip's budget."""
    monkeypatch.setattr(fal, "DAILY_CAP", 1)
    seen = {}

    def refuse(tool, n, **kw):
        seen.update(tool=tool, **kw)
        return "daily cap reached"

    monkeypatch.setattr(generative, "cap_error", refuse)
    http = FakeHttp()
    res = effects.run("remove-background", ["u"], "", {}, usd=0.018, db_path=tmp_db, http=http)
    assert res == {"ok": False, "error": "daily cap reached"} and http.calls == []
    assert seen["tool"] == fal.IMAGE_LOG_TOOL and seen["per_account"] == 1
    assert seen["env_prefix"] == "FAL"



def test_an_effect_records_the_project_it_was_filed_under(tmp_db, keys, fake_download,
                                                          local_publish, monkeypatch):
    import json

    from src import render_assets
    banked = []
    monkeypatch.setattr(render_assets, "record_best_effort",
                        lambda **kw: banked.append(kw) or {"id": 1})
    http = FakeHttp(result={"image": {"url": "https://v3.fal.media/cut.png"}})
    res = effects.run("remove-background", ["https://r2/a.jpg"], "", {}, usd=0.018,
                      db_path=tmp_db, http=http, publish=local_publish, project_id=12)
    assert res["ok"] is True, res["error"]
    assert banked[0]["metadata"]["project_id"] == 12
    with generative.connect(tmp_db) as conn:
        params = json.loads(conn.execute("SELECT params_json FROM generations").fetchone()[0])
    assert params["project_id"] == 12

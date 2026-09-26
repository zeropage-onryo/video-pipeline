"""
ops/render_queue.py -- the repo side of rendering on SUBSCRIPTION credits.

The split it serves: a Claude session picks shots and calls the Higgsfield
MCP (which spends the app plan's credits, not API credits), and this file
tells that session what is waiting and files what came back. These tests
guard the three things that would silently corrupt the pipeline:

- `pending` must mean exactly what /queue/pending means, or the session
  renders things that were never queued;
- a clip must land somewhere /renders can actually serve, or the Queue
  card shows a broken video for a render that really happened;
- the attempt must be logged with credits, not invented dollars.

Since 2026-09-08 BOTH lanes are operator-only -- the Higgsfield app plan
is the same kind of personal consumer subscription the Runway one is --
so every test here acts as a configured operator. The gate itself, and
its refusals, are tested in tests/test_manual_lane.py.
"""
import json
import re

import pytest

from ops import render_queue as rq
from src import accounts, generative, manual_lane, preprod


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    generative.init(path)
    accounts.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


@pytest.fixture(autouse=True)
def no_inherited_environment(monkeypatch):
    """Both lanes are operator-only (src/manual_lane.py), and since
    2026-09-08 the gate is a column rather than these two variables. They
    are unset here so a stray one in a developer's shell cannot be
    mistaken for the reason a test passed."""
    monkeypatch.delenv("ZEROPAGE_OPERATOR_ACCOUNTS", raising=False)
    monkeypatch.delenv("ZEROPAGE_OPERATOR_EMAILS", raising=False)


@pytest.fixture(autouse=True)
def renders_in_tmp(tmp_path, monkeypatch):
    """Never write into the real data/renders/ from a test."""
    root = tmp_path / "renders"
    monkeypatch.setattr(rq, "RENDERS_ROOT", root)
    monkeypatch.setattr(rq, "RENDER_DIR", root / "higgsfield")
    monkeypatch.setattr(rq, "MANUAL_RENDER_DIR", root / "manual")
    return root


def a_scene(path, account_id, title="Cold Open", prompt="a close shot"):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "HIGGSFIELD",
                    "desc": title, "prompt": prompt,
                    # the lane shares the Queue's predicate, which since
                    # 2026-09-08 requires reference photos
                    "refs": ["/refs/seed.jpg"]}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=account_id)


@pytest.fixture
def operator(tmp_db):
    """An account whose own row carries the operator flag -- what every
    lane call now needs."""
    accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    return accounts.set_manual_lane_operator(
        "zeropage", True, dsn=tmp_db)["account_id"]


def a_clip(tmp_path, name="clip.mp4", size=200_000):
    p = tmp_path / name
    p.write_bytes(b"\x00" * size)
    return p


# ---------- what counts as waiting ----------

def test_an_unpicked_concept_is_not_waiting(tmp_db, operator):
    a_scene(tmp_db, operator)
    assert rq.pending(account_id=operator) == []


def test_a_picked_scene_is_waiting(tmp_db, operator):
    cid = a_scene(tmp_db, operator, title="The Bronze Debt")
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    waiting = rq.pending(account_id=operator)
    assert [w["concept_id"] for w in waiting] == [cid]
    assert waiting[0]["title"] == "The Bronze Debt"
    assert waiting[0]["prompt"] == "a close shot"


def test_an_archived_scene_is_not_waiting(tmp_db, operator):
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    preprod.set_archived(cid, True, dsn=tmp_db, account_id=operator)
    assert rq.pending(account_id=operator) == []


def test_a_scene_that_already_has_a_clip_is_not_waiting(tmp_db, tmp_path, operator):
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    preprod.set_shot_media_url(cid, 1, "/renders/higgsfield/x.mp4", dsn=tmp_db, account_id=operator)
    assert rq.pending(account_id=operator) == []


def test_brand_filter(tmp_db, operator):
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    assert rq.pending(brand="zeropage", account_id=operator)
    assert rq.pending(brand="antihero", account_id=operator) == []


# ---------- filing what came back ----------

def test_a_clip_lands_where_renders_can_serve_it(tmp_db, tmp_path, renders_in_tmp, operator):
    """app/main.py mounts /renders on data/renders/. A clip left anywhere
    else 404s in the Queue however real the render was."""
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    out = rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                         account_id=operator)
    assert out["media_url"] == "/renders/higgsfield/clip.mp4"
    assert (renders_in_tmp / "higgsfield" / "clip.mp4").is_file()


def test_a_second_clip_does_not_overwrite_the_first(tmp_db, tmp_path, renders_in_tmp, operator):
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                         account_id=operator)
    cid2 = a_scene(tmp_db, operator, title="Second")
    preprod.set_picked(cid2, True, dsn=tmp_db, account_id=operator)
    out = rq.import_clip(cid2, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                         account_id=operator)
    assert out["media_url"] == "/renders/higgsfield/clip-1.mp4"


def test_the_attempt_is_logged_in_credits_not_invented_dollars(tmp_db, tmp_path, operator):
    """The clip came out of a subscription already paid for. A cost_usd
    here would be a number nobody spent."""
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                         account_id=operator)
    with generative.connect(tmp_db) as conn:
        row = conn.execute("SELECT tool, cost_usd, params_json FROM generations "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["tool"] == "higgsfield"
    assert row["cost_usd"] is None
    params = json.loads(row["params_json"])
    assert params["credits"] == 4.8
    assert params["source"] == "mcp-subscription"
    assert params["model"] == "seedance1_5"


def test_importing_takes_the_scene_out_of_the_queue(tmp_db, tmp_path, operator):
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    assert len(rq.pending(account_id=operator)) == 1
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                         account_id=operator)
    assert rq.pending(account_id=operator) == []


def test_an_imported_clip_joins_the_assets_wall(tmp_db, tmp_path, operator, monkeypatch):
    """2026-09-18: a hand-rendered clip used to live on the concept and
    nowhere else, so it never showed on the Assets wall. The import now
    records a generated_assets row too, best-effort and lazily imported."""
    from src import render_assets
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    result = rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                            account_id=operator)
    assert result["asset_id"]
    rows = render_assets.list_all(tmp_db, account_id=operator)
    assert [r["media_url"] for r in rows] == [result["media_url"]]
    assert rows[0]["media_kind"] == "video"
    assert rows[0]["concept_id"] == cid and rows[0]["shot_n"] == 1
    assert rows[0]["generation_id"] == result["generation_id"]


def test_a_truncated_download_is_refused(tmp_db, tmp_path, operator):
    """A 200-byte 'mp4' is a failed download, and logging it as a render
    would put a broken clip on the board with a row saying it worked."""
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    with pytest.raises(SystemExit, match="not a video"):
        rq.import_clip(cid, 1, str(a_clip(tmp_path, size=200)),
                       "seedance1_5", 4.8, None, True, account_id=operator)


def test_an_unknown_concept_refuses(tmp_db, tmp_path, operator):
    with pytest.raises(SystemExit, match="no concept"):
        rq.import_clip(9999, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                         account_id=operator)


def test_the_anchor_is_recorded_as_what_was_actually_sent(tmp_db, tmp_path, operator):
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, False,
                   account_id=operator)
    with generative.connect(tmp_db) as conn:
        params = json.loads(conn.execute(
            "SELECT params_json FROM generations ORDER BY id DESC LIMIT 1"
        ).fetchone()[0])
    assert params["prompt_image"] is False


# ---------- the stdlib-only contract ----------

def test_render_queue_imports_without_third_party_packages():
    """It runs under a Claude session's plain python3 -- the repo venvs
    are macOS builds and that shell is Linux. One boto3 import here and
    the whole subscription path stops working."""
    import ast
    import pathlib

    source = pathlib.Path(rq.__file__).with_suffix(".py").read_text()
    tree = ast.parse(source)
    # shutil and subprocess joined the list on 2026-09-08: `import` asks
    # ffprobe how long the clip really is. Both are stdlib, which is the
    # only thing this test is about -- one boto3 here and the whole
    # subscription path stops working on a bare python3. `struct` joined
    # on 2026-09-18: the mvhd header reader that stands in for ffprobe.
    allowed = {"argparse", "json", "shutil", "sqlite3", "struct", "subprocess", "sys",
               "pathlib", "src", "ops", "__future__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            assert node.module.split(".")[0] in allowed, node.module


# ---------- the manual lane (the Runway lane until 2026-09-26) ----------
#
# A clip rendered anywhere, filed free. It files a render with no hold,
# which is why every test here has to name an operator first -- the
# allowlist and its refusals are tested in tests/test_manual_lane.py.


def a_manual_scene(path, account_id, title="Cold Open"):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "LTX",
                    "desc": title, "prompt": "a close shot"}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=account_id)


def test_a_manual_clip_lands_in_its_own_folder_under_renders(tmp_db, tmp_path,
                                                             renders_in_tmp, operator):
    """data/renders/manual/ sits under the /renders mount, so the media_url
    derivation is the same as for any render."""
    cid = a_manual_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    out = rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None,
                         True, account_id=operator, provider="manual")
    assert out["media_url"] == "/renders/manual/clip.mp4"
    assert (renders_in_tmp / "manual" / "clip.mp4").is_file()
    assert not (renders_in_tmp / "higgsfield").exists()


def test_the_manual_row_is_free_and_carries_the_lane_marker(tmp_db, tmp_path, operator):
    """cost_usd NULL is how this repo says FREE (src/costs.py's NOTES);
    the marker is what src/ledger.py reads to refuse a hold."""
    cid = a_manual_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="manual", duration=10)
    with generative.connect(tmp_db) as conn:
        row = conn.execute("SELECT tool, cost_usd, params_json FROM generations "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["tool"] == "manual"
    assert row["cost_usd"] is None
    params = json.loads(row["params_json"])
    assert params["source"] == manual_lane.SOURCE
    assert params["lane"] == manual_lane.LANES["manual"]
    assert params["model"] == "gen4_turbo"
    assert params["duration"] == 10
    assert params["ratio"] == manual_lane.LANE_RATIO
    # no API credential was used, and the row says so
    assert params["key_source"] is None


def test_importing_a_manual_clip_takes_the_scene_out_of_the_queue(tmp_db, tmp_path,
                                                                  operator):
    cid = a_manual_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    assert len(rq.pending(account_id=operator, provider="manual")) == 1
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="manual")
    assert rq.pending(account_id=operator, provider="manual") == []


def test_an_unknown_provider_is_refused(tmp_db, operator):
    with pytest.raises(SystemExit, match="unknown provider"):
        rq.pending(account_id=operator, provider="midjourney")


def test_the_higgsfield_lane_is_gated_too(tmp_db, tmp_path):
    """2026-09-08, and a DELIBERATE BREAK of a workflow that needed no
    configuration. The Higgsfield app plan is the same kind of personal
    consumer subscription the Runway one is, so gating one lane and
    leaving the other open would only look like the question had been
    asked and answered.

    Nobody has been turned on in this test, which is what an install
    that has not been told who the operator is looks like."""
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    cid = a_scene(tmp_db, account_id)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=account_id)
    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.pending(account_id=account_id)
    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None,
                       True, account_id=account_id)


def test_the_refusal_tells_the_operator_what_to_run(tmp_db):
    """It says nothing about WHO is allowed -- but a person who hits it
    on their own machine has to be able to act on it, and naming the
    column and the command reveals only what this repo's source already
    says."""
    assert manual_lane.OPERATOR_COLUMN in manual_lane.REFUSAL
    assert manual_lane.OPERATOR_COMMAND in manual_lane.REFUSAL


# ---------- what `import` records (2026-09-08; the Runway checks went 2026-09-26) ----------
#
# --model lands in a generations row the tool scoreboard reads. Neither
# lane has a list to check it against, so the row says it was not checked.


def test_the_manual_row_records_that_the_model_claim_was_not_checked(tmp_db, tmp_path,
                                                                    operator):
    cid = a_manual_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "kling 3 web app", None, None, True,
                   account_id=operator, provider="manual", duration=7)
    params = _last_params(tmp_db)
    assert params["model_verified"] is False
    assert params["model"] == "kling 3 web app" and params["duration"] == 7


def test_the_higgsfield_lane_records_that_it_could_not_check(tmp_db, tmp_path,
                                                             operator):
    """The MCP's model names are its own and are published nowhere this
    repo can read. A list invented here would refuse models that are
    perfectly real, so the row says the claim was not checked rather than
    implying a check that never happened."""
    cid = a_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                   account_id=operator)
    assert _last_params(tmp_db)["model_verified"] is False


def _last_params(path):
    with generative.connect(path) as conn:
        return json.loads(conn.execute(
            "SELECT params_json FROM generations ORDER BY id DESC LIMIT 1"
        ).fetchone()[0])


def test_the_measured_duration_is_recorded_beside_the_claimed_one(tmp_db, tmp_path,
                                                                  operator,
                                                                  monkeypatch):
    """ffprobe is asked about the file itself, so a 5s clip filed as 10s
    is visible in the row rather than silently trusted."""
    monkeypatch.setattr(rq.shutil, "which", lambda name: "/usr/bin/ffprobe")

    class Probed:
        stdout = "5.04\n"

    monkeypatch.setattr(rq.subprocess, "run", lambda *a, **k: Probed())
    cid = a_manual_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="manual", duration=10)
    params = _last_params(tmp_db)
    assert params["duration"] == 10            # what was claimed, kept
    assert params["duration_measured_s"] == 5.04
    assert params["duration_source"] == "ffprobe"


def test_a_missing_ffprobe_says_so_rather_than_asserting_a_measurement(tmp_db,
                                                                      tmp_path,
                                                                      operator,
                                                                      monkeypatch):
    """The script runs wherever the human downloaded the mp4, so ffprobe
    is optional -- but an absent measurement must not read like one that
    agreed with the claim."""
    monkeypatch.setattr(rq.shutil, "which", lambda name: None)
    cid = a_manual_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="manual")
    params = _last_params(tmp_db)
    assert params["duration_measured_s"] is None
    assert "ffprobe" in params["duration_source"]
    assert params["duration_source"].startswith("unmeasured")


def _mvhd_clip(tmp_path, seconds, version=0, name="clip.mp4"):
    """An mp4 with a real `mvhd` box near the front and nothing else a
    decoder would want -- enough for the header reader, not for ffprobe."""
    import struct
    timescale = 1000
    duration = int(seconds * timescale)
    if version == 1:
        body = bytes([1, 0, 0, 0]) + struct.pack(">QQIQ", 0, 0, timescale, duration)
    else:
        body = bytes([0, 0, 0, 0]) + struct.pack(">IIII", 0, 0, timescale, duration)
    mvhd = struct.pack(">I", 8 + len(body)) + b"mvhd" + body
    moov = struct.pack(">I", 8 + len(mvhd)) + b"moov" + mvhd
    ftyp = struct.pack(">I", 16) + b"ftypisom" + b"\x00\x00\x02\x00"
    p = tmp_path / name
    p.write_bytes(ftyp + moov + b"\x00" * 4096)
    return p


def test_without_ffprobe_the_mp4_header_is_read_and_labelled_as_such(tmp_db, tmp_path,
                                                                    operator, monkeypatch):
    """The imports happen on the operator's Mac, which has no ffprobe; an
    mp4 states its own length in mvhd, so that is recorded rather than a
    not-knowing -- under a label that says it is the muxer's word."""
    monkeypatch.setattr(rq.shutil, "which", lambda name: None)
    cid = a_manual_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(_mvhd_clip(tmp_path, 10.042)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="manual", duration=10)
    params = _last_params(tmp_db)
    assert params["duration_measured_s"] == 10.04
    assert params["duration_source"].startswith("mp4 mvhd header")
    assert "ffprobe" in params["duration_source"]


def test_mvhd_reader_handles_both_box_versions_and_never_raises(tmp_path):
    assert rq._mp4_header_duration(_mvhd_clip(tmp_path, 5.5)) == pytest.approx(5.5)
    assert rq._mp4_header_duration(_mvhd_clip(tmp_path, 7.25, version=1, name="v1.mp4")) == pytest.approx(7.25)
    assert rq._mp4_header_duration(a_clip(tmp_path, name="zeros.mp4")) is None   # no box at all
    assert rq._mp4_header_duration(tmp_path / "missing.mp4") is None             # unreadable
    # a zero timescale is a broken header, not a zero-length clip
    broken = _mvhd_clip(tmp_path, 0, name="zero.mp4")
    assert rq._mp4_header_duration(broken) is None


def test_an_unreadable_file_is_a_missing_measurement_not_a_zero(tmp_db, tmp_path,
                                                                operator, monkeypatch):
    """A stub mp4 (what every test here writes) is exactly what ffprobe
    cannot read. Recording 0.0 would be a measurement claiming the clip
    is empty; None plus a reason is the truth."""
    monkeypatch.setattr(rq.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(rq.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    cid = a_manual_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="manual")
    params = _last_params(tmp_db)
    assert params["duration_measured_s"] is None
    assert "could not read" in params["duration_source"]


def test_the_lane_defaults_are_a_frame_the_composer_offers(tmp_db):
    """The frame `list` prints as the target is one the Studio composer can
    write a scene for, so the lane never asks for a shape nothing else uses."""
    from src import render_specs
    assert manual_lane.LANE_RATIO in render_specs.FRAME_SIZES
    assert manual_lane.LANE_DURATION > 0

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
    monkeypatch.setattr(rq, "RUNWAY_RENDER_DIR", root / "runway")
    return root


def a_scene(path, account_id, title="Cold Open", prompt="a close shot"):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "HIGGSFIELD",
                    "desc": title, "prompt": prompt}]},
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
    # subscription path stops working on a bare python3.
    allowed = {"argparse", "json", "shutil", "sqlite3", "subprocess", "sys",
               "pathlib", "src", "ops", "__future__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            assert node.module.split(".")[0] in allowed, node.module


# ---------- the runway lane (2026-09-08) ----------
#
# Runway's Explore Mode is free on the Unlimited plan and reachable only
# from the web app, so this lane is a human in Chrome. It spends the
# OPERATOR'S subscription, which is why every test here has to name an
# operator first -- the allowlist and its refusals are tested in
# tests/test_manual_lane.py.


def a_runway_scene(path, account_id, title="Cold Open"):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "desc": title, "prompt": "a close shot"}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=account_id)


def test_a_runway_clip_lands_in_the_adapters_own_folder(tmp_db, tmp_path,
                                                        renders_in_tmp, operator):
    """data/renders/runway/ is where src/runway.py already writes, so the
    /renders mount and the media_url derivation are unchanged -- a clip
    rendered by hand is the same kind of file in the same place as one
    rendered through the API."""
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    out = rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None,
                         True, account_id=operator, provider="runway")
    assert out["media_url"] == "/renders/runway/clip.mp4"
    assert (renders_in_tmp / "runway" / "clip.mp4").is_file()
    assert not (renders_in_tmp / "higgsfield").exists()


def test_the_runway_row_is_free_and_carries_the_lane_marker(tmp_db, tmp_path, operator):
    """cost_usd NULL is how this repo says FREE (src/costs.py's NOTES);
    the marker is what src/ledger.py reads to refuse a hold."""
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="runway", duration=10)
    with generative.connect(tmp_db) as conn:
        row = conn.execute("SELECT tool, cost_usd, params_json FROM generations "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["tool"] == "runway"
    assert row["cost_usd"] is None
    params = json.loads(row["params_json"])
    assert params["source"] == manual_lane.SOURCE
    assert params["lane"] == manual_lane.LANES["runway"]
    assert params["model"] == "gen4_turbo"
    assert params["duration"] == 10
    assert params["ratio"] == manual_lane.LANE_RATIO
    # no API credential was used, and the row says so rather than
    # borrowing a label from the BYOK vocabulary
    assert params["key_source"] is None


def test_importing_a_runway_clip_takes_the_scene_out_of_the_queue(tmp_db, tmp_path,
                                                                  operator):
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    assert len(rq.pending(account_id=operator, provider="runway")) == 1
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="runway")
    assert rq.pending(account_id=operator, provider="runway") == []


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


# ---------- what `import` checks instead of believing (2026-09-08) ----------
#
# --model, --ratio and --duration land in a generations row the tool
# scoreboard reads. They used to be unverified strings, so a 1am typo
# became a measurement of a model that never ran.


def test_an_unknown_runway_model_is_refused(tmp_db, tmp_path, operator):
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    with pytest.raises(SystemExit, match="unknown runway model"):
        rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen5_ultra", None, None,
                       True, account_id=operator, provider="runway")


def test_an_illegal_duration_is_refused_not_clamped(tmp_db, tmp_path, operator):
    """Refused, because a number outside the model's set is evidence the
    row and the clip have come apart -- and rounding it to the nearest
    legal value hides exactly that."""
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    with pytest.raises(SystemExit, match="does not generate 7s"):
        rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None,
                       True, account_id=operator, provider="runway", duration=7)


def test_an_illegal_ratio_is_refused(tmp_db, tmp_path, operator):
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    with pytest.raises(SystemExit, match="does not render"):
        rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None,
                       True, account_id=operator, provider="runway",
                       ratio="1920:1080")


def test_a_refused_claim_copies_no_file_and_writes_no_row(tmp_db, tmp_path,
                                                          renders_in_tmp, operator):
    """Checked before the clip moves and before a row exists -- the same
    rule the gate keeps, for the same reason: a rejected import must
    leave the install exactly as it found it."""
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    with pytest.raises(SystemExit):
        rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None,
                       True, account_id=operator, provider="runway", duration=7)
    assert not (renders_in_tmp / "runway").exists()
    with generative.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0
    assert rq.pending(account_id=operator, provider="runway") != []


def test_the_row_records_that_the_model_claim_was_checked(tmp_db, tmp_path, operator):
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="runway", duration=10)
    assert _last_params(tmp_db)["model_verified"] is True


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
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="runway", duration=10)
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
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="runway")
    params = _last_params(tmp_db)
    assert params["duration_measured_s"] is None
    assert "ffprobe" in params["duration_source"]
    assert params["duration_source"].startswith("unmeasured")


def test_an_unreadable_file_is_a_missing_measurement_not_a_zero(tmp_db, tmp_path,
                                                                operator, monkeypatch):
    """A stub mp4 (what every test here writes) is exactly what ffprobe
    cannot read. Recording 0.0 would be a measurement claiming the clip
    is empty; None plus a reason is the truth."""
    monkeypatch.setattr(rq.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(rq.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    cid = a_runway_scene(tmp_db, operator)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=operator)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=operator, provider="runway")
    params = _last_params(tmp_db)
    assert params["duration_measured_s"] is None
    assert "could not read" in params["duration_source"]


def test_the_lane_defaults_are_themselves_legal_for_the_lane_model(tmp_db):
    """The defaults `list` prints as targets have to be values the model
    can actually produce, or the lane tells a human to set a chip the
    import will then refuse."""
    from src import render_specs
    assert render_specs.check_ratio("runway", "gen4_turbo",
                                    manual_lane.LANE_RATIO) is True
    assert render_specs.check_duration("runway", "gen4_turbo",
                                       manual_lane.LANE_DURATION) is True

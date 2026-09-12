"""
A concept with no reference images is a no-go.

Mike's rule, 2026-09-08, and a deliberate exception to the standing
convention that grounding shapes and never gates ("a crawl is an
enhancement, never a dependency"). What earned the exception: on the
night of 2026-09-07, 9 of 29 banked sparks had a photograph behind them,
and the other 20 still produced scenes -- written from words alone --
because nothing downstream ever asked. The convention protects a night
from a dead crawl; it was also keeping the crawl dead.

Two places enforce it, and they are different jobs:

  scout.next_spark   PASSES OVER a reference-less finding, leaving it
                     unclaimed so the next research pass can still put
                     images behind it and make it servable.
  orchestrator.planner  REFUSES a direction that arrived from anywhere
                     else -- the sparks.txt rotation, a typed spark, an
                     agent's `generate` -- and holds the run with the
                     reason on the card.

The suite runs with the rule OFF (see tests/conftest.py); every test
here turns it on explicitly.
"""
import pytest

from src import orchestrator, scout


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    scout.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


@pytest.fixture
def required(monkeypatch):
    monkeypatch.setenv("ZEROPAGE_REQUIRE_REFS", "1")


def a_finding(path, brand="zeropage", spark="a crawled idea", score=0.9):
    return scout.record(brand, {"spark": spark, "score": score}, dsn=path)


def with_a_photo(path, finding_id, brand="zeropage"):
    scout.bin_add(brand, scout.agent_pass_id(finding_id),
                  "/refs/abc123.jpg", source_url="https://example.test/p/1",
                  title="wet tile under fluorescent", lane="agent", dsn=path)


# ---------- the switch ----------

def test_the_rule_is_on_by_default(monkeypatch):
    monkeypatch.delenv("ZEROPAGE_REQUIRE_REFS", raising=False)
    assert scout.refs_required() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
def test_and_can_be_turned_off_for_one_run(monkeypatch, value):
    monkeypatch.setenv("ZEROPAGE_REQUIRE_REFS", value)
    assert scout.refs_required() is False


# ---------- what the bank will serve ----------

def test_a_spark_with_no_pictures_is_not_served(tmp_db, required):
    a_finding(tmp_db, spark="nothing behind this one")
    assert scout.next_spark("zeropage", dsn=tmp_db) is None


def test_a_spark_with_a_picture_is(tmp_db, required):
    fid = a_finding(tmp_db, spark="this one has a photo")
    with_a_photo(tmp_db, fid)
    served = scout.next_spark("zeropage", dsn=tmp_db)
    assert served and served["id"] == fid


def test_the_bank_reaches_past_a_higher_scoring_bare_spark(tmp_db, required):
    """Score does not rescue a spark nobody can illustrate -- and the one
    passed over stays UNCLAIMED, so tomorrow's research pass can put
    images behind it rather than losing it."""
    bare = a_finding(tmp_db, spark="the best idea, unillustrated", score=1.0)
    illustrated = a_finding(tmp_db, spark="a lesser idea with a photo", score=0.8)
    with_a_photo(tmp_db, illustrated)

    served = scout.next_spark("zeropage", dsn=tmp_db)
    assert served["id"] == illustrated
    assert scout.get_finding(bare, dsn=tmp_db)["used_at"] is None


def test_turning_the_rule_off_serves_the_bare_spark_again(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_REQUIRE_REFS", "0")
    fid = a_finding(tmp_db, spark="nothing behind this one", score=1.0)
    assert scout.next_spark("zeropage", dsn=tmp_db)["id"] == fid


# ---------- what the graph will generate from ----------

def test_a_run_with_no_photos_holds_before_it_generates(tmp_db, required):
    from src import autonomy
    autonomy.init(tmp_db)
    out = orchestrator.planner({"channel": "zeropage", "spark": "a typed idea"})
    assert out["error"] == orchestrator.NO_REFS_REASON
    assert orchestrator.route_after_planner(out) == "hold"


def test_a_refused_run_does_not_burn_the_spark(tmp_db, required):
    """The worst outcome is refusing a finding AND throwing its research
    away: unclaimed, it can still be illustrated later."""
    from src import autonomy
    autonomy.init(tmp_db)
    fid = a_finding(tmp_db)
    orchestrator.planner({"channel": "zeropage", "scout_finding_id": fid,
                          "reference_photos": []})
    assert scout.get_finding(fid, dsn=tmp_db)["used_at"] is None


def test_a_run_that_has_photos_proceeds_and_claims(tmp_db, required):
    from src import autonomy
    autonomy.init(tmp_db)
    fid = a_finding(tmp_db)
    out = orchestrator.planner({"channel": "zeropage", "scout_finding_id": fid,
                                "reference_photos": ["/refs/abc123.jpg"]})
    assert not out.get("error")
    assert orchestrator.route_after_planner(out) == "plan"
    assert scout.get_finding(fid, dsn=tmp_db)["run_id"] == out["run_id"]


def test_with_the_rule_off_a_bare_run_proceeds(tmp_db, monkeypatch):
    from src import autonomy
    monkeypatch.setenv("ZEROPAGE_REQUIRE_REFS", "0")
    autonomy.init(tmp_db)
    out = orchestrator.planner({"channel": "zeropage", "spark": "a typed idea"})
    assert not out.get("error")
    assert orchestrator.route_after_planner(out) == "plan"


def test_the_refusal_is_wired_into_the_compiled_graph():
    """A router nothing routes through is not a gate."""
    import inspect
    source = inspect.getsource(orchestrator.build_graph
                               if hasattr(orchestrator, "build_graph")
                               else orchestrator)
    assert "route_after_planner" in source
    assert '"plan": "ground_entities"' in source

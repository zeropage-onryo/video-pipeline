"""
The boundary between the two idea paths, pinned.

Mike's rule (2026-08-31, his words): "These are separate. The graph
utilizes the src/scout.py and I myself when I come with an idea that's
separate and doesn't use src/scout.py."

So there are two ways an idea enters this pipeline and they must not
touch:

  HIS      types into the Studio composer -> /api/scenes/run ->
           scene_chain -> shootgen. The scout is not consulted, not
           imported, and cannot alter the idea or spend a banked spark.
  THE GRAPH  orchestrator.run(scout=True) / trigger --scout -> the scout
           node reads the bank and seeds the spark.

Both directions are tested, because a leak either way is silent. A
scout that quietly overrides a typed idea produces a concept about
something he never asked for; a typed idea that quietly claims a banked
spark throws away research he never used. Neither raises anything.
"""
import ast
from pathlib import Path

import pytest

from src import orchestrator, scout, trigger

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    scout.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def _imports(module_path: Path) -> set:
    """Every name this module imports, read structurally rather than by
    grepping -- a comment mentioning the scout is not a dependency on it."""
    tree = ast.parse(module_path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.name for a in node.names)
            if node.module:
                names.add(node.module.split(".")[-1])
    return names


# ---------- structural: his path cannot reach the scout at all ----------

@pytest.mark.parametrize("module", ["scene_chain.py", "shootgen.py", "preprod.py"])
def test_the_generation_engine_does_not_import_the_scout(module):
    """The engine behind Create must not know the scout exists. If this
    ever fails, someone has wired research into the path Mike types on."""
    assert "scout" not in _imports(PROJECT_ROOT / "src" / module)


def test_the_scout_does_not_import_the_generation_engine_at_module_level():
    """Nor the reverse: the scout researches and banks, it does not
    generate. (shootgen is imported lazily inside scout() for one
    default model name -- that is a constant, not a call.)"""
    tree = ast.parse((PROJECT_ROOT / "src" / "scout.py").read_text())
    top_level = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            top_level.update(a.name for a in node.names)
    assert "shootgen" not in top_level
    assert "scene_chain" not in top_level


# ---------- the graph path: the scout IS used ----------

def test_the_graph_asks_the_bank_when_scouting(tmp_db):
    scout.record("zeropage", {"spark": "a crawled idea", "rationale": "because",
                              "score": 0.9}, pass_id="p", dsn=tmp_db)

    out = orchestrator.scout({"brand": "zeropage", "spark": "the rotation",
                              "scout": True})

    assert out["spark"] == "a crawled idea"
    assert out["goal"] == "a crawled idea"


def test_the_graph_claims_the_spark_it_ran_on(tmp_db):
    from src import autonomy
    autonomy.init(tmp_db)
    finding_id = scout.record("zeropage", {"spark": "a crawled idea", "score": 0.9},
                              pass_id="p", dsn=tmp_db)

    out = orchestrator.planner({"channel": "zeropage", "scout_finding_id": finding_id})

    assert scout.get_finding(finding_id, dsn=tmp_db)["run_id"] == out["run_id"]
    assert scout.next_spark("zeropage", dsn=tmp_db) is None


def test_the_graph_never_scouts_unless_asked(tmp_db, monkeypatch):
    """The default must be off. A run that silently swapped in a crawled
    direction would make an explicit --spark a lie."""
    called = []
    monkeypatch.setattr(scout, "next_spark",
                        lambda *a, **k: called.append(1) or None)

    assert orchestrator.scout({"brand": "zeropage", "spark": "mine"}) == {}
    assert orchestrator.scout({"brand": "zeropage", "spark": "mine",
                               "scout": False}) == {}
    assert called == []


def test_an_explicit_spark_survives_a_non_scouting_run(tmp_db):
    scout.record("zeropage", {"spark": "a crawled idea", "score": 0.99},
                 pass_id="p", dsn=tmp_db)
    # a full bank, and a run that did not ask: the typed direction stands
    assert orchestrator.scout({"brand": "zeropage", "spark": "the last check"}) == {}


def test_run_defaults_to_not_scouting():
    import inspect
    assert inspect.signature(orchestrator.run).parameters["scout"].default is False


def test_the_trigger_only_scouts_behind_its_flag(tmp_db, monkeypatch):
    from src import autonomy
    autonomy.init(tmp_db)
    seen = {}

    def fake_run(spark, brand=None, channel="zeropage", scout=False, **kw):
        seen["scout"] = scout
        return {"attempts": 1, "hold_id": 1, "held_reason": "shadow"}

    monkeypatch.setattr(orchestrator, "run", fake_run)

    trigger.main([])
    assert seen["scout"] is False
    trigger.main(["--scout"])
    assert seen["scout"] is True


# ---------- the claim gate: his idea never spends the bank ----------

def test_claims_accepts_the_spark_it_proposed(tmp_db):
    fid = scout.record("zeropage", {"spark": "the last check before leaving",
                                    "score": 0.9}, pass_id="p", dsn=tmp_db)
    assert scout.claims(fid, "the last check before leaving", dsn=tmp_db)


def test_claims_forgives_capitalisation_and_punctuation(tmp_db):
    """Fixing a capital letter is not changing your mind."""
    fid = scout.record("zeropage", {"spark": "the last check before leaving",
                                    "score": 0.9}, pass_id="p", dsn=tmp_db)
    assert scout.claims(fid, "  The Last Check, Before Leaving.  ", dsn=tmp_db)


def test_claims_refuses_an_idea_he_actually_wrote(tmp_db):
    """The leak this closes: load a spark, type over it, press Create.
    A sticky client-side id would burn a spark that wrote nothing."""
    fid = scout.record("zeropage", {"spark": "the last check before leaving",
                                    "score": 0.9}, pass_id="p", dsn=tmp_db)
    assert not scout.claims(fid, "a monster in the garage at 3am", dsn=tmp_db)


def test_claims_refuses_a_partial_rewrite(tmp_db):
    """Ties break toward NOT claiming: an unclaimed spark is offered
    again, a wrongly claimed one is research thrown away."""
    fid = scout.record("zeropage", {"spark": "the last check before leaving",
                                    "score": 0.9}, pass_id="p", dsn=tmp_db)
    assert not scout.claims(fid, "the last check before leaving the garage",
                            dsn=tmp_db)


def test_claims_refuses_an_id_that_does_not_exist(tmp_db):
    assert not scout.claims(4242, "anything at all", dsn=tmp_db)


def test_claims_never_raises_on_a_broken_bank(tmp_path):
    assert scout.claims(1, "anything", dsn=tmp_path / "not-a-db.db") is False

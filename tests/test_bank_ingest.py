"""The agent's plan file, and the morning batch that reads it.

`ops/bank.py` exists because an MCP server never runs itself. Claude can
fill the scout's bank when somebody is asking it to, and cannot be the
thing that fills it at 5am -- so the agent writes a plain JSON plan into
`data/idea_agent/` and the 6am batch banks it seconds before it needs
it, on the machine where refbin has a network and pipeline.db is a local
file.

What these protect: that no plan is a normal night rather than a failure,
that a plan is never ingested twice, and that one bad entry in a plan of
eight does not cost the other seven.
"""

import json

import pytest

from ops import bank
from src import db, entities, preprod, refbin, scout

JPEG = b"\xff\xd8\xff" + b"pretend jpeg"


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    scout.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(refbin, "REFS_DIR", tmp_path / "refs")
    return path


@pytest.fixture
def plans(tmp_path):
    d = tmp_path / "idea_agent"
    d.mkdir()

    def write(name, payload):
        (d / name).write_text(json.dumps(payload))
        return d
    return d, write


@pytest.fixture
def offline_fetch(monkeypatch):
    """refbin.fetch reaches the network; conftest blocks it. Count the
    calls so a test can prove the URL was actually taken."""
    seen = []
    seq = iter(range(100))

    def fake(url):
        seen.append(url)
        return refbin.save(JPEG + bytes([next(seq)]))
    monkeypatch.setattr(refbin, "fetch", fake)
    return seen


def test_a_plan_becomes_sparks_and_the_images_behind_them(tmp_db, plans,
                                                          offline_fetch):
    d, write = plans
    write("2026-09-01.json", {"agent": "claude/idea-agent", "sparks": [
        {"brand": "zeropage", "spark": "a hand already on the handle",
         "turn": "the door never opens", "stake": "dread; anyone who has waited",
         "rationale": "because", "evidence": "12k likes",
         "images": [{"url": "https://cdn.example/a.jpg",
                     "source_url": "https://example.com/post", "title": "a post"},
                    {"url": "https://cdn.example/b.jpg",
                     "source_url": "https://example.com/other"}]},
    ]})

    out = bank.ingest(d, path=tmp_db)

    assert out == {"plans": 1, "sparks": 1, "images": 2, "errors": []}
    served = scout.next_spark("zeropage", path=tmp_db)
    assert served["spark"] == "a hand already on the handle"
    # and the images are reachable through the finding, which is what
    # orchestrator.scout reads to fill reference_photos
    assert len(scout.bin_for_finding(served["id"], path=tmp_db)) == 2


def test_an_agent_spark_outranks_a_crawled_one(tmp_db, plans, offline_fetch):
    """Otherwise the night would keep preferring its own crawl to an
    explicit instruction, which is the opposite of why anyone wrote one."""
    d, write = plans
    scout.record("zeropage", {"spark": "what the crawl found", "score": 0.95},
                 pass_id="p", path=tmp_db)
    write("plan.json", [{"brand": "zeropage", "spark": "what Claude found",
                         "stake": "recognition; anyone"}])

    bank.ingest(d, path=tmp_db)

    assert scout.next_spark("zeropage", path=tmp_db)["spark"] == "what Claude found"


def test_no_plan_is_a_normal_night_not_a_failure(tmp_db, plans):
    d, _ = plans
    assert bank.ingest(d, path=tmp_db)["plans"] == 0
    assert bank.main(["--db", str(tmp_db), "ingest", str(d)]) == 0


def test_a_plan_is_never_ingested_twice(tmp_db, plans, offline_fetch):
    """Re-running a half-banked plan would double the sparks and leave
    the night preferring yesterday's research to today's."""
    d, write = plans
    write("plan.json", [{"brand": "zeropage", "spark": "the only one",
                         "stake": "recognition; anyone"}])

    bank.ingest(d, path=tmp_db)
    assert (d / "done" / "plan.json").is_file()
    assert bank.ingest(d, path=tmp_db)["plans"] == 0
    assert len(scout.list_findings(brand="zeropage", path=tmp_db)) == 1


def test_one_bad_entry_does_not_cost_the_rest_of_the_plan(tmp_db, plans,
                                                          monkeypatch):
    d, write = plans
    monkeypatch.setattr(refbin, "fetch", lambda url: None)   # every image dead
    write("plan.json", [
        {"brand": "zeropage", "spark": "", "stake": "s"},         # no spark
        {"brand": "nonsense", "spark": "wrong brand", "stake": "s"},  # rejected
        {"brand": "zeropage", "spark": "the good one", "stake": "grief; anyone",
         "images": [{"url": "https://cdn.example/gone.jpg",
                     "source_url": "https://example.com/p"}]},
    ])

    out = bank.ingest(d, path=tmp_db)

    assert out["sparks"] == 1 and out["images"] == 0
    assert len(out["errors"]) == 3      # empty, bad brand, dead image
    assert scout.next_spark("zeropage", path=tmp_db)["spark"] == "the good one"


def test_a_dead_image_is_a_missing_picture_not_a_failed_plan(tmp_db, plans,
                                                             monkeypatch):
    """Plans are written hours before 6am and CDN links expire."""
    d, write = plans
    monkeypatch.setattr(refbin, "fetch", lambda url: None)
    write("plan.json", [{"brand": "zeropage", "spark": "still worth running",
                         "stake": "grief; anyone",
                         "images": [{"url": "https://cdn.example/expired.jpg",
                                     "source_url": "https://example.com/p"}]}])

    assert bank.ingest(d, path=tmp_db)["sparks"] == 1
    assert scout.next_spark("zeropage", path=tmp_db)["spark"] == "still worth running"


def test_an_unreadable_plan_is_reported_and_skipped(tmp_db, plans, tmp_path):
    d, write = plans
    (d / "broken.json").write_text("{not json")
    write("good.json", [{"brand": "zeropage", "spark": "the readable one",
                         "stake": "recognition; anyone"}])

    out = bank.ingest(d, path=tmp_db)

    assert out["sparks"] == 1
    assert any("broken.json" in e for e in out["errors"])
    # a plan that could not be read is LEFT where it is, to be looked at
    assert (d / "broken.json").is_file()


def test_a_dry_run_touches_nothing(tmp_db, plans, offline_fetch):
    d, write = plans
    write("plan.json", [{"brand": "zeropage", "spark": "not yet",
                         "stake": "recognition; anyone",
                         "images": [{"url": "https://cdn.example/a.jpg",
                                     "source_url": "https://example.com/p"}]}])

    out = bank.ingest(d, path=tmp_db, dry_run=True)

    assert out["sparks"] == 1
    assert scout.list_findings(brand="zeropage", path=tmp_db) == []
    assert offline_fetch == [], "a dry run fetched an image"
    assert (d / "plan.json").is_file()


def test_attribution_is_required_of_an_agent_too(tmp_db, plans, offline_fetch):
    """bank_reference refuses an unattributed image, and the plan path
    must not be the way around that."""
    d, write = plans
    write("plan.json", [{"brand": "zeropage", "spark": "a spark",
                         "stake": "recognition; anyone",
                         "images": [{"url": "https://cdn.example/a.jpg"}]}])

    out = bank.ingest(d, path=tmp_db)

    assert out["sparks"] == 1 and out["images"] == 0
    assert any("source_url" in e for e in out["errors"])


def test_the_cli_banks_one_spark_and_one_image(tmp_db, plans, offline_fetch,
                                               capsys):
    assert bank.main(["--db", str(tmp_db), "spark", "--brand", "antihero",
                      "--spark", "a hand already on the handle"]) == 0
    fid = scout.next_spark("antihero", path=tmp_db)["id"]
    assert bank.main(["--db", str(tmp_db), "reference", "--finding", str(fid),
                      "--url", "https://cdn.example/a.jpg",
                      "--source", "https://example.com/post"]) == 0
    assert len(scout.bin_for_finding(fid, path=tmp_db)) == 1


def test_a_spark_with_no_stake_is_refused(tmp_db, plans, offline_fetch):
    """The rule prompts/scout_digest_prompt.txt already states, enforced
    in code the way novelty is. Four camera specs sat in this bank at
    0.80 and above with no stake between them and nothing was ever shot
    off one -- asking a prompt for a field and then accepting entries
    without it is steering nothing."""
    d, write = plans
    write("plan.json", [
        {"brand": "zeropage", "spark": "macro zoom tracking a pulsing wrist"},
        {"brand": "zeropage", "spark": "setting the table for one too many",
         "turn": "the extra place gets quietly cleared away",
         "stake": "grief; anyone who has caught themselves doing it"},
    ])

    out = bank.ingest(d, path=tmp_db)

    assert out["sparks"] == 1
    assert any("no stake" in e for e in out["errors"])
    assert scout.next_spark("zeropage", path=tmp_db)["spark"] == \
        "setting the table for one too many"


def test_turn_and_stake_survive_onto_the_board(tmp_db, plans, offline_fetch):
    """Folded by the same function record() uses, so an agent-banked
    spark reads exactly like a crawled one rather than losing both."""
    d, write = plans
    write("plan.json", [{"brand": "zeropage",
                         "spark": "locking a door that is already locked",
                         "turn": "the check repeats, faster each time",
                         "stake": "compulsion; anyone whose brain does this at 2am",
                         "rationale": "the human beat under the signal"}])

    bank.ingest(d, path=tmp_db)

    row = scout.next_spark("zeropage", path=tmp_db)
    assert "TURN: the check repeats" in row["rationale"]
    assert "STAKE: compulsion" in row["rationale"]
    assert "the human beat under the signal" in row["rationale"]

"""
The format-trend feed ranks Zero Page's skeletons by what's actually winning,
prepends today's-hot spice, and NEVER gates -- it degrades to the evergreen
menu on any failure.
"""
import pytest

from src import format_feed, shootgen, winners


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    winners.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def test_empty_library_returns_evergreens_in_order(tmp_db):
    got = format_feed.rank_formats(dsn=tmp_db)
    assert got == list(shootgen.ZEROPAGE_FORMATS)


def test_winners_float_a_proven_format_to_the_top(tmp_db):
    # three winners that all clearly ride the "Slow Push-In" skeleton
    for _ in range(3):
        winners.add("veo", "one continuous slow push in toward the door, dolly in",
                    note="slow push worked", verdict="worked", dsn=tmp_db)
    ranked = format_feed.rank_formats(dsn=tmp_db)
    assert ranked[0][0] == "Slow Push-In"
    # still the full menu, just reordered
    assert {n for n, _ in ranked} == {n for n, _ in shootgen.ZEROPAGE_FORMATS}


def test_didnt_work_winners_do_not_boost(tmp_db):
    winners.add("veo", "slow push in dolly in slow push", note="flopped",
                verdict="didnt_work", dsn=tmp_db)
    ranked = format_feed.rank_formats(dsn=tmp_db)
    # nothing worked, so order is unchanged evergreen
    assert ranked == list(shootgen.ZEROPAGE_FORMATS)


def test_spice_is_prepended_on_top(tmp_db):
    ranked = format_feed.rank_formats(dsn=tmp_db, spice=["liminal pool loops"])
    assert ranked[0][0] == "liminal pool loops"
    assert "TRENDING" in ranked[0][1]
    # evergreens still follow
    assert len(ranked) == len(shootgen.ZEROPAGE_FORMATS) + 1


def test_never_raises_on_a_broken_store(monkeypatch):
    monkeypatch.setattr(winners, "list_all", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    got = format_feed.rank_formats(dsn="whatever")
    assert got == list(shootgen.ZEROPAGE_FORMATS)


def test_limit_caps_the_menu(tmp_db):
    ranked = format_feed.rank_formats(dsn=tmp_db, limit=3)
    assert len(ranked) == 3

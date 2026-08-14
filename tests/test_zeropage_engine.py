"""
Zero Page runs its OWN generation engine, not a brand-block swap on ANTIHERO's
solo-filmmaker-at-home prompt. These lock the separation: Zero Page's prompts
are faceless, format-driven, and uncanny; ANTIHERO's stay room-and-star
grounded. Generation is mocked; the template selection and skeleton injection
run for real.
"""
from src import shootgen


def test_zeropage_ideas_prompt_is_faceless_and_format_driven():
    p = shootgen.build_ideas_prompt([], "zeropage", count=5)
    assert "FACELESS" in p
    assert "GROUNDED-UNCANNY BEAT" in p
    assert "HOT FORMAT SKELETONS" in p
    # the evergreen skeletons are injected
    assert "Slow Push-In" in p and "Seamless Loop" in p
    # it is a different template from ANTIHERO's ideas prompt
    assert p != shootgen.build_ideas_prompt([], "antihero", count=5)


def test_antihero_ideas_prompt_stays_room_and_star_grounded():
    p = shootgen.build_ideas_prompt([], "antihero", count=5)
    assert "solo filmmaker" in p.lower()
    # antihero never gets the Zero Page skeleton menu
    assert "HOT FORMAT SKELETONS" not in p


def test_zeropage_concept_prompt_is_all_ai_and_roomless():
    p = shootgen.build_concept_prompt([], "zeropage")
    assert "faceless" in p.lower()
    assert "ships WITHOUT a shoot" in p or "WITHOUT a shoot" in p
    assert "Freeze on the Wrong Thing" in p   # a skeleton is injected
    assert 'source "AI"' in p   # every shot is AI-generated, no camera


def test_format_skeletons_defaults_to_evergreens():
    text = shootgen.format_skeletons()
    for name, _ in shootgen.ZEROPAGE_FORMATS:
        assert name in text


def test_format_skeletons_accepts_a_live_feed():
    live = [("Trending Thing", "a live-pulled format that is spiking now")]
    text = shootgen.format_skeletons(live)
    assert "Trending Thing" in text
    # the live feed overrides the evergreens rather than appending
    assert "Slow Push-In" not in text


def test_spark_is_treated_as_trend_input_for_zeropage():
    p = shootgen.build_ideas_prompt([], "zeropage", spark="liminal pools", count=5)
    assert "TREND / SPARK: liminal pools" in p


def test_zeropage_ideas_prompt_bans_named_ip():
    p = shootgen.build_ideas_prompt([], "zeropage", count=5)
    assert "never name films" in p.lower() or "Never name films" in p

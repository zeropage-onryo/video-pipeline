"""
Zero Page runs its OWN generation engine, not a brand-block swap on ANTIHERO's
solo-filmmaker-at-home prompt. These lock the separation: Zero Page's prompts
carry no recurring star and are format-driven and uncanny; ANTIHERO's stay
room-and-star grounded. Generation is mocked; the template selection and skeleton injection
run for real.
"""
from src import shootgen


def test_zeropage_ideas_prompt_bars_a_recurring_star_and_drives_on_format():
    p = shootgen.build_ideas_prompt([], "zeropage", count=5)
    assert "NO RECURRING STAR" in p
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
    assert "no recurring star" in p.lower()
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


# --- the no-star brand stops being handed a cast (2026-09-01) --------------
#
# prompts/concept_zeropage.txt: "NO RECURRING STAR -- faces are fine, THIS face
# is not ... never Michael, never the Antihero persona."
# prompts/scenes_prompt.txt:    "reference the uploaded photos as the EXACT
#                                face ... name them, don't redescribe them."
# Two instructions in direct contradiction, and the cast block won: every Zero
# Page concept on the board named Michael, Cyclops or the Ducati.

CHARACTERS = [{"name": "Michael", "role": "protagonist", "photo_count": 3,
               "description": '{"look": "dark hair"}'}]
PROPS = [{"name": "Ducati Panigale 959", "photo_count": 2,
          "description": '{"look": "red"}'}]


def test_zeropage_gets_no_cast_block():
    assert shootgen.cast_for("zeropage", CHARACTERS, PROPS) == ""


def test_antihero_still_gets_its_cast():
    """The fix must not cost Antihero the thing that makes it work --
    real cast, named, with reference photos on file."""
    block = shootgen.cast_for("antihero", CHARACTERS, PROPS)
    assert "Michael" in block and "Ducati" in block


def test_an_empty_cast_tells_the_model_to_describe_plainly():
    """A brand with no cast must not just lose the block silently -- the
    prompt has to say what to do instead, or the model invents a
    recurring person to fill the gap."""
    prompt = shootgen.build_scene_brief_prompt(
        "zeropage", spark="a routine performed wrong",
        cast=shootgen.cast_for("zeropage", CHARACTERS, PROPS))
    assert "{cast}" not in prompt
    assert shootgen.NO_CAST_NOTE in prompt

    # Scoped to the CAST section on purpose. "Michael" also appears in
    # the BRAND blurb ("ZERO PAGE FILMS -- Michael's VIRAL content
    # engine"), which names whose channel it is, not who is on screen.
    # Asserting on the whole prompt would fail on that and teach nothing.
    start = prompt.index("CAST & PROPS ON FILE")
    section = prompt[start:prompt.index("\n\n", start)]
    assert "Michael" not in section
    assert "Ducati" not in section


# --- faces were never the rule (Mike, 2026-09-02) ---------------------------
#
# "I don't want zeropage to not show faces. That's not the point. I just
# wanted it to not be directly tied to my personal account." The word FACELESS
# had been read literally all the way down -- by the generator AND by the
# uncanny gate, which held a concept for ending on a stranger's reaction. What
# Zero Page must not carry is a RECURRING star; a one-off stranger, face and
# all, is fine.

def test_zeropage_does_not_ban_faces():
    for prompt in (shootgen.build_concept_prompt([], "zeropage"),
                   shootgen.build_ideas_prompt([], "zeropage", count=5)):
        low = prompt.lower()
        assert "faces are fine" in low
        # and the old absolute is gone from the rule it used to state
        assert "faceless" not in low


def test_zeropage_still_bars_the_person_the_channel_must_not_be_about():
    p = shootgen.build_concept_prompt([], "zeropage").lower()
    assert "never michael" in p
    assert "antihero persona" in p
    assert "recurring" in p

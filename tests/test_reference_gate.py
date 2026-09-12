"""The reference gate (2026-09-08, Mike's call).

A scene with no reference photographs behind it renders from its own
text, which is the thing this pipeline exists to stop doing. So it comes
off the board when it is written, and it never reaches a spend.

What these tests pin down is mostly the EDGES, because the happy path is
one boolean and the edges are where the money is:

  - a keyframe is not grounding. The board cards that started this said
    "KEYFRAMED · AWAITING APPROVAL IN QUEUE" and "NO REFERENCES" at the
    same time -- that still was drawn by Nano from the prompt, so
    accepting it would be the pipeline checking its own homework.
  - a prompt is not re-judged here. Anything on `shots_json` already
    passed score_prompts, and a second bar would be a second opinion.
  - the machine reason stays out of the taste statistics, or a grounding
    failure reads as Michael passing on an idea.
"""
import pytest

from src import preprod


@pytest.fixture
def tmp_db(pg):
    preprod.init(pg)
    return pg


def _concept(tmp_db, refs=None, *, title="A Scene", picked=False):
    shot = {"n": 1, "type": "CHARACTER", "source": "AI", "tool": "RUNWAY",
            "location": "hallway", "desc": "he steps into frame",
            "prompt": "close on his hands, 35mm, cold overhead light"}
    if refs is not None:
        shot["refs"] = refs
    concept_id = preprod.save_concept(
        {"title": title, "hook": "h", "logline": "l", "shots": [shot]},
        "zeropage", dsn=tmp_db, account_id=None)
    if picked:
        preprod.set_picked(concept_id, True, dsn=tmp_db, account_id=None)
    return concept_id


# ---------- the predicate ----------

def test_a_scene_with_photos_passes(tmp_db):
    concept = preprod.get_concept(_concept(tmp_db, ["/refs/abc.jpg"]),
                                  dsn=tmp_db, account_id=None)
    assert preprod.reference_gate(concept) is None


def test_no_refs_key_at_all_is_refused(tmp_db):
    concept = preprod.get_concept(_concept(tmp_db), dsn=tmp_db, account_id=None)
    assert preprod.reference_gate(concept)


def test_empty_and_blank_refs_are_refused(tmp_db):
    for refs in ([], ["", "   "]):
        concept = preprod.get_concept(_concept(tmp_db, refs), dsn=tmp_db,
                                      account_id=None)
        assert preprod.reference_gate(concept), refs


def test_a_keyframe_is_not_a_reference():
    """The whole reason the gate reads `refs` and not `reference_image`:
    a still this pipeline drew from the prompt is not evidence that the
    prompt was grounded in anything."""
    assert preprod.reference_gate(
        {"shots": [{"n": 1, "reference_image": "https://x.r2.dev/keyframe.png",
                    "prompt": "a long, specific, perfectly good prompt"}]})


def test_a_thin_prompt_with_photos_still_passes():
    """Not re-judged here, deliberately. The prompt bar is score_prompts'
    and it already ran; a second one at the spend gate would be a
    different opinion from the one that let this through."""
    assert preprod.reference_gate(
        {"shots": [{"n": 1, "prompt": "x", "refs": ["/refs/abc.jpg"]}]}) is None


def test_missing_concept_and_missing_shots_are_refused_not_crashed():
    assert preprod.reference_gate(None)
    assert preprod.reference_gate({})
    assert preprod.reference_gate({"shots": []})


# ---------- what it does to the row ----------

def test_archive_ungrounded_takes_it_off_the_board(tmp_db):
    concept_id = _concept(tmp_db)
    assert preprod.archive_ungrounded(concept_id, dsn=tmp_db,
                                      account_id=None) == preprod.NO_REFERENCE
    row = preprod.get_concept(concept_id, dsn=tmp_db, account_id=None)
    assert row["archived"] and row["archive_reason"] == preprod.NO_REFERENCE
    # hidden, never deleted -- the row still holds its prompt
    assert row["shots"][0]["prompt"]


def test_archive_ungrounded_leaves_a_grounded_scene_alone(tmp_db):
    concept_id = _concept(tmp_db, ["/refs/abc.jpg"])
    assert preprod.archive_ungrounded(concept_id, dsn=tmp_db,
                                      account_id=None) is None
    assert not preprod.get_concept(concept_id, dsn=tmp_db,
                                   account_id=None)["archived"]


def test_it_never_overwrites_a_reason_somebody_typed(tmp_db):
    """Those six words are the only record of WHY anything was rejected.
    A second pass must not relabel 'weak concept' as plumbing."""
    concept_id = _concept(tmp_db)
    preprod.set_archived(concept_id, True, dsn=tmp_db, account_id=None,
                         reason="weak concept")
    assert preprod.archive_ungrounded(concept_id, dsn=tmp_db,
                                      account_id=None) is None
    assert preprod.get_concept(concept_id, dsn=tmp_db,
                               account_id=None)["archive_reason"] == "weak concept"


# ---------- and to the numbers ----------

def test_the_machine_reason_is_not_in_the_taste_tally(tmp_db):
    preprod.set_archived(_concept(tmp_db), True, dsn=tmp_db, account_id=None,
                         reason="weak concept")
    preprod.archive_ungrounded(_concept(tmp_db), dsn=tmp_db, account_id=None)
    reasons = {r["reason"] for r in preprod.reason_counts(tmp_db, account_id=None)}
    assert reasons == {"weak concept"}
    assert preprod.ungrounded_count(tmp_db, account_id=None) == 1


def test_an_ungrounded_scene_does_not_depress_pick_rate(tmp_db):
    """The number this protects. pick_rate is generated-vs-picked, so
    counting a scene nobody could look at as one he passed over would
    read a grounding bug as a verdict on the writing."""
    preprod.set_picked(_concept(tmp_db, ["/refs/a.jpg"]), True, dsn=tmp_db,
                       account_id=None)
    _concept(tmp_db, ["/refs/b.jpg"])                 # generated, not picked
    before = preprod.pick_rate(tmp_db, account_id=None)
    assert (before["generated"], before["picked"]) == (2, 1)

    preprod.archive_ungrounded(_concept(tmp_db), dsn=tmp_db, account_id=None)
    after = preprod.pick_rate(tmp_db, account_id=None)
    assert (after["generated"], after["picked"]) == (2, 1)
    assert after["rate"] == before["rate"]


def test_an_ungrounded_scene_does_not_depress_shoot_rate(tmp_db):
    preprod.mark_shot(_concept(tmp_db, ["/refs/a.jpg"]), True, dsn=tmp_db,
                      account_id=None)
    preprod.archive_ungrounded(_concept(tmp_db), dsn=tmp_db, account_id=None)
    assert preprod.shoot_rate(tmp_db, account_id=None)["generated"] == 1


def test_a_hand_archived_row_still_counts_in_pick_rate(tmp_db):
    """The fence is around the MACHINE reason only. Archiving something
    yourself has always left it counted, and that is what keeps the rate
    falsifiable."""
    preprod.set_archived(_concept(tmp_db, ["/refs/a.jpg"]), True, dsn=tmp_db,
                         account_id=None, reason="off-brand")
    assert preprod.pick_rate(tmp_db, account_id=None)["generated"] == 1

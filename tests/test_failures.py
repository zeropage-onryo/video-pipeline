"""A render that did not happen, in a customer's words (src/failures.py).

The live tile that started this read a provider's billing error to a
customer under a card that said Done. These hold the three promises:
the vendor and its links never reach the page, the studio's own refusals
pass through untouched, and every sentence says whether credits moved.
"""
import pytest

from src import charge, failures, ledger

SEEN_LIVE = ('HTTP Error 403: Forbidden -- {"detail":"User is locked. Reason: Exhausted '
             'balance. Top up your balance at fal.ai/dashboard/billing."}')


def test_the_error_seen_live_names_no_vendor_and_no_link():
    said = failures.plain(SEEN_LIVE)
    assert said == ("The still was not made: the image service turned the studio away. "
                    "That is ours to fix, not yours. Nothing was charged.")
    for leak in ("fal", "403", "http", "{", "billing", "Top up"):
        assert leak not in said


@pytest.mark.parametrize("raw, cause", [
    ("fal not configured — FAL_KEY is unset", "turned the studio away"),
    ("no Gemini key -- set GEMINI_API_KEY for the installation", "turned the studio away"),
    ("HTTP Error 401: Unauthorized", "turned the studio away"),
    ("HTTP Error 429: Too Many Requests", "is busy"),
    ("429 RESOURCE_EXHAUSTED", "is busy"),
    ("content_policy_violation: the prompt was flagged", "declined this prompt"),
    ("fal job timed out after 600s", "did not answer"),
    ("HTTP Error 503: Service Unavailable", "did not answer"),
    ("RuntimeError: fal completed but carried no output URL", "reported an error"),
])
def test_a_cause_a_person_can_act_on_differently_is_said_differently(raw, cause):
    said = failures.plain(raw)
    assert said.startswith("The still was not made: the image ") and cause in said
    assert said.endswith(failures.NOT_CHARGED)
    assert "fal" not in said.lower() and "http" not in said.lower()
    # a clip that was not made is about the video service, never the image one
    clip = failures.plain(raw, "The clip")
    assert clip.startswith("The clip was not made: the video ") and "image" not in clip


def test_the_studios_own_refusals_pass_through_as_written():
    empty = charge.refusal(ledger.InsufficientCredit(account_id=1, requested=36, available=4),
                           "this still")
    assert failures.plain(empty) == empty
    cap = "daily cap: 6/6 images generated today -- try again tomorrow"
    assert failures.plain(cap) == cap
    assert failures.plain(charge.CREATE_REFUSAL) == charge.CREATE_REFUSAL


def test_nothing_to_say_still_says_what_happened_to_the_credits():
    assert failures.plain("") == "The still was not made. Nothing was charged."
    assert failures.plain(None, "The sheet") == "The sheet was not made. Nothing was charged."

"""Signed quotes: the thing that renders is provably the thing that was
priced (src/pricing.py sign/verify, step 4 of
docs/tasks/task-pricing-and-quotes.md).

Same standard as tests/test_pricing.py: the line each test guards is
named, and it was seen to fail with that line reverted.
"""
import time

import pytest

from src import pricing

SECRET = "dGVzdC1zZWNyZXQtdGhpcnR5LXR3by1ieXRlcy1sb25nLW9r"


@pytest.fixture
def signing(monkeypatch):
    monkeypatch.setenv(pricing.SIGNING_ENV, SECRET)
    monkeypatch.setenv("RUNWAYML_API_SECRET", "OPERATOR-RUNWAY")


def scene(prompt="A man laces his boots in a cold garage.", refs=("/refs/a.jpg",)):
    return {"n": 1, "tool": "RUNWAY", "prompt": prompt, "refs": list(refs)}


def a_quote(shot=None, account_id=1, part=None):
    return pricing.quote(account_id=account_id, shot=shot or scene(), shot_id=361, part=part,
                         provider="runway", model="gen4_turbo", seconds=5)


def test_round_trip(signing):
    q = a_quote()
    token = pricing.sign(q)
    assert token.startswith("zpfq.") and token.count(".") == 2 and "=" not in token
    assert pricing.verify(token, account_id=1, shot=scene(), shot_id=361) == q


def test_a_quote_signs_the_same_bytes_every_time(signing):
    q = a_quote()
    assert pricing.sign(q, now=1_789_675_340) == pricing.sign(q, now=1_789_675_340)


# guards: hmac.compare_digest in verify (and the prefix / shape checks)
def test_one_flipped_byte_in_any_part_is_bad_signature(signing):
    token = pricing.sign(a_quote())
    head, body, mac = token.split(".")

    def flip(text):
        # the FIRST character, never the last: the last base64 character of
        # a 32-byte mac carries two unused bits, so A -> B there can decode
        # to the same bytes and the token (correctly) still verifies -- the
        # test then failed or passed by what second it was minted in
        ch = "B" if text[0] != "B" else "C"
        return ch + text[1:]

    for broken in (f"{flip(head)}.{body}.{mac}", f"{head}.{flip(body)}.{mac}",
                   f"{head}.{body}.{flip(mac)}", "zpf_notaquote", "", token + ".x"):
        with pytest.raises(pricing.QuoteRefused) as refused:
            pricing.verify(broken, account_id=1, shot=scene(), shot_id=361)
        assert refused.value.reason == "bad_signature", broken


# guards: the `exp < moment` check -- and that it is checked AFTER the
# signature, so an expired token is `expired`, not `bad_signature`
def test_an_old_quote_is_expired_not_invalid(signing):
    token = pricing.sign(a_quote(), now=int(time.time()) - pricing.QUOTE_TTL - 5)
    with pytest.raises(pricing.QuoteRefused) as refused:
        pricing.verify(token, account_id=1, shot=scene(), shot_id=361)
    assert refused.value.reason == "expired"
    assert "hour" in str(refused.value)
    # one second inside the window still verifies
    fresh = pricing.sign(a_quote(), now=int(time.time()) - pricing.QUOTE_TTL + 1)
    assert pricing.verify(fresh, account_id=1, shot=scene(), shot_id=361)


# guards: the chash comparison. THE HEADLINE: edit the prompt after
# quoting and the old price stops working. Passes with the hash removed
# from the body only if nothing compares it -- which is the bug.
def test_editing_the_prompt_after_signing_is_stale_content(signing):
    shot = scene()
    token = pricing.sign(a_quote(shot))
    shot["prompt"] += " He looks up."
    with pytest.raises(pricing.QuoteRefused) as refused:
        pricing.verify(token, account_id=1, shot=shot, shot_id=361)
    assert refused.value.reason == "stale_content"
    # so does changing what grounds it
    shot = scene()
    token = pricing.sign(a_quote(shot))
    shot["refs"].append("/refs/b.jpg")
    with pytest.raises(pricing.QuoteRefused) as refused:
        pricing.verify(token, account_id=1, shot=shot, shot_id=361)
    assert refused.value.reason == "stale_content"


# guards: the acct comparison
def test_another_accounts_quote_is_wrong_account(signing):
    token = pricing.sign(a_quote(account_id=1))
    with pytest.raises(pricing.QuoteRefused) as refused:
        pricing.verify(token, account_id=2, shot=scene(), shot_id=361)
    assert refused.value.reason == "wrong_account"


# guards: the shot / part comparison
def test_a_quote_for_another_render_is_wrong_render(signing):
    token = pricing.sign(a_quote())
    with pytest.raises(pricing.QuoteRefused) as refused:
        pricing.verify(token, account_id=1, shot=scene(), shot_id=362)
    assert refused.value.reason == "wrong_render"
    with pytest.raises(pricing.QuoteRefused) as refused:
        pricing.verify(token, account_id=1, shot=scene(), shot_id=361, part=2)
    assert refused.value.reason == "wrong_render"


# guards: the SUPPORTED_PRICING_VERSIONS membership check
def test_a_retired_pricing_version_is_retired_pricing(signing, monkeypatch):
    token = pricing.sign(a_quote())
    monkeypatch.setattr(pricing, "SUPPORTED_PRICING_VERSIONS", ("2099-01-01-video-v9",))
    with pytest.raises(pricing.QuoteRefused) as refused:
        pricing.verify(token, account_id=1, shot=scene(), shot_id=361)
    assert refused.value.reason == "retired_pricing"


# guards: _secret() raising rather than defaulting
def test_no_secret_means_no_signing_and_no_default(monkeypatch):
    monkeypatch.delenv(pricing.SIGNING_ENV, raising=False)
    monkeypatch.setenv("RUNWAYML_API_SECRET", "OPERATOR-RUNWAY")
    assert pricing.configured() is False
    with pytest.raises(pricing.SigningUnconfigured) as unset:
        pricing.sign(a_quote())
    assert pricing.SIGNING_COMMAND in str(unset.value)
    with pytest.raises(pricing.SigningUnconfigured):
        pricing.verify("zpfq.x.y", account_id=1, shot=scene(), shot_id=361)
    # the price still shows; no token rides with it
    shown = pricing.display(account_id=1, shot=scene(), shot_id=361, provider="runway",
                            model="gen4_turbo", seconds=5)
    assert shown["signed"] is False and shown["renders"][0]["token"] is None


def test_the_suite_does_not_inherit_a_real_secret():
    """tests/conftest.py POSTURE_ENV: a secret present on one machine and
    absent in CI is the failure class that has bitten twice."""
    assert pricing.configured() is False


def test_the_secret_is_its_own_not_the_account_keys_one(signing, monkeypatch):
    monkeypatch.setenv("ACCOUNT_KEYS_SECRET", "something-else")
    token = pricing.sign(a_quote())
    monkeypatch.setenv("ACCOUNT_KEYS_SECRET", "rotated")
    assert pricing.verify(token, account_id=1, shot=scene(), shot_id=361)
    monkeypatch.setenv(pricing.SIGNING_ENV, SECRET + "x")
    with pytest.raises(pricing.QuoteRefused) as refused:
        pricing.verify(token, account_id=1, shot=scene(), shot_id=361)
    assert refused.value.reason == "bad_signature"


def test_display_signs_one_token_per_shot(signing):
    prompt = "BEATS (0-7s) he laces both boots. (7-10s) the visor drops."
    shot = scene(prompt)
    shown = pricing.display(account_id=1, shot=shot, shot_id=361, provider="runway",
                            model="gen4_turbo")
    assert shown["signed"] is True
    tokens = [r["token"] for r in shown["renders"]]
    assert len(tokens) == 2 and len(set(tokens)) == 2
    for r in shown["renders"]:
        q = pricing.verify(r["token"], account_id=1, shot=shot, shot_id=361, part=r["part"])
        assert (q.part, q.seconds, q.credits) == (r["part"], r["seconds"], r["credits"])
    # BYOK-shaped: nothing to charge, nothing to sign
    assert pricing.display(account_id=None, shot=shot, shot_id=361, provider="runway",
                           model="gen4_turbo")["signed"] is True   # env key: billable

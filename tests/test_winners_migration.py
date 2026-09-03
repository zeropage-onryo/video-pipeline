"""
winners.init() and avoid_guidance() on a fresh schema.

This file used to pin a SQLite migration: a winning_prompts table from
before `verdict` existed crashed a trigger run (hold 4, 2026-08-11) with
'no such column: verdict', and init() learned to ALTER the column in.
On Postgres (2026-09-03) the column is simply in the CREATE TABLE and no
database predates it, so what stays pinned is the contract that crash
exposed: init is idempotent, avoid_guidance -- reached on every
orchestrator run -- returns a string and never raises, and a verdict
round-trips.
"""
from src import winners


def test_init_is_idempotent(pg):
    winners.init(dsn=pg)
    winners.init(dsn=pg)  # second call must be a no-op, not an error
    entry_id = winners.add("runway", "another prompt", verdict="didnt_work", dsn=pg)
    assert winners.get(entry_id, dsn=pg)["verdict"] == "didnt_work"


def test_avoid_guidance_self_initialises_and_never_raises(pg):
    """The exact crash path: a verdict filter before anyone ran init()."""
    result = winners.avoid_guidance(dsn=pg)
    assert isinstance(result, str)


def test_avoid_guidance_on_an_unreachable_store_is_empty_not_fatal():
    """Best-effort by contract: a negative steer must never block a generation."""
    assert winners.avoid_guidance(dsn="postgresql://nobody@127.0.0.1:1/nowhere") == ""

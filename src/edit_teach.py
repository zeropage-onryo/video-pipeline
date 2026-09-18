#!/usr/bin/env python3
"""
Does a hand edit of a scene prompt teach the RAG shelves? -- the gate,
and the vocabulary the routes and the Teach tab share (2026-09-18).

WHAT IT CLOSES. Before this, every prompt edit -- the Director prompt
bar, the Pipeline card's in-place edit, a Direct note -- went through
`preprod.update_concept_shots` and nowhere else. The edit changed what
rendered and taught nothing. Worse, the one path that DID teach (the
board's pick, `api._board_verdict`) snapshotted the prompt at click time:
edit-then-pick filed the human's text as "worked" with no record of the
draft it replaced, and pick-then-edit filed the draft while the edit
vanished. Either way the contrast -- the model's draft beside the
person's fix, which is what `winners.record_pair` was built to hold --
was thrown away at the one moment it was in hand.

WHAT IT DOES NOW, when the account's row says so: a saved edit records a
PENDING pair on `concept-{id}-shot-{n}` (the board's own ref), the
model's draft on the avoid side and the edit on the winning side, and
the concept lands on the Teach tab where grade-all ingests it exactly as
it ingests a board tap. Nothing reaches a shelf until that pass, so an
edit is recallable right up until it is taught.

WHY IT IS PER ACCOUNT, AND A COLUMN. The shelves are shared on purpose
(`db.SHARED_TABLES`, and the learning tables stay global by Mike's call);
`project` labels a row with the tenant that taught it and boosts their
own retrieval, but every tenant's writer retrieves from the same pool. A
pilot user retyping a prompt to fix a typo would be teaching Mike's
writer, and Mike's edits would be teaching theirs. So the gate is
`accounts.prompt_edits_teach`, FALSE for everybody, flipped by hand:

    python -m src.accounts edits-teach <slug> --on

The manual-lane rules apply unchanged (src/manual_lane.py): the check is
server-side against the account id, it fails closed on every error and
on the unowned pool, and nothing about membership is consulted.

THE MODEL'S DRAFT IS REMEMBERED ON THE SHOT. `shot["model_prompt"]` is the
last text a MODEL wrote for that shot, captured at the first hand edit
(the pre-edit prompt) and kept across further hand edits, so the pair is
always draft -> latest edit rather than edit -> re-edit. Every model
writer drops it (`scene_chain.persist_prompt`, `director.direct_scene`
via the route, `director.refine_shot_prompt`), so the next hand edit
snapshots afresh. It is written only when the gate is on -- an account
that is off gets no new key on its rows.

ONE PENDING PAIR PER SHOT, LATEST WINS. A new edit replaces a pending
board verdict or a pending edit pair on the same ref; a verdict from the
Grade tab (any other note) is never touched, and nothing already
ingested is either -- `api._board_verdict`'s own asymmetry, extended.
A Direct note's pair is (prompt before the note -> revision after), with
the note in the row, because the note is the person's stated reason.

WHAT IT CANNOT TELL. The Director's Save prompt button can save the
ENHANCE node's text, which Gemini wrote. The server sees a prompt that
differs from the draft and files it as the person's fix; that it is a
machine's polish the person chose is a distinction the route is not
handed. If the shelves start reading like the enhance instruction, that
is where to look.
"""
from __future__ import annotations

from typing import Optional

from .db import EDIT_TEACH_COLUMN, connect

# The column that IS the gate (src/db.py's add_prompt_edits_teach_column).
COLUMN = EDIT_TEACH_COLUMN

# The command that moves it.
COMMAND = "python -m src.accounts edits-teach <slug> --on"

# The key on a shot that remembers the model's last draft. Never on a
# row whose account is off.
DRAFT_KEY = "model_prompt"

# Notes the pair rows carry, so the Teach tab and the replacement rule
# can tell an edit from a board tap and from a Grade-tab verdict.
EDIT_NOTE = "edited by hand"
DIRECT_NOTE_PREFIX = "directed: "


def direct_note(note: str) -> str:
    """The row note for a Direct-note pair: the person's reason, marked."""
    return DIRECT_NOTE_PREFIX + " ".join((note or "").split())


def is_edit_note(note: Optional[str]) -> bool:
    """Whether a winners row was filed by this module (either door)."""
    note = note or ""
    return note == EDIT_NOTE or note.startswith(DIRECT_NOTE_PREFIX)


def allowed(account_id: Optional[int], dsn: Optional[str] = None) -> bool:
    """THE gate. True only for an account whose own row says so.

    manual_lane.manual_lane_allowed's shape exactly: one row by id, None
    (the unowned pool) is never allowed, and every failure -- no table,
    no column, no database -- is a no.
    """
    if account_id is None:
        return False
    try:
        wanted = int(account_id)
    except (TypeError, ValueError):
        return False
    try:
        with connect(dsn) as conn:
            row = conn.execute(
                f"SELECT {COLUMN} FROM accounts WHERE id = %s",
                (wanted,)).fetchone()
            return bool(row and row[COLUMN])
    except Exception:
        return False


def draft_of(shot: dict, before: str) -> str:
    """The model's draft for this shot: the remembered one if a hand edit
    already captured it, else the text that stood before THIS edit."""
    return ((shot.get(DRAFT_KEY) or "") or (before or "")).strip()


def forget_draft(shot: dict) -> None:
    """A model rewrote this shot: the next hand edit snapshots afresh."""
    shot.pop(DRAFT_KEY, None)


__all__ = [
    "COLUMN", "COMMAND", "DRAFT_KEY", "EDIT_NOTE", "DIRECT_NOTE_PREFIX",
    "direct_note", "is_edit_note", "allowed", "draft_of", "forget_draft",
]

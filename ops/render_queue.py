#!/usr/bin/env python3
"""
The repo side of rendering the queue on SUBSCRIPTION credits.

Why this file exists. src/higgsfield.py talks to Higgsfield Cloud, which
bills API credits -- real money, a balance separate from the app plan.
The Higgsfield MCP spends the app subscription's credits instead (~997
already paid for, ~4.8 per seedance clip), but an MCP server is only
reachable from a Claude session, never from the nightly LangGraph. So
the split is:

    Claude session   -- picks the shots, calls the MCP, downloads the mp4
    this file        -- tells it what is waiting, and files what came back

TWO LANES NOW, the same shape (`--provider`, default higgsfield):

    higgsfield  the MCP, above. Reachable from a session, so a session
                can do the whole job without a human's hands.
    runway      NOT reachable from anything. Runway's API has exactly
                one billing path (developer credits at $0.01), and the
                Unlimited plan's free-but-queued Explore Mode is a
                WEB-APP TOGGLE with no API parameter -- src/runway.py
                cannot ask for it however much it wants to. So the
                render happens in Chrome: `list` prints the prompt, the
                keyframe URL to drag in as the start image, and the
                target duration/ratio; a human renders it; `import`
                files the mp4 exactly as the higgsfield lane does.

BOTH LANES ARE OPERATOR-ONLY, AND THAT IS A SECURITY PROPERTY, not a
convenience. Each spends one of the operator's PERSONAL consumer plans,
so serving a paying tenant's shot on either is reselling a consumer
subscription -- an account-termination risk that takes every tenant's
renders down at once. `src/manual_lane.py` holds the allowlist and the
reasoning; this file only ever asks it (`manual_lane.require`), never
re-decides. There is deliberately NO --operator flag, --force, or
environment escape here -- and since 2026-09-08 no environment DOOR
either: the gate is `accounts.manual_lane_operator`, a column on the
account row, and the answer is a function of the account id alone,
resolved server-side. An account nobody has turned on is refused, so
BOTH commands below need `python -m src.accounts operator <slug> --on`
run once and an --account that names that slug.

Subcommands, all safe to run by hand:

    python3 ops/render_queue.py --account zeropage list
    python3 ops/render_queue.py --account zeropage import --concept 128 \
        --shot 1 --file /tmp/clip.mp4 --model seedance1_5 --credits 4.8

    python3 ops/render_queue.py --provider runway --account zeropage list
    python3 ops/render_queue.py --provider runway --account zeropage import \
        --concept 131 --shot 1 --file ~/Downloads/gen4-turbo.mp4 \
        --model gen4_turbo --duration 10 --anchored

WHAT `import` NOW CHECKS INSTEAD OF BELIEVING. `--model`, `--ratio` and
`--duration` land in a `generations` row the tool scoreboard reads, so
until 2026-09-08 a 1am typo became a measurement of a model that never
ran. The runway lane's claims are checked against src/render_specs.py's
per-model legal values and REFUSED, not clamped, when they do not fit --
a value outside the set is evidence that the row and the clip have come
apart, and rounding it hides exactly that. The Higgsfield lane's model
names are the MCP's own and are published nowhere this repo can read, so
they are recorded rather than checked, and the row says so
(`model_verified`) instead of implying a check that never happened.

And the file itself is asked how long it is: `ffprobe`, the same probe
`orchestrator._clip_passes_qc` already uses, writes `duration_measured_s`
beside the claimed `duration`, so a 5s clip filed as 10s is visible in
the row rather than silently trusted. With no ffprobe on PATH the row
says THAT, in `duration_source` -- an absent measurement must not read
like a measurement that agreed.

WHERE THE CLIP HAS TO LIVE. app/main.py mounts /renders on data/renders/,
so that directory is the only place a media_url can point at -- a file
left in footage/generated/ 404s in the Queue however real it is. import
copies whatever you hand it into data/renders/<provider>/ -- the same
folder that provider's adapter already writes to, so the /renders mount
and the media_url derivation are unchanged for both lanes -- and derives
the URL from there.

NO THIRD-PARTY IMPORT OF ITS OWN. It imports src.preprod / src.generative
/ src.accounts / src.manual_lane / src.render_specs and nothing else
(note src.manual_lane imports src.db and stdlib only, src.render_specs
imports NOTHING, and this file never imports src.runway -- that would
drag google-genai in through render_assets), so it ran under any
python3 while those were stdlib --
the repo venvs are macOS builds and a Claude session's shell is Linux.
Since the move to Postgres (2026-09-03) src.db needs psycopg, so the
interpreter running this must have it; the script itself still adds
nothing on top.

The SQLite journal-mode fuse that used to sit above the imports (a
per-connection PRAGMA so a COMMIT over the desktop bridge's FUSE mount
would not die with "disk I/O error") went with SQLite: a network
database has no journal file on the mount to protect.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ruff: noqa: I001 -- these imports must come after the sys.path line.
from src import accounts, generative, manual_lane, preprod, render_specs   # noqa: E402
from src.shot import Shot                     # noqa: E402


PROVIDERS = ("higgsfield", "runway")

# The lanes that spend the OPERATOR'S personal consumer subscription
# rather than a credential a tenant could have bought for themselves.
# Membership here is what puts src/manual_lane.py's allowlist in front of
# a call.
#
# BOTH lanes are here, and higgsfield joining runway on 2026-09-08 is a
# DELIBERATE BREAK of a workflow that used to need no configuration. It
# is the same exposure -- a consumer app subscription spent on any
# account's shot -- and gating one lane while leaving the other open is
# worse than gating neither, because it reads as though the question had
# been asked and answered. The existing Higgsfield workflow now needs
# `python -m src.accounts operator <slug> --on` run once against the
# database; the refusal names that command, which is what anyone who
# hits it needs.
#
# The API-billed adapters (src/higgsfield.py, src/runway.py) are NOT
# affected and were not touched: they spend a credential a tenant can
# own, metered per call, under their own spend gates and daily caps.
# This gate is about the subscription lanes only.
GATED_PROVIDERS = ("higgsfield", "runway")


def _provider(name) -> str:
    """The lane, normalised, or a refusal naming the ones that exist."""
    provider = (name or "higgsfield").strip().lower()
    if provider not in PROVIDERS:
        raise SystemExit(f"unknown provider {provider!r} -- one of {list(PROVIDERS)}")
    return provider


def _guard(provider: str, account_id: int | None) -> None:
    """The gate, asked ONCE per entry point and never re-decided here.

    Both `pending` and `import_clip` call it, rather than only `main`,
    because this module is imported as a library by its tests and could
    be by anything else: a gate that lives in the argument parser is a
    gate that a second caller walks around without noticing.

    The refusal is `manual_lane.REFUSAL` and nothing else -- it must not
    say who IS allowed, whether the allowlist is configured, or whether
    the lane exists for anybody, because all three are answers an
    unauthorised caller could assemble into a map of the operator's
    setup.
    """
    if provider not in GATED_PROVIDERS:
        return
    try:
        manual_lane.require(account_id)
    except manual_lane.LaneRefused as refusal:
        raise SystemExit(str(refusal)) from None


def _lane_duration(shot: dict) -> int:
    """What to set the duration chip to before pressing Generate.

    The shot's own number when it carries one, else the lane default --
    which is NOT src/runway.py's DEFAULT_DURATION of 5. On the API every
    second is a credit; on Explore Mode the queue is the price and the
    seconds are free. Printed on every row because the web app resets
    this control to 5s on each page load (docs/RUNBOOK.md 2026-09-06)
    and a whole round once went out at half length because of it.
    """
    try:
        return int(shot.get("duration"))
    except (TypeError, ValueError):
        return manual_lane.LANE_DURATION


def _verify_claims(provider: str, model: str, ratio, duration) -> bool:
    """Check what the operator says they rendered, before anything is
    written down. Returns whether the MODEL claim was actually checked.

    Refuses (SystemExit, the script's own idiom) rather than clamping, and
    refuses BEFORE the clip is copied and before any row exists -- a
    rejected claim must leave the install exactly as it found it, the
    same rule the gate above keeps.
    """
    for check, args in ((render_specs.check_ratio, (provider, model, ratio)),
                        (render_specs.check_duration, (provider, model, duration))):
        try:
            check(*args)
        except ValueError as wrong:
            raise SystemExit(str(wrong)) from None
    try:
        return render_specs.check_model(provider, model)
    except ValueError as wrong:
        raise SystemExit(str(wrong)) from None


def _measure_duration(path: Path) -> tuple[float | None, str]:
    """How long the clip on disk actually is, and how we know.

    ffprobe is asked the same way `orchestrator._clip_passes_qc` asks it
    -- one spelling of "ask ffprobe about this file" per repo, or the two
    quietly stop agreeing. It is OPTIONAL here rather than required,
    because this script runs wherever the human downloaded the mp4 and a
    missing ffprobe must not stop a real render being filed.

    Returns (seconds, source). `None` seconds is never silent: the source
    string goes in the row and says which kind of not-knowing it was, so
    an absent measurement cannot be mistaken for one that agreed with the
    claim.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None, "unmeasured -- ffprobe is not on PATH"
    try:
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        seconds = float((out.stdout or "").strip() or 0)
    except Exception:
        return None, "unmeasured -- ffprobe could not read the file"
    if seconds <= 0:
        return None, "unmeasured -- ffprobe could not read the file"
    return round(seconds, 2), "ffprobe"


def pending(brand=None, account_id: int | None = None,
            provider: str = "higgsfield") -> list[dict]:
    """What is waiting on a spend, by exactly the rule app/api.py's
    /queue/manual uses: picked (not merely parked), not archived, a scene, no clip
    yet, and reference photos attached. Duplicated deliberately in ONE
    place only -- if that rule changes, this is the line to change with
    it. The reference half is not duplicated at all: both surfaces call
    preprod.reference_gate, which is why the manual lane cannot hand a
    human a shot the Queue page would refuse to render.

    ONE rule for both lanes, on purpose: which provider renders a shot is
    a decision made at the keyboard, not a property of the queue, and a
    second predicate here would be a second definition of "waiting" to
    keep in sync with the Queue page. The runway lane adds fields to each
    row (the keyframe to drag in, the duration and ratio to set) but
    never changes which rows there are.

    `prompt` is the stored shot prompt, which IS the gate-passed one:
    nothing reaches `shots_json` without going through the prompt gate
    that wrote it there (`autonomy.score_prompts`), so this lane renders
    the same text the API lane would have.
    """
    provider = _provider(provider)
    _guard(provider, account_id)
    out = []
    for concept in preprod.list_concepts(account_id=account_id):
        if brand and concept.get("brand") != brand:
            continue
        # picked only -- a parked scene nobody chose is the Queue's to
        # approve (which picks it), not a person's to render by hand
        # (2026-09-14, matching queue_manual in app/api.py)
        if not concept.get("picked"):
            continue
        if concept.get("archived") or not concept.get("is_scene"):
            continue
        # The lane is free, so the instinct is to let anything through.
        # It is not the credit this protects: a human dragging a
        # reference-less shot into Runway by hand produces the same
        # ungrounded clip, and then it is in data/renders looking like
        # output somebody chose.
        if preprod.reference_gate(concept):
            continue
        for shot in concept.get("shots") or []:
            if shot.get("media_url"):
                continue
            row = {
                "concept_id": concept["id"],
                "title": concept.get("title") or "",
                "brand": concept.get("brand"),
                "shot_n": shot.get("n", 1),
                "tool": (shot.get("tool") or "").upper(),
                "prompt": (shot.get("prompt") or "").strip(),
                "reference_image": shot.get("reference_image") or "",
                "logline": concept.get("logline") or "",
            }
            if provider == "runway":
                # What a human actually needs in front of the web app:
                # the frame to drag into the start-image slot, and the
                # two controls to set before Generate.
                row["keyframe_url"] = row["reference_image"]
                row["duration"] = _lane_duration(shot)
                row["ratio"] = shot.get("ratio") or manual_lane.LANE_RATIO
                row["lane"] = manual_lane.LANES["runway"]
            out.append(row)
    return out


RENDER_DIR = REPO / "data" / "renders" / "higgsfield"
# src/runway.py's own output directory, not a new one: the /renders mount
# and every media_url derived from it stay exactly as they are, so a clip
# rendered by hand and a clip rendered through the API are the same kind
# of file in the same place.
RUNWAY_RENDER_DIR = REPO / "data" / "renders" / "runway"
RENDERS_ROOT = REPO / "data" / "renders"


def _render_dir(provider: str):
    """Read through the module attributes rather than a dict, so the test
    suite's redirect of RENDER_DIR / RUNWAY_RENDER_DIR away from the real
    data/renders/ still lands (conftest's output_roots lesson: a stub clip
    in the owner's render folder is indistinguishable from a real one)."""
    return RUNWAY_RENDER_DIR if provider == "runway" else RENDER_DIR


def _place(src: Path, provider: str = "higgsfield") -> Path:
    """The clip, sitting somewhere /renders can actually serve it.
    Already under data/renders/ -> left alone. Anywhere else -> copied
    (not moved: a Claude session's shell cannot delete, and a half-moved
    render is worse than a duplicate)."""
    src = src.resolve()
    try:
        src.relative_to(RENDERS_ROOT.resolve())
        return src
    except ValueError:
        pass
    render_dir = _render_dir(provider)
    render_dir.mkdir(parents=True, exist_ok=True)
    dest = render_dir / src.name
    n = 1
    while dest.exists():
        dest = render_dir / f"{src.stem}-{n}{src.suffix}"
        n += 1
    dest.write_bytes(src.read_bytes())
    return dest


def import_clip(concept_id: int, shot_n, file: str, model: str,
                credits: float | None, prompt: str | None,
                anchored: bool,
                account_id: int | None = None,
                provider: str = "higgsfield",
                duration: int | None = None,
                ratio: str | None = None,
) -> dict:
    """File a finished clip: a generations row so genlog, pick_rate and
    the tool scoreboard see the attempt, then the media_url that
    autopilot.build_plan requires before it will emit a post action.

    cost_usd is left NULL on purpose, in BOTH lanes. The clip was paid
    for out of a subscription that was already bought, so a dollar figure
    here would be invented -- src/costs.py reports such a row as FREE
    with a count, never as $0.00 and never backfilled. What was really
    spent goes in params_json, where it is honest: Higgsfield's app
    credits as a number, Runway Explore's as nothing at all, because
    Explore Mode's price is the queue rather than a balance.

    NO LEDGER HOLD IS TAKEN, and there is no code here that decides that.
    `params["source"]` is the lane marker, and `ledger.is_billable` --
    the one place that rule lives -- reads it and refuses to hold, for
    the same structural reason a BYOK render takes no hold: somebody
    already paid for this clip somewhere the ledger cannot see. Holding
    would debit a CUSTOMER'S credit for a render made on the OPERATOR'S
    personal plan, which is the exact inversion this lane exists to
    avoid.

    `key_source` is written as None deliberately: no API credential was
    used at all. That value reads as "unknown, therefore billable" to
    `is_billable`, which is precisely why the lane marker and not the
    absent credential is what makes the row unbillable.
    """
    provider = _provider(provider)
    _guard(provider, account_id)

    path = Path(file)
    if not path.is_absolute():
        path = REPO / path
    if not path.is_file():
        raise SystemExit(f"no such clip: {path}")
    if path.stat().st_size < 1024:
        raise SystemExit(f"clip is {path.stat().st_size} bytes -- that is not a video")

    concept = preprod.get_concept(concept_id, account_id=account_id)
    if concept is None:
        raise SystemExit(f"no concept {concept_id}")
    shot = next((s for s in concept.get("shots") or []
                 if s.get("n") == shot_n), None)
    if shot is None:
        raise SystemExit(f"concept {concept_id} has no shot {shot_n}")

    text = (prompt or shot.get("prompt") or "").strip()
    if not text:
        raise SystemExit("no prompt to log this attempt against")

    # What was claimed, checked before the clip moves and before a row
    # exists. `claimed_*` are what goes in the row as the claim; the
    # measurement below is recorded beside them rather than replacing
    # them, because the row's job is to show the two and let a human see
    # a disagreement.
    claimed_duration = (int(duration) if duration else _lane_duration(shot))
    claimed_ratio = ratio or shot.get("ratio") or manual_lane.LANE_RATIO
    if provider == "runway":
        model_verified = _verify_claims(provider, model, claimed_ratio,
                                        claimed_duration)
    else:
        # The Higgsfield lane's --duration/--ratio are not written into
        # its row at all (the MCP call decided them), so there is nothing
        # to check them against and nothing they could corrupt.
        model_verified = _verify_claims(provider, model, None, None)

    path = _place(path, provider)
    measured, measured_by = _measure_duration(path)
    generative.init()

    if provider == "runway":
        where = ("rendered by hand in the Runway web app on the operator's "
                 "Unlimited subscription (Explore Mode)")
        params = {"model": model,
                  "source": manual_lane.SOURCE,
                  "lane": manual_lane.LANES["runway"],
                  "key_source": None,
                  "duration": claimed_duration,
                  "ratio": claimed_ratio,
                  "concept_id": concept_id, "shot_n": shot_n,
                  "prompt_image": bool(anchored),
                  # the claim, checked; and the file, measured
                  "model_verified": model_verified,
                  "duration_measured_s": measured,
                  "duration_source": measured_by}
        if credits is not None:
            params["credits"] = credits
        notes = "subscription render, not API credits -- no ledger hold"
    else:
        where = "rendered via the Higgsfield MCP on subscription credits"
        params = {"model": model, "source": "mcp-subscription",
                  "credits": credits, "concept_id": concept_id,
                  "shot_n": shot_n, "prompt_image": bool(anchored),
                  # false, and honestly so: the MCP publishes no model
                  # list this script could have checked the name against
                  "model_verified": model_verified,
                  "duration_measured_s": measured,
                  "duration_source": measured_by}
        notes = "subscription credits, not API credits"

    shot_row_id = generative.add_shot(
        Shot(subject=text[:100], action="as prompted"),
        notes=f"{where} (concept {concept_id} shot {shot_n})",
        account_id=account_id)
    generation_id = generative.record_generation(
        shot_row_id, provider, text,
        params=params,
        output_path=str(path),
        cost_usd=None,
        notes=notes, account_id=account_id)

    media_url = "/renders/" + str(path.relative_to(RENDERS_ROOT.resolve())).replace("\\", "/")
    preprod.set_shot_media_url(concept_id, shot_n, media_url, account_id=account_id)
    return {"ok": True, "generation_id": generation_id,
            "media_url": media_url, "path": str(path), "provider": provider}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="what is waiting on a spend, as JSON")
    p_list.add_argument("--brand")

    p_imp = sub.add_parser("import", help="file a finished clip")
    p_imp.add_argument("--concept", type=int, required=True)
    p_imp.add_argument("--shot", type=int, default=1)
    p_imp.add_argument("--file", required=True)
    p_imp.add_argument("--model", required=True,
                       help="the model that actually rendered it. Checked "
                            "against the lane's known models where there are "
                            "any (runway); recorded unverified where there "
                            "are none (the higgsfield MCP)")
    p_imp.add_argument("--credits", type=float)
    p_imp.add_argument("--prompt")
    p_imp.add_argument("--anchored", action="store_true",
                       help="the render was anchored on the keyframe")
    p_imp.add_argument("--duration", type=int,
                       help="seconds actually generated (runway lane: the "
                            "duration chip you set before Generate). Checked "
                            "against the model's legal lengths, and against "
                            "the file itself when ffprobe is on PATH")
    p_imp.add_argument("--ratio",
                       help="aspect ratio actually generated (runway lane: "
                            "uploading a 9:16 start image flips this chip). "
                            "Checked against the model's legal frames")

    ap.add_argument(
        "--account", default=None,
        help="account slug to act as (default: the oldest on the database)")
    ap.add_argument(
        "--provider", default="higgsfield", choices=list(PROVIDERS),
        help="which lane. `runway` is the operator's own Unlimited "
             "subscription driven by hand in Chrome, and is refused for "
             "any account the allowlist does not name.")

    args = ap.parse_args()
    # A Claude session drives this by hand; there is no cookie behind it.
    # Resolving here rather than defaulting to None deeper down, because
    # after the tenancy backfill nobody owns nothing -- `list` would print
    # an empty queue and look like there was no work waiting.
    account_id = accounts.resolve_account(args.account)
    if args.cmd == "list":
        print(json.dumps(pending(args.brand, account_id=account_id,
                                 provider=args.provider), indent=2))
    else:
        print(json.dumps(import_clip(args.concept, args.shot, args.file,
                                     args.model, args.credits, args.prompt,
                                     args.anchored, account_id=account_id,
                                     provider=args.provider,
                                     duration=args.duration,
                                     ratio=args.ratio), indent=2))


if __name__ == "__main__":
    main()

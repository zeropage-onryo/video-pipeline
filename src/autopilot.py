#!/usr/bin/env python3
"""
The L4 path: generate AI shots via platform APIs and post on a
schedule -- built last, gated hardest, and OFF by default.

The contract here is the gate, not the executors. Three independent
conditions must all align before anything irreversible runs:

  1. ZEROPAGE_AUTOPILOT=1 in the environment (the standing enable),
  2. an explicit approve=True on the call (`run --approve` in the CLI
     -- per-run consent, never remembered),
  3. no kill-switch file at data/autopilot.off (`autopilot kill`
     creates it; deleting it is a deliberate manual act).

Anything less falls through to dry-run, which describes every action
it would have taken and touches nothing. That mirrors
promote_winners' propose/approve split, one level up.

The EXECUTORS registry is where platform generation APIs and posting
adapters plug in. They are deliberately unwired: each raises until a
real adapter is registered, because wiring real API spend and real
public accounts is the user's explicit call, not a default. Building
the gate before the guns means the dangerous part ships already caged.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import autonomy, instagram, preprod, tiktok, youtube

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KILL_SWITCH_PATH = PROJECT_ROOT / "data" / "autopilot.off"
# Where generated candidates land. A module-level constant rather than a
# path built inside _generate, because a path built inside the function
# cannot be redirected -- and an output root a test cannot redirect is an
# output root a test eventually writes to for real.
GENERATED_DIR = PROJECT_ROOT / "footage" / "generated"

ENABLE_ENV = "ZEROPAGE_AUTOPILOT"

# THE POSTING GATE, and what it is and is not (2026-09-02, from the
# pilot dry run). Publishing is the most expensive irreversible action
# in the product, and before this it was the one action with no per-run
# approval: ZEROPAGE_AUTOPILOT, the platform credentials, and the
# data/autopilot.off kill switch are three facts about THE INSTALLATION
# -- standing configuration -- and none of them is about the run or the
# caller. Every render tool has a per-run SPEND_OK; posting had nothing
# equivalent, so the only thing between a stranger and Mike's Instagram
# was whether the kill-switch file happened to exist that day.
#
# ZEROPAGE_POST_OK=1 is the per-run approval, in exactly the SPEND_OK
# shape: set it on the command (the serve command, the cron line, the
# autopilot CLI), never in .env, so a process that can publish is one a
# person started saying so. It is checked inside _post_dispatch, the
# way the spend gates live inside generate_video, so no caller can post
# around it -- and again in execute() so a plan reports "post-unapproved"
# instead of failing mid-run.
#
# What it still is NOT: a fact about the caller. Ownership is now
# enforced (a hold has an account_id and /api/holds/{id}/post 404s on
# someone else's), but the credentials a post goes out under belong to
# the installation, and "may THIS person publish as the installation" is
# the role system this project deliberately does not have yet (`role`
# is recorded and enforced nowhere). This gate is the honest floor
# under that decision, not a substitute for it.
POST_ENV = "ZEROPAGE_POST_OK"

# Which brands may enter an AUTO-post plan. Empty means none: everything
# lands in the Queue and a person pushes it out.
#
# WHY A CONSTANT AND NOT THE ENV VAR (2026-08-31). ZEROPAGE_AUTOPILOT
# also gates the MANUAL approve-and-post button (app/main.py: "Posting is
# OFF -- set ZEROPAGE_AUTOPILOT=1"), so switching it off to stop the
# machine posting would also stop Mike posting by hand from the Queue --
# the opposite of what "everything goes to the Queue for now" means. The
# posture belongs in code anyway, which is what the block in build_plan
# has always said.
#
# This is a HOLD, not a repeal. Zero Page was built to auto-post and the
# whole uncanny gate exists to make that safe; the hold is until the loop
# has proved itself on something a person chose to publish. Re-enable by
# putting "zeropage" back in this tuple -- and note that ANTIHERO must
# never be added: it is review-gated forever, which is why the check
# below reads from a whitelist rather than excluding one name.
AUTO_POST_BRANDS: tuple[str, ...] = ()


def _unwired(kind: str) -> Callable[[dict], Any]:
    def executor(action: dict):
        raise NotImplementedError(
            f"no {kind} adapter wired -- connecting a real platform API is a "
            "deliberate step, not a default. See autopilot.EXECUTORS."
        )
    return executor


def execute_generate_action(action: dict):
    """
    The headless half of the video renderer: same core as the
    interactive path (fal.generate_candidates -- daily cap, a
    generations row per attempt, the credit hold, never-raises), reached
    ONLY through the full gate above, because every call costs real
    money. fal since 2026-09-26, the only video renderer (it was Veo on
    the Gemini key before). Nothing is auto-kept: the clips land as
    candidates and the keeper is still a human pick.
    """
    from . import fal
    out_dir = GENERATED_DIR / f"autopilot-{action.get('concept_id', 'x')}"
    return fal.generate_candidates(
        action.get("prompt", ""), out_dir,
        n=int(action.get("candidates", 1)),
    )


# kind -> callable(action). Both adapters are real but only ever run in
# live mode -- the gate above them is unchanged. post refuses without
# IG_USER_ID/IG_ACCESS_TOKEN; generate goes through fal.py's daily cap
# and logs every attempt as a generations row.
def post_approved() -> bool:
    """The per-run human approval for publishing. Same contract as the
    render tools' spend_approved(): set ZEROPAGE_POST_OK=1 on the
    command, not in .env -- an approval that's always on isn't one."""
    return (os.environ.get(POST_ENV) or "").strip() == "1"


def _post_dispatch(action: dict):
    """Route a post action to its platform's executor. Defaults to
    Instagram (the original behavior); 'youtube' uploads a local file;
    'tiktok' hands TikTok a public URL to pull. All three are only ever
    reached in live mode, behind the same gate --
    and behind the per-run posting approval, checked here so nothing
    that reaches an executor directly can publish around it."""
    if not post_approved():
        raise RuntimeError(
            f"posting not approved: set {POST_ENV}=1 on this run to publish "
            f"(per run, never in .env)")
    platform = (action.get("platform") or "instagram").strip().lower()
    if platform == "youtube":
        return youtube.execute_post_action(action)
    if platform == "instagram":
        return instagram.execute_post_action(action)
    if platform == "tiktok":
        return tiktok.execute_post_action(action)
    raise NotImplementedError(f"no post adapter for platform {platform!r}")


EXECUTORS: dict[str, Callable[[dict], Any]] = {
    "generate": execute_generate_action,
    "post": _post_dispatch,
}


def enabled() -> bool:
    return (os.environ.get(ENABLE_ENV) or "").strip().lower() in {"1", "true", "yes"}


def killed() -> bool:
    return KILL_SWITCH_PATH.exists()


def build_plan(db_path=None, account_id: Optional[int] = None) -> dict[str, Any]:
    """
    What the machine would do next, assembled read-only: one `generate`
    action per AI shot on a planned-but-unshot concept. Posting actions
    enter the plan only once generated media exists to post -- the plan
    never invents deliverables.
    """
    kwargs = {"dsn": db_path} if db_path is not None else {}
    actions: list[dict[str, Any]] = []
    for concept in preprod.list_concepts(**kwargs, account_id=account_id):
        if concept.get("shot_done"):
            continue
        for shot in concept.get("ai_shots") or []:
            prompt = (shot.get("prompt") or "").strip()
            if not prompt:
                continue
            actions.append({
                "kind": "generate",
                "concept_id": concept["id"],
                "concept_title": concept.get("title"),
                "tool": shot.get("tool"),
                "prompt": prompt,
            })
        # The postures are enforced HERE, at the plan, so no configuration
        # mistake downstream can auto-post the wrong thing:
        #   ANTIHERO is review-gated forever -- it NEVER enters an auto-post
        #     plan. Michael's face and name only post when he approves.
        #   ZERO PAGE is review-gated too, for now (2026-08-31, Mike's call):
        #     AUTO_POST_BRANDS is empty, so EVERYTHING goes to the Queue and
        #     a person pushes it out. Even a concept that clears the on-brand
        #     gate stays put.
        #   The uncanny check below stays regardless -- when Zero Page is let
        #     back out, an unjudged concept must still be ineligible.
        if concept.get("brand") not in AUTO_POST_BRANDS:
            continue
        if not concept.get("uncanny_passed"):
            continue

        # Posting enters the plan only once generated media exists: a
        # shot carrying a rendered public media_url (which is also what
        # Meta's API requires). One post per concept, first rendered
        # shot wins -- the plan never invents deliverables.
        rendered = next(
            (s for s in concept.get("shots") or []
             if (s.get("media_url") or "").strip()),
            None,
        )
        if rendered:
            # ONE ACTION PER TARGET (2026-09-07). The plan used to name
            # Instagram and nothing else, so a channel whose `targets`
            # said "instagram,youtube" published to half of them and the
            # column was decoration. The fan-out reads that column --
            # the same one /api/holds/{id}/post has always fanned out on
            # -- so the two publishing paths agree about where a channel
            # posts instead of each having its own idea.
            #
            # Every gate is untouched and every one of them is UPSTREAM
            # of here: the kill switch, the enable env, the per-run
            # approval and the rate cap all sit in execute(), so fanning
            # out multiplies what a plan DESCRIBES, never what it is
            # allowed to do. The brand and uncanny checks above still
            # decide whether any of this is reached at all.
            #
            # Falling back to Instagram when there is no channel row
            # keeps the pre-fan-out behaviour for a database that has no
            # channels table (every preprod-only fixture, and the plan
            # is a read-only preview that must still work there).
            media_url = rendered["media_url"].strip()
            is_local = not media_url.startswith("http")
            targets = autonomy.channel_targets(concept.get("brand") or "",
                                               dsn=db_path) or ["instagram"]
            for platform in targets:
                actions.append({
                    "kind": "post",
                    "platform": platform,
                    "concept_id": concept["id"],
                    "title": concept.get("title"),
                    "video_url": media_url,
                    # YouTube uploads bytes, not a URL: hand it the path
                    # when the render never reached public storage, and
                    # let its executor say so when neither exists.
                    "video_path": media_url if is_local else "",
                    "caption": concept.get("hook") or concept.get("title") or "",
                })
    return {"actions": actions}


def execute(plan: dict, approve: bool = False, dry_run: bool = True) -> dict[str, Any]:
    """
    Run a plan through the gate. Returns what happened and why --
    including, in every non-live mode, the full list of actions that
    would have run, so a dry run is a real preview rather than a shrug.
    """
    actions = plan.get("actions") or []
    described = [
        f"{a.get('kind')}: {a.get('tool') or a.get('platform') or '?'} — "
        f"{(a.get('prompt') or a.get('title') or '')[:60]}"
        for a in actions
    ]

    wants_to_post = any(a.get("kind") == "post" for a in actions)
    if killed():
        mode = "killed"
    elif not enabled():
        mode = "disabled"
    elif not approve:
        mode = "unapproved"
    elif dry_run:
        mode = "dry-run"
    elif wants_to_post and not post_approved():
        # the per-run posting approval (POST_ENV above): a live plan that
        # would publish reports so and executes nothing, rather than
        # running its generate actions and then failing at the post
        mode = "post-unapproved"
    else:
        mode = "live"

    if mode != "live":
        # money reads as money before anyone approves: N generations ≈ $X
        generate_count = sum(1 for a in actions if a.get("kind") == "generate")
        preview = {"mode": mode, "executed": 0, "skipped": [],
                   "would_execute": described}
        if generate_count:
            from . import fal
            preview["estimated_generation_cost_usd"] = fal.estimate_cost(generate_count)
        return preview

    executed = 0
    skipped: list[str] = []
    for action in actions:
        executor = EXECUTORS.get(action.get("kind"))
        if executor is None:
            skipped.append(f"no executor for kind {action.get('kind')!r}")
            continue
        executor(action)
        executed += 1
    return {"mode": "live", "executed": executed, "skipped": skipped,
            "would_execute": described}


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="The gated L4 path. Off by default; dry-run unless "
                    "--approve AND --live AND the enable env AND no kill switch.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("plan", help="show what would run (always safe)")

    p_run = sub.add_parser("run", help="execute the plan through the gate")
    p_run.add_argument("--approve", action="store_true",
                       help="explicit per-run consent (required for live)")
    p_run.add_argument("--live", action="store_true",
                       help="disable dry-run (still requires the env enable)")

    sub.add_parser("kill", help="write the kill switch; nothing runs until it's removed")

    args = parser.parse_args(argv)

    if args.command == "kill":
        KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)
        KILL_SWITCH_PATH.write_text("autopilot disabled by kill switch\n")
        print(f"kill switch written: {KILL_SWITCH_PATH}")
        return

    plan = build_plan()
    if args.command == "plan":
        print(json.dumps(plan, indent=2))
        print(f"\n{len(plan['actions'])} action(s). Nothing was executed.",
              file=sys.stderr)
        return

    result = execute(plan, approve=args.approve, dry_run=not args.live)
    print(json.dumps(result, indent=2))
    if result["mode"] != "live":
        print(f"\nmode={result['mode']} -- nothing was executed.", file=sys.stderr)


if __name__ == "__main__":
    main()

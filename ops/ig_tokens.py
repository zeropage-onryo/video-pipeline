#!/usr/bin/env python3
"""
The two Instagram credentials, by hand: check them, wind the publishing
one's clock, install a fresh one of either.

    python -m ops.ig_tokens check [--probe]   # read-only; the default
    python -m ops.ig_tokens refresh           # IG_ACCESS_TOKEN +60 days, into .env
    python -m ops.ig_tokens publish           # install a re-issued IG_ACCESS_TOKEN
    python -m ops.ig_tokens research          # issue + install IG_GRAPH_TOKEN

(`bash ops/ig_token.sh <command>` is the same thing from a double-click.)

TWO CREDENTIALS, TWO HOSTS, ON PURPOSE (see src/instagram.py):
  IG_ACCESS_TOKEN  publishing + insights. Instagram Login, graph.instagram.com,
                   app "ZeroPageFilms". Scopes: instagram_business_basic,
                   instagram_business_content_publish,
                   instagram_business_manage_insights (the metrics sweep reads
                   insights). The pre-2025 names instagram_basic /
                   instagram_content_publish do NOT exist on Instagram Login.
  IG_GRAPH_TOKEN   the research lane (business_discovery, hashtag_top_media).
                   Facebook Login, graph.facebook.com, a SECOND app pointed at
                   the Page that has the Instagram account linked. There
                   instagram_basic IS the right name, with pages_show_list,
                   pages_read_engagement and business_management.
                   The lane reads the account id from IG_BUSINESS_ID (falling
                   back to IG_USER_ID -- instagram.graph_user_id), so this
                   writes IG_BUSINESS_ID.

What this never does: print a token, publish, or look up a hashtag (that
spends Meta's 30-tags-per-7-days budget). Secrets are read with getpass.
Every write to .env copies it to .env.bak.<stamp> first.

An OPERATOR tool, which is why it lives in ops/ and may write .env: the
nightly sweep (src/refresh_metrics.py) refreshes too, but it never writes
.env -- it keeps a new token in data/ig_token.json. `refresh` here is the
person-driven version that puts the token where the rest of the world
(Fly secrets included) copies it from.
"""
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import requests
from dotenv import load_dotenv

from src import instagram

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

PUBLISH_APP_ID = "1382270770525151"     # ZeroPageFilms -- Instagram Login
RESEARCH_PAGE_ID = "101446494797064"    # the "Mike Massaad" Page, IG linked
PROBE_HANDLE = "zeropagefilms"          # business_discovery reads this account


# --------------------------------------------------------------------------
# .env, written carefully
# --------------------------------------------------------------------------

def set_env(values: dict, path: Path = None, now=None) -> Path:
    """Set KEY=value lines in `path`, replacing an existing line or
    appending one. Copies the file to `.env.bak.<stamp>` first and returns
    that backup's path. Values are never echoed."""
    path = Path(path or ENV_FILE)
    stamp = (now or datetime.now()).strftime("%Y%m%d%H%M%S")
    path.touch(exist_ok=True)
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, backup)
    try:
        backup.chmod(0o600)
    except OSError:
        pass
    lines = path.read_text().splitlines(keepends=True)
    pending = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in pending:
            out.append(f"{key}={pending.pop(key)}\n")
        else:
            out.append(line)
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    out += [f"{k}={v}\n" for k, v in pending.items()]
    path.write_text("".join(out))
    return backup


def _reset_store(token: str, expires_in: Optional[int], now=None) -> None:
    """After a token is written into .env, the refresh store must stop
    serving whatever it held: record the clock against the NEW .env token,
    with no replacement token in it."""
    now = now or datetime.now(timezone.utc)
    record = {"refreshed_at": now.isoformat(),
              "replaces": instagram._fingerprint(token),
              "access_token": None,
              "expires_at": ((now + timedelta(seconds=int(expires_in))).isoformat()
                             if expires_in else None)}
    try:
        instagram._write_token_store(record)
    except OSError:
        pass


def _meta_error(body: dict, token: str = "") -> str:
    err = (body or {}).get("error") or {}
    message = err.get("message") if isinstance(err, dict) else str(err)
    return instagram._safe_error(Exception(message or "no message"), token)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_check(probe: bool = False, *, get=None, say=print) -> int:
    """Read-only: one call per token. Exit 1 when either needs a person."""
    checks = instagram.token_health(get=get)
    for c in checks:
        say(("!!! " if c.get("warning") else "    ") + instagram.health_line(c))
        if c.get("scopes"):
            say(f"      scopes: {', '.join(c['scopes'])}")
    graph = checks[1]
    if probe and graph.get("ok"):
        result = instagram.business_discovery(PROBE_HANDLE, limit=1)
        if result.get("ok"):
            say(f"    business_discovery: OK -- read @{PROBE_HANDLE} "
                f"({result.get('followers')} followers). The research lane can run.")
        else:
            say(f"!!! business_discovery: FAILED -- {result.get('error')}")
            return 1
    return 1 if any(c.get("warning") for c in checks) else 0


def cmd_refresh(*, env_path: Path = None, refresh=None, say=print, now=None) -> int:
    """Wind IG_ACCESS_TOKEN's 60-day clock and write the answer into .env.
    Meta refuses a token under 24h old and cannot revive an expired one --
    for that, re-issue it and use `publish`."""
    refresh = refresh or instagram.refresh_access_token
    token = instagram.access_token()
    if not token:
        say("FAIL: IG_ACCESS_TOKEN is not set -- nothing to refresh. "
            + instagram.PUBLISH_FIX)
        return 1
    try:
        data = refresh(token)
    except Exception as e:                                  # noqa: BLE001
        say("FAIL: refresh refused: " + instagram._safe_error(e, token))
        say("      an expired token cannot be refreshed -- " + instagram.PUBLISH_FIX)
        return 1
    new = data["access_token"]
    backup = set_env({"IG_ACCESS_TOKEN": new}, env_path)
    _reset_store(new, data.get("expires_in"), now=now)
    days = int(data.get("expires_in") or 0) // 86400
    say(f"ok -- IG_ACCESS_TOKEN refreshed, {days} days left"
        + (" (Meta issued a new string)" if new != token else " (same string, longer clock)"))
    say(f"     .env updated; previous copy at {backup.name}")
    say("     if Fly posts or refreshes metrics, copy it there too: "
        "fly secrets set IG_ACCESS_TOKEN=... -a zeropage-studio")
    return 0


def cmd_publish(*, env_path: Path = None, ask: Callable = getpass.getpass,
                get=None, post=None, exchange: bool = False, say=print) -> int:
    """Install a re-issued IG_ACCESS_TOKEN (Instagram Login). The dashboard's
    Generate-token button hands out a long-lived token already; `--exchange`
    takes a short-lived OAuth token plus the app secret instead."""
    get = get or requests.get
    token = (ask("IG_ACCESS_TOKEN (paste; not echoed): ") or "").strip()
    if not token:
        say("FAIL: no token given.")
        return 1
    expires_in = None
    if exchange:
        secret = (ask("ZeroPageFilms app secret (not echoed): ") or "").strip()
        try:
            body = get("https://graph.instagram.com/access_token",
                       params={"grant_type": "ig_exchange_token",
                               "client_secret": secret, "access_token": token},
                       timeout=15).json()
        except Exception as e:                              # noqa: BLE001
            say("FAIL: exchange unreachable: " + instagram._safe_error(e, token))
            return 1
        if not body.get("access_token"):
            say("FAIL: exchange refused: " + _meta_error(body, token))
            return 1
        token, expires_in = body["access_token"], body.get("expires_in")
    check = instagram.check_publish_token(token, get=get)
    if not check["ok"]:
        say("FAIL: " + instagram.health_line(check))
        return 1
    user = get(f"{instagram.API_ROOT}/me", params={"fields": "user_id,username",
                                                    "access_token": token},
               timeout=10).json()
    values = {"IG_ACCESS_TOKEN": token}
    if user.get("user_id"):
        values["IG_USER_ID"] = str(user["user_id"])
    backup = set_env(values, env_path)
    _reset_store(token, expires_in)
    say(f"ok -- IG_ACCESS_TOKEN installed for @{user.get('username') or '?'}"
        + (f", IG_USER_ID={values['IG_USER_ID']}" if "IG_USER_ID" in values else ""))
    say(f"     .env updated; previous copy at {backup.name}")
    return 0


def pick_page(pages: list, page_id: str = RESEARCH_PAGE_ID) -> Optional[dict]:
    """The Page whose linked Instagram account the lane reads as: the named
    one when it is linked, else the only linked one. Two linked Pages and
    neither named is refused rather than guessed."""
    linked = [p for p in pages if p.get("instagram_business_account")]
    named = next((p for p in linked if str(p.get("id")) == str(page_id)), None)
    if named:
        return named
    return linked[0] if len(linked) == 1 else None


def cmd_research(*, app_id: str, page_id: str = RESEARCH_PAGE_ID,
                 env_path: Path = None, ask: Callable = getpass.getpass,
                 get=None, say=print) -> int:
    """Issue IG_GRAPH_TOKEN: short-lived Facebook-Login user token + the
    research app's id/secret -> fb_exchange_token (~60 days) -> me/accounts
    -> the Page's instagram_business_account -> .env."""
    get = get or requests.get
    if not app_id:
        say("FAIL: --app-id is required (the RESEARCH app, Facebook Login).")
        return 1
    if app_id == PUBLISH_APP_ID:
        say(f"FAIL: {app_id} is ZeroPageFilms, the Instagram-Login publishing app. "
            "The research token needs the second app (Instagram API with "
            "Facebook login). Its use case is not changed from here.")
        return 1
    secret = (ask("Research app secret (not echoed): ") or "").strip()
    short = (ask("Short-lived user token from Graph API Explorer (not echoed): ")
             or "").strip()
    if not (secret and short):
        say("FAIL: both the app secret and the short-lived token are required.")
        return 1

    root = instagram.GRAPH_ROOT
    try:
        body = get(f"{root}/oauth/access_token",
                   params={"grant_type": "fb_exchange_token", "client_id": app_id,
                           "client_secret": secret, "fb_exchange_token": short},
                   timeout=15).json()
    except Exception as e:                                  # noqa: BLE001
        say("FAIL: exchange unreachable: " + instagram._safe_error(e, short))
        return 1
    long = body.get("access_token")
    if not long:
        say("FAIL: exchange refused: " + _meta_error(body, short))
        say("      usual causes: wrong app secret, or the short-lived token "
            "(about an hour) already expired")
        return 1
    say(f"1/3  exchanged -- long-lived token issued "
        f"(expires_in={body.get('expires_in', 'unknown')}s)")

    try:
        pages = get(f"{root}/me/accounts",
                    params={"fields": "name,id,instagram_business_account{id,username}",
                            "access_token": long}, timeout=15).json()
    except Exception as e:                                  # noqa: BLE001
        say("FAIL: me/accounts unreachable: " + instagram._safe_error(e, long))
        return 1
    if "error" in pages:
        say("FAIL: me/accounts: " + _meta_error(pages, long)
            + " -- grant pages_show_list and business_management on the Page")
        return 1
    rows = pages.get("data") or []
    for p in rows:
        iba = p.get("instagram_business_account") or {}
        say(f"     {'LINKED' if iba else 'no IG '}  {p.get('name')} ({p.get('id')})"
            + (f" -> @{iba.get('username')} ({iba.get('id')})" if iba else ""))
    page = pick_page(rows, page_id)
    if not page:
        say(f"FAIL: no usable Page. Page {page_id} must be granted to the token "
            "and have the Instagram account linked (Page -> Linked accounts).")
        return 1
    ig_id = str(page["instagram_business_account"]["id"])
    say(f"2/3  Page {page.get('name')} -> Instagram account {ig_id}")

    backup = set_env({"IG_GRAPH_TOKEN": long, "IG_BUSINESS_ID": ig_id}, env_path)
    say(f"3/3  .env updated (IG_GRAPH_TOKEN, IG_BUSINESS_ID); previous copy at "
        f"{backup.name}")

    check = instagram.check_graph_token(long, get=get)
    say(("!!! " if check.get("warning") else "    ") + instagram.health_line(check))
    probe = instagram.business_discovery(PROBE_HANDLE, limit=1, token=long,
                                         user_id=ig_id)
    if probe.get("ok"):
        say("    business_discovery: OK -- the research lane can run "
            "(it stays out of scout's default lanes until you flip it)")
        return 0
    say(f"!!! business_discovery: FAILED -- {probe.get('error')}")
    say("    a permissions / Advanced Access message means App Review; a "
        "'not a professional account' message means the Page link, not the token")
    return 1


def main(argv=None) -> int:
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(prog="ig_tokens", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    p_check = sub.add_parser("check", help="read-only validity + expiry of both tokens")
    p_check.add_argument("--probe", action="store_true",
                         help="also read @zeropagefilms through business_discovery "
                              "(read-only, no hashtag budget)")
    sub.add_parser("refresh", help="wind IG_ACCESS_TOKEN another 60 days, into .env")
    p_pub = sub.add_parser("publish", help="install a re-issued IG_ACCESS_TOKEN")
    p_pub.add_argument("--exchange", action="store_true",
                       help="the pasted token is short-lived: exchange it (asks for "
                            "the app secret)")
    p_res = sub.add_parser("research", help="issue + install IG_GRAPH_TOKEN")
    p_res.add_argument("--app-id", default=os.environ.get("IG_RESEARCH_APP_ID", ""),
                       help="the research app's id (or IG_RESEARCH_APP_ID)")
    p_res.add_argument("--page-id", default=RESEARCH_PAGE_ID)
    args = parser.parse_args(argv)

    if args.command == "refresh":
        return cmd_refresh()
    if args.command == "publish":
        return cmd_publish(exchange=args.exchange)
    if args.command == "research":
        return cmd_research(app_id=args.app_id, page_id=args.page_id)
    return cmd_check(probe=getattr(args, "probe", False))


if __name__ == "__main__":
    sys.exit(main())

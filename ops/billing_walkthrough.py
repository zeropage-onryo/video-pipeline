#!/usr/bin/env python3
"""
The paid path, walked once in Stripe TEST MODE before anyone real pays
(2026-09-29). Everything a customer touches is built -- checkout, the
webhook grant, credits drawn down by Create, keyframes and renders -- and
none of it has been used by anyone but the exempt operator.

WHAT THIS CAN NEVER TOUCH, by construction:
- real money: every Stripe call refuses a key that is not `sk_test_` /
  `rk_test_` (`_stripe`), so a live key pasted into the wrong file fails
  before a request is made;
- the live database: the server this prints runs on its OWN schema
  (`billwalk`) on the local throwaway Postgres, and the DATABASE_URL it
  exports is always that one -- dotenv never overrides an exported var;
- the real R2 bucket: the serve line blanks the R2 credentials, because a
  worktree server otherwise loads the main checkout's .env and mirrors to
  the real bucket (found 2026-09-26);
- fal: FAL_KEY is blanked unless `serve --with-render`, which is the one
  step that spends real money (~$0.36 for the cheapest LTX clip).

NO STRIPE CLI NEEDED. Locally the webhook would need `stripe listen`; here
`relay` reads the test account's own events off the Stripe API and POSTs
each to the local /billing/webhook, signed with a local secret exactly the
way Stripe signs (`t=...,v1=HMAC-SHA256(secret, "t.payload")`). What that
tests is the part that is ours -- verifying, granting, idempotency on
redelivery -- not Stripe's delivery, which is theirs.

The keys live in `.env.billing-walk` at the repo root (gitignored by the
`.env.*` rule): STRIPE_SECRET_KEY=sk_test_... is the only line a person
writes; `prices` and `seed` add the rest.

    venv/bin/python -m ops.billing_walkthrough prices    # 7 test Prices = pricing.PLANS
    venv/bin/python -m ops.billing_walkthrough seed      # schema + a PAYING (non-exempt) account
    venv/bin/python -m ops.billing_walkthrough serve     # prints the uvicorn line to run
    venv/bin/python -m ops.billing_walkthrough checkout starter   # a test Checkout URL
    venv/bin/python -m ops.billing_walkthrough relay     # Stripe events -> local webhook
    venv/bin/python -m ops.billing_walkthrough create    # one Create as the customer (15 cr)
    venv/bin/python -m ops.billing_walkthrough status    # balance, lots, every ledger entry
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.billing-walk"
SEEN_FILE = ROOT / "data" / "billing_walk_relayed.json"

SCHEMA = "billwalk"
BASE_DSN = os.environ.get("TEST_DATABASE_URL") or "postgresql://zeropage:zeropage@localhost:5432/zeropage"
# its own port: 8011 is the usual worktree dev server, and a walk must not
# answer on another session's server (found on the first dry run)
PORT = int(os.environ.get("WALK_PORT", "8021"))
HOST = f"http://app.localhost:{PORT}"     # its own cookie jar, apart from localhost's
EMAIL = "walkthrough@example.test"

# the webhook events handle_event acts on (docs/BILLING.md)
EVENTS = ("checkout.session.completed", "invoice.paid", "customer.subscription.updated",
          "customer.subscription.deleted", "charge.refunded")


def dsn() -> str:
    """The walk's own schema on the throwaway Postgres -- never DATABASE_URL."""
    sep = "&" if "?" in BASE_DSN else "?"
    return f"{BASE_DSN}{sep}options=-c%20search_path%3D{SCHEMA}"


# --- the key file -------------------------------------------------------------

def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def write_env(updates: dict[str, str]) -> None:
    current = read_env()
    current.update(updates)
    body = "# Stripe TEST MODE only -- ops/billing_walkthrough.py. Gitignored (.env.*).\n"
    body += "".join(f"{k}={v}\n" for k, v in current.items())
    ENV_FILE.write_text(body)
    ENV_FILE.chmod(0o600)


def _stripe():
    key = read_env().get("STRIPE_SECRET_KEY", "")
    if not key:
        sys.exit(f"put STRIPE_SECRET_KEY=sk_test_... in {ENV_FILE.name} first "
                 f"(Stripe dashboard, TEST mode -> Developers -> API keys)")
    if not key.startswith(("sk_test_", "rk_test_")):
        sys.exit("that is not a TEST key (sk_test_/rk_test_). This walk never uses a "
                 "live key -- nothing was sent.")
    import stripe
    stripe.api_key = key
    return stripe


# --- prices ---------------------------------------------------------------------

def cmd_prices(_args) -> None:
    """One test Price per plan x interval plus the top-up, amounts read off
    pricing.py so the site and Stripe cannot disagree. Idempotent: found by
    lookup_key, never duplicated."""
    stripe = _stripe()
    from src import billing, pricing

    wanted = []
    for key, plan in pricing.PLANS.items():
        wanted.append((key, "month", plan.monthly_usd, plan.name))
        wanted.append((key, "year", plan.yearly_usd, plan.name))
    wanted.append((pricing.TOPUP.key, "once", pricing.TOPUP.usd, pricing.TOPUP.name))

    updates = {}
    for key, interval, usd, name in wanted:
        lookup = f"zpf_walk_{key}_{interval}"
        found = stripe.Price.list(lookup_keys=[lookup], limit=1).data
        if found:
            price = found[0]
            state = "found"
        else:
            product = stripe.Product.create(name=f"ZPF {name} (walkthrough)")
            params = dict(product=product.id, currency="usd",
                          unit_amount=int(round(usd * 100)), lookup_key=lookup)
            if interval != "once":
                params["recurring"] = {"interval": interval}
            price = stripe.Price.create(**params)
            state = "created"
        if price.unit_amount != int(round(usd * 100)):
            sys.exit(f"{lookup} is ${price.unit_amount / 100} in Stripe but ${usd} in "
                     f"pricing.py -- fix one of them; nothing was written")
        env = billing.price_env_for(key, "month" if interval == "once" else interval)
        updates[env] = price.id
        print(f"  {state:7} {lookup:28} ${usd:>7}  -> {env}")
    write_env(updates)
    print(f"wrote {len(updates)} price ids to {ENV_FILE.name}")


# --- the database -------------------------------------------------------------

def cmd_seed(args) -> None:
    """The walk's schema, a user, and the two accounts -- NOT exempt, which
    is the whole point: this account pays like a customer would."""
    import psycopg

    from src import accounts, db, ledger
    with psycopg.connect(BASE_DSN, autocommit=True) as admin:
        if args.fresh:
            admin.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        admin.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    db.init_db(dsn())
    accounts.seed(EMAIL, display_name="Walkthrough", dsn=dsn())
    ledger.init(dsn())
    user = accounts.get_user_by_email(EMAIL, dsn=dsn())
    for slug in ("zeropage", "antihero"):
        accounts.set_credit_exempt(slug, False, dsn=dsn())
    env = read_env()
    write_env({
        "SESSION_SECRET": env.get("SESSION_SECRET") or secrets.token_urlsafe(32),
        # our own signing secret: relay signs with it, the server verifies with it
        "STRIPE_WEBHOOK_SECRET": env.get("STRIPE_WEBHOOK_SECRET")
        or "whsec_walk_" + secrets.token_urlsafe(24),
    })
    print(f"schema {SCHEMA} ready; user {EMAIL} (id {user['id']}); accounts NOT exempt")


def _account_id() -> int:
    from src import db
    with db.connect(dsn()) as conn:
        return int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])


def cookie() -> str:
    """A session cookie for the walk's user, under the walk's secret."""
    os.environ["SESSION_SECRET"] = read_env()["SESSION_SECRET"]
    from app import auth
    from src import accounts
    user = accounts.get_user_by_email(EMAIL, dsn=dsn())
    return auth._serializer().dumps({"uid": str(user["id"])})


# --- the server -------------------------------------------------------------------

def cmd_serve(args) -> None:
    env = read_env()
    missing = [k for k in ("STRIPE_SECRET_KEY", "SESSION_SECRET", "STRIPE_WEBHOOK_SECRET")
               if not env.get(k)]
    if missing:
        sys.exit(f"missing {', '.join(missing)} -- run `prices` and `seed` first")
    exports = {
        "DATABASE_URL": dsn(),
        # blanked: a worktree server loads the main .env, and these would
        # mirror to the REAL bucket / spend on the real fal account
        "R2_ACCOUNT_ID": "", "R2_ACCESS_KEY_ID": "", "R2_SECRET_ACCESS_KEY": "",
        "R2_BUCKET": "", "R2_PUBLIC_BASE_URL": "",
        "STUDIO_URL": "", "BILLING_RETURN_URL": HOST,
        "FAL_RECOVER": "0",
        **{k: v for k, v in env.items()},
    }
    if not args.with_render:
        exports["FAL_KEY"] = ""
    line = " ".join(f"{k}={json.dumps(v)}" for k, v in exports.items())
    print(f"{line} PYTHONPATH=. venv/bin/uvicorn app.main:app --port {PORT}")


# --- driving it ---------------------------------------------------------------------

def api(method: str, path: str, body: Optional[dict] = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "Cookie": f"zp_session={cookie()}",
                 "X-Requested-With": "fetch"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode(errors="replace")[:500]}


def cmd_checkout(args) -> None:
    out = api("POST", "/api/billing/checkout", {"item": args.item, "interval": args.interval})
    if "url" not in out:
        sys.exit(f"no checkout URL: {out}")
    print("Open this, pay with the TEST card 4242 4242 4242 4242 (any future date, any CVC):")
    print(out["url"])


def cmd_create(args) -> None:
    """One Create as the paying customer -- a REAL Gemini call (~$0.04 on
    the operator's key) that should cost the account 15 credits."""

    import uuid
    boundary = uuid.uuid4().hex
    fields = {"idea": args.idea, "brand": "zeropage", "count": "1"}
    body = "".join(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
                   for k, v in fields.items()) + f"--{boundary}--\r\n"
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/scenes/run", data=body.encode(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Cookie": f"zp_session={cookie()}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            job = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"refused: HTTP {e.code} {e.read().decode(errors='replace')[:300]}")
    print(f"job {job['job_id']} started -- waiting for it")
    for _ in range(120):
        state = api("GET", f"/api/jobs/{job['job_id']}")
        if state.get("status") in ("done", "failed", "cancelled"):
            print(f"  {state['status']}: {state.get('detail') or state.get('error')}")
            return
        time.sleep(2)
    print("  still running -- check `status` in a minute")



def _sign(payload: bytes, secret: str) -> str:
    t = str(int(time.time()))
    mac = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def cmd_relay(args) -> None:
    """Stripe's events for this test account -> the local webhook, each
    once (remembered in data/billing_walk_relayed.json). --again resends
    them all, which is the redelivery check: nothing should grant twice."""
    stripe = _stripe()
    secret = read_env()["STRIPE_WEBHOOK_SECRET"]
    seen = set() if args.again or not SEEN_FILE.exists() else set(json.loads(SEEN_FILE.read_text()))
    deadline = time.time() + args.watch
    while True:
        events = stripe.Event.list(types=list(EVENTS), limit=50).data
        for event in reversed(events):
            if event.id in seen:
                continue
            # str() of an SDK object is its JSON -- the same shape Stripe POSTs
            payload = json.dumps(json.loads(str(event))).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{PORT}/billing/webhook", data=payload, method="POST",
                headers={"Content-Type": "application/json",
                         "Stripe-Signature": _sign(payload, secret)})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    result = r.read().decode()[:200]
            except urllib.error.HTTPError as e:
                result = f"HTTP {e.code} {e.read().decode(errors='replace')[:200]}"
            print(f"  {event.type:32} {event.id}  -> {result}")
            seen.add(event.id)
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(sorted(seen)))
        if time.time() >= deadline:
            return
        time.sleep(3)


def cmd_status(_args) -> None:
    from src import ledger
    account_id = _account_id()
    print(json.dumps(api("GET", "/api/billing/balance"), indent=2, default=str)[:1500])
    print("\nledger entries (oldest first):")
    for e in ledger.entries(account_id, dsn()):
        print(f"  #{e['id']:<4} {e['kind']:8} {e['delta']:>6}  {e.get('ref') or '':48} "
              f"gen={e.get('generation_id')}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prices")
    p = sub.add_parser("seed")
    p.add_argument("--fresh", action="store_true", help="drop the walk's schema first")
    p = sub.add_parser("serve")
    p.add_argument("--with-render", action="store_true",
                   help="keep FAL_KEY: the render step spends REAL money (~$0.36)")
    p = sub.add_parser("checkout")
    p.add_argument("item", nargs="?", default="starter")
    p.add_argument("--interval", default="month", choices=("month", "year"))
    p = sub.add_parser("relay")
    p.add_argument("--watch", type=int, default=0, help="keep polling for N seconds")
    p.add_argument("--again", action="store_true", help="resend everything (redelivery)")
    p = sub.add_parser("create")
    p.add_argument("idea", nargs="?", default="a rider suits up in a cold garage before dawn")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    {"prices": cmd_prices, "seed": cmd_seed, "serve": cmd_serve, "checkout": cmd_checkout,
     "relay": cmd_relay, "create": cmd_create, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()

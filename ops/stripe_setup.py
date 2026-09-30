"""Stripe, switched on in one run (docs/BILLING.md "Switching Stripe on").

    venv/bin/python -m ops.stripe_setup                 # test mode: prices + webhook -> .env
    venv/bin/python -m ops.stripe_setup --fly           # ...and push the same values to Fly
    venv/bin/python -m ops.stripe_setup --live --fly    # the same, against sk_live_ keys

Needs ONE thing by hand: STRIPE_SECRET_KEY in .env (Stripe dashboard ->
Developers -> API keys). Everything else is created here:

- the seven Prices, read off pricing.PLANS / pricing.TOPUP so the amount
  Stripe charges is the amount /pricing prints. Idempotent by lookup_key
  (`zpf_<item>_<interval>`): a rerun reuses a Price whose amount still
  matches and replaces one whose amount does not (the lookup key moves).
- the webhook endpoint on the API (Fly, not the Vercel site: the Next
  rewrites do not proxy /billing and the signature is over the raw body).
  Stripe shows a signing secret ONLY at creation, so an endpoint that
  already exists is reused only when .env still holds its secret AND
  names that endpoint's id (STRIPE_WEBHOOK_ENDPOINT -- a test secret
  must never be kept for a live endpoint); otherwise it is deleted and
  recreated (--rotate forces that). It is pinned to the SDK's API
  version, the event shape src/billing.py was walked against.
- BILLING_RETURN_URL = https://zeropage.studio.

.env is backed up before it is written. No secret is ever printed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import stripe

from src import billing, pricing

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
FLY_APP = "zeropage-studio"
WEBHOOK_URL = "https://zeropage-studio.fly.dev/billing/webhook"
RETURN_URL = "https://zeropage.studio"
ENDPOINT_ENV = "STRIPE_WEBHOOK_ENDPOINT"   # the id the secret in .env belongs to
# the events the handler acts on -- read, never copied, so they cannot drift
EVENTS = list(billing.HANDLED_EVENTS)


def read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV.exists():
        return out
    for line in ENV.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        out[k] = v.strip().strip('"').strip("'")
    return out


def write_env(updates: dict[str, str]) -> Path:
    # beside the REAL file: a worktree's .env is a symlink, and a backup
    # left in the worktree goes when the worktree does
    backup = ENV.resolve().with_name(f".env.bak.stripe.{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(ENV, backup)
    lines = ENV.read_text().splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        k = s.split("=", 1)[0].strip().removeprefix("export ").strip()
        if k in updates:
            lines[i] = f"{k}={updates[k]}"
            seen.add(k)
    missing = [k for k in updates if k not in seen]
    if missing:
        lines += ["", f"# Stripe -- written by ops/stripe_setup.py {time.strftime('%Y-%m-%d')}"]
        lines += [f"{k}={updates[k]}" for k in missing]
    ENV.write_text("\n".join(lines) + "\n")
    return backup


def find_product(item: str):
    """The Product tagged zpf_item=<item>. A list, not Product.search:
    search is eventually consistent, so a quick rerun would miss the
    Product the first run just made and create a duplicate."""
    for product in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        # a StripeObject, not a dict: .get() raises on it
        metadata = product.metadata.to_dict() if product.metadata else {}
        if metadata.get("zpf_item") == item:
            return product
    return None


def ensure_price(item: str, name: str, cents: int, interval: str | None) -> str:
    lookup = f"zpf_{item}_{interval or 'once'}"
    found = stripe.Price.list(lookup_keys=[lookup], active=True, limit=1).data
    if found and found[0].unit_amount == cents:
        print(f"  = {lookup:22} ${cents / 100:>7.2f}  (reused)")
        return found[0].id
    product = find_product(item) or stripe.Product.create(
        name=f"Zero Page {name}", metadata={"zpf_item": item})
    kwargs = dict(product=product.id, currency="usd", unit_amount=cents,
                  lookup_key=lookup, transfer_lookup_key=True,
                  metadata={"zpf_item": item, "interval": interval or "once"})
    if interval:
        kwargs["recurring"] = {"interval": interval}
    price = stripe.Price.create(**kwargs)
    if found:
        stripe.Price.modify(found[0].id, active=False)
        print(f"  ~ {lookup:22} ${cents / 100:>7.2f}  (amount changed; old price archived)")
    else:
        print(f"  + {lookup:22} ${cents / 100:>7.2f}  (created)")
    return price.id


def ensure_webhook(env: dict[str, str], rotate: bool) -> dict[str, str]:
    """The .env values for the endpoint -- empty when the ones there still serve.

    Reused only when .env holds a secret AND names this endpoint's id: a
    secret with no id, or another endpoint's (the test one, on a --live
    run), would sign nothing Stripe sends here."""
    existing = [e for e in stripe.WebhookEndpoint.list(limit=100).data if e.url == WEBHOOK_URL]
    ours = [e for e in existing if e.id == env.get(ENDPOINT_ENV)]
    if ours and env.get("STRIPE_WEBHOOK_SECRET") and not rotate:
        stripe.WebhookEndpoint.modify(ours[0].id, enabled_events=EVENTS)
        print(f"  = webhook {WEBHOOK_URL} (reused; secret in .env kept)")
        return {}
    for e in existing:
        stripe.WebhookEndpoint.delete(e.id)
    ep = stripe.WebhookEndpoint.create(url=WEBHOOK_URL, enabled_events=EVENTS,
                                       api_version=stripe.api_version,
                                       description="Zero Page credit ledger")
    print(f"  + webhook {WEBHOOK_URL} (created, {len(EVENTS)} events, API {stripe.api_version})")
    return {"STRIPE_WEBHOOK_SECRET": ep.secret, ENDPOINT_ENV: ep.id}


def push_to_fly(values: dict[str, str]) -> None:
    body = "".join(f"{k}={v}\n" for k, v in values.items())
    try:
        r = subprocess.run(["fly", "secrets", "import", "-a", FLY_APP],
                           input=body, text=True, capture_output=True)
    except FileNotFoundError:
        sys.exit("fly CLI not found -- install flyctl or rerun without --fly")
    if r.returncode:
        sys.exit(f"fly secrets import failed:\n{r.stderr.strip()}")
    print(f"  pushed {len(values)} secrets to Fly app {FLY_APP} (it redeploys itself)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="allow an sk_live_ key")
    ap.add_argument("--fly", action="store_true", help="also set the values as Fly secrets")
    ap.add_argument("--rotate", action="store_true", help="recreate the webhook endpoint")
    a = ap.parse_args(argv)

    env = read_env()
    key = env.get("STRIPE_SECRET_KEY", "")
    if not key:
        sys.exit("Put STRIPE_SECRET_KEY=sk_test_... in .env first "
                 "(Stripe dashboard -> Developers -> API keys, Test mode on).")
    mode = "live" if key.startswith(("sk_live_", "rk_live_")) else "test"
    if mode == "live" and not a.live:
        sys.exit("That's a LIVE key. Rerun with --live if you mean it.")
    if mode == "test" and a.live:
        sys.exit("--live given but STRIPE_SECRET_KEY is a test key.")
    stripe.api_key = key
    print(f"Stripe {mode.upper()} mode")

    updates: dict[str, str] = {}
    print("Prices:")
    for p in pricing.PLANS.values():
        updates[p.price_env] = ensure_price(p.key, p.name, p.monthly_usd * 100, "month")
        updates[p.price_env_yearly] = ensure_price(p.key, p.name, p.yearly_usd * 100, "year")
    t = pricing.TOPUP
    updates[t.price_env] = ensure_price(t.key, t.name, t.usd * 100, None)

    print("Webhook:")
    updates.update(ensure_webhook(env, a.rotate))
    updates["BILLING_RETURN_URL"] = RETURN_URL

    backup = write_env(updates)
    print(f".env: {len(updates)} values written (backup: {backup.name})")

    if a.fly:
        fly_values = {k: v for k, v in updates.items() if k != ENDPOINT_ENV}
        fly_values["STRIPE_SECRET_KEY"] = key
        if "STRIPE_WEBHOOK_SECRET" not in fly_values:
            fly_values["STRIPE_WEBHOOK_SECRET"] = env["STRIPE_WEBHOOK_SECRET"]
        push_to_fly(fly_values)

    print("\nLeft for you, once per mode, in the dashboard:")
    print("  Settings -> Billing -> Customer portal -> Save (turns on 'Manage plan').")


if __name__ == "__main__":
    main()

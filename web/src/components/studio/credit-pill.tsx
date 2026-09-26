"use client";

/* The credit pill in the studio bar (2026-09-25).

   The ledger, Stripe and /api/billing/balance all existed, and the studio
   never asked: a person who had just paid was told "open the studio to see
   your balance" by the checkout notice, and the studio showed no balance
   anywhere. This is the one place it is shown.

   Three states, all from src/billing.balance:
     - exempt   -- an operator account the ledger never charges. It says
                   so, rather than printing a number that never moves.
     - a number -- `available`: lots minus the holds renders in flight
                   still carry. Red at zero, because at zero the Queue
                   refuses (charge.refusal), key on file or not.
     - nothing  -- signed out, no account, or an API from before the route:
                   the pill is simply not drawn. A balance that failed to
                   load is not a balance of 0. */
import Link from "next/link";
import { useState } from "react";
import { Popover } from "@base-ui/react/popover";
import { Coins } from "lucide-react";
import type { Balance } from "@/lib/studio-api";
import { openPortal } from "@/lib/site-billing";

const num = (n: number) => n.toLocaleString("en-US");
const day = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};

/** the lot that runs out first, among those with anything left in them */
function nextExpiry(b: Balance): { credits: number; on: string } | null {
  const live = b.lots
    .filter((l) => l.remaining > 0 && l.expires_at)
    .sort((x, y) => String(x.expires_at).localeCompare(String(y.expires_at)));
  return live.length ? { credits: live[0].remaining, on: day(live[0].expires_at) } : null;
}

export function CreditPill({ balance, onError }: { balance: Balance | null; onError: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  if (!balance) return null;

  const empty = !balance.exempt && balance.available <= 0;
  const left = Math.max(balance.available, 0);
  const expiry = nextExpiry(balance);
  const release = balance.schedules.find((s) => s.next_release_at);

  const manage = async () => {
    setLeaving(true);
    const out = await openPortal();
    if (out.kind === "redirect") {
      window.location.href = out.url;
      return;
    }
    setLeaving(false);
    onError(out.kind === "sign-in" ? "Sign in again to manage billing" : out.message);
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        className={`tag zcredit-pill${empty ? " empty" : ""}`}
        title={balance.exempt ? "This account is not charged credits" : "Credits — plan, balance, top up"}
      >
        <Coins strokeWidth={1.6} aria-hidden />
        {balance.exempt ? (
          "Not charged"
        ) : (
          <>
            {num(left)}
            {/* the word goes on a phone; the number and the coin stay */}
            <span className="zcredit-word">{left === 1 ? "credit" : "credits"}</span>
          </>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="bottom" align="end" sideOffset={8} className="z-[800]">
          <Popover.Popup className="zcredit" aria-label="Credits">
            <div className="zcredit-head">
              <span className="m">{balance.plan ? balance.plan.name : balance.exempt ? "Operator" : "No plan"}</span>
              <strong className={empty ? "empty" : undefined}>
                {balance.exempt ? "Not charged" : num(Math.max(balance.available, 0))}
              </strong>
              {!balance.exempt ? <span className="u">credits available</span> : null}
            </div>
            <dl className="zcredit-rows">
              {balance.exempt ? (
                <div>
                  <dt>Renders on this account</dt>
                  <dd>take no hold</dd>
                </div>
              ) : null}
              {balance.outstanding > 0 ? (
                <div>
                  <dt>Held for renders in flight</dt>
                  <dd>{num(balance.outstanding)}</dd>
                </div>
              ) : null}
              {balance.plan ? (
                <div>
                  <dt>Plan allowance</dt>
                  <dd>{num(balance.plan.credits)} / month</dd>
                </div>
              ) : null}
              {expiry ? (
                <div>
                  <dt>Expiring soonest</dt>
                  <dd>
                    {num(expiry.credits)} on {expiry.on}
                  </dd>
                </div>
              ) : null}
              {release ? (
                <div>
                  <dt>Next monthly release</dt>
                  <dd>{day(release.next_release_at)}</dd>
                </div>
              ) : null}
            </dl>
            {empty ? (
              <p className="zcredit-note">At zero, approving a render in the Queue is refused — even with your own key on file.</p>
            ) : null}
            <div className="zcredit-actions">
              <Link href="/pricing" className="primary" onClick={() => setOpen(false)}>
                {balance.plan || balance.exempt ? "Buy credits" : "Choose a plan"}
              </Link>
              {balance.portal ? (
                <button type="button" onClick={manage} disabled={leaving}>
                  {leaving ? "Opening…" : "Manage billing"}
                </button>
              ) : null}
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

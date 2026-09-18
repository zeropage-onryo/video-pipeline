"use client";

import { useSearchParams } from "next/navigation";

// What Stripe sends people back to: /pricing?checkout=success|cancelled.
// One line, above the cards; nothing when the query is absent.
export function CheckoutNotice() {
  const state = useSearchParams().get("checkout");
  if (state !== "success" && state !== "cancelled") return null;
  const ok = state === "success";
  return (
    <p
      role="status"
      className={`mx-auto mt-8 max-w-[52ch] rounded-lg border px-4 py-3 text-sm ${
        ok ? "border-[#1f9d64]/40 bg-[#1f9d64]/10 text-foreground" : "border-border bg-card text-[#afafaf]"
      }`}
    >
      {ok
        ? "Payment received. Your credits land the moment Stripe confirms it, usually within a few seconds — open the studio to see your balance."
        : "Checkout cancelled. Nothing was charged."}
    </p>
  );
}

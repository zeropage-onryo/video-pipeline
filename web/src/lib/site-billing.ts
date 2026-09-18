"use client";

// The pricing page's one action: start a Stripe Checkout for a plan or
// the top-up. Same-origin through the proxy (lib/api.ts), so the cookie
// the sign-in handoff set on this origin rides along. Three answers:
//   - a URL: go there (Stripe)
//   - 401: not signed in -- sign in with `next` pointing back at
//     /pricing?checkout=<item>, and the page resumes the checkout
//   - 503: the install has no Stripe keys yet -- say so on the button
import { ApiError, AUTH_ORIGIN, apiFetch } from "@/lib/api";

export type CheckoutOutcome =
  | { kind: "redirect"; url: string }
  | { kind: "sign-in" }
  | { kind: "unconfigured"; message: string }
  | { kind: "error"; message: string };

export async function startCheckout(item: string): Promise<CheckoutOutcome> {
  try {
    const { url } = await apiFetch<{ url: string }>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ item }),
    });
    return { kind: "redirect", url };
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) return { kind: "sign-in" };
      if (e.status === 503) return { kind: "unconfigured", message: e.message };
      if (e.status >= 500) return { kind: "error", message: "The studio is unreachable right now — try again in a minute." };
      return { kind: "error", message: e.message };
    }
    return { kind: "error", message: "could not reach the studio" };
  }
}

export function signInThenCheckout(item: string) {
  if (typeof window === "undefined") return;
  const next = encodeURIComponent(`${window.location.origin}/pricing?checkout=${encodeURIComponent(item)}`);
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.href = `${AUTH_ORIGIN}/signin?next=${next}`;
}

export async function openPortal(): Promise<CheckoutOutcome> {
  try {
    const { url } = await apiFetch<{ url: string }>("/billing/portal", { method: "POST" });
    return { kind: "redirect", url };
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) return { kind: "sign-in" };
      if (e.status === 503) return { kind: "unconfigured", message: e.message };
      return { kind: "error", message: e.message };
    }
    return { kind: "error", message: "could not reach the studio" };
  }
}

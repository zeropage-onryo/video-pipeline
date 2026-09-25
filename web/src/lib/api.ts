// Uses the same-origin Next.js proxy to the existing FastAPI backend.
// NEXT_PUBLIC_API_URL optionally selects a direct API origin; that mode
// requires matching CORS and cookie configuration. Auth remains in FastAPI.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const API_BASE = `${API_URL}/api`;
// Where sign-in and sign-out NAVIGATE to: the API's own origin. Fetches
// stay same-origin through the proxy (API_URL empty) because the API's
// cookie is a third-party cookie to this site and Safari/Chrome will not
// send it; but OAuth has to run on the API's origin (its PKCE session,
// Supabase's redirect list), and it hands the session back to this origin
// through /auth/handoff, which the proxy forwards. Unset (local dev, one
// origin) this is simply API_URL.
export const AUTH_ORIGIN = process.env.NEXT_PUBLIC_AUTH_ORIGIN ?? API_URL;

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    },
    ...init,
  });

  if (!res.ok) {
    let message = res.statusText || `request failed (${res.status})`;
    try {
      const body = await res.clone().json();
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      // not JSON -- keep the fallback
    }
    throw new ApiError(message, res.status);
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

// `mode: "signup"` only changes the door's heading ("Create your account");
// logging in and signing up are the same form since 2026-09-24 -- the
// first pass through it makes the person's workspace (InVideo's shape).
export function goToSignIn(mode?: "signup") {
  if (typeof window !== "undefined") {
    // Full navigation on purpose -- this leaves the Next.js app entirely
    // for the API's own origin (a different domain in production), not
    // an internal route, so next/navigation's router isn't the tool here.
    // `next` asks the API to send the browser back here after sign-in;
    // the API honours it only for an origin in its FRONTEND_ORIGINS.
    const next = encodeURIComponent(`${window.location.origin}/studio`);
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    const which = mode === "signup" ? "&mode=signup" : "";
    window.location.href = `${AUTH_ORIGIN}/signin?next=${next}${which}`;
  }
}

export async function signOut() {
  // /logout lives at the API's root, not under /api -- apiFetch() is
  // scoped to API_BASE (.../api), so this calls it directly.
  // this origin's cookie first (through the proxy), then the API's own,
  // as a navigation -- a cross-site fetch could not carry that one
  await fetch(`${API_URL}/auth/logout`, {
    method: "POST",
    credentials: "include",
  }).catch(() => {});
  if (typeof window !== "undefined") {
    const next = encodeURIComponent(`${window.location.origin}/studio`);
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `${AUTH_ORIGIN}/auth/logout?next=${next}`;
  }
}

// A cheap authenticated call to prove a session exists. /api/capabilities
// is behind require_user_api like everything else under /api, and
// returns feature flags rather than identity -- there's no /api/me yet.
export async function checkSession(): Promise<boolean> {
  try {
    await apiFetch("/capabilities");
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return false;
    throw err;
  }
}

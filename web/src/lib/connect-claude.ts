/* "Connect to Claude" (2026-10-08, Mike: "I want to be able to access the
   MCP from the studio page at the bottom near profile").

   Nothing in the studio can connect anybody. A connector is added FROM
   claude.ai, which starts the OAuth flow; our consent page is where the
   person says yes. So the panel only makes that one step obvious, and
   everything it shows comes from /api/me: `mcp_url` is the server's own
   resource name (app/mcp_auth.connector_url), never a copy kept here.

   claude.ai has no documented deep link that pre-fills a custom
   connector's URL (checked 2026-10-08 against claude.com/docs: the
   "add a connector that isn't in the directory" page names only
   Customize > Connectors > Add custom connector), so the steps are copy
   and paste. A listed connector's page is permanent
   (`claude.ai/directory/connectors/<slug>`) and is the one button once
   the server sets ZEROPAGE_CLAUDE_DIRECTORY_URL. */

/** where a person adds or removes a connector on claude.ai */
export const CLAUDE_CONNECTORS_URL = "https://claude.ai/customize/connectors";

/** the name the steps suggest typing, so "remove it" names the same thing */
export const CONNECTOR_NAME = "Zero Page Studio";

export type ConnectPlan =
  /** the server takes no person's connection: say so, offer nothing */
  | { mode: "off" }
  /** not listed yet: the address to copy and the three steps */
  | { mode: "manual"; url: string }
  /** listed: one button to the listing, the address still there to copy */
  | { mode: "directory"; url: string; listing: string };

export function connectPlan(me: {
  mcp_url?: string | null;
  claude_directory_url?: string | null;
} | null): ConnectPlan {
  const url = me?.mcp_url || "";
  if (!url) return { mode: "off" };
  const listing = me?.claude_directory_url || "";
  return listing ? { mode: "directory", url, listing } : { mode: "manual", url };
}

export const MANUAL_STEPS = [
  "Open claude.ai, then Customize → Connectors → Add custom connector.",
  `Paste the address above and name it ${CONNECTOR_NAME}.`,
  "Press Connect and sign in with the same account you use for this studio.",
] as const;

/** "3 hours ago", "just now", "2 days ago" -- coarse on purpose: the use
 *  stamp is written at most once every ten minutes */
export function since(iso: string | null | undefined, now: number = Date.now()): string {
  const then = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(then)) return "";
  const minutes = Math.floor(Math.max(0, now - then) / 60_000);
  if (minutes < 10) return "just now";
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/** the panel's status line, or null when there is nothing to say */
export function connectedLine(
  status: { connected: boolean; approved_at: string | null; last_used_at: string | null; client_name: string | null } | null,
  now: number = Date.now(),
): string | null {
  if (!status?.connected) return null;
  const via = status.client_name ? ` through ${status.client_name}` : "";
  const used = since(status.last_used_at, now);
  if (used) return `Connected${via} · last used ${used}`;
  const allowed = since(status.approved_at, now);
  return allowed ? `Connected${via} · allowed ${allowed}, not used yet` : `Connected${via}`;
}

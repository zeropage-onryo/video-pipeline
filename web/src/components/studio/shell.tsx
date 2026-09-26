"use client";

/* The signed-in shell (2026-09-11): the rail, the bar, the account
   row — one component every studio page sits inside, so the product
   has one navigation instead of a rail per screen.

   The rail is the design's: Studio, Assets, Pipeline, Director,
   Elements, Queue. Analytics is gone in favour of Elements (Mike's
   call, 2026-09-11): the thing you @ in a prompt is a page, the charts
   were not. Every rail entry is a React page now (Assets, Pipeline
   and Queue landed 2026-09-12). */
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  AtSign,
  Clapperboard,
  ChevronsUpDown,
  House,
  Layers,
  ListVideo,
  LogOut,
  PanelLeft,
  Workflow,
} from "lucide-react";
import { API_URL, ApiError, goToSignIn, signOut } from "@/lib/api";
import {
  BALANCE_EVENT,
  getBalance,
  getMe,
  queueCount,
  queuePending,
  switchAccount,
  QUEUE_EVENT,
  type Balance,
  type Me,
} from "@/lib/studio-api";
import { CreditPill } from "@/components/studio/credit-pill";
/* eslint-disable @next/next/no-img-element */
import "@/app/studio/studio.css";

export type ViewId = "studio" | "assets" | "pipeline" | "director" | "elements" | "queue";

const NAV: { id: ViewId; label: string; href: string; icon: typeof House; external?: boolean }[] = [
  { id: "studio", label: "Studio", href: "/studio", icon: House },
  { id: "assets", label: "Assets", href: "/studio/assets", icon: Layers },
  { id: "pipeline", label: "Pipeline", href: "/studio/pipeline", icon: Workflow },
  { id: "director", label: "Director", href: "/studio/flows", icon: Clapperboard },
  { id: "elements", label: "Elements", href: "/studio/elements", icon: AtSign },
  { id: "queue", label: "Queue", href: "/studio/queue", icon: ListVideo },
];

const VIEW_BY_PATH: [string, ViewId][] = [
  ["/studio/flows", "director"],
  ["/studio/elements", "elements"],
  ["/studio/assets", "assets"],
  ["/studio/pipeline", "pipeline"],
  ["/studio/queue", "queue"],
  ["/studio", "studio"],
];

/* what the pages read from the shell: who, and a way to say something */
type ShellContext = {
  me: Me | null;
  /** /api/me answered 401: a visitor, not an account still loading */
  signedOut: boolean;
  brand: string;
  /** /api/billing/balance for the active account; null until it answers,
   *  and null for good when it cannot (signed out, no account, older API) */
  balance: Balance | null;
  toast: (text: string, kind?: "ok" | "err") => void;
  setBar: (node: ReactNode) => void;
};
const Ctx = createContext<ShellContext>({
  me: null,
  signedOut: false,
  brand: "",
  balance: null,
  toast: () => {},
  setBar: () => {},
});
export const useShell = () => useContext(Ctx);

const PIN_KEY = "zpf.rail.pinned";
const PIN_EVENT = "zpf:rail-pin";
/* the pin lives in localStorage; read through an external-store
   subscription so the server renders it collapsed and the client
   snaps to the saved state without a setState-in-effect */
const subscribePin = (cb: () => void) => {
  window.addEventListener(PIN_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(PIN_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
};
const readPin = () => {
  try {
    return localStorage.getItem(PIN_KEY) === "1";
  } catch {
    return false;
  }
};

export function StudioShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/studio";
  const view = VIEW_BY_PATH.find(([p]) => pathname.startsWith(p))?.[1] ?? "studio";
  const stage = view === "director";
  const [me, setMe] = useState<Me | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const pinned = useSyncExternalStore(subscribePin, readPin, () => false);
  const [menu, setMenu] = useState(false);
  const [pending, setPending] = useState(0);
  // keyed by the account it was read for, so a switch never shows the
  // previous account's number while the new one is being asked
  const [balanceRead, setBalanceRead] = useState<{ account: number; value: Balance | null } | null>(null);
  const [toastState, setToastState] = useState<{ text: string; kind: "ok" | "err" } | null>(null);
  const [bar, setBarNode] = useState<ReactNode>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadMe = useCallback(
    () =>
      getMe()
        .then(setMe)
        .catch((err) => {
          setMe(null);
          // a 401 is a visitor, not an outage: the account row becomes Sign in
          if (err instanceof ApiError && err.status === 401) setSignedOut(true);
        }),
    [],
  );
  useEffect(() => {
    loadMe();
  }, [loadMe]);
  const brand = me?.account?.slug ?? "";

  const refreshBadge = useCallback(() => {
    // the count route, not the listing: the listing prices every card and
    // the badge is on every page. An API from before the route existed
    // answers 404 (or 405), so the listing stays as the fallback.
    // branded, as the vanilla shell's badge is (shared.js sends ?brand=):
    // the badge counts the list the Queue page is about to draw
    queueCount(brand || undefined)
      .then((res) => setPending(res.spendable))
      .catch((err) => {
        if (!(err instanceof ApiError) || ![404, 405].includes(err.status)) return setPending(0);
        queuePending(brand || undefined)
          .then((res) => setPending(res.spendable ?? res.items.length))
          .catch(() => setPending(0));
      });
  }, [brand]);
  useEffect(() => {
    // not before /api/me has answered: an unbranded count would be asked,
    // drawn, and replaced a beat later
    if (!me) return;
    // Poll only while this tab is visible (2026-09-21): every background
    // tab polling once a minute was a steady drain on the database's
    // egress for a number nobody was looking at. Coming back to the tab
    // refreshes at once, so the badge is never stale when it is seen;
    // your own picks, decisions and finished jobs still fire QUEUE_EVENT.
    const visible = () => document.visibilityState === "visible";
    const tick = () => {
      if (visible()) refreshBadge();
    };
    const onVisibility = () => {
      if (visible()) refreshBadge();
    };
    refreshBadge();
    const timer = setInterval(tick, 60_000);
    window.addEventListener(QUEUE_EVENT, refreshBadge);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(timer);
      window.removeEventListener(QUEUE_EVENT, refreshBadge);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refreshBadge, me]);

  // THE BALANCE (2026-09-25). Re-read when the account changes, when
  // anything announces that credit moved (an approve takes a hold; the
  // Queue announces QUEUE_EVENT on its decisions and finished jobs, which
  // is when a hold settles), and when the tab comes back. No timer: a
  // balance only moves when this account spends or pays, and paying is a
  // round trip through Stripe that lands back on a fresh page load.
  const accountId = me?.account?.id ?? null;
  const refreshBalance = useCallback(() => {
    if (accountId === null) return;
    getBalance()
      .then((value) => setBalanceRead({ account: accountId, value }))
      // a failed read is "unknown", never "0": the pill hides rather than
      // telling a paying customer they have nothing
      .catch(() => setBalanceRead({ account: accountId, value: null }));
  }, [accountId]);
  const balance = balanceRead && balanceRead.account === accountId ? balanceRead.value : null;
  useEffect(() => {
    if (accountId === null) return;
    const onVisibility = () => {
      if (document.visibilityState === "visible") refreshBalance();
    };
    refreshBalance();
    window.addEventListener(BALANCE_EVENT, refreshBalance);
    window.addEventListener(QUEUE_EVENT, refreshBalance);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener(BALANCE_EVENT, refreshBalance);
      window.removeEventListener(QUEUE_EVENT, refreshBalance);
      document.removeEventListener("visibilitychange", onVisibility);
    };
    // keyed on the account id (through refreshBalance), not the object:
    // /api/me is re-read on a switch and hands back a new object for the
    // same account
  }, [accountId, refreshBalance]);

  const togglePin = () => {
    try {
      localStorage.setItem(PIN_KEY, pinned ? "0" : "1");
    } catch {
      /* private window: the pin just forgets */
    }
    window.dispatchEvent(new Event(PIN_EVENT));
  };

  const toast = useCallback((text: string, kind: "ok" | "err" = "ok") => {
    setToastState({ text, kind });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastState(null), kind === "err" ? 7000 : 4200);
  }, []);
  const setBar = useCallback((node: ReactNode) => setBarNode(node), []);

  // The switch is a cookie on THIS origin (the proxy forwards POST /brand),
  // and /api/me is what says it took: every page keys its fetches on the
  // `brand` this context hands out, so re-reading /api/me is what makes the
  // Queue, the board and the badge re-ask -- no reload (BACKLOG #19).
  const pickAccount = (slug: string) => {
    setMenu(false);
    if (slug === brand) return;
    switchAccount(slug)
      .then(loadMe)
      .catch(() => toast("Could not switch account", "err"));
  };

  const who = me?.user.display_name || me?.user.email || "—";
  const initials = who
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0] || "")
    .join("")
    .toUpperCase();

  return (
    <Ctx.Provider value={{ me, signedOut, brand, balance, toast, setBar }}>
      <div className="zps" data-view={view} data-stage={stage ? "1" : undefined}>
        <div className="zps-field" aria-hidden />

        <nav className={`rail${pinned ? " pinned" : ""}`} aria-label="Primary">
          <div className="rhead">
            <Link href="/studio" className="mark" title="Studio">
              ZP
            </Link>
            <span className="rl rtitle">Studio</span>
            <button
              type="button"
              className="rpin"
              onClick={togglePin}
              aria-pressed={pinned}
              title={pinned ? "Let the rail collapse" : "Keep the rail open"}
            >
              <PanelLeft size={14} strokeWidth={1.5} />
            </button>
          </div>
          <div className="rnav">
            {NAV.map(({ id, label, href, icon: Icon, external }) => {
              const current = id === view;
              const inner = (
                <>
                  <Icon strokeWidth={1.35} />
                  <span className="rl">{label}</span>
                  {id === "queue" && pending > 0 ? (
                    <span className="rbadge">{pending > 9 ? "9+" : pending}</span>
                  ) : null}
                </>
              );
              return external ? (
                <a key={id} href={`${API_URL}${href}`} aria-current={current ? "page" : undefined} title={label}>
                  {inner}
                </a>
              ) : (
                <Link key={id} href={href} aria-current={current ? "page" : undefined} title={label}>
                  {inner}
                </Link>
              );
            })}
          </div>
          <div className="rfoot">
            <span className="rl rkbd">
              <kbd>⌘K</kbd>
            </span>
            <button
              type="button"
              className="racct"
              onClick={() => (signedOut ? goToSignIn() : setMenu((v) => !v))}
              aria-expanded={menu}
              title={signedOut ? "Sign in" : `${who} · switch account`}
            >
              <span className="ravatar">
                {me?.user.avatar_url ? <img src={me.user.avatar_url} alt="" /> : initials || "ZP"}
              </span>
              <span className="rl rwho">
                <span className="rname">{signedOut ? "Sign in" : who}</span>
                <span className="rrole">
                  {signedOut
                    ? "Google, Discord or email"
                    : me?.account
                      ? `${me.account.label} · ${me.account.role || "member"}`
                      : "no account"}
                </span>
              </span>
              <ChevronsUpDown className="rl rchev" strokeWidth={1.6} />
              {menu && me ? (
                <span className="rmenu" role="menu" onClick={(e) => e.stopPropagation()}>
                  <span className="m">Accounts</span>
                  {me.accounts.map((a) => (
                    <button
                      key={a.id}
                      type="button"
                      aria-current={a.slug === brand ? "true" : undefined}
                      onClick={() => pickAccount(a.slug)}
                    >
                      {a.label}
                    </button>
                  ))}
                  <button type="button" onClick={signOut}>
                    <LogOut strokeWidth={1.6} /> Sign out
                  </button>
                </span>
              ) : null}
            </button>
          </div>
        </nav>

        <div className="shell">
          <div className="bar">
            <span className="brand">ZPF</span>
            <span className="sep">/</span>
            <span className="cur">{view}</span>
            {bar}
            <span className="spacer" />
            <CreditPill balance={balance} onError={(text) => toast(text, "err")} />
            <button
              type="button"
              className="tag"
              title={signedOut ? "Sign in" : "Switch account"}
              onClick={() => (signedOut ? goToSignIn() : setMenu((v) => !v))}
            >
              {signedOut ? "Sign in" : `${me?.account?.label ?? "—"} · switch`}
            </button>
          </div>
          {stage ? <div className="stage">{children}</div> : children}
        </div>

        {toastState ? (
          <div className={`ztoast${toastState.kind === "err" ? " err" : ""}`} role="status">
            {toastState.text}
          </div>
        ) : null}
      </div>
    </Ctx.Provider>
  );
}

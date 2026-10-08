"use client";

/* The signed-in shell (2026-09-11): the rail, the bar, the account
   row — one component every studio page sits inside, so the product
   has one navigation instead of a rail per screen.

   The rail (2026-10-07, Mike's call): Projects first, as the home, then
   Create, Assets, Edit, Elements and the Queue. Pipeline and Director are
   gone from it -- a concept is one scene and a project holds scenes, so
   the board of projects replaced the board of concepts, and the Director
   canvas lives inside each project's workspace (or, for a scene made
   outside any project, on /studio/scene/<id>). Their old URLs redirect.
   Analytics went in favour of Elements on 2026-09-11. */
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
  ChevronsUpDown,
  FolderKanban,
  House,
  Layers,
  ListVideo,
  LogOut,
  PanelLeft,
  Plug,
  Scissors,
  Search,
  Settings,
  X,
} from "lucide-react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
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
import { ConnectClaude } from "@/components/studio/connect-claude";
import { CommandPalette } from "@/components/studio/command-palette";
import { modKey, openPalette } from "@/lib/palette";
import { requestNewSession } from "@/lib/assistant";
/* eslint-disable @next/next/no-img-element */
import "@/app/studio/studio.css";

export type ViewId = "studio" | "projects" | "assets" | "cut" | "elements" | "queue" | "settings";

const NAV: { id: ViewId; label: string; href: string; icon: typeof House; external?: boolean }[] = [
  { id: "projects", label: "Projects", href: "/studio/projects", icon: FolderKanban },
  { id: "studio", label: "Create", href: "/studio", icon: House },
  { id: "assets", label: "Assets", href: "/studio/assets", icon: Layers },
  { id: "cut", label: "Edit", href: "/studio/cut", icon: Scissors },
  { id: "elements", label: "Elements", href: "/studio/elements", icon: AtSign },
  { id: "queue", label: "Queue", href: "/studio/queue", icon: ListVideo },
];

/* The header's three tabs (2026-10-02, the "ZPF Composer Directions"
   mock): Create is the box, Library the Assets wall, Timeline the editor.
   The rail still carries every page; these are the three the mock names. */
const TABS: { label: string; href: string; view: ViewId }[] = [
  { label: "Projects", href: "/studio/projects", view: "projects" },
  { label: "Create", href: "/studio", view: "studio" },
  { label: "Library", href: "/studio/assets", view: "assets" },
  { label: "Timeline", href: "/studio/cut", view: "cut" },
];

const VIEW_BY_PATH: [string, ViewId][] = [
  // settings is reached from the account menus, not the rail (2026-10-03):
  // its own view id so no rail entry lights up while it is open
  ["/studio/settings", "settings"],
  ["/studio/projects", "projects"],
  // a scene's canvas belongs to the Projects side of the studio
  ["/studio/scene", "projects"],
  ["/studio/cut", "cut"],
  ["/studio/elements", "elements"],
  ["/studio/assets", "assets"],
  ["/studio/queue", "queue"],
  ["/studio", "studio"],
];

/* A toast can carry ONE action (Undo, nearly always) and a deferred half.
   `onClose` runs once when the toast leaves WITHOUT its action pressed --
   it timed out, was dismissed, was pushed off the stack, or the page is
   being left -- so a change the server cannot take back (an element's
   delete is a hard DELETE) is held until then, and Undo simply cancels
   it. A change the server can reverse is made at once and its action
   calls the inverse route instead. */
export type ToastOpts = {
  action?: { label: string; run: () => unknown };
  onClose?: () => void;
};
type ToastItem = { id: number; text: string; kind: "ok" | "err"; action?: ToastOpts["action"] };

/** how long a toast stays: an error or an Undo gets longer to be read and
 *  answered; hovering one holds it */
const toastMs = (kind: "ok" | "err", action: boolean) => (kind === "err" || action ? 7000 : 4200);
/** the most toasts on screen at once; an older one is pushed off */
const TOAST_MAX = 4;

/* what the pages read from the shell: who, and a way to say something */
type ShellContext = {
  me: Me | null;
  /** /api/me answered 401: a visitor, not an account still loading */
  signedOut: boolean;
  brand: string;
  /** /api/billing/balance for the active account; null until it answers,
   *  and null for good when it cannot (signed out, no account, older API) */
  balance: Balance | null;
  toast: (text: string, kind?: "ok" | "err", opts?: ToastOpts) => void;
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
const subscribeNothing = () => () => {};
const readPin = () => {
  try {
    return localStorage.getItem(PIN_KEY) === "1";
  } catch {
    return false;
  }
};

/* The end of both account menus -- the rail's profile row and the header's
   avatar -- as ONE component, so the two menus cannot drift apart. */
function MenuTail({ close, onConnect }: { close: () => void; onConnect: () => void }) {
  return (
    <>
      <button
        type="button"
        role="menuitem"
        onClick={() => {
          close();
          onConnect();
        }}
      >
        <Plug strokeWidth={1.6} /> Connect to Claude
      </button>
      <Link href="/studio/settings" role="menuitem" onClick={close}>
        <Settings strokeWidth={1.6} /> Settings
      </Link>
      <button type="button" role="menuitem" onClick={signOut}>
        <LogOut strokeWidth={1.6} /> Sign out
      </button>
    </>
  );
}

export function StudioShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/studio";
  const view = VIEW_BY_PATH.find(([p]) => pathname.startsWith(p))?.[1] ?? "studio";
  // an open project (/studio/cut/<id>) is the editor: it takes the whole
  // stage and draws its own top bar, so the shell's bar steps aside
  const editor = /^\/studio\/cut\/[^/]+/.test(pathname);
  // a project's workspace and a scene's canvas fill the stage the way the
  // Director tab did: the canvas needs every pixel and scrolls itself
  const canvas = /^\/studio\/(projects\/\d+|scene\/[^/]+)/.test(pathname);
  const stage = canvas || editor;
  const [me, setMe] = useState<Me | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const pinned = useSyncExternalStore(subscribePin, readPin, () => false);
  const [menu, setMenu] = useState(false);
  // the header's avatar menu (accounts, sign out) -- its own flag, so the
  // rail's account row and the avatar never open each other's
  const [hmenu, setHmenu] = useState(false);
  // the Connect to Claude panel, opened from either menu
  const [connect, setConnect] = useState(false);
  const [pending, setPending] = useState(0);
  // keyed by the account it was read for, so a switch never shows the
  // previous account's number while the new one is being asked
  const [balanceRead, setBalanceRead] = useState<{ account: number; value: Balance | null } | null>(null);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [bar, setBarNode] = useState<ReactNode>(null);
  // per toast: its timer and its deferred half, outside React state so the
  // page-leave flush below can reach them synchronously
  const toastTimers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const toastClose = useRef(new Map<number, () => void>());
  const toastSeq = useRef(0);

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

  // the palette's modifier as this machine presses it (⌘ on a Mac, Ctrl
  // elsewhere); "⌘" on the server, so the first paint matches the old hint
  const mod = useSyncExternalStore(
    subscribeNothing,
    () => modKey(navigator.platform || navigator.userAgent),
    () => "⌘" as const,
  );

  const togglePin = () => {
    try {
      localStorage.setItem(PIN_KEY, pinned ? "0" : "1");
    } catch {
      /* private window: the pin just forgets */
    }
    window.dispatchEvent(new Event(PIN_EVENT));
  };

  useEffect(() => {
    if (!hmenu) return;
    const off = (e: MouseEvent) => {
      if (!(e.target as Element | null)?.closest?.(".havatar-wrap")) setHmenu(false);
    };
    document.addEventListener("pointerdown", off);
    return () => document.removeEventListener("pointerdown", off);
  }, [hmenu]);

  /* THE TOAST STACK (2026-10-08). It was one slot that overwrote itself, so
     two things said in a row lost the first, and a destructive action had
     no way back. Now: up to TOAST_MAX, newest on top, each on its own
     timer (held while hovered), each dismissible, and an Undo where the
     caller gives one. `acted` says the action was pressed, which is the one
     way to leave WITHOUT running the deferred half. */
  const dropToast = useCallback((id: number, acted: boolean) => {
    const timer = toastTimers.current.get(id);
    if (timer) clearTimeout(timer);
    toastTimers.current.delete(id);
    const close = toastClose.current.get(id);
    toastClose.current.delete(id);
    setToasts((all) => all.filter((t) => t.id !== id));
    if (!acted && close) close();
  }, []);
  const armToast = useCallback(
    (id: number, ms: number) => {
      const old = toastTimers.current.get(id);
      if (old) clearTimeout(old);
      toastTimers.current.set(
        id,
        setTimeout(() => dropToast(id, false), ms),
      );
    },
    [dropToast],
  );
  const holdToast = useCallback((id: number) => {
    const timer = toastTimers.current.get(id);
    if (timer) clearTimeout(timer);
    toastTimers.current.delete(id);
  }, []);
  // what is on screen, oldest first, readable synchronously by toast()
  const toastList = useRef<ToastItem[]>([]);
  useEffect(() => {
    toastList.current = toasts;
  }, [toasts]);
  const toast = useCallback(
    (text: string, kind: "ok" | "err" = "ok", opts?: ToastOpts) => {
      const newest = toastList.current[toastList.current.length - 1];
      // the same plain message again (a retried error, a double click) is
      // the same toast held longer, not a second copy of it
      if (newest && !opts && !newest.action && newest.text === text && newest.kind === kind) {
        armToast(newest.id, toastMs(kind, false));
        return;
      }
      const id = ++toastSeq.current;
      if (opts?.onClose) toastClose.current.set(id, opts.onClose);
      const item: ToastItem = { id, text, kind, action: opts?.action };
      toastList.current = [...toastList.current, item];
      setToasts((all) => [...all, item]);
      armToast(id, toastMs(kind, !!opts?.action));
      // past the cap the oldest goes -- and its deferred half runs, since
      // nobody undid it
      while (toastList.current.length > TOAST_MAX) {
        const oldest = toastList.current[0];
        toastList.current = toastList.current.slice(1);
        dropToast(oldest.id, false);
      }
    },
    [armToast, dropToast],
  );
  // Leaving the page runs every deferred half still waiting: the change
  // was asked for and never undone. (Moving between studio pages does not
  // leave it -- the shell, and so the stack, stays mounted.)
  useEffect(() => {
    const closers = toastClose.current;
    const flush = () => {
      for (const close of closers.values()) {
        try {
          close();
        } catch {
          /* a failed deferred half has nobody left to tell */
        }
      }
      closers.clear();
    };
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, []);
  const actOnToast = (t: ToastItem) => {
    dropToast(t.id, true);
    Promise.resolve()
      .then(() => t.action?.run())
      .catch((e) => toast(e instanceof Error ? e.message : "That could not be undone", "err"));
  };
  const setBar = useCallback((node: ReactNode) => setBarNode(node), []);

  // The switch is a cookie on THIS origin (the proxy forwards POST /brand),
  // and /api/me is what says it took: every page keys its fetches on the
  // `brand` this context hands out, so re-reading /api/me is what makes the
  // Queue, the board and the badge re-ask -- no reload (BACKLOG #19).
  const pickAccount = (slug: string) => {
    setMenu(false);
    setHmenu(false);
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
      <div
        className="zps"
        data-view={view}
        data-stage={stage ? "1" : undefined}
        data-editor={editor ? "1" : undefined}
        data-canvas={canvas ? "1" : undefined}
      >
        <div className="zps-field" aria-hidden />

        <nav className={`rail${pinned ? " pinned" : ""}`} aria-label="Primary">
          <div className="rhead">
            <Link href="/studio/projects" className="mark" title="Projects">
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
            {/* the hint that had nothing behind it until 2026-10-08: it opens
                the palette (command-palette.tsx), as ⌘K / Ctrl+K does */}
            <button type="button" className="rl rkbd" onClick={() => openPalette()} title="Search and commands">
              <span>Search</span>
              <kbd>{mod === "⌘" ? "⌘K" : "Ctrl K"}</kbd>
            </button>
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
                  <MenuTail close={() => setMenu(false)} onConnect={() => setConnect(true)} />
                </span>
              ) : null}
            </button>
          </div>
        </nav>

        <div className="shell">
          {/* THE HEADER (2026-10-02, the composer mock): the brand with its
              red dot, Create / Library / Timeline in the middle, and on the
              right the balance, New session and the account's avatar. Every
              piece is wired: the tabs are pages, New session archives the
              open conversation (lib/assistant.ts requestNewSession, taken by
              AssistantThreadProvider), the avatar opens the account menu. */}
          <header className="bar hdr">
            <Link href="/studio/projects" className="hbrand" title="Projects">
              <span className="hdot" aria-hidden />
              <b>Zero Page Studio</b>
            </Link>
            <nav className="htabs" aria-label="Studio">
              {TABS.map((t) => (
                <Link
                  key={t.href}
                  href={t.href}
                  aria-current={view === t.view ? "page" : undefined}
                  className={t.view === "cut" ? "htab-cut" : undefined}
                >
                  {t.label}
                </Link>
              ))}
            </nav>
            {/* the right-hand cluster is one grid cell, so the tabs between
                it and the brand can never be drawn underneath it */}
            <span className="hright">
              {bar}
              {!signedOut && me?.account ? (
                <button
                  type="button"
                  className="hsearch"
                  onClick={() => openPalette()}
                  aria-label="Search and commands"
                  title={`Search and commands · ${mod === "⌘" ? "⌘K" : "Ctrl+K"}`}
                >
                  <Search size={15} strokeWidth={1.7} />
                </button>
              ) : null}
              <CreditPill balance={balance} onError={(text) => toast(text, "err")} />
              {!signedOut && me?.account ? (
                <button
                  type="button"
                  className="hnew"
                  title="Start a new session -- this one is kept"
                  onClick={() => {
                    requestNewSession();
                    toast("New session · the last one is kept");
                  }}
                >
                  New session
                </button>
              ) : null}
              <span className="havatar-wrap">
                <button
                  type="button"
                  className="havatar"
                  aria-haspopup="menu"
                  aria-expanded={hmenu}
                  title={signedOut ? "Sign in" : `${who} · account`}
                  onClick={() => (signedOut ? goToSignIn() : setHmenu((v) => !v))}
                >
                  {me?.user.avatar_url ? <img src={me.user.avatar_url} alt="" /> : initials.slice(0, 1) || "ZP"}
                </button>
                {hmenu && me ? (
                  <span className="rmenu hmenu" role="menu">
                    <span className="m">{who}</span>
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
                    <MenuTail close={() => setHmenu(false)} onConnect={() => setConnect(true)} />
                  </span>
                ) : null}
              </span>
            </span>
          </header>
          {stage ? <div className="stage">{children}</div> : children}
        </div>

        {connect ? <ConnectClaude me={me} onClose={() => setConnect(false)} toast={toast} /> : null}
        <CommandPalette
          me={me}
          brand={brand}
          signedOut={signedOut}
          toast={toast}
          pinned={pinned}
          onTogglePin={togglePin}
          onSwitchAccount={pickAccount}
        />

        <MotionConfig reducedMotion="user">
          <div className="ztoasts">
            <AnimatePresence initial={false}>
              {toasts.map((t) => (
                <motion.div
                  key={t.id}
                  layout
                  initial={{ opacity: 0, y: -12, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.98, transition: { duration: 0.14 } }}
                  transition={{ duration: 0.22, ease: [0.22, 0.61, 0.36, 1] }}
                  className={`ztoast${t.kind === "err" ? " err" : ""}`}
                  role={t.kind === "err" ? "alert" : "status"}
                  onMouseEnter={() => holdToast(t.id)}
                  onMouseLeave={() => armToast(t.id, 2500)}
                  onFocus={() => holdToast(t.id)}
                  onBlur={() => armToast(t.id, 2500)}
                >
                  <span className="ztext">{t.text}</span>
                  {t.action ? (
                    <button type="button" className="zact" onClick={() => actOnToast(t)}>
                      {t.action.label}
                    </button>
                  ) : null}
                  <button type="button" className="zx" aria-label="Dismiss" onClick={() => dropToast(t.id, false)}>
                    <X size={12} strokeWidth={2} />
                  </button>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </MotionConfig>
      </div>
    </Ctx.Provider>
  );
}

"use client";

/* THE ⌘K PALETTE (2026-10-08, the front-end gap list vs LTX Studio and
   invideo, items 1 and 2). The rail had printed "⌘K" since 2026-09-11 with
   nothing behind it, and search lived per page -- the Queue and Elements had
   none. Now one box, from every studio page:

   - typed words search everything this account made, on the server
     (GET /api/search, src/search.py): projects, scenes by title AND prompt,
     elements, renders by prompt, cuts -- and the palette's own commands,
     ranked by the same every-word rule (lib/palette.ts)
   - nothing typed shows the recent projects and scenes, then the pages and
     the actions
   - ↑ ↓ move, ↵ opens, esc closes; ⌘K (Ctrl+K) toggles from anywhere

   NOTHING HERE SPENDS. "Draw keyframes" opens the Queue, where each card's
   priced button is; "New project" and "Find references" open Create with the
   Guide asked, because a project is only ever made through the Guide
   (guide_tools.PROJECT_TOOLS) and references are its find_references tool.
   A new cut is a scratch project, which costs nothing. */
/* eslint-disable @next/next/no-img-element */
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import { useRouter } from "next/navigation";
import { Dialog } from "@base-ui/react/dialog";
import {
  AtSign,
  Clapperboard,
  CornerDownLeft,
  CreditCard,
  FolderKanban,
  House,
  Image as ImageIcon,
  ImagePlus,
  Layers,
  ListVideo,
  Loader2,
  LogOut,
  MessageSquarePlus,
  PanelLeft,
  Plus,
  RectangleHorizontal,
  RectangleVertical,
  Scissors,
  Search,
  Settings,
  Sparkles,
  Square,
  Users,
} from "lucide-react";
import { signOut } from "@/lib/api";
import { createProject as createCut } from "@/lib/cut/api";
import { handleOf, kindLabel } from "@/lib/elements";
import { requestNewSession } from "@/lib/assistant";
import { PALETTE_EVENT, isPaletteKey, marks, rankCommands, step } from "@/lib/palette";
import { globalSearch, sceneHref, workspaceHref, type Me, type SearchResult } from "@/lib/studio-api";

type Icon = ComponentType<{ size?: number; strokeWidth?: number }>;
type Row = {
  key: string;
  title: string;
  sub?: string;
  icon?: Icon;
  thumb?: string | null;
  badge?: string;
  /** what the row does, said on the right when it is the active one */
  verb: string;
  run: () => void | Promise<void>;
};
type Command = Row & { keywords?: string };
type Group = { label: string; rows: Row[] };

const SEARCH_DELAY = 120;

/* Mounted by the shell, which hands it what it knows (who, which account,
   the toast) as props -- not through useShell, which would make the two
   modules import each other. */
export function CommandPalette({
  me,
  brand,
  signedOut,
  toast,
  pinned,
  onTogglePin,
  onSwitchAccount,
}: {
  me: Me | null;
  brand: string;
  signedOut: boolean;
  toast: (text: string, kind?: "ok" | "err") => void;
  pinned: boolean;
  onTogglePin: () => void;
  onSwitchAccount: (slug: string) => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // keyed by the query it answers, so a slow reply to an older query is
  // never drawn under a newer one
  const [found, setFound] = useState<{ q: string; result: SearchResult } | null>(null);
  const [searching, setSearching] = useState(false);
  const [failed, setFailed] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  // ⌘K / Ctrl+K from anywhere, and the event any button fires
  useEffect(() => {
    if (signedOut) return;
    const onKey = (e: KeyboardEvent) => {
      if (!isPaletteKey(e)) return;
      e.preventDefault();
      setOpen((o) => !o);
    };
    const onOpen = (e: Event) => {
      const q = (e as CustomEvent<{ query?: string }>).detail?.query ?? "";
      setQuery(q);
      setOpen(true);
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener(PALETTE_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener(PALETTE_EVENT, onOpen);
    };
  }, [signedOut]);

  // the server's search, a beat after the typing stops
  const q = query.trim();
  useEffect(() => {
    if (!open || !me?.account) return;
    const controller = new AbortController();
    const timer = setTimeout(
      () => {
        setSearching(true);
        globalSearch(q, { signal: controller.signal })
          .then((result) => {
            setFound({ q, result });
            setFailed("");
          })
          .catch((e) => {
            if (controller.signal.aborted) return;
            setFailed(e instanceof Error ? e.message : "Search is unavailable");
          })
          .finally(() => {
            if (!controller.signal.aborted) setSearching(false);
          });
      },
      q ? SEARCH_DELAY : 0,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // brand: an account switch re-asks; the account id is what /api scopes on
  }, [open, q, me?.account, brand]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setActive(0);
  }, []);
  const go = useCallback(
    (href: string) => {
      close();
      router.push(href);
    },
    [close, router],
  );

  // the palette's own commands: pages, then actions
  const commands = useMemo<{ pages: Command[]; actions: Command[] }>(() => {
    const page = (title: string, href: string, icon: Icon, keywords = ""): Command => ({
      key: `page:${href}`,
      title,
      icon,
      keywords,
      verb: "Go",
      run: () => go(href),
    });
    const newCut = (aspect: "9:16" | "16:9" | "1:1", icon: Icon): Command => ({
      key: `cut:${aspect}`,
      title: `New cut · ${aspect}`,
      sub: "A blank timeline in the editor",
      icon,
      keywords: "edit timeline video editor scratch blank",
      verb: "Create",
      run: async () => {
        close();
        try {
          const res = await createCut({ aspect });
          router.push(`/studio/cut/${encodeURIComponent(res.project.id)}`);
        } catch (e) {
          toast(e instanceof Error ? e.message : "Could not start a cut", "err");
        }
      },
    });
    const others = (me?.accounts ?? []).filter((a) => a.slug !== brand);
    return {
      pages: [
        page("Projects", "/studio/projects", FolderKanban, "home board workspace"),
        page("Create", "/studio", House, "composer write scene image video guide"),
        page("Assets", "/studio/assets", Layers, "library wall renders images clips"),
        page("Edit", "/studio/cut", Scissors, "timeline editor cuts"),
        page("Elements", "/studio/elements", AtSign, "characters props products places cast"),
        page("Queue", "/studio/queue", ListVideo, "approve render spend credits"),
        page("Settings", "/studio/settings", Settings, "account password email profile"),
      ],
      actions: [
        {
          key: "act:new-project",
          title: "New project",
          sub: "The Guide sets it up on Create",
          icon: MessageSquarePlus,
          keywords: "start brief client ad short",
          verb: "Ask the Guide",
          run: () => go(`/studio?spark=${encodeURIComponent("Start a new project: ")}`),
        },
        {
          key: "act:find-references",
          title: "Find references",
          sub: "The Guide searches images for an idea",
          icon: ImagePlus,
          keywords: "images photos look mood moodboard search web",
          verb: "Ask the Guide",
          run: () => go(`/studio?spark=${encodeURIComponent("Find reference images for ")}`),
        },
        {
          key: "act:keyframes",
          title: "Draw keyframes",
          sub: "On the Queue, beside each scene's price",
          icon: Sparkles,
          keywords: "stills frames queue",
          verb: "Open the Queue",
          run: () => go("/studio/queue"),
        },
        {
          key: "act:new-element",
          title: "New element",
          sub: "A character, prop, product or place",
          icon: Plus,
          keywords: "add character prop product place photos",
          verb: "Create",
          run: () => go("/studio/elements?new=1"),
        },
        newCut("9:16", RectangleVertical),
        newCut("16:9", RectangleHorizontal),
        newCut("1:1", Square),
        {
          key: "act:new-session",
          title: "New session",
          sub: "Start the Guide fresh; the last one is kept",
          icon: Plus,
          keywords: "guide conversation chat clear",
          verb: "Start",
          run: () => {
            close();
            requestNewSession();
            toast("New session · the last one is kept");
          },
        },
        ...others.map<Command>((a) => ({
          key: `act:switch:${a.slug}`,
          title: `Switch to ${a.label}`,
          icon: Users,
          keywords: "account workspace brand",
          verb: "Switch",
          run: () => {
            close();
            onSwitchAccount(a.slug);
          },
        })),
        {
          key: "act:pin",
          title: pinned ? "Let the rail collapse" : "Keep the rail open",
          icon: PanelLeft,
          keywords: "sidebar navigation pin",
          verb: pinned ? "Collapse" : "Pin",
          run: () => {
            close();
            onTogglePin();
          },
        },
        {
          key: "act:credits",
          title: "Buy credits",
          icon: CreditCard,
          keywords: "billing plan top up balance pricing",
          verb: "Open",
          run: () => go("/pricing"),
        },
        {
          key: "act:sign-out",
          title: "Sign out",
          icon: LogOut,
          keywords: "log out leave",
          verb: "Sign out",
          run: () => {
            close();
            void signOut();
          },
        },
      ],
    };
  }, [me?.accounts, brand, pinned, go, close, router, toast, onSwitchAccount, onTogglePin]);

  // what is drawn: the server's groups for THIS query, plus the commands
  const groups = useMemo<Group[]>(() => {
    const result = found && found.q === q ? found.result : null;
    const g = result?.groups;
    const out: Group[] = [];
    const projects: Row[] = (g?.projects ?? []).map((p) => ({
      key: `project:${p.id}`,
      title: p.title,
      sub: p.sub || undefined,
      thumb: p.thumb,
      icon: FolderKanban,
      badge: p.archived ? "archived" : undefined,
      verb: "Open",
      run: () => go(`/studio/projects/${p.id}`),
    }));
    const scenes: Row[] = (g?.scenes ?? []).map((s) => ({
      key: `scene:${s.id}`,
      title: s.title,
      sub: [s.project_title || "no project", s.sub].filter(Boolean).join(" · "),
      thumb: s.thumb,
      icon: Clapperboard,
      badge: s.archived ? "passed" : s.rendered ? "rendered" : s.picked ? "picked" : undefined,
      verb: "Open",
      run: () => go(s.project_id ? workspaceHref(s.project_id, s.id) : sceneHref(s.id)),
    }));
    if (!q) {
      if (projects.length) out.push({ label: "Recent projects", rows: projects });
      if (scenes.length) out.push({ label: "Recent scenes", rows: scenes });
      out.push({ label: "Go to", rows: commands.pages });
      out.push({ label: "Actions", rows: commands.actions });
      return out;
    }
    const pages = rankCommands(commands.pages, q, 4);
    const actions = rankCommands(commands.actions, q, 8);
    if (pages.length) out.push({ label: "Go to", rows: pages });
    if (actions.length) out.push({ label: "Actions", rows: actions });
    if (projects.length) out.push({ label: "Projects", rows: projects });
    if (scenes.length) out.push({ label: "Scenes", rows: scenes });
    const elements: Row[] = (g?.elements ?? []).map((e) => ({
      key: `element:${e.id}`,
      title: e.name,
      sub: [kindLabel(e.kind), handleOf(e.name), e.frames ? `${e.frames} frame${e.frames === 1 ? "" : "s"}` : "", e.sub]
        .filter(Boolean)
        .join(" · "),
      thumb: e.thumb,
      icon: AtSign,
      verb: "Open",
      run: () => go(`/studio/elements?open=${encodeURIComponent(e.id)}`),
    }));
    if (elements.length) out.push({ label: "Elements", rows: elements });
    const renders: Row[] = (g?.renders ?? []).map((r) => ({
      key: `render:${r.id}`,
      title: r.label,
      sub: r.sub,
      thumb: r.thumb,
      icon: r.kind === "video" ? Clapperboard : ImageIcon,
      badge: r.kind === "video" ? "clip" : "still",
      verb: "Open",
      run: () => go(`/studio/assets?open=${r.id}`),
    }));
    if (renders.length) out.push({ label: "Renders", rows: renders });
    const cuts: Row[] = (g?.cuts ?? []).map((c) => ({
      key: `cut:${c.id}`,
      title: c.title,
      sub: "Cut",
      icon: Scissors,
      verb: "Open",
      run: () => go(`/studio/cut/${encodeURIComponent(c.id)}`),
    }));
    if (cuts.length) out.push({ label: "Cuts", rows: cuts });
    return out;
  }, [found, q, commands, go]);

  const rows = useMemo(() => groups.flatMap((g) => g.rows), [groups]);
  const current = active >= 0 && active < rows.length ? active : rows.length ? 0 : -1;

  // the active row stays in view as the arrows move it
  useEffect(() => {
    if (current < 0) return;
    listRef.current?.querySelector(`[data-index="${current}"]`)?.scrollIntoView({ block: "nearest" });
  }, [current]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive(step(current, e.key === "ArrowDown" ? 1 : -1, rows.length));
    } else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      const row = rows[current];
      if (row) void row.run();
    } else if (e.key === "Home" && rows.length) {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End" && rows.length) {
      e.preventDefault();
      setActive(rows.length - 1);
    }
  };

  const pending = searching || (!!q && (!found || found.q !== q));
  const empty = !!q && !pending && !failed && rows.length === 0;
  let index = -1;

  return (
    <Dialog.Root open={open} onOpenChange={(o) => (o ? setOpen(true) : close())}>
      <Dialog.Portal>
        <Dialog.Backdrop className="zpk-backdrop" />
        <Dialog.Popup className="zpk" aria-label="Search and commands">
          <Dialog.Title className="zpk-sr">Search and commands</Dialog.Title>
          <div className="zpk-input">
            {pending ? <Loader2 size={17} className="zpk-spin" /> : <Search size={17} strokeWidth={1.7} />}
            <input
              autoFocus
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="Search projects, scenes, prompts, elements…"
              role="combobox"
              aria-expanded
              aria-controls="zpk-list"
              aria-activedescendant={current >= 0 ? `zpk-row-${current}` : undefined}
              aria-autocomplete="list"
              spellCheck={false}
              autoComplete="off"
            />
            <kbd>esc</kbd>
          </div>
          <div className="zpk-list" id="zpk-list" role="listbox" ref={listRef} aria-label="Results">
            {failed ? <p className="zpk-state err">{failed}</p> : null}
            {empty ? (
              <p className="zpk-state">
                Nothing matches “{q}”. Every word has to match somewhere: a title, a prompt, a note or a brief.
              </p>
            ) : null}
            {groups.map((group) => (
              <div key={group.label} role="group" aria-label={group.label}>
                <p className="zpk-group">{group.label}</p>
                {group.rows.map((row) => {
                  index += 1;
                  const i = index;
                  const Icon = row.icon;
                  return (
                    <div
                      key={row.key}
                      id={`zpk-row-${i}`}
                      data-index={i}
                      role="option"
                      aria-selected={i === current}
                      className="zpk-row"
                      onMouseMove={() => i !== current && setActive(i)}
                      onClick={() => void row.run()}
                    >
                      <span className="zpk-lead" aria-hidden>
                        {row.thumb ? <img src={row.thumb} alt="" loading="lazy" /> : Icon ? <Icon size={16} strokeWidth={1.6} /> : null}
                      </span>
                      <span className="zpk-text">
                        <span className="zpk-title">
                          {marks(row.title, q).map((m, k) => (m.hit ? <b key={k}>{m.text}</b> : <span key={k}>{m.text}</span>))}
                        </span>
                        {row.sub ? (
                          <span className="zpk-sub">
                            {marks(row.sub, q).map((m, k) => (m.hit ? <b key={k}>{m.text}</b> : <span key={k}>{m.text}</span>))}
                          </span>
                        ) : null}
                      </span>
                      {row.badge ? <span className="zpk-badge">{row.badge}</span> : null}
                      <span className="zpk-verb" aria-hidden>
                        {row.verb} <CornerDownLeft size={12} strokeWidth={1.8} />
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          <div className="zpk-foot" aria-hidden>
            <span>
              <kbd>↑</kbd>
              <kbd>↓</kbd> move
            </span>
            <span>
              <kbd>↵</kbd> open
            </span>
            <span>
              <kbd>esc</kbd> close
            </span>
            <span className="zpk-note">Nothing here spends credits</span>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

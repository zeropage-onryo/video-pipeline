"use client";

/* ONE conversation for the whole studio (2026-10-02).

   The assistant pill and the Studio composer's Guide each kept their own
   thread, and the composer's lived only in its page's React state, so
   clicking from Studio to Pipeline threw away the conversation and every
   frame a hunt had drawn under it. This provider sits in studio/layout.tsx
   above both: one `turns` list, one step, and the composer's DRAFT (the
   idea in the box, the brief, the references, the mode, the "scene
   written" card), loaded once per account and saved on every change --
   to sessionStorage at once (the offline, same-tab fallback) and to the
   server debounced (src/assistant_store.py's open project, so another
   browser picks it up too).

   The load is the pill's rule, kept: the browser's copy paints first, the
   server's copy then wins. A draft typed before the server answered is
   kept only when the server had none, and is pushed up by the save that
   follows.

   A CONVERSATION IS WORKING MEMORY (2026-10-02, Mike's call): it is saved
   only so the person can pick it up where they left off. Once the scene is
   CREATED it goes away (`finishProject`: the turns, the brief, the box and
   its references are cleared, and only the "scene written" card remains
   until "Write another"); the pill's button clears it the same way
   (`clearProject`). Nothing is ever archived -- the server DELETES the row.
   What the talk produced lives on the concept and, once rendered, on the
   asset with its prompt. Nothing here calls a model or spends.

   INSIDE A PROJECT IT IS THE PROJECT'S (2026-10-07, Mike's call). On a
   project's workspace (/studio/projects/<id>) the thread this provider
   hands out is that project's chat history instead: loaded from
   GET /projects/<id>/messages (the newest page, `loadOlder` for the rest),
   written by the server as each turn happens (the pill sends remember=1),
   and kept until the project is deleted -- never cleared from here. The
   studio-wide thread above is untouched while a project is open, and is
   back the moment the person leaves it. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { usePathname } from "next/navigation";
import { useShell } from "@/components/studio/shell";
import { projectMessages, type GuideReply, type ProjectMessage } from "@/lib/studio-api";
import {
  EMPTY_DRAFT,
  NEW_SESSION_EVENT,
  asDraft,
  draftHasContent,
  getAssistantMemory,
  isStage,
  putProject,
  clearProject as clearProjectOnServer,
  type ComposerDraft,
  type Stage,
  type Turn,
} from "@/lib/assistant";

type DraftUpdate = Partial<ComposerDraft> | ((d: ComposerDraft) => ComposerDraft);

export type AssistantThread = {
  /** the account slug the thread belongs to ("" while signed out) */
  account: string;
  /** the server has answered for this account: saves are allowed, params may apply */
  ready: boolean;
  turns: Turn[];
  setTurns: Dispatch<SetStateAction<Turn[]>>;
  stage: Stage | "";
  setStage: (s: Stage | "") => void;
  draft: ComposerDraft;
  setDraft: (update: DraftUpdate) => void;
  /** delete the conversation on the server and start empty */
  clearProject: () => Promise<void>;
  /** the scene was created: the conversation is done, only its card remains */
  finishProject: (written: ComposerDraft["written"]) => void;
  /** set on a project's workspace: `turns` are that project's saved history */
  projectId: number | null;
  /** the project's history has turns older than the ones loaded */
  hasOlder: boolean;
  loadOlder: () => Promise<void>;
};

const Ctx = createContext<AssistantThread>({
  account: "",
  ready: false,
  turns: [],
  setTurns: () => {},
  stage: "",
  setStage: () => {},
  draft: EMPTY_DRAFT,
  setDraft: () => {},
  clearProject: async () => {},
  finishProject: () => {},
  projectId: null,
  hasOlder: false,
  loadOlder: async () => {},
});
export const useAssistantThread = () => useContext(Ctx);

const THREAD_KEY = "zpf.assistant.thread";
const MIRRORED_TURNS = 24;
const SAVE_DEBOUNCE_MS = 700;

type Local = { turns: Turn[]; stage: Stage | ""; draft: ComposerDraft };
const EMPTY: Local = { turns: [], stage: "", draft: EMPTY_DRAFT };

function loadLocal(account: string): Local {
  try {
    const raw = sessionStorage.getItem(`${THREAD_KEY}.${account}`);
    if (raw) {
      const t = JSON.parse(raw) as { turns?: Turn[]; stage?: string; draft?: unknown };
      return {
        turns: Array.isArray(t.turns) ? t.turns : [],
        stage: isStage(t.stage) ? t.stage : "",
        draft: asDraft(t.draft),
      };
    }
  } catch {
    /* a fresh start */
  }
  return EMPTY;
}

const snapshot = (turns: Turn[], stage: string, draft: ComposerDraft) =>
  JSON.stringify({ turns: turns.filter((t) => !t.failed), stage, draft });

/* One saved turn of a project's history, as a thread turn. A proposal is
   not restored: whether it was confirmed is not in the history, and a card
   drawn again could bank the same thing twice -- its words still say what
   was offered. */
function fromMessage(m: ProjectMessage): Turn & { messageId: number } {
  if (m.role === "user") return { role: "user", content: m.content, messageId: m.id };
  const extras = { ...(m.tool_calls || {}) } as Partial<GuideReply>;
  delete extras.proposal;
  return { role: "assistant", content: m.content, reply: { ...extras, message: m.content }, messageId: m.id };
}
const PROJECT_PATH = /^\/studio\/projects\/(\d+)/;

export function AssistantThreadProvider({ children }: { children: ReactNode }) {
  const { me, brand } = useShell();
  const account = brand || me?.account?.slug || "";
  const pathname = usePathname() || "";
  const projectId = Number(PROJECT_PATH.exec(pathname)?.[1]) || null;
  // the open project's history: keyed by the project it was read for, so
  // moving between two projects never shows the first one's talk
  const [projectThread, setProjectThread] = useState<{
    id: number;
    turns: (Turn & { messageId?: number })[];
    stage: Stage | "";
    hasOlder: boolean;
  } | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [stage, setStage] = useState<Stage | "">("");
  const [draft, setDraftState] = useState<ComposerDraft>(EMPTY_DRAFT);
  // whose thread the state is: saving must never write one account's
  // thread under another's key in the render between a switch and its load
  const [loadedFor, setLoadedFor] = useState("");
  // what the server last had (as loaded or as saved), so a load does not
  // save itself back and an unchanged tick sends nothing
  const saved = useRef("");

  useEffect(() => {
    if (!account) return;
    let live = true;
    const local = loadLocal(account);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sessionStorage is only readable after mount
    setTurns(local.turns);
    setStage(local.stage);
    setDraftState(local.draft);
    setLoadedFor("");
    getAssistantMemory()
      .then((m) => {
        if (!live) return;
        if (m.project) {
          const serverTurns = (m.project.turns as Turn[]) || [];
          const serverStage = isStage(m.project.stage) ? m.project.stage : "";
          const serverDraft = asDraft(m.project.draft);
          // the server's copy wins; a box typed into before it answered
          // survives only when the server had nothing in its own
          const useDraft = draftHasContent(serverDraft) || !draftHasContent(local.draft) ? serverDraft : local.draft;
          setTurns(serverTurns);
          setStage(serverStage);
          setDraftState(useDraft);
          saved.current = snapshot(serverTurns, serverStage, serverDraft);
        } else {
          // nothing remembered: whatever this browser has is pushed up by
          // the save effect, since it differs from the (empty) server copy
          saved.current = snapshot([], "", EMPTY_DRAFT);
        }
      })
      .catch(() => {
        // the server cannot be asked: the browser's copy is what there
        // is, and nothing is sent until it can be
        saved.current = snapshot(local.turns, local.stage, local.draft);
      })
      .finally(() => live && setLoadedFor(account));
    return () => {
      live = false;
    };
  }, [account]);

  // every change is mirrored to this tab at once and saved to the server
  // debounced -- a turn and its extras land in a burst, and the box saves
  // on a pause in typing rather than on every key
  useEffect(() => {
    if (!account || loadedFor !== account) return;
    try {
      sessionStorage.setItem(
        `${THREAD_KEY}.${account}`,
        JSON.stringify({ turns: turns.slice(-MIRRORED_TURNS), stage, draft }),
      );
    } catch {
      /* the thread just forgets on reload */
    }
    const now = snapshot(turns, stage, draft);
    if (now === saved.current) return;
    const t = setTimeout(() => {
      putProject(turns.filter((x) => !x.failed), stage, draft)
        .then(() => {
          saved.current = now;
        })
        .catch(() => {
          /* tried again on the next change; the tab's copy holds meanwhile */
        });
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [turns, stage, draft, account, loadedFor]);

  useEffect(() => {
    if (!projectId || !account) return;
    let live = true;
    projectMessages(projectId)
      .then((r) => {
        if (!live) return;
        const turns = r.items.map(fromMessage);
        const last = [...turns].reverse().find((t) => t.reply?.stage);
        setProjectThread({
          id: projectId,
          turns,
          stage: isStage(last?.reply?.stage) ? (last!.reply!.stage as Stage) : "",
          hasOlder: r.has_more,
        });
      })
      // unreadable (gone, not this account's): an empty thread, never
      // the studio-wide one under the project's name
      .catch(() => live && setProjectThread({ id: projectId, turns: [], stage: "", hasOlder: false }));
    return () => {
      live = false;
    };
  }, [projectId, account]);
  const scoped = projectId && projectThread?.id === projectId ? projectThread : null;
  const setProjectTurns = useCallback<Dispatch<SetStateAction<Turn[]>>>(
    (update) =>
      setProjectThread((pt) =>
        pt ? { ...pt, turns: typeof update === "function" ? update(pt.turns) : update } : pt,
      ),
    [],
  );
  const setProjectStage = useCallback(
    (st: Stage | "") => setProjectThread((pt) => (pt ? { ...pt, stage: st } : pt)),
    [],
  );
  const loadOlder = useCallback(async () => {
    const pt = projectThread;
    if (!pt || !pt.hasOlder) return;
    const oldest = pt.turns.find((t) => t.messageId)?.messageId;
    if (!oldest) return;
    const r = await projectMessages(pt.id, oldest);
    setProjectThread((now) =>
      now && now.id === pt.id
        ? { ...now, turns: [...r.items.map(fromMessage), ...now.turns], hasOlder: r.has_more }
        : now,
    );
  }, [projectThread]);

  const setDraft = useCallback((update: DraftUpdate) => {
    setDraftState((d) => (typeof update === "function" ? update(d) : { ...d, ...update }));
  }, []);

  const clearProject = useCallback(async () => {
    await clearProjectOnServer();
    setTurns([]);
    setStage("");
    setDraftState(EMPTY_DRAFT);
    saved.current = snapshot([], "", EMPTY_DRAFT);
    try {
      sessionStorage.removeItem(`${THREAD_KEY}.${account}`);
    } catch {
      /* nothing kept here to clear */
    }
  }, [account]);
  // Create wrote the scene: everything the conversation was for is on the
  // concept now. The Guide talk, the brief, the box and its references go;
  // what stays is the card pointing at it -- and the composer's own send
  // bubbles (`t.made`, lib/composer.ts), each of which carries its result
  // and is the "scene written" card the mock composer draws. The save
  // effect writes exactly that.
  const finishProject = useCallback((written: ComposerDraft["written"]) => {
    setTurns((ts) => ts.filter((t) => !!t.made));
    setStage("");
    setDraftState({ ...EMPTY_DRAFT, written });
  }, []);

  // the header's "New session" (lib/assistant.ts requestNewSession): the
  // shell cannot reach this context, so it asks through a window event
  useEffect(() => {
    const on = () => {
      clearProject().catch(() => {
        /* the server could not delete it: the thread stays as it is */
      });
    };
    window.addEventListener(NEW_SESSION_EVENT, on);
    return () => window.removeEventListener(NEW_SESSION_EVENT, on);
  }, [clearProject]);

  const value = useMemo<AssistantThread>(
    () => ({
      account,
      // inside a project the thread is ready once its history is read
      ready: projectId ? !!scoped : !!account && loadedFor === account,
      turns: projectId ? (scoped?.turns ?? []) : turns,
      setTurns: projectId ? setProjectTurns : setTurns,
      stage: projectId ? (scoped?.stage ?? "") : stage,
      setStage: projectId ? setProjectStage : setStage,
      draft,
      setDraft,
      clearProject,
      finishProject,
      projectId,
      hasOlder: !!scoped?.hasOlder,
      loadOlder,
    }),
    [account, loadedFor, turns, stage, draft, setDraft, clearProject, finishProject, projectId, scoped, setProjectTurns, setProjectStage, loadOlder],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

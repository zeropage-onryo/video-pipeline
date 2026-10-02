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
   follows. "New project" archives the open row (never deletes) and clears
   all three. Nothing here calls a model or spends. */
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
import { useShell } from "@/components/studio/shell";
import {
  EMPTY_DRAFT,
  NEW_SESSION_EVENT,
  asDraft,
  draftHasContent,
  getAssistantMemory,
  isStage,
  putProject,
  startNewProject,
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
  /** archive the open project on the server and start empty */
  newProject: () => Promise<void>;
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
  newProject: async () => {},
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

export function AssistantThreadProvider({ children }: { children: ReactNode }) {
  const { me, brand } = useShell();
  const account = brand || me?.account?.slug || "";
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

  const setDraft = useCallback((update: DraftUpdate) => {
    setDraftState((d) => (typeof update === "function" ? update(d) : { ...d, ...update }));
  }, []);

  const newProject = useCallback(async () => {
    await startNewProject();
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

  // the header's "New session" (lib/assistant.ts requestNewSession): the
  // shell cannot reach this context, so it asks through a window event
  useEffect(() => {
    const on = () => {
      newProject().catch(() => {
        /* the server could not archive it: the thread stays as it is */
      });
    };
    window.addEventListener(NEW_SESSION_EVENT, on);
    return () => window.removeEventListener(NEW_SESSION_EVENT, on);
  }, [newProject]);

  const value = useMemo<AssistantThread>(
    () => ({
      account,
      ready: !!account && loadedFor === account,
      turns,
      setTurns,
      stage,
      setStage,
      draft,
      setDraft,
      newProject,
    }),
    [account, loadedFor, turns, stage, draft, setDraft, newProject],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

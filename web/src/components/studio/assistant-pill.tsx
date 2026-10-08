"use client";

/* The assistant pill (2026-09-26, ASSISTANT_HANDOFF.md step 2; the
   "ZPF Guided Studio" design canvas). A named helper that floats
   bottom-right on every studio page: collapsed it is a pill with the
   avatar on its corner and the next move under the name; opened it is
   a card that talks the project through seven steps.

   It reads and suggests; it never spends. Every turn is the same
   POST /api/creative-guide the composer's Guide posts, with assistant=1
   (src/assistant_brain.py). Finding references costs nothing and banks
   nothing; Keep is the person's click and copies frames into /refs. A
   direction it likes goes INTO the composer with a ring on Create --
   pressing Create, like pressing Approve, stays the person's.

   Mounted once in studio/layout.tsx, so it survives client navigation
   and the conversation follows the person from page to page. The thread
   itself is not this component's (2026-10-02): it is the one
   AssistantThreadProvider holds for the whole studio, which the Studio
   composer's Guide writes into too -- so a talk started in the box is
   here when the pill opens on Pipeline, and the box is still full when
   the person comes back.

   Inside a project's workspace (2026-10-07) the thread IS that project's
   chat history: every turn carries project_id and remember=1, the server
   writes it as it happens, and reopening the project carries on where it
   left off. There, nothing clears it -- deleting the project does. The
   Guide makes projects too (create_project / save_as_project): those come
   back as a proposal, drawn as a confirm card, and the click makes it.

   How it shows a turn (2026-10-08, docs/ASSISTANT_AVATARS.md "not built
   yet" 1-4): the face's arc fills from the job's `steps` while the
   reference hunt can say how far it is; the answer types itself out from
   the job's `partial` as the model writes it; an answer that lands while
   the card is shut is counted on the face and quoted in the bubble; and
   the card grows out of the pill (one motion layoutId for the shell, one
   for the face) instead of swapping with it.

   It can draw a still (2026-10-08): its turns ask as `output=still`, which
   hands the brain make_image and nothing else -- a scene is the composer's.
   A still is the same step card the composer shows (still-step.tsx), held
   on Approve, with the model and its price under it; the click draws it
   through /generate/run into that same turn, so the composer shows it too,
   and a still waiting on Approve turns the face amber like any click it
   is waiting on. */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { motion, useReducedMotion, type Transition } from "motion/react";
import { ArrowRight, ChevronDown, ChevronUp, Settings2, SquarePen } from "lucide-react";
import { useShell } from "@/components/studio/shell";
import { useAssistantThread } from "@/components/studio/assistant-thread";
import {
  announceBalanceChange,
  getBalance,
  getConceptDetail,
  getImageModels,
  isProjectTool,
  queuePending,
  runCreativeGuide,
  runGuideAction,
  runImage,
  waitForJob,
  workspaceHref,
  type Balance,
  type Concept,
  type GuideReply,
  type ImageModels,
} from "@/lib/studio-api";
import { IMAGE_ASPECTS, isMake, loadImageModel, newMadeId, type Made } from "@/lib/composer";
import { StillStep, isStillStep, lineIsPrompt, stepOf } from "@/components/studio/still-step";
import { headline } from "@/lib/assistant-text";
import { TypedText } from "@/components/studio/typed-text";
import {
  AVATARS,
  asProjectConversation,
  STAGES,
  STAGE_LABEL,
  TONES,
  cleanName,
  firstEmoji,
  getAssistantMemory,
  isStage,
  keepReferences,
  laterStage,
  loadPersona,
  pageName,
  pageStage,
  postVerdicts,
  putPersona,
  savePersona,
  sendToComposer,
  type ContactSheet,
  type Persona,
  type Stage,
  type Tone,
  type Turn,
} from "@/lib/assistant";
import "@/components/studio/assistant.css";
import { ContactSheetView } from "@/components/studio/contact-sheet";
import {
  AVATAR_STATES,
  AssistantAvatar,
  DEFAULT_AVATAR,
  EMOJI_SKINS,
  GLYPHS,
  STATE_LABEL,
  glyphAvatar,
  glyphOf,
  type AvatarState,
} from "@/components/studio/assistant-avatar";

/* a sheet opens with the frames the check kept already chosen */
const chosenOf = (t: Turn): Record<string, boolean> => {
  if (t.chosen) return t.chosen;
  const sel: Record<string, boolean> = {};
  t.reply?.sheet?.sheet?.forEach((n) => n.keepers.forEach((k) => (sel[k.id] = true)));
  return sel;
};

const GREETED_KEY = "zpf.assistant.greeted";
/* how long the face says "done" after a turn lands, and how long nothing
   has to happen before it rests (assistant-avatar.tsx's states) */
const SUCCESS_MS = 1400;
const SLEEP_MS = 10 * 60 * 1000;
/* a turn whose words are arriving is asked again sooner than one still
   thinking, so the typing keeps up without polling a silent job faster */
const POLL_MS = 1500;
const STREAM_POLL_MS = 500;
/* the card growing out of the pill, and back: quick and settled, never a
   bounce (motion is the assistant's, but it should not show off) */
const MORPH: Transition = { type: "spring", stiffness: 520, damping: 44, mass: 0.9 };

/* phones draw the open card as a sheet with square bottom corners; the
   morph has to be told, since it scale-corrects the radius it is given */
const PHONE = "(max-width: 720px)";
function usePhone(): boolean {
  return useSyncExternalStore(
    (on) => {
      const q = window.matchMedia(PHONE);
      q.addEventListener("change", on);
      return () => q.removeEventListener("change", on);
    },
    () => window.matchMedia(PHONE).matches,
    () => false,
  );
}

export function AssistantPill() {
  const pathname = usePathname() || "/studio";
  const { me, signedOut, toast, balance } = useShell();
  // the thread, the step and the composer's box are the studio's, shared
  // with the Studio page's Guide (assistant-thread.tsx)
  const {
    account,
    turns,
    setTurns,
    stage: convStage,
    setStage: setConvStage,
    draft: composer,
    clearProject: resetProject,
    projectId,
    hasOlder,
    loadOlder,
  } = useAssistantThread();
  const router = useRouter();
  const [persona, setPersona] = useState<Persona | null>(null);
  const [setup, setSetup] = useState(false);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState("");
  // the running turn, as its job reports it: how far the hunt is (the
  // arc) and the answer's words so far (typed into the card)
  const [steps, setSteps] = useState<{ done: number; of: number } | null>(null);
  const [partial, setPartial] = useState("");
  // answers that landed while the card was shut, until it is opened
  const [unread, setUnread] = useState(0);
  const openRef = useRef(false);
  const phone = usePhone();
  // under reduced motion the card and the pill simply swap, as they did
  const still = useReducedMotion();
  const [bubble, setBubble] = useState("");
  const bubbleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [landed, setLanded] = useState(false);
  const [resting, setResting] = useState(false);
  const wasBusy = useRef(false);
  const body = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  // the persona is per account: two brands, two assistants. The browser's
  // copy paints first; the server's copy (src/assistant_store.py) then
  // wins. One set up here before the server remembered anything is sent
  // up once, so nothing already made is lost. (The thread used to load
  // here too; the provider owns that now.)
  useEffect(() => {
    if (!account) return;
    let live = true;
    const localPersona = loadPersona(account);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after mount
    setPersona(localPersona);
    getAssistantMemory()
      .then((m) => {
        if (!live) return;
        if (m.persona) {
          const p = { name: m.persona.name, avatar: m.persona.avatar, tone: m.persona.tone };
          setPersona(p);
          savePersona(account, p);
        } else if (localPersona) {
          void putPersona(localPersona).catch(() => {});
        }
      })
      .catch(() => {
        /* the server cannot be asked: the browser's copy is what there is */
      });
    return () => {
      live = false;
    };
  }, [account]);

  const say = useCallback((line: string, ms = 6500) => {
    setBubble(line);
    if (bubbleTimer.current) clearTimeout(bubbleTimer.current);
    bubbleTimer.current = setTimeout(() => setBubble(""), ms);
  }, []);
  // the one hello per tab, once there is someone to greet
  useEffect(() => {
    if (!persona || !me || open) return;
    try {
      if (sessionStorage.getItem(GREETED_KEY)) return;
      sessionStorage.setItem(GREETED_KEY, "1");
    } catch {
      return;
    }
    const first = (me.user.display_name || "").split(/\s+/)[0];
    const t = setTimeout(() => say(`Hey${first ? ` ${first}` : ""} — what are we making today?`), 900);
    return () => clearTimeout(t);
  }, [persona, me, open, say]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  useEffect(() => {
    body.current?.scrollTo({ top: body.current.scrollHeight, behavior: "smooth" });
  }, [turns, busy, open, partial]);
  // read by turns that land after the person has closed (or opened) the
  // card: the closure a turn started in still holds the old `open`
  useEffect(() => {
    openRef.current = open;
  }, [open]);

  /* An answer landed. With the card open the person is reading it; shut,
     it is counted on the face and its gist goes in the bubble. */
  const arrived = useCallback(
    (line: string) => {
      if (openRef.current) return;
      setUnread((n) => n + 1);
      if (line) say(line);
    },
    [say],
  );
  // what a still can be drawn on and what one costs: read once a step card
  // is on the thread (the composer may have left one waiting), for its line
  const [stillModels, setStillModels] = useState<ImageModels | null>(null);
  const hasStep = turns.some(isStillStep);
  useEffect(() => {
    if (!hasStep || stillModels) return;
    getImageModels()
      .then(setStillModels)
      .catch(() => {
        /* the card shows Approve without its price line */
      });
  }, [hasStep, stillModels]);
  // the model a still is drawn on: the composer's remembered pick, else the server's default
  const stillModel = (models: ImageModels | null) => {
    const kept = loadImageModel();
    return models?.items.some((m) => m.id === kept) ? kept : (models?.default ?? "");
  };
  const stillLine = (modelId?: string) => {
    if (!stillModels) return "";
    const id = modelId || stillModel(stillModels);
    const m = stillModels.items.find((x) => x.id === id) ?? stillModels.items[0];
    if (!m) return "";
    return `${m.label} · ${balance?.exempt ? "not charged" : `${m.credits.toLocaleString()} credits`}`;
  };

  function openCard() {
    setBubble("");
    setUnread(0);
    setOpen(true);
    setTimeout(() => input.current?.focus(), 50);
  }

  // a turn that comes back without failing earns one "done" on the face
  useEffect(() => {
    if (wasBusy.current && !busy && !turns.some((t) => t.failed)) {
      setLanded(true);
      const t = setTimeout(() => setLanded(false), SUCCESS_MS);
      wasBusy.current = busy;
      return () => clearTimeout(t);
    }
    wasBusy.current = busy;
  }, [busy, turns]);
  // nobody has touched it in a while: it rests, and wakes on the next touch
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- any activity wakes it
    setResting(false);
    if (busy || open) return;
    const t = setTimeout(() => setResting(true), SLEEP_MS);
    return () => clearTimeout(t);
  }, [busy, open, turns, text, bubble]);

  const stage: Stage = laterStage(convStage, pageStage(pathname));
  const step = STAGES.indexOf(stage) + 1;
  const where = pageName(pathname);
  const project = turns.length > 0;
  // the extras stay on the newest ANSWER: a "Kept 3 frames" note after it
  // must not take the contact sheet away
  const lastIndex = turns.map((t) => !!t.reply).lastIndexOf(true);
  const nudge = [...turns].reverse().find((t) => t.nudge || t.reply?.nudge);
  const nextMove = nudge?.nudge || nudge?.reply?.nudge || "";
  const pageAhead = STAGES.indexOf(pageStage(pathname)) > STAGES.indexOf(convStage || "brief");
  const setTurn = (i: number, patch: Partial<Turn>) =>
    setTurns((all) => all.map((t, j) => (j === i ? { ...t, ...patch } : t)));

  async function ask(message: string) {
    const said = message.trim();
    if (!said || busy || !persona) return;
    const next: Turn[] = [...turns.filter((t) => !t.failed), { role: "user", content: said }];
    setTurns(next);
    setText("");
    setBusy(true);
    setDetail("Thinking…");
    setSteps(null);
    setPartial("");
    try {
      const form = new FormData();
      // the box's own sends (t.made) are left out: they were never asked of
      // the Guide, and two user turns in a row with no answer between
      // would read as an unanswered question
      form.append(
        "conversation",
        // the newest 40: the server takes no more in one turn, and a
        // project's history can be longer than that
        JSON.stringify({ messages: next.filter((t) => !t.made).slice(-40).map(({ role, content }) => ({ role, content })) }),
      );
      // inside a project's workspace: the turn is the project's, and the
      // server keeps it in the project's history
      if (projectId) {
        form.append("project_id", String(projectId));
        form.append("remember", "1");
      }
      if (account) form.append("brand", account);
      form.append("guide_provider", "gemini");
      form.append("idea", composer.idea.trim() || said);
      form.append("assistant", "1");
      form.append("assistant_name", persona.name);
      form.append("assistant_tone", persona.tone);
      form.append("stage", stage);
      form.append("page", pathname);
      form.append("brain", "auto");
      // a maker turn that can draw a still and nothing else: a "make it"
      // here comes back as a step card, held on Approve
      form.append("output", "still");
      // the composer's references ride along, so the turn sees what the box
      // sees: its uploads (saved to the bin on attach) and then its picks
      [...composer.uploads.map((u) => u.url), ...composer.picked].forEach((u) => form.append("asset_photos", u));
      const started = await runCreativeGuide(form);
      const job = await waitForJob(
        started.job_id,
        (j) => {
          setDetail(j.detail || "Thinking…");
          setSteps(j.steps && j.steps.of > 0 ? j.steps : null);
          setPartial(j.status === "running" ? (j.partial ?? "") : "");
        },
        (j) => (j.partial ? STREAM_POLL_MS : POLL_MS),
      );
      const reply = (job as unknown as { reply?: GuideReply }).reply;
      if (job.status !== "done" || !reply) throw new Error(job.error || `${persona.name} stopped.`);
      setTurns([...next, { role: "assistant", content: reply.message, reply }]);
      if (isStage(reply.stage)) setConvStage(reply.stage);
      arrived(headline(reply.nudge, reply.message));
    } catch (e) {
      setTurns([...next.slice(0, -1), { ...next[next.length - 1], failed: true }]);
      setText((now) => now || said);
      toast(e instanceof Error ? e.message : "That did not go through.", "err");
    } finally {
      setBusy(false);
      setDetail("");
      setSteps(null);
      setPartial("");
    }
  }

  /* Keep: the person's click, and the only write here. The frames come
     back as /refs paths and go straight onto the composer's picks. */
  async function keep(i: number, sheet: ContactSheet) {
    const chosen = chosenOf(turns[i]);
    const ids = sheet.sheet.flatMap((n) => [...n.keepers, ...n.rejected]).filter((f) => chosen[f.id]).map((f) => f.id);
    if (!ids.length || busy || !persona) return;
    setBusy(true);
    setDetail("Keeping the frames…");
    try {
      const res = await keepReferences(ids);
      // the click against the checker, every frame the sheet showed: which
      // ones refcheck kept, which ones the person kept. Best-effort -- a
      // verdict that did not record must never undo a keep that did.
      void postVerdicts(
        sheet.sheet.flatMap((n) =>
          [...n.keepers, ...n.rejected].map((f) => ({
            id: f.id,
            role: n.role,
            query: n.query,
            checker_kept: n.keepers.includes(f),
            why: f.why || f.kept_for || "",
            person_kept: !!chosen[f.id],
            source_url: f.source_url || "",
          })),
        ),
      ).catch(() => {});
      const urls = res.result.kept.map((k) => k.url);
      if (urls.length) sendToComposer({ refs: urls, by: persona.name, avatar: persona.avatar });
      const refused = res.result.refused.length;
      setTurns((t) => [
        ...t.map((x, j) => (j === i ? { ...x, kept: true } : x)),
        {
          nudge: pathname === "/studio" ? "Next: press Create when it reads right" : "Next: open Studio and press Create",
          role: "assistant",
          content:
            `Kept ${urls.length} frame${urls.length === 1 ? "" : "s"} — they're on your composer as references.` +
            (refused ? ` ${refused} could not be kept.` : ""),
        },
      ]);
      toast(`${urls.length} reference${urls.length === 1 ? "" : "s"} added to the composer`);
      arrived("");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Those frames were not kept.", "err");
    } finally {
      setBusy(false);
      setDetail("");
    }
  }

  /* Approve on a still's step card: the click that spends. The still is
     drawn through the composer's own route (/generate/run, on the model the
     composer last picked) into that same turn, so the composer shows it as
     its own when the person goes back. */
  async function approveStill(i: number) {
    const t = turns[i];
    if (!t || busy || !isStillStep(t)) return;
    const { prompt, aspect, state } = stepOf(t);
    if (state !== "waiting" && state !== "failed") return;
    const models = stillModels ?? (await getImageModels().catch(() => null));
    const model = stillModel(models);
    const frame = aspect && IMAGE_ASPECTS.some((a) => a.id === aspect) ? aspect : IMAGE_ASPECTS[0].id;
    const refs = [...composer.uploads.map((u) => u.url), ...composer.picked];
    const made: Made = {
      id: newMadeId(),
      output: "image",
      refs,
      status: "running",
      detail: "",
      frame,
      prompt,
      ...(model ? { model } : {}),
    };
    const patch = (p: Partial<Made>) =>
      setTurns((all) => all.map((x) => (x.made?.id === made.id ? { ...x, made: { ...x.made!, ...p } } : x)));
    setTurns((all) => all.map((x) => (x === t ? { ...x, made } : x)));
    setBusy(true);
    setDetail("Drawing the still…");
    try {
      const form = new FormData();
      if (account) form.append("brand", account);
      form.append("prompt", prompt);
      form.append("output", "image");
      form.append("aspect", frame);
      if (model) form.append("image_model", model);
      refs.forEach((u) => form.append("asset_photos", u));
      const started = await runImage(form);
      patch({ jobId: started.job_id });
      const job = await waitForJob(started.job_id, (j) => setDetail(j.detail || "Drawing the still…"));
      announceBalanceChange();
      if (job.status !== "done") throw new Error(job.error || "The still did not finish.");
      const conceptId = typeof job.ref_id === "number" ? job.ref_id : null;
      const concept = conceptId ? await getConceptDetail(conceptId).catch(() => null) : null;
      const shots = concept?.shots ?? [];
      const image = concept?.reference_image || shots[shots.length - 1]?.reference_image || null;
      patch({ status: "done", conceptId, image, detail: job.detail || "" });
      if (!image) toast(job.detail || "Saved, but no image came back.", "err");
      arrived("Your still is ready");
    } catch (e) {
      const said = e instanceof Error ? e.message : "The still was not drawn.";
      patch({ status: "failed", detail: said });
      toast(said, "err");
    } finally {
      setBusy(false);
      setDetail("");
    }
  }

  /* The confirm card: a WRITE the Guide proposed, run only on this click.
     A project tool comes back with the project it made, and the person is
     taken to its workspace; save_as_project carries the thread so far (its
     turns and the scenes its sends made) and then clears the studio-wide
     thread, whose conversation is the project's now. */
  async function decide(i: number, yes: boolean) {
    const t = turns[i];
    const proposal = t?.reply?.proposal;
    if (!proposal || t.decided || busy) return;
    if (!yes) {
      setTurn(i, { decided: "skipped" });
      return;
    }
    setBusy(true);
    setDetail(`${proposal.label}…`);
    try {
      const extra = proposal.tool === "save_as_project" ? asProjectConversation(turns.slice(0, i)) : undefined;
      const done = await runGuideAction(proposal, extra);
      if (done.project && isProjectTool(proposal.tool)) {
        setTurn(i, { decided: "done" });
        toast(`“${done.project.title}” is on the Projects board`);
        if (proposal.tool === "save_as_project") await resetProject().catch(() => {});
        router.push(workspaceHref(done.project.id));
        return;
      }
      setTurns((all) => [
        ...all.map((x, j) => (j === i ? { ...x, decided: "done" as const } : x)),
        { role: "assistant", content: `Done — ${done.result}` },
      ]);
      arrived(`Done — ${done.result}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "That did not go through.", "err");
    } finally {
      setBusy(false);
      setDetail("");
    }
  }

  /* Clear: the conversation is deleted on the server (never archived --
     it was working memory) and the card AND the composer's box start empty. */
  async function clearConversation() {
    if (busy) return;
    try {
      await resetProject();
    } catch {
      toast("Could not clear the conversation", "err");
      return;
    }
    setText("");
    setTimeout(() => input.current?.focus(), 50);
  }

  function pickDirection(i: number, j: number, d: { title: string; logline: string; turn?: string }) {
    if (!persona) return;
    const written = [d.logline.trim(), d.turn?.trim()].filter(Boolean).join(" ");
    sendToComposer({ text: written, by: persona.name, avatar: persona.avatar });
    setTurns((all) =>
      all.map((t, k) => (k === i ? { ...t, picked: j, nudge: `Next: press Create on ${d.title}` } : t)),
    );
    say(`${d.title} is in your composer — press Create when it reads right.`);
  }

  if (signedOut || !me?.account) return null;
  // the editor seats its agent in its own left panel (invideo's place), so
  // a floating pill over the timeline would be a second, competing one
  if (/^\/studio\/cut\/[^/]+/.test(pathname)) return null;
  // the Studio composer has the Guide IN its box, on this same thread
  // (2026-10-02, the composer mock): a pill floating over the send button
  // would be the same helper twice, so it stays off on that one page
  if (pathname.replace(/\/$/, "") === "/studio") return null;

  const pillLine = !project
    ? "Start a project, or ask me anything"
    : pageAhead && pathname.startsWith("/studio/queue")
      ? "Ask me which render to start with"
      : pageAhead
        ? `On ${STAGE_LABEL[stage]} — ask me what's next`
        : nextMove || `On ${STAGE_LABEL[stage]}`;
  const avatar = persona?.avatar ?? DEFAULT_AVATAR;
  const name = persona?.name ?? "Assistant";
  // what the face shows. "needs" is the newest answer waiting on the
  // person's click: a confirm card not yet answered, or a contact sheet
  // with frames picked and not yet kept.
  const latest = lastIndex >= 0 ? turns[lastIndex] : null;
  const waiting =
    !!latest &&
    !busy &&
    ((!!latest.reply?.proposal && isProjectTool(latest.reply.proposal.tool) && latest.decided == null) ||
      (isStillStep(latest) && stepOf(latest).state === "waiting") ||
      (!!latest.reply?.sheet?.sheet?.length && !latest.kept && Object.values(chosenOf(latest)).some(Boolean)));
  const face: AvatarState = busy
    ? steps || (detail && !/^thinking/i.test(detail))
      ? "working"
      : "thinking"
    : turns.some((t) => t.failed)
      ? "error"
      : landed
        ? "success"
        : waiting
          ? "needs"
          : open && text.trim()
            ? "listening"
            : resting
              ? "sleeping"
              : "idle";
  // the hunt's own count, when it has one: the arc fills for real
  const progress = face === "working" && steps ? steps.done / steps.of : undefined;
  const faceTitle =
    `${name}: ${STATE_LABEL[face]}` +
    (progress != null ? `, ${Math.round(progress * 100)}%` : "") +
    (unread ? ` · ${unread} new` : "");
  // the morph scale-corrects only the radius it is handed, so the card's
  // and the pill's corners are given here rather than left to the CSS
  const lower = phone ? 0 : 26;
  const cardCorners = {
    borderTopLeftRadius: 26,
    borderTopRightRadius: 26,
    borderBottomLeftRadius: lower,
    borderBottomRightRadius: lower,
  };
  const pillCorners = { borderRadius: 30 };
  const morph = (id: string) =>
    still ? {} : { layoutId: id, layoutDependency: open, transition: MORPH };

  return (
    <div className={`zpa${open ? " open" : ""}`} data-page={where.toLowerCase()} data-face={face}>
      {open ? (
        <motion.section
          {...morph("zpa-shell")}
          style={cardCorners}
          className="zpa-card"
          aria-label={name}
          role="dialog"
        >
          <motion.span {...morph("zpa-face")} className="zpa-avatar big">
            <AssistantAvatar
              avatar={avatar}
              state={setup || !persona ? "listening" : face}
              progress={progress}
              size="lg"
              title={faceTitle}
            />
          </motion.span>
          {setup || !persona ? (
            <Setup
              initial={persona}
              onDone={(p) => {
                savePersona(account, p);
                setPersona(p);
                // the account's copy, so every browser meets the same assistant
                putPersona(p)
                  .then((r) => setPersona(r.persona))
                  .catch(() => toast("Saved in this browser only -- the studio could not be reached", "err"));
                setSetup(false);
                setTimeout(() => input.current?.focus(), 50);
              }}
              onClose={() => (persona ? setSetup(false) : setOpen(false))}
            />
          ) : (
            <>
              <header className="zpa-head">
                <div className="zpa-title">
                  <b>{persona.name}</b>
                  <span>on {where}</span>
                  {project && !projectId ? (
                    <button
                      type="button"
                      className="zpa-icon"
                      title="Clear the conversation -- nothing is kept"
                      aria-label="Clear conversation"
                      disabled={busy}
                      onClick={() => void clearConversation()}
                    >
                      <SquarePen strokeWidth={1.6} />
                    </button>
                  ) : null}
                  <button type="button" className="zpa-icon" title="Rename or change the look" onClick={() => setSetup(true)}>
                    <Settings2 strokeWidth={1.6} />
                  </button>
                  <button type="button" className="zpa-icon" aria-label="Shrink to pill" onClick={() => setOpen(false)}>
                    <ChevronDown strokeWidth={1.6} />
                  </button>
                </div>
                <div className="zpa-steps" aria-hidden>
                  {STAGES.map((s, k) => (
                    <span key={s} data-state={k + 1 < step ? "done" : k + 1 === step ? "now" : undefined} />
                  ))}
                </div>
                <span className="zpa-mono">
                  Step {step} of 7 · {STAGE_LABEL[stage]}
                </span>
              </header>

              <div className="zpa-body" ref={body}>
                {projectId && hasOlder ? (
                  <button type="button" className="zpa-chip zpa-older" disabled={busy} onClick={() => void loadOlder().catch(() => {})}>
                    Earlier messages
                  </button>
                ) : null}
                {!turns.length ? (
                  <p className="zpa-msg">
                    {pathname.startsWith("/studio/queue")
                      ? "The Queue is where money is spent. Ask me which render to start with — approving stays your click."
                      : projectId
                        ? "This conversation stays with the project until it is deleted. Ask me to continue the story, or what to make next."
                        : "Tell me what you want to make. I'll ask a couple of things, pitch directions, find references and put it all in your composer. Create and Approve stay your clicks."}
                  </p>
                ) : null}
                {turns.map((t, i) => t.made && !isStillStep(t) ? null : (
                  <div key={i} className="zpa-turn">
                    {lineIsPrompt(t) ? null : (
                      <p className={`zpa-msg${t.role === "user" ? " me" : ""}${t.failed ? " failed" : ""}`}>
                        {t.content}
                        {t.failed ? <span className="zpa-failed">Not sent — press send to retry</span> : null}
                      </p>
                    )}
                    {isStillStep(t) ? (
                      <StillStep
                        turn={t}
                        line={stillLine(t.made?.model)}
                        busy={busy}
                        onApprove={() => void approveStill(i)}
                        showImage
                      />
                    ) : null}
                    {t.reply && i === lastIndex ? (
                      <Extras
                        reply={t.reply}
                        busy={busy}
                        chosen={chosenOf(t)}
                        kept={!!t.kept}
                        picked={t.picked ?? null}
                        name={persona.name}
                        onChip={(c) => void ask(c)}
                        onDirection={(j, d) => pickDirection(i, j, d)}
                        onToggle={(id) => {
                          const c = chosenOf(t);
                          setTurn(i, { chosen: { ...c, [id]: !c[id] } });
                        }}
                        onKeep={(sheet) => void keep(i, sheet)}
                        decided={t.decided}
                        onDecide={(yes) => void decide(i, yes)}
                      />
                    ) : null}
                  </div>
                ))}
                {busy && partial.trim() ? (
                  // the answer as it is written; the turn that lands replaces
                  // it with the same words, so it is hidden from a screen
                  // reader, which hears the turn once
                  <p className="zpa-msg zpa-typing" aria-hidden>
                    <TypedText text={partial.trim()} caret="zpa-caret" />
                  </p>
                ) : null}
                {busy ? (
                  <p className="zpa-working" role="status">
                    <span className="zpa-dot" /> {detail || "Thinking…"}
                    {steps ? (
                      <span className="zpa-count">
                        {steps.done}/{steps.of}
                      </span>
                    ) : null}
                  </p>
                ) : null}
                {pathname.startsWith("/studio/queue") ? <Credits
                    brand={account}
                    onShow={() => {
                      // a phone's sheet covers the page: step aside so the ring is seen
                      if (window.matchMedia("(max-width: 720px)").matches) setOpen(false);
                    }}
                  /> : null}
              </div>

              <form
                className="zpa-input"
                onSubmit={(e) => {
                  e.preventDefault();
                  void ask(text || [...turns].reverse().find((t) => t.failed)?.content || "");
                }}
              >
                <label htmlFor="zpa-say" className="zpa-sr">
                  Message {persona.name}
                </label>
                <input
                  id="zpa-say"
                  ref={input}
                  value={text}
                  maxLength={2000}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={`Talk to ${persona.name}…`}
                  autoComplete="off"
                />
                <button type="submit" aria-label="Send" disabled={busy || !(text.trim() || turns.some((t) => t.failed))}>
                  <ArrowRight strokeWidth={1.8} />
                </button>
              </form>
            </>
          )}
        </motion.section>
      ) : (
        <>
          <span className="zpa-perch">
            <motion.span {...morph("zpa-face")} className="zpa-avatar">
              <AssistantAvatar avatar={avatar} state={face} progress={progress} badge={unread} size="md" title={faceTitle} />
            </motion.span>
            {bubble ? (
              <span className="zpa-bubble" role="status">
                {bubble}
              </span>
            ) : null}
          </span>
          <motion.button
            {...morph("zpa-shell")}
            style={pillCorners}
            type="button"
            className="zpa-pill"
            aria-label={`Open ${name}${unread ? ` — ${unread} new ${unread === 1 ? "answer" : "answers"}` : ""}`}
            onClick={openCard}
          >
            <span className="zpa-lines">
              <span className="zpa-mono">
                {name} · {project ? `Step ${step} of 7` : `on ${where}`}
                {face !== "idle" ? (
                  <span className="zpa-state" data-state={face}>
                    {STATE_LABEL[face]}
                  </span>
                ) : null}
              </span>
              <span className="zpa-nudge">{pillLine}</span>
            </span>
            <span className="zpa-go" aria-hidden>
              <ChevronUp strokeWidth={1.8} />
            </span>
          </motion.button>
        </>
      )}
    </div>
  );
}

/* the latest answer's tap-ables: chips, judged directions, the contact sheet */
function Extras({
  reply,
  busy,
  chosen,
  kept,
  picked,
  name,
  onChip,
  onDirection,
  onToggle,
  onKeep,
  decided,
  onDecide,
}: {
  reply: GuideReply;
  busy: boolean;
  chosen: Record<string, boolean>;
  kept: boolean;
  picked: number | null;
  name: string;
  onChip: (c: string) => void;
  onDirection: (j: number, d: { title: string; logline: string; turn?: string }) => void;
  onToggle: (id: string) => void;
  onKeep: (sheet: ContactSheet) => void;
  decided?: "done" | "skipped";
  onDecide: (yes: boolean) => void;
}) {
  const sheet = reply.sheet;
  // a write the Guide proposed: its card, here. A make proposal is the
  // composer's (it runs on the send) and keep_references is the sheet's Keep.
  const proposal =
    reply.proposal && !isMake(reply.proposal.tool) && reply.proposal.tool !== "keep_references" ? reply.proposal : null;
  // a question whose options are just the directions' titles says the
  // same thing twice; the direction cards are the better tap
  const titles = new Set((reply.directions ?? []).map((d) => d.title.trim().toLowerCase()));
  const questions = (reply.questions ?? [])
    .map((q) => ({ ...q, options: q.options.filter((o) => !titles.has(o.trim().toLowerCase())) }))
    .filter((q) => q.options.length);
  return (
    <>
      {questions.map((q, k) => (
        <div key={k} className="zpa-q">
          <span>{q.ask}</span>
          <div className="zpa-chips">
            {q.options.map((o) => (
              <button type="button" key={o} className="zpa-chip" disabled={busy} onClick={() => onChip(o)}>
                {o}
              </button>
            ))}
          </div>
        </div>
      ))}
      {!reply.questions?.length && reply.choices?.length ? (
        <div className="zpa-chips">
          {reply.choices.map((o) => (
            <button type="button" key={o} className="zpa-chip" disabled={busy} onClick={() => onChip(o)}>
              {o}
            </button>
          ))}
        </div>
      ) : null}

      {reply.directions?.length ? (
        <div className="zpa-dirs">
          {reply.directions.map((d, j) => (
            <button
              type="button"
              key={j}
              className={`zpa-dir${picked === j ? " on" : ""}`}
              aria-pressed={picked === j}
              title={d.verdict || undefined}
              onClick={() => onDirection(j, d)}
            >
              <span className="zpa-mono">
                {String.fromCharCode(65 + j)} · {picked === j ? "in composer" : d.title}
                <em>
                  {typeof d.score === "number"
                    ? `${d.rubric === "ad" ? "ad " : ""}${Math.round(d.score * 10)}/10`
                    : "not judged"}
                </em>
              </span>
              {picked === j ? <b>{d.title}</b> : null}
              <span className="zpa-log">{d.logline}</span>
              {d.verdict ? (
                <span className="zpa-verdict">
                  {d.rubric === "ad" ? "Ad judge" : "Judge"}: {d.verdict}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}

      {sheet ? (
        <ContactSheetView sheet={sheet} chosen={chosen} kept={kept} busy={busy} name={name} onToggle={onToggle} onKeep={onKeep} />
      ) : null}

      {proposal ? (
        <div className="zpa-confirm">
          <span className="zpa-mono">{proposal.label}</span>
          {Object.entries(proposal.args)
            .filter(([, v]) => v !== "" && v != null)
            .map(([k, v]) => (
              <p key={k} className="zpa-msg">
                <span className="zpa-mono dim">{k}</span> {String(v)}
              </p>
            ))}
          {decided ? (
            <span className="zpa-mono dim">{decided === "done" ? "Done" : "Not now"}</span>
          ) : (
            <div className="zpa-chips">
              <button type="button" className="zpa-keep" disabled={busy} onClick={() => onDecide(true)}>
                Confirm
              </button>
              <button type="button" className="zpa-chip" disabled={busy} onClick={() => onDecide(false)}>
                Not now
              </button>
            </div>
          )}
        </div>
      ) : null}
    </>
  );
}

/* On the Queue: what the next render costs, in credits, and a way to
   find its Approve button. Pointing is all it does. */
function Credits({ brand, onShow }: { brand: string; onShow: () => void }) {
  const [balance, setBalance] = useState<Balance | null>(null);
  const [card, setCard] = useState<Concept | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    getBalance()
      .then((b) => live && setBalance(b))
      .catch(() => live && setBalance(null));
    queuePending(brand || undefined)
      .then((r) => live && setCard(r.items.find((c) => !c.blocked && c.quote && !c.quote.error) ?? null))
      .catch(() => live && setCard(null));
    return () => {
      live = false;
    };
  }, [brand]);
  if (card === undefined) return <p className="zpa-working">Reading the Queue…</p>;
  if (!card?.quote) return <p className="zpa-mono dim">Nothing is waiting on an approve.</p>;
  const q = card.quote;
  const credits = q.credits ?? 0;
  const have = balance?.available;
  let line: React.ReactNode;
  if (balance?.exempt) line = <span className="zpa-cost">Not charged</span>;
  else if (typeof have === "number" && credits > have)
    line = (
      <>
        <span className="zpa-cost short">
          Need {credits.toLocaleString()} cr · have {have.toLocaleString()}
        </span>
        <Link href="/pricing" className="zpa-buy">
          Buy credits
        </Link>
      </>
    );
  else
    line = (
      <>
        <span className="zpa-cost">{credits.toLocaleString()} cr</span>
        {typeof have === "number" ? (
          <span className="zpa-mono dim">
            You have {have.toLocaleString()} · after {(have - credits).toLocaleString()}
          </span>
        ) : null}
      </>
    );
  return (
    <div className="zpa-credits">
      <span className="zpa-mono dim">Next render</span>
      <b>{card.title || `Concept #${card.id}`}</b>
      <div className="zpa-costline">{line}</div>
      <button type="button" className="zpa-chip" onClick={() => {
          onShow();
          showApprove();
        }}>
        Show me its Approve
      </button>
    </div>
  );
}

/* rings the page's first live Approve button; the click is still theirs */
function showApprove() {
  const btn = Array.from(document.querySelectorAll<HTMLButtonElement>(".zps .shell button")).find(
    (b) => /^\s*approve/i.test(b.textContent || "") && !b.disabled,
  );
  if (!btn) return;
  btn.scrollIntoView({ behavior: "smooth", block: "center" });
  btn.classList.add("zpa-ring");
  setTimeout(() => btn.classList.remove("zpa-ring"), 4000);
}

/* "Meet your assistant": a name, a face, a way of talking */
function Setup({
  initial,
  onDone,
  onClose,
}: {
  initial: Persona | null;
  onDone: (p: Persona) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "Nova");
  const [avatar, setAvatar] = useState(initial?.avatar ?? DEFAULT_AVATAR);
  const [other, setOther] = useState(
    initial && !glyphOf(initial.avatar) && !EMOJI_SKINS.includes(initial.avatar) && !AVATARS.includes(initial.avatar)
      ? initial.avatar
      : "",
  );
  // the preview walks through every state so the look is seen moving
  const [demo, setDemo] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setDemo((d) => (d + 1) % AVATAR_STATES.length), 1700);
    return () => clearInterval(t);
  }, []);
  const demoState = AVATAR_STATES[demo];
  const [tone, setTone] = useState<Tone>(initial?.tone ?? "direct");
  const clean = cleanName(name);
  return (
    <form
      className="zpa-setup"
      onSubmit={(e) => {
        e.preventDefault();
        if (clean) onDone({ name: clean, avatar: avatar || DEFAULT_AVATAR, tone });
      }}
    >
      <div className="zpa-title">
        <b>Meet your assistant</b>
        <button type="button" className="zpa-icon" aria-label="Close" onClick={onClose}>
          <ChevronDown strokeWidth={1.6} />
        </button>
      </div>
      <p className="zpa-msg">It rides along on every page, remembers what you like, and walks you from idea to clips.</p>
      <label className="zpa-field">
        <span className="zpa-mono">Name</span>
        <input value={name} maxLength={24} onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="zpa-preview" aria-live="off">
        <AssistantAvatar avatar={avatar} state={demoState} size="xl" />
        <div>
          <span className="zpa-mono">{STATE_LABEL[demoState]}</span>
          <b>{clean || "Your assistant"}</b>
        </div>
      </div>
      <div className="zpa-field">
        <span className="zpa-mono">Look</span>
        <div className="zpa-glyphs">
          {GLYPHS.map((g) => {
            const id = glyphAvatar(g.id);
            return (
              <button
                type="button"
                key={g.id}
                className="zpa-glyph"
                aria-pressed={avatar === id}
                title={g.note}
                onClick={() => setAvatar(id)}
              >
                <AssistantAvatar avatar={id} state={avatar === id ? demoState : "idle"} size="sm" />
                {g.label}
              </button>
            );
          })}
        </div>
        <div className="zpa-avs">
          {EMOJI_SKINS.map((a) => (
            <button type="button" key={a} className="zpa-av" aria-pressed={avatar === a} onClick={() => setAvatar(a)}>
              {a}
            </button>
          ))}
          <input
            className="zpa-av any"
            aria-label="Any emoji"
            placeholder="Any…"
            value={other}
            onChange={(e) => {
              const one = firstEmoji(e.target.value);
              setOther(one);
              if (one) setAvatar(one);
            }}
          />
        </div>
      </div>
      <div className="zpa-field">
        <span className="zpa-mono">How it talks</span>
        <div className="zpa-chips">
          {TONES.map((t) => (
            <button type="button" key={t.id} className="zpa-chip" aria-pressed={tone === t.id} onClick={() => setTone(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <button type="submit" className="zpa-keep" disabled={!clean}>
        Say hi to {clean || "your assistant"}
      </button>
      <span className="zpa-mono dim">Rename or change it any time from the card.</span>
    </form>
  );
}

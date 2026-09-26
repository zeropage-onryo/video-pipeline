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
   and the conversation follows the person from page to page. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ChevronDown, ChevronUp, ExternalLink, Settings2 } from "lucide-react";
import { useShell } from "@/components/studio/shell";
import {
  getBalance,
  queuePending,
  runCreativeGuide,
  waitForJob,
  type Balance,
  type Concept,
  type GuideReply,
} from "@/lib/studio-api";
import {
  AVATARS,
  COMPOSER_EVENT,
  STAGES,
  STAGE_LABEL,
  TONES,
  cleanName,
  firstEmoji,
  isStage,
  keepReferences,
  laterStage,
  loadPersona,
  pageName,
  pageStage,
  savePersona,
  sendToComposer,
  type ComposerState,
  type ContactSheet,
  type Persona,
  type Stage,
  type Tone,
} from "@/lib/assistant";
import "@/components/studio/assistant.css";
/* eslint-disable @next/next/no-img-element */

type Turn = {
  role: "user" | "assistant";
  content: string;
  failed?: boolean;
  /** an assistant turn's extras: chips, directions, the contact sheet */
  reply?: GuideReply;
  /** the contact sheet's frames as the person has them chosen (default: what the check kept) */
  chosen?: Record<string, boolean>;
  /** Keep has run for this sheet */
  kept?: boolean;
  /** the direction put in the composer */
  picked?: number;
  /** the pill's next-move line after a local step (a keep, a pick) */
  nudge?: string;
};

/* a sheet opens with the frames the check kept already chosen */
const chosenOf = (t: Turn): Record<string, boolean> => {
  if (t.chosen) return t.chosen;
  const sel: Record<string, boolean> = {};
  t.reply?.sheet?.sheet?.forEach((n) => n.keepers.forEach((k) => (sel[k.id] = true)));
  return sel;
};

const THREAD_KEY = "zpf.assistant.thread";
const GREETED_KEY = "zpf.assistant.greeted";

function loadThread(account: string): { turns: Turn[]; stage: Stage | "" } {
  try {
    const raw = sessionStorage.getItem(`${THREAD_KEY}.${account}`);
    if (raw) {
      const t = JSON.parse(raw) as { turns: Turn[]; stage: string };
      return { turns: t.turns ?? [], stage: isStage(t.stage) ? t.stage : "" };
    }
  } catch {
    /* a fresh start */
  }
  return { turns: [], stage: "" };
}

export function AssistantPill() {
  const pathname = usePathname() || "/studio";
  const { me, signedOut, brand, toast } = useShell();
  const account = brand || me?.account?.slug || "";
  const [persona, setPersona] = useState<Persona | null>(null);
  const [setup, setSetup] = useState(false);
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [convStage, setConvStage] = useState<Stage | "">("");
  // whose conversation `turns` is: saving must never write one account's
  // thread under the other's key in the render between a switch and its load
  const [turnsFor, setTurnsFor] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState("");
  const [bubble, setBubble] = useState("");
  const [composer, setComposer] = useState<ComposerState>({ idea: "", picked: [] });
  const bubbleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  // persona + thread are per account: two brands, two conversations
  useEffect(() => {
    if (!account) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after mount
    setPersona(loadPersona(account));
    const t = loadThread(account);
    setTurns(t.turns);
    setConvStage(t.stage);
    setTurnsFor(account);
  }, [account]);
  useEffect(() => {
    if (!account || turnsFor !== account) return;
    try {
      sessionStorage.setItem(`${THREAD_KEY}.${account}`, JSON.stringify({ turns: turns.slice(-24), stage: convStage }));
    } catch {
      /* the thread just forgets on reload */
    }
  }, [turns, convStage, account, turnsFor]);

  // what the composer holds, so a turn can see the idea and its picks
  useEffect(() => {
    const on = (e: Event) => setComposer((e as CustomEvent<ComposerState>).detail);
    window.addEventListener(COMPOSER_EVENT, on);
    return () => window.removeEventListener(COMPOSER_EVENT, on);
  }, []);

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
  }, [turns, busy, open]);

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
    try {
      const form = new FormData();
      form.append("conversation", JSON.stringify({ messages: next.map(({ role, content }) => ({ role, content })) }));
      if (account) form.append("brand", account);
      form.append("guide_provider", "gemini");
      form.append("idea", composer.idea.trim() || said);
      form.append("assistant", "1");
      form.append("assistant_name", persona.name);
      form.append("assistant_tone", persona.tone);
      form.append("stage", stage);
      form.append("page", pathname);
      form.append("brain", "auto");
      // the composer's picks ride along, so the turn sees what the box sees
      composer.picked.forEach((u) => form.append("asset_photos", u));
      const started = await runCreativeGuide(form);
      const job = await waitForJob(started.job_id, (j) => setDetail(j.detail || "Thinking…"));
      const reply = (job as unknown as { reply?: GuideReply }).reply;
      if (job.status !== "done" || !reply) throw new Error(job.error || `${persona.name} stopped.`);
      setTurns([...next, { role: "assistant", content: reply.message, reply }]);
      if (isStage(reply.stage)) setConvStage(reply.stage);
      if (!open && reply.nudge) say(reply.nudge);
    } catch (e) {
      setTurns([...next.slice(0, -1), { ...next[next.length - 1], failed: true }]);
      setText((now) => now || said);
      toast(e instanceof Error ? e.message : "That did not go through.", "err");
    } finally {
      setBusy(false);
      setDetail("");
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
    } catch (e) {
      toast(e instanceof Error ? e.message : "Those frames were not kept.", "err");
    } finally {
      setBusy(false);
      setDetail("");
    }
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

  const pillLine = !project
    ? "Start a project, or ask me anything"
    : pageAhead && pathname.startsWith("/studio/queue")
      ? "Ask me which render to start with"
      : pageAhead
        ? `On ${STAGE_LABEL[stage]} — ask me what's next`
        : nextMove || `On ${STAGE_LABEL[stage]}`;
  const avatar = persona?.avatar ?? "✦";
  const name = persona?.name ?? "Assistant";

  return (
    <div className={`zpa${open ? " open" : ""}`} data-page={where.toLowerCase()}>
      {open ? (
        <section className="zpa-card" aria-label={name} role="dialog">
          <span className="zpa-avatar big" aria-hidden>
            {avatar}
          </span>
          {setup || !persona ? (
            <Setup
              initial={persona}
              onDone={(p) => {
                savePersona(account, p);
                setPersona(p);
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
                {!turns.length ? (
                  <p className="zpa-msg">
                    {pathname.startsWith("/studio/queue")
                      ? "The Queue is where money is spent. Ask me which render to start with — approving stays your click."
                      : "Tell me what you want to make. I'll ask a couple of things, pitch directions, find references and put it all in your composer. Create and Approve stay your clicks."}
                  </p>
                ) : null}
                {turns.map((t, i) => (
                  <div key={i} className="zpa-turn">
                    <p className={`zpa-msg${t.role === "user" ? " me" : ""}${t.failed ? " failed" : ""}`}>
                      {t.content}
                      {t.failed ? <span className="zpa-failed">Not sent — press send to retry</span> : null}
                    </p>
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
                      />
                    ) : null}
                  </div>
                ))}
                {busy ? (
                  <p className="zpa-working" role="status">
                    <span className="zpa-dot" /> {detail || "Thinking…"}
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
        </section>
      ) : (
        <>
          <span className="zpa-perch">
            <span className="zpa-avatar" aria-hidden>
              {avatar}
            </span>
            {bubble ? (
              <span className="zpa-bubble" role="status">
                {bubble}
              </span>
            ) : null}
          </span>
          <button
            type="button"
            className="zpa-pill"
            aria-label={`Open ${name}`}
            onClick={() => {
              setBubble("");
              setOpen(true);
              setTimeout(() => input.current?.focus(), 50);
            }}
          >
            <span className="zpa-lines">
              <span className="zpa-mono">
                {name} · {project ? `Step ${step} of 7` : `on ${where}`}
              </span>
              <span className="zpa-nudge">{pillLine}</span>
            </span>
            <span className="zpa-go" aria-hidden>
              <ChevronUp strokeWidth={1.8} />
            </span>
          </button>
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
}) {
  const sheet = reply.sheet;
  const frames = useMemo(() => sheet?.sheet?.flatMap((n) => [...n.keepers, ...n.rejected]) ?? [], [sheet]);
  const count = frames.filter((f) => chosen[f.id]).length;
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
                <em>{typeof d.score === "number" ? `${Math.round(d.score * 10)}/10` : "not judged"}</em>
              </span>
              {picked === j ? <b>{d.title}</b> : null}
              <span className="zpa-log">{d.logline}</span>
              {d.verdict ? <span className="zpa-verdict">Judge: {d.verdict}</span> : null}
            </button>
          ))}
        </div>
      ) : null}

      {sheet ? (
        <div className="zpa-sheet">
          <span className="zpa-mono dim">{sheet.note}</span>
          {sheet.faces ? <span className="zpa-face">A face comes from your Elements (@name), never the web.</span> : null}
          {sheet.sheet.map((n, k) => {
            const all = [...n.keepers, ...n.rejected];
            return (
              <div key={k} className="zpa-need">
                <div className="zpa-needhead">
                  <span className="zpa-mono">
                    {n.role} · {n.query}
                  </span>
                  <span className="zpa-mono dim">
                    {n.keepers.length}/{all.length}
                  </span>
                </div>
                {all.length ? (
                  <div className="zpa-grid">
                    {all.map((f) => {
                      const rejected = n.rejected.includes(f);
                      const on = !!chosen[f.id];
                      return (
                        <span key={f.id} className="zpa-frame-wrap">
                          <button
                            type="button"
                            className={`zpa-frame${on ? " on" : ""}${rejected ? " rej" : ""}`}
                            aria-pressed={on}
                            disabled={kept}
                            title={`${f.title || f.source}${rejected ? ` — cut: ${f.why}` : f.kept_for ? ` — ${f.kept_for}` : ""}${rejected ? " · click to keep anyway" : ""}`}
                            onClick={() => onToggle(f.id)}
                          >
                            <img src={f.image_url} alt={f.title || "reference"} loading="lazy" referrerPolicy="no-referrer" />
                            <span className="zpa-tag">{rejected && !on ? `✕ ${f.why || "cut"}` : f.source}</span>
                          </button>
                          {f.source_url ? (
                            <a href={f.source_url} target="_blank" rel="noreferrer" className="zpa-src" aria-label={`Where ${f.title || "this frame"} came from`}>
                              <ExternalLink strokeWidth={1.8} />
                            </a>
                          ) : null}
                        </span>
                      );
                    })}
                  </div>
                ) : (
                  <span className="zpa-mono dim">{n.note || "nothing found"}</span>
                )}
              </div>
            );
          })}
          {frames.length ? (
            <button type="button" className="zpa-keep" disabled={busy || kept || !count} onClick={() => onKeep(sheet)}>
              {kept ? "Kept · on your composer" : `Keep ${count} · 0 cr`}
            </button>
          ) : null}
          {frames.length && !kept ? (
            <span className="zpa-mono dim">Kept frames go on the composer. {name} never presses Create.</span>
          ) : null}
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
  const [avatar, setAvatar] = useState(initial?.avatar ?? AVATARS[0]);
  const [other, setOther] = useState(initial && !AVATARS.includes(initial.avatar) ? initial.avatar : "");
  const [tone, setTone] = useState<Tone>(initial?.tone ?? "direct");
  const clean = cleanName(name);
  return (
    <form
      className="zpa-setup"
      onSubmit={(e) => {
        e.preventDefault();
        if (clean) onDone({ name: clean, avatar: avatar || AVATARS[0], tone });
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
      <div className="zpa-field">
        <span className="zpa-mono">Look</span>
        <div className="zpa-avs">
          {AVATARS.map((a) => (
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

"use client";

/* The agent (T19-T22), in invideo's place: the left panel.

   THE RULE (D4, and the same rule as spend): nothing the agent does
   touches the cut without your click. Every edit it wants arrives as a
   DIFF CARD -- what it does in one line, how much shorter or longer the
   cut gets, the region it touches highlighted on the timeline, a
   before/after you can play, and Keep / Undo. Keep saves ONE version
   authored "agent" (the server re-validates the ops against the head
   first); Undo is the card going away, because nothing was saved.

   Three sources of proposals, one card:
   - AGENT mode: a message to the model, which reads the timeline, may
     search the footage, and proposes ops the server has already validated.
   - CLEAN UP (T22): silences and filler words, found in the index's word
     timings by code -- no model call.
   - CAPTIONS FROM SPEECH: cues from the same word timings.
   The last two need the clips indexed; when they are not, the card offers
   to index them (cents a clip, metered) and re-runs itself once that lands.

   EDITOR mode is the command palette over the manual tools. */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AudioWaveform,
  Bot,
  Captions,
  Check,
  Eye,
  EyeOff,
  Loader2,
  ScanSearch,
  Sparkles,
  TerminalSquare,
  Undo2,
  Wand2,
} from "lucide-react";
import { useCut, type Turn } from "@/lib/cut/store";
import {
  askAgent,
  CutError,
  indexProject,
  keepProposal,
  proposeCaptions,
  proposeCleanup,
  type AgentReply,
  type Suggested,
} from "@/lib/cut/api";
import { getJob, type Job } from "@/lib/studio-api";
import { timecode } from "@/lib/cut/timeline";
import { COMMANDS, runCommand, type Command } from "@/components/cut/commands";

const st = () => useCut.getState();

async function waitJob(id: number): Promise<Job & Partial<AgentReply>> {
  for (;;) {
    await new Promise((r) => setTimeout(r, 1200));
    const j = (await getJob(id)) as Job & Partial<AgentReply>;
    if (["done", "failed", "cancelled"].includes(j.status)) return j;
  }
}

const signed = (frames: number, fps: number) => {
  const s = Math.abs(frames) / fps;
  const txt = `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
  return `${frames < 0 ? "−" : "+"}${txt}`;
};

/* ── the three ways a proposal is asked for ── */
export async function askTheAgent(message: string) {
  const s = st();
  if (!s.projectId) return;
  s.setLeftTab("agent");
  s.pushTurn({ role: "me", text: message });
  const turn = s.pushTurn({ role: "agent", text: "Reading the cut…", working: true });
  try {
    const { job_id } = await askAgent(s.projectId, {
      message,
      playhead: s.playhead,
      selection: s.selection.kind === "clip" ? s.selection.ids : undefined,
    });
    const j = await waitJob(job_id);
    if (j.status !== "done") throw new Error(j.error || j.detail || "the agent did not answer");
    st().updateTurn(turn, {
      working: false,
      text: j.reply || (j.proposal ? "Here is an edit." : "No edit."),
      proposal: j.proposal ?? null,
      status: j.proposal ? "pending" : undefined,
      notes: j.notes,
    });
  } catch (e) {
    st().updateTurn(turn, { working: false, text: e instanceof Error ? e.message : "the agent is unavailable" });
  }
}

export async function suggest(kind: "cleanup" | "captions") {
  const s = st();
  if (!s.projectId || !s.head) return;
  s.setLeftTab("agent");
  const label = kind === "cleanup" ? "Clean up: silences and filler words" : "Captions from speech";
  s.pushTurn({ role: "me", text: label });
  const turn = s.pushTurn({ role: "agent", text: "Reading the words…", working: true });
  try {
    const res: Suggested & { found?: { silences: number; fillers: number }; cues?: number } =
      kind === "cleanup"
        ? await proposeCleanup(s.projectId, { base_id: s.head.id })
        : await proposeCaptions(s.projectId, { base_id: s.head.id });
    const needs = res.needs_index ?? [];
    let text: string;
    if (res.proposal) text = res.proposal.summary;
    else if (needs.length && kind === "cleanup")
      text = "I can only hear clips that have been indexed — none of these have been yet.";
    else if (needs.length) text = "Captions come from the words in indexed clips — none of these have been indexed yet.";
    else if (kind === "cleanup") text = "Nothing to clean up — no long silences or filler words found.";
    else text = "No spoken words found in the sound on the timeline.";
    st().updateTurn(turn, {
      working: false,
      text,
      proposal: res.proposal,
      status: res.proposal ? "pending" : undefined,
      notes: res.notes,
      needsIndex: needs.length ? needs : undefined,
      retry: needs.length ? kind : undefined,
    });
  } catch (e) {
    st().updateTurn(turn, { working: false, text: e instanceof Error ? e.message : "that failed" });
  }
}

async function indexThenRetry(turn: Turn) {
  const s = st();
  if (!s.projectId) return;
  s.updateTurn(turn.id, { working: true, text: `Indexing ${turn.needsIndex?.length ?? 0} clip(s)…`, needsIndex: undefined });
  try {
    const { job_id } = await indexProject(s.projectId);
    const j = await waitJob(job_id);
    if (j.status !== "done") throw new Error(j.error || j.detail || "indexing failed");
    st().updateTurn(turn.id, { working: false, text: j.detail || "Indexed." });
    if (turn.retry) await suggest(turn.retry);
  } catch (e) {
    const msg = e instanceof CutError && e.code === "nothing_to_index" ? "Everything here is already indexed." : e instanceof Error ? e.message : "indexing failed";
    st().updateTurn(turn.id, { working: false, text: msg });
    if (e instanceof CutError && e.code === "nothing_to_index" && turn.retry) await suggest(turn.retry);
  }
}

async function keep(turn: Turn) {
  const s = st();
  const p = turn.proposal;
  if (!s.projectId || !p) return;
  s.preview(null);
  try {
    const res = await keepProposal(s.projectId, { base_id: p.base_id, ops: p.ops, summary: p.summary, kind: p.kind });
    useCut.setState((cur) => ({
      head: res.head,
      doc: res.head.doc,
      ghost: null,
      highlight: null,
      canUndo: res.can_undo,
      canRedo: res.can_redo,
      media: res.media ? { ...cur.media, ...res.media } : cur.media,
      versions: [res.head, ...cur.versions.filter((v) => v.id !== res.head.id)].sort((a, b) => b.version - a.version),
    }));
    st().updateTurn(turn.id, { status: "kept" });
    st().toast(`Kept · v${res.head.version}`);
  } catch (e) {
    const stale = e instanceof CutError && e.code === "stale";
    st().toast(
      stale
        ? "The cut changed since this was proposed — ask again"
        : e instanceof CutError && e.problems.length
          ? e.problems.slice(0, 2).join(" · ")
          : e instanceof Error
            ? e.message
            : "could not keep it",
      "err",
    );
  }
}

function undoTurn(turn: Turn) {
  const s = st();
  if (s.previewing === turn.id) s.preview(null);
  s.updateTurn(turn.id, { status: "undone" });
}

/* ── the panel ── */
const PROMPTS = [
  "Cut this down to 30 seconds",
  "Crossfade every cut, 8 frames",
  "Put a marker where each clip starts",
  "Trim the dead air at the head of each clip",
];

export function AgentPanel() {
  const [mode, setMode] = useState<"agent" | "editor">("agent");
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const thread = useCut((s) => s.thread);
  const busy = thread.some((t) => t.working);
  const bodyRef = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const matches = useMemo(() => {
    const q = text.trim().toLowerCase();
    if (!q) return COMMANDS;
    return COMMANDS.filter((c) => c.label.toLowerCase().includes(q) || c.words?.some((w) => w.includes(q)));
  }, [text]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [thread.length]);

  // leaving the panel ends a before/after preview
  useEffect(() => () => st().preview(null), []);

  const runPalette = (c: Command | undefined) => {
    if (!c) return;
    runCommand(c);
    setText("");
    setActive(0);
  };
  const send = () => {
    const m = text.trim();
    if (!m || busy) return;
    setText("");
    void askTheAgent(m);
  };

  return (
    <>
      <div className="cx-pane-body" ref={bodyRef}>
        {mode === "agent" ? (
          <>
            <div className="cx-chips">
              <button type="button" className="cx-chip" disabled={busy} onClick={() => void suggest("cleanup")}>
                <AudioWaveform /> Clean up
              </button>
              <button type="button" className="cx-chip" disabled={busy} onClick={() => void suggest("captions")}>
                <Captions /> Captions from speech
              </button>
              <button type="button" className="cx-chip" onClick={() => st().setLeftTab("search")}>
                <ScanSearch /> Find a moment
              </button>
            </div>
            {!thread.length ? (
              <div className="cx-card" style={{ marginTop: 10 }}>
                <p className="cx-h" style={{ marginBottom: 6 }}>
                  <Sparkles size={12} style={{ verticalAlign: -1, marginRight: 6 }} />
                  Your assistant editor
                </p>
                <p className="cx-note">
                  Ask for an edit in plain words. It reads the timeline, can search your footage, and proposes real cuts
                  you can play before you keep them. Nothing changes until you press Keep.
                </p>
                <div className="cx-thread" style={{ gap: 4, marginTop: 10 }}>
                  {PROMPTS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      className="cx-btn ghost"
                      style={{ justifyContent: "flex-start", height: "auto", minHeight: 28, padding: "5px 9px", textAlign: "left" }}
                      onClick={() => {
                        setText(p);
                        input.current?.focus();
                      }}
                    >
                      <Wand2 /> {p}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="cx-thread" style={{ marginTop: 10 }}>
              {thread.map((t) => (t.role === "me" ? <p key={t.id} className="cx-msg me">{t.text}</p> : <AgentTurn key={t.id} turn={t} />))}
            </div>
          </>
        ) : (
          <>
            <p className="cx-note">Type a tool — split, marker, caption, fit — and press Enter.</p>
            <div className="cx-palette" role="listbox">
              {matches.map((c, i) => (
                <button
                  key={c.id}
                  type="button"
                  role="option"
                  aria-selected={i === active}
                  data-active={i === active}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => runPalette(c)}
                >
                  <c.icon />
                  {c.label}
                  {c.keys ? <kbd>{c.keys}</kbd> : null}
                </button>
              ))}
              {!matches.length ? <p className="cx-note">No tool by that name.</p> : null}
            </div>
          </>
        )}
      </div>
      <div className="cx-composer">
        <textarea
          ref={input}
          value={text}
          placeholder={mode === "agent" ? "Tell the editor what to change…" : "Split, marker, add caption, zoom to fit…"}
          onChange={(e) => {
            setText(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Escape") {
              setText("");
              input.current?.blur();
              return;
            }
            if (mode === "agent") {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
              return;
            }
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(matches.length - 1, a + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(0, a - 1));
            } else if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              runPalette(matches[active]);
            }
          }}
        />
        <div className="cx-composer-row">
          <span className="cx-seg">
            <button type="button" aria-pressed={mode === "agent"} onClick={() => setMode("agent")}>
              <Bot size={11} style={{ verticalAlign: -1, marginRight: 4 }} />
              Agent
            </button>
            <button type="button" aria-pressed={mode === "editor"} onClick={() => setMode("editor")}>
              <TerminalSquare size={11} style={{ verticalAlign: -1, marginRight: 4 }} />
              Editor
            </button>
          </span>
          <span className="spacer" />
          {mode === "agent" ? (
            <button type="button" className="cx-go" disabled={!text.trim() || busy} onClick={send}>
              {busy ? <Loader2 className="animate-spin" /> : <Sparkles />} Ask
            </button>
          ) : (
            <span className="cx-label">⏎ run</span>
          )}
        </div>
      </div>
    </>
  );
}

function AgentTurn({ turn }: { turn: Turn }) {
  const head = useCut((s) => s.head);
  const fps = useCut((s) => s.doc?.fps ?? 30);
  const previewing = useCut((s) => s.previewing === turn.id);
  const [openOps, setOpenOps] = useState(false);
  const p = turn.proposal;
  // a note the reply already says is not said twice
  const notes = (turn.notes ?? []).filter((n) => !turn.text.toLowerCase().includes(n.toLowerCase()));

  if (turn.working) {
    return (
      <p className="cx-msg">
        <Loader2 size={12} className="animate-spin" style={{ verticalAlign: -2, marginRight: 6 }} />
        {turn.text}
      </p>
    );
  }
  if (!p) {
    return (
      <div className="cx-msg">
        {turn.text}
        {notes.length ? (
          <ul className="cx-note" style={{ margin: "6px 0 0", paddingLeft: 16 }}>
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ) : null}
        {turn.needsIndex?.length ? (
          <div className="cx-diff-actions">
            <button type="button" className="cx-go" onClick={() => void indexThenRetry(turn)}>
              <ScanSearch /> Index {turn.needsIndex.length} clip{turn.needsIndex.length === 1 ? "" : "s"} (≈ a cent each)
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  const stale = !!head && p.base_id !== head.id && turn.status === "pending";
  return (
    <div
      className="cx-diff"
      data-status={turn.status}
      onMouseEnter={() => turn.status === "pending" && !stale && st().setHighlight(p.region)}
      onMouseLeave={() => !previewing && st().setHighlight(null)}
    >
      {turn.text && turn.text !== p.summary ? <p className="cx-note" style={{ color: "var(--text)", marginBottom: 8 }}>{turn.text}</p> : null}
      <p className="cx-h" style={{ textTransform: "none", letterSpacing: "0.02em", fontSize: 13 }}>
        {p.summary}
        {p.duration_delta && !/[−-]\d|\+\d/.test(p.summary) ? (
          <span className="cx-label" style={{ marginLeft: 8, color: p.duration_delta < 0 ? "#6fcf97" : "var(--dim)" }}>
            {signed(p.duration_delta, fps)}
          </span>
        ) : null}
      </p>
      <p className="cx-label" style={{ marginTop: 4 }}>
        {p.ops.length} edit{p.ops.length === 1 ? "" : "s"}
        {p.region ? ` · ${timecode(p.region.from, fps)}–${timecode(p.region.to, fps)}` : ""} ·{" "}
        <button type="button" className="cx-link" onClick={() => setOpenOps((o) => !o)}>
          {openOps ? "hide" : "show"}
        </button>
      </p>
      {openOps ? (
        <ol className="cx-oplist">
          {p.ops.map((o, i) => (
            <li key={i}>
              <b>{o.op}</b> {Object.entries(o.args).map(([k, v]) => `${k}=${typeof v === "object" ? "…" : String(v)}`).join(" ")}
            </li>
          ))}
        </ol>
      ) : null}
      {turn.status === "pending" ? (
        stale ? (
          <p className="cx-note" style={{ marginTop: 8 }}>
            The cut has changed since this was proposed. Ask again to get an edit of the cut as it is now.
          </p>
        ) : (
          <div className="cx-diff-actions">
            <button type="button" className="cx-go" onClick={() => void keep(turn)}>
              <Check /> Keep
            </button>
            <button type="button" className="cx-btn ghost" onClick={() => undoTurn(turn)}>
              <Undo2 /> Undo
            </button>
            <span className="spacer" />
            <button
              type="button"
              className="cx-btn ghost"
              aria-pressed={previewing}
              title={previewing ? "Back to the cut as it is" : "Play the cut with this edit"}
              onClick={() => st().preview(previewing ? null : turn.id)}
            >
              {previewing ? <EyeOff /> : <Eye />} {previewing ? "Before" : "After"}
            </button>
          </div>
        )
      ) : (
        <p className="cx-label" style={{ marginTop: 8, color: turn.status === "kept" ? "#6fcf97" : "var(--dimmer)" }}>
          {turn.status === "kept" ? "Kept" : "Undone — nothing was changed"}
        </p>
      )}
    </div>
  );
}
